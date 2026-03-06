"""Safety/unit tests for scripts/benchmarks/bench_reference_pipeline.py."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "benchmarks"
        / "bench_reference_pipeline.py"
    )
    spec = importlib.util.spec_from_file_location("bench_reference_pipeline", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runner_aborts_when_db_path_is_m_drive() -> None:
    mod = _load_module()
    rc = mod.run(
        [
            "extract_terms",
            "--db-path",
            r"M:\V_book\HDLE_Processing\hewiki_gpu_processing.db",
            "--copy-target",
            "--source-db",
            r"J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db",
        ]
    )
    assert rc == 1


def test_artifact_name_timestamp_is_deterministic(monkeypatch, tmp_path: Path) -> None:
    mod = _load_module()
    fixed = datetime(2026, 3, 6, 12, 34, 56, tzinfo=timezone.utc)
    monkeypatch.setattr(mod, "_utc_now", lambda: fixed)

    paths = mod.build_artifact_file_paths(tmp_path)
    assert paths["metrics_json"].name == "pipeline_bench_metrics_20260306_123456.json"
    assert paths["report_md"].name == "pipeline_bench_report_20260306_123456.md"
    assert paths["latest_log"].name == "pipeline_bench_latest.log"


def test_doc_slice_ordering_is_stable() -> None:
    mod = _load_module()
    sliced = mod.deterministic_slice_doc_ids([9, 1, 7, 1, 5, 3], 4)
    assert sliced == [1, 3, 5, 7]
