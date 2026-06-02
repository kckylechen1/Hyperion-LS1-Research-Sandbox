"""Kronos probe schema tests (reference mirror; needs numpy + private deps)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("numpy", reason="kronos probe tests need numpy in CI")
pytest.importorskip("pandas", reason="kronos probe tests need pandas in CI")


def _full_monorepo_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("engine.v8.infra") is not None


pytestmark = pytest.mark.skipif(
    not _full_monorepo_available(),
    reason="engine.v8.infra not vendored in public sandbox (mirror-only review)",
)

from autoresearch_lab.kronos_probe.run_causality_probe import run_probe  # noqa: E402


class NamespaceStub:
    """Argparse Namespace stub."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


@pytest.fixture
def mock_dependencies():
    """Mock database and deep learning dependencies to ensure fast, isolated tests."""
    with patch("engine.v8.infra.radar.radar.load_kline") as mock_kline, patch(
        "autoresearch_lab.kronos.extractor.KronosExtractor"
    ) as mock_extractor_class:

        # Mock K-line DataFrame loading
        import pandas as pd

        mock_df_15m = pd.DataFrame(
            {
                "date": pd.date_range(start="2026-05-28 09:30", periods=200, freq="15min"),
                "open": [10.0] * 200,
                "high": [11.0] * 200,
                "low": [9.0] * 200,
                "close": [10.5] * 200,
                "volume": [1000] * 200,
                "turnover": [10500.0] * 200,
            }
        )

        mock_df_day = pd.DataFrame(
            {
                "date": pd.date_range(start="2026-05-01", periods=50, freq="D"),
                "open": [10.0] * 50,
                "high": [11.0] * 50,
                "low": [9.0] * 50,
                "close": [10.5] * 50,
                "volume": [5000] * 50,
                "turnover": [52500.0] * 50,
            }
        )

        # Handle load_kline queries by period
        def load_kline_side_effect(symbol, period, limit):
            if period == "15min":
                return mock_df_15m
            return mock_df_day

        mock_kline.side_effect = load_kline_side_effect

        # Mock Extractor instance
        mock_extractor = MagicMock()
        mock_extractor._model = MagicMock()
        mock_extractor.load_mode = "pytorch_hub"
        mock_extractor.load_error = None
        mock_extractor.embedding_dim = 832
        mock_extractor.device = "cpu"
        mock_extractor.model_repo = "NeoQuasar/Kronos-base"
        mock_extractor.tokenizer_repo = "NeoQuasar/Kronos-Tokenizer-base"
        mock_extractor.feature_cols = ["open", "high", "low", "close", "volume", "turnover"]
        mock_extractor.preprocess_mode = "zscore_norm"

        # Mock embed_dataframe to return a dummy embedding
        mock_extractor.embed_dataframe.return_value = [0.1] * 832

        mock_extractor_class.return_value = mock_extractor

        yield mock_kline, mock_extractor


def test_probe_output_schema_and_safeguards(tmp_path, mock_dependencies):
    """Test that the run_probe function produces correctly structured, validated JSON."""
    out_file = tmp_path / "probe_results.json"

    args = NamespaceStub(
        workspace_dir=str(tmp_path),
        output_path=str(out_file),
        symbols=["688521.SH", "688256.SH"],
        model="kronos-base",
        device="cpu",
        hf_mirror="https://hf-mirror.com",
        prime=False,
    )

    # Run the probe using our mock fixture
    output = run_probe(args)

    # Assert structural keys exist in output dictionary
    assert output["title"] == "Kronos Time-Slice Vector Causality Experiment Report"
    assert output["calibration_status"] == "insufficient_calibration"

    # Verify auditing metadata schema matches PR 3 specification
    meta = output["metadata"]
    assert meta["load_mode"] == "pytorch_hub"
    assert meta["load_error"] is None
    assert meta["embedding_dim"] == 832
    assert meta["device"] == "cpu"
    assert meta["model_repo"] == "NeoQuasar/Kronos-base"
    assert meta["tokenizer_repo"] == "NeoQuasar/Kronos-Tokenizer-base"
    assert meta["feature_cols"] == ["open", "high", "low", "close", "volume", "turnover"]
    assert meta["preprocess_mode"] == "zscore_norm"

    # Verify data properties are captured
    data_meta = output["data_metadata"]
    assert data_meta["symbols"] == ["688521.SH", "688256.SH"]
    assert "timestamp" in data_meta

    # Verify results matrices exist
    sim = output["cross_sectional_similarity"]
    assert "peak_15m_similarity" in sim
    assert "entry_day_similarity" in sim

    # Test 15m and daily similarity matrix dimensions
    assert "688521.SH" in sim["peak_15m_similarity"]
    assert sim["peak_15m_similarity"]["688521.SH"]["688256.SH"] == 1.0  # since both return identical mock vectors

    # Verify transition similarity (drift)
    assert "transition_similarity" in output
    assert "688521.SH" in output["transition_similarity"]
    assert output["transition_similarity"]["688521.SH"]["Entry_vs_Exit"] == 1.0

    # Verify micro-macro divergence
    assert "micro_macro_divergence" in output
    assert "688521.SH" in output["micro_macro_divergence"]
    # Divergence between day (1.0) and 15m (1.0) should be exactly 0
    assert output["micro_macro_divergence"]["688521.SH"]["688256.SH"] == 0.0

    # Ensure JSON file was written and successfully parses
    assert out_file.exists()
    with open(out_file, encoding="utf-8") as f:
        loaded_json = json.load(f)
    assert loaded_json["calibration_status"] == "insufficient_calibration"
