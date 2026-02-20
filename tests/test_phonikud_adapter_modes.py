"""Phonikud adapter mode detection tests."""

from __future__ import annotations

import importlib

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
