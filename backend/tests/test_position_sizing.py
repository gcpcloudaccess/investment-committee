"""Tests for confidence-scaled, capped leverage in position sizing - no
network, no LLM key required."""

from app.portfolio import position_sizing


def test_leverage_never_exceeds_configured_ceiling():
    result = position_sizing.size_position(
        directional_confidence_pct=100.0, risk_level="LOW", price=1000.0,
        current_open_exposure=0.0, cash_available=10_000.0,
    )
    assert result["leverage_used"] <= result["max_leverage"]
    assert result["max_leverage"] == 2.0  # settings default


def test_leverage_scales_up_with_confidence():
    low_conf = position_sizing.size_position(
        directional_confidence_pct=20.0, risk_level="LOW", price=1000.0,
        current_open_exposure=0.0, cash_available=10_000.0,
    )
    high_conf = position_sizing.size_position(
        directional_confidence_pct=90.0, risk_level="LOW", price=1000.0,
        current_open_exposure=0.0, cash_available=10_000.0,
    )
    assert high_conf["leverage_used"] > low_conf["leverage_used"]


def test_leverage_scales_down_with_risk():
    low_risk = position_sizing.size_position(
        directional_confidence_pct=80.0, risk_level="LOW", price=1000.0,
        current_open_exposure=0.0, cash_available=10_000.0,
    )
    high_risk = position_sizing.size_position(
        directional_confidence_pct=80.0, risk_level="EXTREME", price=1000.0,
        current_open_exposure=0.0, cash_available=10_000.0,
    )
    assert low_risk["leverage_used"] > high_risk["leverage_used"]


def test_zero_confidence_uses_no_leverage():
    result = position_sizing.size_position(
        directional_confidence_pct=0.0, risk_level="MEDIUM", price=1000.0,
        current_open_exposure=0.0, cash_available=10_000.0,
    )
    assert result["leverage_used"] == 1.0  # own capital only, no margin


def test_margin_used_reflects_leverage_beyond_own_cash():
    result = position_sizing.size_position(
        directional_confidence_pct=100.0, risk_level="LOW", price=100.0,
        current_open_exposure=0.0, cash_available=10_000.0,
    )
    # High confidence + low risk should push notional above available cash (using leverage).
    if result["notional"] > 10_000.0:
        assert result["margin_used_inr"] > 0.0
    assert result["notional"] <= 10_000.0 * result["max_leverage"]


def test_never_exceeds_portfolio_wide_exposure_cap():
    # Exposure budget already exhausted -> no new position regardless of confidence.
    result = position_sizing.size_position(
        directional_confidence_pct=100.0, risk_level="LOW", price=1000.0,
        current_open_exposure=20_000.0, cash_available=10_000.0,  # at the 2x cap already
    )
    assert result["quantity"] == 0
