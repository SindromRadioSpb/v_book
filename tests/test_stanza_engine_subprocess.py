from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.infra import runtime_torch_bootstrap
from app.infra.nlp_engines import stanza_engine
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


def test_windows_create_stanza_engine_ignores_forced_inprocess_failure(monkeypatch):
    subprocess_engine = object()
    monkeypatch.setenv("HDLE_FORCE_STANZA_INPROCESS_FAILURE", "1")
    monkeypatch.setattr(
        "app.infra.nlp_engines.stanza_engine.SubprocessStanzaEngine",
        lambda use_gpu=False: subprocess_engine,
    )

    assert create_stanza_engine(use_gpu=False) is subprocess_engine


def test_prepare_torch_runtime_paths_registers_frozen_internal_dirs(monkeypatch, tmp_path):
    exe_root = tmp_path / "dist" / "HDLE_Premium"
    internal_root = exe_root / "_internal"
    torch_root = internal_root / "torch"
    torch_lib = torch_root / "lib"
    cuda_bin = tmp_path / "cuda" / "bin"
    for path in (internal_root, torch_root, torch_lib, cuda_bin):
        path.mkdir(parents=True, exist_ok=True)
    (torch_root / "__init__.py").write_text("# stub\n", encoding="utf-8")

    monkeypatch.setattr(runtime_torch_bootstrap.os, "name", "nt")
    monkeypatch.setattr(runtime_torch_bootstrap.sys, "executable", str(exe_root / "HDLE_Premium.exe"))
    monkeypatch.setattr(runtime_torch_bootstrap.sys, "_MEIPASS", str(internal_root), raising=False)
    monkeypatch.setattr(
        runtime_torch_bootstrap.importlib.util,
        "find_spec",
        lambda name: SimpleNamespace(origin=str(torch_root / "__init__.py")) if name == "torch" else None,
    )
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("CUDA_PATH", str(tmp_path / "cuda"))
    monkeypatch.setattr(runtime_torch_bootstrap.sys, "frozen", True, raising=False)

    recorded: list[str] = []
    runtime_torch_bootstrap._TORCH_DLL_HANDLES.clear()
    runtime_torch_bootstrap._TORCH_DLL_KEYS.clear()
    monkeypatch.setattr(
        runtime_torch_bootstrap.os,
        "add_dll_directory",
        lambda path: recorded.append(str(Path(path))) or object(),
        raising=False,
    )

    runtime_torch_bootstrap.prepare_torch_runtime_paths()

    normalized = [str(Path(path)) for path in recorded]
    assert str(internal_root) in normalized
    assert str(torch_root) in normalized
    assert str(torch_lib) in normalized
    assert str(cuda_bin) not in normalized
    assert os.environ["PATH"].split(";")[:4] == [
        str(internal_root),
        str(torch_root),
        str(torch_lib),
        str(exe_root),
    ]


def test_prepare_torch_runtime_paths_preloads_c10_for_frozen_runtime(monkeypatch, tmp_path):
    exe_root = tmp_path / "dist" / "HDLE_Premium"
    internal_root = exe_root / "_internal"
    torch_lib = internal_root / "torch" / "lib"
    torch_lib.mkdir(parents=True, exist_ok=True)
    for dll_name in ("vcruntime140.dll", "msvcp140.dll", "vcruntime140_1.dll"):
        (internal_root / dll_name).write_text("stub", encoding="utf-8")
    (torch_lib / "c10.dll").write_text("stub", encoding="utf-8")

    monkeypatch.setattr(runtime_torch_bootstrap.os, "name", "nt")
    monkeypatch.setattr(runtime_torch_bootstrap.sys, "executable", str(exe_root / "HDLE_Premium.exe"))
    monkeypatch.setattr(runtime_torch_bootstrap.sys, "_MEIPASS", str(internal_root), raising=False)
    monkeypatch.setattr(runtime_torch_bootstrap.sys, "frozen", True, raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(runtime_torch_bootstrap.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(
        runtime_torch_bootstrap.os,
        "add_dll_directory",
        lambda path: object(),
        raising=False,
    )

    loaded: list[tuple[str, str]] = []
    runtime_torch_bootstrap._TORCH_PRELOAD_HANDLES.clear()
    runtime_torch_bootstrap._TORCH_PRELOAD_KEYS.clear()
    monkeypatch.setattr(
        runtime_torch_bootstrap.ctypes,
        "CDLL",
        lambda path: loaded.append(("cdll", str(Path(path)))) or object(),
    )
    monkeypatch.setattr(
        runtime_torch_bootstrap.ctypes,
        "WinDLL",
        lambda path: loaded.append(("windll", str(Path(path)))) or object(),
    )

    result = runtime_torch_bootstrap.prepare_torch_runtime_paths(preload_frozen_torch=True)

    assert result["preload_errors"] == {}
    assert ("cdll", str(internal_root / "vcruntime140.dll")) in loaded
    assert ("cdll", str(internal_root / "msvcp140.dll")) in loaded
    assert ("cdll", str(internal_root / "vcruntime140_1.dll")) in loaded
    assert ("windll", str(torch_lib / "c10.dll")) in loaded

