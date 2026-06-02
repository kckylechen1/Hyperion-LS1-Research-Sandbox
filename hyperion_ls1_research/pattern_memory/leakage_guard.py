"""Minimal leakage guard for synthetic pattern recall demos."""

from __future__ import annotations


def is_future_neighbor(
    query_trade_idx: int,
    neighbor_trade_idx: int,
    *,
    min_gap_bars: int = 1,
) -> bool:
    """True if neighbor is not strictly in the past (leakage)."""
    if neighbor_trade_idx is None:
        return True
    return int(neighbor_trade_idx) > int(query_trade_idx) - min_gap_bars


def filter_past_neighbors(
    neighbors: list[dict],
    *,
    query_trade_idx: int,
    min_gap_bars: int = 1,
) -> list[dict]:
    return [
        n
        for n in neighbors
        if not is_future_neighbor(
            query_trade_idx,
            n.get("trade_idx", query_trade_idx),
            min_gap_bars=min_gap_bars,
        )
    ]