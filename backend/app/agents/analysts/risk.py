"""Risk Assessment Analyst: blends our own fast per-bar volatility read with
the team-contributed comprehensive quantitative risk model (vendored,
unmodified, under backend/risk_agent/ - beta, Sharpe/Sortino, VaR/CVaR,
liquidity, concentration, sector exposure, market regime, sentiment/macro
risk, plus a critic-style report and its own persisted decision memory).

The two signals are kept in separate metric namespaces rather than naively
merged: `metrics["volatility"]`/`risk_level` stay in OUR per-bar scale because
position_sizing.py and scenario_analysis.py consume them expecting that
scale - the team model's (annualized) numbers live under `metrics["advanced"]`
so nothing downstream silently breaks on unit mismatch.
"""

from __future__ import annotations

import pandas as pd

from app.agents.base import AgentVote, AnalysisContext, BaseAgent, prior_stage_summary
from app.data.market_data import CACHE_DIR
from app.llm.client import get_llm_client
from app.tools import risk_model, sentiment_engine
from risk_agent import OHLCVBar, PortfolioPosition, RiskAssessmentAgent, RiskAssessmentInput
from risk_agent.memory import DecisionMemory

_MEMORY = DecisionMemory(storage_path=CACHE_DIR / "risk_agent_memory.json")
_TEAM_AGENT = RiskAssessmentAgent(memory=_MEMORY)

_LEVEL_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "EXTREME": 3}
_OWN_WEIGHT = 0.4
_TEAM_WEIGHT = 0.6


def _to_ohlcv_bars(bars: pd.DataFrame | None) -> list[OHLCVBar]:
    if bars is None or bars.empty:
        return []
    out: list[OHLCVBar] = []
    for idx, row in bars.iterrows():
        try:
            out.append(
                OHLCVBar(
                    date=str(idx),
                    open=float(row["Open"]), high=float(row["High"]), low=float(row["Low"]),
                    close=float(row["Close"]), volume=float(row.get("Volume", 0.0) or 0.0),
                )
            )
        except (KeyError, ValueError, TypeError):
            continue
    return out


def _combine_level(a: str, b: str) -> str:
    return a if _LEVEL_RANK.get(a, 1) >= _LEVEL_RANK.get(b, 1) else b


class RiskAnalyst(BaseAgent):
    name = "Risk Assessment Analyst"
    agent_type = "analyst"
    expertise = "risk"

    def vote(self, ctx: AnalysisContext) -> AgentVote:
        own_signal = risk_model.analyze(ctx.bars)
        team_result = self._run_team_agent(ctx)

        action_totals: dict[str, float] = {own_signal["action"]: own_signal["confidence"] * _OWN_WEIGHT}
        evidence = list(own_signal["evidence"])
        metrics = dict(own_signal["metrics"])

        if team_result is not None:
            rec = team_result.recommendation
            team_conf = team_result.directional_confidence.to_dict()[rec.lower()]
            action_totals[rec] = action_totals.get(rec, 0.0) + team_conf * _TEAM_WEIGHT

            metrics["risk_level"] = _combine_level(
                metrics.get("risk_level", "MEDIUM"),
                "HIGH" if team_result.risk_level == "EXTREME" else team_result.risk_level,
            )
            metrics["advanced"] = {
                **team_result.metrics.to_dict(),
                "risk_score": team_result.risk_score,
                "risk_level": team_result.risk_level,
                "consensus_payload": team_result.consensus_payload,
            }

            m = team_result.metrics
            evidence.append(
                f"[Quant risk model] score {team_result.risk_score}/100 ({team_result.risk_level}), "
                f"beta {m.beta:.2f}, Sharpe {m.sharpe_ratio:.2f}, Sortino {m.sortino_ratio:.2f}, "
                f"CVaR95 {m.cvar_95*100:.1f}%, max drawdown {m.max_drawdown*100:.1f}%."
            )
            evidence.extend(f"[Risk critic] {t}" for t in team_result.top_risks[:2])
            if team_result.rejection_conditions:
                evidence.append(f"[Rejection condition] {team_result.rejection_conditions[0]}")
        else:
            evidence.append("Quantitative risk model skipped this tick (insufficient benchmark/price history).")

        action = max(action_totals, key=action_totals.get)
        confidence = round(min(0.95, max(0.15, action_totals[action])), 3)

        llm = get_llm_client()
        evidence_txt = " ".join(evidence)
        context_txt = prior_stage_summary(ctx)
        reasoning = llm.chat(
            system=(
                "You are the Risk Assessment Analyst on a trading committee, drilling into company/position-specific "
                "risk after the macro/sentiment/geopolitical backdrop has already been assessed. Combining a fast "
                "intraday volatility read with a comprehensive quantitative risk model (beta, Sharpe/Sortino, VaR/"
                "CVaR, liquidity, concentration, sector exposure, market regime), summarize the risk case in 2-3 "
                "crisp sentences."
            ),
            user=f"Symbol {ctx.symbol}. Signal: {action} (confidence {confidence}). Evidence: {evidence_txt}\n\n{context_txt}",
            fallback=f"Risk read for {ctx.symbol}: {action}. {evidence_txt}",
        )

        return AgentVote(
            agent_name=self.name, agent_type=self.agent_type, action=action, confidence=confidence,
            reasoning=reasoning, evidence=evidence, metrics=metrics,
        )

    def _run_team_agent(self, ctx: AnalysisContext):
        # Deliberately uses daily bars, not the 5-min intraday ctx.bars: the team model
        # annualizes assuming ~252 trading-day observations (volatility, Sharpe/Sortino,
        # market regime lookback) - feeding it intraday bars would silently understate
        # every risk figure it produces.
        price_bars = _to_ohlcv_bars(ctx.daily_bars)
        benchmark_bars = _to_ohlcv_bars(ctx.benchmark_bars)
        if len(price_bars) < 3 or len(benchmark_bars) < 3:
            return None

        try:
            portfolio = [PortfolioPosition(**p) for p in ctx.open_positions]
        except TypeError:
            portfolio = []

        news_scores = [
            sentiment_engine.score_headline(f"{n.get('title', '')}. {n.get('summary', '')}") for n in ctx.symbol_news
        ]
        news_sentiment = {"news": sum(news_scores) / len(news_scores)} if news_scores else {}

        request = RiskAssessmentInput(
            symbol=ctx.symbol, price_data=price_bars, benchmark_data=benchmark_bars,
            portfolio=portfolio, news_sentiment=news_sentiment, macro_indicators={}, risk_free_rate=0.07,
        )
        try:
            return _TEAM_AGENT.assess(request, store_decision=True)
        except ValueError:
            return None
