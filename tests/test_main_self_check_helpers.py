from __future__ import annotations

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
