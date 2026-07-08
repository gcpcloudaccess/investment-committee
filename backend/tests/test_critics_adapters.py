"""Tests for the 4 critic agents (RiskCritic, ProfitCritic, MacroCritic,
OpportunityCritic), each a thin adapter over a vendored teammate package
(backend/macro_critic, backend/profit_critic_agent.py,
backend/opportunity_critic_agent.py, backend/risk_critic_agent). These assert
the *mapping* into AgentVote is well-formed - valid action/confidence and
non-empty reasoning - regardless of whether an LLM call (Risk Critic only)
succeeds or gracefully falls back, matching how the rest of this suite treats
optional LLM enrichment as a non-required upgrade to a working deterministic
core."""

import numpy as np
import pandas as pd
import pytest

from app.agents.base import AgentVote, AnalysisContext
from app.agents.critics import ALL_CRITICS, MacroCritic, OpportunityCritic, ProfitCritic, RiskCritic

VALID_ACTIONS = {"BUY", "SELL", "HOLD", "WAIT", "SWITCH"}


def _synthetic_bars(seed: int = 0, n: int = 80, start: float = 1000.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = start + np.cumsum(rng.normal(size=n))
    idx = pd.date_range("2026-07-01", periods=n, freq="5min")
    return pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1000.0}, index=idx)


@pytest.fixture()
def ctx() -> AnalysisContext:
    bars = _synthetic_bars()
    return AnalysisContext(
        symbol="RELIANCE.NS", bars=bars, fundamentals={"sector": "Energy"}, symbol_news=[], market_news=[],
        peer_bars={"RELIANCE.NS": bars, "TCS.NS": _synthetic_bars(seed=1, start=3000.0)},
        benchmark_bars=_synthetic_bars(seed=2, start=22000.0), open_positions=[],
    )


@pytest.fixture()
def prior_votes() -> list[AgentVote]:
    return [
        AgentVote(agent_name="Technical Analyst", agent_type="analyst", action="BUY", confidence=0.4, reasoning="momentum is strong", evidence=["RSI oversold bounce"]),
        AgentVote(agent_name="Fundamental Analyst", agent_type="analyst", action="BUY", confidence=0.3, reasoning="valuation reasonable", evidence=["PE below sector avg"]),
        AgentVote(agent_name="Risk Assessment Analyst", agent_type="analyst", action="HOLD", confidence=0.2, reasoning="moderate vol", evidence=["vol regime medium"]),
    ]


def _assert_well_formed(vote: AgentVote) -> None:
    assert vote.action in VALID_ACTIONS
    assert 0.0 <= vote.confidence <= 1.0
    assert vote.reasoning.strip()
    assert vote.evidence


def test_all_critics_produce_well_formed_votes(ctx, prior_votes):
    for cls in ALL_CRITICS:
        vote = cls().vote(ctx, prior_votes)
        _assert_well_formed(vote)


def test_risk_critic_degrades_gracefully_on_llm_failure(ctx, prior_votes, monkeypatch):
    """Force the model_caller path to fail (simulating no key / network issue) and
    confirm RiskCritic still returns a valid, non-crashing vote via the vendored
    package's own insufficient_data_response - not an unhandled exception."""
    from app.llm import client as llm_client_module

    monkeypatch.setattr(llm_client_module.LLMClient, "available", property(lambda self: False))
    vote = RiskCritic().vote(ctx, prior_votes)
    _assert_well_formed(vote)
    assert vote.metrics.get("decision") == "insufficient_data"


def test_profit_critic_waits_with_no_directional_lean(ctx):
    """With no BUY/SELL lean among prior votes, there's nothing priceable to
    critique - should not crash trying to build a TradeProposal."""
    votes = [AgentVote(agent_name="X", agent_type="analyst", action="HOLD", confidence=0.3, reasoning="r", evidence=["e"])]
    vote = ProfitCritic().vote(ctx, votes)
    assert vote.action == "WAIT"
    _assert_well_formed(vote)


def test_opportunity_critic_echoes_current_lean_when_no_better_alternative(ctx):
    """With only the current symbol in peer_bars (no real alternatives to compare),
    the vendored agent should support the current lean, not force it to HOLD."""
    single_symbol_ctx = AnalysisContext(
        symbol=ctx.symbol, bars=ctx.bars, fundamentals=ctx.fundamentals, symbol_news=[], market_news=[],
        peer_bars={ctx.symbol: ctx.bars}, open_positions=[],
    )
    votes = [AgentVote(agent_name="Technical Analyst", agent_type="analyst", action="BUY", confidence=0.5, reasoning="r", evidence=["e"])]
    vote = OpportunityCritic().vote(single_symbol_ctx, votes)
    assert vote.action == "BUY"


def test_macro_critic_uses_configured_macro_settings(ctx, prior_votes, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MACRO_GDP_GROWTH_PCT", "7.5")
    monkeypatch.setenv("MACRO_INFLATION_PCT", "3.0")
    monkeypatch.setenv("MACRO_POLICY_RATE_PCT", "5.5")
    get_settings.cache_clear()
    try:
        vote = MacroCritic().vote(ctx, prior_votes)
        _assert_well_formed(vote)
    finally:
        get_settings.cache_clear()
