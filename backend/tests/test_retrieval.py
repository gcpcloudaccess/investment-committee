"""Tests for the RAG-lite retrieval layer (app/memory/retrieval.py) - no
network, no LLM key required. Uses an in-memory SQLite DB, same fixture
pattern as test_trading.py."""

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Decision, Portfolio, Position, Trade
from app.memory import retrieval


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_decision(db, symbol: str, verdict: str, confidence: float, ts: dt.datetime, reasoning: str = "reasoning") -> Decision:
    d = Decision(symbol=symbol, verdict=verdict, directional_confidence=confidence, consensus_reasoning=reasoning, timestamp=ts, executed=verdict in ("BUY", "SELL", "SWITCH"))
    db.add(d)
    db.flush()
    return d


def _make_closed_trade(db, portfolio: Portfolio, decision: Decision, symbol: str, realized_pnl: float) -> Trade:
    position = Position(portfolio_id=portfolio.id, symbol=symbol, side="LONG", quantity=1, avg_price=100.0, status="closed", exit_price=100.0 + realized_pnl, realized_pnl=realized_pnl)
    db.add(position)
    db.flush()
    trade = Trade(portfolio_id=portfolio.id, decision_id=decision.id, position_id=position.id, symbol=symbol, action="BUY", quantity=1, price=100.0, gross_value=100.0, total_costs=1.0, net_cash_impact=-101.0)
    db.add(trade)
    db.flush()
    return trade


@pytest.fixture()
def portfolio(db) -> Portfolio:
    p = Portfolio(cash_inr=10_000.0, starting_capital=10_000.0, leverage=2.0, status="active")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_returns_empty_for_symbol_with_no_history(db):
    assert retrieval.get_relevant_history(db, "NEWSTOCK.NS") == []


def test_only_returns_matching_symbol(db):
    _make_decision(db, "RELIANCE.NS", "BUY", 30.0, dt.datetime.now(dt.timezone.utc))
    _make_decision(db, "TCS.NS", "SELL", 25.0, dt.datetime.now(dt.timezone.utc))
    db.commit()

    history = retrieval.get_relevant_history(db, "RELIANCE.NS")
    assert len(history) == 1
    assert history[0]["verdict"] == "BUY"


def test_orders_most_recent_first_and_respects_limit(db):
    base = dt.datetime.now(dt.timezone.utc)
    for i in range(5):
        _make_decision(db, "RELIANCE.NS", "HOLD", 10.0 + i, base + dt.timedelta(minutes=i))
    db.commit()

    history = retrieval.get_relevant_history(db, "RELIANCE.NS", limit=3)
    assert len(history) == 3
    # Most recent (highest confidence, since confidence increases with i) comes first.
    assert history[0]["confidence"] == 14.0
    assert history[1]["confidence"] == 13.0
    assert history[2]["confidence"] == 12.0


def test_outcome_reflects_closed_position_realized_pnl(db, portfolio):
    decision = _make_decision(db, "RELIANCE.NS", "BUY", 30.0, dt.datetime.now(dt.timezone.utc))
    _make_closed_trade(db, portfolio, decision, "RELIANCE.NS", realized_pnl=-45.5)
    db.commit()

    history = retrieval.get_relevant_history(db, "RELIANCE.NS")
    assert history[0]["outcome"] == "closed Rs-45.50"


def test_outcome_is_still_open_for_unclosed_position(db, portfolio):
    decision = _make_decision(db, "RELIANCE.NS", "BUY", 30.0, dt.datetime.now(dt.timezone.utc))
    position = Position(portfolio_id=portfolio.id, symbol="RELIANCE.NS", side="LONG", quantity=1, avg_price=100.0, status="open")
    db.add(position)
    db.flush()
    db.add(Trade(portfolio_id=portfolio.id, decision_id=decision.id, position_id=position.id, symbol="RELIANCE.NS", action="BUY", quantity=1, price=100.0, gross_value=100.0, total_costs=1.0, net_cash_impact=-101.0))
    db.commit()

    history = retrieval.get_relevant_history(db, "RELIANCE.NS")
    assert history[0]["outcome"] == "still open"


def test_outcome_is_no_trade_for_hold_decision(db):
    _make_decision(db, "RELIANCE.NS", "HOLD", 10.0, dt.datetime.now(dt.timezone.utc))
    db.commit()

    history = retrieval.get_relevant_history(db, "RELIANCE.NS")
    assert history[0]["outcome"] == "no trade"
