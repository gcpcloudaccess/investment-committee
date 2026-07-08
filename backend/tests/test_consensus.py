"""Unit tests for the mandatory trust-weighted consensus algorithm.
Pure synthetic votes, no DB / no LLM / no network required."""

from app.agents.base import AgentVote
from app.consensus.trust_weighted_consensus import compute_consensus


def _vote(agent_name, action, confidence):
    return AgentVote(agent_name=agent_name, agent_type="analyst", action=action, confidence=confidence, reasoning="synthetic", evidence=[], metrics={})


def test_low_reliability_high_confidence_is_downweighted():
    """An agent with a poor track record but a loud (high-confidence) vote should
    NOT dominate the outcome the way plain confidence-averaging would let it."""
    votes = [
        _vote("Technical Analyst", "BUY", 0.95),   # loud, but unreliable
        _vote("Fundamental Analyst", "SELL", 0.55),  # quieter, but reliable
        _vote("Risk Assessment Analyst", "SELL", 0.5),
    ]
    trust_scores = {
        "Technical Analyst": 0.15,       # poor track record
        "Fundamental Analyst": 0.9,      # strong track record
        "Risk Assessment Analyst": 0.85,
    }

    result = compute_consensus(votes, trust_scores)

    # Plain confidence averaging would hand this to BUY (0.95 > 0.55/0.5 individually).
    # Trust-weighting should flip it toward SELL because the loud BUY voter is unreliable.
    assert result.winning_action == "SELL"


def test_not_equivalent_to_plain_averaging():
    """Two committees with identical raw confidences but different trust histories
    must produce different directional confidence scores - proves the math isn't
    just averaging confidences."""
    votes = [_vote("Technical Analyst", "BUY", 0.7), _vote("Sentiment Analyst", "BUY", 0.7)]

    high_trust = compute_consensus(votes, {"Technical Analyst": 0.9, "Sentiment Analyst": 0.9})
    low_trust = compute_consensus(votes, {"Technical Analyst": 0.2, "Sentiment Analyst": 0.2})

    assert high_trust.directional_confidence != low_trust.directional_confidence


def test_agreement_adjustment_rewards_reliable_contrarian():
    """An agent that disagrees with the room but has a strong track record should
    carry more influence per unit of raw confidence than a mirror-agent that just
    agrees with everyone (redundant signal) - matches the slide's Agent A/B example."""
    contrarian = _vote("Risk Assessment Analyst", "SELL", 0.6)
    crowd = [
        _vote("Technical Analyst", "BUY", 0.6),
        _vote("Sentiment Analyst", "BUY", 0.6),
        _vote("Fundamental Analyst", "BUY", 0.6),
    ]
    trust_scores = {
        "Risk Assessment Analyst": 0.9,
        "Technical Analyst": 0.9,
        "Sentiment Analyst": 0.9,
        "Fundamental Analyst": 0.9,
    }

    result = compute_consensus([contrarian, *crowd], trust_scores)
    contrarian_detail = next(d for d in result.agent_details if d["agent_name"] == "Risk Assessment Analyst")
    agreeing_detail = next(d for d in result.agent_details if d["agent_name"] == "Technical Analyst")

    # same raw confidence (0.6) and same trust (0.9), but contrarian's agreement_adjustment
    # must exceed the crowd-agreeing agent's, since it disagreed with the majority.
    assert contrarian_detail["agreement_adjustment"] > agreeing_detail["agreement_adjustment"]


def test_wait_on_low_conviction():
    votes = [
        _vote("Technical Analyst", "BUY", 0.3),
        _vote("Sentiment Analyst", "SELL", 0.3),
        _vote("Fundamental Analyst", "HOLD", 0.3),
    ]
    trust_scores = {"Technical Analyst": 0.5, "Sentiment Analyst": 0.5, "Fundamental Analyst": 0.5}

    result = compute_consensus(votes, trust_scores)
    assert result.verdict == "WAIT"


def test_strong_fresh_consensus_can_still_clear_decisive_threshold():
    """Regression guard: a brand-new system where every agent still sits at the
    neutral trust prior (0.5, no closed trades yet to update it) must still be
    ABLE to place a first trade when the room is genuinely unanimous and
    confident. If neutral trust silently discounted conviction, the system
    could never clear the decisive threshold on day one - a permanent
    WAIT-only deadlock, since trust only updates from trade outcomes that can
    never happen without an initial trade."""
    votes = [
        _vote("Technical Analyst", "BUY", 0.85),
        _vote("Sentiment Analyst", "BUY", 0.8),
        _vote("Algo Signal Analyst", "BUY", 0.8),
        _vote("Risk Assessment Analyst", "BUY", 0.75),
    ]
    trust_scores = {name: 0.5 for name in ("Technical Analyst", "Sentiment Analyst", "Algo Signal Analyst", "Risk Assessment Analyst")}

    result = compute_consensus(votes, trust_scores)
    assert result.verdict == "BUY"
    assert result.directional_confidence >= 50.0
