from __future__ import annotations

import sys
from types import SimpleNamespace

from app.tools import onnx_probe


def test_onnx_probe_import_mode_returns_ok(monkeypatch):
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(__file__="C:/fake/onnxruntime/__init__.py"))
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

    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(__file__="C:/fake/onnxruntime/__init__.py"))
    monkeypatch.setitem(sys.modules, "phonikud_onnx", SimpleNamespace(Phonikud=_FakePhonikud))

    code, payload = onnx_probe.run("probe", model_path_arg=str(model_path), sample_text="\u05e9\u05dc\u05d5\u05dd")

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

    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(__file__="C:/fake/onnxruntime/__init__.py"))
    monkeypatch.setitem(sys.modules, "phonikud_onnx", SimpleNamespace(Phonikud=_FakePhonikud))

    code, payload = onnx_probe.run("probe", model_path_arg=str(model_path), sample_text="\u05e9\u05dc\u05d5\u05dd")

    assert code == 1
    assert payload["ok"] is False
    assert payload["stage"] == "infer"
    assert "without niqqud" in payload["error"].lower()
