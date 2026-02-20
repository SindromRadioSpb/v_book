"""Tests for phonikud shim ONNX mode routing."""

from __future__ import annotations

import importlib
import sys
import types


def _reload_shim():
    if "phonikud" in sys.modules:
        return importlib.reload(sys.modules["phonikud"])
    return importlib.import_module("phonikud")


def test_shim_onnx_file_path_uses_phonikud_onnx(monkeypatch, tmp_path):
    model_path = tmp_path / "phonikud-1.0.int8.onnx"
    model_path.write_text("dummy", encoding="utf-8")

    seen = {"path": None}

    class _FakePhonikud:
        def __init__(self, model_path_value: str):
            seen["path"] = model_path_value

        def add_diacritics(self, text: str) -> str:
            return text + "_nikud"

    fake_module = types.SimpleNamespace(Phonikud=_FakePhonikud)
    monkeypatch.setitem(sys.modules, "phonikud_onnx", fake_module)
    monkeypatch.setenv("PHONIKUD_MODEL_PATH", str(model_path))

    shim = _reload_shim()
    shim._load_model_bundle.cache_clear()
    out = shim.add_niqqud("\u05e9\u05dc\u05d5\u05dd")

    assert out.endswith("_nikud")
    assert seen["path"] == str(model_path)
    assert shim.get_runtime_mode() == "real_inference"


def test_shim_directory_prefers_int8_onnx(monkeypatch, tmp_path):
    (tmp_path / "phonikud-1.0.onnx").write_text("full", encoding="utf-8")
    (tmp_path / "phonikud-1.0.int8.onnx").write_text("int8", encoding="utf-8")

    seen = {"path": None}

    class _FakePhonikud:
        def __init__(self, model_path_value: str):
            seen["path"] = model_path_value

        def add_diacritics(self, text: str) -> str:
            return text

    fake_module = types.SimpleNamespace(Phonikud=_FakePhonikud)
    monkeypatch.setitem(sys.modules, "phonikud_onnx", fake_module)
    monkeypatch.setenv("PHONIKUD_MODEL_PATH", str(tmp_path))

    shim = _reload_shim()
    shim._load_model_bundle.cache_clear()
    _ = shim.add_niqqud("\u05ea\u05d7\u05e0\u05d4")

    assert seen["path"] is not None
    assert seen["path"].endswith("int8.onnx")
