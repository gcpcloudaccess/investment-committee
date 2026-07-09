"""Tests for the Investment Planner's tick symbol selection (app/agents/planner.py)
- no network, no LLM key required."""

from app.agents.planner import InvestmentPlanner


def test_default_budget_is_one_symbol_per_tick():
    """Locks in the current speed-oriented default (2026-07-09): each symbol's
    full committee takes ~30-90s wall-clock, so this is the main lever on how
    fast a decision actually lands, not TICK_MINUTES alone."""
    planner = InvestmentPlanner()
    assert planner.max_symbols_per_tick == 1


def test_picks_exactly_the_budgeted_number_of_new_symbols():
    planner = InvestmentPlanner(max_symbols_per_tick=1)
    selected = planner.plan_tick(["A.NS", "B.NS", "C.NS"], open_position_symbols=[])
    assert len(selected) == 1
    assert selected[0] == "A.NS"


def test_open_positions_are_always_monitored_even_over_budget():
    """An open position must never be dropped just because the per-tick budget
    is small - the budget only limits how many NEW candidates get explored."""
    planner = InvestmentPlanner(max_symbols_per_tick=1)
    selected = planner.plan_tick(["A.NS", "B.NS", "C.NS"], open_position_symbols=["B.NS"])
    assert "B.NS" in selected


def test_no_new_candidates_explored_when_budget_already_consumed_by_open_positions():
    planner = InvestmentPlanner(max_symbols_per_tick=1)
    selected = planner.plan_tick(["A.NS", "B.NS", "C.NS"], open_position_symbols=["B.NS"])
    assert selected == ["B.NS"]  # budget of 1 fully used by the open position, no room to explore


def test_rotation_advances_across_ticks():
    planner = InvestmentPlanner(max_symbols_per_tick=1)
    first = planner.plan_tick(["A.NS", "B.NS", "C.NS"], open_position_symbols=[])
    second = planner.plan_tick(["A.NS", "B.NS", "C.NS"], open_position_symbols=[])
    assert first != second  # cursor moved on, not stuck analyzing the same symbol forever
