"""Phonikud adapter mode detection tests."""

from __future__ import annotations

import importlib
import os
import types

from app.infra.pronunciation import PhonikudAdapter


def test_phonikud_adapter_reports_real_inference(monkeypatch):
    class _FakeModule:
        @staticmethod
        def add_niqqud(text: str) -> str:
            return f"{text}_nikud"

        @staticmethod
        def get_runtime_mode() -> str:
            return "real_inference"

    monkeypatch.setattr(importlib, "import_module", lambda _name: _FakeModule)
    adapter = PhonikudAdapter(model_path="J:/fake/model", enabled=True)
    report = adapter.health_check(["שלום"])

    assert report.mode == "real_inference"
    assert report.status == "ok"
    assert report.samples[0]["output"] == "שלום_nikud"


def test_phonikud_adapter_reports_fallback(monkeypatch):
    class _FakeModule:
        @staticmethod
        def add_niqqud(text: str) -> str:
            return text

        @staticmethod
        def get_runtime_mode() -> str:
            return "fallback"

    monkeypatch.setattr(importlib, "import_module", lambda _name: _FakeModule)
    adapter = PhonikudAdapter(model_path="", enabled=True)
    report = adapter.health_check(["תחנה"])

    assert report.mode == "fallback"
    assert report.status == "fallback"
    assert report.samples[0]["output"] == "תחנה"


def test_phonikud_adapter_reports_error_when_import_fails(monkeypatch):
    def _raise(_name: str):
        raise ImportError("phonikud missing")

    monkeypatch.setattr(importlib, "import_module", _raise)
    adapter = PhonikudAdapter(model_path="", enabled=True)
    report = adapter.health_check(["אבג"])

    assert report.mode == "error"
    assert report.status == "error"
    assert "import" in report.details.lower()


def test_phonikud_adapter_clears_runtime_cache_when_model_path_changes(monkeypatch):
    state = {
        "initialized": False,
        "mode": "fallback",
        "details": "not initialized",
        "identity": True,
    }

    def _initialize_from_env():
        if state["initialized"]:
            return
        path = (os.getenv("PHONIKUD_MODEL_PATH") or "").strip()
        if "bad-model-path" in path:
            state["mode"] = "error"
            state["details"] = "invalid model path"
            state["identity"] = True
        else:
            state["mode"] = "real_inference"
            state["details"] = "model loaded"
            state["identity"] = False
        state["initialized"] = True

    def _add_niqqud(text: str) -> str:
        _initialize_from_env()
        if state["identity"]:
            return text
        return f"{text}_nikud"

    def _get_runtime_mode() -> str:
        return state["mode"]

    def _get_runtime_details() -> str:
        return state["details"]

    def _reset_runtime_cache() -> None:
        state["initialized"] = False
        state["mode"] = "fallback"
        state["details"] = "cache reset"
        state["identity"] = True

    fake_module = types.SimpleNamespace(
        add_niqqud=_add_niqqud,
        get_runtime_mode=_get_runtime_mode,
        get_runtime_details=_get_runtime_details,
        reset_runtime_cache=_reset_runtime_cache,
    )
    monkeypatch.setattr(importlib, "import_module", lambda _name: fake_module)

    bad = PhonikudAdapter(model_path="J:/Models/phonikud/bad-model-path", enabled=True)
    bad_report = bad.health_check(["שלום"])
    assert bad_report.mode == "error"
    assert bad_report.status == "error"

    good = PhonikudAdapter(model_path="J:/Models/phonikud/phonikud-1.0.int8", enabled=True)
    good_report = good.health_check(["שלום"])
    assert good_report.mode == "real_inference"
    assert good_report.status == "ok"
    assert good_report.samples[0]["output"].endswith("_nikud")


def test_phonikud_adapter_prefers_batch_callable(monkeypatch):
    calls = {"batch": 0, "single": 0}

    class _FakeModule:
        @staticmethod
        def add_niqqud(text: str) -> str:
            calls["single"] += 1
            return f"{text}_single"

        @staticmethod
        def batch_add_niqqud(texts):
            calls["batch"] += 1
            return [f"{text}_batch" for text in texts]

        @staticmethod
        def get_runtime_mode() -> str:
            return "real_inference"

    monkeypatch.setattr(importlib, "import_module", lambda _name: _FakeModule)
    adapter = PhonikudAdapter(model_path="J:/fake/model", enabled=True)
    outputs = adapter.infer(["a", "b"])

    assert outputs["a"] == "a_batch"
    assert outputs["b"] == "b_batch"
    assert calls["batch"] == 1
    assert calls["single"] == 0
