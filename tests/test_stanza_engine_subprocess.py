from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.infra.nlp_engines.base import Sentence
from app.infra.nlp_engines.stanza_engine import SubprocessStanzaEngine, create_stanza_engine


class _FakeReadable:
    def __init__(self, lines: list[str]):
        self._lines = list(lines)

    def readline(self) -> str:
        if self._lines:
            return self._lines.pop(0)
        return ""

    def read(self) -> str:
        if not self._lines:
            return ""
        text = "".join(self._lines)
        self._lines.clear()
        return text


class _FakeWritable:
    def __init__(self):
        self.writes: list[str] = []
        self.flush_calls = 0

    def write(self, value: str) -> int:
        self.writes.append(value)
        return len(value)

    def flush(self) -> None:
        self.flush_calls += 1


class _FakeProcess:
    def __init__(self, stdout_lines: list[str], stderr_lines: list[str] | None = None):
        self.stdin = _FakeWritable()
        self.stdout = _FakeReadable(stdout_lines)
        self.stderr = _FakeReadable(stderr_lines or [])
        self._poll = None
        self.terminate_called = False
        self.kill_called = False
        self.wait_calls: list[int] = []

    def poll(self):
        return self._poll

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        self._poll = 0
        return 0

    def terminate(self):
        self.terminate_called = True
        self._poll = 0

    def kill(self):
        self.kill_called = True
        self._poll = -9


def _bootstrap_result(*, model_present: bool = True):
    return SimpleNamespace(
        model_present=model_present,
        model_path=Path("C:/managed/stanza_resources/he"),
        resources_root=Path("C:/managed/stanza_resources"),
    )


def test_create_stanza_engine_falls_back_to_subprocess(monkeypatch):
    subprocess_engine = object()

    monkeypatch.setattr(
        "app.infra.nlp_engines.stanza_engine.StanzaEngine",
        lambda use_gpu=False: (_ for _ in ()).throw(OSError("WinError 1114")),
    )
    monkeypatch.setattr(
        "app.infra.nlp_engines.stanza_engine.SubprocessStanzaEngine",
        lambda use_gpu=False: subprocess_engine,
    )

    assert create_stanza_engine(use_gpu=False) is subprocess_engine


def test_subprocess_stanza_engine_processes_json_protocol(monkeypatch):
    handshake = json.dumps({"ok": True, "name": "stanza", "version": "1.11.1"}) + "\n"
    response = (
        json.dumps(
            {
                "ok": True,
                "sentences": [
                    {
                        "text": "הילד קורא ספר.",
                        "tokens": [
                            {
                                "text": "הילד",
                                "lemma": "ילד",
                                "pos": "NOUN",
                                "morph": "Gender=Masc|Number=Sing",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n"
    )
    fake_process = _FakeProcess([handshake, response])

    monkeypatch.setattr(
        "app.infra.nlp_engines.stanza_engine.subprocess.Popen",
        lambda *args, **kwargs: fake_process,
    )
    monkeypatch.setattr(
        "app.infra.nlp_engines.stanza_engine.ManagedStanzaRuntime.bootstrap_runtime",
        lambda self, force_repair=False: _bootstrap_result(),
    )
    monkeypatch.setattr(
        "app.infra.nlp_engines.stanza_engine.ManagedStanzaRuntime.build_runtime_env",
        lambda self, use_gpu=False, run_smoke=False: {"STANZA_RESOURCES_DIR": "C:/managed/stanza_resources"},
    )
    monkeypatch.setattr(
        "app.infra.nlp_engines.stanza_engine.ManagedStanzaRuntime.build_worker_command",
        lambda self: ["python", "-m", "app.main", "--stanza-worker"],
    )

    engine = SubprocessStanzaEngine(use_gpu=False)
    sentences = engine.process("הילד קורא ספר.")

    assert engine.get_name() == "stanza"
    assert engine.get_version() == "1.11.1"
    assert isinstance(sentences[0], Sentence)
    assert sentences[0].tokens[0].lemma == "ילד"
    request = json.loads(fake_process.stdin.writes[0].strip())
    assert request["command"] == "process"
    assert request["text"] == "הילד קורא ספר."

    engine.close()
    shutdown = json.loads(fake_process.stdin.writes[-1].strip())
    assert shutdown["command"] == "shutdown"


def test_create_stanza_engine_reports_both_failures(monkeypatch):
    monkeypatch.setattr(
        "app.infra.nlp_engines.stanza_engine.SubprocessStanzaEngine",
        lambda use_gpu=False: (_ for _ in ()).throw(RuntimeError("worker failed")),
    )
    monkeypatch.setattr(
        "app.infra.nlp_engines.stanza_engine.StanzaEngine",
        lambda use_gpu=False: (_ for _ in ()).throw(OSError("WinError 1114")),
    )

    with pytest.raises(RuntimeError, match="Managed Stanza subprocess runtime and in-process fallback both failed"):
        create_stanza_engine(use_gpu=False)


def test_subprocess_stanza_engine_requires_managed_model(monkeypatch):
    monkeypatch.setattr(
        "app.infra.nlp_engines.stanza_engine.ManagedStanzaRuntime.bootstrap_runtime",
        lambda self, force_repair=False: _bootstrap_result(model_present=False),
    )

    with pytest.raises(RuntimeError, match="missing the Hebrew model resources"):
        SubprocessStanzaEngine(use_gpu=False)
