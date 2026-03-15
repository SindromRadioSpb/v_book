"""Tests for prebuild_validate reference-ro behavior."""

from __future__ import annotations

from pathlib import Path

import scripts.prebuild_validate as pv


def _status_map(results: list[pv.CheckResult]) -> dict[str, str]:
    return {item.name: item.status for item in results}


def test_reference_ro_profile_returns_pass_with_skips(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "readonly.db"
    db_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(pv, "check_required_local_modules", lambda: True)
    monkeypatch.setattr(
        pv,
        "check_db_corruption_probe",
        lambda _db: pv.CheckResult(name="DB Corruption Probe", status=pv.CHECK_PASSED),
    )
    monkeypatch.setattr(pv, "check_fts_presence", lambda _db: True)
    monkeypatch.setattr(pv, "check_project_lifecycle", lambda _db: False)
    monkeypatch.setattr(pv, "check_export_import", lambda _db: False)
    monkeypatch.setattr(pv, "check_database_integrity", lambda _db: True)

    final_status, results = pv.run_prebuild_validation(
        db_path,
        profile=pv.PROFILE_REFERENCE_RO,
        skip_export_import=False,
        skip_quick_check=False,
    )

    statuses = _status_map(results)
    assert final_status == pv.FINAL_PASS_WITH_SKIPS
    assert statuses["Required Local Modules"] == pv.CHECK_PASSED
    assert statuses["DB Corruption Probe"] == pv.CHECK_PASSED
    assert statuses["FTS Presence"] == pv.CHECK_PASSED
    assert statuses["Project Lifecycle"] == pv.CHECK_SKIPPED
    assert statuses["Export/Import"] == pv.CHECK_SKIPPED
    assert statuses["Database Integrity"] == pv.CHECK_PASSED


def test_default_profile_still_fails_on_write_check(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "readonly.db"
    db_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(pv, "check_required_local_modules", lambda: True)
    monkeypatch.setattr(
        pv,
        "check_db_corruption_probe",
        lambda _db: pv.CheckResult(name="DB Corruption Probe", status=pv.CHECK_PASSED),
    )
    monkeypatch.setattr(pv, "check_fts_presence", lambda _db: True)
    monkeypatch.setattr(pv, "check_project_lifecycle", lambda _db: False)
    monkeypatch.setattr(pv, "check_export_import", lambda _db: True)
    monkeypatch.setattr(pv, "check_database_integrity", lambda _db: True)

    final_status, results = pv.run_prebuild_validation(
        db_path,
        profile=pv.PROFILE_DEFAULT,
        skip_export_import=False,
        skip_quick_check=False,
    )

    statuses = _status_map(results)
    assert statuses["DB Corruption Probe"] == pv.CHECK_PASSED
    assert statuses["Project Lifecycle"] == pv.CHECK_FAILED
    assert final_status == pv.FINAL_FAIL
