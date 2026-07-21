from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_provider: str = "anthropic"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    newsapi_key: str = ""

    data_mode: str = "replay"  # live | replay

    database_url: str = "sqlite:///./investment_committee.db"

    starting_capital_inr: float = 1_000_000.0  # ₹10 lac paper capital
    leverage: float = 1.0  # no margin - cash-only paper trading
    session_hours: float = 4.0
    tick_minutes: int = 10
    # Scoped to an India-only, single-exchange universe: the Nifty 50 index
    # (via its NIFTYBEES.NS ETF) plus MCX gold/silver via their NSE-listed ETF
    # proxies (GOLDBEES.NS / SILVERBEES.NS) - see app/data/exchanges.py for why
    # the ETF proxies are used instead of raw MCX contracts.
    watchlist: str = "NIFTYBEES.NS,GOLDBEES.NS,SILVERBEES.NS"

    # This build only supports NSE (see app/data/exchanges.py) - kept as a
    # setting rather than hardcoded so the session runner's live/replay branch
    # doesn't need special-casing.
    replay_exchange: str = "NSE"

    # Drives the Investment Planner's asset-allocation caps and profit/loss goals
    # (see agents/allocation_planner.py) - conservative | moderate | aggressive.
    risk_tolerance: str = "moderate"

    backend_host: str = "127.0.0.1"
    backend_port: int = 8000

    # Caps concurrent LLM calls when running agents in parallel. Keep conservative -
    # most API tiers rate-limit on concurrent/burst requests, and firing all 8+
    # analysts at once can trigger retries that cost more time than sequential
    # execution would have. Raise this if your API tier comfortably supports it.
    max_parallel_agents: int = 4

    # How many symbols the Investment Planner analyzes per tick (see agents/planner.py).
    # Each symbol runs the full 14-agent committee (~30-90s wall-clock), so this is the
    # main lever on how fast a decision lands, not TICK_MINUTES - a tick can't finish
    # faster than max_symbols_per_tick x (time per symbol), regardless of how often the
    # scheduler fires. Lower = faster individual decisions, less breadth per tick (the
    # watchlist still rotates fully over time, just in smaller batches).
    max_symbols_per_tick: int = 1

    # Optional India macro inputs for the Macroeconomist Analyst's regime model
    # (GDP growth, CPI inflation, RBI repo rate). No free live feed for these is
    # wired up, so rather than fabricate numbers this is left unset by default -
    # the agent falls back to its news-sentiment-only reading until you fill
    # these in from RBI/MOSPI bulletins (update periodically; they move slowly).
    macro_gdp_growth_pct: float | None = None
    macro_inflation_pct: float | None = None
    macro_policy_rate_pct: float | None = None
    macro_data_as_of: str = ""  # ISO date, e.g. "2026-06-30"

    @property
    def watchlist_symbols(self) -> list[str]:
        return [s.strip() for s in self.watchlist.split(",") if s.strip()]

    @property
    def max_exposure_inr(self) -> float:
        return self.starting_capital_inr * self.leverage

    @property
    def llm_key_configured(self) -> bool:
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.llm_provider == "openai":
            return bool(self.openai_api_key)
        return False


@lru_cache
def get_settings() -> Settings:
    return Settings()
