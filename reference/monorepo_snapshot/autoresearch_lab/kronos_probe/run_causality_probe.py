"""Kronos Causality Probe CLI.

Calculates high-dimensional time-slice pattern similarity, temporal drift,
and micro-macro structural divergence using the pre-trained Kronos model.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

# Resolve project path dynamically
_SELF_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SELF_DIR.parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Setup logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("kronos_probe")


def get_cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
    """Compute the cosine similarity between two 1D vectors."""
    dot = np.dot(v1, v2)
    norm = np.linalg.norm(v1) * np.linalg.norm(v2)
    return float(dot / (norm + 1e-9))


def find_bar_index_by_time(df, target_date: str, target_time: str | None = None) -> int | None:
    """Find the index of the bar matching target_date and optionally target_time."""
    df_copy = df.copy()
    df_copy["date_str"] = df_copy["date"].astype(str)

    if target_time:
        query = f"{target_date} {target_time}"
        matches = df_copy[df_copy["date_str"].str.contains(query)]
        if not matches.empty:
            return int(matches.index[-1])

        date_matches = df_copy[df_copy["date_str"].str.startswith(target_date)]
        if not date_matches.empty:
            for idx in date_matches.index:
                if target_time in df_copy.loc[idx, "date_str"]:
                    return int(idx)
            return int(date_matches.index[-1])
    else:
        matches = df_copy[df_copy["date_str"].str.startswith(target_date)]
        if not matches.empty:
            return int(matches.index[-1])

    return None


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    """Execute the causality validation pipeline."""
    # Step 1. Mirror setup
    if args.hf_mirror:
        os.environ["HF_ENDPOINT"] = args.hf_mirror
        logger.info("Setting HF_ENDPOINT = %s", args.hf_mirror)

    # Step 2. Prime cache if requested and on local workspace
    if args.prime:
        logger.info("Priming live caches via hapi-edge cli...")
        import subprocess
        for sym in args.symbols:
            for p in ["15m", "60m", "day"]:
                cmd = ["./hapi-edge", "cli", "kline", sym, "--period", p, "--count", "500"]
                try:
                    subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=str(_PROJECT_ROOT))
                    logger.info("SUCCESS: Primed %s %s", sym, p)
                except Exception as e:
                    logger.warning("FAILED to prime %s %s: %s", sym, p, e)
                time.sleep(0.05)
        time.sleep(0.5)

    # Step 3. Import heavy packages dynamically
    from engine.v8.infra.radar import radar
    from autoresearch_lab.kronos.extractor import KronosExtractor

    # Step 4. Load K-lines
    logger.info("Loading K-line data for %d symbols...", len(args.symbols))
    data: dict[str, dict[str, Any]] = {sym: {} for sym in args.symbols}
    date_ranges: dict[str, dict[str, str]] = {}
    total_bars_loaded = 0

    for period in ["15min", "day"]:
        for sym in args.symbols:
            # Map period name for radar loading
            rad_p = "15min" if period == "15min" else "day"
            try:
                df = radar.load_kline(sym, period=rad_p, limit=1000)
                if df is not None and not df.empty:
                    data[sym][period] = df
                    total_bars_loaded += len(df)
                    if sym not in date_ranges:
                        date_ranges[sym] = {}
                    date_ranges[sym][period] = f"{df['date'].iloc[0]} to {df['date'].iloc[-1]}"
                else:
                    logger.error("No K-line data loaded for %s (%s)", sym, period)
            except Exception as e:
                logger.error("Error loading %s %s: %s", sym, period, e)

    # Check for complete dataset before proceeding
    missing = []
    for sym in args.symbols:
        for period in ["15min", "day"]:
            if period not in data[sym] or data[sym][period].empty:
                missing.append(f"{sym} {period}")
    if missing:
        logger.error("Aborting probe! Missing K-line series: %s", missing)
        sys.exit(1)

    # Step 5. Instantiate Extractor
    logger.info("Loading KronosExtractor model='%s' on device='%s'...", args.model, args.device)
    extractor = KronosExtractor(model_name=args.model, device=args.device)

    if extractor._model is None:
        logger.error("KronosExtractor failed to initialize.")
        sys.exit(1)

    # Step 6. Extract time-slice embeddings
    embeddings: dict[str, dict[str, np.ndarray]] = {
        "Peak_15m": {},
        "Entry_Day": {},
        "Reaction_Day": {},
        "Exit_Day": {},
    }

    # Slice target timestamps
    t_date = "2026-05-28"
    t_time = "10:00"
    t_reaction = "2026-05-29"
    t_exit = "2026-06-01"

    # Peak 15m Embeddings (Length: 128 bars)
    for sym in args.symbols:
        df = data[sym]["15min"]
        idx = find_bar_index_by_time(df, t_date, t_time)
        if idx is not None:
            window = df.iloc[: idx + 1].tail(128)
            emb = extractor.embed_dataframe(window, label=f"{sym}_peak_15m")
            if emb is not None:
                embeddings["Peak_15m"][sym] = emb

    # Day Embeddings (Length: 256 bars)
    for sym in args.symbols:
        df = data[sym]["day"]
        # Entry
        idx_entry = find_bar_index_by_time(df, t_date)
        if idx_entry is not None:
            window = df.iloc[: idx_entry + 1].tail(256)
            emb = extractor.embed_dataframe(window, label=f"{sym}_entry_day")
            if emb is not None:
                embeddings["Entry_Day"][sym] = emb

        # Reaction
        idx_reaction = find_bar_index_by_time(df, t_reaction)
        if idx_reaction is not None:
            window = df.iloc[: idx_reaction + 1].tail(256)
            emb = extractor.embed_dataframe(window, label=f"{sym}_reaction_day")
            if emb is not None:
                embeddings["Reaction_Day"][sym] = emb

        # Exit
        idx_exit = find_bar_index_by_time(df, t_exit)
        if idx_exit is not None:
            window = df.iloc[: idx_exit + 1].tail(256)
            emb = extractor.embed_dataframe(window, label=f"{sym}_exit_day")
            if emb is not None:
                embeddings["Exit_Day"][sym] = emb

    # Step 7. Compute high-fidelity matrices
    # Cross-sectional 15m similarity
    mat_15m = {}
    for sym1 in args.symbols:
        mat_15m[sym1] = {}
        for sym2 in args.symbols:
            if sym1 in embeddings["Peak_15m"] and sym2 in embeddings["Peak_15m"]:
                sim = get_cosine_similarity(embeddings["Peak_15m"][sym1], embeddings["Peak_15m"][sym2])
                mat_15m[sym1][sym2] = round(sim, 4)

    # Cross-sectional daily entry similarity
    mat_day = {}
    for sym1 in args.symbols:
        mat_day[sym1] = {}
        for sym2 in args.symbols:
            if sym1 in embeddings["Entry_Day"] and sym2 in embeddings["Entry_Day"]:
                sim = get_cosine_similarity(embeddings["Entry_Day"][sym1], embeddings["Entry_Day"][sym2])
                mat_day[sym1][sym2] = round(sim, 4)

    # Transition Drift Similarity
    transition_drift = {}
    for sym in args.symbols:
        if (
            sym in embeddings["Entry_Day"]
            and sym in embeddings["Reaction_Day"]
            and sym in embeddings["Exit_Day"]
        ):
            sim_e_r = get_cosine_similarity(embeddings["Entry_Day"][sym], embeddings["Reaction_Day"][sym])
            sim_r_ex = get_cosine_similarity(embeddings["Reaction_Day"][sym], embeddings["Exit_Day"][sym])
            sim_e_ex = get_cosine_similarity(embeddings["Entry_Day"][sym], embeddings["Exit_Day"][sym])
            transition_drift[sym] = {
                "Entry_vs_Reaction": round(sim_e_r, 4),
                "Reaction_vs_Exit": round(sim_r_ex, 4),
                "Entry_vs_Exit": round(sim_e_ex, 4),
            }

    # Micro-Macro Divergence Index
    # Highlight divergences where daily and 15m charts present conflicting stories
    micro_macro_div = {}
    for sym1 in args.symbols:
        micro_macro_div[sym1] = {}
        for sym2 in args.symbols:
            if sym1 in mat_day and sym2 in mat_day[sym1] and sym1 in mat_15m and sym2 in mat_15m[sym1]:
                # Divergence is absolute delta between macro trend (day) and micro execution (15m)
                divergence = mat_day[sym1][sym2] - mat_15m[sym1][sym2]
                micro_macro_div[sym1][sym2] = round(divergence, 4)

    # Step 8. Construct auditing schema payload (PR 3)
    probe_output = {
        "title": "Kronos Time-Slice Vector Causality Experiment Report",
        "description": "High-fidelity causality probe of the 800k RMB trading incident.",
        "calibration_status": "insufficient_calibration",
        "metadata": {
            "load_mode": extractor.load_mode,
            "load_error": extractor.load_error,
            "embedding_dim": extractor.embedding_dim,
            "device": extractor.device,
            "model_repo": extractor.model_repo,
            "tokenizer_repo": extractor.tokenizer_repo,
            "feature_cols": extractor.feature_cols,
            "preprocess_mode": extractor.preprocess_mode,
        },
        "data_metadata": {
            "symbols": args.symbols,
            "date_range": date_ranges,
            "total_bars_loaded": total_bars_loaded,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "cross_sectional_similarity": {
            "peak_15m_similarity": mat_15m,
            "entry_day_similarity": mat_day,
        },
        "transition_similarity": transition_drift,
        "micro_macro_divergence": micro_macro_div,
    }

    # Step 9. Write outputs
    out_path = Path(args.output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(probe_output, f, indent=2, ensure_ascii=False)

    logger.info("SUCCESS: Saved causality experiment report to: %s", out_path)
    return probe_output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Kronos Causality Probe")
    parser.add_argument(
        "--workspace-dir",
        type=str,
        default=str(_PROJECT_ROOT),
        help="Workspace root path containing config and database files.",
    )
    parser.add_argument(
        "--output-path",
        type=str,
        default=str(_PROJECT_ROOT / "data" / "results" / "kronos_causality_experiment_results_base.json"),
        help="Target output file path for results JSON.",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["688521.SH", "688256.SH", "300502.SZ", "601138.SH"],
        help="Symbol tickers to evaluate.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="kronos-base",
        help="Pre-trained Kronos model identifier.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="auto",
        help="PyTorch device selector ('cpu', 'cuda', 'mps', 'auto').",
    )
    parser.add_argument(
        "--hf-mirror",
        type=str,
        default="https://hf-mirror.com",
        help="Custom Hugging Face mirror endpoint url.",
    )
    parser.add_argument(
        "--prime",
        action="store_true",
        help="Force prime live SQLite caches using local Go gateway cli.",
    )

    parsed_args = parser.parse_args()
    run_probe(parsed_args)
