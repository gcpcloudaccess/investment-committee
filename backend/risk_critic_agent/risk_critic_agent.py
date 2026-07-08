from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional


Decision = str
ModelCaller = Callable[[List[Dict[str, str]], Mapping[str, Any]], str]


PROMPT_PATH = Path(__file__).with_name("risk_critic_prompt.md")
SCHEMA_PATH = Path(__file__).with_name("risk_critic_schema.json")

REQUIRED_INPUT_FIELDS = (
    "proposed_action",
    "instrument",
    "time_horizon",
    "portfolio_context",
    "market_data",
    "supporting_evidence",
)

VALID_DECISIONS = {
    "approve_with_controls",
    "reduce_size",
    "delay_for_confirmation",
    "hedge_required",
    "reject",
    "insufficient_data",
}

VALID_RISK_RATINGS = {"low", "medium", "high", "critical"}
VALID_SEVERITIES = {"low", "medium", "high", "critical"}


@dataclass(frozen=True)
class RiskCriticAgent:
    """Portable wrapper for the Risk Critic investment committee agent.

    Pass any chat-model function as model_caller. The function should accept
    messages and model_options, then return the model's raw text response.
    """

    model_caller: Optional[ModelCaller] = None
    model_options: Optional[Mapping[str, Any]] = None

    def build_messages(self, payload: Mapping[str, Any]) -> List[Dict[str, str]]:
        prompt = PROMPT_PATH.read_text(encoding="utf-8")
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        user_payload = json.dumps(payload, indent=2, sort_keys=True)

        return [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (
                    "Review this investment proposal as the Risk Critic Agent.\n\n"
                    "Return JSON only and conform to this JSON Schema:\n"
                    f"{schema}\n\n"
                    "Input payload:\n"
                    f"{user_payload}"
                ),
            },
        ]

    def run(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        if self.model_caller is None:
            return self.insufficient_data_response(payload)

        raw_response = self.model_caller(
            self.build_messages(payload),
            self.model_options or {},
        )
        parsed = parse_json_object(raw_response)
        validate_output(parsed)
        return parsed

    def insufficient_data_response(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        missing = get_missing_input_fields(payload)
        missing_text = ", ".join(missing) if missing else "model_caller"
        return {
            "agent": "risk_critic",
            "decision": "insufficient_data",
            "risk_confidence_score": 90,
            "evidence_quality_score": 0,
            "overall_risk_rating": "high",
            "summary": f"Risk critique is data-limited. Missing required input: {missing_text}.",
            "top_risks": [
                {
                    "risk": "Incomplete trade proposal",
                    "severity": "critical",
                    "mechanism": "The agent lacks enough information to test downside, sizing, liquidity, and portfolio impact.",
                    "mitigation": "Provide the missing fields before trade approval.",
                }
            ],
            "scenario_analysis": [
                {
                    "scenario": "base_case",
                    "trigger": "Not assessable from supplied data.",
                    "expected_impact": "Unknown",
                    "approximate_loss_or_drawdown": "Cannot estimate",
                    "mitigation": "Provide instrument, action, horizon, market data, and thesis.",
                },
                {
                    "scenario": "bear_case",
                    "trigger": "Not assessable from supplied data.",
                    "expected_impact": "Unknown",
                    "approximate_loss_or_drawdown": "Cannot estimate",
                    "mitigation": "Provide volatility, liquidity, stop, and downside assumptions.",
                },
                {
                    "scenario": "stress_case",
                    "trigger": "Not assessable from supplied data.",
                    "expected_impact": "Unknown",
                    "approximate_loss_or_drawdown": "Cannot estimate",
                    "mitigation": "Provide portfolio exposures and risk budget.",
                },
            ],
            "portfolio_impact": {
                "assessment": "not_assessable",
                "missing": "portfolio_context",
            },
            "consensus_risk": {
                "assessment": "not_assessable",
                "missing": "agent recommendations and confidence calibration",
            },
            "required_controls": [
                "Do not execute until missing proposal, evidence, and portfolio inputs are supplied.",
                "Require human review if any required field remains missing.",
            ],
            "missing_information": missing or ["model_caller"],
            "monitoring_triggers": [],
            "human_review_required": True,
            "final_risk_note": "No trade should proceed from this critique alone because required risk inputs are absent.",
        }


def get_missing_input_fields(payload: Mapping[str, Any]) -> List[str]:
    missing: List[str] = []
    for field in REQUIRED_INPUT_FIELDS:
        value = payload.get(field)
        if value in (None, "", [], {}):
            missing.append(field)
    return missing


def parse_json_object(raw_response: str) -> Dict[str, Any]:
    text = raw_response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Risk Critic response must be a JSON object.")
    return parsed


def validate_output(output: Mapping[str, Any]) -> None:
    required = {
        "agent",
        "decision",
        "risk_confidence_score",
        "evidence_quality_score",
        "overall_risk_rating",
        "summary",
        "top_risks",
        "scenario_analysis",
        "portfolio_impact",
        "consensus_risk",
        "required_controls",
        "missing_information",
        "monitoring_triggers",
        "human_review_required",
        "final_risk_note",
    }

    missing = required.difference(output)
    if missing:
        raise ValueError(f"Risk Critic output missing required keys: {sorted(missing)}")

    if output["agent"] != "risk_critic":
        raise ValueError("agent must be 'risk_critic'.")

    if output["decision"] not in VALID_DECISIONS:
        raise ValueError(f"Invalid decision: {output['decision']}")

    _validate_score("risk_confidence_score", output["risk_confidence_score"])
    _validate_score("evidence_quality_score", output["evidence_quality_score"])

    if output["overall_risk_rating"] not in VALID_RISK_RATINGS:
        raise ValueError(f"Invalid overall_risk_rating: {output['overall_risk_rating']}")

    _validate_list("top_risks", output["top_risks"])
    _validate_list("scenario_analysis", output["scenario_analysis"])
    if len(output["scenario_analysis"]) < 3:
        raise ValueError("scenario_analysis must include at least three scenarios.")

    for key in ("required_controls", "missing_information", "monitoring_triggers"):
        _validate_list(key, output[key])

    if not isinstance(output["portfolio_impact"], dict):
        raise ValueError("portfolio_impact must be an object.")
    if not isinstance(output["consensus_risk"], dict):
        raise ValueError("consensus_risk must be an object.")
    if not isinstance(output["human_review_required"], bool):
        raise ValueError("human_review_required must be a boolean.")


def _validate_score(name: str, value: Any) -> None:
    if not isinstance(value, int) or value < 0 or value > 100:
        raise ValueError(f"{name} must be an integer from 0 to 100.")


def _validate_list(name: str, value: Any) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list.")


def aggregate_committee_payload(
    proposal: Mapping[str, Any],
    market_data: Mapping[str, Any],
    portfolio_context: Mapping[str, Any],
    agent_recommendations: Iterable[Mapping[str, Any]],
    supporting_evidence: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Normalize common investment-app inputs into the Risk Critic payload."""

    return {
        "proposed_action": proposal.get("action"),
        "instrument": proposal.get("instrument"),
        "time_horizon": proposal.get("time_horizon"),
        "entry": proposal.get("entry"),
        "target": proposal.get("target"),
        "stop_loss": proposal.get("stop_loss"),
        "expected_return": proposal.get("expected_return"),
        "expected_drawdown": proposal.get("expected_drawdown"),
        "proposed_position_size": proposal.get("position_size"),
        "market_data": dict(market_data),
        "portfolio_context": dict(portfolio_context),
        "agent_recommendations": list(agent_recommendations),
        "supporting_evidence": list(supporting_evidence),
    }


if __name__ == "__main__":
    example = {
        "proposed_action": "buy",
        "instrument": "EXAMPLE",
        "time_horizon": "3 months",
        "portfolio_context": {},
        "market_data": {},
        "supporting_evidence": [],
    }
    print(json.dumps(RiskCriticAgent().run(example), indent=2))
