from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Literal


class Verdict(str, Enum):
    SUPPORT_CURRENT = "support_current"
    CHALLENGE_CURRENT = "challenge_current"
    ESCALATE_TO_DEBATE = "escalate_to_debate"


Rating = Literal["weak", "mixed", "strong"]


@dataclass(frozen=True)
class Evidence:
    source: str
    claim: str
    rating: Rating = "mixed"


@dataclass(frozen=True)
class InvestmentCandidate:
    ticker: str
    name: str
    expected_return: float
    downside_risk: float
    conviction: float
    liquidity_score: float
    catalyst_score: float
    valuation_score: float
    evidence: tuple[Evidence, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class CurrentProposal:
    action: Literal["buy", "sell", "hold", "trim", "add"]
    candidate: InvestmentCandidate
    thesis: str


@dataclass(frozen=True)
class OpportunityCriticConfig:
    min_improvement_to_challenge: float = 0.08
    min_improvement_to_escalate: float = 0.16
    min_alternative_confidence: float = 0.55
    return_weight: float = 0.32
    risk_weight: float = 0.24
    conviction_weight: float = 0.18
    liquidity_weight: float = 0.08
    catalyst_weight: float = 0.10
    valuation_weight: float = 0.08


@dataclass(frozen=True)
class CandidateScore:
    candidate: InvestmentCandidate
    score: float
    opportunity_gap_vs_current: float
    confidence: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Critique:
    verdict: Verdict
    current_score: CandidateScore
    alternatives: tuple[CandidateScore, ...]
    recommended_alternative: CandidateScore | None
    committee_message: str
    questions_for_debate: tuple[str, ...] = field(default_factory=tuple)


class OpportunityCriticAgent:
    """
    Searches for better opportunities than the committee's current proposal.

    This agent is intentionally adversarial but evidence-bound: it should not
    reject the current idea just because another asset looks interesting. It
    challenges only when the alternative clears a configurable opportunity gap.
    """

    def __init__(self, config: OpportunityCriticConfig | None = None) -> None:
        self.config = config or OpportunityCriticConfig()

    def critique(
        self,
        proposal: CurrentProposal,
        alternatives: Iterable[InvestmentCandidate],
    ) -> Critique:
        current_score = self._score_candidate(proposal.candidate, proposal.candidate)
        scored_alternatives = tuple(
            sorted(
                (
                    self._score_candidate(candidate, proposal.candidate)
                    for candidate in alternatives
                    if candidate.ticker != proposal.candidate.ticker
                ),
                key=lambda item: item.score,
                reverse=True,
            )
        )
        viable = [
            item
            for item in scored_alternatives
            if item.confidence >= self.config.min_alternative_confidence
        ]
        best = viable[0] if viable else None
        verdict = self._verdict(best)
        return Critique(
            verdict=verdict,
            current_score=current_score,
            alternatives=scored_alternatives,
            recommended_alternative=best,
            committee_message=self._committee_message(proposal, best, verdict),
            questions_for_debate=self._questions_for_debate(proposal, best, verdict),
        )

    def _score_candidate(
        self,
        candidate: InvestmentCandidate,
        current: InvestmentCandidate,
    ) -> CandidateScore:
        cfg = self.config
        score = (
            cfg.return_weight * candidate.expected_return
            - cfg.risk_weight * candidate.downside_risk
            + cfg.conviction_weight * candidate.conviction
            + cfg.liquidity_weight * candidate.liquidity_score
            + cfg.catalyst_weight * candidate.catalyst_score
            + cfg.valuation_weight * candidate.valuation_score
        )
        current_score = (
            cfg.return_weight * current.expected_return
            - cfg.risk_weight * current.downside_risk
            + cfg.conviction_weight * current.conviction
            + cfg.liquidity_weight * current.liquidity_score
            + cfg.catalyst_weight * current.catalyst_score
            + cfg.valuation_weight * current.valuation_score
        )
        confidence = self._confidence(candidate)
        return CandidateScore(
            candidate=candidate,
            score=round(score, 4),
            opportunity_gap_vs_current=round(score - current_score, 4),
            confidence=confidence,
            reasons=self._reasons(candidate, current),
        )

    def _confidence(self, candidate: InvestmentCandidate) -> float:
        if not candidate.evidence:
            return round(candidate.conviction * 0.5, 4)
        evidence_quality = {
            "weak": 0.35,
            "mixed": 0.65,
            "strong": 0.9,
        }
        avg_evidence = sum(evidence_quality[item.rating] for item in candidate.evidence)
        avg_evidence /= len(candidate.evidence)
        return round((0.55 * candidate.conviction) + (0.45 * avg_evidence), 4)

    def _reasons(
        self,
        candidate: InvestmentCandidate,
        current: InvestmentCandidate,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if candidate.expected_return > current.expected_return:
            delta = candidate.expected_return - current.expected_return
            reasons.append(f"higher expected return by {delta:.1%}")
        if candidate.downside_risk < current.downside_risk:
            delta = current.downside_risk - candidate.downside_risk
            reasons.append(f"lower downside risk by {delta:.1%}")
        if candidate.catalyst_score > current.catalyst_score:
            reasons.append("stronger near-term catalyst profile")
        if candidate.valuation_score > current.valuation_score:
            reasons.append("more attractive valuation setup")
        if candidate.conviction > current.conviction:
            reasons.append("higher analyst conviction")
        if not reasons:
            reasons.append("no decisive edge over the current proposal")
        return tuple(reasons)

    def _verdict(self, best: CandidateScore | None) -> Verdict:
        if best is None:
            return Verdict.SUPPORT_CURRENT
        gap = best.opportunity_gap_vs_current
        if gap >= self.config.min_improvement_to_escalate:
            return Verdict.ESCALATE_TO_DEBATE
        if gap >= self.config.min_improvement_to_challenge:
            return Verdict.CHALLENGE_CURRENT
        return Verdict.SUPPORT_CURRENT

    def _committee_message(
        self,
        proposal: CurrentProposal,
        best: CandidateScore | None,
        verdict: Verdict,
    ) -> str:
        current = proposal.candidate
        if best is None or verdict == Verdict.SUPPORT_CURRENT:
            return (
                f"Opportunity Critic supports the current {proposal.action.upper()} "
                f"proposal on {current.ticker}. No screened alternative clears the "
                "minimum evidence-adjusted opportunity gap."
            )
        candidate = best.candidate
        reasons = "; ".join(best.reasons)
        return (
            f"Opportunity Critic challenges the current {proposal.action.upper()} "
            f"proposal on {current.ticker}. {candidate.ticker} ({candidate.name}) "
            f"shows an opportunity gap of {best.opportunity_gap_vs_current:.1%} "
            f"with {best.confidence:.1%} confidence: {reasons}."
        )

    def _questions_for_debate(
        self,
        proposal: CurrentProposal,
        best: CandidateScore | None,
        verdict: Verdict,
    ) -> tuple[str, ...]:
        if best is None or verdict == Verdict.SUPPORT_CURRENT:
            return (
                f"What evidence would invalidate the current {proposal.candidate.ticker} thesis?",
                "Are there unscreened assets with superior risk-adjusted return?",
            )
        alternative = best.candidate
        return (
            f"Why should capital stay with {proposal.candidate.ticker} instead of {alternative.ticker}?",
            f"Is {alternative.ticker}'s catalyst durable or already priced in?",
            "Does the alternative improve portfolio diversification after transaction costs?",
        )
