"""Managed application-owned runtime paths for Stanza processing."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.infra.resource_paths import ResourcePaths


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
    bundled_payload_root: str | None
    payload_manifest_path: str | None
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
            "bundled_payload_root": self.bundled_payload_root,
            "payload_manifest_path": self.payload_manifest_path,
            "model_present": bool(self.model_present),
            "runtime_command": list(self.runtime_command),
            "probe_command": list(self.probe_command),
            "message": self.message,
        }


@dataclass(frozen=True)
class _ManagedPayloadSource:
    source_kind: str
    resources_root: Path
    model_path: Path
    payload_root: Path | None = None
    payload_manifest_path: Path | None = None


class ManagedStanzaRuntime:
    """Application-owned runtime/bootstrap contract for Stanza subprocess paths."""

    SETTINGS_KEY_MANAGED_RUNTIME_ROOT = "nlp_runtime/managed_root"
    _REQUIRED_MODEL_ENTRIES = (
        "backward_charlm",
        "forward_charlm",
        "lemma",
        "mwt",
        "pos",
        "pretrain",
        "tokenize",
        "default.zip",
    )

    def __init__(self, *, settings: Any | None = None):
        self.settings = settings

    def runtime_root(self) -> Path:
        explicit = ""
        if self.settings is not None and hasattr(self.settings, "get_string"):
            explicit = str(self.settings.get_string(self.SETTINGS_KEY_MANAGED_RUNTIME_ROOT, "") or "").strip()
        if explicit:
            preferred = Path(explicit).expanduser()
        else:
            preferred = ResourcePaths.build(settings=self.settings, create=True).data_root / "nlp_runtime"
        try:
            preferred.mkdir(parents=True, exist_ok=True)
            return preferred
        except OSError:
            fallback = Path(tempfile.gettempdir()) / "HDLE" / "nlp_runtime"
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback

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
        data_root = str(self.runtime_root().parent)
        env[ResourcePaths.ENV_KEY_DATA_ROOT] = data_root
        return env

    def bootstrap_runtime(self, *, force_repair: bool = False) -> ManagedRuntimeBootstrapResult:
        runtime_root = self.runtime_root()
        resources_root = self.resources_root()
        model_path = self.model_path()
        manifest_path = self.manifest_path()

        manifest_payload = self.load_manifest() or {}
        source_kind = "repaired_managed" if self._managed_runtime_ready(resources_root, model_path) else "missing"
        source_path: str | None = str(model_path) if model_path.exists() else None
        bundled_payload_root: str | None = str(manifest_payload.get("bundled_payload_root") or "") or None
        payload_manifest_path: str | None = str(manifest_payload.get("payload_manifest_path") or "") or None
        runtime_ready = self._managed_runtime_ready(resources_root, model_path)

        if runtime_ready and not force_repair:
            source_kind = str(manifest_payload.get("model_source_kind") or "repaired_managed")
            source_path = str(manifest_payload.get("model_source_path") or source_path or "") or source_path
        else:
            resources_json = resources_root / "resources.json"
            if model_path.exists() and (force_repair or not runtime_ready):
                shutil.rmtree(model_path, ignore_errors=True)
            if resources_json.exists() and (force_repair or not runtime_ready):
                resources_json.unlink(missing_ok=True)

            source = self._resolve_bootstrap_source(include_managed=False)
            if source is not None:
                source_kind = source.source_kind
                source_path = str(source.model_path)
                bundled_payload_root = str(source.payload_root) if source.payload_root else None
                payload_manifest_path = (
                    str(source.payload_manifest_path) if source.payload_manifest_path else None
                )
                self._copy_resources_payload(
                    source_resources_root=source.resources_root,
                    source_model_path=source.model_path,
                    target_resources_root=resources_root,
                )

        resources_json = resources_root / "resources.json"
        model_present = self._managed_runtime_ready(resources_root, model_path)
        message = (
            "Managed Stanza runtime is ready."
            if model_present
            else "Managed Stanza runtime is missing the Hebrew model resources."
        )

        payload = {
            "schema_version": 2,
            "updated_at_utc": _utc_now_iso(),
            "ownership": self.ownership(),
            "runtime_root": str(runtime_root),
            "resources_root": str(resources_root),
            "model_path": str(model_path),
            "model_present": bool(model_present),
            "resources_json_present": bool(resources_json.exists()),
            "model_source_kind": source_kind,
            "model_source_path": source_path,
            "bundled_payload_root": bundled_payload_root,
            "payload_manifest_path": payload_manifest_path,
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
            bundled_payload_root=bundled_payload_root,
            payload_manifest_path=payload_manifest_path,
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
        if self._managed_runtime_ready(self.resources_root(), managed):
            return str(managed)

        source = self._resolve_bootstrap_source(include_managed=False)
        if source is not None:
            return str(source.model_path)
        return None

    def _resolve_bootstrap_source(self, *, include_managed: bool = True) -> _ManagedPayloadSource | None:
        candidates: list[_ManagedPayloadSource] = []

        if include_managed:
            managed = self.model_path()
            if self._managed_runtime_ready(self.resources_root(), managed):
                candidates.append(
                    _ManagedPayloadSource(
                        source_kind="repaired_managed",
                        resources_root=self.resources_root(),
                        model_path=managed,
                    )
                )

        for candidate in self._bundled_model_candidates():
            if self._payload_ready(candidate.resources_root, candidate.model_path):
                candidates.append(candidate)

        for candidate in self._legacy_model_candidates():
            if self._payload_ready(candidate.resources_root, candidate.model_path):
                candidates.append(candidate)

        return candidates[0] if candidates else None

    def _bundled_model_candidates(self) -> list[_ManagedPayloadSource]:
        bundled_root = ResourcePaths.resolve_bundled_resources_root()
        packaged_root = bundled_root / "nlp_runtime" / "stanza_payload"
        repo_root = Path(__file__).resolve().parents[3]
        dev_root = repo_root / "installer" / "resources" / "local_models" / "stanza_hebrew"
        return [
            _ManagedPayloadSource(
                source_kind="bundled_packaged",
                resources_root=packaged_root / "stanza_resources",
                model_path=packaged_root / "stanza_resources" / "he",
                payload_root=packaged_root,
                payload_manifest_path=packaged_root / "payload_manifest.json",
            ),
            _ManagedPayloadSource(
                source_kind="bundled_dev",
                resources_root=dev_root / "stanza_resources",
                model_path=dev_root / "stanza_resources" / "he",
                payload_root=dev_root,
                payload_manifest_path=dev_root / "payload_manifest.json",
            ),
        ]

    def _legacy_model_candidates(self) -> list[_ManagedPayloadSource]:
        candidates: list[_ManagedPayloadSource] = []
        explicit = os.getenv("STANZA_RESOURCES_DIR", "").strip()
        if explicit:
            candidates.extend(self._build_legacy_candidates_from_root(Path(explicit)))

        candidates.extend(self._build_legacy_candidates_from_root(Path.home() / "stanza_resources"))

        local_appdata = os.getenv("LOCALAPPDATA", "").strip()
        if local_appdata:
            cache_root = Path(local_appdata) / "StanfordNLP" / "stanza" / "Cache"
            if cache_root.exists():
                for version_dir in sorted(cache_root.iterdir(), reverse=True):
                    if version_dir.is_dir():
                        candidates.extend(
                            self._build_legacy_candidates_from_root(version_dir / "resources")
                        )
        return candidates

    @staticmethod
    def _copy_resources_payload(
        *,
        source_resources_root: Path,
        source_model_path: Path,
        target_resources_root: Path,
    ) -> None:
        target_resources_root.mkdir(parents=True, exist_ok=True)
        target_model_dir = target_resources_root / "he"
        if target_model_dir.exists():
            shutil.rmtree(target_model_dir, ignore_errors=True)
        shutil.copytree(source_model_path, target_model_dir)

        resources_json = source_resources_root / "resources.json"
        if resources_json.exists():
            shutil.copy2(resources_json, target_resources_root / "resources.json")

    @staticmethod
    def _dir_has_contents(path: Path) -> bool:
        if not path.exists() or not path.is_dir():
            return False
        return any(path.iterdir())

    @classmethod
    def _payload_ready(cls, resources_root: Path, model_path: Path) -> bool:
        resources_json = resources_root / "resources.json"
        if not resources_json.exists():
            return False
        if not cls._dir_has_contents(model_path):
            return False
        return all((model_path / entry).exists() for entry in cls._REQUIRED_MODEL_ENTRIES)

    def _managed_runtime_ready(self, resources_root: Path, model_path: Path) -> bool:
        return self._payload_ready(resources_root, model_path)

    @staticmethod
    def _build_legacy_candidates_from_root(root: Path) -> list[_ManagedPayloadSource]:
        normalized = root.expanduser()
        if normalized.name == "he":
            resources_root = normalized.parent
            model_path = normalized
        else:
            resources_root = normalized
            model_path = normalized / "he"
        return [
            _ManagedPayloadSource(
                source_kind="legacy_cache",
                resources_root=resources_root,
                model_path=model_path,
            )
        ]
