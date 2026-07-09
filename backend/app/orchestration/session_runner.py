"""Session Runner: the market-hours (or replay) tick loop.

In live mode, every tick first asks app/data/exchanges.py which of
NSE/SGX/LSE/NYSE is currently open (there is only ever one active market at a
time by design) and trades that one. When the active session's exchange no
longer matches the one that's currently open - NSE closed for the day, SGX
just opened - the old session is force-closed on its own market's last known
prices exactly like an ordinary end-of-day close, and a fresh session starts
immediately on the newly-open exchange. If all 4 are closed (the daily dead
zone between US close and NSE open), the tick is a no-op, same as today's
single-exchange behavior.

Each tick, the Investment Planner picks which symbols to run, the supervisor
runs the full committee pipeline per symbol, and positions are force-closed
once the session ends (real market close, or replay data exhausted)."""

from __future__ import annotations

import logging

from app.agents.planner import InvestmentPlanner
from app.config import get_settings
from app.data import exchanges, fx
from app.data.exchanges import Exchange
from app.data.market_data import MarketDataProvider
from app.db.models import Position, utcnow
from app.db.session import SessionLocal
from app.orchestration import supervisor
from app.reporting import audit_log, pdf_export
from app.trading import execution_engine

logger = logging.getLogger("session_runner")


class SessionRunner:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.provider = MarketDataProvider(self.settings.data_mode)
        self.planner = InvestmentPlanner(max_symbols_per_tick=self.settings.max_symbols_per_tick)

    def _current_exchange(self) -> Exchange | None:
        if self.settings.data_mode == "live":
            return exchanges.get_open_exchange()
        return exchanges.get_exchange(self.settings.replay_exchange)

    def run_tick(self) -> None:
        db = SessionLocal()
        try:
            current_exchange = self._current_exchange()
            if current_exchange is None:
                audit_log.log_event(db, "tick_skipped", {"reason": "all exchanges closed", "mode": "live"})
                return

            portfolio = execution_engine.get_active_portfolio(db, exchange=current_exchange.code)
            if portfolio.status != "active":
                return

            if self.settings.data_mode == "live" and portfolio.exchange != current_exchange.code:
                # A different market is now open than the one this session was trading -
                # roll the session over: close out the old one on its own exchange's
                # prices, then start a fresh session tagged for the newly-open market.
                old_watchlist = list(exchanges.get_exchange(portfolio.exchange).watchlist)
                self._close_session(db, portfolio, old_watchlist)
                portfolio = execution_engine.get_active_portfolio(db, exchange=current_exchange.code)

            watchlist = list(current_exchange.watchlist)
            open_symbols = [p.symbol for p in db.query(Position).filter_by(portfolio_id=portfolio.id, status="open").all()]
            symbols = self.planner.plan_tick(watchlist, open_symbols)

            for sym in symbols:
                try:
                    supervisor.run_committee_for_symbol(db, self.provider, sym, watchlist, execute=True, exchange=current_exchange)
                except Exception as exc:
                    logger.exception("Committee run failed for %s", sym)
                    audit_log.log_event(db, "tick_error", {"symbol": sym, "error": str(exc)})

            self.provider.advance_all(watchlist)

            if self._session_should_end(current_exchange, watchlist):
                self._close_session(db, portfolio, watchlist)
        finally:
            db.close()

    def _session_should_end(self, exchange: Exchange, watchlist: list[str]) -> bool:
        if self.settings.data_mode == "live":
            return exchange.minutes_to_close() <= self.settings.tick_minutes
        return all(self.provider.is_session_exhausted(s) for s in watchlist)

    def close_now(self) -> None:
        """Force-close the active session immediately (manual override, e.g. from the API)."""
        db = SessionLocal()
        try:
            portfolio = execution_engine.get_active_portfolio(db)
            if portfolio.status == "active":
                watchlist = list(exchanges.get_exchange(portfolio.exchange).watchlist)
                self._close_session(db, portfolio, watchlist)
        finally:
            db.close()

    def _close_session(self, db, portfolio, watchlist: list[str]) -> None:
        # force_close_all needs INR-equivalent prices, same as every other price
        # that enters the ledger - get_latest_price() returns the exchange's own
        # local currency, so convert it here just like the regular tick path does.
        fx_rate = fx.get_fx_rate(exchanges.get_exchange(portfolio.exchange).currency)
        price_lookup = {}
        for s in watchlist:
            try:
                price_lookup[s] = self.provider.get_latest_price(s) * fx_rate
            except Exception:
                continue

        execution_engine.force_close_all(db, portfolio, price_lookup)
        portfolio.status = "closed"
        portfolio.session_end = utcnow()
        db.add(portfolio)
        db.commit()

        report_path = pdf_export.generate_session_report(db, portfolio)
        audit_log.log_event(db, "session_closed", {"portfolio_id": portfolio.id, "report_path": report_path})
        logger.info("Session closed (%s). Report at %s", portfolio.exchange, report_path)
