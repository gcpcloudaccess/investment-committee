"""Debate Agent: sits between the analysts and the critics. Its job is to
surface the strongest contradicting views among the 7 analyst votes and
produce a synthesized read of how contested the picture actually is -
matching the architecture diagram's "Debate Agent: Agents debate
contradicting views" box in the Debate & Consensus layer.

Unlike the critics (which challenge specific domains: risk, profit, macro,
opportunity), the Debate Agent is domain-agnostic - it looks at the *shape*
of disagreement across all analysts and casts its own vote into the
trust-weighted consensus: confident when the room is lopsided, deliberately
low-confidence when the strongest bull and bear cases are evenly matched.
"""

from __future__ import annotations

from app.agents.base import AgentVote, AnalysisContext, BaseAgent, historical_context_summary
from app.llm.client import get_llm_client


class DebateAgent(BaseAgent):
    name = "Debate Agent"
    agent_type = "debate"
    expertise = "synthesis"

    def vote(self, ctx: AnalysisContext, analyst_votes: list[AgentVote]) -> AgentVote:
        action_totals: dict[str, float] = {}
        for v in analyst_votes:
            action_totals[v.action] = action_totals.get(v.action, 0.0) + v.confidence

        ranked = sorted(action_totals.items(), key=lambda kv: kv[1], reverse=True)
        winning_action, winning_total = ranked[0]
        runner_up_action, runner_up_total = ranked[1] if len(ranked) > 1 else (None, 0.0)

        contest_ratio = (runner_up_total / winning_total) if winning_total else 0.0
        confidence = round(max(0.15, min(0.9, 1.0 - contest_ratio)), 3)

        pro_side = sorted((v for v in analyst_votes if v.action == winning_action), key=lambda v: v.confidence, reverse=True)
        con_side = sorted((v for v in analyst_votes if v.action == runner_up_action), key=lambda v: v.confidence, reverse=True) if runner_up_action else []

        if con_side:
            pro_lead = pro_side[0]
            con_lead = con_side[0]
            contention = (
                f"Strongest case for {winning_action} comes from {pro_lead.agent_name} "
                f"(confidence {pro_lead.confidence:.2f}: {'; '.join(pro_lead.evidence[:1]) or pro_lead.reasoning[:100]}). "
                f"Strongest counter-case for {runner_up_action} comes from {con_lead.agent_name} "
                f"(confidence {con_lead.confidence:.2f}: {'; '.join(con_lead.evidence[:1]) or con_lead.reasoning[:100]})."
            )
        else:
            contention = f"No material dissent this tick - all analyst signal weight is concentrated on {winning_action}."

        history_note = historical_context_summary(ctx)
        user_prompt = f"Symbol {ctx.symbol}. {contention}"
        if history_note:
            user_prompt += f"\n\n{history_note}"

        llm = get_llm_client()
        reasoning = llm.chat(
            system=(
                "You are the Debate Agent on an investment committee. Given the strongest bull case and the "
                "strongest counter-case among the analysts, write a short (3-4 sentence) dialectic: state each "
                "side fairly, then say plainly how contested the picture is and why. Do not declare a winner - "
                "that is the consensus engine's job, not yours. If past committee decisions for this symbol are "
                "provided, weigh them - a pattern of similar setups losing money is itself evidence worth naming."
            ),
            user=user_prompt,
            fallback=contention,
        )

        evidence = [contention] + ([history_note] if history_note else [])
        return AgentVote(
            agent_name=self.name,
            agent_type=self.agent_type,
            action=winning_action,
            confidence=confidence,
            reasoning=reasoning,
            evidence=evidence,
            metrics={
                "contest_ratio": round(contest_ratio, 3),
                "winning_action": winning_action,
                "runner_up_action": runner_up_action,
                "action_totals": {k: round(v, 3) for k, v in action_totals.items()},
            },
        )
