"""Position Sizing Agent: turns a consensus verdict + confidence into a
concrete order quantity, respecting the ₹10,000 capital / 1:2 leverage cap and
scaling exposure with both confidence and the risk regime.

Leverage is flexible, not a flat always-on 2x: any trade that actually clears
the committee's decisive threshold already represents real conviction, so it
gets meaningful leverage by default (BASE_LEVERAGE), scaling up toward the
configured ceiling (settings.leverage, default 2x for 1:2) as confidence and
risk quality improve further. This system's directional confidence realistically
ranges ~18-40% for trades that clear the decisive bar (see
trust_weighted_consensus.py) - scaling against the full 0-100% range would
make leverage nearly impossible to exercise in practice, which is exactly the
bug this was calibrated to fix: real trades were sizing well under available
*cash*, never even touching margin, let alone approaching the 2x ceiling."""

from __future__ import annotations

from app.config import get_settings

# Any trade that fires already cleared the decisive threshold - start it here rather
# than near 1.0x, so leverage is actually exercised rather than sitting unused.
BASE_LEVERAGE = 1.4
# Directional confidence treated as "maximally convinced" for leverage-scaling purposes -
# calibrated against this system's realistic range, not the full 0-100% scale.
STRONG_CONFIDENCE_PCT = 30.0


def size_position(
    directional_confidence_pct: float,
    risk_level: str,
    price: float,
    current_open_exposure: float,
    cash_available: float,
) -> dict:
    settings = get_settings()
    max_leverage = settings.leverage  # hard ceiling, e.g. 2.0 for 1:2
    max_exposure = settings.max_exposure_inr  # starting_capital * max_leverage, portfolio-wide ceiling
    remaining_exposure_budget = max(max_exposure - current_open_exposure, 0.0)

    if price <= 0 or remaining_exposure_budget <= 0:
        return {
            "quantity": 0, "notional": 0.0, "reason": "No exposure budget remaining under leverage cap.",
            "leverage_used": 1.0, "margin_used_inr": 0.0, "max_leverage": max_leverage,
        }

    confidence_fraction = max(0.0, min(directional_confidence_pct / 100.0, 1.0))
    risk_multiplier = {"LOW": 1.0, "MEDIUM": 0.65, "HIGH": 0.35, "EXTREME": 0.15}.get(risk_level, 0.65)

    # Effective leverage for THIS trade: BASE_LEVERAGE for any decisive-but-modest signal,
    # scaling up to max_leverage as confidence approaches STRONG_CONFIDENCE_PCT and risk is low.
    strength = max(0.0, min(1.0, directional_confidence_pct / STRONG_CONFIDENCE_PCT))
    leverage_used = round(min(max_leverage, BASE_LEVERAGE + strength * risk_multiplier * (max_leverage - BASE_LEVERAGE)), 3)

    # Buying power for this trade: available cash amplified by the leverage above, capped by
    # the portfolio-wide exposure budget so the overall 2x-of-starting-capital ceiling holds
    # even across multiple open positions.
    buying_power = min(cash_available * leverage_used, remaining_exposure_budget)

    # Deploy fraction now describes how much of THIS TRADE's leveraged buying power to commit
    # (not a small slice of the total portfolio budget) - 50% at minimum decisive confidence,
    # up to 90% at strong confidence and low risk, so leverage actually gets drawn on rather
    # than being capped by an unrelated, overly conservative slice of the total budget.
    deploy_fraction = 0.5 + 0.4 * confidence_fraction * risk_multiplier
    target_notional = buying_power * deploy_fraction

    quantity = int(target_notional // price)
    notional = round(quantity * price, 2)
    margin_used_inr = round(max(0.0, notional - cash_available), 2)

    return {
        "quantity": quantity,
        "notional": notional,
        "deploy_fraction": round(deploy_fraction, 3),
        "remaining_exposure_budget": round(remaining_exposure_budget, 2),
        "risk_multiplier": risk_multiplier,
        "leverage_used": leverage_used,
        "margin_used_inr": margin_used_inr,
        "max_leverage": max_leverage,
    }
