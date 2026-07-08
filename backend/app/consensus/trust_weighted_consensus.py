"""Directional Confidence-Aware Consensus — the mandatory core algorithm.

Explicitly NOT simple majority voting and NOT plain confidence averaging.
Each agent's influence on the final verdict is a product of several
independently-varying factors, recomputed fresh every tick:

    weight_i = base_confidence_i
             * expertise_relevance_i(context)      # how relevant this agent's
                                                     # domain is to an intraday call
             * trust_score_i                        # persisted, Beta-updated
                                                     # historical reliability/trust
             * agreement_adjustment_i(this tick)     # penalizes redundant agreement,
                                                       # rewards contrarian-but-reliable votes

`agreement_adjustment` is what implements the slide's worked example: an agent
that always agrees with the room contributes little new information and is
discounted, while an agent that disagrees with the room but has a strong track
record is amplified — the opposite of what majority voting or plain averaging
would do.

This module is pure Python / no I/O / no LLM calls, so the math is unit
testable with synthetic votes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agents.base import AgentVote

ACTIONS = ("BUY", "SELL", "HOLD", "WAIT", "SWITCH")

# How relevant each agent's domain is to a same-day intraday call (0-1).
# Technical/sentiment/risk dominate; slower-moving fundamentals/macro still
# contribute but are down-weighted for a 4-6h horizon.
EXPERTISE_RELEVANCE: dict[str, float] = {
    "Technical Analyst": 1.0,
    "Algo Signal Analyst": 0.85,
    "Sentiment Analyst": 0.9,
    "Risk Assessment Analyst": 0.9,
    "Risk Critic": 0.9,
    "Profit Critic": 0.85,
    "Debate Agent": 0.75,
    "Opportunity Critic": 0.8,
    "Geopolitical Analyst": 0.55,
    "Government Policy Analyst": 0.55,
    "Macroeconomic Analyst": 0.5,
    "Macro Critic": 0.5,
    "Fundamental Analyst": 0.45,
}
DEFAULT_EXPERTISE_RELEVANCE = 0.5

REDUNDANCY_FACTOR = 0.3   # discount for agreeing with the room
DISAGREEMENT_BONUS = 0.5  # amplification for disagreeing while historically reliable
AGREEMENT_ADJ_MIN = 0.4
AGREEMENT_ADJ_MAX = 1.6

# Verdict thresholds on the winning action's directional confidence share (0-100).
# Calibrated against real multi-agent committee runs (not guessed): with 13
# intentionally-diverse agents (8 analysts + debate + 4 critics), several
# agents structurally default to HOLD as their "no strong objection" answer
# under ambiguous evidence (e.g. the risk model returns HOLD for anything
# above LOW risk). That makes HOLD win the plurality by sheer vote count even
# when its individual backers are only lukewarm, while genuine BUY/SELL
# conviction from 1-2 strongly-confident agents gets diluted below it.
# Empirically, real BUY/SELL-leaning pluralities in this system's live runs
# cap out around 20-25% directional confidence, not 40-50% - so a 30%
# decisive bar (already lowered once from an initial 50%) still left the
# system unable to ever trade in practice. Lowered further so a genuine,
# above-noise directional lean can actually execute instead of always losing
# to HOLD's vote-count advantage. This is a deliberate trade-off toward
# trading more actively; it does not require near-consensus the way the
# original thresholds effectively did.
DECISIVE_THRESHOLD = 18.0
LOW_CONVICTION_THRESHOLD = 10.0


@dataclass
class ConsensusResult:
    verdict: str
    directional_confidence: float  # 0-100, share of trust-weighted influence behind the winning action
    winning_action: str
    action_weight_totals: dict[str, float]
    agent_weights: dict[str, float] = field(default_factory=dict)
    agent_details: list[dict] = field(default_factory=list)


def _same_tick_agreement(vote: AgentVote, all_votes: list[AgentVote]) -> float:
    others = [v for v in all_votes if v.agent_name != vote.agent_name]
    if not others:
        return 0.0
    agree = sum(1 for v in others if v.action == vote.action)
    return agree / len(others)


def _agreement_adjustment(vote: AgentVote, all_votes: list[AgentVote], trust_score: float) -> float:
    agreement = _same_tick_agreement(vote, all_votes)
    adj = 1.0 - REDUNDANCY_FACTOR * agreement + DISAGREEMENT_BONUS * (1.0 - agreement) * trust_score
    return max(AGREEMENT_ADJ_MIN, min(AGREEMENT_ADJ_MAX, adj))


def _trust_multiplier(trust: float) -> float:
    """Maps trust (0-1) to a conviction multiplier centered on 1.0x at the
    neutral 0.5 prior, so an untested agent's confidence isn't penalized
    before it has any track record - only proven reliability/unreliability
    should push conviction up or down from the neutral baseline."""
    return 0.75 + 0.5 * trust


def compute_consensus(votes: list[AgentVote], trust_scores: dict[str, float]) -> ConsensusResult:
    """
    votes: all analyst + critic votes cast this tick for one symbol.
    trust_scores: agent_name -> persisted historical reliability/trust (0-1).
        Callers should supply a sane prior (e.g. 0.5) for agents with no history yet.
    """
    if not votes:
        return ConsensusResult(verdict="WAIT", directional_confidence=0.0, winning_action="WAIT", action_weight_totals={})

    action_totals = {a: 0.0 for a in ACTIONS}
    agent_weights: dict[str, float] = {}
    agent_details: list[dict] = []

    for vote in votes:
        trust = trust_scores.get(vote.agent_name, 0.5)
        relevance = EXPERTISE_RELEVANCE.get(vote.agent_name, DEFAULT_EXPERTISE_RELEVANCE)
        agreement_adj = _agreement_adjustment(vote, votes, trust)

        weight = vote.confidence * relevance * trust * agreement_adj
        action_totals[vote.action] = action_totals.get(vote.action, 0.0) + weight
        agent_weights[vote.agent_name] = weight
        agent_details.append(
            {
                "agent_name": vote.agent_name,
                "action": vote.action,
                "confidence": vote.confidence,
                "trust_score": round(trust, 3),
                "expertise_relevance": relevance,
                "agreement_adjustment": round(agreement_adj, 3),
                "weight": round(weight, 4),
            }
        )

    total_weight = sum(action_totals.values()) or 1e-9
    winning_action = max(action_totals, key=action_totals.get)

    # Directional confidence blends two independent things: how *dominant* the
    # winning action is versus the rest of the room (share of trust-weighted
    # influence), and how *convinced* the agents backing it actually are (their
    # own confidence, modulated by trust around a neutral baseline). Using
    # dominance alone would report 100% confidence any time the committee is
    # unanimous, even if every backer is low-confidence - not meaningful.
    #
    # Trust modulates conviction rather than multiplying it directly: an agent
    # with no track record yet sits at the neutral prior (trust=0.5), which
    # must NOT discount its confidence, or the system could never place a
    # first trade at all - trust already starts at 0.5 for every agent and
    # only moves once a trade closes, so a raw confidence*trust term creates a
    # permanent ceiling (share * 0.5 at best) that can never clear a 50%
    # decisive threshold. Proven-reliable agents (trust -> 1) get a conviction
    # boost; proven-unreliable ones (trust -> 0) get a real penalty.
    share = action_totals[winning_action] / total_weight
    backers = [v for v in votes if v.action == winning_action]
    avg_conviction = sum(v.confidence * _trust_multiplier(trust_scores.get(v.agent_name, 0.5)) for v in backers) / len(backers)
    directional_confidence = round(max(0.0, min(100.0, 100.0 * share * avg_conviction)), 2)

    if directional_confidence < LOW_CONVICTION_THRESHOLD:
        verdict = "WAIT"
    elif winning_action in ("BUY", "SELL", "SWITCH") and directional_confidence >= DECISIVE_THRESHOLD:
        verdict = winning_action
    else:
        verdict = "HOLD" if winning_action not in ("WAIT",) else "WAIT"

    return ConsensusResult(
        verdict=verdict,
        directional_confidence=directional_confidence,
        winning_action=winning_action,
        action_weight_totals={k: round(v, 4) for k, v in action_totals.items()},
        agent_weights=agent_weights,
        agent_details=agent_details,
    )
