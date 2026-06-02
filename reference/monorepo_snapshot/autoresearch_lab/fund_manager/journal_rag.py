"""Outcome-validated case memory retrieval for the fund manager."""

import logging
from pathlib import Path
from typing import Optional

import duckdb

from runtime_compat import resolve_lab_db_path

logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

class CaseRAG:
    """Retrieve balanced, validated cases from journal_verdicts."""

    _CASE_BUCKETS = (
        ("calibrated_wait", ("CORRECT_WAIT", "VALIDATED")),
        ("missed_entry", ("MISSED_ENTRY",)),
        ("good_entry", ("GOOD_ENTRY",)),
        ("premature_exit", ("PREMATURE_EXIT",)),
        ("good_exit", ("GOOD_EXIT",)),
        ("bad_trade", ("BAD_ENTRY", "REFUTED")),
    )

    def __init__(self, db_path: str = None, run_id: Optional[str] = None):
        if db_path is None:
            self.db_path = str(resolve_lab_db_path())
        else:
            self.db_path = db_path
        self.run_id = run_id

    @staticmethod
    def _signed_pct(value: float | int | None) -> str:
        if value is None:
            return "N/A"
        return f"{float(value):+.0f}%"

    @staticmethod
    def _build_case_title(memory: dict) -> str:
        verdict = memory.get("verdict", "")
        price = memory.get("price_at_action")
        action = str(memory.get("action_taken", "") or "").upper()

        if verdict in ("MISSED_ENTRY", "CORRECT_WAIT"):
            verb = "You waited"
        elif verdict in ("GOOD_ENTRY", "BAD_ENTRY") or action in ("BUY", "ADD"):
            verb = "You bought"
        elif verdict in ("VALIDATED", "REFUTED", "PREMATURE_EXIT", "GOOD_EXIT") or action in ("SELL", "TRIM"):
            verb = "You exited"
        else:
            verb = "You acted"

        if price in (None, ""):
            return verb
        return f"{verb} at {float(price):.2f}"

    def _build_case_summary(self, memory: dict) -> str:
        verdict = memory.get("verdict", "")
        verdict_price = memory.get("price_at_verdict")
        pnl_pct = memory.get("pnl_pct")
        lesson = (memory.get("lesson_extracted") or "").strip()
        move = (
            f"Price {'rose' if float(pnl_pct or 0) >= 0 else 'fell'} "
            f"to {float(verdict_price):.2f} ({self._signed_pct(pnl_pct)}) in 10 days."
            if verdict_price not in (None, "") and pnl_pct is not None
            else lesson
        )

        if verdict == "MISSED_ENTRY":
            return f"{move} Lesson: Should have entered with PROBE conviction."
        if verdict == "GOOD_ENTRY":
            return f"{move} Entry was correct."
        if verdict == "PREMATURE_EXIT":
            return f"{move} Exit was premature; protect strong structures from fear-driven selling."
        if verdict == "GOOD_EXIT":
            return f"{move} Exit was correct; risk control saved capital."
        if verdict in ("CORRECT_WAIT", "VALIDATED"):
            return (
                f"{move} Patience was correct."
                if verdict == "CORRECT_WAIT"
                else f"{move} Exit was correct."
            )
        if verdict in ("BAD_ENTRY", "REFUTED"):
            return f"{move} The action was premature."
        return lesson or move

    def _fetch_latest_case(
        self,
        conn: duckdb.DuckDBPyConnection,
        verdicts: tuple[str, ...],
        before_date: Optional[str],
        symbol: Optional[str],
    ) -> Optional[dict]:
        placeholders = ", ".join("?" for _ in verdicts)
        sql = f"""
            SELECT
                id,
                run_id,
                journal_date,
                verdict_date,
                action_taken,
                price_at_action,
                price_at_verdict,
                pnl_pct,
                verdict,
                lesson_extracted
            FROM journal_verdicts
            WHERE verdict IN ({placeholders})
        """
        params: list[object] = [*verdicts]
        if symbol:
            sql += " AND run_id LIKE ?"
            params.append(f"{symbol}_%")
        if before_date:
            sql += " AND journal_date < ? AND verdict_date IS NOT NULL AND verdict_date < ?"
            params.extend([before_date, before_date])

        sql += " ORDER BY journal_date DESC, id DESC LIMIT 1"
        cursor = conn.execute(sql, params)
        row = cursor.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

    def _candidate_db_paths(self) -> list[Path]:
        """Return current and historical run DBs without requiring a global merge job."""
        paths: list[Path] = []

        def add(path: Path) -> None:
            resolved = path.expanduser()
            if resolved.exists() and resolved not in paths:
                paths.append(resolved)

        add(Path(self.db_path))
        db_path = Path(self.db_path).expanduser()
        if db_path.parent.exists():
            for sibling in sorted(db_path.parent.glob("*.db")):
                add(sibling)

        runs_dir = _PROJECT_ROOT / "data" / "runs"
        try:
            in_project = db_path.resolve().is_relative_to(_PROJECT_ROOT)
        except OSError:
            in_project = False
        if in_project and runs_dir.exists():
            for run_db in sorted(runs_dir.glob("*.db")):
                add(run_db)
        return paths

    def retrieve_similar_journals(
        self,
        current_snapshot: dict,
        top_k: int = 3,
        before_date: Optional[str] = None,
        symbol: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> list[dict]:
        """Return balanced outcome-validated cases available before `before_date`."""
        _ = current_snapshot, run_id  # run_id is context only; retrieval is cross-run.
        if top_k <= 0 or not before_date:
            return []

        cases_by_bucket: dict[str, dict] = {}
        seen: set[tuple[object, ...]] = set()
        for db_path in self._candidate_db_paths():
            try:
                with duckdb.connect(str(db_path), read_only=True) as conn:
                    conn.execute("SELECT 1 FROM journal_verdicts LIMIT 1").fetchone()
                    for bucket, verdicts in self._CASE_BUCKETS:
                        case = self._fetch_latest_case(
                            conn=conn,
                            verdicts=verdicts,
                            before_date=before_date,
                            symbol=symbol,
                        )
                        if not case:
                            continue
                        key = (
                            case.get("run_id"),
                            case.get("journal_date"),
                            case.get("verdict"),
                            case.get("action_taken"),
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        case["_source_db"] = str(db_path)
                        case["_bucket"] = bucket
                        current = cases_by_bucket.get(bucket)
                        case_key = (
                            case.get("journal_date", ""),
                            case.get("verdict_date", ""),
                            case.get("id", 0),
                        )
                        current_key = (
                            current.get("journal_date", ""),
                            current.get("verdict_date", ""),
                            current.get("id", 0),
                        ) if current else ("", "", 0)
                        if current is None or case_key > current_key:
                            cases_by_bucket[bucket] = case
            except duckdb.Error:
                continue

        cases = list(cases_by_bucket.values())
        if not cases:
            return []

        cases.sort(
            key=lambda item: (
                item.get("journal_date", ""),
                item.get("verdict_date", ""),
                item.get("verdict", ""),
            ),
            reverse=True,
        )
        return cases[:top_k]

    def format_for_prompt(self, memories: list[dict]) -> str:
        """Format retrieved cases for prompt injection."""
        if not memories:
            return ""

        lines = ["## 📋 Case Memory (Outcome-Validated)"]
        lines.append(
            "These are past decisions validated before today against actual market outcomes."
        )
        lines.append("Use them as calibration, not as commands.\n")

        for memory in memories:
            title = self._build_case_title(memory)
            summary = self._build_case_summary(memory)
            lines.append(
                f"**[{memory.get('verdict', 'CASE')}] {memory.get('journal_date', 'N/A')} — {title}**"
            )
            lines.append(f"> {summary}")
            lines.append("")

        lines.append(
            '⚠️ Memory is calibration, not truth. A past SKIP is "correct" only if the '
            "subsequent path did NOT offer a risk-adjusted entry. Today's market structure decides everything."
        )
        return "\n".join(lines)


class JournalRAG:
    """Retrieve past `inner_journal` rows from `fund_manager_decisions` for the same symbol.

    Uses lightweight structural/keyword similarity (no sentence-transformer hard
    dependency) so unit tests and CI stay deterministic. For outcome rows in
    `journal_verdicts`, use :class:`CaseRAG` instead.
    """

    def __init__(self, db_path: str | None = None, run_id: str | None = None) -> None:
        if db_path is None:
            self.db_path = str(resolve_lab_db_path())
        else:
            self.db_path = db_path
        self.run_id = run_id

    @staticmethod
    def _heuristic_score(
        current_snapshot: dict, row: dict, adx_val: float, rsi_val: float, strong_trend: bool
    ) -> int:
        """Score a past journal row against the current snapshot (legacy V5 heuristics)."""
        trend_mode = (current_snapshot.get("momentum") or {}).get("trend_mode", "") or ""
        if rsi_val > 70:
            rsi_zone = "overbought"
        elif rsi_val < 30:
            rsi_zone = "oversold"
        else:
            rsi_zone = "neutral"

        journal = (row["inner_journal"] or "").lower()
        action = (row["action"] or "").upper()
        score = 0

        if trend_mode and str(trend_mode).lower() in journal:
            score += 3

        fear_words = ("scared", "afraid", "fear", "worried", "nervous", "hesitant", "panic")
        fomo_words = ("missing", "missed", "regret", "should have", "too late", "left behind")
        greed_words = ("acceleration", "momentum", "breakout", "all-in", "fat pitch", "moon")

        if rsi_zone == "oversold" and any(w in journal for w in fear_words):
            score += 2
        elif rsi_zone == "overbought" and any(w in journal for w in greed_words):
            score += 2

        if any(w in journal for w in fomo_words):
            score += 2

        if strong_trend and any(w in journal for w in ("strong", "adx", "trend")):
            score += 1

        if action in ("BUY", "ADD") and str(trend_mode).lower() == "acceleration":
            score += 1

        return score

    def retrieve_similar_journals(
        self,
        current_snapshot: dict,
        top_k: int = 3,
        before_date: Optional[str] = None,
        symbol: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> list[dict]:
        """Rows from ``fund_manager_decisions``, same symbol, excluding the active run."""

        exclude_run = run_id if run_id is not None else self.run_id

        adx_raw = (current_snapshot.get("indicators") or {}).get("adx", 0)
        rsi_raw = (current_snapshot.get("indicators") or {}).get("rsi", 50)
        try:
            adx_val = float(adx_raw) if adx_raw not in (None, "N/A", "unknown", "") else 0.0
        except (TypeError, ValueError):
            adx_val = 0.0
        try:
            rsi_val = float(rsi_raw) if rsi_raw not in (None, "N/A", "unknown", "") else 50.0
        except (TypeError, ValueError):
            rsi_val = 50.0
        strong_trend = adx_val > 35

        if top_k <= 0:
            return []

        with duckdb.connect(self.db_path) as conn:
            sql = """
                SELECT run_id, symbol, date, inner_journal, action, close_price
                FROM fund_manager_decisions
                WHERE inner_journal IS NOT NULL AND TRIM(inner_journal) != ''
            """
            params: list[object] = []
            if symbol:
                sql += " AND symbol = ?"
                params.append(symbol)
            if before_date:
                sql += " AND date < ?"
                params.append(before_date)
            if exclude_run:
                sql += " AND run_id != ?"
                params.append(exclude_run)

            sql += " ORDER BY date DESC"

            try:
                cursor = conn.execute(sql, params)
                columns = [desc[0] for desc in cursor.description]
                rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            except duckdb.Error as exc:
                logger.debug("JournalRAG query skipped: %s", exc)
                return []

        scored: list[tuple[int, dict]] = []
        for row in rows:
            pts = self._heuristic_score(current_snapshot, row, adx_val, rsi_val, strong_trend)
            if pts > 0:
                scored.append((pts, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        out: list[dict] = []
        for pts, row in scored[:top_k]:
            out.append(
                {
                    "symbol": row["symbol"],
                    "run_id": row["run_id"],
                    "date": row["date"],
                    "inner_journal": row["inner_journal"],
                    "journal": row["inner_journal"],
                    "action": row["action"],
                    "score": pts,
                }
            )
        return out

    def format_for_prompt(self, memories: list[dict]) -> str:
        """Format reflexive journal memories for LLM injection."""
        if not memories:
            return ""

        lines = ["## 📝 Your Past Self (Reflexive Memory)"]
        lines.append(
            "These are your own journal entries from similar market situations. "
            "Learn from your past self:\n"
        )

        for m in memories:
            date = m.get("date", "N/A")
            action = m.get("action", "")
            journal = (m.get("inner_journal") or m.get("journal") or "").strip()
            lines.append(f"**[{date}] You chose: {action}**")
            lines.append(f"> {journal[:500]}")
            lines.append("")

        lines.append(
            "Reflect: Are you about to repeat a past mistake? Or can you do better this time?\n"
        )
        return "\n".join(lines)
