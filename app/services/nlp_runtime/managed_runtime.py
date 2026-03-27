"""Managed application-owned runtime paths for Stanza processing."""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.infra.resource_paths import ResourcePaths
from app.infra.settings import SettingsService


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class ManagedRuntimeBootstrapResult:
    ok: bool
    runtime_root: Path
    resources_root: Path
    model_path: Path
    manifest_path: Path
    ownership: str
    source_kind: str
    source_path: str | None
    model_present: bool
    runtime_command: list[str]
    probe_command: list[str]
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": bool(self.ok),
            "runtime_root": str(self.runtime_root),
            "resources_root": str(self.resources_root),
            "model_path": str(self.model_path),
            "manifest_path": str(self.manifest_path),
            "ownership": self.ownership,
            "source_kind": self.source_kind,
            "source_path": self.source_path,
            "model_present": bool(self.model_present),
            "runtime_command": list(self.runtime_command),
            "probe_command": list(self.probe_command),
            "message": self.message,
        }


class ManagedStanzaRuntime:
    """Application-owned runtime/bootstrap contract for Stanza subprocess paths."""

    SETTINGS_KEY_MANAGED_RUNTIME_ROOT = "nlp_runtime/managed_root"

    def __init__(self, *, settings: SettingsService | None = None):
        self.settings = settings or SettingsService.get_instance()

    def runtime_root(self) -> Path:
        explicit = (self.settings.get_string(self.SETTINGS_KEY_MANAGED_RUNTIME_ROOT, "") or "").strip()
        if explicit:
            root = Path(explicit).expanduser()
        else:
            root = ResourcePaths.build(settings=self.settings, create=True).data_root / "nlp_runtime"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def resources_root(self) -> Path:
        root = self.runtime_root() / "stanza_resources"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def model_path(self) -> Path:
        return self.resources_root() / "he"

    def manifest_path(self) -> Path:
        return self.runtime_root() / "runtime_manifest.json"

    def ownership(self) -> str:
        return "packaged_app" if self.is_packaged_runtime() else "development_app"

    @staticmethod
    def is_packaged_runtime() -> bool:
        return bool(getattr(sys, "frozen", False))

    def build_worker_command(self) -> list[str]:
        if self.is_packaged_runtime():
            return [str(Path(sys.executable).resolve()), "--stanza-worker"]
        return [sys.executable, "-u", "-m", "app.main", "--stanza-worker"]

    def build_probe_command(self) -> list[str]:
        if self.is_packaged_runtime():
            return [str(Path(sys.executable).resolve()), "--stanza-probe"]
        return [sys.executable, "-u", "-m", "app.main", "--stanza-probe"]

    def build_runtime_env(self, *, use_gpu: bool = False, run_smoke: bool = False) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["HDLE_STANZA_WORKER_MODE"] = "gpu" if use_gpu else "cpu"
        env["HDLE_STANZA_PROBE_MODE"] = "gpu" if use_gpu else "cpu"
        env["HDLE_STANZA_PROBE_SMOKE"] = "1" if run_smoke else "0"
        env["STANZA_RESOURCES_DIR"] = str(self.resources_root())
        return env

    def bootstrap_runtime(self, *, force_repair: bool = False) -> ManagedRuntimeBootstrapResult:
        runtime_root = self.runtime_root()
        resources_root = self.resources_root()
        model_path = self.model_path()
        manifest_path = self.manifest_path()

        source_kind = "missing"
        source_path: str | None = None

        if model_path.exists() and self._dir_has_contents(model_path) and not force_repair:
            source_kind = "managed_existing"
        else:
            if model_path.exists() and force_repair:
                shutil.rmtree(model_path, ignore_errors=True)

            source = self._resolve_bootstrap_source()
            if source is not None:
                source_kind, source_dir = source
                source_path = str(source_dir)
                self._copy_model_tree(source_dir, model_path)

        model_present = model_path.exists() and self._dir_has_contents(model_path)
        message = (
            "Managed Stanza runtime is ready."
            if model_present
            else "Managed Stanza runtime is missing the Hebrew model resources."
        )

        payload = {
            "schema_version": 1,
            "updated_at_utc": _utc_now_iso(),
            "ownership": self.ownership(),
            "runtime_root": str(runtime_root),
            "resources_root": str(resources_root),
            "model_path": str(model_path),
            "model_present": bool(model_present),
            "model_source_kind": source_kind,
            "model_source_path": source_path,
            "runtime_command": self.build_worker_command(),
            "probe_command": self.build_probe_command(),
            "runtime_executable": str(Path(sys.executable).resolve()),
        }
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        return ManagedRuntimeBootstrapResult(
            ok=bool(model_present),
            runtime_root=runtime_root,
            resources_root=resources_root,
            model_path=model_path,
            manifest_path=manifest_path,
            ownership=self.ownership(),
            source_kind=source_kind,
            source_path=source_path,
            model_present=bool(model_present),
            runtime_command=self.build_worker_command(),
            probe_command=self.build_probe_command(),
            message=message,
        )

    def load_manifest(self) -> dict[str, Any] | None:
        path = self.manifest_path()
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def detect_best_model_path(self) -> str | None:
        managed = self.model_path()
        if managed.exists() and self._dir_has_contents(managed):
            return str(managed)

        source = self._resolve_bootstrap_source(include_managed=False)
        if source is not None:
            return str(source[1])
        return None

    def _resolve_bootstrap_source(self, *, include_managed: bool = True) -> tuple[str, Path] | None:
        candidates: list[tuple[str, Path]] = []

        if include_managed:
            managed = self.model_path()
            if managed.exists() and self._dir_has_contents(managed):
                candidates.append(("managed_existing", managed))

        for candidate in self._bundled_model_candidates():
            if candidate.exists() and self._dir_has_contents(candidate):
                candidates.append(("bundled", candidate))

        for candidate in self._legacy_model_candidates():
            if candidate.exists() and self._dir_has_contents(candidate):
                candidates.append(("legacy", candidate))

        return candidates[0] if candidates else None

    def _bundled_model_candidates(self) -> list[Path]:
        bundled_root = ResourcePaths.resolve_bundled_resources_root()
        return [
            bundled_root / "stanza_resources" / "he",
            bundled_root / "models" / "stanza" / "he",
            bundled_root / "nlp_runtime" / "stanza_resources" / "he",
        ]

    def _legacy_model_candidates(self) -> list[Path]:
        candidates: list[Path] = []
        explicit = os.getenv("STANZA_RESOURCES_DIR", "").strip()
        if explicit:
            explicit_root = Path(explicit)
            candidates.append(explicit_root / "he")
            candidates.append(explicit_root)

        candidates.append(Path.home() / "stanza_resources" / "he")

        local_appdata = os.getenv("LOCALAPPDATA", "").strip()
        if local_appdata:
            cache_root = Path(local_appdata) / "StanfordNLP" / "stanza" / "Cache"
            if cache_root.exists():
                for version_dir in sorted(cache_root.iterdir(), reverse=True):
                    if version_dir.is_dir():
                        candidates.append(version_dir / "resources" / "he")
        return candidates

    @staticmethod
    def _copy_model_tree(source_dir: Path, target_dir: Path) -> None:
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        shutil.copytree(source_dir, target_dir)

    @staticmethod
    def _dir_has_contents(path: Path) -> bool:
        if not path.exists() or not path.is_dir():
            return False
        return any(path.iterdir())
