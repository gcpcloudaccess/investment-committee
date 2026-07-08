"""Report Generation Agent: turns the structured consensus/vote data into the
natural-language "why" every trade (and no-trade) must carry."""

from __future__ import annotations

from app.agents.base import AgentVote
from app.consensus.trust_weighted_consensus import ConsensusResult
from app.llm.client import get_llm_client


def _fallback_reasoning(symbol: str, consensus: ConsensusResult, votes: list[AgentVote]) -> str:
    top = sorted(consensus.agent_details, key=lambda d: d["weight"], reverse=True)[:3]
    top_txt = "; ".join(f"{d['agent_name']} ({d['action']}, weight {d['weight']:.2f})" for d in top)
    return (
        f"Consensus verdict for {symbol}: {consensus.verdict} with {consensus.directional_confidence:.1f}% "
        f"directional confidence, driven mainly by {top_txt}. Weighting accounts for each agent's confidence, "
        f"domain relevance to an intraday call, historical reliability, and whether it agreed or diverged from "
        f"the rest of the committee this tick."
    )


def build_consensus_reasoning(symbol: str, consensus: ConsensusResult, votes: list[AgentVote], history_note: str = "") -> str:
    llm = get_llm_client()
    fallback = _fallback_reasoning(symbol, consensus, votes)

    votes_digest = "\n".join(f"- {v.agent_name} ({v.agent_type}): {v.action} @ {v.confidence:.2f} confidence — {v.reasoning}" for v in votes)
    weights_digest = "\n".join(f"- {d['agent_name']}: trust-weight {d['weight']:.3f} (trust={d['trust_score']}, relevance={d['expertise_relevance']}, agreement_adj={d['agreement_adjustment']})" for d in consensus.agent_details)

    user_prompt = (
        f"Symbol: {symbol}\nFinal verdict: {consensus.verdict} ({consensus.directional_confidence:.1f}% directional confidence)\n\n"
        f"Agent votes:\n{votes_digest}\n\nTrust-weighted influence:\n{weights_digest}"
    )
    if history_note:
        user_prompt += f"\n\n{history_note}"

    reasoning = llm.chat(
        system=(
            "You are the Report Generation Agent for an autonomous trading committee. Write a concise (3-5 sentence) "
            "explanation of why the committee reached this verdict. Explain the directional confidence score in terms "
            "of which agents drove it and why (their trust/expertise weighting, and whether they agreed or "
            "contrarily diverged from the room). Do not just restate the vote list - synthesize the reasoning. If "
            "past committee decisions for this symbol are provided, explicitly reference what happened last time "
            "a similar call was made."
        ),
        user=user_prompt,
        max_tokens=400,
        fallback=fallback,
    )
    return reasoning
