"""Algo Signal Analyst: wraps two team-contributed packages that were built
as a pair (vendored, unmodified):

- backend/algo_agent/: trains a fresh dependency-free logistic-regression
  model on this session's intraday bars each tick, validates it out-of-
  sample, and emits a BUY/SELL/HOLD recommendation with trade geometry.
- backend/critic_agent/: a standalone schema/consistency/policy reviewer
  built specifically to critique algo_agent's recommendation shape (trade
  geometry sanity, model evidence strength, internal consistency).

This is new capability, not a replacement for any existing analyst - closest
fit to the architecture's mandatory "Time-Series / DL Forecasting" tool
category (our own forecasting.py is a simple linear trend; this is an actual
trained, validated, and critic-reviewed classifier).

We do NOT treat their real-money policy gate as a hard veto by itself - its
liquidity/volatility thresholds are calibrated for daily-bar swing trading,
not a 4-6h intraday session on 5-min bars. Instead the critic's overall
verdict (PASS/CAUTION/REJECT, which itself folds in the policy gate plus
model-evidence and consistency checks) is used as a confidence discount, and
REJECT downgrades the action to WAIT.
"""

from __future__ import annotations

import pandas as pd

from algo_agent.agent import recommend
from algo_agent.data import PriceBar
from algo_agent.policy import TradePolicy
from app.agents.base import AgentVote, AnalysisContext, BaseAgent, prior_stage_summary
from app.config import get_settings
from app.llm.client import get_llm_client
from critic_agent.critic import review_recommendation

_MIN_BARS = 90  # headroom above the package's own 60-labeled-row training minimum
_CRITIC_FACTOR = {"PASS": 1.0, "CAUTION": 0.6, "REJECT": 0.25}


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


def _skill_factor(accuracy: float, baseline: float) -> float:
    """Discount confidence when the model shows little/no edge over predicting
    the majority class out-of-sample - a "confident" 55% probability is not
    meaningful if the model can't beat a coin flip on recent validation data."""
    edge = accuracy - baseline
    return max(0.2, min(1.0, 0.35 + edge * 3.5))


class AlgoSignalAnalyst(BaseAgent):
    name = "Algo Signal Analyst"
    agent_type = "analyst"
    expertise = "technical"

    def vote(self, ctx: AnalysisContext) -> AgentVote:
        bars = _to_price_bars(ctx.bars)
        if len(bars) < _MIN_BARS:
            return AgentVote(
                agent_name=self.name, agent_type=self.agent_type, action="WAIT", confidence=0.15,
                reasoning=f"Not enough intraday bars yet to train a reliable model for {ctx.symbol}.",
                evidence=["Insufficient bar history for model training this tick."], metrics={},
            )

        settings = get_settings()
        policy = TradePolicy(capital=settings.starting_capital_inr, max_position_pct=50.0)
        try:
            rec = recommend(bars, symbol=ctx.symbol, horizon=5, policy=policy)
        except ValueError as exc:
            return AgentVote(
                agent_name=self.name, agent_type=self.agent_type, action="WAIT", confidence=0.15,
                reasoning=f"Model training skipped for {ctx.symbol}: {exc}", evidence=[str(exc)], metrics={},
            )

        critique = review_recommendation(rec.to_dict())

        skill = _skill_factor(rec.model_metrics.accuracy, rec.model_metrics.baseline_accuracy)
        critic_factor = _CRITIC_FACTOR.get(critique.verdict, 0.5)
        action = "WAIT" if critique.verdict == "REJECT" else rec.action
        confidence = round(max(0.15, min(0.9, rec.confidence * skill * critic_factor)), 3)

        edge = rec.model_metrics.accuracy - rec.model_metrics.baseline_accuracy
        evidence = list(rec.rationale)
        evidence.append(
            f"Out-of-sample validation accuracy {rec.model_metrics.accuracy:.0%} vs baseline "
            f"{rec.model_metrics.baseline_accuracy:.0%} (edge {edge:+.0%}, n={rec.model_metrics.samples})."
        )
        evidence.append(f"[Critic Agent] {critique.verdict} (score {critique.score}/100) - {critique.summary}")
        top_findings = sorted(critique.findings, key=lambda f: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(f.severity, 4))
        for finding in top_findings[:2]:
            evidence.append(f"[Critic finding: {finding.severity}] {finding.message}")

        metrics = {
            "model_probability_up": rec.model_probability_up,
            "validation_accuracy": rec.model_metrics.accuracy,
            "baseline_accuracy": rec.model_metrics.baseline_accuracy,
            "validation_edge": round(edge, 4),
            "validation_samples": rec.model_metrics.samples,
            "review_status": rec.review_status,
            "top_features": rec.top_features,
            "critic_verdict": critique.verdict,
            "critic_score": critique.score,
        }

        llm = get_llm_client()
        evidence_txt = " ".join(evidence)
        context_txt = prior_stage_summary(ctx)
        reasoning = llm.chat(
            system=(
                "You are the Algo Signal Analyst on a trading committee - the final automated stage after the macro/"
                "sentiment/geopolitical backdrop and the fundamental/technical/risk drill-down have already run. A "
                "freshly-trained logistic regression model on this session's intraday bars, validated out-of-sample "
                "and reviewed by a dedicated critic agent. Summarize the signal in 2-3 crisp sentences, being honest "
                "about whether the model actually beats a naive baseline, whether the critic flagged concerns, and "
                "whether this automated signal agrees with the rest of the committee's earlier read."
            ),
            user=f"Symbol {ctx.symbol}. Signal: {action} (confidence {confidence}). Evidence: {evidence_txt}\n\n{context_txt}",
            fallback=f"Algo signal for {ctx.symbol}: {action}. {evidence_txt}",
        )

        return AgentVote(
            agent_name=self.name, agent_type=self.agent_type, action=action, confidence=confidence,
            reasoning=reasoning, evidence=evidence, metrics=metrics,
        )
