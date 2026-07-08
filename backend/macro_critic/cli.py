from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .agent import MacroCriticAgent
from .models import MacroSnapshot, MarketSnapshot, TradeProposal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Macro Critic investment committee agent.")
    parser.add_argument("input", type=Path, help="Path to a JSON request payload.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON response.")
    args = parser.parse_args(argv)

    try:
        payload = _read_json(args.input)
        proposal = TradeProposal.from_dict(payload.get("proposal", {}))
        macro = MacroSnapshot.from_dict(payload.get("macro", {}))
        market = MarketSnapshot.from_dict(payload.get("market", {}))
        result = MacroCriticAgent().critique(proposal, macro, market).to_dict()
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    indent = 2 if args.pretty else None
    print(json.dumps(result, indent=indent, sort_keys=True))
    return 0


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Input JSON must be an object.")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())

