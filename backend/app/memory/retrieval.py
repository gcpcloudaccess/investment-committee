"""Retrieval layer for the committee's memory: pulls a symbol's recent past
Decision rows (and, where a resulting trade has since closed, its realized
outcome) so agents can factor in what happened last time rather than
analyzing each symbol as if the committee had no history with it.

No embeddings/vector DB - this is the "SQLite decision history + recency
retrieval" memory layer from the architecture plan (PGVector was never a
hard requirement; embeddings would add an API dependency for no real benefit
at this history size). Recency + symbol match is intentionally simple and
fully explainable, consistent with the rest of this system's design bias
toward deterministic, inspectable logic over opaque similarity search."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Decision


def get_relevant_history(db: Session, symbol: str, limit: int = 3) -> list[dict]:
    decisions = (
        db.query(Decision)
        .filter_by(symbol=symbol)
        .order_by(Decision.timestamp.desc())
        .limit(limit)
        .all()
    )

    history: list[dict] = []
    for d in decisions:
        outcome = "no trade"
        for trade in d.trades:
            position = trade.position
            if position is not None and position.status == "closed" and position.realized_pnl is not None:
                sign = "+" if position.realized_pnl >= 0 else ""
                outcome = f"closed {sign}Rs{position.realized_pnl:.2f}"
                break
            if position is not None and position.status == "open":
                outcome = "still open"
                break
        else:
            if d.executed:
                outcome = "executed, outcome pending"

        history.append({
            "timestamp": d.timestamp,
            "verdict": d.verdict,
            "confidence": d.directional_confidence,
            "reasoning_snippet": (d.consensus_reasoning or "")[:160],
            "outcome": outcome,
        })

    return history
