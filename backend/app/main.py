from __future__ import annotations

import datetime as dt
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import get_settings
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
    }


def _trade_dict(t: Trade) -> dict:
    return {
        "id": t.id, "symbol": t.symbol, "action": t.action, "quantity": t.quantity,
        "price": t.price, "gross_value": t.gross_value, "total_costs": t.total_costs,
        "cost_breakdown": t.cost_breakdown_json, "net_cash_impact": t.net_cash_impact,
        "timestamp": t.timestamp.isoformat() if t.timestamp else None,
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
@app.get("/portfolio")
def get_portfolio(db: Session = Depends(get_db)) -> dict:
    portfolio = execution_engine.get_active_portfolio(db)
    positions = db.query(Position).filter_by(portfolio_id=portfolio.id, status="open").all()

    # Long-only build: mark-to-market value of an open position is simply current price x quantity.
    mtm_value = 0.0
    for p in positions:
        try:
            price = _search_provider.get_latest_price(p.symbol)
        except Exception:
            price = p.avg_price
        mtm_value += price * p.quantity

    total_value = portfolio.cash_inr + mtm_value
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

    return {
        "portfolio_id": portfolio.id,
        "status": portfolio.status,
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
def list_trades(db: Session = Depends(get_db)) -> list[dict]:
    portfolio = execution_engine.get_active_portfolio(db)
    trades = db.query(Trade).filter_by(portfolio_id=portfolio.id).order_by(Trade.timestamp.desc()).all()
    return [_trade_dict(t) for t in trades]


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


@app.get("/settings")
def get_settings_view() -> dict:
    return {
        "llm_provider": settings.llm_provider,
        "llm_key_configured": settings.llm_key_configured,
        "data_mode": settings.data_mode,
        "starting_capital_inr": settings.starting_capital_inr,
        "leverage": settings.leverage,
        "session_hours": settings.session_hours,
        "tick_minutes": settings.tick_minutes,
        "watchlist": settings.watchlist_symbols,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "time": dt.datetime.now(dt.timezone.utc).isoformat()}
