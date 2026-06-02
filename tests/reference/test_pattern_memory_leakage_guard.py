"""
Tests for pattern_memory/leakage_guard.py — boundary and integration coverage.

Usage:
    uv run pytest tests/test_pattern_memory_leakage_guard.py -v
"""

import pytest

from autoresearch_lab.pattern_memory.leakage_guard import (
    enforce_leakage_guard,
    leakage_guard_sql,
)


# ── enforce_leakage_guard core boundary tests ───────────────────────────────


class TestEnforceLeakageGuardBasic:
    """Core boundary tests for the leakage guard."""

    def test_safe_candidate_far_away(self):
        """Candidate 50 bars before query is safe (boundary 40 with defaults)."""
        assert enforce_leakage_guard(query_idx=100, candidate_idx=50) is True

    def test_exact_boundary_is_safe(self):
        """Candidate exactly at the boundary is included (<=)."""
        # boundary = 100 - 20 - 20 = 60
        assert enforce_leakage_guard(query_idx=100, candidate_idx=60) is True

    def test_one_past_boundary_is_unsafe(self):
        """Candidate 1 bar inside the boundary is rejected."""
        # boundary = 100 - 20 - 20 = 60; candidate 61 > 60
        assert enforce_leakage_guard(query_idx=100, candidate_idx=61) is False

    def test_same_index_is_unsafe(self):
        """Candidate at the same trade_idx as query is always unsafe."""
        assert enforce_leakage_guard(query_idx=100, candidate_idx=100) is False

    def test_candidate_after_query_is_unsafe(self):
        """Future candidate (higher trade_idx) is always unsafe."""
        assert enforce_leakage_guard(query_idx=100, candidate_idx=150) is False

    def test_zero_query_all_candidates_unsafe(self):
        """query_idx=0 means no safe candidates exist (boundary is negative)."""
        # boundary = 0 - 20 - 20 = -40; candidate 0 > -40 => False
        assert enforce_leakage_guard(query_idx=0, candidate_idx=0) is False


class TestEnforceLeakageGuardCustomParams:
    """Tests with custom horizon and purge parameters."""

    def test_custom_horizon_and_purge(self):
        """Smaller horizon/purge narrows the exclusion window."""
        # boundary = 100 - 5 - 1 = 94
        assert enforce_leakage_guard(
            query_idx=100, candidate_idx=94, max_label_horizon_bars=5, purge_bars=1
        ) is True
        assert enforce_leakage_guard(
            query_idx=100, candidate_idx=95, max_label_horizon_bars=5, purge_bars=1
        ) is False

    def test_zero_purge_still_blocks_label_overlap(self):
        """With purge=0, the guard still blocks label window overlap."""
        # boundary = 100 - 20 - 0 = 80
        assert enforce_leakage_guard(
            query_idx=100, candidate_idx=80, max_label_horizon_bars=20, purge_bars=0
        ) is True
        assert enforce_leakage_guard(
            query_idx=100, candidate_idx=81, max_label_horizon_bars=20, purge_bars=0
        ) is False

    def test_zero_horizon_and_zero_purge_candidate_equals_query(self):
        """Degenerate case: no label window and no purge => candidate at query is still safe."""
        # boundary = 100 - 0 - 0 = 100; candidate 100 <= 100 => True
        assert enforce_leakage_guard(
            query_idx=100, candidate_idx=100, max_label_horizon_bars=0, purge_bars=0
        ) is True

    def test_zero_horizon_only_purge_blocks(self):
        """With zero horizon, only purge separates query from candidate."""
        # boundary = 100 - 0 - 10 = 90
        assert enforce_leakage_guard(
            query_idx=100, candidate_idx=90, max_label_horizon_bars=0, purge_bars=10
        ) is True
        assert enforce_leakage_guard(
            query_idx=100, candidate_idx=91, max_label_horizon_bars=0, purge_bars=10
        ) is False


class TestEnforceLeakageGuardErrors:
    """Negative index and error tests."""

    def test_negative_query_raises(self):
        """Negative query_idx raises ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            enforce_leakage_guard(query_idx=-1, candidate_idx=10)

    def test_negative_candidate_raises(self):
        """Negative candidate_idx raises ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            enforce_leakage_guard(query_idx=10, candidate_idx=-1)

    def test_both_negative_raises(self):
        """Both negative raises ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            enforce_leakage_guard(query_idx=-5, candidate_idx=-3)


class TestEnforceLeakageGuardPreparePyAlignment:
    """Alignment with prepare.py TEMPORAL_PURGE_DAYS."""

    def test_prepare_py_purge_aligned(self):
        """Default purge_bars=20 aligns with prepare.py TEMPORAL_PURGE_DAYS=20."""
        pytest.importorskip("autoresearch_lab.prepare", reason="prepare.py in private monorepo")
        from autoresearch_lab.prepare import TEMPORAL_PURGE_DAYS
        assert 20 == TEMPORAL_PURGE_DAYS

    def test_default_boundary_equals_prepare_minus_40(self):
        """With defaults, safe boundary = query_idx - 40 (20 horizon + 20 purge)."""
        # boundary for query_idx=200 with defaults = 200 - 40 = 160
        assert enforce_leakage_guard(query_idx=200, candidate_idx=160) is True
        assert enforce_leakage_guard(query_idx=200, candidate_idx=161) is False


class TestLeakageGuardSql:
    """Tests for the SQL fragment generator."""

    def test_sql_fragment_default_params(self):
        """Default params produce correct boundary."""
        sql, params = leakage_guard_sql(query_trade_idx=100)
        assert sql == "trade_idx <= ?"
        assert params == [60]

    def test_sql_fragment_custom_params(self):
        """Custom params produce correct boundary."""
        sql, params = leakage_guard_sql(
            query_trade_idx=100, max_label_horizon_bars=10, purge_bars=5
        )
        assert sql == "trade_idx <= ?"
        assert params == [85]

    def test_sql_fragment_zero_purge(self):
        """Zero purge narrows but still produces valid SQL."""
        sql, params = leakage_guard_sql(
            query_trade_idx=100, max_label_horizon_bars=20, purge_bars=0
        )
        assert params == [80]

    def test_sql_fragment_large_query_idx(self):
        """Large trade_idx values work correctly."""
        sql, params = leakage_guard_sql(query_trade_idx=100000)
        assert params == [100000 - 20 - 20]

    @pytest.mark.parametrize(
        "query_idx,horizon,purge,expected_boundary",
        [
            (50, 20, 20, 10),
            (100, 5, 5, 90),
            (1000, 20, 20, 960),
            (40, 20, 20, 0),
            (39, 20, 20, -1),
        ],
    )
    def test_sql_parametrized(self, query_idx, horizon, purge, expected_boundary):
        """Parameterized SQL boundary checks."""
        sql, params = leakage_guard_sql(query_idx, horizon, purge)
        assert params == [expected_boundary]
        assert sql == "trade_idx <= ?"
