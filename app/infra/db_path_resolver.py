"""Deterministic runtime database path resolution and validation helpers."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from app.infra.resource_paths import ResourcePaths

SETTINGS_KEY_ACTIVE_DB_PATH = "app/active_db_path"
ENV_KEY_DB_PATH = "HDLE_DB_PATH"

DEV_HEWIKI_BASELINE_DB_PATH = Path(
    r"J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db"
)


@dataclass(frozen=True)
class ResolvedDBPath:
    path: Path
    source: str  # CLI|ENV|SETTINGS|DEFAULT


@dataclass(frozen=True)
class DBPathInfo:
    path: Path
    exists: bool
    size_bytes: int
    schema_version: Optional[int]
    supported_schema_version: int
    error: str = ""


def _normalize_path(raw_value: Optional[str]) -> Optional[Path]:
    text = str(raw_value or "").strip()
    if not text:
        return None
    cleaned = text.strip("\"'").strip()
    if not cleaned:
        return None
    return Path(cleaned).expanduser().resolve()


def get_default_db_path(*, settings=None, resource_paths_cls=ResourcePaths) -> Path:
    data_root = resource_paths_cls.resolve_data_root(settings=settings, create=True)
    return (data_root / "hdle.db").resolve()


def resolve_db_path(
    cli_db_path: Optional[str],
    *,
    env: Optional[Mapping[str, str]] = None,
    settings=None,
    resource_paths_cls=ResourcePaths,
) -> ResolvedDBPath:
    env_map = env if env is not None else os.environ

    cli_path = _normalize_path(cli_db_path)
    if cli_path is not None:
        return ResolvedDBPath(path=cli_path, source="CLI")

    env_path = _normalize_path(env_map.get(ENV_KEY_DB_PATH, ""))
    if env_path is not None and env_path.exists() and env_path.is_file():
        return ResolvedDBPath(path=env_path, source="ENV")

    settings_path = None
    if settings is not None:
        try:
            settings_path = _normalize_path(settings.get_string(SETTINGS_KEY_ACTIVE_DB_PATH, ""))
        except Exception:
            settings_path = None
    if settings_path is not None and settings_path.exists() and settings_path.is_file():
        return ResolvedDBPath(path=settings_path, source="SETTINGS")

    default_path = get_default_db_path(settings=settings, resource_paths_cls=resource_paths_cls)
    return ResolvedDBPath(path=default_path, source="DEFAULT")


def discover_baseline_db_path() -> Optional[Path]:
    candidate = DEV_HEWIKI_BASELINE_DB_PATH.resolve()
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def classify_db_profile(path: Path, *, settings=None, resource_paths_cls=ResourcePaths) -> str:
    resolved = Path(path).resolve()
    default_path = get_default_db_path(settings=settings, resource_paths_cls=resource_paths_cls)
    baseline_path = discover_baseline_db_path()
    if resolved == default_path:
        return "Default"
    if baseline_path is not None and resolved == baseline_path:
        return "Baseline (dev)"
    return "Custom"


def get_supported_schema_version() -> int:
    migrations_dir = Path(__file__).parent / "migrations"
    version = 0
    for sql_file in migrations_dir.glob("*.sql"):
        try:
            parsed = int(sql_file.name.split("_", 1)[0])
        except (ValueError, IndexError):
            continue
        if parsed > version:
            version = parsed
    return version


def inspect_db_path(path: Path) -> DBPathInfo:
    target = Path(path).resolve()
    if not target.exists():
        return DBPathInfo(
            path=target,
            exists=False,
            size_bytes=0,
            schema_version=None,
            supported_schema_version=get_supported_schema_version(),
            error="Database file does not exist.",
        )
    if not target.is_file():
        return DBPathInfo(
            path=target,
            exists=False,
            size_bytes=0,
            schema_version=None,
            supported_schema_version=get_supported_schema_version(),
            error="Selected path is not a file.",
        )

    schema_version: Optional[int] = None
    error = ""
    try:
        with sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=2.0) as conn:
            row = conn.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            if row and row[0] is not None:
                schema_version = int(row[0])
    except Exception as exc:
        error = str(exc)

    return DBPathInfo(
        path=target,
        exists=True,
        size_bytes=target.stat().st_size,
        schema_version=schema_version,
        supported_schema_version=get_supported_schema_version(),
        error=error,
    )

