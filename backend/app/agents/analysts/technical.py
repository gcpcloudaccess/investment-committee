"""Technical Analyst: blends our own fast intraday (5-min bar) RSI/MACD/volume
read with a team-contributed daily-chart trend overlay (vendored, unmodified,
under backend/technical_analyst_agent/ - RSI/EMA-stack/MACD/volume scored on
daily bars, requiring 80+ daily bars for EMA200 to warm up).

Like the risk agent integration, the two signals are kept in separate metric
namespaces (`metrics["daily_trend"]`) rather than flat-merged, since several
of the team model's field names (e.g. macd_histogram) collide with our own
intraday metric names but are on a completely different timeframe/scale.
"""

from __future__ import annotations

import pandas as pd

from app.agents.base import AgentVote, AnalysisContext, BaseAgent, blend_signals, prior_stage_summary
from app.llm.client import get_llm_client
from app.tools import forecasting, technical_indicators
from technical_analyst_agent import PriceBar, TechnicalAnalystAgent

_TEAM_AGENT = TechnicalAnalystAgent(name="Technical Analyst (daily trend)")
_MIN_DAILY_BARS = 80
_INTRADAY_WEIGHT = 0.6
_DAILY_WEIGHT = 0.4


def _to_price_bars(bars: pd.DataFrame | None) -> list[PriceBar]:
    if bars is None or bars.empty:
        return []
    out: list[PriceBar] = []
    for idx, row in bars.iterrows():
        try:
            out.append(
                PriceBar(
                    date=str(idx),
                    open=float(row["Open"]), high=float(row["High"]), low=float(row["Low"]),
                    close=float(row["Close"]), volume=float(row.get("Volume", 0.0) or 0.0),
                )
            )
        except (KeyError, ValueError, TypeError):
            continue
    return out


class TechnicalAnalyst(BaseAgent):
    name = "Technical Analyst"
    agent_type = "analyst"
    expertise = "technical"

    def vote(self, ctx: AnalysisContext) -> AgentVote:
        tech = technical_indicators.analyze(ctx.bars)
        forecast = forecasting.forecast_next(ctx.bars)
        intraday = blend_signals([tech, forecast], [0.65, 0.35])

        daily_result = self._run_daily_trend(ctx)

        if daily_result is not None:
            action_totals = {intraday["action"]: intraday["confidence"] * _INTRADAY_WEIGHT}
            daily_conf = daily_result.confidence_score / 100.0
            action_totals[daily_result.action] = action_totals.get(daily_result.action, 0.0) + daily_conf * _DAILY_WEIGHT

            action = max(action_totals, key=action_totals.get)
            confidence = round(min(0.95, max(0.15, action_totals[action])), 3)

            evidence = list(intraday["evidence"])
            evidence.append(
                f"[Daily trend] {daily_result.label} (directional {daily_result.directional_score:.0f}/100, "
                f"confidence {daily_result.confidence_score:.0f}/100)."
            )
            if daily_result.risk_flags:
                evidence.append(f"[Daily trend risk] {daily_result.risk_flags[0]}")

            metrics = dict(intraday["metrics"])
            metrics["daily_trend"] = {
                "action": daily_result.action,
                "directional_score": daily_result.directional_score,
                "confidence_score": daily_result.confidence_score,
                "conviction_score": daily_result.conviction_score,
                "label": daily_result.label,
            }
        else:
            action = intraday["action"]
            confidence = intraday["confidence"]
            evidence = [*intraday["evidence"], "Daily trend overlay skipped this tick (insufficient daily history)."]
            metrics = dict(intraday["metrics"])

        llm = get_llm_client()
        evidence_txt = " ".join(evidence)
        context_txt = prior_stage_summary(ctx)
        reasoning = llm.chat(
            system=(
                "You are a technical analyst on a trading committee, drilling into price action after the macro/"
                "sentiment/geopolitical backdrop has already been assessed. Blending a fast intraday indicator read "
                "with a daily-chart trend overlay, summarize the technical case in 2-3 crisp sentences, noting "
                "whether the intraday and daily-trend reads agree or conflict."
            ),
            user=f"Symbol {ctx.symbol}. Signal: {action} (confidence {confidence}). Evidence: {evidence_txt}\n\n{context_txt}",
            fallback=f"Technical read for {ctx.symbol}: {action}. {evidence_txt}",
        )

        return AgentVote(
            agent_name=self.name,
            agent_type=self.agent_type,
            action=action,
            confidence=confidence,
            reasoning=reasoning,
            evidence=evidence,
            metrics=metrics,
        )

    def _run_daily_trend(self, ctx: AnalysisContext):
        daily_bars = _to_price_bars(ctx.daily_bars)
        if len(daily_bars) < _MIN_DAILY_BARS:
            return None
        try:
            return _TEAM_AGENT.analyze(daily_bars, symbol=ctx.symbol)
        except ValueError:
            return None
