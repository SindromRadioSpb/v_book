"""Tests for runtime build metadata traceability."""

from __future__ import annotations

from app import __version__
import app.build_meta as build_meta
import app.main as main
from app.infra.settings import SettingsService


def test_get_build_meta_exposes_required_fields():
    meta = build_meta.get_build_meta()

    assert meta["version"] == __version__
    assert "commit" in meta
    assert "built_at_utc" in meta
    assert meta["dirty"] in (0, 1)


def test_run_self_check_attaches_build_metadata(monkeypatch):
    monkeypatch.setattr(SettingsService, "get_instance", classmethod(lambda cls: object()))
    monkeypatch.setattr(
        main, "_run_import_self_check", lambda _settings: (0, {"mode": "import", "ok": True})
    )
    monkeypatch.setattr(
        main,
        "get_build_meta",
        lambda: {
            "version": "1.0.0",
            "commit": "abc123",
            "dirty": 1,
            "built_at_utc": "2026-03-06T00:00:00Z",
        },
    )

    exit_code, payload = main.run_self_check("import", db_path_arg=None)

    assert exit_code == 0
    assert payload["mode"] == "import"
    assert payload["build"]["commit"] == "abc123"
    assert payload["build"]["dirty"] == 1
