"""Isolation fixtures for smoke/env tests.

These tests must never touch real user AppData paths.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterator

import pytest


def _copy_sqlite_with_sidecars(source_db: Path, target_db: Path) -> None:
    target_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_db, target_db)
    for sidecar_suffix in ("-wal", "-shm"):
        source_sidecar = Path(f"{source_db}{sidecar_suffix}")
        if source_sidecar.exists():
            shutil.copy2(source_sidecar, Path(f"{target_db}{sidecar_suffix}"))


def _set_env_var(key: str, value: str, previous: dict[str, str | None]) -> None:
    previous[key] = os.environ.get(key)
    os.environ[key] = value


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, old_value in previous.items():
        if old_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old_value


@pytest.fixture(scope="session", autouse=True)
def isolate_smoke_environment(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Path]]:
    """Redirect smoke tests to temp paths and a temp DB copy."""
    source_raw = (os.environ.get("SMOKE_DB_PATH") or "").strip()
    if not source_raw:
        pytest.skip(
            "SMOKE_DB_PATH is required for smoke/env gate. "
            "Point it to a source DB; tests will copy it to a temp location."
        )

    source_db = Path(source_raw).expanduser().resolve()
    if not source_db.exists():
        pytest.skip(f"SMOKE_DB_PATH does not exist: {source_db}")

    session_root = tmp_path_factory.mktemp("smoke_env")
    isolated_db = session_root / "db" / source_db.name
    lock_dir = session_root / "locks"
    data_root = session_root / "hdle_data"
    appdata_root = session_root / "appdata"

    lock_dir.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    appdata_root.mkdir(parents=True, exist_ok=True)
    _copy_sqlite_with_sidecars(source_db, isolated_db)

    previous: dict[str, str | None] = {}
    _set_env_var("SMOKE_DB_PATH", str(isolated_db), previous)
    _set_env_var("HDLE_DATA_ROOT", str(data_root), previous)
    _set_env_var("HDLE_MIGRATION_LOCK_DIR", str(lock_dir), previous)
    _set_env_var("LOCALAPPDATA", str(appdata_root), previous)
    _set_env_var("APPDATA", str(appdata_root), previous)
    _set_env_var("HDLE_DEV_MODE", "0", previous)

    try:
        from app.infra.settings import SettingsService

        SettingsService.reset_instance()
    except Exception:
        pass

    try:
        yield {
            "session_root": session_root,
            "source_db": source_db,
            "isolated_db": isolated_db,
            "lock_dir": lock_dir,
            "data_root": data_root,
            "appdata_root": appdata_root,
        }
    finally:
        try:
            from app.services.db_service import DBService

            DBService.shutdown()
        except Exception:
            pass

        try:
            from app.infra.settings import SettingsService

            SettingsService.reset_instance()
        except Exception:
            pass

        lock_path = lock_dir / "migrate.lock"
        if lock_path.exists():
            lock_path.unlink()

        _restore_env(previous)
