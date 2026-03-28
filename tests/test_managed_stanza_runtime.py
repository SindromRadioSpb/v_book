from __future__ import annotations

import json
from pathlib import Path

from app.services.nlp_runtime.managed_runtime import (
    ManagedStanzaRuntime,
    _ManagedPayloadSource,
)


class _Settings:
    def __init__(self, values: dict[str, str] | None = None):
        self.values = dict(values or {})

    def get_string(self, key: str, default: str = "") -> str:
        return str(self.values.get(key, default))


def _populate_runtime_payload(root: Path) -> Path:
    he = root / "he"
    he.mkdir(parents=True)
    for name in ManagedStanzaRuntime._REQUIRED_MODEL_ENTRIES:
        path = he / name
        if "." in name:
            path.write_text("stub", encoding="utf-8")
        else:
            path.mkdir()
    (root / "resources.json").write_text("{}", encoding="utf-8")
    return he


def test_bootstrap_runtime_copies_legacy_model_into_managed_root(monkeypatch, tmp_path):
    managed_root = tmp_path / "managed"
    legacy_root = tmp_path / "legacy"
    legacy_he = _populate_runtime_payload(legacy_root)

    runtime = ManagedStanzaRuntime(
        settings=_Settings({ManagedStanzaRuntime.SETTINGS_KEY_MANAGED_RUNTIME_ROOT: str(managed_root)})
    )
    monkeypatch.setattr(runtime, "_bundled_model_candidates", lambda: [])
    monkeypatch.setattr(
        runtime,
        "_legacy_model_candidates",
        lambda: [
            _ManagedPayloadSource(
                source_kind="legacy_cache",
                resources_root=legacy_root,
                model_path=legacy_he,
            )
        ],
    )

    result = runtime.bootstrap_runtime(force_repair=False)

    assert result.ok is True
    assert result.source_kind == "legacy_cache"
    assert result.bundled_payload_root is None
    assert (managed_root / "stanza_resources" / "he" / "tokenize").exists()
    assert (managed_root / "stanza_resources" / "he" / "backward_charlm").exists()
    assert (managed_root / "stanza_resources" / "resources.json").exists()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["model_source_kind"] == "legacy_cache"


def test_bootstrap_runtime_prefers_bundled_dev_over_legacy(monkeypatch, tmp_path):
    managed_root = tmp_path / "managed"
    bundled_root = tmp_path / "bundled_dev"
    bundled_he = _populate_runtime_payload(bundled_root / "stanza_resources")
    payload_manifest = bundled_root / "payload_manifest.json"
    payload_manifest.write_text("{}", encoding="utf-8")

    legacy_root = tmp_path / "legacy"
    legacy_he = _populate_runtime_payload(legacy_root)

    runtime = ManagedStanzaRuntime(
        settings=_Settings({ManagedStanzaRuntime.SETTINGS_KEY_MANAGED_RUNTIME_ROOT: str(managed_root)})
    )
    monkeypatch.setattr(
        runtime,
        "_bundled_model_candidates",
        lambda: [
            _ManagedPayloadSource(
                source_kind="bundled_dev",
                resources_root=bundled_root / "stanza_resources",
                model_path=bundled_he,
                payload_root=bundled_root,
                payload_manifest_path=payload_manifest,
            )
        ],
    )
    monkeypatch.setattr(
        runtime,
        "_legacy_model_candidates",
        lambda: [
            _ManagedPayloadSource(
                source_kind="legacy_cache",
                resources_root=legacy_root,
                model_path=legacy_he,
            )
        ],
    )

    result = runtime.bootstrap_runtime(force_repair=False)

    assert result.ok is True
    assert result.source_kind == "bundled_dev"
    assert result.bundled_payload_root == str(bundled_root)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["model_source_kind"] == "bundled_dev"
    assert manifest["bundled_payload_root"] == str(bundled_root)
    assert manifest["payload_manifest_path"] == str(payload_manifest)


def test_bootstrap_runtime_repairs_incomplete_managed_copy_from_legacy(monkeypatch, tmp_path):
    managed_root = tmp_path / "managed"
    managed_resources = managed_root / "stanza_resources"
    managed_he = managed_resources / "he"
    managed_he.mkdir(parents=True)
    (managed_resources / "resources.json").write_text("{}", encoding="utf-8")
    (managed_he / "forward_charlm").mkdir()
    (managed_he / "default.zip").write_text("stub", encoding="utf-8")

    legacy_root = tmp_path / "legacy"
    legacy_he = _populate_runtime_payload(legacy_root)

    runtime = ManagedStanzaRuntime(
        settings=_Settings({ManagedStanzaRuntime.SETTINGS_KEY_MANAGED_RUNTIME_ROOT: str(managed_root)})
    )
    monkeypatch.setattr(runtime, "_bundled_model_candidates", lambda: [])
    monkeypatch.setattr(
        runtime,
        "_legacy_model_candidates",
        lambda: [
            _ManagedPayloadSource(
                source_kind="legacy_cache",
                resources_root=legacy_root,
                model_path=legacy_he,
            )
        ],
    )

    result = runtime.bootstrap_runtime(force_repair=False)

    assert result.ok is True
    assert result.source_kind == "legacy_cache"
    assert (managed_he / "backward_charlm").exists()
    assert (managed_he / "tokenize").exists()


def test_detect_best_model_path_prefers_managed_copy(monkeypatch, tmp_path):
    managed_root = tmp_path / "managed"
    managed_resources = managed_root / "stanza_resources"
    managed_he = _populate_runtime_payload(managed_resources)

    runtime = ManagedStanzaRuntime(
        settings=_Settings({ManagedStanzaRuntime.SETTINGS_KEY_MANAGED_RUNTIME_ROOT: str(managed_root)})
    )
    monkeypatch.setattr(runtime, "_bundled_model_candidates", lambda: [])
    monkeypatch.setattr(runtime, "_legacy_model_candidates", lambda: [])

    assert runtime.detect_best_model_path() == str(managed_he)


def test_runtime_root_falls_back_to_temp_when_preferred_root_is_not_writable(monkeypatch, tmp_path):
    managed_root = tmp_path / "blocked"
    fallback_root = tmp_path / "temp" / "HDLE" / "nlp_runtime"
    runtime = ManagedStanzaRuntime(
        settings=_Settings({ManagedStanzaRuntime.SETTINGS_KEY_MANAGED_RUNTIME_ROOT: str(managed_root)})
    )

    original_mkdir = Path.mkdir

    def _fake_mkdir(self, *args, **kwargs):
        if self == managed_root:
            raise PermissionError("blocked")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", _fake_mkdir)
    monkeypatch.setattr(
        "app.services.nlp_runtime.managed_runtime.tempfile.gettempdir",
        lambda: str(tmp_path / "temp"),
    )

    root = runtime.runtime_root()

    assert root == fallback_root
