"""Tests for resource manifest parsing and installation status."""

import hashlib
import json
from pathlib import Path

from app.infra.settings import SettingsService
from app.services.resources import ResourceRegistry


def _write_manifest(path: Path, checksum: str) -> None:
    payload = {
        "manifest_version": "1.0",
        "resources": [
            {
                "id": "nikud_pronunciation_model",
                "display_name": "Phonikud Pronunciation Model",
                "version": "1.0",
                "type": "model",
                "required": True,
                "payload_kind": "manual_import",
                "download_url": "",
                "size_bytes": 12,
                "checksum": checksum,
                "local_install_subdir": "models/phonikud",
                "filenames": ["phonikud-1.0.int8.onnx"],
                "description": "test",
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_resource_manifest_parsing_and_status(monkeypatch, tmp_path):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.sync()

    data_root = tmp_path / "data"
    model_path = data_root / "models" / "phonikud" / "phonikud-1.0.int8.onnx"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"test-model")
    checksum = hashlib.sha256(b"test-model").hexdigest()

    manifest_path = tmp_path / "resource_manifest.json"
    _write_manifest(manifest_path, checksum)

    settings.set_value("resources/manifest_path", str(manifest_path))
    settings.set_value("resources/data_root", str(data_root))
    settings.sync()
    monkeypatch.delenv("HDLE_DATA_ROOT", raising=False)

    registry = ResourceRegistry(settings=settings)
    entries = registry.list_entries()
    assert len(entries) == 1
    assert entries[0].id == "nikud_pronunciation_model"

    status = registry.get_status("nikud_pronunciation_model")
    assert status.state == "installed"

    # Corrupt file -> checksum mismatch
    model_path.write_bytes(b"corrupted")
    status_corrupted = registry.get_status("nikud_pronunciation_model")
    assert status_corrupted.state == "corrupted"

