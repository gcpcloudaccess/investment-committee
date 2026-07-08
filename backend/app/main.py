from __future__ import annotations

import datetime as dt
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.agents import allocation_planner
from app.config import get_settings
from app.data import exchanges as exchange_registry
from app.data import fundamentals as fundamentals_data
from app.data import fx, market_data
from app.data.market_data import MarketDataProvider
from app.db.models import AgentVote, AuditLog, Decision, Portfolio, Position, Trade
from app.db.session import get_db, init_db
from app.orchestration import supervisor
from app.orchestration.session_runner import SessionRunner
from app.reporting import pdf_export, visualization
from app.trading import execution_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

settings = get_settings()
app = FastAPI(title="Autonomous Multi-Agent Investment Committee")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_scheduler = BackgroundScheduler()
_session_runner = SessionRunner()
_search_provider = MarketDataProvider("live" if settings.data_mode == "live" else "replay")


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    _scheduler.add_job(_session_runner.run_tick, "interval", minutes=settings.tick_minutes, id="session_tick", replace_existing=True)
    _scheduler.start()
    logger.info("Backend started. data_mode=%s tick_minutes=%s llm_key_configured=%s", settings.data_mode, settings.tick_minutes, settings.llm_key_configured)


@app.on_event("shutdown")
def on_shutdown() -> None:
    _scheduler.shutdown(wait=False)


# ---------------------------------------------------------------- helpers
def _position_dict(p: Position) -> dict:
    return {
        "id": p.id, "symbol": p.symbol, "side": p.side, "quantity": p.quantity,
        "avg_price": p.avg_price, "status": p.status,
        "opened_at": p.opened_at.isoformat() if p.opened_at else None,
        "closed_at": p.closed_at.isoformat() if p.closed_at else None,
        "exit_price": p.exit_price, "realized_pnl": p.realized_pnl,
        "exchange": p.exchange, "currency": p.currency,
    }


def _trade_dict(t: Trade) -> dict:
    return {
        "id": t.id, "portfolio_id": t.portfolio_id, "symbol": t.symbol, "action": t.action, "quantity": t.quantity,
        "price": t.price, "gross_value": t.gross_value, "total_costs": t.total_costs,
        "cost_breakdown": t.cost_breakdown_json, "net_cash_impact": t.net_cash_impact,
        "timestamp": t.timestamp.isoformat() if t.timestamp else None,
        "exchange": t.exchange, "currency": t.currency, "price_local": t.price_local, "fx_rate_to_inr": t.fx_rate_to_inr,
    }


def _decision_dict(d: Decision, db: Session) -> dict:
    votes = db.query(AgentVote).filter_by(decision_id=d.id).all()
    return {
        "id": d.id, "symbol": d.symbol, "timestamp": d.timestamp.isoformat() if d.timestamp else None,
        "verdict": d.verdict, "directional_confidence": d.directional_confidence,
        "consensus_reasoning": d.consensus_reasoning, "evidence": d.evidence_json,
        "alternatives": d.alternatives_json, "critic_feedback": d.critic_feedback_json,
        "expected_risk_return": d.expected_risk_return_json, "executed": d.executed,
        "agent_votes": [
            {
                "agent_name": v.agent_name, "agent_type": v.agent_type, "action": v.action,
                "confidence": v.confidence, "reasoning": v.reasoning,
                "evidence": v.evidence_json.get("evidence", []), "weight_used": v.weight_used,
            }
            for v in votes
        ],
    }


# ---------------------------------------------------------------- portfolio / dashboard
def _ist_date(ts: dt.datetime | None) -> dt.date | None:
    """SQLite drops tzinfo on round-trip even for DateTime(timezone=True) columns,
    so timestamps come back naive despite being written via utcnow() (which IS
    timezone-aware). Treat a naive value as UTC before converting to IST, or
    date comparisons silently use the server's local timezone instead."""
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return ts.astimezone(market_data.IST).date()


def _portfolio_total_value(db: Session, portfolio: Portfolio) -> float:
    """Mark-to-market total value of the ACTIVE portfolio (long-only: value of an
    open position is simply current price x quantity). Closed portfolios have no
    open positions after force-close, so their value is just cash_inr - use that
    directly rather than calling this helper for a closed portfolio.

    get_latest_price() returns a symbol's own local currency (USD/GBP/SGD for a
    foreign listing), so it must be converted back to INR-equivalent here just
    like every other price in the pipeline (see supervisor.py) - otherwise a
    live SGX/LSE/NYSE position's mark-to-market value would silently be treated
    as if it were already in rupees."""
    positions = db.query(Position).filter_by(portfolio_id=portfolio.id, status="open").all()
    mtm_value = 0.0
    for p in positions:
        try:
            price_local = _search_provider.get_latest_price(p.symbol)
            price = price_local * fx.get_fx_rate(p.currency)
        except Exception:
            price = p.avg_price  # already INR-equivalent (stored that way at open time)
        mtm_value += price * p.quantity
    return portfolio.cash_inr + mtm_value


@app.get("/portfolio")
def get_portfolio(db: Session = Depends(get_db)) -> dict:
    portfolio = execution_engine.get_active_portfolio(db)
    positions = db.query(Position).filter_by(portfolio_id=portfolio.id, status="open").all()

    total_value = _portfolio_total_value(db, portfolio)
    mtm_value = total_value - portfolio.cash_inr
    net_profit = total_value - portfolio.starting_capital

    # "Overall" aggregates every session (portfolio row) this app has ever run, not just
    # today's: each session independently starts at settings.starting_capital_inr (₹10,000,
    # non-compounding) and force-closes with 0 open positions, so a closed session's ending
    # value is simply its final cash balance; the active session uses today's mark-to-market.
    all_portfolios = db.query(Portfolio).all()
    overall_starting_capital = 0.0
    overall_ending_value = 0.0
    closed_sessions = 0
    for p in all_portfolios:
        overall_starting_capital += p.starting_capital
        if p.id == portfolio.id:
            overall_ending_value += total_value
        else:
            overall_ending_value += p.cash_inr
            closed_sessions += 1
    overall_net_profit = overall_ending_value - overall_starting_capital
    overall_return_pct = round((overall_net_profit / overall_starting_capital) * 100, 2) if overall_starting_capital else 0.0

    closed_positions = db.query(Position).filter_by(portfolio_id=portfolio.id, status="closed").all()
    closed_count = len(closed_positions)
    winning_count = sum(1 for p in closed_positions if (p.realized_pnl or 0) > 0)
    win_rate_pct = round(winning_count / closed_count * 100, 1) if closed_count else 0.0

    return {
        "portfolio_id": portfolio.id,
        "status": portfolio.status,
        "exchange": portfolio.exchange,
        "exchange_label": exchange_registry.get_exchange(portfolio.exchange).label,
        "starting_capital": portfolio.starting_capital,
        "cash": round(portfolio.cash_inr, 2),
        "open_positions_value": round(mtm_value, 2),
        "total_value": round(total_value, 2),
        # Intraday = this session only (kept as the original field names for compatibility).
        "net_profit": round(net_profit, 2),
        "total_return_pct": round((net_profit / portfolio.starting_capital) * 100, 2) if portfolio.starting_capital else 0.0,
        "leverage": portfolio.leverage,
        "positions": [_position_dict(p) for p in positions],
        "session_start": portfolio.session_start.isoformat() if portfolio.session_start else None,
        "session_end": portfolio.session_end.isoformat() if portfolio.session_end else None,
        "closed_trades_count": closed_count,
        "winning_trades_count": winning_count,
        "win_rate_pct": win_rate_pct,
        "overall": {
            "total_sessions": len(all_portfolios),
            "closed_sessions": closed_sessions,
            "starting_capital": round(overall_starting_capital, 2),
            "ending_value": round(overall_ending_value, 2),
            "net_profit": round(overall_net_profit, 2),
            "return_pct": overall_return_pct,
        },
    }


@app.get("/portfolio/equity-curve")
def get_equity_curve(db: Session = Depends(get_db)) -> dict:
    portfolio = execution_engine.get_active_portfolio(db)
    trades = db.query(Trade).filter_by(portfolio_id=portfolio.id).order_by(Trade.timestamp).all()

    timestamps = [portfolio.session_start.isoformat()]
    values = [portfolio.starting_capital]
    markers = []
    running = portfolio.starting_capital
    for t in trades:
        running += t.net_cash_impact
        timestamps.append(t.timestamp.isoformat())
        values.append(round(running, 2))
        markers.append({"timestamp": t.timestamp.isoformat(), "value": round(running, 2), "action": t.action})

    fig = visualization.build_equity_curve(timestamps, values, markers)
    return {"figure": fig, "trade_markers": markers}


@app.get("/trades")
def list_trades(limit: int = 200, current_session_only: bool = False, db: Session = Depends(get_db)) -> list[dict]:
    """Retained and appended across every session/exchange by default - a
    session rolling over to a new exchange (see session_runner.py) closes the
    old Portfolio row and opens a new one, and scoping this query to only the
    active portfolio_id would make trade history appear to reset on every
    rollover even though nothing was actually lost from the database.
    current_session_only=True opts back into the old single-session view."""
    query = db.query(Trade)
    if current_session_only:
        portfolio = execution_engine.get_active_portfolio(db)
        query = query.filter_by(portfolio_id=portfolio.id)
    trades = query.order_by(Trade.timestamp.desc()).limit(limit).all()
    return [_trade_dict(t) for t in trades]


@app.get("/market/chart/{symbol}")
def get_market_chart(symbol: str, db: Session = Depends(get_db)) -> dict:
    bars = _search_provider.get_recent_bars(symbol, lookback_bars=100)
    if bars.empty:
        raise HTTPException(status_code=404, detail=f"No bar data available for {symbol}")

    portfolio = execution_engine.get_active_portfolio(db)
    trades = (
        db.query(Trade)
        .filter_by(portfolio_id=portfolio.id, symbol=symbol)
        .order_by(Trade.timestamp)
        .all()
    )
    trade_points = [{"timestamp": t.timestamp.isoformat(), "action": t.action, "price": t.price} for t in trades]

    figure = visualization.build_price_chart(symbol, bars, trade_points)
    return {"symbol": symbol, "latest_price": float(bars["Close"].iloc[-1]), "figure": figure}


# ---------------------------------------------------------------- watchlist / search
@app.get("/watchlist")
def get_watchlist(db: Session = Depends(get_db)) -> list[dict]:
    out = []
    for symbol in settings.watchlist_symbols:
        latest = db.query(Decision).filter_by(symbol=symbol).order_by(Decision.timestamp.desc()).first()
        try:
            price = _search_provider.get_latest_price(symbol)
        except Exception:
            price = None
        out.append({
            "symbol": symbol, "price": price,
            "latest_verdict": latest.verdict if latest else None,
            "latest_confidence": latest.directional_confidence if latest else None,
            "latest_decision_id": latest.id if latest else None,
            "latest_timestamp": latest.timestamp.isoformat() if latest else None,
        })
    return out


@app.post("/analyze/{symbol}")
def analyze_symbol(symbol: str, db: Session = Depends(get_db)) -> dict:
    try:
        result = supervisor.run_committee_for_symbol(db, _search_provider, symbol, settings.watchlist_symbols, execute=False)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Analysis failed for {symbol}: {exc}") from exc
    return result


# ---------------------------------------------------------------- committee meetings / decisions
@app.get("/decisions")
def list_decisions(limit: int = 50, db: Session = Depends(get_db)) -> list[dict]:
    decisions = db.query(Decision).order_by(Decision.timestamp.desc()).limit(limit).all()
    return [_decision_dict(d, db) for d in decisions]


@app.get("/decisions/{decision_id}")
def get_decision(decision_id: int, db: Session = Depends(get_db)) -> dict:
    d = db.get(Decision, decision_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    return _decision_dict(d, db)


# ---------------------------------------------------------------- audit / reports
@app.get("/audit-log")
def get_audit_log(limit: int = 100, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit).all()
    return [{"id": r.id, "timestamp": r.timestamp.isoformat(), "event_type": r.event_type, "payload": r.payload_json} for r in rows]


@app.post("/reports/generate")
def generate_report(db: Session = Depends(get_db)) -> dict:
    portfolio = execution_engine.get_active_portfolio(db)
    path = pdf_export.generate_session_report(db, portfolio)
    return {"report_path": path}


# ---------------------------------------------------------------- session controls
@app.post("/session/tick")
def trigger_tick() -> dict:
    _session_runner.run_tick()
    return {"status": "tick executed"}


@app.post("/session/close")
def close_session() -> dict:
    _session_runner.close_now()
    return {"status": "session closed"}


@app.post("/session/pause")
def pause_ticking() -> dict:
    """Pauses the automatic scheduled tick (the source of nearly all LLM/token
    usage) without touching open positions or the active session - "Run Tick
    Now" still works for a deliberate one-off analysis while paused."""
    _scheduler.pause_job("session_tick")
    return {"status": "paused"}


@app.post("/session/resume")
def resume_ticking() -> dict:
    _scheduler.resume_job("session_tick")
    return {"status": "resumed"}


@app.get("/session/tick-status")
def tick_status() -> dict:
    job = _scheduler.get_job("session_tick")
    paused = job is None or job.next_run_time is None
    return {
        "paused": paused,
        "tick_minutes": settings.tick_minutes,
        "next_run_time": job.next_run_time.isoformat() if job and job.next_run_time else None,
    }


@app.get("/settings")
def get_settings_view() -> dict:
    # Real-world check, independent of data_mode - this answers "which exchange
    # is actually open right now", never a stand-in for the replay session's
    # exchange choice (that's session_exchange below). Conflating the two was
    # a real bug: replay mode used to report the replay pick here even when
    # that exchange was genuinely closed, which reads as a live status claim
    # it wasn't making.
    really_open = exchange_registry.get_open_exchange()
    session_exchange = really_open if settings.data_mode == "live" else exchange_registry.get_exchange(settings.replay_exchange)
    return {
        "llm_provider": settings.llm_provider,
        "llm_key_configured": settings.llm_key_configured,
        "data_mode": settings.data_mode,
        "starting_capital_inr": settings.starting_capital_inr,
        "leverage": settings.leverage,
        "session_hours": settings.session_hours,
        "tick_minutes": settings.tick_minutes,
        "watchlist": settings.watchlist_symbols,
        "risk_tolerance": settings.risk_tolerance,
        "currently_open_exchange": really_open.code if really_open else None,
        "session_exchange": session_exchange.code if session_exchange else None,
        "exchanges": [
            {
                "code": ex.code, "label": ex.label, "currency": ex.currency,
                "open_time": ex.open_time.strftime("%H:%M"), "close_time": ex.close_time.strftime("%H:%M"),
                "timezone": str(ex.tz), "watchlist": list(ex.watchlist), "is_open": ex.is_open(),
            }
            for ex in exchange_registry.ALL_EXCHANGES
        ],
    }


@app.get("/planner/allocation-plan")
def get_allocation_plan(db: Session = Depends(get_db)) -> dict:
    """Investment Planner Agent: current session's asset-allocation caps
    (per-symbol, per-sector) and profit/loss goals, plus live progress toward
    those goals for the trading day so far."""
    portfolio = execution_engine.get_active_portfolio(db)
    plan = allocation_planner.build_plan(settings.risk_tolerance, portfolio.starting_capital, portfolio.leverage * portfolio.starting_capital)

    # "Today's P&L" must span every session that started today, not just the currently
    # active one - a session force-closes at market close and a fresh one auto-opens the
    # moment any endpoint is next called, so a single trading day can span 2+ Portfolio
    # rows. Summing only the active session's P&L silently drops any loss/profit already
    # realized earlier today in a session that has since closed and been replaced.
    today_ist = dt.datetime.now(market_data.IST).date()
    running_pnl_estimate = 0.0
    for p in db.query(Portfolio).all():
        session_date = _ist_date(p.session_start)
        if session_date != today_ist:
            continue
        if p.id == portfolio.id:
            ending_value = _portfolio_total_value(db, portfolio)
        else:
            ending_value = p.cash_inr  # closed sessions hold 0 open positions after force-close
        running_pnl_estimate += ending_value - p.starting_capital
    running_pnl_estimate = round(running_pnl_estimate, 2)

    sector_exposure: dict[str, float] = {}
    for p in execution_engine.get_open_positions(db, portfolio):
        sector = fundamentals_data.get_sector(p.symbol)
        sector_exposure[sector] = sector_exposure.get(sector, 0.0) + p.quantity * p.avg_price

    return {
        "risk_tolerance": plan.risk_tolerance,
        "symbol_cap_inr": plan.symbol_cap_inr,
        "sector_cap_inr": plan.sector_cap_inr,
        "profit_target_inr": plan.profit_target_inr,
        "loss_limit_inr": plan.loss_limit_inr,
        "reasoning": plan.reasoning,
        "running_pnl_estimate": running_pnl_estimate,
        "goal_hit": running_pnl_estimate >= plan.profit_target_inr or running_pnl_estimate <= plan.loss_limit_inr,
        "sector_exposure": {k: round(v, 2) for k, v in sector_exposure.items()},
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "time": dt.datetime.now(dt.timezone.utc).isoformat()}
