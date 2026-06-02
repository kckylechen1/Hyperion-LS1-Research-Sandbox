"""Main backtest loop for LLM-as-Fund-Manager."""

import logging
import sqlite3
from collections import Counter
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

from .execution_sim import ExecutionSimulator
from .ghost_portfolio import GhostPortfolioTracker
from .journal_rag import CaseRAG
from .ledger import DecisionLedger
from .pattern_recall import PatternRecallProvider
from .position_policy import PositionPolicy, ShieldMode, WinnerState
from .prompts import SYSTEM_PROMPT, build_daily_prompt, parse_llm_decision
from .sector_resonance import SectorResonance
from .snapshot_adapter import adapt_snapshot, build_rolling_digest
from .watchpoint_eval import check_t0_tautology, eval_watchpoints

try:
    from engine.v8.core.v8_score import calculate_v8_score, build_prior_memory_entry
except ImportError:
    calculate_v8_score = None
    build_prior_memory_entry = None

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_ROLLING_HISTORY_MAXLEN = 61
_EVENT_COMPACT_INTERVAL_DAYS = 30


def default_thesis() -> dict:
    """Default thesis state (no position)."""
    return {
        "regime_view": "NEUTRAL",
        "invalidation_price": None,
        "add_zone": [],
        "trim_zone": [],
        "entry_triggered": False,
    }


def default_structural_memory() -> dict:
    """Default structural memory."""
    return {
        "last_zs_ladder": None,
        "last_bsp_type": None,
        "trend_start_date": None,
        "high_water_mark": None,
    }


class EpisodeRunner:
    """Run a full backtest episode with LLM fund manager."""

    def __init__(
        self,
        symbol: str,
        name: str,
        initial_cash: float = 100000.0,
        llm_model: str = "claude",
        run_id: str | None = None,
    ):
        self.symbol = symbol
        self.name = name
        self.sim = ExecutionSimulator(initial_cash, symbol=symbol)

        # Import LLMClient from nightly
        try:
            from autoresearch_lab.nightly.llm_client import LLMClient

            self.llm = LLMClient(model=llm_model)
        except ImportError as e:
            logger.error("Failed to import LLMClient: %s", e)
            self.llm = None

        self.run_id = run_id or f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # V5.1: Per-run DB for physical journal isolation (Oracle recommendation)
        self.run_db_dir = _PROJECT_ROOT / "data" / "runs"
        self.run_db_dir.mkdir(parents=True, exist_ok=True)
        self.run_db_path = self.run_db_dir / f"{self.run_id}.db"

        # V8: JSONL journal — human-readable decision log
        self._journal_dir = _PROJECT_ROOT / "autoresearch_lab" / "fund_manager" / "results"
        self._journal_dir.mkdir(parents=True, exist_ok=True)
        self._journal_path = self._journal_dir / f"{self.run_id}.jsonl"
        self._journal_file = None

        # State
        self.thesis_state = default_thesis()
        self.structural_memory = default_structural_memory()
        self.event_memory: deque[dict] = deque(maxlen=50)
        self.ghost_tracker = GhostPortfolioTracker()

        # V5: Position policy (deterministic sizing)
        self.position_policy = PositionPolicy()
        self.position_policy.sim = self.sim
        self.winner_state = WinnerState()

        # V5.1: Ledger and CaseRAG use per-run DB
        self.ledger = DecisionLedger(db_path=self.run_db_path)
        self.journal_rag = CaseRAG(db_path=str(self.run_db_path), run_id=self.run_id)
        self.pattern_recall = PatternRecallProvider(enabled=True)

        # V5: Sector resonance (cross-stock confirmation)
        self.sector_resonance = SectorResonance()
        self._consecutive_skip_count = 0
        self._last_buy_day = None  # Track last buy day for Grace Period
        self._last_sell_day = None  # P1: Track last sell day for T+3 cooling period tracking
        self._last_trim_day = None  # P2: Track last TRIM day for 5-day cooldown
        self._active_watchpoints = None
        self._prev_snapshot = None
        self._days_since_last_llm_call = 0
        self._watchpoint_set_day = 0
        self._triggered_labels = []
        self._wakeup_reason = ""
        self._watchpoint_wake = False
        self._day_pattern_recall_bundle: dict | None = None

    def _prepare_pattern_recall_for_day(self, date: str, trade_idx: int) -> dict | None:
        """Fetch Pattern Recall once per bar; shared by prompt and ledger."""
        self._day_pattern_recall_bundle = self.pattern_recall.fetch_evidence(
            symbol=self.symbol,
            as_of_date=date,
            trade_idx=trade_idx,
        )
        return self._day_pattern_recall_bundle

    def _pattern_recall_prompt_block(self) -> str:
        return self.pattern_recall.format_for_prompt(self._day_pattern_recall_bundle)

    def run(
        self,
        bars: list[dict],
        snapshots: Optional[list[dict]] = None,
        start_day: int = 60,
        max_days: Optional[int] = None,
        skip_llm_on_flat: bool = True,
        flat_threshold: float = 0.5,
    ) -> dict:
        """Run full episode.

        Args:
            bars: list of daily OHLCV dicts with 'local_date', 'open', 'high',
                  'low', 'close', 'volume'
            snapshots: optional pre-computed V8 snapshots aligned with bars
            start_day: skip first N days for indicator warmup
            max_days: maximum days to run (None = all)
            skip_llm_on_flat: skip LLM call on flat days with no position
            flat_threshold: max daily change % to consider "flat"

        Returns:
            Summary dict with run metrics
        """
        if not bars:
            return {"error": "No bars provided"}

        if snapshots is None:
            logger.warning("No snapshots provided, using basic indicators only")
            snapshots = [None] * len(bars)

        snapshots_history: deque[dict] = deque(maxlen=_ROLLING_HISTORY_MAXLEN)
        temporal_memory: deque[dict] = deque(maxlen=5)
        conviction_counts = Counter({"SKIP": 0, "PROBE": 0, "HIGH": 0, "MAX": 0})
        auto_skip_count = 0
        llm_skip_count = 0
        policy_action_override_count = 0
        position_pct_sum_in_market = 0.0
        days_in_market = 0

        end_day = min(len(bars), start_day + (max_days or len(bars)))
        total_days = max(end_day - start_day, 0)
        if total_days == 0:
            return {"error": "No bars traded"}

        # Open JSONL journal
        self._journal_file = open(self._journal_path, "a")
        logger.info("JSONL journal → %s", self._journal_path)

        for i in range(start_day, end_day):
            bar = bars[i]
            snap = snapshots[i] if i < len(snapshots) else None
            date = bar.get("local_date", bar.get("date", f"day_{i}"))

            # Advance T+1 at start of day
            self.sim.advance_day()
            self.ghost_tracker.tick(bar["close"])

            # Build or adapt snapshot
            if snap:
                adapted = adapt_snapshot(snap)
                # P3.2: Preserve raw gates consumed by deterministic policy.
                for raw_key in (
                    "chan_daily",
                    "objective_tensions",
                    "macro_sentinel",
                    "crash_signals",
                ):
                    if raw_key in snap:
                        adapted[raw_key] = snap[raw_key]
            else:
                adapted = _build_basic_snapshot(bars[: i + 1])
            adapted.setdefault("price", {})["date"] = date

            snapshots_history.append(adapted)

            # Build rolling digest
            history_window = list(snapshots_history)
            rolling = build_rolling_digest(history_window, len(history_window) - 1)

            # V6: Compute V8 score for Oracle Floor and P3 Interrupts
            v8_result = {"grade": "C", "entry_score": 0, "is_overheated": False}
            for mem_entry in temporal_memory:
                mem_entry["lag"] = int(mem_entry.get("lag", 0)) + 1
            if calculate_v8_score and snap and not snap.get("_degraded"):
                try:
                    v8_result = calculate_v8_score(
                        snap,
                        prior_memory=list(temporal_memory),
                    )
                    if build_prior_memory_entry:
                        memory_entry = build_prior_memory_entry(
                            v8_result,
                            close=bar.get("close", 0.0),
                            signal_date=date,
                            symbol=adapted.get("symbol") or (snap or {}).get("symbol"),
                            name=adapted.get("name") or (snap or {}).get("name"),
                        )
                        if memory_entry:
                            temporal_memory.append(memory_entry)
                except Exception as e:
                    logger.error("V8 Score failed: %s", e)

            # P2 FIX: Inject v8_result into adapted snapshot so prompts.py
            # can render the Fire-Control Matrix (setup_score, left/right, etc.)
            # Only overwrite if V8 was actually computed (not the fallback default)
            if v8_result.get("score") is not None or v8_result.get("setup_score") is not None:
                adapted["v8_score"] = v8_result
            elif "v8_score" not in adapted:
                adapted["v8_score"] = v8_result

            current_equity = self.sim.cash + self.sim.shares * bar["close"]
            current_position_pct = (
                (self.sim.shares * bar["close"]) / current_equity
                if current_equity > 0
                else 0.0
            )
            unrealized_pnl_pct = 0.0
            if self.sim.shares > 0 and self.sim.avg_cost > 0:
                unrealized_pnl_pct = (bar["close"] / self.sim.avg_cost - 1) * 100
            self._update_winner_state(bar["close"], adapted, unrealized_pnl_pct, v8_result)
            if self.sim.shares > 0:
                if self.winner_state.entry_day is None and self._last_buy_day is not None:
                    self.winner_state.entry_day = self._last_buy_day
                holding_days = (
                    i - self.winner_state.entry_day
                    if self.winner_state.entry_day is not None
                    else 0
                )
            else:
                holding_days = 0

            self._prepare_pattern_recall_for_day(date, i)

            # Check if we should call LLM
            should_call = self._should_call_llm(
                adapted, rolling, skip_llm_on_flat, flat_threshold, v8_result
            )

            decision = {
                "action": "HOLD" if self.sim.shares > 0 else "WAIT",
                "conviction": "SKIP",
                "target_position_pct": 0.0,
                "confidence": 0.0,
                "reason_codes": ["SKIP_LLM"],
                "thesis_update": {},
                "risk_flags": [],
                "brief_rationale": "LLM skipped: no meaningful change"
                if self.sim.shares == 0
                else "LLM skipped: degraded data, auto-HOLD",
            }

            raw_llm_output = None
            parse_ok = None

            if should_call and self.llm:
                had_active_watchpoints = bool(self._active_watchpoints)
                decision, raw_llm_output, parse_ok = self._call_llm_with_raw(
                    date, adapted, rolling, trade_idx=i
                )
                if had_active_watchpoints:
                    self._active_watchpoints = None
                self._days_since_last_llm_call = 0

                raw_wp = decision.get("watchpoints")
                if raw_wp and isinstance(raw_wp, dict) and raw_wp.get("events"):
                    sanitized = check_t0_tautology(
                        raw_wp, adapted, self._prev_snapshot or adapted
                    )
                    if sanitized.get("events"):
                        self._active_watchpoints = sanitized
                        self._watchpoint_set_day = i
                        logger.info(
                            "Watchpoints set: %s",
                            list(sanitized["events"].keys()),
                        )
                    else:
                        self._active_watchpoints = None
                        logger.info("All watchpoints were T0 tautologies, discarded")
                else:
                    self._active_watchpoints = None
            elif not should_call:
                auto_skip_count += 1
                logger.debug("Skipping LLM on %s", date)
                self._days_since_last_llm_call += 1
            else:
                self._days_since_last_llm_call += 1

            # --- V5 Position Policy Layer ---
            # LLM decides direction + conviction, code decides exact size
            # Handle backward compatibility: if conviction field is missing,
            # fall back to target_position_pct (V4 behavior)
            conviction = str(decision.get("conviction") or "SKIP").upper()
            if conviction == "LOW":
                conviction = "PROBE"
            original_action = str(decision.get("action") or "WAIT").upper()

            if should_call and self.llm and conviction == "SKIP":
                llm_skip_count += 1

            if conviction in ("SKIP", "PROBE", "HIGH", "MAX"):
                # V8 score is now computed earlier

                # V5.1 path: LLM provides conviction only, code decides everything else
                target_pct = self.position_policy.compute_target_position(
                    conviction, adapted, v8_result=v8_result,
                    unrealized_pnl_pct=unrealized_pnl_pct,
                    is_new_entry=(self.sim.shares == 0),
                    winner_state=self.winner_state,
                    current_position_pct=current_position_pct,
                    holding_days=holding_days,
                )

                # V6: Use effective conviction (after Oracle Floor), NOT raw LLM conviction
                effective_conviction = self.position_policy.last_effective_conviction

                # P1: T+3 Cooling Period — block re-entry within 3 days of a sell
                # Journal data: 336 quick re-entries (≤5d), 82% at higher prices, 65% with FOMO language
                if (
                    effective_conviction in ("PROBE", "HIGH", "MAX")
                    and self.sim.shares == 0
                    and self._last_sell_day is not None
                    and (i - self._last_sell_day) <= 3
                ):
                    v8_grade_cool = v8_result.get("grade", "C") if v8_result else "C"
                    if v8_grade_cool != "S":
                        # Force SKIP: not strong enough to override cooling period
                        effective_conviction = "SKIP"
                        target_pct = 0.0
                        logger.debug(
                            f"[P1 Cooling] SKIP: {i - self._last_sell_day}d since sell, "
                            f"v8={v8_grade_cool}, blocking re-entry (need V8=S to override)"
                        )

                hard_stop_action = None
                hard_stop_target = current_position_pct
                guard_reason = None
                gate_reason = None
                if self.sim.shares > 0:
                    v8_grade_now = v8_result.get("grade", "C") if v8_result else "C"
                    unrealized_pnl = unrealized_pnl_pct

                    if unrealized_pnl < -10.0:
                        # Absolute circuit breaker: -10% drawdown = Python pulls the plug
                        hard_stop_action = "SELL"
                        hard_stop_target = 0.0
                        logger.debug(
                            f"[P1 CircuitBreaker] SELL: pnl={unrealized_pnl:+.1f}% < -10%, "
                            f"absolute hard stop triggered"
                        )
                    elif v8_grade_now == "D" and unrealized_pnl < -5.0:
                        # Physical hard stop: V8=D + losing >5% = structural collapse, exit
                        hard_stop_action = "SELL"
                        hard_stop_target = 0.0
                        logger.debug(
                            f"[P1 HardStop] SELL: V8=D + pnl={unrealized_pnl:+.1f}%, "
                            f"structural collapse confirmed"
                        )

                if hard_stop_action is not None:
                    final_action = hard_stop_action
                    final_target = hard_stop_target
                else:
                    final_action, final_target, guard_reason = (
                        self.position_policy.derive_guarded_action(
                            current_position_pct,
                            target_pct,
                            effective_conviction,
                            self.winner_state,
                        )
                    )

                    # P2 FIX: TRIM cooldown — block ADD within 5 days of TRIM
                    # Forensic: 52 TRIM↔ADD oscillations destroyed alpha (MFE 189% → 140%)
                    if (
                        final_action == "ADD"
                        and self._last_trim_day is not None
                        and (i - self._last_trim_day) <= 5
                    ):
                        final_action = "HOLD"
                        final_target = current_position_pct
                        logger.info(
                            f"[P2 TrimCooldown] ADD blocked: {i - self._last_trim_day}d since TRIM, "
                            f"need 5d cooldown"
                        )

                    if guard_reason == "skip_hold_guard":
                        v8_grade_now = v8_result.get("grade", "C") if v8_result else "C"
                        logger.debug(
                            f"[P1 HOLD] SKIP→HOLD: shield={self.winner_state.shield_mode.value}, "
                            f"v8={v8_grade_now}, pnl={unrealized_pnl_pct:+.1f}%, "
                            f"position locked at {current_position_pct:.2f}"
                        )
                    elif guard_reason == "damaged_add_block":
                        logger.debug(
                            f"[WinnerShield] DAMAGED: ADD blocked by action guard "
                            f"current={current_position_pct:.2f}, target={target_pct:.2f}"
                        )

                    logger.debug(
                        f"[V6 Policy] Derived action: {final_action}, "
                        f"conviction={conviction}, effective={effective_conviction}, "
                        f"v8={v8_result.get('grade','?')}, "
                        f"current_pct={current_position_pct:.2f}, target_pct={target_pct:.2f}"
                    )

                final_action, final_target, gate_reason = (
                    self.position_policy.apply_entry_hard_gates(
                        final_action,
                        final_target,
                        current_position_pct,
                        adapted,
                        v8_result,
                        conviction,
                        effective_conviction,
                    )
                )
                if gate_reason:
                    decision.setdefault("reason_codes", []).append(gate_reason)
                    logger.info(
                        "[P0 Gate] %s: action=%s target=%.2f current=%.2f",
                        gate_reason,
                        final_action,
                        final_target,
                        current_position_pct,
                    )

                # Override the decision with policy-computed values
                decision["action"] = final_action
                decision["target_position_pct"] = final_target
                decision["original_action"] = (
                    original_action  # LLM's action (if any, for logging)
                )
                decision["policy_overrode_action"] = final_action != original_action
                decision["original_conviction"] = conviction
                decision["policy_target_pct"] = target_pct
                decision["resolved_conviction"] = effective_conviction
                decision["policy_guard_reason"] = guard_reason
                decision["policy_gate_reason"] = gate_reason
                decision["v8_grade"] = v8_result.get("grade", "C")
                decision["trend_mode"] = adapted.get("momentum", {}).get("trend_mode", "range")
                if final_action != original_action:
                    policy_action_override_count += 1
            else:
                # V4 backward compatibility: LLM provided target_position_pct directly
                # or conviction field is missing/invalid
                if "target_position_pct" not in decision:
                    decision["target_position_pct"] = 0.0
                decision["original_action"] = original_action
                decision["policy_overrode_action"] = False
                decision["resolved_conviction"] = "SKIP"
                logger.debug(
                    f"[V5 Policy] Using V4 fallback (no conviction field): "
                    f"action={decision.get('action')}, "
                    f"target_pct={decision.get('target_position_pct')}"
                )
            # --------------------------------------

            resolved_conviction = str(
                decision.get("resolved_conviction") or "SKIP"
            ).upper()
            if resolved_conviction == "LOW":
                resolved_conviction = "PROBE"
            if resolved_conviction != "SKIP":
                self._consecutive_skip_count = 0
            if resolved_conviction in conviction_counts:
                conviction_counts[resolved_conviction] += 1

            elapsed_days = i - start_day + 1
            if total_days and ((i - start_day) % 10 == 0 or elapsed_days == total_days):
                logger.info(
                    "Day %d/%d: %s | equity=%.0f | pos=%.0f%% | action=%s | conviction=%s",
                    elapsed_days,
                    total_days,
                    date,
                    current_equity,
                    current_position_pct * 100,
                    decision.get("action"),
                    resolved_conviction,
                )

            # Execute at next day's open (or today's close if last day)
            execution_price = bar["close"]
            if i + 1 < len(bars):
                execution_price = bars[i + 1]["open"]

            pre_execute_shares = self.sim.shares
            exec_result = self.sim.execute_action(
                decision,
                execution_price,
                date,
                prev_close=bar["close"],
            )

            # P0: Track last buy day for grace period
            if exec_result.executed and decision.get("action") in ("BUY", "ADD"):
                self._last_buy_day = i
                if pre_execute_shares <= 0 and self.sim.shares > 0:
                    self.winner_state.entry_day = i

            # P1: Track last sell day for T+3 cooling period
            if exec_result.executed and decision.get("action") in ("SELL",) and self.sim.shares == 0:
                self._last_sell_day = i
                self._last_trim_day = None  # P2: Reset TRIM cooldown on full exit
                self.winner_state = WinnerState()

            # P2: Track last TRIM day for 5-day ADD cooldown
            if exec_result.executed and exec_result.action == "TRIM":
                self._last_trim_day = i

            # Get portfolio state
            portfolio_state = self.sim.get_state()
            current_equity = self.sim.cash + self.sim.shares * execution_price
            portfolio_state["equity"] = round(current_equity, 2)
            portfolio_state["date"] = date
            end_of_day_position_pct = (
                (self.sim.shares * execution_price) / current_equity
                if current_equity > 0
                else 0.0
            )
            if end_of_day_position_pct > 0.0001:
                days_in_market += 1
                position_pct_sum_in_market += end_of_day_position_pct

            # Persist policy override fields for analysis
            exec_result_dict = exec_result.__dict__
            exec_result_dict["original_conviction"] = decision.get(
                "original_conviction"
            )
            exec_result_dict["policy_target_pct"] = decision.get("policy_target_pct")
            exec_result_dict["original_action"] = decision.get("original_action")
            exec_result_dict["policy_overrode_action"] = decision.get(
                "policy_overrode_action", False
            )
            exec_result_dict["resolved_conviction"] = resolved_conviction
            exec_result_dict["v8_grade"] = decision.get("v8_grade", "C")
            exec_result_dict["trend_mode"] = decision.get("trend_mode", "range")
            exec_result_dict["policy_guard_reason"] = decision.get("policy_guard_reason")
            exec_result_dict["policy_gate_reason"] = decision.get("policy_gate_reason")

            # Log decision
            _iron = adapted.get("iron_rules", {}) or {}
            _v8_payload = adapted.get("v8_score", {}) or {}
            _toxic_factors = (
                v8_result.get("toxic_breaker_factors")
                or _v8_payload.get("toxic_breaker_factors")
                or []
            )
            _tensions = adapted.get("objective_tensions", {}) or {}
            _tension_types = [
                str(t.get("type"))
                for t in (_tensions.get("tension_list") or [])
                if isinstance(t, dict) and t.get("type")
            ]
            _pr_fields = self.pattern_recall.ledger_fields(self._day_pattern_recall_bundle)
            self.ledger.log_decision(
                run_id=self.run_id,
                symbol=self.symbol,
                date=date,
                day_index=i,
                close_price=bar["close"],
                action=decision.get("action", "WAIT"),
                target_position_pct=decision.get("target_position_pct", 0.0),
                confidence=decision.get("confidence", 0.0),
                reason_codes=decision.get("reason_codes", []),
                thesis_update=decision.get("thesis_update", {}),
                risk_flags=decision.get("risk_flags", []),
                brief_rationale=decision.get("brief_rationale", ""),
                inner_journal=decision.get("inner_journal", ""),
                portfolio_state=portfolio_state,
                execution_result=exec_result_dict,
                iron_verdict=_iron.get("entry_verdict") or _iron.get("verdict") or "",
                iron_blocks=_iron.get("entry_blocks", []),
                iron_penalties=_iron.get("entry_penalties", []),
                snapshot_source="runner_adapted",
                snapshot_schema_version="fund_manager_v8_p0",
                v8_grade_at_decision=v8_result.get("grade", "C"),
                v8_score_at_decision=v8_result.get("score"),
                iron_entry_verdict_at_decision=(
                    _iron.get("entry_verdict") or _iron.get("verdict") or ""
                ),
                iron_entry_blocks_at_decision=_iron.get("entry_blocks", []),
                toxic_breaker_factors_at_decision=_toxic_factors,
                objective_tension_types_at_decision=_tension_types,
                policy_gate_reason=decision.get("policy_gate_reason") or "",
                pattern_recall_version=_pr_fields.get("pattern_recall_version") or "",
                embedding_arm=_pr_fields.get("embedding_arm") or "",
                stats_id=_pr_fields.get("stats_id") or "",
                pca_artifact_id=_pr_fields.get("pca_artifact_id") or "",
                top_k_case_ids=_pr_fields.get("top_k_case_ids") or "",
                evidence_card_json=_pr_fields.get("evidence_card_json") or "",
                fund_manager_interpretation=_pr_fields.get("fund_manager_interpretation") or "",
            )

            # V8: JSONL journal entry
            if self._journal_file:
                try:
                    import json as _json
                    entry = {
                        "day": i - start_day + 1,
                        "date": date,
                        "close": bar["close"],
                        "equity": round(current_equity, 0),
                        "position_pct": round(end_of_day_position_pct * 100, 1),
                        "should_call_llm": should_call,
                        "llm_called": should_call and self.llm is not None,
                        "raw_output": raw_llm_output,
                        "parse_ok": parse_ok,
                        "conviction": decision.get("original_conviction", conviction),
                        "effective_conviction": resolved_conviction,
                        "v8_grade": v8_result.get("grade", "C"),
                        "shield_mode": self.winner_state.shield_mode.value,
                        "winner_floor_pct": round(self.winner_state.winner_floor_pct * 100, 1),
                        "action": decision.get("action", "WAIT"),
                        "target_pct": decision.get("policy_target_pct", 0.0),
                        "policy_gate_reason": decision.get("policy_gate_reason"),
                        "policy_guard_reason": decision.get("policy_guard_reason"),
                        "rationale": decision.get("brief_rationale", ""),
                        "inner_journal": decision.get("inner_journal", ""),
                        "watchpoints_active": bool(self._active_watchpoints),
                        "watchpoint_triggered": getattr(
                            self, "_triggered_labels", []
                        ),
                        "wakeup_reason": getattr(self, "_wakeup_reason", ""),
                        "days_since_last_llm": self._days_since_last_llm_call,
                    }
                    self._journal_file.write(
                        _json.dumps(entry, ensure_ascii=False) + "\n"
                    )
                    self._journal_file.flush()
                except Exception:
                    pass  # non-fatal
                self._triggered_labels = []
                self._wakeup_reason = ""
                self._watchpoint_wake = False

            # Update thesis and structural memory
            self._update_memory(decision, adapted, date)

            if (i - start_day) > 0 and (i - start_day) % _EVENT_COMPACT_INTERVAL_DAYS == 0:
                self._compress_event_memory()

            # Log events
            if exec_result.executed:
                total_shares = sum(fill.get("shares", 0) for fill in exec_result.fills)
                executed_price = execution_price
                if total_shares > 0:
                    weighted_price = sum(
                        float(fill.get("price", 0.0)) * int(fill.get("shares", 0))
                        for fill in exec_result.fills
                    )
                    if weighted_price > 0:
                        executed_price = weighted_price / total_shares
                self.event_memory.append(
                    {
                        "date": date,
                        "type": "trade",
                        "action": exec_result.action,
                        "shares": total_shares,
                        "price": round(float(executed_price), 4),
                        "event": (
                            f"{exec_result.action} {total_shares} share(s)"
                            f" @ {float(executed_price):.2f}"
                        ),
                    }
                )
                if exec_result.action == "SELL":
                    self.position_policy.record_exit(date, bar["close"])
                    if self.sim.shares == 0:
                        self.winner_state = WinnerState()
            if exec_result.executed and exec_result.action in ("SELL", "TRIM"):
                sold_shares = sum(fill["shares"] for fill in exec_result.fills)
                fork_price = (
                    exec_result.fills[0]["price"] if exec_result.fills else bar["close"]
                )
                self.ghost_tracker.fork(date, fork_price, sold_shares)

            self._prev_snapshot = adapted

        # Final summary
        if bars:
            final_price = bars[min(end_day, len(bars)) - 1]["close"]
            final_metrics = self.sim.get_metrics(final_price)
            final_metrics["run_id"] = self.run_id
            final_metrics["symbol"] = self.symbol
            final_metrics["days_traded"] = end_day - start_day
            final_metrics["conviction_counts"] = dict(conviction_counts)
            final_metrics["conviction_skip_count"] = conviction_counts["SKIP"]
            final_metrics["conviction_probe_count"] = conviction_counts["PROBE"]
            final_metrics["conviction_high_count"] = conviction_counts["HIGH"]
            final_metrics["conviction_max_count"] = conviction_counts["MAX"]
            final_metrics["auto_skip_count"] = auto_skip_count
            final_metrics["llm_skip_count"] = llm_skip_count
            final_metrics["policy_action_override_count"] = policy_action_override_count
            final_metrics["days_in_market"] = days_in_market
            final_metrics["avg_position_pct_in_market"] = round(
                ((position_pct_sum_in_market / days_in_market) * 100)
                if days_in_market
                else 0.0,
                2,
            )
            final_metrics["avg_position_size_when_in_market_pct"] = final_metrics[
                "avg_position_pct_in_market"
            ]
            final_metrics["time_in_market_pct"] = round(
                (days_in_market / total_days) * 100 if total_days else 0.0,
                2,
            )

            # Get ledger summary for more metrics
            ledger_summary = self.ledger.get_run_summary(self.run_id)
            final_metrics.update(ledger_summary)

            ghost_report = self.ghost_tracker.get_report()
            final_metrics["ghost_trades"] = ghost_report
            self.ledger.save_ghost_trades(self.run_id, self.symbol, ghost_report)

            self.ledger.validate_journals(self.run_id, bars, lookahead=10)
            self.ledger.validate_missed_entries(self.run_id, bars, lookahead=10)
            self.ledger.validate_entries(self.run_id, bars, lookahead=10)
            self.ledger.validate_hold_skips(self.run_id, bars, lookahead=10)

            # Close JSONL journal
            if self._journal_file:
                self._journal_file.close()
                self._journal_file = None
                logger.info("JSONL journal saved: %s", self._journal_path)

            return final_metrics

        if self._journal_file:
            self._journal_file.close()
            self._journal_file = None
        return {"error": "No bars traded"}

    def _update_winner_state(
        self,
        close_price: float,
        adapted: dict,
        unrealized_pnl_pct: float,
        v8_result: dict | None = None,
    ) -> None:
        """Update high-water winner lifecycle state for the held position."""
        if self.sim.shares <= 0 or self.sim.avg_cost <= 0:
            self.winner_state = WinnerState()
            return

        winner = self.winner_state
        close_val = PositionPolicy._to_float(close_price, 0.0)
        prior_20_high = max(winner.recent_closes) if winner.recent_closes else 0.0
        made_new_20d_high = close_val > 0 and prior_20_high > 0 and close_val > prior_20_high

        if close_val > winner.peak_price:
            winner.peak_price = close_val
        if unrealized_pnl_pct > winner.peak_pnl_pct:
            winner.peak_pnl_pct = unrealized_pnl_pct

        ma20 = PositionPolicy._to_float(
            adapted.get("indicators", {}).get("ma20", 0.0),
            0.0,
        )
        if close_val > 0 and ma20 > 0 and close_val < ma20:
            winner.days_below_ma20 += 1
            winner.days_above_ma20 = 0
        else:
            winner.days_below_ma20 = 0
            if close_val > 0 and ma20 > 0 and close_val > ma20:
                winner.days_above_ma20 += 1
            else:
                winner.days_above_ma20 = 0

        v8_grade = str((v8_result or {}).get("grade", "C")).upper()
        if v8_grade == "D":
            winner.v8_d_days += 1
        else:
            winner.v8_d_days = 0

        atr_pct = PositionPolicy._to_float(
            adapted.get("indicators", {}).get("atr_pct", 0.0),
            0.0,
        )
        peak_drawdown_pct = 0.0
        if close_val > 0 and winner.peak_price > 0:
            peak_drawdown_pct = (
                (winner.peak_price - close_val) / winner.peak_price * 100
            )

        exit_reason = None
        if winner.days_below_ma20 >= 5:
            exit_reason = f"{winner.days_below_ma20} closes below MA20"
        elif winner.v8_d_days >= 3:
            exit_reason = f"V8=D for {winner.v8_d_days} days"
        elif atr_pct > 0 and peak_drawdown_pct >= 4 * atr_pct:
            exit_reason = (
                f"peak drawdown {peak_drawdown_pct:.1f}% >= 4x ATR {atr_pct:.1f}%"
            )

        if exit_reason and winner.shield_mode != ShieldMode.EXITED:
            winner.shield_mode = ShieldMode.EXITED
            winner.winner_floor_pct = 0.0
            logger.info("[WinnerShield] EXITED: %s", exit_reason)
        elif winner.shield_mode == ShieldMode.DAMAGED:
            if winner.days_above_ma20 >= 3 or made_new_20d_high:
                winner.shield_mode = ShieldMode.ACTIVE
                logger.info("[WinnerShield] RECOVERED")
        elif winner.shield_mode == ShieldMode.ACTIVE:
            damage_reason = None
            if winner.days_below_ma20 >= 2:
                damage_reason = f"{winner.days_below_ma20} closes below MA20"
            elif atr_pct > 0 and peak_drawdown_pct >= 2 * atr_pct:
                damage_reason = (
                    f"peak drawdown {peak_drawdown_pct:.1f}% >= 2x ATR {atr_pct:.1f}%"
                )

            if damage_reason:
                winner.shield_mode = ShieldMode.DAMAGED
                logger.info("[WinnerShield] DAMAGED: %s", damage_reason)

        if close_val > 0:
            winner.recent_closes.append(close_val)

    def _should_call_llm(
        self,
        adapted: dict,
        rolling: dict,
        skip_on_flat: bool,
        threshold: float,
        v8_result: dict = None,
    ) -> bool:
        """Decide whether to call LLM based on market state."""
        self._triggered_labels = []
        self._wakeup_reason = ""
        self._watchpoint_wake = False

        # 🚨 [V4 SURGERY 1] The N/A Blackhole Breaker (数据幽闭恐惧症断路器)
        # 停止在空数据上白白烧钱。没带枪，就别上战场。
        # V6: degraded snapshots now compute talib indicators, so only block
        # when ADX is truly missing (not merely because _degraded flag is set).
        adx = adapted.get("indicators", {}).get("adx")
        has_no_adx = adx in (None, "N/A", "unknown", "") or adx == 0

        # 如果核心指标缺失，直接物理拔线，底层静默返回 WAIT 或 HOLD
        if has_no_adx:
            return False

        active_watchpoints = getattr(self, "_active_watchpoints", None)
        days_since_last_call = getattr(self, "_days_since_last_llm_call", 0)
        if active_watchpoints:
            wake, labels, reason = eval_watchpoints(
                active_watchpoints,
                adapted,
                getattr(self, "_prev_snapshot", None) or adapted,
                days_since_last_call,
            )
            if wake:
                self._wakeup_reason = reason
                self._triggered_labels = labels
                self._watchpoint_wake = True
                logger.info("Watchpoint wake: %s — %s", labels, reason)
                return True
        elif days_since_last_call >= 5:
            self._wakeup_reason = (
                "No watchpoints set, heartbeat wake after %d days"
                % days_since_last_call
            )
            self._triggered_labels = ["heartbeat"]

        if not skip_on_flat:
            return True

        v8_grade = (v8_result or {}).get("grade", "C")
        chan = adapted.get("chan", {})

        # --- Phase 3: Event-Driven Interrupt ---
        # When holding a position, DO NOT call LLM unless structural weakness triggers an interrupt
        if self.sim.shares > 0:
            winner_state = getattr(self, "winner_state", WinnerState())
            if winner_state.shield_mode == ShieldMode.EXITED:
                logger.debug("P3.1 Interrupt: WinnerShield EXITED, waking LLM")
                return True

            trendlock_locked = bool(
                getattr(self.position_policy, "trend_lock", None)
                and self.position_policy.trend_lock.locked
            )

            # Count structural damage signals instead of triggering on any single one
            damage_signals = 0

            # Signal 1: Momentum collapse
            if v8_grade == "C":
                if not trendlock_locked:
                    damage_signals += 1
                    logger.debug("P3 damage signal: V8 degraded to C")

            # Signal 2: Price structure breakdown
            try:
                close_price = float(adapted.get("price", {}).get("close", 0))
                ma20 = float(adapted.get("indicators", {}).get("ma20", 0))
                if close_price < ma20 and ma20 > 0:
                    damage_signals += 1
                    logger.debug("P3 damage signal: Price below MA20")
            except (TypeError, ValueError):
                pass

            # Signal 3: Structural Top (Chanlun Sell)
            if isinstance(chan, dict):
                bsp = chan.get("bsp", {})
                if isinstance(bsp, dict):
                    latest = bsp.get("latest", {})
                    if isinstance(latest, dict) and latest.get("side") == "卖":
                        damage_signals += 1
                        logger.debug("P3 damage signal: Chanlun Sell Point")

            # Require 2+ damage signals to wake LLM (not just 1)
            if damage_signals >= 2:
                logger.debug("P3 Interrupt: %d damage signals, waking LLM", damage_signals)
                return True
            elif damage_signals == 1:
                logger.debug("P3 Warning: only 1 damage signal, letting it ride")

            # If no interrupt triggered, let it ride!
            return False

        # If we DO NOT have a position, only wake up on strength
        if v8_grade in ("S", "A", "B"):
            return True
        change_pct = abs(adapted.get("price", {}).get("change_pct", 0))
        if change_pct > threshold:
            return True

        # Check for signal changes
        if rolling.get("signal_changes"):
            return True

        # Check for entry triggers
        chan = adapted.get("chan", {})
        if chan.get("last_bsp") not in ("none", None, "unknown"):
            return True

        # VCP / compression trigger - wake up LLM on quiet pre-breakout days
        comp = adapted.get("compression", {})
        try:
            comp_score = int(comp.get("compression_score") or 0)
        except (TypeError, ValueError):
            comp_score = 0

        if comp.get("is_ready") or (
            comp_score >= 4
            and (comp.get("is_bb_squeeze") or comp.get("is_range_compressed"))
        ):
            return True

        # Early-bird trigger: volume spike after quiet period suggests potential launch
        vol_ratio = adapted.get("volume", {}).get("vol_ratio")
        try:
            vol_ratio_val = (
                float(vol_ratio)
                if vol_ratio not in (None, "N/A", "", "unknown")
                else 0.0
            )
        except (TypeError, ValueError):
            vol_ratio_val = 0.0

        adx_val_raw = adapted.get("indicators", {}).get("adx")
        try:
            adx_val = (
                float(adx_val_raw)
                if adx_val_raw not in (None, "N/A", "", "unknown", 0)
                else 0.0
            )
        except (TypeError, ValueError):
            adx_val = 0.0

        # Volume breakout from quiet: sudden 1.5x volume spike
        if vol_ratio_val >= 1.5:
            logger.debug("Early-bird trigger: volume spike %.1fx", vol_ratio_val)
            return True

        # ADX inflection: trend starting to form (crossed above 20)
        prev_adx = rolling.get("prev_adx")
        try:
            prev_adx_val = (
                float(prev_adx)
                if prev_adx not in (None, "N/A", "", "unknown")
                else 0.0
            )
        except (TypeError, ValueError):
            prev_adx_val = 0.0
        if adx_val > 20 and prev_adx_val <= 20 and prev_adx_val > 0:
            logger.debug(
                "Early-bird trigger: ADX crossed above 20 (%.1f -> %.1f)",
                prev_adx_val,
                adx_val,
            )
            return True

        return False

    def _build_regret_context(self) -> str:
        """Summarize recent ghost trade regrets for LLM context."""
        report = self.ghost_tracker.get_report()
        if not report:
            return ""

        # Only show completed ghost trades with significant regret.
        # GhostTrade exposes MFE/MAE/regret_score, not pnl_pct.
        high_regret = [
            t for t in report if t.get("mfe_pct", 0) > 15 and t.get("regret_score", 0) > 10
        ]  # Missed >15% upside

        if not high_regret:
            return ""

        recent = sorted(high_regret, key=lambda x: x.get("fork_date", ""))[
            -3:
        ]  # Last 3

        lines = ["## ⚠️ Regret Report (Ghost Portfolio)"]
        lines.append("These are positions you exited that continued to rally:\n")

        for t in recent:
            lines.append(
                f"- Exited on {t.get('fork_date')}: stock had MFE **+{t.get('mfe_pct', 0):.1f}%** "
                f"after exit (MAE {t.get('mae_pct', 0):+.1f}%, regret {t.get('regret_score', 0):+.1f})"
            )

        lines.append(
            "\nDid you violate any Iron Rules? If your exit was disciplined, this regret is acceptable."
        )
        lines.append(
            "If you dumped because of fear or premature profit-taking, learn from this.\n"
        )
        return "\n".join(lines)

    def _call_llm_with_raw(
        self,
        date: str,
        adapted: dict,
        rolling: dict,
        trade_idx: int = 0,
    ) -> tuple:
        """Wrapper around _call_llm that also returns raw LLM output for JSONL journal.
        
        Returns:
            (decision_dict, raw_output_str_or_None, parse_ok_bool_or_None)
        """
        # Build the prompt (same as _call_llm) to capture raw output separately
        try:
            portfolio_state = self.sim.get_state()
            prompt = build_daily_prompt(
                date=date,
                today_snapshot=adapted,
                portfolio_state=portfolio_state,
                thesis_state=self.thesis_state,
                structural_memory=self.structural_memory,
                rolling_digest=rolling,
                event_memory=self.event_memory,
                wakeup_context=self._wakeup_reason
                if getattr(self, "_watchpoint_wake", False)
                else "",
            )

            journal_memories = self.journal_rag.retrieve_similar_journals(
                adapted, top_k=3, before_date=date,
                symbol=self.symbol, run_id=self.run_id,
            )
            if journal_memories:
                prompt += "\n\n" + self.journal_rag.format_for_prompt(journal_memories)

            if self._day_pattern_recall_bundle is None:
                self._prepare_pattern_recall_for_day(date, trade_idx)
            pattern_block = self._pattern_recall_prompt_block()
            if pattern_block:
                prompt += "\n\n" + pattern_block

            # P1: DISABLED — Oracle identified _build_regret_context as FOMO poison.
            # 88.3% of LLM journals contained FOMO keywords traced to this injection.
            # Regret data is now restricted to post-market review only.
            # regret_context = self._build_regret_context()
            # if regret_context:
            #     prompt += "\n\n" + regret_context

            try:
                resonance = self.sector_resonance.compute_resonance(
                    target_symbol=self.symbol, all_snapshots={},
                )
                resonance_context = self.sector_resonance.format_for_prompt(resonance)
                if resonance_context:
                    prompt += "\n\n" + resonance_context
            except Exception:
                pass

            raw_response = self.llm.generate(SYSTEM_PROMPT, prompt, json_mode=True)
            decision = parse_llm_decision(raw_response)

            if decision is None:
                logger.warning("Failed to parse LLM decision on %s", date)
                fallback = self._safe_fallback_decision("parse error", "LLM_PARSE_FAILED")
                return (fallback, raw_response, False)

            return (decision, raw_response, True)

        except Exception as e:
            logger.error("Exception in _call_llm_with_raw on %s: %s", date, e)
            fallback = self._safe_fallback_decision(str(e)[:100], "LLM_EXCEPTION")
            return (fallback, None, None)

    def _safe_fallback_decision(self, reason: str, risk_flag: str) -> dict:
        """Return a safe fallback decision."""
        return {
            "action": "HOLD" if self.sim.shares > 0 else "WAIT",
            "conviction": "SKIP",
            "target_position_pct": 0.0,
            "confidence": 0.0,
            "reason_codes": [risk_flag],
            "thesis_update": {},
            "risk_flags": [risk_flag],
            "brief_rationale": f"LLM error: {reason}",
        }

    def _call_llm(
        self,
        date: str,
        adapted: dict,
        rolling: dict,
        trade_idx: int = 0,
    ) -> dict:
        """Call LLM for decision.

        Exception fence: on any error (SQLite, LLM API, parse), return a safe
        WAIT/HOLD decision instead of crashing the backtest.
        """

        # Safe fallback decision
        def safe_fallback(reason: str, risk_flag: str = "LLM_ERROR") -> dict:
            default_action = "HOLD" if self.sim.shares > 0 else "WAIT"
            return {
                "action": default_action,
                "conviction": "SKIP",
                "target_position_pct": 0.0
                if default_action == "WAIT"
                else (
                    (self.sim.shares * adapted.get("price", {}).get("close", 0))
                    / (
                        self.sim.cash
                        + self.sim.shares * adapted.get("price", {}).get("close", 0)
                    )
                    if self.sim.shares > 0
                    and adapted.get("price", {}).get("close", 0) > 0
                    else 0.0
                ),
                "confidence": 0.0,
                "reason_codes": ["LLM_EXCEPTION"],
                "thesis_update": {},
                "risk_flags": [risk_flag],
                "brief_rationale": f"LLM error: {reason}",
            }

        try:
            portfolio_state = self.sim.get_state()

            prompt = build_daily_prompt(
                date=date,
                today_snapshot=adapted,
                portfolio_state=portfolio_state,
                thesis_state=self.thesis_state,
                structural_memory=self.structural_memory,
                rolling_digest=rolling,
                event_memory=self.event_memory,
                wakeup_context=self._wakeup_reason
                if getattr(self, "_watchpoint_wake", False)
                else "",
            )

            # V5.2: Inject outcome-validated case memory from this run
            journal_memories = self.journal_rag.retrieve_similar_journals(
                adapted,
                top_k=3,
                before_date=date,
                symbol=self.symbol,
                run_id=self.run_id,
            )
            if journal_memories:
                prompt += "\n\n" + self.journal_rag.format_for_prompt(journal_memories)

            if self._day_pattern_recall_bundle is None:
                self._prepare_pattern_recall_for_day(date, trade_idx)
            pattern_block = self._pattern_recall_prompt_block()
            if pattern_block:
                prompt += "\n\n" + pattern_block

            # FOMO/regret injection is disabled in both LLM call paths. Journal
            # RAG above is outcome-validated; regret-context wording was shown
            # to bias the manager toward fast re-entry.

            # V5: Inject sector resonance context (peer confirmation)
            # Note: Currently no-op when peers aren't available (single-stock backtest)
            # This is a placeholder for future multi-stock sector analysis
            try:
                resonance = self.sector_resonance.compute_resonance(
                    target_symbol=self.symbol,
                    all_snapshots={},  # Empty for single-stock backtest
                )
                resonance_context = self.sector_resonance.format_for_prompt(resonance)
                if resonance_context:
                    prompt += "\n\n" + resonance_context
            except Exception as e:
                logger.debug("Sector resonance skipped: %s", e)

            response = self.llm.generate(SYSTEM_PROMPT, prompt, json_mode=True)

            decision = parse_llm_decision(response)

            if decision is None:
                logger.warning("Failed to parse LLM decision on %s", date)
                return safe_fallback("parse error", "LLM_PARSE_FAILED")

            return decision

        except sqlite3.Error as e:
            logger.error("SQLite error in _call_llm on %s: %s", date, e)
            return safe_fallback("database error", "SQLITE_EXCEPTION")
        except Exception as e:
            logger.error("Exception in _call_llm on %s: %s", date, e)
            return safe_fallback(str(e)[:100], "LLM_EXCEPTION")

    def _update_memory(self, decision: dict, adapted: dict, date: str):
        """Update thesis and structural memory based on decision."""
        # Update thesis from decision
        thesis_update = decision.get("thesis_update", {})
        if thesis_update:
            self.thesis_state.update(thesis_update)

        # Update structural memory
        chan = adapted.get("chan", {})
        current_zs_ladder = chan.get("zs_stack_direction")
        current_bsp = chan.get("last_bsp")

        if current_zs_ladder and current_zs_ladder != "unknown":
            if self.structural_memory["last_zs_ladder"] != current_zs_ladder:
                self.structural_memory["last_zs_ladder"] = current_zs_ladder
                self.structural_memory["trend_start_date"] = date

        if current_bsp and current_bsp != "none":
            self.structural_memory["last_bsp_type"] = current_bsp

        # Track high water mark
        price = adapted.get("price", {}).get("close", 0)
        if (
            self.structural_memory["high_water_mark"] is None
            or price > self.structural_memory["high_water_mark"]
        ):
            self.structural_memory["high_water_mark"] = price

    def _compress_event_memory(self) -> None:
        """Compact old execution events into one rolling summary boundary."""
        if len(self.event_memory) <= 5:
            return

        compact_summary = self._compact_event_memory()
        recent = list(self.event_memory)[-5:]
        self.event_memory.clear()
        self.event_memory.append(
            {
                "date": recent[0].get("date") if recent else "",
                "type": "compact_boundary",
                "summary": compact_summary,
                "event": compact_summary,
            }
        )
        self.event_memory.extend(recent)

    def _compact_event_memory(self) -> str:
        """Summarize older execution events without another LLM call."""
        entries = list(self.event_memory)
        prior_summary = ""
        action_counts = Counter()
        prices: list[float] = []
        dates: list[str] = []

        for entry in entries:
            if entry.get("type") == "compact_boundary":
                prior_summary = str(entry.get("summary") or entry.get("event") or "")[:180]
                continue

            action = str(entry.get("action") or "").upper()
            if not action:
                event_text = str(entry.get("event") or "").strip()
                action = event_text.split(" ", 1)[0].upper() if event_text else "EVENT"
            action_counts[action] += 1

            try:
                price = float(entry.get("price"))
            except (TypeError, ValueError):
                price = None
            if price is not None and price > 0:
                prices.append(price)

            date = str(entry.get("date") or "").strip()
            if date:
                dates.append(date)

        summary_parts = []
        if prior_summary:
            summary_parts.append(f"Earlier compressed context: {prior_summary}")

        if dates:
            summary_parts.append(f"Window {dates[0]} -> {dates[-1]}")

        if action_counts:
            summary_parts.append(
                "Trades: " + ", ".join(
                    f"{action} x{count}" for action, count in sorted(action_counts.items())
                )
            )

        if prices:
            summary_parts.append(
                "Execution range "
                f"{min(prices):.2f} -> {max(prices):.2f}"
            )

        if not summary_parts:
            return "Earlier trade events compacted."
        return " | ".join(summary_parts)


def _build_basic_snapshot(bars: list[dict]) -> dict:
    """Fallback when pre-computed snapshots are missing.

    Computes core indicators (RSI, MACD, ADX, ATR, Bollinger) via talib
    so LLM decisions still have meaningful data. Also attempts warpcore
    chan theory if available.

    WARNING: This is still a degraded path — fewer modules than the full
    snapshot_factory pipeline. Pre-generate via
    ``snapshot_factory.generate_snapshots()`` for full fidelity.
    """
    logger.warning(
        "Using degraded snapshot fallback (no pre-computed snapshot). "
        "Pre-generate via snapshot_factory.generate_snapshots() for full fidelity."
    )
    if not bars or len(bars) < 2:
        return {
            "price": {"close": 0, "change_pct": 0},
            "error": "Insufficient bars",
            "_degraded": True,
        }

    current = bars[-1]
    close_val = current.get("close", 0)
    prev_close = bars[-2].get("close", close_val)
    change_pct = ((close_val / prev_close) - 1) * 100 if prev_close > 0 else 0.0
    highs = [b.get("high", 0) for b in bars]
    lows = [b.get("low", 0) for b in bars]
    closes = [b.get("close", 0) for b in bars]
    volumes = [b.get("volume", 0) for b in bars]

    indicators = {}
    momentum = {}
    volume_info = {}

    # Compute talib indicators if enough data
    try:
        import numpy as np
        import talib

        close_arr = np.array(closes, dtype=float)
        high_arr = np.array(highs, dtype=float)
        low_arr = np.array(lows, dtype=float)
        vol_arr = np.array(volumes, dtype=float)

        n = len(close_arr)

        # RSI
        if n >= 15:
            rsi_val = talib.RSI(close_arr, 14)[-1]
            if np.isfinite(rsi_val):
                indicators["rsi"] = round(float(rsi_val), 1)

        # MACD
        if n >= 35:
            macd_line, macd_signal, macd_hist = talib.MACD(close_arr, 12, 26, 9)
            ml, ms, mh = (
                float(macd_line[-1]),
                float(macd_signal[-1]),
                float(macd_hist[-1]),
            )
            if np.isfinite(ml):
                indicators["macd_line"] = round(ml, 4)
                indicators["macd_signal"] = round(ms, 4)
                indicators["macd_hist"] = round(mh, 4)
                if mh > 0 and ml > ms:
                    indicators["macd_state"] = "bullish"
                elif mh < 0 and ml < ms:
                    indicators["macd_state"] = "bearish"
                else:
                    indicators["macd_state"] = "neutral"

        # ADX
        if n >= 28:
            adx_val = talib.ADX(high_arr, low_arr, close_arr, 14)[-1]
            plus_di = talib.PLUS_DI(high_arr, low_arr, close_arr, 14)[-1]
            minus_di = talib.MINUS_DI(high_arr, low_arr, close_arr, 14)[-1]
            if np.isfinite(adx_val):
                indicators["adx"] = round(float(adx_val), 1)
            if np.isfinite(plus_di) and np.isfinite(minus_di):
                momentum["di_bull"] = round(float(plus_di), 1)
                momentum["di_bear"] = round(float(minus_di), 1)
                if adx_val > 25:
                    if plus_di > minus_di:
                        momentum["trend_mode"] = (
                            "acceleration" if adx_val > 35 else "trending"
                        )
                    else:
                        momentum["trend_mode"] = "decline"
                else:
                    momentum["trend_mode"] = "range"

        # ATR
        if n >= 15:
            atr_val = talib.ATR(high_arr, low_arr, close_arr, 14)[-1]
            if np.isfinite(atr_val):
                indicators["atr_14"] = round(float(atr_val), 2)
                if close_val > 0:
                    indicators["atr_pct"] = round(float(atr_val / close_val * 100), 2)

        # Bollinger Bands
        if n >= 21:
            bb_upper, bb_mid, bb_lower = talib.BBANDS(close_arr, 20, 2, 2)
            bbu, bbl = float(bb_upper[-1]), float(bb_lower[-1])
            if np.isfinite(bbu) and bbu > bbl:
                bb_pos = (close_val - bbl) / (bbu - bbl)
                indicators["bollinger_pos"] = round(bb_pos, 2)

        # Volume state (simple)
        if n >= 21:
            vol_ma20 = talib.SMA(vol_arr, 20)[-1]
            if np.isfinite(vol_ma20) and vol_ma20 > 0:
                vol_ratio = float(vol_arr[-1]) / float(vol_ma20)
                if vol_ratio > 2.0:
                    volume_info["vol_state"] = "heavy"
                elif vol_ratio > 1.3:
                    volume_info["vol_state"] = "above_avg"
                elif vol_ratio < 0.5:
                    volume_info["vol_state"] = "dried_up"
                else:
                    volume_info["vol_state"] = "normal"
                volume_info["vol_ratio"] = round(vol_ratio, 2)

    except Exception as e:
        logger.debug("talib indicators in fallback failed: %s", e)

    # Attempt chan theory via warpcore
    chan = {}
    try:
        import warpcore

        if hasattr(warpcore, "compute_all_features_rs"):
            dates = [b.get("local_date", b.get("date", "")) for b in bars]
            rust_features = warpcore.compute_all_features_rs(
                highs,
                lows,
                closes,
                volumes,
                close_val,
                [str(d)[:10] for d in dates] if dates else None,
            )
            rust_features = dict(rust_features)
            if "chan" in rust_features:
                chan = dict(rust_features["chan"])
    except Exception as e:
        logger.debug("warpcore chan in fallback failed: %s", e)

    return {
        "price": {
            "close": close_val,
            "change_pct": round(change_pct, 2),
            "high_250d": max(highs[-250:]) if len(highs) >= 250 else max(highs),
            "low_250d": min(lows[-250:]) if len(lows) >= 250 else min(lows),
        },
        "indicators": indicators,
        "chan": chan,
        "volume": volume_info,
        "momentum": momentum,
        "crash": {},
        "wave": {},
        "_degraded": True,
    }
