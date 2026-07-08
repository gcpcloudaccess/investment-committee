from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from app.agents.analysts import ALGO_TIER, DRILLDOWN_TIER, MACRO_TIER
from app.agents.base import AgentVote, AnalysisContext
from app.agents.critics import ALL_CRITICS
from app.agents.debate_agent import DebateAgent
from app.config import get_settings


def _run_tier(tier: list[type], ctx: AnalysisContext, max_workers: int) -> list[AgentVote]:
    if len(tier) == 1:
        return [tier[0]().vote(ctx)]
    with ThreadPoolExecutor(max_workers=min(max_workers, len(tier))) as pool:
        return list(pool.map(lambda cls: cls().vote(ctx), tier))


def run_debate(ctx: AnalysisContext) -> tuple[list[AgentVote], AgentVote, list[AgentVote]]:
    """Runs analysts as a staged pipeline rather than one flat parallel batch,
    each tier informed by the ones before it (AnalysisContext.prior_stage_votes):

      1. Macro context tier (parallel): Macro, Sentiment, Geopolitical, Government
         Policy - top-down backdrop, independent of any single stock's specifics.
      2. Drill-down tier (parallel, sees tier 1's votes): Fundamental, Technical,
         Risk - company-specific analysis informed by that backdrop.
      3. Algo tier (sequential, sees tiers 1+2's votes): the trained model signal,
         already internally reviewed by its own dedicated critic
         (see app/agents/analysts/algo_signal.py) - the final automated trigger.

    Concurrency within each tier is capped at `settings.max_parallel_agents`
    (unbounded parallelism trips API rate limits and the SDK's retry-with-
    backoff ends up slower than sequential execution).

    The Debate Agent then synthesizes the strongest contradicting views across
    ALL tiers, and all 4 committee critics review the full set - the mandatory
    trust-weighted consensus (not this staging) is still what makes the final
    call, using every tier's votes together.

    Returns (analyst_votes, debate_vote, critic_votes).
    """
    max_workers = max(1, get_settings().max_parallel_agents)

    macro_votes = _run_tier(MACRO_TIER, ctx, max_workers)

    drilldown_ctx = replace(ctx, prior_stage_votes=macro_votes)
    drilldown_votes = _run_tier(DRILLDOWN_TIER, drilldown_ctx, max_workers)

    algo_ctx = replace(ctx, prior_stage_votes=macro_votes + drilldown_votes)
    algo_votes = _run_tier(ALGO_TIER, algo_ctx, max_workers)

    analyst_votes = [*macro_votes, *drilldown_votes, *algo_votes]

    debate_vote = DebateAgent().vote(ctx, analyst_votes)

    with ThreadPoolExecutor(max_workers=min(max_workers, len(ALL_CRITICS))) as pool:
        critic_votes = list(pool.map(lambda cls: cls().vote(ctx, analyst_votes + [debate_vote]), ALL_CRITICS))

    return analyst_votes, debate_vote, critic_votes
