"""Unit tests for scripts/check_perf_correctness_harness.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "check_perf_correctness_harness.py"
    spec = importlib.util.spec_from_file_location("check_perf_correctness_harness", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_artifact(
    path: Path,
    *,
    stage_name: str,
    rows: dict[str, int],
    details: dict | None = None,
    errors_count: int = 0,
    overall_status: str = "pass",
    stage_status: str = "ok",
) -> None:
    payload = {
        "scenario": stage_name,
        "overall_status": overall_status,
        "config": {"overwrite": 1},
        "db": {
            "source_db": r"J:\Project_Vibe\V_book\ref_corpora\safe.db",
            "base_sandbox_db": r"J:\Project_Vibe\V_book\build\bench\safe.db",
            "working_db": r"J:\Project_Vibe\V_book\build\tmp\safe_work.db",
        },
        "stages": [
            {
                "name": stage_name,
                "duration_sec": 1.0,
                "rows_processed": rows,
                "overwrite": 1,
                "errors_count": errors_count,
                "error_samples": [],
                "details": details or {},
                "status": stage_status,
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _seed_pass_set(tmp_path: Path, token: str) -> tuple[Path, Path, Path]:
    extract = tmp_path / f"pipeline_bench_metrics_{token}1.json"
    niqqud = tmp_path / f"pipeline_bench_metrics_{token}2.json"
    translate = tmp_path / f"pipeline_bench_metrics_{token}3.json"
    _write_artifact(
        extract,
        stage_name="extract_terms",
        rows={"lemma": 10, "term": 5, "sentence": 8},
    )
    _write_artifact(
        niqqud,
        stage_name="niqqud_bootstrap",
        rows={"lemma": 5, "term": 0, "sentence": 5},
        details={"lexical": {"failed": 0}, "sentence": {"failed": 0}},
    )
    _write_artifact(
        translate,
        stage_name="translate_bootstrap",
        rows={"lemma": 4, "term": 0, "sentence": 4},
        details={
            "lemma": {"total": 4, "succeeded": 4, "skipped": 0, "failed": 0},
            "term": {"total": 0, "succeeded": 0, "skipped": 0, "failed": 0},
            "sentence": {"total": 4, "succeeded": 4, "skipped": 0, "failed": 0},
        },
    )
    return extract, niqqud, translate


def test_correctness_harness_pass_with_tts_deferred(tmp_path: Path) -> None:
    mod = _load_module()
    report = tmp_path / "correctness_pass.md"
    a, b, c = _seed_pass_set(tmp_path, "20260106_00000")

    rc = mod.run(
        [
            "--artifacts",
            str(a),
            str(b),
            str(c),
            "--report-path",
            str(report),
        ]
    )
    assert rc == 0
    text = report.read_text(encoding="utf-8")
    assert "Overall status: **PASS**" in text
    assert "`tts_bootstrap`" in text
    assert "DEFERRED" in text


def test_correctness_harness_warn_when_niqqud_details_missing(tmp_path: Path) -> None:
    mod = _load_module()
    report = tmp_path / "correctness_warn.md"
    a, b, c = _seed_pass_set(tmp_path, "20260107_00000")
    _write_artifact(
        b,
        stage_name="niqqud_bootstrap",
        rows={"lemma": 5, "term": 0, "sentence": 5},
        details={},  # triggers WARN on missing details
    )

    rc = mod.run(
        [
            "--artifacts",
            str(a),
            str(b),
            str(c),
            "--report-path",
            str(report),
        ]
    )
    assert rc == 2
    text = report.read_text(encoding="utf-8")
    assert "Overall status: **WARN**" in text


def test_correctness_harness_fail_on_extract_terms_invariant(tmp_path: Path) -> None:
    mod = _load_module()
    report = tmp_path / "correctness_fail.md"
    a, b, c = _seed_pass_set(tmp_path, "20260108_00000")
    _write_artifact(
        a,
        stage_name="extract_terms",
        rows={"lemma": 10, "term": 0, "sentence": 8},  # invalid
    )

    rc = mod.run(
        [
            "--artifacts",
            str(a),
            str(b),
            str(c),
            "--report-path",
            str(report),
        ]
    )
    assert rc == 1
    text = report.read_text(encoding="utf-8")
    assert "Overall status: **FAIL**" in text


def test_correctness_harness_malformed_json_fails(tmp_path: Path) -> None:
    mod = _load_module()
    report = tmp_path / "correctness_malformed.md"
    a, b, c = _seed_pass_set(tmp_path, "20260109_00000")
    bad = tmp_path / "pipeline_bench_metrics_20260109_000004.json"
    bad.write_text("{bad-json", encoding="utf-8")

    rc = mod.run(
        [
            "--artifacts",
            str(a),
            str(b),
            str(c),
            str(bad),
            "--report-path",
            str(report),
        ]
    )
    assert rc == 1
    text = report.read_text(encoding="utf-8")
    assert "Malformed JSON" in text

