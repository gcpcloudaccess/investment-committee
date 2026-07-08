"""Position Sizing Agent: turns a consensus verdict + confidence into a
concrete order quantity, respecting the ₹10,000 capital / 1:2 leverage cap and
scaling exposure with both confidence and the risk regime.

Leverage itself is flexible, not a flat always-on 2x: the amount of margin
actually used for a given trade scales with how strong the committee's
conviction is (and how risky the setup looks), from ~1x (using only owned
cash) up to the configured ceiling (settings.leverage, default 2x) for a
high-confidence, low-risk setup. This lets a strong recommendation buy more
shares against the same capital ("additional buying... at lower cost" per
share of conviction), while a marginal signal doesn't quietly max out margin."""

from __future__ import annotations

from app.config import get_settings


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

    # Effective leverage for THIS trade: 1.0x (no margin, own capital only) at zero conviction,
    # scaling up toward the configured ceiling as confidence and risk quality improve. Never
    # exceeds max_leverage regardless of inputs.
    leverage_used = round(min(max_leverage, 1.0 + confidence_fraction * risk_multiplier * (max_leverage - 1.0)), 3)

    # Scale how much of the *remaining* exposure budget to deploy this trade:
    # base 20%, up to 60% at max confidence and low risk.
    deploy_fraction = 0.2 + 0.4 * confidence_fraction * risk_multiplier
    target_notional = remaining_exposure_budget * deploy_fraction

    # Buying power for this specific trade: available cash amplified by the confidence-scaled
    # leverage above (not a blanket max_leverage), so a weak-conviction trade doesn't silently
    # borrow the full 2x just because the portfolio-wide cap would technically allow it.
    buying_power = cash_available * leverage_used
    target_notional = min(target_notional, buying_power)

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
