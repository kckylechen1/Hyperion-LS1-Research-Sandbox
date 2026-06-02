"""In-memory synthetic case store for public demos (no DuckDB / no Kronos)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PatternCase:
    case_id: str
    symbol: str
    scenario: str
    outcome_label: str
    trade_idx: int
    ls1_signature: dict = field(default_factory=dict)


class InMemoryPatternStore:
    def __init__(self) -> None:
        self._cases: list[PatternCase] = []

    def register(self, case: PatternCase) -> None:
        self._cases.append(case)

    def list_cases(self) -> list[PatternCase]:
        return list(self._cases)

    def query_by_scenario(self, scenario: str, *, k: int = 5) -> list[PatternCase]:
        hits = [c for c in self._cases if c.scenario == scenario]
        return hits[:k]