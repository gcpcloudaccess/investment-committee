from app.agents.analysts.algo_signal import AlgoSignalAnalyst
from app.agents.analysts.astro import AstroAnalyst
from app.agents.analysts.fundamental import FundamentalAnalyst
from app.agents.analysts.geopolitical import GeopoliticalAnalyst
from app.agents.analysts.macro import MacroAnalyst
from app.agents.analysts.policy import PolicyAnalyst
from app.agents.analysts.risk import RiskAnalyst
from app.agents.analysts.sentiment import SentimentAnalyst
from app.agents.analysts.technical import TechnicalAnalyst

# Staged pipeline (see app/agents/debate_loop.py): each tier runs after the
# previous one completes, and later tiers receive earlier tiers' votes as
# context (AnalysisContext.prior_stage_votes) - top-down macro/sentiment/
# policy/astrology backdrop first, then company-specific drill-down informed
# by that backdrop, then the algo model + its critic as the final automated
# signal. AstroAnalyst sits in the macro tier since it reads a market-wide
# planetary backdrop, not anything symbol-specific in the fundamental sense -
# see its own docstring for why it's deliberately a low-weight nudge, not a
# primary signal.
MACRO_TIER = [MacroAnalyst, SentimentAnalyst, GeopoliticalAnalyst, PolicyAnalyst, AstroAnalyst]
DRILLDOWN_TIER = [FundamentalAnalyst, TechnicalAnalyst, RiskAnalyst]
ALGO_TIER = [AlgoSignalAnalyst]

ALL_ANALYSTS = [*MACRO_TIER, *DRILLDOWN_TIER, *ALGO_TIER]

__all__ = [
    "FundamentalAnalyst",
    "TechnicalAnalyst",
    "MacroAnalyst",
    "SentimentAnalyst",
    "GeopoliticalAnalyst",
    "PolicyAnalyst",
    "RiskAnalyst",
    "AlgoSignalAnalyst",
    "AstroAnalyst",
    "MACRO_TIER",
    "DRILLDOWN_TIER",
    "ALGO_TIER",
    "ALL_ANALYSTS",
]
