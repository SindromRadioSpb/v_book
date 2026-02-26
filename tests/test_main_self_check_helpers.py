from __future__ import annotations

import io
import json
import sys
import builtins
import importlib
from pathlib import Path
from types import SimpleNamespace

import app.main as main


class _DummySettings:
    def __init__(self, values: dict[str, object] | None = None):
        self.values = values or {}

    def get_string(self, key: str, default: str = "") -> str:
        return str(self.values.get(key, default))

    def get_int(self, key: str, default: int = 0) -> int:
        return int(self.values.get(key, default))

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.values.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)


def test_is_phonikud_subprocess_script_detects_known_pattern():
    snippet = (
        "import json,sys\n"
        "from phonikud_onnx import Phonikud\n"
        "raw=sys.stdin.read() or '{}'\n"
        "data=json.loads(raw)\n"
        "model=Phonikud(str(data.get('model_path') or ''))\n"
        "outputs=[]\n"
        "outputs.append(model.add_diacritics('שלום'))\n"
    )
    assert main._is_phonikud_subprocess_script(snippet) is True


def test_is_phonikud_subprocess_script_rejects_unrelated_snippet():
    snippet = "print('hello world')"
    assert main._is_phonikud_subprocess_script(snippet) is False


def test_handle_embedded_python_compat_routes_known_script(monkeypatch):
    snippet = "from phonikud_onnx import Phonikud; json.loads('{}'); outputs=[]; model.add_diacritics('a')"
    monkeypatch.setattr(main, "_run_phonikud_subprocess_bridge", lambda: 7)

    result = main._handle_embedded_python_compat(["HDLE_Premium.exe", "-c", snippet])
    assert result == 7


def test_run_phonikud_subprocess_bridge_uses_identity_fallback_on_backend_error(monkeypatch):
    class _BrokenPhonikud:
        def __init__(self, _model_path: str):
            raise RuntimeError("DLL load failed while importing onnxruntime_pybind11_state")

    monkeypatch.setitem(sys.modules, "phonikud_onnx", SimpleNamespace(Phonikud=_BrokenPhonikud))
    monkeypatch.setitem(sys.modules, "phonikud", SimpleNamespace(prepare_runtime_dll_paths=lambda: None))
    monkeypatch.setattr(
        main.sys,
        "stdin",
        io.StringIO(json.dumps({"model_path": "C:/models/phonikud.onnx", "texts": ["a", "b"]})),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    monkeypatch.setattr(main.sys, "stdout", stdout)
    monkeypatch.setattr(main.sys, "stderr", stderr)

    result = main._run_phonikud_subprocess_bridge()
    payload = json.loads(stdout.getvalue())
    assert result == 0
    assert payload["outputs"] == ["a", "b"]
    assert "identity fallback" in stderr.getvalue().lower()


def test_run_phonikud_subprocess_bridge_reads_utf8_buffer_and_emits_ascii_safe_json(monkeypatch):
    class _FakePhonikud:
        def __init__(self, _model_path: str):
            pass

        def add_diacritics(self, text: str) -> str:
            return "\u05e9\u05b8\u05c1\u05dc\u05d5\u05b9\u05dd" if text == "\u05e9\u05dc\u05d5\u05dd" else text

    class _FakeStdin:
        def __init__(self, payload_bytes: bytes):
            self.buffer = io.BytesIO(payload_bytes)

        def read(self) -> str:
            return ""

    monkeypatch.setitem(sys.modules, "phonikud_onnx", SimpleNamespace(Phonikud=_FakePhonikud))
    monkeypatch.setitem(sys.modules, "phonikud", SimpleNamespace(prepare_runtime_dll_paths=lambda: None))
    payload = json.dumps(
        {"model_path": "C:/models/phonikud.onnx", "texts": ["\u05e9\u05dc\u05d5\u05dd"]},
        ensure_ascii=False,
    ).encode("utf-8")
    monkeypatch.setattr(main.sys, "stdin", _FakeStdin(payload))
    stdout = io.StringIO()
    stderr = io.StringIO()
    monkeypatch.setattr(main.sys, "stdout", stdout)
    monkeypatch.setattr(main.sys, "stderr", stderr)

    result = main._run_phonikud_subprocess_bridge()
    rendered_json = stdout.getvalue()
    parsed = json.loads(rendered_json)

    assert result == 0
    assert parsed["outputs"][0] == "\u05e9\u05b8\u05c1\u05dc\u05d5\u05b9\u05dd"
    assert "\\u05" in rendered_json
    assert stderr.getvalue() == ""


def test_load_service_account_file_rejects_api_key_text(tmp_path: Path):
    path = tmp_path / "api_key.txt"
    path.write_text("AIza-not-a-service-account-json", encoding="utf-8")

    data, status = main._load_service_account_file(path)
    assert data is None
    assert status.startswith("invalid_json:")


def test_load_service_account_info_prefers_env_path(monkeypatch, tmp_path: Path):
    sa_path = tmp_path / "service_account.json"
    sa_path.write_text(
        (
            "{\n"
            '  "type": "service_account",\n'
            '  "project_id": "proj-123",\n'
            '  "client_email": "svc@example.iam.gserviceaccount.com"\n'
            "}\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HDLE_GCP_SA_JSON_PATH", str(sa_path))

    data, source = main._load_service_account_info_from_env_or_paths(_DummySettings())
    assert data is not None
    assert data["project_id"] == "proj-123"
    assert source == "env:HDLE_GCP_SA_JSON_PATH"


def test_load_service_account_from_env_key_not_set(monkeypatch):
    monkeypatch.delenv("HDLE_GCP_TRANSLATE_SA_JSON_PATH", raising=False)
    data, source = main._load_service_account_from_env_key("HDLE_GCP_TRANSLATE_SA_JSON_PATH")
    assert data is None
    assert source == "not_set"


def test_candidate_db_paths_default_then_active(monkeypatch, tmp_path: Path):
    default_db = (tmp_path / "default.db").resolve()
    active_db = (tmp_path / "active.db").resolve()

    monkeypatch.setattr(main, "get_default_db_path", lambda settings=None: default_db)
    monkeypatch.setattr(
        main,
        "resolve_db_path",
        lambda arg, settings=None: SimpleNamespace(path=active_db, source="SETTINGS"),
    )

    result = main._candidate_db_paths_for_credentials(_DummySettings(), None)
    assert result == [default_db, active_db]


def test_candidate_db_paths_cli_override(monkeypatch, tmp_path: Path):
    cli_db = (tmp_path / "cli.db").resolve()

    monkeypatch.setattr(
        main,
        "resolve_db_path",
        lambda arg, settings=None: SimpleNamespace(path=cli_db, source="CLI"),
    )

    result = main._candidate_db_paths_for_credentials(_DummySettings(), "ignored.db")
    assert result == [cli_db]


def test_main_self_check_path_skips_heavy_ui_imports(monkeypatch):
    original_import = builtins.__import__

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "app.ui.app_window":
            raise AssertionError("UI module import must not run for --self-check")
        return original_import(name, globals, locals, fromlist, level)

    captured = {}

    monkeypatch.setattr(builtins, "__import__", _guarded_import)
    monkeypatch.setattr(main.sys, "argv", ["prog", "--self-check", "import"])
    monkeypatch.setattr(main, "run_self_check", lambda mode, db_path_arg=None: (0, {"mode": mode, "ok": True}))
    monkeypatch.setattr(
        main,
        "_emit_self_check",
        lambda payload, out_path=None: captured.update({"payload": payload, "out_path": out_path}),
    )

    exit_code = main.main()
    assert exit_code == 0
    assert captured["payload"]["mode"] == "import"
    assert captured["payload"]["ok"] is True


def test_import_self_check_uses_frozen_onnx_helper(monkeypatch):
    real_import = importlib.import_module
    imported = []

    def _fake_import(name: str):
        imported.append(name)
        if name == "phonikud":
            return SimpleNamespace(__name__="phonikud", __version__="test")
        if name == "onnxruntime":
            raise AssertionError("Frozen import self-check must use helper instead of in-process onnxruntime import")
        return real_import(name)

    monkeypatch.setattr(main.importlib, "import_module", _fake_import)
    monkeypatch.setattr(main.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        main,
        "_run_frozen_onnx_probe_helper",
        lambda **_kwargs: (
            0,
            {
                "ok": True,
                "stage": "import",
                "error": "",
                "helper_path": "C:/HDLE_ONNX_Probe.exe",
                "onnxruntime_origin": "C:/onnxruntime/__init__.py",
                "exit_code": 0,
            },
        ),
    )

    exit_code, payload = main._run_import_self_check(_DummySettings())
    check = payload["checks"]["onnxruntime_import"]

    assert exit_code == 0
    assert check["ok"] is True
    assert check["helper_path"] == "C:/HDLE_ONNX_Probe.exe"
    assert "onnxruntime" in check["origin"].lower()
    assert "onnxruntime" not in imported


def test_import_self_check_reports_helper_failure(monkeypatch):
    monkeypatch.setattr(main.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        main,
        "_run_frozen_onnx_probe_helper",
        lambda **_kwargs: (
            1,
            {
                "ok": False,
                "stage": "import",
                "error": "DLL initialization routine failed",
                "helper_path": "C:/HDLE_ONNX_Probe.exe",
                "exit_code": 1,
            },
        ),
    )

    exit_code, payload = main._run_import_self_check(_DummySettings())
    check = payload["checks"]["onnxruntime_import"]

    assert exit_code == 1
    assert check["ok"] is False
    assert "DLL initialization routine failed" in check["error"]


def test_acquire_app_instance_lock_uses_expected_lockfile(monkeypatch, tmp_path: Path):
    captured = {}

    class _FakeLock:
        def __init__(self, lock_path, timeout_seconds):
            captured["lock_path"] = lock_path
            captured["timeout_seconds"] = timeout_seconds

        def __enter__(self):
            captured["entered"] = True
            return self

        def __exit__(self, *_args):
            return None

    import app.infra.process_lock as process_lock_module

    monkeypatch.setattr(process_lock_module, "ProcessLock", _FakeLock)

    lock, error = main._acquire_app_instance_lock(tmp_path, timeout_seconds=7)
    assert error == ""
    assert lock is not None
    assert captured["entered"] is True
    assert captured["timeout_seconds"] == 7
    assert captured["lock_path"] == (tmp_path.resolve() / "app_instance.lock")


def test_acquire_app_instance_lock_returns_error_when_busy(monkeypatch, tmp_path: Path):
    class _BusyLock:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            raise RuntimeError("app already running")

        def __exit__(self, *_args):
            return None

    import app.infra.process_lock as process_lock_module

    monkeypatch.setattr(process_lock_module, "ProcessLock", _BusyLock)

    lock, error = main._acquire_app_instance_lock(tmp_path)
    assert lock is None
    assert "already running" in error


def test_health_self_check_retries_probe_on_timeout(monkeypatch, tmp_path: Path):
    class _Item:
        def __init__(self, item_id: str, status: str = "ok"):
            self.item_id = item_id
            self.status = status

        def to_dict(self):
            return {
                "id": self.item_id,
                "name": self.item_id,
                "status": self.status,
                "message": "",
                "remediation": "",
            }

    class _FakeHealthCheckService:
        def __init__(self, settings=None):
            self.settings = settings

        def _check_required_resources(self):
            return [_Item("required_resources")]

        def _check_pronunciation_bootstrap(self):
            return _Item("pronunciation_bootstrap")

        def _check_sentence_niqqud_bootstrap(self):
            return _Item("sentence_niqqud_bootstrap")

        def _check_cloud_providers(self):
            return [_Item("cloud_provider", status="optional")]

        def _check_baseline_reference(self):
            return _Item("baseline_reference")

    import app.services.health_check_service as health_module

    monkeypatch.setattr(health_module, "HealthCheckService", _FakeHealthCheckService)
    monkeypatch.setattr(main.os, "name", "nt")
    monkeypatch.setattr(main.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        main,
        "resolve_db_path",
        lambda _arg, settings=None: SimpleNamespace(path=str(tmp_path / "health.db"), source="CLI"),
    )

    calls: list[int] = []

    def _fake_probe_helper(**kwargs):
        calls.append(int(kwargs["timeout_ms"]))
        if len(calls) == 1:
            return 1, {
                "ok": False,
                "stage": "import",
                "mode": "probe",
                "error": "command timed out after 5 seconds",
                "timed_out": True,
            }
        return 0, {
            "ok": True,
            "stage": "infer",
            "mode": "probe",
            "error": "",
        }

    monkeypatch.setattr(main, "_run_frozen_onnx_probe_helper", _fake_probe_helper)

    exit_code, payload = main._run_health_self_check(_DummySettings(), None)

    assert exit_code == 0
    assert calls == [main._FROZEN_ONNX_PROBE_TIMEOUT_MS, main._FROZEN_ONNX_PROBE_RETRY_TIMEOUT_MS]
    assert payload["onnx_probe"]["ok"] is True
    assert payload["onnx_probe"]["retry_attempted"] is True
    assert payload["onnx_probe"]["retry_reason"] == "timeout"
    item = next(item for item in payload["report"]["items"] if item["id"] == "frozen_onnx_probe")
    assert item["status"] == "ok"


def test_health_self_check_does_not_retry_probe_on_non_timeout(monkeypatch, tmp_path: Path):
    class _Item:
        def __init__(self, item_id: str, status: str = "ok"):
            self.item_id = item_id
            self.status = status

        def to_dict(self):
            return {
                "id": self.item_id,
                "name": self.item_id,
                "status": self.status,
                "message": "",
                "remediation": "",
            }

    class _FakeHealthCheckService:
        def __init__(self, settings=None):
            self.settings = settings

        def _check_required_resources(self):
            return [_Item("required_resources")]

        def _check_pronunciation_bootstrap(self):
            return _Item("pronunciation_bootstrap")

        def _check_sentence_niqqud_bootstrap(self):
            return _Item("sentence_niqqud_bootstrap")

        def _check_cloud_providers(self):
            return [_Item("cloud_provider", status="optional")]

        def _check_baseline_reference(self):
            return _Item("baseline_reference")

    import app.services.health_check_service as health_module

    monkeypatch.setattr(health_module, "HealthCheckService", _FakeHealthCheckService)
    monkeypatch.setattr(main.os, "name", "nt")
    monkeypatch.setattr(main.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        main,
        "resolve_db_path",
        lambda _arg, settings=None: SimpleNamespace(path=str(tmp_path / "health.db"), source="CLI"),
    )

    calls: list[int] = []

    def _fake_probe_helper(**kwargs):
        calls.append(int(kwargs["timeout_ms"]))
        return 1, {
            "ok": False,
            "stage": "import",
            "mode": "probe",
            "error": "DLL load failed",
        }

    monkeypatch.setattr(main, "_run_frozen_onnx_probe_helper", _fake_probe_helper)

    exit_code, payload = main._run_health_self_check(_DummySettings(), None)

    assert exit_code == 0
    assert calls == [main._FROZEN_ONNX_PROBE_TIMEOUT_MS]
    assert payload["onnx_probe"]["ok"] is False
    assert payload["onnx_probe"]["retry_attempted"] is False
    item = next(item for item in payload["report"]["items"] if item["id"] == "frozen_onnx_probe")
    assert item["status"] == "error"
