"""
PatternStore — Persistent DuckDB store for pattern memory tables.

Usage:
    from autoresearch_lab.pattern_memory.store import PatternStore
    store = PatternStore(":memory:")
    store.create_tables()
    pid = store.insert_snapshot(snap)
    results = store.query_top_k(pid, query_trade_idx=500)
    store.close()
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

import duckdb

from autoresearch_lab.pattern_memory.schema import get_all_ddl, get_schema_migrations
from autoresearch_lab.pattern_memory.leakage_guard import (
    leakage_guard_sql,
    same_symbol_guard_sql,
)
from autoresearch_lab.pattern_memory.evidence import aggregate_top_k_evidence

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DB_PATH = str(_PROJECT_ROOT / "data" / "lab.duckdb")


class PatternStore:
    """Persistent DuckDB store for pattern memory vectors and recall cache."""

    def __init__(self, db_path: str = _DEFAULT_DB_PATH):
        self.db_path = db_path
        self.con = duckdb.connect(db_path)

    # ── Schema Management ────────────────────────────────────────────

    def create_tables(self) -> None:
        """Execute all DDL from schema.py."""
        for stmt in get_all_ddl():
            self.con.execute(stmt)
        for stmt in get_schema_migrations():
            self.con.execute(stmt)

    # ── Insertion ────────────────────────────────────────────────────

    def insert_snapshot(self, snap: dict) -> str:
        """Insert one pattern snapshot. Returns pattern_id.

        snap must contain: symbol, as_of_date, period, trade_idx, v8_grade,
        v8_score, v8_setup_score, v8_ignition_score, feature_names_json,
        raw_feature_vector, z_feature_vector, raw_json.
        Optional: kronos_vector, fused_vector, labels, chan fields.
        """
        symbol = snap["symbol"]
        as_of_date = str(snap["as_of_date"])[:10]
        period = snap.get("period", "day")
        pattern_id = f"{symbol}_{as_of_date}_{period}"

        v8_raw = snap.get("v8_score", {})
        v8 = v8_raw if isinstance(v8_raw, dict) else {}
        chan = snap.get("chan", {})
        _bsp_dict = chan.get("bsp") if isinstance(chan.get("bsp"), dict) else {}
        bsp = _bsp_dict.get("latest") if isinstance(_bsp_dict.get("latest"), dict) else {}
        compression = snap.get("compression", {})
        momentum = snap.get("momentum", {})
        crash_signals = snap.get("crash_signals", {})
        labels = snap.get("labels", {})

        def _label_field(horizon: str, field: str, default=None):
            return labels.get(horizon, {}).get(field, default)

        # Extract optional chan bsp_types — may be list or scalar
        bsp_types_raw = bsp.get("type") or bsp.get("types")
        chan_bsp_types = json.dumps(bsp_types_raw) if bsp_types_raw is not None else None

        trap_flags_raw = momentum.get("trap_flags") or crash_signals.get("trap_flags")
        trap_flags = json.dumps(trap_flags_raw) if isinstance(trap_flags_raw, list) else trap_flags_raw

        crash_flags_raw = crash_signals.get("flags") or crash_signals.get("crash_flags")
        crash_flags = json.dumps(crash_flags_raw) if isinstance(crash_flags_raw, list) else crash_flags_raw

        feature_names_json = snap.get("feature_names_json")
        if isinstance(feature_names_json, list):
            feature_names_json = json.dumps(feature_names_json)

        raw_vec = snap.get("raw_feature_vector", [])
        z_vec = snap.get("z_feature_vector", [])

        self.con.execute(
            """
            INSERT OR REPLACE INTO pattern_snapshot (
                pattern_id, symbol, name, period, as_of_date, trade_idx,
                schema_version, feature_set, stats_id,
                v8_grade, v8_score, v8_setup_score, v8_ignition_score,
                chan_trend_type, chan_trend_code, chan_bsp_side, chan_bsp_types,
                chan_divergence_flag,
                spring_coiling, spring_launch, squeeze_intensity,
                trap_flags, crash_flags,
                feature_names_json, raw_feature_vector, z_feature_vector,
                kronos_vector, fused_vector,
                label_T5, fwd_return_T5, mae_T5, mae_gate_T5,
                label_T10, fwd_return_T10, mae_T10, mae_gate_T10,
                label_T20, fwd_return_T20, mae_T20, mae_gate_T20,
                market_regime, vol_regime,
                raw_json, source
            ) VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?, ?
            )
            """,
            [
                pattern_id,
                symbol,
                snap.get("name"),
                period,
                as_of_date,
                snap["trade_idx"],
                snap.get("schema_version", 1),
                snap.get("feature_set", "warpcore_v1"),
                snap.get("stats_id", ""),
                snap.get("v8_grade") or v8.get("grade", "D"),
                float(snap.get("v8_score") if isinstance(snap.get("v8_score"), (int, float)) else v8.get("total", 0.0)),
                float(snap.get("v8_setup_score") if isinstance(snap.get("v8_setup_score"), (int, float)) else v8.get("setup_score", 0.0)),
                float(snap.get("v8_ignition_score") if isinstance(snap.get("v8_ignition_score"), (int, float)) else v8.get("ignition_score", 0.0)),
                chan.get("trend_type"),
                chan.get("stage_code"),
                bsp.get("side"),
                chan_bsp_types,
                1 if (chan.get("macd_divergence", {}).get("divergence") if isinstance(chan.get("macd_divergence"), dict) else False) else 0,
                int(compression.get("spring_coiling", 0) or 0),
                int(momentum.get("spring_launch", 0) or 0),
                compression.get("squeeze_intensity"),
                trap_flags,
                crash_flags,
                feature_names_json,
                list(raw_vec) if raw_vec else [],
                list(z_vec) if z_vec else [],
                list(snap.get("kronos_vector")) if snap.get("kronos_vector") is not None else None,
                list(snap.get("fused_vector")) if snap.get("fused_vector") is not None else None,
                _label_field("T5", "label"),
                _label_field("T5", "fwd_return"),
                _label_field("T5", "mae"),
                _label_field("T5", "mae_gate"),
                _label_field("T10", "label"),
                _label_field("T10", "fwd_return"),
                _label_field("T10", "mae"),
                _label_field("T10", "mae_gate"),
                _label_field("T20", "label"),
                _label_field("T20", "fwd_return"),
                _label_field("T20", "mae"),
                _label_field("T20", "mae_gate"),
                snap.get("market_regime"),
                snap.get("vol_regime"),
                json.dumps(snap.get("raw_json", snap), default=str),
                snap.get("source", "snapshot_factory"),
            ],
        )
        return pattern_id

    # ── Normalization ────────────────────────────────────────────────

    def compute_and_save_stats(
        self,
        stats_id: str,
        feature_names: list[str],
        split_id: str,
        train_start: str,
        train_end: str,
        holdout_start: str,
        purge_bars: int = 20,
        max_label_horizon_bars: int = 20,
    ) -> dict:
        """Compute global mean/std on train split and persist to pattern_feature_stats.

        Returns the stats dict {feature_name: {mean, std, n, n_missing}}.
        """
        # Collect train-split rows as Python lists for columnar stat computation
        rows = self.con.execute(
            """
            SELECT raw_feature_vector, feature_names_json
            FROM pattern_snapshot
            WHERE stats_id = ? AND as_of_date >= ? AND as_of_date <= ?
            """,
            [stats_id, train_start, train_end],
        ).fetchall()

        if not rows:
            return {}

        # Build column index from the first row's feature_names_json
        first_names = json.loads(rows[0][1])
        col_index = {name: i for i, name in enumerate(first_names)}
        
        # Gather per-column values
        columns: dict[str, list[float]] = {fn: [] for fn in feature_names}
        for raw_vec, _ in rows:
            for fn in feature_names:
                idx = col_index.get(fn)
                if idx is not None and idx < len(raw_vec):
                    val = raw_vec[idx]
                    if val is not None:
                        columns[fn].append(float(val))

        result: dict[str, dict] = {}
        insert_data = []
        for fn in feature_names:
            values = columns[fn]
            n = len(values)
            n_total = len(rows)
            n_missing = n_total - n
            if n == 0:
                mean_val = 0.0
                std_val = 1.0  # Safe std default for completely empty columns
            else:
                mean_val = sum(values) / n
                variance = sum((v - mean_val) ** 2 for v in values) / max(n, 1)
                std_val = variance ** 0.5
                if std_val < 1e-9:
                    std_val = 1e-9  # Prevent division by zero when loaded later

            feature_stats = {
                "mean": mean_val,
                "std": std_val,
                "n": n,
                "n_missing": n_missing,
            }
            result[fn] = feature_stats

        # Batch upsert all features at once
        rows_to_insert = []
        for fn in feature_names:
            fs = result[fn]
            rows_to_insert.append([
                stats_id,
                "warpcore_v1",
                1,
                split_id,
                train_start,
                train_end,
                holdout_start,
                purge_bars,
                max_label_horizon_bars,
                fn,
                fs["mean"],
                fs["std"],
                fs["n"],
                fs["n_missing"],
            ])

        self.con.executemany(
            """
            INSERT OR REPLACE INTO pattern_feature_stats (
                stats_id, feature_set, schema_version, split_id,
                train_start, train_end, holdout_start, purge_bars,
                max_label_horizon_bars, feature_name,
                mean, std, n, n_missing
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows_to_insert,
        )

        return result

    def load_stats(self, stats_id: str) -> dict:
        """Load stats from pattern_feature_stats. Returns {feature_name: {mean, std, ...}}."""
        rows = self.con.execute(
            """
            SELECT feature_name, mean, std, n, n_missing
            FROM pattern_feature_stats
            WHERE stats_id = ?
            """,
            [stats_id],
        ).fetchall()

        return {
            row[0]: {
                "mean": row[1],
                "std": row[2],
                "n": row[3],
                "n_missing": row[4],
            }
            for row in rows
        }

    # ── Similarity Search ────────────────────────────────────────────

    def query_top_k(
        self,
        query_pattern_id: str,
        query_trade_idx: int,
        embedding_type: str = "z",
        k: int = 5,
        max_label_horizon_bars: int = 20,
        purge_bars: int = 20,
        horizon: str = "T10",
        stats_id: str | None = None,
        *,
        exclude_same_symbol: bool = False,
        same_symbol_min_gap_bars: int | None = None,
        return_evidence_card: bool = False,
    ) -> list[dict]:
        """Query top-k similar patterns with leakage guard.

        Returns list of {pattern_id, symbol, as_of_date, similarity,
                         label_T5/T10/T20, fwd_return_T5/T10/T20, ...}.
        When ``return_evidence_card`` is True, appends ``evidence_card`` on the
        first element (or returns a one-element list with only the card when
        no neighbors match).
        """
        if horizon not in ("T5", "T10", "T20"):
            raise ValueError(f"Invalid horizon: {horizon!r}. Must be one of T5, T10, T20")
        vec_cols = {
            "raw": "raw_feature_vector",
            "z": "z_feature_vector",
            "kronos": "kronos_vector",
            "fused": "fused_vector",
        }
        if embedding_type not in vec_cols:
            raise ValueError(
                f"Invalid embedding_type: {embedding_type!r}. "
                f"Must be one of {', '.join(sorted(vec_cols))}"
            )
        vec_col = vec_cols[embedding_type]

        label_col = f"label_{horizon}"
        fwd_col = f"fwd_return_{horizon}"
        mae_col = f"mae_{horizon}"
        mae_gate_col = f"mae_gate_{horizon}"

        # Fetch the query vector and symbol context
        row = self.con.execute(
            f"""
            SELECT {vec_col}, stats_id, symbol, market_regime
            FROM pattern_snapshot WHERE pattern_id = ?
            """,
            [query_pattern_id],
        ).fetchone()

        if row is None or row[0] is None:
            if return_evidence_card:
                card = aggregate_top_k_evidence(
                    [],
                    horizon=horizon,
                    query_symbol=None,
                    query_trade_idx=query_trade_idx,
                    embedding_type=embedding_type,
                    top_k=k,
                )
                return [{"evidence_card": card}]
            return []

        query_vec = list(row[0])
        effective_stats_id = stats_id if stats_id is not None else row[1]
        query_symbol = row[2]
        query_regime = row[3]
        guard_sql, guard_params = leakage_guard_sql(
            query_trade_idx, max_label_horizon_bars, purge_bars
        )
        sym_sql, sym_params = same_symbol_guard_sql(
            query_symbol,
            query_trade_idx,
            exclude_same_symbol=exclude_same_symbol,
            same_symbol_min_gap_bars=same_symbol_min_gap_bars,
        )
        cohort_sql = ""
        cohort_params: list = []
        if effective_stats_id is not None:
            cohort_sql = " AND stats_id = ?"
            cohort_params.append(effective_stats_id)

        sym_clause = f" AND {sym_sql}" if sym_sql else ""

        results = self.con.execute(
            f"""
            SELECT
                pattern_id, symbol, as_of_date, trade_idx,
                list_cosine_similarity({vec_col}, ?::DOUBLE[]) AS similarity,
                label_T5, fwd_return_T5, mae_T5, mae_gate_T5,
                label_T10, fwd_return_T10, mae_T10, mae_gate_T10,
                label_T20, fwd_return_T20, mae_T20, mae_gate_T20,
                v8_grade, market_regime
            FROM pattern_snapshot
            WHERE pattern_id != ?
              AND array_length({vec_col}) = ?
              AND {guard_sql}
              {sym_clause}
              {cohort_sql}
            ORDER BY similarity DESC, pattern_id ASC
            LIMIT ?
            """,
            [query_vec, query_pattern_id, len(query_vec)]
            + guard_params
            + sym_params
            + cohort_params
            + [k],
        ).fetchall()

        hits = [
            {
                "pattern_id": r[0],
                "symbol": r[1],
                "as_of_date": r[2],
                "trade_idx": r[3],
                "similarity": r[4],
                "label_T5": r[5],
                "fwd_return_T5": r[6],
                "mae_T5": r[7],
                "mae_gate_T5": r[8],
                "label_T10": r[9],
                "fwd_return_T10": r[10],
                "mae_T10": r[11],
                "mae_gate_T10": r[12],
                "label_T20": r[13],
                "fwd_return_T20": r[14],
                "mae_T20": r[15],
                "mae_gate_T20": r[16],
                "v8_grade": r[17],
                "market_regime": r[18],
            }
            for r in results
        ]

        if return_evidence_card:
            card = aggregate_top_k_evidence(
                hits,
                horizon=horizon,
                query_symbol=query_symbol,
                query_trade_idx=query_trade_idx,
                query_market_regime=query_regime,
                embedding_type=embedding_type,
                top_k=k,
            )
            if hits:
                hits[0]["evidence_card"] = card
            else:
                hits = [{"evidence_card": card}]
        return hits

    # ── Fused Vector Writeback ───────────────────────────────────────

    def iter_fusion_inputs(self) -> list[dict]:
        """Return rows that have both a kronos_vector and a z_feature_vector.

        These are the candidates for PCA fusion writeback. Returns a list of
        {pattern_id, as_of_date, stats_id, kronos_vector, z_feature_vector} dicts.
        """
        rows = self.con.execute(
            """
            SELECT pattern_id, as_of_date, stats_id, kronos_vector, z_feature_vector
            FROM pattern_snapshot
            WHERE kronos_vector IS NOT NULL
              AND z_feature_vector IS NOT NULL
            ORDER BY pattern_id
            """
        ).fetchall()
        return [
            {
                "pattern_id": r[0],
                "as_of_date": str(r[1])[:10],
                "stats_id": r[2],
                "kronos_vector": list(r[3]),
                "z_feature_vector": list(r[4]),
            }
            for r in rows
        ]

    def update_fused_vector(
        self,
        pattern_id: str,
        fused_vector: list[float],
        *,
        pca_artifact_id: str | None = None,
        fusion_version: str | None = None,
    ) -> None:
        """Persist a fused vector back onto an existing pattern_snapshot row."""
        self.con.execute(
            """
            UPDATE pattern_snapshot
            SET fused_vector = ?::DOUBLE[],
                pca_artifact_id = COALESCE(?, pca_artifact_id),
                fusion_version = COALESCE(?, fusion_version)
            WHERE pattern_id = ?
            """,
            [list(fused_vector), pca_artifact_id, fusion_version, pattern_id],
        )

    def save_pca_artifact(self, record: dict) -> str:
        """Upsert a row into ``pattern_pca_artifact``."""
        self.con.execute(
            """
            INSERT OR REPLACE INTO pattern_pca_artifact (
                pca_artifact_id, fusion_version, stats_id,
                fit_start, fit_end, n_fit_rows, n_components,
                explained_variance_ratio_sum, model_repo,
                artifact_path, artifact_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                record["pca_artifact_id"],
                record.get("fusion_version", "fused_concat_v1"),
                record.get("stats_id"),
                record.get("fit_start"),
                record.get("fit_end"),
                record["n_fit_rows"],
                record["n_components"],
                record.get("explained_variance_ratio_sum"),
                record.get("model_repo"),
                record.get("artifact_path"),
                record.get("artifact_hash"),
            ],
        )
        return record["pca_artifact_id"]

    def get_pca_artifact(self, pca_artifact_id: str) -> dict | None:
        """Load PCA artifact registry row."""
        row = self.con.execute(
            """
            SELECT pca_artifact_id, fusion_version, stats_id, fit_start, fit_end,
                   n_fit_rows, n_components, explained_variance_ratio_sum,
                   model_repo, artifact_path, artifact_hash
            FROM pattern_pca_artifact
            WHERE pca_artifact_id = ?
            """,
            [pca_artifact_id],
        ).fetchone()
        if row is None:
            return None
        keys = (
            "pca_artifact_id", "fusion_version", "stats_id", "fit_start", "fit_end",
            "n_fit_rows", "n_components", "explained_variance_ratio_sum",
            "model_repo", "artifact_path", "artifact_hash",
        )
        return dict(zip(keys, row))

    # ── Kronos Vector Backfill ───────────────────────────────────────

    def iter_kronos_targets(self, *, only_missing: bool = True) -> list[dict]:
        """Return rows needing a Kronos embedding, anchored on as_of_date.

        ``as_of_date`` is the stable point-in-time anchor (``trade_idx`` is only
        positional within the original bounded load and is NOT reusable across a
        differently-sized kline fetch). Returns
        ``{pattern_id, symbol, as_of_date, period}`` dicts sorted by symbol so a
        caller can load each symbol's series once.
        """
        where = "WHERE kronos_vector IS NULL" if only_missing else ""
        rows = self.con.execute(
            f"""
            SELECT pattern_id, symbol, as_of_date, period
            FROM pattern_snapshot
            {where}
            ORDER BY symbol, as_of_date
            """
        ).fetchall()
        return [
            {"pattern_id": r[0], "symbol": r[1], "as_of_date": str(r[2])[:10], "period": r[3]}
            for r in rows
        ]

    def update_kronos_vector(self, pattern_id: str, kronos_vector: list[float]) -> None:
        """Persist a Kronos embedding back onto an existing pattern_snapshot row."""
        self.con.execute(
            "UPDATE pattern_snapshot SET kronos_vector = ?::DOUBLE[] WHERE pattern_id = ?",
            [list(kronos_vector), pattern_id],
        )

    def bulk_update_feature_vectors(
        self,
        updates: list[tuple[str, list[float], list[float], list[str]]],
    ) -> int:
        """Batch overwrite raw/z vectors and feature names transactionally.

        Use after ``revectorize.py`` to migrate legacy 34D rows onto the 30D
        blind spec. Caller is responsible for ensuring ``z_feature_vector`` is
        L2-normalized and feature names match both vector columns.
        """
        n = 0
        try:
            self.con.execute("BEGIN TRANSACTION")
            for pid, raw_vec, z_vec, feature_names in updates:
                self.con.execute(
                    """
                    UPDATE pattern_snapshot
                    SET raw_feature_vector = ?::DOUBLE[],
                        z_feature_vector = ?::DOUBLE[],
                        feature_names_json = ?
                    WHERE pattern_id = ?
                    """,
                    [list(raw_vec), list(z_vec), json.dumps(list(feature_names)), pid],
                )
                n += 1
            self.con.execute("COMMIT")
        except Exception:
            self.con.execute("ROLLBACK")
            raise
        return n

    def bulk_update_z_vectors(self, updates: list[tuple[str, list[float]]]) -> int:
        """Batch overwrite z_feature_vector for many rows. Returns count written.

        Kept for narrow callers that only need z writeback. Prefer
        ``bulk_update_feature_vectors`` for spec migrations so raw/z/names stay
        dimensionally consistent.
        """
        n = 0
        try:
            self.con.execute("BEGIN TRANSACTION")
            for pid, vec in updates:
                self.con.execute(
                    "UPDATE pattern_snapshot SET z_feature_vector = ?::DOUBLE[] WHERE pattern_id = ?",
                    [list(vec), pid],
                )
                n += 1
            self.con.execute("COMMIT")
        except Exception:
            self.con.execute("ROLLBACK")
            raise
        return n

    # ── Trading Calendar ─────────────────────────────────────────────

    def build_trading_calendar(self, dates: list[str]) -> None:
        """Populate trading_calendar from a sorted list of unique trade dates."""
        # Clear existing data for a clean rebuild
        self.con.execute("DELETE FROM trading_calendar")
        for idx, d in enumerate(dates):
            d_str = str(d)[:10]
            # Mark month-end: last trading day of the month
            parts = d_str.split("-")
            is_month_end = False
            if len(parts) == 3 and idx == len(dates) - 1:
                is_month_end = True
            elif len(parts) == 3:
                next_d = str(dates[idx + 1])[:10]
                next_parts = next_d.split("-")
                if parts[:2] != next_parts[:2]:
                    is_month_end = True
            self.con.execute(
                "INSERT OR REPLACE INTO trading_calendar (trade_date, trade_idx, is_month_end) VALUES (?, ?, ?)",
                [d_str, idx, is_month_end],
            )

    def get_trade_idx(self, date: str) -> int:
        """Look up sequential trade_idx for a given date. Raises if not found."""
        row = self.con.execute(
            "SELECT trade_idx FROM trading_calendar WHERE trade_date = ?",
            [str(date)[:10]],
        ).fetchone()
        if row is None:
            raise KeyError(f"trade_date {date} not found in trading_calendar")
        return int(row[0])

    # ── Lifecycle ────────────────────────────────────────────────────

    def close(self) -> None:
        """Close DuckDB connection."""
        self.con.close()

    def __del__(self):
        try:
            self.con.close()
        except Exception:
            pass
