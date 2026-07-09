"""Investment Planner Agent: decides which watchlist symbols to run the full
committee on this tick (strategic focus + workflow management), balancing
"must monitor open positions" against "explore new candidates" under a
per-tick symbol budget (keeps LLM/API cost bounded during a live session)."""

from __future__ import annotations


class InvestmentPlanner:
    def __init__(self, max_symbols_per_tick: int = 1) -> None:
        self.max_symbols_per_tick = max_symbols_per_tick
        self._cursor = 0

    def plan_tick(self, watchlist: list[str], open_position_symbols: list[str]) -> list[str]:
        selected: list[str] = list(dict.fromkeys(open_position_symbols))  # always monitor open positions

        remaining_budget = max(self.max_symbols_per_tick - len(selected), 0)
        if remaining_budget and watchlist:
            n = len(watchlist)
            candidates = []
            for i in range(n):
                sym = watchlist[(self._cursor + i) % n]
                if sym not in selected:
                    candidates.append(sym)
                if len(candidates) >= remaining_budget:
                    break
            selected.extend(candidates)
            self._cursor = (self._cursor + max(len(candidates), 1)) % n

        return selected
