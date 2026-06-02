"""DuckDB-backed decision ledger for fund manager backtests."""

import json
import logging
from pathlib import Path
from typing import Optional

import duckdb

from runtime_compat import resolve_lab_db_path

logger = logging.getLogger(__name__)

_DB_PATH = resolve_lab_db_path()


class DecisionLedger:
    """Manages fund manager decision records in SQLite."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or _DB_PATH
        self._ensure_table()

    def _get_conn(self) -> duckdb.DuckDBPyConnection:
        path = Path(self.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(str(path))

    @staticmethod
    def _next_id(conn: duckdb.DuckDBPyConnection, table: str) -> int:
        row = conn.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {table}").fetchone()
        return int(row[0])

    @staticmethod
    def _fetchall_dicts(cursor) -> list[dict]:
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _ensure_table(self):
        """Create table if not exists."""
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE SEQUENCE IF NOT EXISTS fund_manager_decisions_id_seq START 1
            """)
            conn.execute("""
                CREATE SEQUENCE IF NOT EXISTS ghost_trades_id_seq START 1
            """)
            conn.execute("""
                CREATE SEQUENCE IF NOT EXISTS journal_verdicts_id_seq START 1
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fund_manager_decisions (
                    id BIGINT PRIMARY KEY DEFAULT nextval('fund_manager_decisions_id_seq'),
                    run_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    date TEXT NOT NULL,
                    day_index INTEGER NOT NULL,
                    close_price DOUBLE,
                    action TEXT,
                    target_position_pct DOUBLE,
                    confidence DOUBLE,
                    reason_codes TEXT,
                    thesis_update TEXT,
                    risk_flags TEXT,
                    brief_rationale TEXT,
                    inner_journal TEXT,
                    portfolio_state TEXT,
                    execution_result TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_run_id ON fund_manager_decisions(run_id)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ghost_trades (
                    id BIGINT PRIMARY KEY DEFAULT nextval('ghost_trades_id_seq'),
                    run_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    fork_date TEXT NOT NULL,
                    fork_price DOUBLE,
                    shares_held INTEGER,
                    mfe_pct DOUBLE,
                    mae_pct DOUBLE,
                    regret_score DOUBLE,
                    horizon INTEGER DEFAULT 20,
                    days_tracked INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS journal_verdicts (
                    id BIGINT PRIMARY KEY DEFAULT nextval('journal_verdicts_id_seq'),
                    decision_id INTEGER,
                    run_id TEXT,
                    journal_date TEXT,
                    verdict_date TEXT,
                    action_taken TEXT,
                    price_at_action DOUBLE,
                    price_at_verdict DOUBLE,
                    pnl_pct DOUBLE,
                    verdict TEXT,
                    lesson_extracted TEXT,
                    inner_journal_snippet TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Migrate: add inner_journal if missing
            try:
                conn.execute("ALTER TABLE fund_manager_decisions ADD COLUMN inner_journal TEXT")
            except duckdb.Error:
                pass  # Column already exists
            # Phase 2 Oracle: iron rules columns
            for _col in ("iron_verdict", "iron_blocks", "iron_penalties"):
                try:
                    conn.execute(f"ALTER TABLE fund_manager_decisions ADD COLUMN {_col} TEXT")
                except duckdb.Error:
                    pass
            for _col, _type in (
                ("snapshot_source", "TEXT"),
                ("snapshot_schema_version", "TEXT"),
                ("v8_grade_at_decision", "TEXT"),
                ("v8_score_at_decision", "REAL"),
                ("iron_entry_verdict_at_decision", "TEXT"),
                ("iron_entry_blocks_at_decision", "TEXT"),
                ("toxic_breaker_factors_at_decision", "TEXT"),
                ("objective_tension_types_at_decision", "TEXT"),
                ("policy_gate_reason", "TEXT"),
                ("pattern_recall_version", "TEXT"),
                ("embedding_arm", "TEXT"),
                ("stats_id", "TEXT"),
                ("pca_artifact_id", "TEXT"),
                ("top_k_case_ids", "TEXT"),
                ("evidence_card_json", "TEXT"),
                ("fund_manager_interpretation", "TEXT"),
            ):
                try:
                    conn.execute(
                        f"ALTER TABLE fund_manager_decisions ADD COLUMN {_col} {_type}"
                    )
                except duckdb.Error:
                    pass
            conn.commit()
        finally:
            conn.close()

    def log_decision(
        self,
        run_id: str,
        symbol: str,
        date: str,
        day_index: int,
        close_price: float,
        action: str,
        target_position_pct: float,
        confidence: float,
        reason_codes: list,
        thesis_update: dict,
        risk_flags: list,
        brief_rationale: str,
        portfolio_state: dict,
        execution_result: dict,
        inner_journal: str = "",
        iron_verdict: str = "",
        iron_blocks: Optional[list] = None,
        iron_penalties: Optional[list] = None,
        snapshot_source: str = "",
        snapshot_schema_version: str = "",
        v8_grade_at_decision: str = "",
        v8_score_at_decision: Optional[float] = None,
        iron_entry_verdict_at_decision: str = "",
        iron_entry_blocks_at_decision: Optional[list] = None,
        toxic_breaker_factors_at_decision: Optional[list] = None,
        objective_tension_types_at_decision: Optional[list] = None,
        policy_gate_reason: str = "",
        pattern_recall_version: str = "",
        embedding_arm: str = "",
        stats_id: str = "",
        pca_artifact_id: str = "",
        top_k_case_ids: str = "",
        evidence_card_json: str = "",
        fund_manager_interpretation: str = "",
    ) -> int:
        """Insert a decision row and return the row ID."""
        conn = self._get_conn()
        try:
            row_id = self._next_id(conn, "fund_manager_decisions")
            cursor = conn.execute("""
                INSERT INTO fund_manager_decisions (
                    id, run_id, symbol, date, day_index, close_price,
                    action, target_position_pct, confidence,
                    reason_codes, thesis_update, risk_flags, brief_rationale,
                    inner_journal, portfolio_state, execution_result,
                    iron_verdict, iron_blocks, iron_penalties,
                    snapshot_source, snapshot_schema_version,
                    v8_grade_at_decision, v8_score_at_decision,
                    iron_entry_verdict_at_decision,
                    iron_entry_blocks_at_decision,
                    toxic_breaker_factors_at_decision,
                    objective_tension_types_at_decision,
                    policy_gate_reason,
                    pattern_recall_version, embedding_arm, stats_id,
                    pca_artifact_id, top_k_case_ids, evidence_card_json,
                    fund_manager_interpretation
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row_id, run_id, symbol, date, day_index, close_price,
                action, target_position_pct, confidence,
                json.dumps(reason_codes, ensure_ascii=False),
                json.dumps(thesis_update, ensure_ascii=False),
                json.dumps(risk_flags, ensure_ascii=False),
                brief_rationale,
                inner_journal,
                json.dumps(portfolio_state, ensure_ascii=False),
                json.dumps(execution_result, ensure_ascii=False),
                iron_verdict,
                json.dumps(iron_blocks or [], ensure_ascii=False),
                json.dumps(iron_penalties or [], ensure_ascii=False),
                snapshot_source,
                snapshot_schema_version,
                v8_grade_at_decision,
                v8_score_at_decision,
                iron_entry_verdict_at_decision,
                json.dumps(
                    iron_entry_blocks_at_decision or [],
                    ensure_ascii=False,
                ),
                json.dumps(
                    toxic_breaker_factors_at_decision or [],
                    ensure_ascii=False,
                ),
                json.dumps(
                    objective_tension_types_at_decision or [],
                    ensure_ascii=False,
                ),
                policy_gate_reason,
                pattern_recall_version,
                embedding_arm,
                stats_id,
                pca_artifact_id,
                top_k_case_ids,
                evidence_card_json,
                fund_manager_interpretation,
            ))
            conn.commit()
            return row_id
        except Exception as e:
            logger.error("Failed to log decision: %s", e)
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_run_decisions(self, run_id: str) -> list[dict]:
        """Get all decisions for a run."""
        conn = self._get_conn()
        try:
            cursor = conn.execute("""
                SELECT * FROM fund_manager_decisions
                WHERE run_id = ?
                ORDER BY day_index ASC
            """, (run_id,))
            return self._fetchall_dicts(cursor)
        finally:
            conn.close()

    def get_run_summary(self, run_id: str) -> dict:
        """Compute PnL, Sharpe, etc. for a run."""
        decisions = self.get_run_decisions(run_id)
        if not decisions:
            return {"error": "No decisions found"}

        # Reconstruct portfolio evolution
        trades = []
        equity_curve = []

        for d in decisions:
            portfolio_state = json.loads(d["portfolio_state"])
            execution_result = json.loads(d["execution_result"])

            equity_curve.append({
                "date": d["date"],
                "day_index": d["day_index"],
                "equity": portfolio_state.get("equity", 0),
            })

            if execution_result.get("executed"):
                trades.append({
                    "date": d["date"],
                    "action": d["action"],
                    "price": d.get("close_price", 0),
                })

        if not equity_curve:
            return {"error": "No equity data"}

        # Calculate metrics
        initial_equity = equity_curve[0]["equity"] if equity_curve else 100000
        final_equity = equity_curve[-1]["equity"]

        total_return = (final_equity / initial_equity) - 1

        # Calculate daily returns for Sharpe
        daily_returns = []
        for i in range(1, len(equity_curve)):
            prev_equity = equity_curve[i - 1]["equity"]
            curr_equity = equity_curve[i]["equity"]
            if prev_equity > 0:
                daily_returns.append((curr_equity / prev_equity) - 1)

        import math
        import statistics
        sharpe = 0.0
        sortino = 0.0
        if daily_returns:
            mean_return = statistics.mean(daily_returns)
            std_return = statistics.stdev(daily_returns) if len(daily_returns) > 1 else 0
            if std_return > 0:
                sharpe = (mean_return / std_return) * (252 ** 0.5)  # Annualized

            # Sortino: only penalize downside volatility (PMPT)
            rf_daily = (1.03 ** (1 / 252)) - 1  # 3% annual risk-free rate
            downside_diffs = [min(r - rf_daily, 0.0) for r in daily_returns]
            n_total = len(daily_returns)
            downside_std = math.sqrt(sum(d ** 2 for d in downside_diffs) / n_total) if n_total > 0 else 0.0
            if downside_std > 1e-8:
                sortino = ((mean_return - rf_daily) / downside_std) * math.sqrt(252)

        # Max drawdown
        max_dd = 0.0
        peak = equity_curve[0]["equity"]
        for e in equity_curve:
            if e["equity"] > peak:
                peak = e["equity"]
            dd = (peak - e["equity"]) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        # Calmar: annualized return / max drawdown
        import math as _math
        n_days = len(equity_curve)
        ann_return = ((1 + total_return) ** (252 / n_days) - 1) if n_days > 0 else 0
        calmar = ann_return / max_dd if max_dd > 0.001 else 0.0

        return {
            "run_id": run_id,
            "total_decisions": len(decisions),
            "total_trades": len(trades),
            "initial_equity": round(initial_equity, 2),
            "final_equity": round(final_equity, 2),
            "total_return_pct": round(total_return * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "sortino_ratio": round(sortino, 2),
            "calmar_ratio": round(calmar, 2),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "days": len(equity_curve),
        }

    def save_ghost_trades(self, run_id: str, symbol: str, ghost_report: list[dict]):
        """Persist ghost trade results to DB."""
        conn = self._get_conn()
        try:
            for ghost in ghost_report:
                row_id = self._next_id(conn, "ghost_trades")
                conn.execute("""
                    INSERT INTO ghost_trades (
                        id, run_id, symbol, fork_date, fork_price,
                        shares_held, mfe_pct, mae_pct, regret_score, horizon, days_tracked
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    row_id,
                    run_id,
                    symbol,
                    ghost["fork_date"],
                    ghost["fork_price"],
                    ghost["shares_held"],
                    ghost["mfe_pct"],
                    ghost["mae_pct"],
                    ghost["regret_score"],
                    ghost.get("horizon", 20),
                    ghost.get("days_tracked", 0),
                ))
            conn.commit()
            logger.info("Saved %d ghost trades for run %s", len(ghost_report), run_id)
        except Exception as e:
            logger.error("Failed to save ghost trades: %s", e)
            conn.rollback()
        finally:
            conn.close()

    @staticmethod
    def _load_json_blob(raw_value: str | dict | None) -> dict:
        """Best-effort JSON loader for stored blobs."""
        if isinstance(raw_value, dict):
            return raw_value
        if not raw_value:
            return {}
        try:
            parsed = json.loads(raw_value)
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _bar_date(bar: dict) -> str:
        return bar.get("local_date", bar.get("date", ""))

    @staticmethod
    def _bar_close(bar: dict) -> float:
        return bar.get("close", bar.get("close_price", 0)) or 0.0

    def _build_bar_index(self, bars: list[dict]) -> dict[str, int]:
        return {
            self._bar_date(bar): idx
            for idx, bar in enumerate(bars)
            if self._bar_date(bar)
        }

    def _compute_forward_outcome(
        self,
        decision: dict,
        bars: list[dict],
        bar_index_by_date: dict[str, int],
        lookahead: int,
    ) -> tuple[str, float, dict, float] | None:
        """Return T+N validation outcome for a decision row."""
        t_date = decision.get("date", "")
        t_price = decision.get("close_price", 0) or 0.0
        if not t_date or t_price <= 0:
            return None

        idx = bar_index_by_date.get(t_date)
        if idx is None or idx + lookahead >= len(bars):
            return None

        t_n_bar = bars[idx + lookahead]
        t_n_price = self._bar_close(t_n_bar)
        if t_n_price <= 0:
            return None

        pnl = (t_n_price - t_price) / t_price
        return t_date, t_price, t_n_bar, pnl

    def _insert_journal_verdict(
        self,
        conn: duckdb.DuckDBPyConnection,
        decision: dict,
        run_id: str,
        action_taken: str,
        verdict: str,
        lesson: str,
        t_date: str,
        t_price: float,
        t_n_bar: dict,
        t_n_price: float,
        pnl: float,
    ) -> None:
        """Persist one validated case into journal_verdicts."""
        journal = decision.get("inner_journal", "")
        row_id = self._next_id(conn, "journal_verdicts")
        conn.execute("""
            INSERT INTO journal_verdicts (
                id, decision_id, run_id, journal_date, verdict_date,
                action_taken, price_at_action, price_at_verdict, pnl_pct, verdict,
                lesson_extracted, inner_journal_snippet
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row_id,
            decision.get("id"),
            run_id,
            t_date,
            self._bar_date(t_n_bar),
            action_taken,
            t_price,
            t_n_price,
            round(pnl * 100, 2),
            verdict,
            lesson,
            journal[:200] if journal else "",
        ))

    def validate_journals(self, run_id: str, bars: list[dict], lookahead: int = 10):
        """Post-backtest: validate each SELL/TRIM journal entry against T+N outcome."""
        decisions = self.get_run_decisions(run_id)
        bar_index_by_date = self._build_bar_index(bars)

        validated = 0
        conn = self._get_conn()
        try:
            for decision in decisions:
                action = str(decision.get("action", "") or "").upper()
                if action not in ("SELL", "TRIM"):
                    continue

                journal = decision.get("inner_journal", "")
                if not journal:
                    continue

                outcome = self._compute_forward_outcome(
                    decision, bars, bar_index_by_date, lookahead
                )
                if outcome is None:
                    continue

                t_date, t_price, t_n_bar, pnl = outcome
                t_n_price = self._bar_close(t_n_bar)

                if pnl > 0.15:
                    verdict = "REFUTED"
                    lesson = (
                        f"[LESSON-NEG] Sold at {t_price:.1f} on {t_date}, "
                        f"price went to {t_n_price:.1f} (+{pnl:.0%}) in {lookahead}d. "
                        "Fear was irrational."
                    )
                elif pnl < -0.05:
                    verdict = "VALIDATED"
                    lesson = (
                        f"[LESSON-POS] Correctly exited at {t_price:.1f} on {t_date}, "
                        f"price dropped to {t_n_price:.1f} ({pnl:.0%}) in {lookahead}d."
                    )
                else:
                    continue

                self._insert_journal_verdict(
                    conn=conn,
                    decision=decision,
                    run_id=run_id,
                    action_taken=action,
                    verdict=verdict,
                    lesson=lesson,
                    t_date=t_date,
                    t_price=t_price,
                    t_n_bar=t_n_bar,
                    t_n_price=t_n_price,
                    pnl=pnl,
                )
                validated += 1

            conn.commit()
            logger.info("Validated %d journal entries for run %s", validated, run_id)
        except Exception as e:
            logger.error("Failed to validate journals: %s", e)
            conn.rollback()
        finally:
            conn.close()

    def validate_missed_entries(self, run_id: str, bars: list[dict], lookahead: int = 10):
        """Post-backtest: check WAIT decisions where a buy signal existed."""
        decisions = self.get_run_decisions(run_id)
        bar_index_by_date = self._build_bar_index(bars)

        validated = 0
        conn = self._get_conn()
        try:
            for decision in decisions:
                action = decision.get("action", "")
                if action != "WAIT":
                    continue

                # Check if there was a buy signal on this day
                # We look at execution_result for reason_codes or check portfolio_state
                exec_result = self._load_json_blob(decision.get("execution_result", "{}"))
                portfolio_state = self._load_json_blob(decision.get("portfolio_state", "{}"))

                # Only flag if agent was in cash (no position)
                if portfolio_state.get("shares", 0) > 0:
                    continue

                journal = decision.get("inner_journal", "")
                outcome = self._compute_forward_outcome(
                    decision, bars, bar_index_by_date, lookahead
                )
                if outcome is None:
                    continue

                t_date, t_price, t_n_bar, pnl = outcome
                t_n_price = self._bar_close(t_n_bar)

                if pnl > 0.15:
                    verdict = "MISSED_ENTRY"
                    lesson = (
                        f"[FOMO] Waited at {t_price:.1f} on {t_date}, "
                        f"price went to {t_n_price:.1f} (+{pnl:.0%}) in {lookahead}d. "
                        "Should have entered."
                    )
                elif pnl < -0.05:
                    verdict = "CORRECT_WAIT"
                    lesson = (
                        f"[VALIDATED] Correctly waited at {t_price:.1f} on {t_date}, "
                        f"price dropped to {t_n_price:.1f} ({pnl:.0%}) in {lookahead}d."
                    )
                else:
                    continue  # Skip neutral outcomes for WAIT

                self._insert_journal_verdict(
                    conn=conn,
                    decision=decision,
                    run_id=run_id,
                    action_taken="WAIT",
                    verdict=verdict,
                    lesson=lesson,
                    t_date=t_date,
                    t_price=t_price,
                    t_n_bar=t_n_bar,
                    t_n_price=t_n_price,
                    pnl=pnl,
                )
                validated += 1

            conn.commit()
            logger.info("Validated %d missed entries for run %s", validated, run_id)
        except Exception as e:
            logger.error("Failed to validate missed entries: %s", e)
            conn.rollback()
        finally:
            conn.close()

    def validate_entries(self, run_id: str, bars: list[dict], lookahead: int = 10):
        """Post-backtest: validate BUY/ADD decisions against T+N outcome."""
        decisions = self.get_run_decisions(run_id)
        bar_index_by_date = self._build_bar_index(bars)

        validated = 0
        conn = self._get_conn()
        try:
            for decision in decisions:
                action = str(decision.get("action", "") or "").upper()
                if action not in ("BUY", "ADD"):
                    continue

                outcome = self._compute_forward_outcome(
                    decision, bars, bar_index_by_date, lookahead
                )
                if outcome is None:
                    continue

                t_date, t_price, t_n_bar, pnl = outcome
                t_n_price = self._bar_close(t_n_bar)

                if pnl > 0.10:
                    verdict = "GOOD_ENTRY"
                    lesson = (
                        f"[GOOD_ENTRY] Bought at {t_price:.2f} on {t_date}, "
                        f"price rose to {t_n_price:.2f} ({pnl:+.0%}) in {lookahead}d. "
                        "Entry was correct."
                    )
                elif pnl < -0.05:
                    verdict = "BAD_ENTRY"
                    lesson = (
                        f"[BAD_ENTRY] Bought at {t_price:.2f} on {t_date}, "
                        f"price dropped to {t_n_price:.2f} ({pnl:+.0%}) in {lookahead}d. "
                        "Entry was premature."
                    )
                else:
                    continue

                self._insert_journal_verdict(
                    conn=conn,
                    decision=decision,
                    run_id=run_id,
                    action_taken=action,
                    verdict=verdict,
                    lesson=lesson,
                    t_date=t_date,
                    t_price=t_price,
                    t_n_bar=t_n_bar,
                    t_n_price=t_n_price,
                    pnl=pnl,
                )
                validated += 1

            conn.commit()
            logger.info("Validated %d entries for run %s", validated, run_id)
        except Exception as e:
            logger.error("Failed to validate entries: %s", e)
            conn.rollback()
        finally:
            conn.close()

    def validate_hold_skips(self, run_id: str, bars: list[dict], lookahead: int = 10):
        """Post-backtest: validate skip/hold exit impulses while in position."""
        decisions = self.get_run_decisions(run_id)
        bar_index_by_date = self._build_bar_index(bars)

        validated = 0
        conn = self._get_conn()
        try:
            for decision in decisions:
                action = str(decision.get("action", "") or "").upper()
                exec_result = self._load_json_blob(decision.get("execution_result", "{}"))
                portfolio_state = self._load_json_blob(decision.get("portfolio_state", "{}"))
                resolved_conviction = str(
                    exec_result.get("resolved_conviction") or ""
                ).upper()

                is_hold_skip = action in ("WAIT", "HOLD") and portfolio_state.get("shares", 0) > 0
                is_skip_exit = action in ("SELL", "TRIM") and resolved_conviction == "SKIP"
                if not (is_hold_skip or is_skip_exit):
                    continue

                outcome = self._compute_forward_outcome(
                    decision, bars, bar_index_by_date, lookahead
                )
                if outcome is None:
                    continue

                t_date, t_price, t_n_bar, pnl = outcome
                t_n_price = self._bar_close(t_n_bar)

                if pnl > 0.10:
                    verdict = "PREMATURE_EXIT"
                    lesson = (
                        f"[PREMATURE_EXIT] Exit signal at {t_price:.2f} on {t_date}, "
                        f"price rose to {t_n_price:.2f} ({pnl:+.0%}) in {lookahead}d. "
                        "The exit was premature."
                    )
                elif pnl < -0.05:
                    verdict = "GOOD_EXIT"
                    lesson = (
                        f"[GOOD_EXIT] Exit signal at {t_price:.2f} on {t_date}, "
                        f"price fell to {t_n_price:.2f} ({pnl:+.0%}) in {lookahead}d. "
                        "Exiting was correct."
                    )
                else:
                    continue

                self._insert_journal_verdict(
                    conn=conn,
                    decision=decision,
                    run_id=run_id,
                    action_taken=action,
                    verdict=verdict,
                    lesson=lesson,
                    t_date=t_date,
                    t_price=t_price,
                    t_n_bar=t_n_bar,
                    t_n_price=t_n_price,
                    pnl=pnl,
                )
                validated += 1

            conn.commit()
            logger.info("Validated %d hold/skip exits for run %s", validated, run_id)
        except Exception as e:
            logger.error("Failed to validate hold skips: %s", e)
            conn.rollback()
        finally:
            conn.close()

    def _row_to_dict(self, row) -> dict:
        """Convert a row-like object to dict."""
        return dict(row)
