from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from app.services.nlp_runtime.runtime_probe import NlpRuntimeProbe


class _Completed:
    def __init__(self, *, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _bootstrap():
    return SimpleNamespace(
        ok=True,
        model_present=True,
        model_path=Path("C:/managed/stanza_resources/he"),
        to_dict=lambda: {
            "ok": True,
            "model_present": True,
            "model_path": "C:/managed/stanza_resources/he",
        },
    )


def test_probe_stanza_uses_subprocess_payload(monkeypatch):
    payload = {
        "package_installed": True,
        "model_present": True,
        "pipeline_init_ok": False,
        "smoke_ok": False,
        "cuda_available": False,
        "engine_version": "1.11.1",
        "model_path": "C:/models/he",
        "smoke_requested": True,
        "error_code": "hostile_torch_state",
        "error_detail": "WinError 1114",
    }

    monkeypatch.setattr(
        "app.services.nlp_runtime.runtime_probe.ManagedStanzaRuntime.bootstrap_runtime",
        lambda self, force_repair=False: _bootstrap(),
    )
    monkeypatch.setattr(
        "app.services.nlp_runtime.runtime_probe.ManagedStanzaRuntime.build_probe_command",
        lambda self: ["python", "-m", "app.main", "--stanza-probe"],
    )
    monkeypatch.setattr(
        "app.services.nlp_runtime.runtime_probe.ManagedStanzaRuntime.build_runtime_env",
        lambda self, use_gpu=False, run_smoke=False: {},
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: _Completed(stdout=json.dumps(payload, ensure_ascii=False) + "\n"),
    )

    status = NlpRuntimeProbe().probe_stanza(use_gpu=False, run_smoke=True)

    assert status.error_code == "hostile_torch_state"
    assert status.package_installed is True
    assert status.effective_engine_id is None
    assert "DLL initialization" in status.remediation or "Torch failed" in status.remediation


def test_probe_stanza_timeout_becomes_machine_readable_status(monkeypatch):
    monkeypatch.setattr(
        "app.services.nlp_runtime.runtime_probe.ManagedStanzaRuntime.bootstrap_runtime",
        lambda self, force_repair=False: _bootstrap(),
    )
    monkeypatch.setattr(
        "app.services.nlp_runtime.runtime_probe.ManagedStanzaRuntime.build_probe_command",
        lambda self: ["python", "-m", "app.main", "--stanza-probe"],
    )
    monkeypatch.setattr(
        "app.services.nlp_runtime.runtime_probe.ManagedStanzaRuntime.build_runtime_env",
        lambda self, use_gpu=False, run_smoke=False: {},
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="probe", timeout=45)),
    )

    status = NlpRuntimeProbe().probe_stanza(use_gpu=False, run_smoke=True)

    assert status.error_code == "probe_timeout"
    assert status.effective_engine_id is None
    assert "timed out" in status.remediation.lower() or "timed out" in (status.error_detail or "").lower()


def test_probe_stanza_packaged_mode_changes_package_missing_remediation(monkeypatch):
    payload = {
        "package_installed": False,
        "model_present": False,
        "pipeline_init_ok": False,
        "smoke_ok": False,
        "cuda_available": False,
        "engine_version": None,
        "model_path": None,
        "smoke_requested": True,
        "error_code": "package_missing",
        "error_detail": "No module named stanza",
    }

    monkeypatch.setattr(
        "app.services.nlp_runtime.runtime_probe.ManagedStanzaRuntime.bootstrap_runtime",
        lambda self, force_repair=False: _bootstrap(),
    )
    monkeypatch.setattr(
        "app.services.nlp_runtime.runtime_probe.ManagedStanzaRuntime.build_probe_command",
        lambda self: ["app.exe", "--stanza-probe"],
    )
    monkeypatch.setattr(
        "app.services.nlp_runtime.runtime_probe.ManagedStanzaRuntime.build_runtime_env",
        lambda self, use_gpu=False, run_smoke=False: {},
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: _Completed(stdout=json.dumps(payload, ensure_ascii=False) + "\n"),
    )
    monkeypatch.setattr(
        "app.services.nlp_runtime.runtime_probe.ManagedStanzaRuntime.is_packaged_runtime",
        staticmethod(lambda: True),
    )

    status = NlpRuntimeProbe().probe_stanza(use_gpu=False, run_smoke=True)

    assert status.error_code == "package_missing"
    assert "Packaged mode detected" in status.remediation


def test_guided_repair_plan_routes_runtime_failures():
    probe = NlpRuntimeProbe()
    status = probe.build_mock_status(error_code="hostile_torch_state", error_detail="WinError 1114")
    status = type(status)(
        configured_engine_id="stanza",
        effective_engine_id=None,
        package_installed=True,
        model_present=False,
        pipeline_init_ok=False,
        smoke_ok=False,
        cuda_available=False,
        runtime_mode="cpu",
        fallback_used=False,
        error_code="hostile_torch_state",
        error_detail="WinError 1114",
        remediation="Inspect runtime.",
        engine_version=None,
        model_id="he/tokenize,pos,lemma",
        model_path=None,
    )

    plan = probe.build_guided_repair_plan(status)

    assert plan["route"] == "runtime"
    assert "Health Check" in plan["next_action"]


def test_guided_repair_plan_routes_model_failures_to_resource():
    probe = NlpRuntimeProbe()
    status = type(probe.build_mock_status())(
        configured_engine_id="stanza",
        effective_engine_id=None,
        package_installed=True,
        model_present=False,
        pipeline_init_ok=False,
        smoke_ok=False,
        cuda_available=False,
        runtime_mode="cpu",
        fallback_used=False,
        error_code="model_missing",
        error_detail="missing",
        remediation="Import model.",
        engine_version="1.11.1",
        model_id="he/tokenize,pos,lemma",
        model_path="C:/models/he",
    )

    plan = probe.build_guided_repair_plan(status)

    assert plan["route"] == "resource"
    assert "Managed Hebrew Resource" in plan["next_action"]


def test_build_setup_steps_mentions_official_runtime_repair():
    probe = NlpRuntimeProbe()
    status = type(probe.build_mock_status())(
        configured_engine_id="stanza",
        effective_engine_id=None,
        package_installed=True,
        model_present=False,
        pipeline_init_ok=False,
        smoke_ok=False,
        cuda_available=False,
        runtime_mode="cpu",
        fallback_used=False,
        error_code="model_missing",
        error_detail="missing",
        remediation="Import model.",
        engine_version="1.11.1",
        model_id="he/tokenize,pos,lemma",
        model_path="C:/managed/stanza_resources/he",
    )

    steps = probe.build_setup_steps(status)

    assert any("Install / Repair NLP Runtime" in step for step in steps)
