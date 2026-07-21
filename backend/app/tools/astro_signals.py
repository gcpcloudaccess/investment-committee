"""Interpretive layer over app/tools/planetary_positions.py: turns a raw
planetary snapshot into a bounded, per-symbol trading signal.

This is explicitly a traditional/folklore-based heuristic (Vedic "financial
astrology"), not an empirically validated model - unlike every other tool in
this package, it has no peer-reviewed or backtested basis. It's built to the
same shape as the other tools (blend_signals-compatible {action, confidence,
evidence, metrics} dict) so it plugs into the committee the same way, but
deliberately capped at a low confidence ceiling and given a low
expertise_relevance weight in the consensus (see
app/consensus/trust_weighted_consensus.py) so it can nudge, not drive, the
final verdict.

Classical planet-asset associations used here (all standard, well-documented
Vedic/Jyotish correspondences, not invented for this app):
  - Jupiter ("Guru"): wealth, expansion, growth -> broad equity index.
  - Sun ("Surya"): gold.
  - Moon ("Chandra"): silver.
  - Mercury ("Budh"): commerce/trade/contracts -> retrograde is the
    traditional "avoid signing new agreements" caution, applied broadly.
Exaltation/debilitation signs (Sun: Aries/Libra, Moon: Taurus/Scorpio,
Jupiter: Cancer/Capricorn) are standard classical Jyotish dignities.
"""

from __future__ import annotations

import datetime as dt

from app.tools import planetary_positions as pp

# Nakshatras folk-classed as auspicious for starting new ventures / financial
# gain in muhurta (electional astrology) tradition.
_AUSPICIOUS_NAKSHATRAS = {"Pushya", "Punarvasu", "Hasta", "Anuradha", "Revati"}

_CONFIDENCE_FLOOR = 0.15
_CONFIDENCE_CEILING = 0.5  # deliberately capped - this signal should never out-shout the empirical analysts


def _clip(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _score_to_action(score: float) -> str:
    if score >= 0.3:
        return "BUY"
    if score <= -0.3:
        return "SELL"
    if abs(score) < 0.1:
        return "WAIT"
    return "HOLD"


def _symbol_category(symbol: str) -> str:
    upper = symbol.upper()
    if "GOLD" in upper:
        return "gold"
    if "SILVER" in upper:
        return "silver"
    return "index"  # NIFTYBEES.NS and anything else falls back to the broad-index rules


def analyze(symbol: str, when: dt.datetime | None = None) -> dict:
    snap = pp.get_snapshot(when)
    category = _symbol_category(symbol)

    evidence: list[str] = [
        f"[Astro disclaimer] Traditional Vedic (Jyotish) heuristic, not empirically validated - "
        f"treated as a low-weight nudge, not a primary signal.",
        f"Moon: {snap.moon_phase_name} ({snap.moon_illumination:.0%} illuminated, "
        f"{'waxing' if snap.moon_waxing else 'waning'}), in {snap.moon_nakshatra} nakshatra, {snap.moon_rashi} rashi.",
    ]
    score = 0.0

    # Shared factor: Mercury retrograde - traditional caution against new
    # contracts/agreements, applied to all three instruments.
    if snap.retrograde["mercury"]:
        score -= 0.25
        evidence.append("Mercury is retrograde - traditional caution against new commitments/contracts.")
    else:
        evidence.append("Mercury is direct - no communication/contract caution flagged.")

    # Shared factor: Moon waxing/waning - short-term accumulation vs.
    # distribution mood, weighted higher for silver (Moon's own metal).
    moon_weight = 0.20 if category == "silver" else 0.10
    if snap.moon_waxing:
        score += moon_weight
    else:
        score -= moon_weight

    if category == "index":
        if snap.retrograde["jupiter"]:
            score -= 0.3
            evidence.append("Jupiter (growth/expansion) is retrograde - a traditionally introspective, not expansive, phase for broad equity gains.")
        else:
            score += 0.15
            evidence.append("Jupiter (growth/expansion) is direct - traditionally supportive of expansion.")
        if snap.moon_nakshatra in _AUSPICIOUS_NAKSHATRAS:
            score += 0.15
            evidence.append(f"Moon's {snap.moon_nakshatra} nakshatra is traditionally considered auspicious for new financial ventures.")
        if snap.jupiter_rashi == "Cancer":
            score += 0.15
            evidence.append("Jupiter is in its sign of exaltation (Cancer, sidereal) - traditionally its strongest placement.")
        elif snap.jupiter_rashi == "Capricorn":
            score -= 0.15
            evidence.append("Jupiter is in its sign of debilitation (Capricorn, sidereal) - traditionally its weakest placement.")

    elif category == "gold":
        if snap.sun_rashi == "Aries":
            score += 0.2
            evidence.append("Sun (gold's classical ruler) is exalted in Aries (sidereal) - traditionally its strongest placement.")
        elif snap.sun_rashi == "Libra":
            score -= 0.2
            evidence.append("Sun (gold's classical ruler) is debilitated in Libra (sidereal) - traditionally its weakest placement.")
        else:
            evidence.append(f"Sun (gold's classical ruler) is in {snap.sun_rashi} (sidereal) - a neutral placement.")
        if snap.retrograde["jupiter"]:
            score -= 0.2
            evidence.append("Jupiter (wealth significator) is retrograde - a traditionally cautious phase for safe-haven accumulation.")
        else:
            score += 0.2
            evidence.append("Jupiter (wealth significator) is direct - traditionally supportive of safe-haven accumulation.")

    else:  # silver
        if snap.moon_rashi == "Taurus":
            score += 0.25
            evidence.append("Moon (silver's classical ruler) is exalted in Taurus (sidereal) - traditionally its strongest placement.")
        elif snap.moon_rashi == "Scorpio":
            score -= 0.25
            evidence.append("Moon (silver's classical ruler) is debilitated in Scorpio (sidereal) - traditionally its weakest placement.")
        else:
            evidence.append(f"Moon (silver's classical ruler) is in {snap.moon_rashi} (sidereal) - a neutral placement.")

    score = _clip(score)
    action = _score_to_action(score)
    confidence = round(min(_CONFIDENCE_CEILING, max(_CONFIDENCE_FLOOR, _CONFIDENCE_FLOOR + abs(score) * 0.35)), 3)

    return {
        "action": action,
        "confidence": confidence,
        "evidence": evidence,
        "metrics": {
            "score": round(score, 3),
            "category": category,
            "ayanamsa_deg": snap.ayanamsa_deg,
            "moon_nakshatra": snap.moon_nakshatra,
            "moon_rashi": snap.moon_rashi,
            "sun_rashi": snap.sun_rashi,
            "jupiter_rashi": snap.jupiter_rashi,
            "moon_phase": snap.moon_phase_name,
            "moon_waxing": snap.moon_waxing,
            "mercury_retrograde": snap.retrograde["mercury"],
            "jupiter_retrograde": snap.retrograde["jupiter"],
        },
    }
