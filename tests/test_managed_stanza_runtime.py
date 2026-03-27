from __future__ import annotations

from pathlib import Path

from app.services.nlp_runtime.managed_runtime import ManagedStanzaRuntime


class _Settings:
    def __init__(self, values: dict[str, str] | None = None):
        self.values = dict(values or {})

    def get_string(self, key: str, default: str = "") -> str:
        return str(self.values.get(key, default))


def test_bootstrap_runtime_copies_legacy_model_into_managed_root(monkeypatch, tmp_path):
    managed_root = tmp_path / "managed"
    legacy_he = tmp_path / "legacy" / "he"
    legacy_he.mkdir(parents=True)
    (legacy_he / "tokenize.pt").write_text("stub", encoding="utf-8")

    runtime = ManagedStanzaRuntime(
        settings=_Settings({ManagedStanzaRuntime.SETTINGS_KEY_MANAGED_RUNTIME_ROOT: str(managed_root)})
    )
    monkeypatch.setattr(
        runtime,
        "_bundled_model_candidates",
        lambda: [],
    )
    monkeypatch.setattr(
        runtime,
        "_legacy_model_candidates",
        lambda: [legacy_he],
    )

    result = runtime.bootstrap_runtime(force_repair=False)

    assert result.ok is True
    assert result.source_kind == "legacy"
    assert (managed_root / "stanza_resources" / "he" / "tokenize.pt").exists()
    assert result.manifest_path.exists()


def test_detect_best_model_path_prefers_managed_copy(monkeypatch, tmp_path):
    managed_root = tmp_path / "managed"
    managed_he = managed_root / "stanza_resources" / "he"
    managed_he.mkdir(parents=True)
    (managed_he / "tokenize.pt").write_text("stub", encoding="utf-8")

    runtime = ManagedStanzaRuntime(
        settings=_Settings({ManagedStanzaRuntime.SETTINGS_KEY_MANAGED_RUNTIME_ROOT: str(managed_root)})
    )
    monkeypatch.setattr(runtime, "_bundled_model_candidates", lambda: [])
    monkeypatch.setattr(runtime, "_legacy_model_candidates", lambda: [])

    assert runtime.detect_best_model_path() == str(managed_he)
