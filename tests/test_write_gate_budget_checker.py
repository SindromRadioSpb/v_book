"""Unit tests for scripts/check_write_gate_budget.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_checker_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "check_write_gate_budget.py"
    spec = importlib.util.spec_from_file_location("check_write_gate_budget", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_artifact(
    path: Path,
    *,
    overall_max_hold_ms: float,
    lemma_max_hold_ms: float,
    save_p95_ms: float,
    save_max_ms: float,
) -> None:
    payload = {
        "gate_trace": {
            "max_hold_ms": overall_max_hold_ms,
            "top_phase_max_holds": [
                {"phase": "import.table.lemma", "max_hold_ms": lemma_max_hold_ms},
            ],
        },
        "save_ops": {
            "latency_ms": {
                "p95": save_p95_ms,
                "max": save_max_ms,
            }
        },
    }
    path.write_text(__import__("json").dumps(payload), encoding="utf-8")


def test_budget_checker_pass_classification(tmp_path: Path) -> None:
    checker = _load_checker_module()
    report_path = tmp_path / "pass_report.md"

    a1 = tmp_path / "import_concurrent_save_metrics_20260101_000001.json"
    a2 = tmp_path / "import_concurrent_save_metrics_20260101_000002.json"
    a3 = tmp_path / "import_concurrent_save_metrics_20260101_000003.json"
    for path in (a1, a2, a3):
        _write_artifact(
            path,
            overall_max_hold_ms=280.0,
            lemma_max_hold_ms=280.0,
            save_p95_ms=200.0,
            save_max_ms=320.0,
        )

    rc = checker.run(
        [
            "--artifacts",
            str(a1),
            str(a2),
            str(a3),
            "--report-path",
            str(report_path),
        ]
    )

    assert rc == 0
    text = report_path.read_text(encoding="utf-8")
    assert "Overall status: **PASS**" in text


def test_budget_checker_warn_classification(tmp_path: Path) -> None:
    checker = _load_checker_module()
    report_path = tmp_path / "warn_report.md"
    pass_limit = float(checker.PASS_THRESHOLDS_MS["overall_hold_p95_ms"])
    warn_value = pass_limit + 5.0

    a1 = tmp_path / "import_concurrent_save_metrics_20260102_000001.json"
    a2 = tmp_path / "import_concurrent_save_metrics_20260102_000002.json"
    a3 = tmp_path / "import_concurrent_save_metrics_20260102_000003.json"
    for path in (a1, a2, a3):
        _write_artifact(
            path,
            overall_max_hold_ms=warn_value,
            lemma_max_hold_ms=280.0,
            save_p95_ms=200.0,
            save_max_ms=320.0,
        )

    rc = checker.run(
        [
            "--artifacts",
            str(a1),
            str(a2),
            str(a3),
            "--report-path",
            str(report_path),
        ]
    )

    assert rc == 2
    text = report_path.read_text(encoding="utf-8")
    assert "Overall status: **WARN**" in text


def test_budget_checker_fail_classification(tmp_path: Path) -> None:
    checker = _load_checker_module()
    report_path = tmp_path / "fail_report.md"
    pass_limit = float(checker.PASS_THRESHOLDS_MS["save_p95_ms"])
    fail_value = pass_limit + max(30.0, pass_limit * 0.10) + 5.0

    a1 = tmp_path / "import_concurrent_save_metrics_20260103_000001.json"
    a2 = tmp_path / "import_concurrent_save_metrics_20260103_000002.json"
    a3 = tmp_path / "import_concurrent_save_metrics_20260103_000003.json"
    for path in (a1, a2, a3):
        _write_artifact(
            path,
            overall_max_hold_ms=280.0,
            lemma_max_hold_ms=280.0,
            save_p95_ms=fail_value,
            save_max_ms=320.0,
        )

    rc = checker.run(
        [
            "--artifacts",
            str(a1),
            str(a2),
            str(a3),
            "--report-path",
            str(report_path),
        ]
    )

    assert rc == 1
    text = report_path.read_text(encoding="utf-8")
    assert "Overall status: **FAIL**" in text


def test_budget_checker_glob_and_dir_take_selection_deterministic(tmp_path: Path) -> None:
    checker = _load_checker_module()

    names = [
        "import_concurrent_save_metrics_20260104_000004.json",
        "import_concurrent_save_metrics_20260104_000001.json",
        "import_concurrent_save_metrics_20260104_000003.json",
        "import_concurrent_save_metrics_20260104_000002.json",
    ]
    for idx, name in enumerate(names):
        path = tmp_path / name
        _write_artifact(
            path,
            overall_max_hold_ms=280.0 + idx,
            lemma_max_hold_ms=280.0 + idx,
            save_p95_ms=200.0,
            save_max_ms=320.0,
        )

    report_glob = tmp_path / "glob_report.md"
    rc_glob = checker.run(
        [
            "--glob",
            str(tmp_path / "import_concurrent_save_metrics_*.json"),
            "--take",
            "2",
            "--report-path",
            str(report_glob),
        ]
    )
    assert rc_glob in (0, 2)
    glob_text = report_glob.read_text(encoding="utf-8")
    assert "import_concurrent_save_metrics_20260104_000003.json" in glob_text
    assert "import_concurrent_save_metrics_20260104_000004.json" in glob_text
    assert "import_concurrent_save_metrics_20260104_000001.json" not in glob_text

    report_dir = tmp_path / "dir_report.md"
    rc_dir = checker.run(
        [
            "--dir",
            str(tmp_path),
            "--take",
            "2",
            "--report-path",
            str(report_dir),
        ]
    )
    assert rc_dir in (0, 2)
    dir_text = report_dir.read_text(encoding="utf-8")
    assert "import_concurrent_save_metrics_20260104_000003.json" in dir_text
    assert "import_concurrent_save_metrics_20260104_000004.json" in dir_text


def test_budget_checker_fails_on_malformed_json(tmp_path: Path) -> None:
    checker = _load_checker_module()
    report_path = tmp_path / "malformed_report.md"

    good = tmp_path / "import_concurrent_save_metrics_20260105_000001.json"
    bad = tmp_path / "import_concurrent_save_metrics_20260105_000002.json"
    _write_artifact(
        good,
        overall_max_hold_ms=280.0,
        lemma_max_hold_ms=280.0,
        save_p95_ms=200.0,
        save_max_ms=320.0,
    )
    bad.write_text("{not-json", encoding="utf-8")

    rc = checker.run(
        [
            "--artifacts",
            str(good),
            str(bad),
            "--report-path",
            str(report_path),
        ]
    )

    assert rc == 1
    text = report_path.read_text(encoding="utf-8")
    assert "Malformed JSON" in text
