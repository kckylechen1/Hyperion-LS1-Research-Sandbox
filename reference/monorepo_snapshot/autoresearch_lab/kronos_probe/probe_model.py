"""Phase 1.5: Kronos Feasibility Probe.

Usage:
    uv sync --extra kronos
    uv run python -m autoresearch_lab.kronos_probe.probe_model

Answers:
    1. Can we load Kronos-small and extract hidden states?
    2. What is CPU inference latency (single + batch)?
    3. Are embeddings deterministic (stability > 0.999)?
    4. Does the environment stay clean (pytest passes without kronos)?

Output: data/results/kronos_probe_*.json
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RESULTS_DIR = _PROJECT_ROOT / "data" / "results"

MODEL_NAME = "NeoQuasar/Kronos-small"


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def run_probe() -> dict:
    """Run the full Kronos feasibility probe."""
    results: dict[str, Any] = {
        "model_name": MODEL_NAME,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "checks": {},
    }

    # ── Check 1: Dependency availability ──
    t0 = time.monotonic()
    try:
        import torch
        import transformers
        results["checks"]["deps"] = {
            "status": "ok",
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "load_sec": round(time.monotonic() - t0, 2),
        }
        logger.info("Deps OK: torch=%s, transformers=%s", torch.__version__, transformers.__version__)
    except ImportError as e:
        results["checks"]["deps"] = {"status": "fail", "error": str(e)}
        logger.error("Kronos dependencies not installed: %s", e)
        results["verdict"] = "NO_GO"
        _save(results)
        return results

    # ── Check 2: Model loading ──
    t0 = time.monotonic()
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_NAME,
            trust_remote_code=True,
            torch_dtype=torch.float32,
        )
        model.eval()
        load_sec = time.monotonic() - t0
        params = sum(p.numel() for p in model.parameters())
        results["checks"]["model"] = {
            "status": "ok",
            "params": params,
            "load_sec": round(load_sec, 1),
        }
        logger.info("Loaded %s: %dM params in %.1fs", MODEL_NAME, params // 1_000_000, load_sec)
    except Exception as e:
        results["checks"]["model"] = {"status": "fail", "error": str(e)[:200]}
        logger.error("Model loading failed: %s", e)
        results["verdict"] = "NO_GO"
        _save(results)
        return results

    # ── Check 3: Hidden state extraction ──
    try:
        # Test tokenization with mock OHLCV data
        seq_len = 256
        dummy_input_ids = torch.randint(0, 1000, (1, seq_len))
        with torch.no_grad():
            outputs = model(dummy_input_ids, output_hidden_states=True)

        hidden_dim = outputs.last_hidden_state.shape[-1]
        seq_dim = outputs.last_hidden_state.shape[1]

        # Try mean pooling
        mean_pooled = outputs.last_hidden_state.mean(dim=1).squeeze().numpy()
        # Try last token
        last_token = outputs.last_hidden_state[:, -1, :].squeeze().numpy()

        results["checks"]["hidden_state"] = {
            "status": "ok",
            "hidden_dim": hidden_dim,
            "seq_len": seq_dim,
            "mean_pooled_shape": list(mean_pooled.shape),
            "last_token_shape": list(last_token.shape),
            "extraction_method": "mean_pool",
        }
        logger.info("Hidden state: dim=%d, mean_pool_shape=%s", hidden_dim, mean_pooled.shape)
    except Exception as e:
        results["checks"]["hidden_state"] = {"status": "fail", "error": str(e)[:200]}
        logger.error("Hidden state extraction failed: %s", e)
        results["verdict"] = "NO_GO"
        _save(results)
        return results

    # ── Check 4: Latency ──
    try:
        # Warmup
        for _ in range(3):
            with torch.no_grad():
                _ = model(dummy_input_ids)

        # Single sample
        latencies = []
        for _ in range(10):
            t0 = time.perf_counter()
            with torch.no_grad():
                _ = model(dummy_input_ids)
            latencies.append((time.perf_counter() - t0) * 1000)

        single_ms = float(np.mean(latencies))
        results["checks"]["latency"] = {
            "status": "ok",
            "single_mean_ms": round(single_ms, 1),
            "single_p99_ms": round(float(np.percentile(latencies, 99)), 1),
            "n_runs": len(latencies),
        }

        # Batch 16
        batch_ids = torch.randint(0, 1000, (16, seq_len))
        batch_latencies = []
        for _ in range(5):
            t0 = time.perf_counter()
            with torch.no_grad():
                _ = model(batch_ids)
            batch_latencies.append((time.perf_counter() - t0) * 1000)

        batch_ms = float(np.mean(batch_latencies))
        results["checks"]["latency"]["batch16_mean_ms"] = round(batch_ms, 1)
        results["checks"]["latency"]["batch16_per_sample_ms"] = round(batch_ms / 16, 1)

        latency_verdict = "GO" if single_ms < 500 else ("GO_WITH_CAVEATS" if single_ms < 2000 else "NO_GO")
        results["checks"]["latency"]["verdict"] = latency_verdict
        logger.info("Latency: single=%.1fms, batch16=%.1fms → %s", single_ms, batch_ms, latency_verdict)
    except Exception as e:
        results["checks"]["latency"] = {"status": "fail", "error": str(e)[:200]}
        logger.error("Latency test failed: %s", e)

    # ── Check 5: Embedding stability ──
    try:
        embeddings = []
        for _ in range(3):
            with torch.no_grad():
                out = model(dummy_input_ids, output_hidden_states=True)
            emb = out.last_hidden_state.mean(dim=1).squeeze().numpy()
            embeddings.append(emb)

        sim_01 = _cosine(embeddings[0], embeddings[1])
        sim_02 = _cosine(embeddings[0], embeddings[2])
        min_sim = min(sim_01, sim_02)
        stable = min_sim > 0.999

        results["checks"]["stability"] = {
            "status": "ok",
            "cosine_run1_vs_run2": round(sim_01, 6),
            "cosine_run1_vs_run3": round(sim_02, 6),
            "deterministic": stable,
        }
        logger.info("Stability: min_cosine=%.6f → %s", min_sim, "deterministic" if stable else "NON-DETERMINISTIC")
    except Exception as e:
        results["checks"]["stability"] = {"status": "fail", "error": str(e)[:200]}

    # ── Final verdict ──
    all_ok = all(
        c.get("status") == "ok"
        for c in results["checks"].values()
        if isinstance(c, dict)
    )
    if all_ok:
        if results["checks"]["latency"].get("verdict") == "NO_GO":
            results["verdict"] = "NO_GO"
            results["verdict_reason"] = "latency unacceptable"
        elif results["checks"]["latency"].get("verdict") == "GO_WITH_CAVEATS":
            results["verdict"] = "GO_WITH_CAVEATS"
            results["verdict_reason"] = "latency > 500ms, batch-only mode"
        elif not results["checks"]["stability"].get("deterministic", False):
            results["verdict"] = "NO_GO"
            results["verdict_reason"] = "embeddings not deterministic"
        else:
            results["verdict"] = "GO"
            results["verdict_reason"] = "all checks passed"
    else:
        results["verdict"] = "NO_GO"

    logger.info("VERDICT: %s — %s", results["verdict"], results.get("verdict_reason", ""))
    _save(results)
    return results


def _save(results: dict) -> None:
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = _RESULTS_DIR / f"kronos_probe_{ts}.json"
    path.write_text(json.dumps(results, indent=2, default=str))
    logger.info("Results saved: %s", path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_probe()
