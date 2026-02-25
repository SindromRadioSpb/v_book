"""Tests for deterministic DB path resolution precedence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.infra import db_path_resolver as resolver


@dataclass
class _SettingsStub:
    values: dict

    def get_string(self, key: str, default: str = "") -> str:
        return str(self.values.get(key, default))


class _ResourcePathsStub:
    _root: Path | None = None

    @classmethod
    def resolve_data_root(cls, settings=None, create: bool = True) -> Path:
        assert cls._root is not None
        if create:
            cls._root.mkdir(parents=True, exist_ok=True)
        return cls._root


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_resolve_db_path_prefers_cli(tmp_path):
    cli_db = _touch(tmp_path / "cli.db")
    env_db = _touch(tmp_path / "env.db")
    settings_db = _touch(tmp_path / "settings.db")
    settings = _SettingsStub({resolver.SETTINGS_KEY_ACTIVE_DB_PATH: str(settings_db)})

    _ResourcePathsStub._root = tmp_path / "appdata"
    resolved = resolver.resolve_db_path(
        str(cli_db),
        env={resolver.ENV_KEY_DB_PATH: str(env_db)},
        settings=settings,
        resource_paths_cls=_ResourcePathsStub,
    )

    assert resolved.source == "CLI"
    assert resolved.path == cli_db.resolve()


def test_resolve_db_path_uses_env_if_existing(tmp_path):
    env_db = _touch(tmp_path / "env.db")
    settings_db = _touch(tmp_path / "settings.db")
    settings = _SettingsStub({resolver.SETTINGS_KEY_ACTIVE_DB_PATH: str(settings_db)})

    _ResourcePathsStub._root = tmp_path / "appdata"
    resolved = resolver.resolve_db_path(
        None,
        env={resolver.ENV_KEY_DB_PATH: str(env_db)},
        settings=settings,
        resource_paths_cls=_ResourcePathsStub,
    )

    assert resolved.source == "ENV"
    assert resolved.path == env_db.resolve()


def test_resolve_db_path_falls_back_to_settings_when_env_missing(tmp_path):
    settings_db = _touch(tmp_path / "settings.db")
    settings = _SettingsStub({resolver.SETTINGS_KEY_ACTIVE_DB_PATH: str(settings_db)})

    _ResourcePathsStub._root = tmp_path / "appdata"
    resolved = resolver.resolve_db_path(
        None,
        env={resolver.ENV_KEY_DB_PATH: str(tmp_path / "missing_env.db")},
        settings=settings,
        resource_paths_cls=_ResourcePathsStub,
    )

    assert resolved.source == "SETTINGS"
    assert resolved.path == settings_db.resolve()


def test_resolve_db_path_uses_default_when_settings_missing(tmp_path):
    settings = _SettingsStub({resolver.SETTINGS_KEY_ACTIVE_DB_PATH: str(tmp_path / "missing_settings.db")})
    _ResourcePathsStub._root = tmp_path / "appdata"

    resolved = resolver.resolve_db_path(
        None,
        env={resolver.ENV_KEY_DB_PATH: str(tmp_path / "missing_env.db")},
        settings=settings,
        resource_paths_cls=_ResourcePathsStub,
    )

    assert resolved.source == "DEFAULT"
    assert resolved.path == (tmp_path / "appdata" / "hdle.db").resolve()


def test_discover_baseline_db_path_returns_existing_candidate(tmp_path, monkeypatch):
    baseline_db = _touch(tmp_path / "hewiki_gpu_processing.db")
    monkeypatch.setattr(resolver, "DEV_HEWIKI_BASELINE_DB_PATH", baseline_db)

    discovered = resolver.discover_baseline_db_path()
    assert discovered == baseline_db.resolve()
