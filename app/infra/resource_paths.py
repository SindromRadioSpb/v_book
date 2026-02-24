"""Deterministic application resource paths for runtime and release."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ResourcePathSet:
    """Resolved roots used by runtime resource loaders."""

    data_root: Path
    models_root: Path
    datasets_root: Path
    temp_root: Path
    logs_root: Path
    backups_root: Path


class ResourcePaths:
    """Single source-of-truth for runtime writable resource locations."""

    SETTINGS_KEY_DATA_ROOT = "resources/data_root"
    ENV_KEY_DATA_ROOT = "HDLE_DATA_ROOT"

    @classmethod
    def _default_data_root(cls) -> Path:
        system = platform.system().lower()
        if system == "windows":
            local_app_data = os.getenv("LOCALAPPDATA")
            if local_app_data:
                return Path(local_app_data) / "HDLE"
            return Path.home() / "AppData" / "Local" / "HDLE"
        if system == "darwin":
            return Path.home() / "Library" / "Application Support" / "HDLE"
        return Path.home() / ".local" / "share" / "hdle"

    @classmethod
    def _normalize_root(cls, value: Optional[str]) -> Optional[Path]:
        text = (value or "").strip()
        if not text:
            return None
        cleaned = text.strip("\"'").rstrip(" .")
        if not cleaned:
            return None
        return Path(cleaned).expanduser()

    @classmethod
    def resolve_data_root(cls, settings=None, *, create: bool = True) -> Path:
        """Resolve writable data root from env/settings/defaults."""
        env_override = cls._normalize_root(os.getenv(cls.ENV_KEY_DATA_ROOT))
        settings_override: Optional[Path] = None
        if env_override is None and settings is not None:
            try:
                raw_setting = settings.get_string(cls.SETTINGS_KEY_DATA_ROOT, "")
            except Exception:
                raw_setting = ""
            settings_override = cls._normalize_root(raw_setting)

        data_root = env_override or settings_override or cls._default_data_root()
        if create:
            data_root.mkdir(parents=True, exist_ok=True)
        return data_root

    @classmethod
    def build(cls, settings=None, *, create: bool = True) -> ResourcePathSet:
        data_root = cls.resolve_data_root(settings=settings, create=create)
        models = data_root / "models"
        datasets = data_root / "datasets"
        temp = data_root / "tmp"
        logs = data_root / "logs"
        backups = data_root / "backups"
        if create:
            for path in (models, datasets, temp, logs, backups):
                path.mkdir(parents=True, exist_ok=True)
        return ResourcePathSet(
            data_root=data_root,
            models_root=models,
            datasets_root=datasets,
            temp_root=temp,
            logs_root=logs,
            backups_root=backups,
        )

