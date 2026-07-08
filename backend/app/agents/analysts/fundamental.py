"""Fundamental Analyst: blends the team-contributed statement-based quality
model (vendored, unmodified, backend/fundamental_analyst_agent.py - revenue
growth/quality, balance sheet strength, profitability, cash conversion,
dilution/capital allocation, each with its own confidence and missing-data
penalty) with our peer-relative momentum signal (sector_intelligence.py).

The team model expects real income statement / balance sheet / cash flow
figures (see app/data/fundamentals.get_financial_statements) rather than the
simpler .info-derived ratios our original fundamental_scoring.py tool used.
When statements aren't available for a symbol (yfinance coverage varies),
this falls back to that lighter PE/growth/margin model instead of guessing."""

from app.agents.base import AgentVote, AnalysisContext, BaseAgent, blend_signals, prior_stage_summary
from app.llm.client import get_llm_client
from app.tools import fundamental_scoring, sector_intelligence
from fundamental_analyst_agent import analyze as analyze_statements

_FINAL_VIEW_ACTION = {
    "Fundamentally Excellent": "BUY",
    "Fundamentally Strong": "BUY",
    "Fundamentally Mixed": "HOLD",
    "Fundamentally Weak": "SELL",
    "Financially Distressed": "SELL",
    "Insufficient Data": "WAIT",
}


def _team_signal(financial_statements: dict) -> dict | None:
    if not financial_statements or not financial_statements.get("income_statement", {}).get("revenue"):
        return None

    result = analyze_statements(financial_statements)
    composite = result["composite_fundamental_quality_score"]
    conf_score = result["overall_confidence_score"]
    action = _FINAL_VIEW_ACTION.get(result["final_view"], "HOLD")

    strength = abs(composite - 50) / 50
    confidence = round(max(0.15, min(0.92, (conf_score / 100) * (0.4 + 0.6 * strength))), 3)

    evidence = [f"{result['final_view']} (quality {composite:.0f}/100, data confidence {conf_score:.0f}/100)."]
    evidence.extend(f"Strength: {s}" for s in result["top_strengths"][:2])
    evidence.extend(f"Concern: {c}" for c in result["top_concerns"][:2])
    for r in result["risk_flags"][:2]:
        evidence.append(f"[{r['severity']} risk] {r['risk']}: {r['evidence']}")

    return {
        "action": action,
        "confidence": confidence,
        "evidence": evidence,
        "metrics": {
            "composite_quality_score": composite,
            "confidence_score": conf_score,
            "final_view": result["final_view"],
            "category_scores": {c["category"]: c["score"] for c in result["category_scores"]},
        },
    }


class FundamentalAnalyst(BaseAgent):
    name = "Fundamental Analyst"
    agent_type = "analyst"
    expertise = "fundamental"

    def vote(self, ctx: AnalysisContext) -> AgentVote:
        sector = sector_intelligence.analyze(ctx.symbol, ctx.bars, ctx.peer_bars)
        team = _team_signal(ctx.financial_statements)

        if team is not None:
            combined = blend_signals([team, sector], [0.75, 0.25])
        else:
            fund = fundamental_scoring.analyze(ctx.fundamentals)
            combined = blend_signals([fund, sector], [0.7, 0.3])
            combined["evidence"].append("Full financial statements unavailable this tick; used lighter valuation model.")

        llm = get_llm_client()
        evidence_txt = " ".join(combined["evidence"])
        context_txt = prior_stage_summary(ctx)
        reasoning = llm.chat(
            system="You are a fundamental analyst on a trading committee, drilling into company-specific fundamentals "
            "after the macro/sentiment/geopolitical backdrop has already been assessed. Summarize the valuation/quality "
            "case in 2-3 crisp sentences, noting briefly if it reinforces or conflicts with that backdrop.",
            user=f"Symbol {ctx.symbol}. Signal: {combined['action']} (confidence {combined['confidence']}). Evidence: {evidence_txt}\n\n{context_txt}",
            fallback=f"Fundamental read for {ctx.symbol}: {combined['action']}. {evidence_txt}",
        )

        return AgentVote(
            agent_name=self.name,
            agent_type=self.agent_type,
            action=combined["action"],
            confidence=combined["confidence"],
            reasoning=reasoning,
            evidence=combined["evidence"],
            metrics=combined["metrics"],
        )
