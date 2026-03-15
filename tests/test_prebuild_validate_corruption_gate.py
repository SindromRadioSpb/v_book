"""Regression tests for prebuild_validate corruption gating."""

from __future__ import annotations

from pathlib import Path

import scripts.prebuild_validate as pv
from scripts import repair_db_corruption as repair_mod


def _status_map(results: list[pv.CheckResult]) -> dict[str, pv.CheckResult]:
    return {item.name: item for item in results}


def test_check_db_corruption_probe_returns_actionable_failure(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "corrupt.db"
    db_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        repair_mod,
        "diagnose_db_corruption",
        lambda _db_path, deep=False: {
            "status": "CORRUPT",
            "failing_objects": ["database", "tm_entry"],
            "quick_check": {
                "rows": ["database disk image is malformed"],
                "error": None,
            },
        },
    )

    result = pv.check_db_corruption_probe(db_path)

    assert result.status == pv.CHECK_FAILED
    assert "database disk image is malformed" in result.details
    assert "repair_db_corruption.py" in result.details


def test_run_prebuild_validation_skips_following_checks_when_corruption_detected(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "corrupt.db"
    db_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(pv, "check_required_local_modules", lambda: True)
    monkeypatch.setattr(
        pv,
        "check_db_corruption_probe",
        lambda _db: pv.CheckResult(
            name="DB Corruption Probe",
            status=pv.CHECK_FAILED,
            details='repair: python scripts/repair_db_corruption.py --db-path "broken.db"',
        ),
    )
    monkeypatch.setattr(pv, "check_fts_presence", lambda _db: (_ for _ in ()).throw(AssertionError("should skip")))
    monkeypatch.setattr(
        pv, "check_project_lifecycle", lambda _db: (_ for _ in ()).throw(AssertionError("should skip"))
    )
    monkeypatch.setattr(pv, "check_export_import", lambda _db: (_ for _ in ()).throw(AssertionError("should skip")))
    monkeypatch.setattr(
        pv, "check_database_integrity", lambda _db: (_ for _ in ()).throw(AssertionError("should skip"))
    )

    final_status, results = pv.run_prebuild_validation(db_path)
    statuses = _status_map(results)

    assert final_status == pv.FINAL_FAIL
    assert statuses["Required Local Modules"].status == pv.CHECK_PASSED
    assert statuses["DB Corruption Probe"].status == pv.CHECK_FAILED
    assert statuses["FTS Presence"].status == pv.CHECK_SKIPPED
    assert statuses["Project Lifecycle"].status == pv.CHECK_SKIPPED
    assert statuses["Export/Import"].status == pv.CHECK_SKIPPED
    assert statuses["Database Integrity"].status == pv.CHECK_SKIPPED
    assert "repair_db_corruption.py" in statuses["FTS Presence"].details
