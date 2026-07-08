"""Macroeconomic Analyst: blends our existing macro-tagged news sentiment
read with the team-contributed regime model (vendored, unmodified,
backend/macroeconomist_agent.py - turns GDP growth/inflation/policy-rate
observations into growth/inflation/policy regime labels with explainable,
recency-and-source-quality-weighted confidence).

That model explicitly does not fetch its own data - it requires real GDP/
inflation/repo-rate figures. No free live feed for Indian macro data is
wired into this system, so rather than fabricate numbers, these are exposed
as optional settings (MACRO_GDP_GROWTH_PCT / MACRO_INFLATION_PCT /
MACRO_POLICY_RATE_PCT in .env, sourced from RBI/MOSPI bulletins - they move
slowly, so periodic manual updates are fine). When unset, this agent falls
back to the news-sentiment-only reading it always had."""

from __future__ import annotations

import datetime as dt

from app.agents.base import AgentVote, AnalysisContext, BaseAgent, blend_signals
from app.config import get_settings
from app.llm.client import get_llm_client
from app.tools import sentiment_engine
from macroeconomist_agent import MacroeconomistAgent, MacroObservation

MACRO_KEYWORDS = [
    "gdp", "inflation", "interest rate", "repo rate", "cpi", "wpi", "currency", "rupee",
    "crude oil", "global markets", "fii", "dii", "fed", "federal reserve", "bond yield",
]

_ENGINE = MacroeconomistAgent()
_BULLISH_REGIMES = {"strong_expansion", "moderate_expansion", "accommodative_policy", "near_target", "disinflationary"}
_BEARISH_REGIMES = {"contraction", "stall_speed", "high_inflation", "restrictive_policy"}


def _is_macro(item: dict) -> bool:
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    return any(k in text for k in MACRO_KEYWORDS)


def _recency_days(as_of: str) -> int:
    if not as_of:
        return 60
    try:
        return max(0, (dt.date.today() - dt.date.fromisoformat(as_of)).days)
    except ValueError:
        return 60


def _regime_signal() -> dict | None:
    settings = get_settings()
    if settings.macro_gdp_growth_pct is None or settings.macro_inflation_pct is None or settings.macro_policy_rate_pct is None:
        return None

    recency = _recency_days(settings.macro_data_as_of)
    obs = [
        MacroObservation(name="gdp_growth", value=settings.macro_gdp_growth_pct, unit="percent", period="latest_quarter",
                          source="MOSPI", as_of=settings.macro_data_as_of or "unknown", recency_days=recency, source_quality=0.85, revision_risk=0.3),
        MacroObservation(name="inflation", value=settings.macro_inflation_pct, unit="percent", period="latest_month",
                          source="MOSPI/RBI", as_of=settings.macro_data_as_of or "unknown", recency_days=recency, source_quality=0.85, revision_risk=0.2),
        MacroObservation(name="policy_rate", value=settings.macro_policy_rate_pct, unit="percent", period="current",
                          source="RBI", as_of=settings.macro_data_as_of or "unknown", recency_days=recency, source_quality=0.95, revision_risk=0.05),
    ]
    result = _ENGINE.analyze(obs)

    regimes = [s.regime for s in result.signals]
    bull = sum(1 for r in regimes if r in _BULLISH_REGIMES)
    bear = sum(1 for r in regimes if r in _BEARISH_REGIMES)
    if bull > bear:
        action, strength = "BUY", (bull - bear) / len(regimes)
    elif bear > bull:
        action, strength = "SELL", (bear - bull) / len(regimes)
    else:
        action, strength = "HOLD", 0.3

    confidence = round(max(0.15, min(0.85, result.overall_confidence.score * (0.4 + 0.6 * strength))), 3)

    evidence = [result.summary]
    evidence.extend(f"{s.indicator} ({s.regime}): {s.interpretation}" for s in result.signals)
    evidence.extend(result.risks[:2])

    return {
        "action": action,
        "confidence": confidence,
        "evidence": evidence,
        "metrics": {
            "regime_mix": regimes,
            "regime_confidence": result.overall_confidence.score,
            "suggested_tilts": result.suggested_tilts,
        },
    }


class MacroAnalyst(BaseAgent):
    name = "Macroeconomic Analyst"
    agent_type = "analyst"
    expertise = "macro"

    def vote(self, ctx: AnalysisContext) -> AgentVote:
        macro_items = [n for n in ctx.market_news if _is_macro(n)]
        news_signal = sentiment_engine.analyze(macro_items)

        regime_signal = _regime_signal()
        if regime_signal is not None:
            combined = blend_signals([regime_signal, news_signal], [0.6, 0.4])
            system_prompt = (
                "You are a macroeconomic analyst on a trading committee. Summarize how the macro backdrop "
                "(GDP, inflation, rates, currency, global markets) affects this stock in 2-3 crisp sentences, "
                "grounded only in the evidence given - do not assert macro facts beyond it."
            )
        else:
            combined = dict(news_signal)
            combined["evidence"] = [
                *combined["evidence"],
                "Numeric macro regime analysis not configured - set MACRO_GDP_GROWTH_PCT/MACRO_INFLATION_PCT/"
                "MACRO_POLICY_RATE_PCT in .env from RBI/MOSPI bulletins to activate it.",
            ]
            system_prompt = (
                "You are a macroeconomic analyst on a trading committee, but no live GDP/inflation/policy-rate data "
                "is configured this tick - only macro-tagged news headlines are available. Comment ONLY on the "
                "specific evidence given (2-3 sentences); do NOT assert claims about current GDP growth, inflation, "
                "or RBI/central-bank policy stance, since you have no real data for those - state plainly that the "
                "broader macro regime is unassessed if the evidence is thin."
            )

        llm = get_llm_client()
        evidence_txt = " ".join(combined["evidence"])
        reasoning = llm.chat(
            system=system_prompt,
            user=f"Symbol {ctx.symbol}. Signal: {combined['action']} (confidence {combined['confidence']}). Evidence: {evidence_txt}",
            fallback=f"Macro read for {ctx.symbol}: {combined['action']}. {evidence_txt or 'No material macro headlines this tick.'}",
        )

        return AgentVote(
            agent_name=self.name,
            agent_type=self.agent_type,
            action=combined["action"],
            confidence=combined["confidence"],
            reasoning=reasoning,
            evidence=combined["evidence"] or ["No macro-tagged headlines in the current window."],
            metrics=combined["metrics"],
        )
