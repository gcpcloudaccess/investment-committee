"""Tests for FX rate conversion (app/data/fx.py) - no network required
(fetch failures are simulated via monkeypatch, matching the fallback path)."""

import pandas as pd
import pytest

from app.data import fx


@pytest.fixture(autouse=True)
def _clear_fx_cache():
    fx._cache.clear()
    yield
    fx._cache.clear()


def test_same_currency_shortcut_returns_one_with_no_fetch(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("should not fetch for INR->INR")
    monkeypatch.setattr(fx.yf, "Ticker", _boom)
    assert fx.get_fx_rate("INR") == 1.0
    assert fx.get_fx_rate("inr") == 1.0  # case-insensitive


def test_live_fetch_used_when_available(monkeypatch):
    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period, interval):
            assert self.symbol == "USDINR=X"
            return pd.DataFrame({"Close": [86.0, 86.5]})

    monkeypatch.setattr(fx.yf, "Ticker", FakeTicker)
    assert fx.get_fx_rate("USD") == 86.5


def test_falls_back_to_static_rate_on_fetch_failure(monkeypatch):
    class FailingTicker:
        def __init__(self, symbol):
            pass

        def history(self, period, interval):
            raise ConnectionError("network down")

    monkeypatch.setattr(fx.yf, "Ticker", FailingTicker)
    rate = fx.get_fx_rate("GBP")
    assert rate == fx._FALLBACK_RATES["GBP"]


def test_result_is_cached_between_calls(monkeypatch):
    call_count = 0

    class FakeTicker:
        def __init__(self, symbol):
            pass

        def history(self, period, interval):
            nonlocal call_count
            call_count += 1
            return pd.DataFrame({"Close": [64.0]})

    monkeypatch.setattr(fx.yf, "Ticker", FakeTicker)
    fx.get_fx_rate("SGD")
    fx.get_fx_rate("SGD")
    assert call_count == 1
