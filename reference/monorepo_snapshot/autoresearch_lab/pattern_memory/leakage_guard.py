"""
Leakage guard — prevents look-ahead contamination in pattern recall.

Usage:
    from autoresearch_lab.pattern_memory.leakage_guard import (
        enforce_leakage_guard, leakage_guard_sql,
    )
    safe = enforce_leakage_guard(query_idx=100, candidate_idx=50)
    sql_fragment, params = leakage_guard_sql(query_trade_idx=100)
"""

from __future__ import annotations


def enforce_leakage_guard(
    query_idx: int,
    candidate_idx: int,
    max_label_horizon_bars: int = 20,
    purge_bars: int = 20,
) -> bool:
    """Return True if candidate is safe (no look-ahead), False otherwise.

    Rule: candidate_trade_idx <= query_trade_idx - max_label_horizon_bars - purge_bars

    purge_bars default = 20 (spec §3.2 allows 1–20; we use the conservative
    upper bound to fully buffer regime shifts and label-window overlap).

    Raises ValueError if indices are negative.
    """
    if query_idx < 0 or candidate_idx < 0:
        raise ValueError(
            f"Indices must be non-negative. query={query_idx}, candidate={candidate_idx}"
        )
    safe_boundary = query_idx - max_label_horizon_bars - purge_bars
    return candidate_idx <= safe_boundary


def leakage_guard_sql(
    query_trade_idx: int,
    max_label_horizon_bars: int = 20,
    purge_bars: int = 20,
) -> tuple[str, list]:
    """Return (sql_fragment, params) for DuckDB WHERE clause.

    Example: ("trade_idx <= ?", [40])
    """
    boundary = query_trade_idx - max_label_horizon_bars - purge_bars
    return "trade_idx <= ?", [boundary]


def same_symbol_guard_sql(
    query_symbol: str,
    query_trade_idx: int,
    *,
    exclude_same_symbol: bool = False,
    same_symbol_min_gap_bars: int | None = None,
) -> tuple[str, list]:
    """Extra SQL fragment excluding near-duplicate same-symbol rolling windows."""
    if exclude_same_symbol:
        return "symbol != ?", [query_symbol]
    if same_symbol_min_gap_bars is not None and same_symbol_min_gap_bars > 0:
        boundary = query_trade_idx - same_symbol_min_gap_bars
        return "(symbol != ? OR trade_idx <= ?)", [query_symbol, boundary]
    return "", []


def enforce_same_symbol_gap(
    query_symbol: str,
    query_trade_idx: int,
    candidate_symbol: str,
    candidate_trade_idx: int,
    *,
    exclude_same_symbol: bool = False,
    same_symbol_min_gap_bars: int | None = None,
) -> bool:
    """Return True when the candidate is allowed under same-symbol rules."""
    if exclude_same_symbol and candidate_symbol == query_symbol:
        return False
    if (
        same_symbol_min_gap_bars is not None
        and same_symbol_min_gap_bars > 0
        and candidate_symbol == query_symbol
        and candidate_trade_idx > query_trade_idx - same_symbol_min_gap_bars
    ):
        return False
    return True
