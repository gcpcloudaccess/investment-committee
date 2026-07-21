"""Astrological Analyst: reads current planetary positions (own pure-Python
low-precision ephemeris, app/tools/planetary_positions.py - no external
service, no API key) and applies traditional Vedic ("financial astrology")
planet-asset correspondences to Nifty/gold/silver (app/tools/astro_signals.py).

This is explicitly NOT an empirically validated signal - it's included
because it was requested as a feature, not because planetary positions have
a demonstrated causal link to market prices. Two things keep it from
distorting the committee's real decisions: its own confidence is capped low
(see astro_signals.CONFIDENCE_CEILING) and its expertise_relevance in the
trust-weighted consensus is set low (app/consensus/trust_weighted_consensus.py)
so it can only ever nudge the verdict, never drive it. Every reasoning output
carries an explicit disclaimer for the same reason."""

from __future__ import annotations

from app.agents.base import AgentVote, AnalysisContext, BaseAgent
from app.llm.client import get_llm_client
from app.tools import astro_signals


class AstroAnalyst(BaseAgent):
    name = "Astrological Analyst"
    agent_type = "analyst"
    expertise = "astrology"

    def vote(self, ctx: AnalysisContext) -> AgentVote:
        signal = astro_signals.analyze(ctx.symbol)

        llm = get_llm_client()
        evidence_txt = " ".join(signal["evidence"])
        reasoning = llm.chat(
            system=(
                "You are the Astrological Analyst on a trading committee, applying traditional Vedic "
                "(Jyotish) financial-astrology heuristics - planetary positions, retrograde status, lunar "
                "phase/nakshatra - to the symbol's classical planetary ruler. This is folklore, not an "
                "empirically validated model: always make that explicit, keep the tone measured rather than "
                "mystical, and summarize the placements and their traditional interpretation in 2-3 crisp "
                "sentences, grounded only in the evidence given."
            ),
            user=f"Symbol {ctx.symbol}. Signal: {signal['action']} (confidence {signal['confidence']}). Evidence: {evidence_txt}",
            fallback=f"Astrological (Vedic) read for {ctx.symbol}: {signal['action']}. {evidence_txt}",
        )

        return AgentVote(
            agent_name=self.name,
            agent_type=self.agent_type,
            action=signal["action"],
            confidence=signal["confidence"],
            reasoning=reasoning,
            evidence=signal["evidence"],
            metrics=signal["metrics"],
        )
