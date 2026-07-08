"""Tests for the staged analyst pipeline (macro -> drill-down -> algo) - no
network, no LLM key required."""

from app.agents.analysts import ALGO_TIER, ALL_ANALYSTS, DRILLDOWN_TIER, MACRO_TIER
from app.agents.analysts.algo_signal import AlgoSignalAnalyst
from app.agents.analysts.fundamental import FundamentalAnalyst
from app.agents.analysts.geopolitical import GeopoliticalAnalyst
from app.agents.analysts.macro import MacroAnalyst
from app.agents.analysts.policy import PolicyAnalyst
from app.agents.analysts.risk import RiskAnalyst
from app.agents.analysts.sentiment import SentimentAnalyst
from app.agents.analysts.technical import TechnicalAnalyst
from app.agents.base import AgentVote, AnalysisContext, prior_stage_summary


def test_tiers_partition_all_analysts_with_no_overlap():
    assert set(MACRO_TIER) == {MacroAnalyst, SentimentAnalyst, GeopoliticalAnalyst, PolicyAnalyst}
    assert set(DRILLDOWN_TIER) == {FundamentalAnalyst, TechnicalAnalyst, RiskAnalyst}
    assert set(ALGO_TIER) == {AlgoSignalAnalyst}

    all_tiered = set(MACRO_TIER) | set(DRILLDOWN_TIER) | set(ALGO_TIER)
    assert all_tiered == set(ALL_ANALYSTS)
    assert len(all_tiered) == len(MACRO_TIER) + len(DRILLDOWN_TIER) + len(ALGO_TIER)  # no double-counting


def test_prior_stage_summary_empty_when_no_prior_votes():
    ctx = AnalysisContext(symbol="TCS.NS", bars=None, fundamentals={}, symbol_news=[], market_news=[])
    assert prior_stage_summary(ctx) == ""


def test_prior_stage_summary_includes_each_prior_vote():
    prior_votes = [
        AgentVote(agent_name="Macroeconomic Analyst", agent_type="analyst", action="BUY", confidence=0.6, reasoning="r"),
        AgentVote(agent_name="Sentiment Analyst", agent_type="analyst", action="SELL", confidence=0.4, reasoning="r"),
    ]
    ctx = AnalysisContext(
        symbol="TCS.NS", bars=None, fundamentals={}, symbol_news=[], market_news=[], prior_stage_votes=prior_votes,
    )
    summary = prior_stage_summary(ctx)
    assert "Macroeconomic Analyst" in summary
    assert "BUY" in summary
    assert "Sentiment Analyst" in summary
    assert "SELL" in summary
