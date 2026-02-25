"""Tests for phonikud shim ONNX mode routing."""

from __future__ import annotations

import importlib
import json
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


def test_shim_path_without_onnx_extension_recovers_existing_file(monkeypatch, tmp_path):
    onnx_file = tmp_path / "phonikud-1.0.int8.onnx"
    onnx_file.write_text("int8", encoding="utf-8")
    input_without_ext = tmp_path / "phonikud-1.0.int8"

    seen = {"path": None}

    class _FakePhonikud:
        def __init__(self, model_path_value: str):
            seen["path"] = model_path_value

        def add_diacritics(self, text: str) -> str:
            return text

    fake_module = types.SimpleNamespace(Phonikud=_FakePhonikud)
    monkeypatch.setitem(sys.modules, "phonikud_onnx", fake_module)
    monkeypatch.setenv("PHONIKUD_MODEL_PATH", str(input_without_ext))

    shim = _reload_shim()
    shim._load_model_bundle.cache_clear()
    _ = shim.add_niqqud("\u05e9\u05dc\u05d5\u05dd")

    assert seen["path"] == str(onnx_file)


def test_shim_path_with_trailing_dot_recovers_existing_onnx(monkeypatch, tmp_path):
    onnx_file = tmp_path / "phonikud-1.0.int8.onnx"
    onnx_file.write_text("int8", encoding="utf-8")
    path_with_trailing_dot = str(tmp_path / "phonikud-1.0.int8.")  # common copy/paste typo

    seen = {"path": None}

    class _FakePhonikud:
        def __init__(self, model_path_value: str):
            seen["path"] = model_path_value

        def add_diacritics(self, text: str) -> str:
            return text

    fake_module = types.SimpleNamespace(Phonikud=_FakePhonikud)
    monkeypatch.setitem(sys.modules, "phonikud_onnx", fake_module)
    monkeypatch.setenv("PHONIKUD_MODEL_PATH", path_with_trailing_dot)

    shim = _reload_shim()
    shim.reset_runtime_cache()
    _ = shim.add_niqqud("\u05e9\u05dc\u05d5\u05dd")

    assert seen["path"] == str(onnx_file)
    assert shim.get_runtime_mode() == "real_inference"


def test_shim_falls_back_to_subprocess_when_inprocess_onnx_load_fails(monkeypatch, tmp_path):
    onnx_file = tmp_path / "phonikud-1.0.int8.onnx"
    onnx_file.write_text("int8", encoding="utf-8")

    class _BrokenPhonikud:
        def __init__(self, _model_path_value: str):
            raise RuntimeError("DLL load failed while importing onnxruntime_pybind11_state")

    fake_module = types.SimpleNamespace(Phonikud=_BrokenPhonikud)
    monkeypatch.setitem(sys.modules, "phonikud_onnx", fake_module)
    monkeypatch.setenv("PHONIKUD_MODEL_PATH", str(onnx_file))

    shim = _reload_shim()
    shim.reset_runtime_cache()

    def _fake_run(*_args, **kwargs):
        payload = json.loads(kwargs.get("input") or "{}")
        texts = payload.get("texts") or []
        stdout = json.dumps({"outputs": [f"{text}_sub" for text in texts]}, ensure_ascii=False)
        return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(shim.subprocess, "run", _fake_run)
    out = shim.add_niqqud("\u05e9\u05dc\u05d5\u05dd")

    assert out.endswith("_sub")
    assert shim.get_runtime_mode() == "real_inference"
    assert "subprocess backend active" in shim.get_runtime_details().lower()


def test_shim_marks_fallback_when_subprocess_probe_returns_identity(monkeypatch, tmp_path):
    onnx_file = tmp_path / "phonikud-1.0.int8.onnx"
    onnx_file.write_text("int8", encoding="utf-8")

    class _BrokenPhonikud:
        def __init__(self, _model_path_value: str):
            raise RuntimeError("DLL load failed while importing onnxruntime_pybind11_state")

    fake_module = types.SimpleNamespace(Phonikud=_BrokenPhonikud)
    monkeypatch.setitem(sys.modules, "phonikud_onnx", fake_module)
    monkeypatch.setenv("PHONIKUD_MODEL_PATH", str(onnx_file))

    shim = _reload_shim()
    shim.reset_runtime_cache()

    def _fake_run(*_args, **kwargs):
        payload = json.loads(kwargs.get("input") or "{}")
        texts = payload.get("texts") or []
        stdout = json.dumps({"outputs": texts}, ensure_ascii=False)
        return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(shim.subprocess, "run", _fake_run)
    out = shim.add_niqqud("\u05e9\u05dc\u05d5\u05dd")

    assert out == "\u05e9\u05dc\u05d5\u05dd"
    assert shim.get_runtime_mode() == "fallback"
    assert "identity output" in shim.get_runtime_details().lower()
