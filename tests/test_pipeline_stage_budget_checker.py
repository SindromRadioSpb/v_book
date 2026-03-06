"""Unit tests for scripts/check_pipeline_stage_budget.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_checker_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "check_pipeline_stage_budget.py"
    spec = importlib.util.spec_from_file_location("check_pipeline_stage_budget", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_stage_artifact(
    path: Path,
    *,
    stage_name: str,
    duration_sec: float,
    rows: dict[str, int],
    errors_count: int = 0,
    overall_status: str = "pass",
    stage_status: str = "ok",
) -> None:
    payload = {
        "timestamp_utc": "2026-03-06T00:00:00+00:00",
        "scenario": stage_name,
        "overall_status": overall_status,
        "config": {
            "overwrite": 1,
            "doc_limit": 30,
            "lemma_limit": 30,
            "term_limit": 30,
            "sentence_limit": 30,
        },
        "db": {
            "source_db": r"J:\Project_Vibe\V_book\ref_corpora\safe.db",
            "base_sandbox_db": r"J:\Project_Vibe\V_book\build\bench\safe.db",
            "working_db": r"J:\Project_Vibe\V_book\build\tmp\safe_work.db",
        },
        "stages": [
            {
                "name": stage_name,
                "started_at_utc": "2026-03-06T00:00:00+00:00",
                "ended_at_utc": "2026-03-06T00:01:00+00:00",
                "duration_sec": duration_sec,
                "rows_processed": rows,
                "overwrite": 1,
                "errors_count": errors_count,
                "error_samples": [],
                "details": {},
                "status": stage_status,
            }
        ],
        "artifacts": {
            "metrics_json": str(path),
            "report_md": str(path.with_suffix(".md")),
            "latest_log": str(path.with_suffix(".log")),
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _seed_pass_set(tmp_path: Path, *, prefix: str = "20260101_00000") -> tuple[Path, Path, Path]:
    extract = tmp_path / f"pipeline_bench_metrics_{prefix}1.json"
    niqqud = tmp_path / f"pipeline_bench_metrics_{prefix}2.json"
    translate = tmp_path / f"pipeline_bench_metrics_{prefix}3.json"

    _write_stage_artifact(
        extract,
        stage_name="extract_terms",
        duration_sec=100.0,
        rows={"lemma": 7600, "term": 600, "sentence": 2400},
    )
    _write_stage_artifact(
        niqqud,
        stage_name="niqqud_bootstrap",
        duration_sec=120.0,
        rows={"lemma": 1000, "term": 0, "sentence": 1000},
    )
    _write_stage_artifact(
        translate,
        stage_name="translate_bootstrap",
        duration_sec=960.0,
        rows={"lemma": 30, "term": 0, "sentence": 30},
    )
    return extract, niqqud, translate


def test_pipeline_budget_checker_pass_and_deferred_tts(tmp_path: Path) -> None:
    checker = _load_checker_module()
    report = tmp_path / "pipeline_budget_pass.md"
    artifacts = _seed_pass_set(tmp_path)

    rc = checker.run(
        [
            "--artifacts",
            str(artifacts[0]),
            str(artifacts[1]),
            str(artifacts[2]),
            "--report-path",
            str(report),
        ]
    )
    assert rc == 0
    text = report.read_text(encoding="utf-8")
    assert "Overall status: **PASS**" in text
    assert "`tts_bootstrap`" in text
    assert "DEFERRED" in text


def test_pipeline_budget_checker_warn_classification(tmp_path: Path) -> None:
    checker = _load_checker_module()
    report = tmp_path / "pipeline_budget_warn.md"
    extract, niqqud, translate = _seed_pass_set(tmp_path, prefix="20260102_00000")

    _write_stage_artifact(
        extract,
        stage_name="extract_terms",
        duration_sec=145.0,  # in WARN band
        rows={"lemma": 7600, "term": 600, "sentence": 2400},
    )

    rc = checker.run(
        [
            "--artifacts",
            str(extract),
            str(niqqud),
            str(translate),
            "--report-path",
            str(report),
        ]
    )
    assert rc == 2
    text = report.read_text(encoding="utf-8")
    assert "Overall status: **WARN**" in text


def test_pipeline_budget_checker_fail_classification(tmp_path: Path) -> None:
    checker = _load_checker_module()
    report = tmp_path / "pipeline_budget_fail.md"
    extract, niqqud, translate = _seed_pass_set(tmp_path, prefix="20260103_00000")

    _write_stage_artifact(
        translate,
        stage_name="translate_bootstrap",
        duration_sec=960.0,
        rows={"lemma": 30, "term": 0, "sentence": 30},
        errors_count=1,
    )

    rc = checker.run(
        [
            "--artifacts",
            str(extract),
            str(niqqud),
            str(translate),
            "--report-path",
            str(report),
        ]
    )
    assert rc == 1
    text = report.read_text(encoding="utf-8")
    assert "Overall status: **FAIL**" in text


def test_pipeline_budget_checker_deterministic_stage_pick(tmp_path: Path) -> None:
    checker = _load_checker_module()
    report = tmp_path / "pipeline_budget_pick.md"

    _seed_pass_set(tmp_path, prefix="20260104_00000")
    new_extract, new_niqqud, new_translate = _seed_pass_set(tmp_path, prefix="20260104_00010")

    rc = checker.run(
        [
            "--glob",
            str(tmp_path / "pipeline_bench_metrics_*.json"),
            "--take",
            "6",
            "--report-path",
            str(report),
        ]
    )
    assert rc == 0
    text = report.read_text(encoding="utf-8")
    assert new_extract.name in text
    assert new_niqqud.name in text
    assert new_translate.name in text
    assert "pipeline_bench_metrics_20260104_000001.json" not in text


def test_pipeline_budget_checker_fails_on_malformed_json(tmp_path: Path) -> None:
    checker = _load_checker_module()
    report = tmp_path / "pipeline_budget_malformed.md"
    extract, niqqud, translate = _seed_pass_set(tmp_path, prefix="20260105_00000")
    bad = tmp_path / "pipeline_bench_metrics_20260105_000004.json"
    bad.write_text("{broken-json", encoding="utf-8")

    rc = checker.run(
        [
            "--artifacts",
            str(extract),
            str(niqqud),
            str(translate),
            str(bad),
            "--report-path",
            str(report),
        ]
    )
    assert rc == 1
    text = report.read_text(encoding="utf-8")
    assert "Malformed JSON" in text
