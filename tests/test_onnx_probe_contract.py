from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from pathlib import Path

from app.tools import onnx_probe


def test_onnx_probe_import_mode_returns_ok(monkeypatch):
    monkeypatch.setitem(
        sys.modules, "onnxruntime", SimpleNamespace(__file__="C:/fake/onnxruntime/__init__.py")
    )
    monkeypatch.setitem(sys.modules, "phonikud_onnx", SimpleNamespace(Phonikud=object))

    code, payload = onnx_probe.run("import", model_path_arg="", sample_text="sample")

    assert code == 0
    assert payload["ok"] is True
    assert payload["stage"] == "import"
    assert "onnxruntime" in payload["onnxruntime_origin"].lower()


def test_onnx_probe_probe_mode_requires_niqqud(monkeypatch, tmp_path):
    model_path = tmp_path / "phonikud-1.0.int8.onnx"
    model_path.write_text("dummy", encoding="utf-8")

    class _FakePhonikud:
        def __init__(self, _model_path: str):
            pass

        def add_diacritics(self, _text: str) -> str:
            return "\u05e9\u05b8\u05c1\u05dc\u05d5\u05b9\u05dd"

    monkeypatch.setitem(
        sys.modules, "onnxruntime", SimpleNamespace(__file__="C:/fake/onnxruntime/__init__.py")
    )
    monkeypatch.setitem(sys.modules, "phonikud_onnx", SimpleNamespace(Phonikud=_FakePhonikud))

    code, payload = onnx_probe.run(
        "probe", model_path_arg=str(model_path), sample_text="\u05e9\u05dc\u05d5\u05dd"
    )

    assert code == 0
    assert payload["ok"] is True
    assert payload["stage"] == "infer"
    assert payload["has_niqqud"] is True


def test_onnx_probe_probe_mode_fails_on_identity_output(monkeypatch, tmp_path):
    model_path = tmp_path / "phonikud-1.0.int8.onnx"
    model_path.write_text("dummy", encoding="utf-8")

    class _FakePhonikud:
        def __init__(self, _model_path: str):
            pass

        def add_diacritics(self, text: str) -> str:
            return text

    monkeypatch.setitem(
        sys.modules, "onnxruntime", SimpleNamespace(__file__="C:/fake/onnxruntime/__init__.py")
    )
    monkeypatch.setitem(sys.modules, "phonikud_onnx", SimpleNamespace(Phonikud=_FakePhonikud))

    code, payload = onnx_probe.run(
        "probe", model_path_arg=str(model_path), sample_text="\u05e9\u05dc\u05d5\u05dd"
    )

    assert code == 1
    assert payload["ok"] is False
    assert payload["stage"] == "infer"
    assert "without niqqud" in payload["error"].lower()


def test_onnx_probe_discovers_bundled_model_when_data_root_missing(monkeypatch, tmp_path):
    bundled_root = tmp_path / "resources" / "models" / "phonikud"
    bundled_root.mkdir(parents=True)
    preferred = bundled_root / "phonikud-1.0.int8.onnx"
    preferred.write_text("dummy", encoding="utf-8")

    class _FakeResourcePaths:
        @staticmethod
        def build(*, create: bool = True):
            assert create is False
            return SimpleNamespace(models_root=tmp_path / "missing_models")

        @staticmethod
        def resolve_bundled_resources_root():
            return tmp_path / "resources"

    monkeypatch.setitem(
        sys.modules, "app.infra.resource_paths", SimpleNamespace(ResourcePaths=_FakeResourcePaths)
    )

    discovered = onnx_probe._discover_default_model_path()

    assert isinstance(discovered, Path)
    assert discovered == preferred


def test_ensure_hf_home_accepts_existing_configured_path_without_write_probe(
    monkeypatch, tmp_path: Path
):
    configured = tmp_path / "hf_home"
    configured.mkdir()
    sentinel = configured / "keep.txt"
    sentinel.write_text("ok", encoding="utf-8")

    monkeypatch.setenv("HF_HOME", str(configured))
    monkeypatch.delenv("HF_HUB_DISABLE_XET", raising=False)
    monkeypatch.delenv("HF_HUB_DISABLE_TELEMETRY", raising=False)
    monkeypatch.delenv("HF_HUB_DISABLE_SYMLINKS_WARNING", raising=False)

    def _fail_named_tempfile(*args, **kwargs):
        raise AssertionError("configured HF_HOME must not use NamedTemporaryFile probe")

    monkeypatch.setattr(onnx_probe.tempfile, "NamedTemporaryFile", _fail_named_tempfile)
    monkeypatch.setattr(onnx_probe.sys, "frozen", True, raising=False)

    onnx_probe._ensure_hf_home()

    assert os.environ["HF_HOME"] == str(configured)
    assert os.environ["HF_HUB_DISABLE_XET"] == "1"
    assert os.environ["HF_HUB_DISABLE_TELEMETRY"] == "1"
    assert os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] == "1"


def test_ensure_hf_home_frozen_missing_configured_path_falls_back_without_touching_it(
    monkeypatch, tmp_path: Path
):
    missing_configured = tmp_path / "missing_hf_home"
    fallback_root = tmp_path / "cwd"
    fallback_root.mkdir()

    monkeypatch.setenv("HF_HOME", str(missing_configured))
    monkeypatch.setattr(onnx_probe.sys, "frozen", True, raising=False)
    monkeypatch.setattr(onnx_probe.Path, "cwd", staticmethod(lambda: fallback_root))

    onnx_probe._ensure_hf_home()

    assert os.environ["HF_HOME"] == str(fallback_root / "build" / "hf_cache")
    assert not missing_configured.exists()
