"""Direct AutoResearch worker — executes tasks natively without hapi-server dependency.

This module is launched by hapi-edge's Go research runner. It directly imports
and executes AutoResearch modules, writing durable result JSON next to the run log.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")

logger = logging.getLogger(__name__)

# Action handler registry
ACTION_HANDLERS: dict[str, Any] = {}


def register_action(name: str):
    """Decorator to register action handlers."""
    def decorator(func):
        ACTION_HANDLERS[name] = func
        return func
    return decorator


@register_action("evaluate")
def _run_evaluate(params: dict, run_id: str) -> dict:
    """Run prepare.evaluate() with current weights on labeled data."""
    from autoresearch_lab.prepare import evaluate, load_labeled_data, _default_weights
    from autoresearch_lab.fit import WEIGHTS

    days = int(params.get("days", 200))
    horizon = str(params.get("horizon", "T10"))
    chan_every_n = int(params.get("chan_every_n", 1))
    seed = int(params.get("seed", 42))
    min_grade = str(params.get("min_grade", "B"))
    refresh_cache = bool(params.get("refresh_cache", False))
    use_default_weights = bool(params.get("use_default_weights", False))

    logger.info("Loading labeled data (days=%d, horizon=%s)...", days, horizon)
    train_data, oos_data, stats = load_labeled_data(
        days=days,
        chan_every_n=chan_every_n,
        min_grade=min_grade,
        seed=seed,
        use_cache=True,
        refresh_cache=refresh_cache,
    )

    logger.info("Evaluating weights on %d symbols...", len(train_data))
    weights = _default_weights() if use_default_weights else WEIGHTS
    result = evaluate(weights, train_data, horizon=horizon)

    out = {
        "run_id": run_id,
        "action": "evaluate",
        "status": "completed",
        "horizon": horizon,
        "train_symbols": len(train_data),
        "oos_symbols": len(oos_data),
        "dataset_stats": stats,
        "weights_source": "default" if use_default_weights else "fit.py",
    }
    # Prefer to_dict() if available; otherwise build from fields.
    if hasattr(result, "to_dict") and callable(result.to_dict):
        out["result"] = result.to_dict()
    else:
        out["precision_a"] = result.precision_a
        out["coverage_a"] = result.coverage_a
        out["precision_s"] = result.precision_s
        out["total_s"] = result.total_s
        out["total_a"] = result.total_a
        out["rank_ic"] = result.rank_ic
        out["rank_ic_obs"] = result.rank_ic_obs
        out["grade_separation"] = result.grade_separation
        out["left_ic"] = getattr(result, "left_ic", None)
        out["right_ic"] = getattr(result, "right_ic", None)
        out["interaction_ic"] = getattr(result, "interaction_ic", None)
    return out


@register_action("evolve")
def _run_evolve(params: dict, run_id: str) -> dict:
    """Run nightly evolution loop. dry_run defaults to True; real runs require unfreeze=True."""
    from autoresearch_lab.nightly.run_nightly import run_nightly
    from autoresearch_lab.nightly.config import NightlyConfig

    rounds = int(params.get("rounds", 10))
    dry_run = bool(params.get("dry_run", True))
    days = int(params.get("days", 200))
    horizon = str(params.get("horizon", "T10"))
    llm_model = str(params.get("model", "claude"))
    chan_every_n = int(params.get("chan_every_n", 1))
    seed = int(params.get("seed", 42))
    hypotheses = int(params.get("hypotheses", 4))
    refresh_cache = bool(params.get("refresh_cache", False))

    # Safety gate: block real runs unless unfreeze is explicitly True
    if not dry_run and params.get("unfreeze") is not True:
        logger.warning("evolve blocked: dry_run=False requires unfreeze=True")
        return {
            "run_id": run_id,
            "action": "evolve",
            "status": "blocked",
            "error": "dry_run=False requires params.unfreeze=True to proceed",
        }

    logger.info("Starting evolution loop (rounds=%d, dry_run=%s)...", rounds, dry_run)

    cfg = NightlyConfig(
        rounds=rounds,
        days=days,
        horizon=horizon,
        llm_model=llm_model,
        chan_every_n=chan_every_n,
        seed=seed,
        hypotheses_per_round=hypotheses,
        use_cache=True,
        refresh_cache=refresh_cache,
    )

    result = run_nightly(cfg, dry_run=dry_run)

    champion_info = result.get("final_champion", {})
    return {
        "run_id": run_id,
        "action": "evolve",
        "status": "completed",
        "rounds": result.get("total_rounds", rounds),
        "dry_run": dry_run,
        "via": "nightly_runner",
        "total_trials": result.get("total_trials"),
        "accepted": result.get("accepted"),
        "champion_round": champion_info.get("round"),
        "train_precision": champion_info.get("train_prec"),
        "rank_ic": champion_info.get("rank_ic"),
        "coverage": champion_info.get("coverage"),
    }


@register_action("fund_manager")
def _run_fund_manager(params: dict, run_id: str) -> dict:
    """Run fund manager backtest (defaults to DuckDB path)."""
    symbol = params.get("symbol")
    if not symbol:
        raise ValueError("fund_manager requires 'symbol' parameter")

    name = str(params.get("name", ""))
    max_days = params.get("max_days")
    use_duckdb = bool(params.get("use_duckdb", True))
    cash = float(params.get("cash", 1000000.0))

    logger.info("Starting fund manager (symbol=%s, duckdb=%s)...", symbol, use_duckdb)

    if use_duckdb:
        from autoresearch_lab.fund_manager.run_backtest_duckdb import main
    else:
        from autoresearch_lab.fund_manager.run_backtest import main

    # Build sys.argv for the main function
    sys.argv = [
        "fund_manager",
        "--symbol", str(symbol),
        "--name", name,
        "--cash", str(cash),
        "--run-id", run_id,
    ]
    if max_days:
        sys.argv.extend(["--max-days", str(int(max_days))])

    main()

    # Locate and read the result JSON written by main()
    fm_results_dir = _PROJECT_ROOT / "autoresearch_lab" / "fund_manager" / "results"
    if use_duckdb:
        result_path = fm_results_dir / f"{run_id}_duckdb.json"
    else:
        result_path = fm_results_dir / f"{run_id}.json"

    if not result_path.exists():
        raise RuntimeError(
            f"fund_manager result file not found: {result_path}"
        )

    with open(result_path, encoding="utf-8") as f:
        raw_result = json.load(f)

    summary = {
        "run_id": run_id,
        "action": "fund_manager",
        "status": "completed",
        "symbol": symbol,
        "use_duckdb": use_duckdb,
        "result_path": str(result_path),
    }
    # Forward known fields from raw result
    for key in (
        "final_equity", "total_return_pct", "trades", "decision_count",
        "max_drawdown_pct", "sharpe", "win_rate",
    ):
        if key in raw_result:
            summary[key] = raw_result[key]
    summary["raw_result"] = raw_result
    return summary


@register_action("forensics_tag")
def _run_forensics_tag(params: dict, run_id: str) -> dict:
    """Run forensic tagging for a fund manager run."""
    from autoresearch_lab.fund_manager.forensic_tagger import tag_forensics

    target_run_id = params.get("run_id")
    write_report = bool(params.get("write_report", True))

    logger.info("Running forensics_tag (target_run_id=%s)...", target_run_id)

    result = tag_forensics(
        run_id=target_run_id,
        write_report=write_report,
    )

    return {
        "run_id": run_id,
        "action": "forensics_tag",
        "status": "completed",
        "target_run_id": target_run_id,
        "severity": result.get("severity"),
        "tag_counts": result.get("tag_counts", {}),
        "lessons": result.get("lessons", []),
        "recommendation": result.get("recommendation"),
    }


@register_action("promote_lesson")
def _run_promote_lesson(params: dict, run_id: str) -> dict:
    """Promote a forensic tag report into HyperTachi wiki. dry_run defaults to True."""
    from autoresearch_lab.fund_manager.forensic_tagger import promote_lesson

    target_run_id = params.get("run_id")
    dry_run = bool(params.get("dry_run", True))
    title = params.get("title")

    logger.info("Promoting lesson (target_run_id=%s, dry_run=%s)...", target_run_id, dry_run)

    result = promote_lesson(
        run_id=target_run_id,
        title=title,
        dry_run=dry_run,
    )

    return {
        "run_id": run_id,
        "action": "promote_lesson",
        "status": "completed",
        "target_run_id": target_run_id,
        "dry_run": dry_run,
        "promotion_status": result.get("status"),
        "wiki_title": result.get("title"),
        "wiki_path": result.get("path"),
    }


@register_action("pattern")
def _run_pattern(params: dict, run_id: str) -> dict:
    """Run pattern discriminator analysis via direct imports."""
    from autoresearch_lab.prepare import load_labeled_data
    from autoresearch_lab.pattern_discriminator import discriminate_patterns, LLMClient

    horizon = str(params.get("horizon", "T10"))
    samples = int(params.get("sample_size", params.get("samples", 30)))
    days = int(params.get("days", 200))
    chan_every_n = int(params.get("chan_every_n", 1))
    min_grade = str(params.get("min_grade", "B"))
    seed = int(params.get("seed", 42))
    model = str(params.get("model", "claude"))
    include_oos = bool(params.get("include_oos", False))
    include_samples = bool(params.get("include_samples", False))
    refresh_cache = bool(params.get("refresh_cache", False))

    logger.info("Loading labeled data for pattern (days=%d, horizon=%s)...", days, horizon)
    train_data, oos_data, stats = load_labeled_data(
        days=days,
        chan_every_n=chan_every_n,
        min_grade=min_grade,
        seed=seed,
        use_cache=True,
        refresh_cache=refresh_cache,
    )

    # Merge train + oos if requested
    if include_oos and oos_data:
        merged = dict(train_data)
        for sym, snaps in oos_data.items():
            merged.setdefault(sym, []).extend(snaps)
        analysis_data = merged
    else:
        analysis_data = train_data

    logger.info("Running pattern discriminator (horizon=%s, samples=%d)...", horizon, samples)
    client = LLMClient(model=model)
    result = discriminate_patterns(
        labeled_data=analysis_data,
        horizon=horizon,
        sample_size=samples,
        llm_client=client,
        seed=seed,
        include_samples=include_samples,
    )

    result["run_id"] = run_id
    result["action"] = "pattern"
    result["status"] = "completed"
    result["dataset_stats"] = stats
    result["train_symbols"] = len(train_data)
    result["oos_symbols"] = len(oos_data)
    result["horizon"] = horizon
    result["samples"] = samples
    result["include_oos"] = include_oos
    if "error" in result:
        result["status"] = "failed"
    return result


@register_action("pattern_store_build")
def _run_pattern_store_build(params: dict, run_id: str) -> dict:
    """Build pattern memory store: load labeled snapshots, extract features, normalize, insert into DuckDB."""
    from autoresearch_lab.pattern_memory.actions import pattern_store_build

    result = pattern_store_build(params)
    result["run_id"] = run_id
    result["action"] = "pattern_store_build"
    if result.get("status") == "error":
        result["status"] = "failed"
    elif result.get("status") == "ok":
        result["status"] = "completed"
    return result


@register_action("pattern_similarity_eval")
def _run_pattern_similarity_eval(params: dict, run_id: str) -> dict:
    """Evaluate pattern similarity: query top-k, compute metrics, write result JSON."""
    from autoresearch_lab.pattern_memory.actions import pattern_similarity_eval

    result = pattern_similarity_eval(params)
    result["run_id"] = run_id
    result["action"] = "pattern_similarity_eval"
    if result.get("status") == "error":
        result["status"] = "failed"
    elif result.get("status") == "ok":
        result["status"] = "completed"
    return result


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the AutoResearch worker."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Run an AutoResearch action.")
    parser.add_argument("action", choices=sorted(ACTION_HANDLERS.keys()))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--params-json", default="{}")
    args = parser.parse_args(argv)

    try:
        params = json.loads(args.params_json)
        if not isinstance(params, dict):
            raise ValueError("--params-json must decode to an object")
    except json.JSONDecodeError as exc:
        logger.error("--params-json must be valid JSON: %s", exc)
        return 1

    result_path = _result_path(args.run_id)
    started_at = _now()

    try:
        handler = ACTION_HANDLERS[args.action]
        logger.info("Executing action=%s run_id=%s", args.action, args.run_id)
        result = handler(params, args.run_id)

        # If handler returned a blocked status, propagate it.
        handler_status = result.get("status", "completed") if isinstance(result, dict) else "completed"

        payload = {
            "run_id": args.run_id,
            "action": args.action,
            "status": handler_status,
            "started_at": started_at,
            "completed_at": _now(),
            "result": result,
        }
        if handler_status in {"failed", "blocked"} and isinstance(result, dict):
            error = result.get("error")
            if error:
                payload["error"] = str(error)

        _write_json(result_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    except Exception as exc:
        logger.exception("Action %s failed", args.action)
        payload = {
            "run_id": args.run_id,
            "action": args.action,
            "status": "failed",
            "started_at": started_at,
            "completed_at": _now(),
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }

        _write_json(result_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


def _result_path(run_id: str) -> Path:
    """Get the result JSON path for a run."""
    logs_dir = Path(os.getenv("HAPI_RESEARCH_LOG_DIR", _PROJECT_ROOT / "logs" / "research"))
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / f"{run_id}.result.json"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON to a file."""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _now() -> str:
    """Get current time in Shanghai timezone."""
    return datetime.now(SHANGHAI).strftime("%Y-%m-%d %H:%M:%S %Z")


@register_action("kronos_probe")
def _run_kronos_probe(params: dict, run_id: str) -> dict:
    """Run offline Kronos probe metrics (latency, VRAM, rank IC)."""
    try:
        from autoresearch_lab.kronos.probe import run_probe
    except ImportError as exc:
        return {
            "run_id": run_id,
            "action": "kronos_probe",
            "status": "failed",
            "error": f"Missing dependency: {exc}",
        }
    try:
        return run_probe(params, run_id)
    except ImportError as exc:
        return {
            "run_id": run_id,
            "action": "kronos_probe",
            "status": "failed",
            "error": f"Missing dependency: {exc}",
        }
    except Exception as exc:
        return {
            "run_id": run_id,
            "action": "kronos_probe",
            "status": "failed",
            "error": str(exc),
        }


@register_action("kronos_embed")
def _run_kronos_embed(params: dict, run_id: str) -> dict:
    """Batch-embed symbols with Kronos and export JSON snapshots for Go recall."""
    try:
        from autoresearch_lab.kronos.embed import run_embed
    except ImportError as exc:
        return {
            "run_id": run_id,
            "action": "kronos_embed",
            "status": "failed",
            "error": f"Missing dependency: {exc}",
        }
    try:
        return run_embed(params, run_id)
    except ImportError as exc:
        return {
            "run_id": run_id,
            "action": "kronos_embed",
            "status": "failed",
            "error": f"Missing dependency: {exc}",
        }
    except Exception as exc:
        return {
            "run_id": run_id,
            "action": "kronos_embed",
            "status": "failed",
            "error": str(exc),
        }


@register_action("cvrf_discriminate")
def _run_cvrf_discriminate(params: dict, run_id: str) -> dict:
    """Run CVRF multi-agent refinement on pattern discrimination beliefs."""
    try:
        return _run_cvrf_discriminate_impl(params, run_id)
    except Exception as exc:
        return {
            "run_id": run_id,
            "action": "cvrf_discriminate",
            "status": "failed",
            "error": str(exc),
        }


def _run_cvrf_discriminate_impl(params: dict, run_id: str) -> dict:
    """Implementation for CVRF; wrapped so direct handler calls fail gracefully."""
    from autoresearch_lab.prepare import load_labeled_data
    from autoresearch_lab.pattern_discriminator import (
        collect_pattern_samples,
        discriminate_patterns,
    )
    from autoresearch_lab.pattern_discriminator_cvrf import (
        beliefs_from_discriminator,
        run_cvrf_cycle,
    )
    from autoresearch_lab.nightly.llm_client import LLMClient

    horizon = str(params.get("horizon", "T10"))
    days = int(params.get("days", 200))
    chan_every_n = int(params.get("chan_every_n", 1))
    min_grade = str(params.get("min_grade", "B"))
    seed = int(params.get("seed", 42))
    max_rounds = int(params.get("max_rounds", 3))
    min_confidence = float(params.get("min_confidence", 0.3))
    model = str(params.get("model", "claude"))
    sample_size = int(params.get("sample_size", 30))
    refresh_cache = bool(params.get("refresh_cache", False))

    logger.info("Loading labeled data for CVRF (days=%d, horizon=%s)...", days, horizon)
    train_data, oos_data, stats = load_labeled_data(
        days=days,
        chan_every_n=chan_every_n,
        min_grade=min_grade,
        seed=seed,
        use_cache=True,
        refresh_cache=refresh_cache,
    )

    # Split: train for initial discrimination, heldout for CVRF refinement
    all_symbols = sorted(set(train_data.keys()) | set(oos_data.keys()))
    import random
    rng = random.Random(seed)
    rng.shuffle(all_symbols)
    split = max(1, len(all_symbols) * 2 // 3)
    train_symbols = set(all_symbols[:split])
    heldout_symbols = set(all_symbols[split:])

    train_split = {s: train_data[s] for s in train_symbols if s in train_data}
    heldout_split = {s: train_data[s] for s in heldout_symbols if s in train_data}
    for s in heldout_symbols:
        if s in oos_data:
            heldout_split.setdefault(s, []).extend(oos_data[s])

    # Initial discrimination
    client = LLMClient(model=model)
    disc_result = discriminate_patterns(
        train_split,
        horizon=horizon,
        sample_size=sample_size,
        llm_client=client,
        seed=seed,
    )

    if disc_result.get("error"):
        return {
            "run_id": run_id,
            "action": "cvrf_discriminate",
            "status": "failed",
            "error": disc_result["error"],
            "dataset_stats": stats,
        }

    beliefs = beliefs_from_discriminator(disc_result)
    if not beliefs:
        return {
            "run_id": run_id,
            "action": "cvrf_discriminate",
            "status": "completed",
            "initial_beliefs": 0,
            "final_beliefs": 0,
            "rounds": 0,
            "dataset_stats": stats,
        }

    # Prepare heldout samples
    heldout_samples = []
    grouped = collect_pattern_samples(heldout_split, horizon=horizon, masked=True)
    for label in ("true_S", "stale_S"):
        for sample in grouped.get(label, []):
            sample.setdefault("outcome", {})["label"] = label
            heldout_samples.append(sample)

    # Run CVRF cycle
    session = run_cvrf_cycle(
        beliefs=beliefs,
        train_samples=[],
        heldout_samples=heldout_samples,
        llm_client=client,
        max_rounds=max_rounds,
        min_confidence=min_confidence,
    )

    return {
        "run_id": run_id,
        "action": "cvrf_discriminate",
        "status": "completed",
        "initial_beliefs": len(beliefs),
        "final_beliefs": len(session.updated_beliefs),
        "rounds": session.rounds_completed,
        "retired": len(beliefs) - len(session.updated_beliefs),
        "beliefs": [
            {
                "id": b.belief_id,
                "text": b.text,
                "confidence": b.confidence,
                "generation": b.generation,
                "conditions": b.conditions,
            }
            for b in session.updated_beliefs
        ],
        "dataset_stats": stats,
        "train_symbols": len(train_split),
        "heldout_symbols": len(heldout_split),
    }


if __name__ == "__main__":
    raise SystemExit(main())
