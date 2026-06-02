"""Pattern recall evidence for fund-manager episodes (evidence-only, no execution)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from runtime_compat import resolve_lab_db_path

logger = logging.getLogger(__name__)


class PatternRecallProvider:
    """Attach PatternRecallEvidenceCard to fund-manager prompts and ledger."""

    def __init__(self, lab_db_path: str | Path | None = None, *, enabled: bool = True):
        self.enabled = enabled
        self._db_path = str(lab_db_path or resolve_lab_db_path())
        self._store = None

    def _open_store(self):
        if self._store is not None:
            return self._store
        from autoresearch_lab.pattern_memory.store import PatternStore

        self._store = PatternStore(self._db_path)
        self._store.create_tables()
        return self._store

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None

    def resolve_pattern_id(self, symbol: str, as_of_date: str, period: str = "day") -> str | None:
        pid = f"{symbol}_{str(as_of_date)[:10]}_{period}"
        store = self._open_store()
        row = store.con.execute(
            "SELECT pattern_id FROM pattern_snapshot WHERE pattern_id = ?",
            [pid],
        ).fetchone()
        return pid if row else None

    def fetch_evidence(
        self,
        *,
        symbol: str,
        as_of_date: str,
        trade_idx: int,
        period: str = "day",
        top_k: int = 5,
        horizon: str = "T10",
    ) -> dict[str, Any] | None:
        """Build multi-arm evidence card; returns None when disabled or missing row."""
        if not self.enabled:
            return None
        try:
            from autoresearch_lab.pattern_memory.evidence_card import (
                build_pattern_recall_evidence_card,
                interpret_evidence_for_fund_manager,
            )

            store = self._open_store()
            pattern_id = self.resolve_pattern_id(symbol, as_of_date, period)
            if not pattern_id:
                return None

            pca_row = store.con.execute(
                "SELECT pca_artifact_id, stats_id FROM pattern_snapshot WHERE pattern_id = ?",
                [pattern_id],
            ).fetchone()
            pca_artifact_id = pca_row[0] if pca_row else None
            stats_id = pca_row[1] if pca_row else None

            card = build_pattern_recall_evidence_card(
                store,
                pattern_id=pattern_id,
                query_trade_idx=trade_idx,
                symbol=symbol,
                as_of=as_of_date,
                top_k=top_k,
                horizon=horizon,
                stats_id=stats_id or None,
                pca_artifact_id=pca_artifact_id,
            )
            interpretation = interpret_evidence_for_fund_manager(card)
            return {"card": card, "interpretation": interpretation}
        except Exception as exc:
            logger.warning("Pattern recall evidence unavailable: %s", exc)
            return None

    def format_for_prompt(self, bundle: dict[str, Any] | None) -> str:
        if not bundle:
            return ""
        from autoresearch_lab.pattern_memory.evidence_card import format_evidence_for_prompt

        return format_evidence_for_prompt(bundle["card"], bundle["interpretation"])

    def ledger_fields(self, bundle: dict[str, Any] | None) -> dict[str, Any]:
        if not bundle:
            return {}
        from autoresearch_lab.pattern_memory.evidence_card import evidence_card_to_ledger_fields

        return evidence_card_to_ledger_fields(
            bundle["card"],
            bundle["interpretation"],
        )