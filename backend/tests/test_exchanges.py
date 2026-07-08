"""Tests for the multi-exchange registry (app/data/exchanges.py) - no
network, no LLM key required."""

import datetime as dt
from zoneinfo import ZoneInfo

from app.data import exchanges as ex


def test_nse_open_during_its_own_hours_on_a_weekday():
    t = dt.datetime(2026, 7, 8, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))  # Wednesday
    assert ex.NSE.is_open(t)
    assert ex.get_open_exchange(t).code == "NSE"


def test_nse_closed_on_weekend():
    # 2026-07-11 is a Saturday
    t = dt.datetime(2026, 7, 11, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert not ex.NSE.is_open(t)


def test_nse_closed_before_open_and_after_close():
    before = dt.datetime(2026, 7, 8, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    after = dt.datetime(2026, 7, 8, 15, 45, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert not ex.NSE.is_open(before)
    assert not ex.NSE.is_open(after)


def test_nyse_open_during_its_own_hours():
    # 14:00 ET is after LSE's 16:30 BST close (15:30 UTC) but still within NYSE
    # hours, so this time genuinely has only NYSE open (11:00 ET would also
    # have LSE open - London/NY hours overlap for a few hours each day).
    t = dt.datetime(2026, 7, 8, 14, 0, tzinfo=ZoneInfo("America/New_York"))  # Wednesday
    assert ex.NYSE.is_open(t)
    assert not ex.LSE.is_open(t)
    assert ex.get_open_exchange(t).code == "NYSE"


def test_all_exchanges_closed_in_the_daily_dead_zone():
    # ~22:00 UTC: US closed for the day (16:00 ET close = ~20:00-21:00 UTC depending on
    # DST), NSE not open until 03:45 UTC the next day.
    t = dt.datetime(2026, 7, 8, 22, 0, tzinfo=dt.timezone.utc)
    assert ex.get_open_exchange(t) is None


def test_priority_order_breaks_ties_when_multiple_exchanges_are_open():
    # NSE (03:45-10:00 UTC) and LSE (07:00-15:30 UTC in UK winter/no-DST reference)
    # overlap - at a time both are open, NSE (listed first) should win per the
    # India -> Singapore -> London -> US priority order.
    t = dt.datetime(2026, 7, 8, 8, 0, tzinfo=dt.timezone.utc)
    assert ex.NSE.is_open(t)
    assert ex.LSE.is_open(t)
    assert ex.get_open_exchange(t).code == "NSE"


def test_infer_exchange_from_symbol_suffixes():
    assert ex.infer_exchange_from_symbol("RELIANCE.NS").code == "NSE"
    assert ex.infer_exchange_from_symbol("D05.SI").code == "SGX"
    assert ex.infer_exchange_from_symbol("HSBA.L").code == "LSE"
    assert ex.infer_exchange_from_symbol("AAPL").code == "NYSE"  # no suffix -> assume US


def test_all_exchanges_have_distinct_codes_and_currencies():
    codes = [e.code for e in ex.ALL_EXCHANGES]
    assert len(codes) == len(set(codes)) == 4
    assert {e.currency for e in ex.ALL_EXCHANGES} == {"INR", "SGD", "GBP", "USD"}
