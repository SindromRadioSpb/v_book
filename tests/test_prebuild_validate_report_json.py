"""Regression tests for prebuild_validate JSON evidence reporting."""

from __future__ import annotations

import json
from pathlib import Path

import scripts.prebuild_validate as pv


def test_build_validation_report_includes_checks_and_build_meta(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "candidate.db"
    db_path.write_bytes(b"sqlite")

    monkeypatch.setattr(
        "app.build_meta.get_build_meta",
        lambda: {
            "version": "1.2.3",
            "commit": "abc123",
            "dirty": 0,
            "built_at_utc": "2026-03-15T12:34:56Z",
        },
    )

    report = pv.build_validation_report(
        db_path=db_path,
        profile=pv.PROFILE_REFERENCE_RO,
        skip_export_import=True,
        skip_quick_check=False,
        final_status=pv.FINAL_PASS_WITH_SKIPS,
        results=[
            pv.CheckResult(name="DB Corruption Probe", status=pv.CHECK_PASSED),
            pv.CheckResult(
                name="Export/Import",
                status=pv.CHECK_SKIPPED,
                details="Skipped in reference-ro profile (write check).",
            ),
        ],
    )

    assert report["db_path"] == str(db_path)
    assert report["db_size_bytes"] == db_path.stat().st_size
    assert report["profile"] == pv.PROFILE_REFERENCE_RO
    assert report["skip_export_import"] is True
    assert report["skip_quick_check"] is False
    assert report["final_status"] == pv.FINAL_PASS_WITH_SKIPS
    assert report["build"]["commit"] == "abc123"
    assert report["checks"][0]["name"] == "DB Corruption Probe"
    assert report["checks"][1]["status"] == pv.CHECK_SKIPPED


def test_write_validation_report_writes_json_file(tmp_path: Path) -> None:
    out_path = tmp_path / "verify" / "prebuild_validate.json"
    report = {
        "final_status": pv.FINAL_PASS,
        "checks": [
            {"name": "Required Local Modules", "status": pv.CHECK_PASSED, "details": ""},
        ],
    }

    written_path = pv.write_validation_report(report, out_path)

    assert written_path == out_path
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["final_status"] == pv.FINAL_PASS
    assert payload["checks"][0]["name"] == "Required Local Modules"
