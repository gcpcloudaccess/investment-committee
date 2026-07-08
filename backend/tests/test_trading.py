"""Isolated tests for the execution engine and cost model, using an in-memory
SQLite DB so they don't touch the real session DB."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Portfolio
from app.portfolio import portfolio_manager
from app.trading import execution_engine
from app.trading.costs import compute_costs, COST_PROFILES


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_costs_buy_vs_sell_asymmetry():
    buy = compute_costs("BUY", 10, 1000.0)
    sell = compute_costs("SELL", 10, 1000.0)
    assert buy["stt"] == 0.0
    assert sell["stt"] > 0.0
    assert buy["stamp_duty"] > 0.0
    assert sell["stamp_duty"] == 0.0
    assert sell["total"] > buy["total"]  # STT only on sell side


def test_open_and_close_position_updates_cash(db):
    portfolio = Portfolio(cash_inr=10000.0, starting_capital=10000.0, leverage=2.0, status="active")
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)

    trade = execution_engine.open_position(db, portfolio, "RELIANCE.NS", "LONG", 5, 1000.0, decision_id=None)
    assert trade.action == "BUY"
    assert portfolio.cash_inr < 10000.0 - 5 * 1000.0  # cash reduced by notional + costs (costs > 0)

    position = execution_engine.get_open_position(db, portfolio, "RELIANCE.NS")
    assert position is not None
    assert position.quantity == 5

    cash_before_close = portfolio.cash_inr
    close_trade = execution_engine.close_position(db, portfolio, position, 1050.0, decision_id=None)
    assert close_trade.action == "SELL"
    assert portfolio.cash_inr > cash_before_close  # proceeds credited back
    assert position.status == "closed"
    assert position.realized_pnl is not None
    # profitable move (1000 -> 1050) minus costs should still be net positive
    assert position.realized_pnl > 0


def test_switch_verdict_without_existing_position_opens_long(db):
    """SWITCH means "prefer a different stock" relative to an existing holding -
    with no current position in this symbol, that has nothing to switch out of,
    so it should resolve to a real BUY rather than silently no-op'ing a verdict
    the consensus engine already committed to."""
    portfolio = Portfolio(cash_inr=10000.0, starting_capital=10000.0, leverage=2.0, status="active")
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)

    result = portfolio_manager.process_decision(
        db, portfolio, "RELIANCE.NS", verdict="SWITCH", directional_confidence_pct=25.0,
        risk_level="MEDIUM", volatility=0.01, price=1000.0, decision_id=None,
    )
    assert result["executed"] is True
    assert result["action"] == "OPEN_LONG_FROM_SWITCH"
    position = execution_engine.get_open_position(db, portfolio, "RELIANCE.NS")
    assert position is not None


def test_switch_verdict_with_existing_position_closes_it(db):
    portfolio = Portfolio(cash_inr=10000.0, starting_capital=10000.0, leverage=2.0, status="active")
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    execution_engine.open_position(db, portfolio, "RELIANCE.NS", "LONG", 5, 1000.0, decision_id=None)

    result = portfolio_manager.process_decision(
        db, portfolio, "RELIANCE.NS", verdict="SWITCH", directional_confidence_pct=25.0,
        risk_level="MEDIUM", volatility=0.01, price=1010.0, decision_id=None,
    )
    assert result["executed"] is True
    assert result["action"] == "CLOSE_LONG"
    assert execution_engine.get_open_position(db, portfolio, "RELIANCE.NS") is None


def test_all_four_exchange_cost_profiles_exist_and_produce_nonnegative_costs():
    for exchange in COST_PROFILES:
        buy = compute_costs("BUY", 10, 10_000.0, exchange=exchange, fx_rate_to_inr=86.0)
        sell = compute_costs("SELL", 10, 10_000.0, exchange=exchange, fx_rate_to_inr=86.0)
        assert buy["total"] >= 0
        assert sell["total"] >= 0


def test_lse_stamp_duty_is_buy_side_only():
    buy = compute_costs("BUY", 10, 10_000.0, exchange="LSE", fx_rate_to_inr=109.0)
    sell = compute_costs("SELL", 10, 10_000.0, exchange="LSE", fx_rate_to_inr=109.0)
    assert buy["stamp_duty"] > 0
    assert sell["stamp_duty"] == 0.0


def test_nyse_is_near_zero_cost_on_buy_and_charges_only_a_tiny_sell_fee():
    buy = compute_costs("BUY", 10, 160_000.0, exchange="NYSE", fx_rate_to_inr=86.0)
    sell = compute_costs("SELL", 10, 160_000.0, exchange="NYSE", fx_rate_to_inr=86.0)
    assert buy["total"] == 0.0
    assert sell["total"] > 0.0
    assert sell["total"] < buy["turnover"] * 0.001  # tiny relative to turnover


def test_sgx_gst_applies_to_fees_not_turnover():
    result = compute_costs("BUY", 10, 20_000.0, exchange="SGX", fx_rate_to_inr=64.0)
    # GST should be a small fraction of the fee components, nowhere near 9% of turnover.
    assert result["gst"] < result["turnover"] * 0.01


def test_flat_local_fee_scales_with_fx_rate():
    """LSE's flat GBP commission should come out larger in INR terms at a higher fx rate."""
    low_fx = compute_costs("BUY", 10, 5_000.0, exchange="LSE", fx_rate_to_inr=100.0)
    high_fx = compute_costs("BUY", 10, 5_000.0, exchange="LSE", fx_rate_to_inr=120.0)
    assert high_fx["brokerage"] > low_fx["brokerage"]


def test_get_active_portfolio_tags_new_portfolio_with_requested_exchange(db):
    portfolio = execution_engine.get_active_portfolio(db, exchange="SGX")
    assert portfolio.exchange == "SGX"


def test_get_active_portfolio_defaults_to_nse_when_no_exchange_given(db):
    portfolio = execution_engine.get_active_portfolio(db)
    assert portfolio.exchange == "NSE"


def test_open_position_stores_exchange_and_fx_metadata(db):
    portfolio = Portfolio(cash_inr=10000.0, starting_capital=10000.0, leverage=2.0, status="active", exchange="NYSE")
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)

    trade = execution_engine.open_position(
        db, portfolio, "AAPL", "LONG", 5, 16_000.0, decision_id=None,
        exchange="NYSE", currency="USD", price_local=187.32, fx_rate_to_inr=85.5,
    )
    position = execution_engine.get_open_position(db, portfolio, "AAPL")

    assert trade.exchange == "NYSE"
    assert trade.currency == "USD"
    assert trade.price_local == 187.32
    assert trade.fx_rate_to_inr == 85.5
    assert position.exchange == "NYSE"
    assert position.currency == "USD"


def test_close_position_uses_positions_own_exchange_for_costs(db):
    """A position opened on LSE should close using LSE's cost profile even if
    called without an explicit exchange override - it should read it off the
    position itself, not assume NSE."""
    portfolio = Portfolio(cash_inr=10000.0, starting_capital=10000.0, leverage=2.0, status="active", exchange="LSE")
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)

    execution_engine.open_position(
        db, portfolio, "HSBA.L", "LONG", 10, 5_450.0, decision_id=None,
        exchange="LSE", currency="GBP", price_local=50.0, fx_rate_to_inr=109.0,
    )
    position = execution_engine.get_open_position(db, portfolio, "HSBA.L")

    close_trade = execution_engine.close_position(db, portfolio, position, 5_600.0, decision_id=None)
    assert close_trade.exchange == "LSE"
    assert close_trade.cost_breakdown_json["stamp_duty"] == 0.0  # LSE stamp duty is buy-side only, this is a sell


def test_force_close_all(db):
    portfolio = Portfolio(cash_inr=10000.0, starting_capital=10000.0, leverage=2.0, status="active")
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)

    execution_engine.open_position(db, portfolio, "TCS.NS", "LONG", 2, 3000.0, decision_id=None)
    execution_engine.open_position(db, portfolio, "INFY.NS", "LONG", 3, 1500.0, decision_id=None)

    trades = execution_engine.force_close_all(db, portfolio, {"TCS.NS": 3100.0, "INFY.NS": 1480.0})
    assert len(trades) == 2
    assert execution_engine.get_open_exposure(db, portfolio) == 0.0
