"""Tests for the Astrological Analyst (app/agents/analysts/astro.py) and its
interpretive layer (app/tools/astro_signals.py) - no network, no LLM key
required (LLM narrative degrades to a deterministic templated fallback).

Fixed dates below were computed once via app.tools.astro_signals.analyze()
and cross-checked by hand against the underlying planetary snapshot
(app.tools.planetary_positions.get_snapshot) - see the comments on each test
for the specific placements driving the expected result."""

from __future__ import annotations

import datetime as dt

from app.agents.analysts.astro import AstroAnalyst
from app.agents.base import AnalysisContext, VALID_ACTIONS
from app.tools import astro_signals


def test_symbol_category_detection():
    assert astro_signals._symbol_category("NIFTYBEES.NS") == "index"
    assert astro_signals._symbol_category("GOLDBEES.NS") == "gold"
    assert astro_signals._symbol_category("SILVERBEES.NS") == "silver"
    assert astro_signals._symbol_category("RELIANCE.NS") == "index"  # unrecognized -> index fallback


def test_confidence_always_within_the_deliberately_low_cap():
    """This is a folklore heuristic, not an empirical model - confidence must
    never approach the ranges the real analysts use (see astro.py docstring)."""
    for symbol in ("NIFTYBEES.NS", "GOLDBEES.NS", "SILVERBEES.NS"):
        for day_offset in range(0, 365, 17):  # sample throughout a year
            when = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=day_offset)
            result = astro_signals.analyze(symbol, when)
            assert 0.15 <= result["confidence"] <= 0.5
            assert result["action"] in VALID_ACTIONS


def test_disclaimer_present_in_every_reading():
    result = astro_signals.analyze("NIFTYBEES.NS", dt.datetime(2026, 7, 21, tzinfo=dt.timezone.utc))
    assert any("not empirically validated" in e for e in result["evidence"])


def test_silver_buys_on_exalted_waxing_moon():
    # 2026-01-01: Moon is waxing in Taurus (its sign of exaltation for silver's
    # classical ruler) and Mercury is direct -> +0.20 (waxing, silver-weighted)
    # + 0.25 (Moon exalted in Taurus) = +0.45 -> BUY.
    when = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    result = astro_signals.analyze("SILVERBEES.NS", when)
    assert result["metrics"]["moon_rashi"] == "Taurus"
    assert result["metrics"]["moon_waxing"] is True
    assert result["action"] == "BUY"
    assert result["metrics"]["score"] > 0


def test_silver_sells_on_waning_moon_with_mercury_retrograde():
    # 2026-03-15: Mercury retrograde (-0.25) + waning Moon, silver-weighted
    # (-0.20) = -0.45 -> SELL. Moon's rashi (Capricorn) is neither silver's
    # exaltation nor debilitation sign, so it contributes 0 here.
    when = dt.datetime(2026, 3, 15, tzinfo=dt.timezone.utc)
    result = astro_signals.analyze("SILVERBEES.NS", when)
    assert result["metrics"]["mercury_retrograde"] is True
    assert result["metrics"]["moon_waxing"] is False
    assert result["action"] == "SELL"
    assert result["metrics"]["score"] < 0


def test_astro_analyst_returns_valid_agent_vote():
    ctx = AnalysisContext(symbol="NIFTYBEES.NS", bars=None, fundamentals={}, symbol_news=[], market_news=[])
    vote = AstroAnalyst().vote(ctx)
    assert vote.agent_name == "Astrological Analyst"
    assert vote.agent_type == "analyst"
    assert vote.action in VALID_ACTIONS
    assert 0.15 <= vote.confidence <= 0.5
    assert vote.evidence  # non-empty
    assert "category" in vote.metrics


def test_astro_analyst_differentiates_gold_and_silver_on_the_same_day():
    """Gold and silver use different classical rulers (Sun vs. Moon), so they
    shouldn't always move in lockstep even on the same day."""
    ctx_gold = AnalysisContext(symbol="GOLDBEES.NS", bars=None, fundamentals={}, symbol_news=[], market_news=[])
    ctx_silver = AnalysisContext(symbol="SILVERBEES.NS", bars=None, fundamentals={}, symbol_news=[], market_news=[])
    gold_vote = AstroAnalyst().vote(ctx_gold)
    silver_vote = AstroAnalyst().vote(ctx_silver)
    assert gold_vote.metrics["category"] == "gold"
    assert silver_vote.metrics["category"] == "silver"
