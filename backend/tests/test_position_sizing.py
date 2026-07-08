"""Tests for confidence-scaled, capped leverage in position sizing - no
network, no LLM key required.

Regression context: the first version of this scaling used the full 0-100%
directional_confidence range, but real trades in this system only ever fire
in the ~18-40% band (see trust_weighted_consensus.py's decisive threshold),
so leverage never actually got exercised - real executed trades sized well
under available *cash*, let alone margin. These tests lock in that leverage
is meaningfully used for any trade that actually fires, not just in theory."""

from app.portfolio import position_sizing


def test_leverage_never_exceeds_configured_ceiling():
    result = position_sizing.size_position(
        directional_confidence_pct=100.0, risk_level="LOW", price=1000.0,
        current_open_exposure=0.0, cash_available=10_000.0,
    )
    assert result["leverage_used"] <= result["max_leverage"]
    assert result["max_leverage"] == 2.0  # settings default


def test_realistic_decisive_confidence_meaningfully_uses_leverage():
    """The actual bug report: a trade at a realistic just-cleared-the-bar
    confidence (~19%, matching real production decisions) must draw
    meaningfully on leverage, not size so conservatively it never even
    spends available cash."""
    result = position_sizing.size_position(
        directional_confidence_pct=19.0, risk_level="MEDIUM", price=1290.40,
        current_open_exposure=0.0, cash_available=10_000.0,
    )
    assert result["leverage_used"] > 1.4  # meaningfully above the 1.4x base, not stuck near 1x
    assert result["notional"] > 0.0


def test_leverage_scales_up_with_confidence():
    low_conf = position_sizing.size_position(
        directional_confidence_pct=18.0, risk_level="LOW", price=1000.0,
        current_open_exposure=0.0, cash_available=10_000.0,
    )
    high_conf = position_sizing.size_position(
        directional_confidence_pct=30.0, risk_level="LOW", price=1000.0,
        current_open_exposure=0.0, cash_available=10_000.0,
    )
    assert high_conf["leverage_used"] > low_conf["leverage_used"]
    assert high_conf["leverage_used"] == 2.0  # at/above STRONG_CONFIDENCE_PCT with LOW risk -> full ceiling


def test_leverage_scales_down_with_risk():
    low_risk = position_sizing.size_position(
        directional_confidence_pct=25.0, risk_level="LOW", price=1000.0,
        current_open_exposure=0.0, cash_available=10_000.0,
    )
    high_risk = position_sizing.size_position(
        directional_confidence_pct=25.0, risk_level="EXTREME", price=1000.0,
        current_open_exposure=0.0, cash_available=10_000.0,
    )
    assert low_risk["leverage_used"] > high_risk["leverage_used"]


def test_strong_low_risk_signal_actually_draws_margin():
    result = position_sizing.size_position(
        directional_confidence_pct=30.0, risk_level="LOW", price=100.0,
        current_open_exposure=0.0, cash_available=10_000.0,
    )
    assert result["notional"] > 10_000.0  # exceeds own cash -> genuinely using leverage
    assert result["margin_used_inr"] > 0.0
    assert result["notional"] <= 10_000.0 * result["max_leverage"]


def test_never_exceeds_portfolio_wide_exposure_cap():
    # Exposure budget already exhausted -> no new position regardless of confidence.
    result = position_sizing.size_position(
        directional_confidence_pct=100.0, risk_level="LOW", price=1000.0,
        current_open_exposure=20_000.0, cash_available=10_000.0,  # at the 2x cap already
    )
    assert result["quantity"] == 0
