"""Frozen ONNX bridge tests for phonikud shim."""

from __future__ import annotations

import importlib
import json
import sys
from types import SimpleNamespace

import pytest


def _reload_shim():
    if "phonikud" in sys.modules:
        return importlib.reload(sys.modules["phonikud"])
    return importlib.import_module("phonikud")


def test_run_onnx_subprocess_uses_helper_in_frozen_runtime(monkeypatch, tmp_path):
    shim = _reload_shim()
    helper_path = tmp_path / "HDLE_ONNX_Probe.exe"
    helper_path.write_text("stub", encoding="utf-8")
    model_path = tmp_path / "phonikud-1.0.int8.onnx"
    model_path.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr(shim, "_is_frozen_windows_runtime", lambda: True)
    monkeypatch.setattr(shim, "_resolve_frozen_onnx_probe_executable", lambda: helper_path)

    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        payload = json.loads(kwargs.get("input") or "{}")
        texts = payload.get("texts") or []
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"outputs": [f"{text}_helper" for text in texts]}, ensure_ascii=True),
            stderr="",
        )

    monkeypatch.setattr(shim.subprocess, "run", _fake_run)
    outputs = shim._run_onnx_subprocess(model_path, ["\u05e9\u05dc\u05d5\u05dd"])

    assert outputs == ["\u05e9\u05dc\u05d5\u05dd_helper"]
    assert captured["cmd"][0] == str(helper_path)
    assert "--mode" in captured["cmd"]
    assert "infer" in captured["cmd"]


def test_run_onnx_subprocess_fails_when_helper_missing_in_frozen_runtime(monkeypatch, tmp_path):
    shim = _reload_shim()
    model_path = tmp_path / "phonikud-1.0.int8.onnx"
    model_path.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr(shim, "_is_frozen_windows_runtime", lambda: True)
    monkeypatch.setattr(shim, "_resolve_frozen_onnx_probe_executable", lambda: None)

    with pytest.raises(RuntimeError, match="helper not found"):
        _ = shim._run_onnx_subprocess(model_path, ["\u05e9\u05dc\u05d5\u05dd"])
