"""
Profit Critic Agent

Standalone, dependency-free agent for the "Dynamic Debate & Critic Loop" shown in
the autonomous multi-agent investment committee diagram.

This module is educational infrastructure, not financial advice. Wire it into a
larger investment workflow as a critic that challenges proposed trades before
they reach a consensus or execution agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Verdict(str, Enum):
    SUPPORT = "support"
    CHALLENGE = "challenge"
    REJECT = "reject"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class TradeProposal:
    symbol: str
    action: str
    entry_price: float
    target_price: float
    stop_loss: Optional[float]
    holding_days: int
    position_size_pct: float
    thesis: str
    expected_win_probability: Optional[float] = None
    expected_drawdown_pct: Optional[float] = None
    fees_bps: float = 10.0
    slippage_bps: float = 10.0
    alternative_symbols: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class MarketContext:
    sector_trend_score: float
    technical_score: float
    fundamental_score: float
    sentiment_score: float
    liquidity_score: float
    macro_risk_score: float
    risk_agent_verdict: Optional[str] = None
    consensus_confidence: Optional[float] = None
    evidence: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProfitCritique:
    verdict: Verdict
    score: float
    expected_return_pct: float
    reward_to_risk: Optional[float]
    cost_drag_pct: float
    opportunity_cost_flags: List[str]
    evidence_used: List[str]
    objections: List[str]
    required_followups: List[str]
    recommendation: str
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": "profit_critic",
            "verdict": self.verdict.value,
            "score": round(self.score, 2),
            "confidence": round(self.confidence, 2),
            "expected_return_pct": round(self.expected_return_pct, 2),
            "reward_to_risk": None
            if self.reward_to_risk is None
            else round(self.reward_to_risk, 2),
            "cost_drag_pct": round(self.cost_drag_pct, 2),
            "opportunity_cost_flags": self.opportunity_cost_flags,
            "evidence_used": self.evidence_used,
            "objections": self.objections,
            "required_followups": self.required_followups,
            "recommendation": self.recommendation,
        }


class ProfitCriticAgent:
    """
    Critiques profit potential before a trade reaches the consensus engine.

    The agent is intentionally skeptical. It does not select trades by itself;
    it asks whether the proposed trade has enough profit quality to deserve
    committee attention after transaction costs, downside, alternatives, and
    evidence quality are considered.
    """

    def __init__(
        self,
        min_expected_return_pct: float = 4.0,
        min_reward_to_risk: float = 1.8,
        min_score_to_support: float = 70.0,
        min_score_to_escalate: float = 55.0,
    ) -> None:
        self.min_expected_return_pct = min_expected_return_pct
        self.min_reward_to_risk = min_reward_to_risk
        self.min_score_to_support = min_score_to_support
        self.min_score_to_escalate = min_score_to_escalate

    def critique(
        self,
        proposal: TradeProposal,
        context: MarketContext,
        peer_agent_notes: Optional[Dict[str, str]] = None,
    ) -> ProfitCritique:
        expected_return_pct = self._expected_return_pct(proposal)
        downside_pct = self._downside_pct(proposal)
        reward_to_risk = (
            None if downside_pct <= 0 else expected_return_pct / downside_pct
        )
        cost_drag_pct = (proposal.fees_bps + proposal.slippage_bps) / 100.0

        objections: List[str] = []
        followups: List[str] = []
        opportunity_flags: List[str] = []

        if expected_return_pct < self.min_expected_return_pct:
            objections.append(
                "Expected return is too small for committee attention after costs."
            )

        if reward_to_risk is None:
            followups.append("Provide a stop loss or explicit downside estimate.")
        elif reward_to_risk < self.min_reward_to_risk:
            objections.append("Reward-to-risk is below the profit hurdle.")

        if proposal.expected_win_probability is not None:
            if proposal.expected_win_probability < 0.52:
                objections.append("Win probability does not justify the trade thesis.")
        else:
            followups.append("Estimate win probability from historical setups.")

        if proposal.expected_drawdown_pct is not None and proposal.expected_drawdown_pct > 12:
            objections.append("Expected drawdown is high relative to profit target.")

        if context.liquidity_score < 45:
            objections.append("Liquidity may erase expected profit through execution drag.")

        if context.technical_score < 50 and context.fundamental_score < 50:
            objections.append("Technical and fundamental support are both weak.")

        if context.sentiment_score < 40:
            objections.append("Sentiment is weak enough to question timing.")

        if context.macro_risk_score > 70:
            objections.append("Macro risk is high and may compress upside.")

        if proposal.alternative_symbols:
            opportunity_flags.append(
                "Compare expected return against alternatives: "
                + ", ".join(proposal.alternative_symbols)
            )
        else:
            followups.append("Ask opportunity critic for at least two comparable alternatives.")

        if peer_agent_notes:
            for agent_name, note in peer_agent_notes.items():
                if any(term in note.lower() for term in ["weak", "avoid", "overvalued", "risk"]):
                    objections.append(f"{agent_name} raised a negative signal: {note}")

        score = self._score(
            expected_return_pct=expected_return_pct,
            reward_to_risk=reward_to_risk,
            context=context,
            cost_drag_pct=cost_drag_pct,
            objections_count=len(objections),
            followups_count=len(followups),
        )
        verdict = self._verdict(score, objections, followups)
        confidence = self._confidence(context, proposal, reward_to_risk)
        recommendation = self._recommendation(verdict, proposal, objections, followups)

        return ProfitCritique(
            verdict=verdict,
            score=score,
            expected_return_pct=expected_return_pct,
            reward_to_risk=reward_to_risk,
            cost_drag_pct=cost_drag_pct,
            opportunity_cost_flags=opportunity_flags,
            evidence_used=context.evidence,
            objections=objections,
            required_followups=followups,
            recommendation=recommendation,
            confidence=confidence,
        )

    def build_llm_prompt(
        self,
        proposal: TradeProposal,
        context: MarketContext,
        peer_agent_notes: Optional[Dict[str, str]] = None,
    ) -> str:
        peer_notes = peer_agent_notes or {}
        return f"""
You are the Profit Critic Agent inside an autonomous multi-agent investment committee.
Your role is to challenge profit quality before a proposal reaches directional consensus.

Critique only the profit case. Do not act as the final investment committee.

Evaluate:
- Expected return after brokerage, taxes, fees, and slippage.
- Reward-to-risk versus the stop loss or expected drawdown.
- Probability-weighted upside and whether the setup deserves capital.
- Opportunity cost versus better comparable stocks.
- Whether peer agents provide enough evidence for a profit-positive trade.
- Whether the trade should be supported, challenged, rejected, or escalated.

Trade proposal:
{proposal}

Market context:
{context}

Peer agent notes:
{peer_notes}

Return strict JSON with:
agent, verdict, score, confidence, expected_return_pct, reward_to_risk,
cost_drag_pct, opportunity_cost_flags, evidence_used, objections,
required_followups, recommendation.
""".strip()

    def _expected_return_pct(self, proposal: TradeProposal) -> float:
        if proposal.action.lower() in {"sell", "short"}:
            gross = (proposal.entry_price - proposal.target_price) / proposal.entry_price
        else:
            gross = (proposal.target_price - proposal.entry_price) / proposal.entry_price
        cost_drag = (proposal.fees_bps + proposal.slippage_bps) / 10000.0
        return (gross - cost_drag) * 100.0

    def _downside_pct(self, proposal: TradeProposal) -> float:
        if proposal.stop_loss is not None:
            if proposal.action.lower() in {"sell", "short"}:
                return max(0.0, (proposal.stop_loss - proposal.entry_price) / proposal.entry_price * 100.0)
            return max(0.0, (proposal.entry_price - proposal.stop_loss) / proposal.entry_price * 100.0)
        return proposal.expected_drawdown_pct or 0.0

    def _score(
        self,
        expected_return_pct: float,
        reward_to_risk: Optional[float],
        context: MarketContext,
        cost_drag_pct: float,
        objections_count: int,
        followups_count: int,
    ) -> float:
        return_score = min(25.0, max(0.0, expected_return_pct / 12.0 * 25.0))
        rr_score = 0.0 if reward_to_risk is None else min(20.0, reward_to_risk / 3.0 * 20.0)
        evidence_score = (
            context.technical_score * 0.18
            + context.fundamental_score * 0.18
            + context.sentiment_score * 0.10
            + context.sector_trend_score * 0.12
            + context.liquidity_score * 0.12
            + (100.0 - context.macro_risk_score) * 0.10
        )
        penalty = objections_count * 7.0 + followups_count * 3.5 + cost_drag_pct * 1.5
        return max(0.0, min(100.0, return_score + rr_score + evidence_score - penalty))

    def _verdict(
        self,
        score: float,
        objections: List[str],
        followups: List[str],
    ) -> Verdict:
        if score >= self.min_score_to_support and len(objections) <= 1:
            return Verdict.SUPPORT
        if score >= self.min_score_to_escalate:
            return Verdict.CHALLENGE
        if followups and score >= 45.0:
            return Verdict.ESCALATE
        return Verdict.REJECT

    def _confidence(
        self,
        context: MarketContext,
        proposal: TradeProposal,
        reward_to_risk: Optional[float],
    ) -> float:
        completeness = 0.4
        completeness += 0.15 if proposal.stop_loss is not None else 0.0
        completeness += 0.15 if proposal.expected_win_probability is not None else 0.0
        completeness += 0.10 if proposal.expected_drawdown_pct is not None else 0.0
        completeness += 0.10 if reward_to_risk is not None else 0.0
        completeness += min(0.10, len(context.evidence) * 0.025)
        if context.consensus_confidence is not None:
            completeness = (completeness + context.consensus_confidence / 100.0) / 2.0
        return max(0.0, min(1.0, completeness))

    def _recommendation(
        self,
        verdict: Verdict,
        proposal: TradeProposal,
        objections: List[str],
        followups: List[str],
    ) -> str:
        if verdict == Verdict.SUPPORT:
            return f"Support {proposal.action.upper()} {proposal.symbol}, subject to final consensus weighting."
        if verdict == Verdict.CHALLENGE:
            return "Challenge the proposal and require stronger profit evidence before execution."
        if verdict == Verdict.ESCALATE:
            return "Escalate to opportunity and risk critics for missing evidence: " + "; ".join(followups)
        return "Reject or defer the proposal. Main blockers: " + "; ".join(objections or followups)


if __name__ == "__main__":
    agent = ProfitCriticAgent()
    sample_proposal = TradeProposal(
        symbol="NEXA",
        action="buy",
        entry_price=100.0,
        target_price=112.0,
        stop_loss=94.0,
        holding_days=20,
        position_size_pct=8.0,
        thesis="Clean-energy momentum with improving fundamentals.",
        expected_win_probability=0.58,
        expected_drawdown_pct=6.0,
        alternative_symbols=["TATAPOWER", "ADANIGREEN"],
    )
    sample_context = MarketContext(
        sector_trend_score=76,
        technical_score=72,
        fundamental_score=68,
        sentiment_score=61,
        liquidity_score=80,
        macro_risk_score=42,
        consensus_confidence=78,
        evidence=[
            "News sentiment positive for clean energy.",
            "Technical breakout confirmed by volume.",
            "Fundamental revenue growth improving.",
        ],
    )
    critique = agent.critique(sample_proposal, sample_context)
    print(critique.to_dict())
