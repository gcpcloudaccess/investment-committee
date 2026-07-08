from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


TradeAction = Literal["BUY", "SELL", "HOLD"]
CriticStance = Literal["support", "caution", "oppose"]


@dataclass(frozen=True)
class TradeProposal:
    action: TradeAction
    symbol: str
    asset_class: str
    sector: str
    country: str
    horizon_days: int
    rationale: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TradeProposal":
        return cls(
            action=str(payload.get("action", "HOLD")).upper(),  # type: ignore[arg-type]
            symbol=str(payload.get("symbol", "UNKNOWN")).upper(),
            asset_class=str(payload.get("asset_class", "equity")).lower(),
            sector=str(payload.get("sector", "unknown")).lower(),
            country=str(payload.get("country", "unknown")).upper(),
            horizon_days=int(payload.get("horizon_days", 30)),
            rationale=str(payload.get("rationale", "")),
        )


@dataclass(frozen=True)
class MacroSnapshot:
    inflation_yoy: float | None = None
    policy_rate: float | None = None
    policy_bias: str = "neutral"
    gdp_growth_yoy: float | None = None
    pmi: float | None = None
    currency_change_30d_pct: float | None = None
    liquidity_condition: str = "neutral"
    yield_curve_slope_bps: float | None = None
    fiscal_impulse: str = "neutral"
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MacroSnapshot":
        known = {
            "inflation_yoy",
            "policy_rate",
            "policy_bias",
            "gdp_growth_yoy",
            "pmi",
            "currency_change_30d_pct",
            "liquidity_condition",
            "yield_curve_slope_bps",
            "fiscal_impulse",
        }
        return cls(
            inflation_yoy=_float_or_none(payload.get("inflation_yoy")),
            policy_rate=_float_or_none(payload.get("policy_rate")),
            policy_bias=str(payload.get("policy_bias", "neutral")).lower(),
            gdp_growth_yoy=_float_or_none(payload.get("gdp_growth_yoy")),
            pmi=_float_or_none(payload.get("pmi")),
            currency_change_30d_pct=_float_or_none(payload.get("currency_change_30d_pct")),
            liquidity_condition=str(payload.get("liquidity_condition", "neutral")).lower(),
            yield_curve_slope_bps=_float_or_none(payload.get("yield_curve_slope_bps")),
            fiscal_impulse=str(payload.get("fiscal_impulse", "neutral")).lower(),
            extras={k: v for k, v in payload.items() if k not in known},
        )


@dataclass(frozen=True)
class MarketSnapshot:
    index_trend_30d_pct: float | None = None
    sector_trend_30d_pct: float | None = None
    volatility_percentile: float | None = None
    credit_spread_change_30d_bps: float | None = None
    commodity_pressure: str = "neutral"
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MarketSnapshot":
        known = {
            "index_trend_30d_pct",
            "sector_trend_30d_pct",
            "volatility_percentile",
            "credit_spread_change_30d_bps",
            "commodity_pressure",
        }
        return cls(
            index_trend_30d_pct=_float_or_none(payload.get("index_trend_30d_pct")),
            sector_trend_30d_pct=_float_or_none(payload.get("sector_trend_30d_pct")),
            volatility_percentile=_float_or_none(payload.get("volatility_percentile")),
            credit_spread_change_30d_bps=_float_or_none(payload.get("credit_spread_change_30d_bps")),
            commodity_pressure=str(payload.get("commodity_pressure", "neutral")).lower(),
            extras={k: v for k, v in payload.items() if k not in known},
        )


@dataclass(frozen=True)
class EvidenceItem:
    label: str
    direction: Literal["positive", "negative", "neutral"]
    score: int
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "direction": self.direction,
            "score": self.score,
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class CritiqueResult:
    agent_name: str
    stance: CriticStance
    directional_confidence: int
    summary: str
    evidence: list[EvidenceItem]
    critic_comments: list[str]
    stress_scenarios: list[str]
    consensus_payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "stance": self.stance,
            "directional_confidence": self.directional_confidence,
            "summary": self.summary,
            "evidence": [item.to_dict() for item in self.evidence],
            "critic_comments": self.critic_comments,
            "stress_scenarios": self.stress_scenarios,
            "consensus_payload": self.consensus_payload,
        }


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

