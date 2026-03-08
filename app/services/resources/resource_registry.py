"""Resource manifest registry and installation status checks."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from app.infra.resource_paths import ResourcePaths
from app.infra.settings import SettingsService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResourceEntry:
    id: str
    display_name: str
    version: str
    type: str
    required: bool
    payload_kind: str
    download_url: str
    size_bytes: int
    checksum: str
    local_install_subdir: str
    filenames: List[str]
    description: str = ""


@dataclass(frozen=True)
class ResourceStatus:
    resource_id: str
    state: str  # installed|missing|corrupted|not_configured
    message: str
    install_paths: List[Path]


class ResourceRegistry:
    """Single source-of-truth for local model/dataset resource state."""

    SETTINGS_KEY_MANIFEST_OVERRIDE = "resources/manifest_path"
    SETTINGS_KEY_DATA_ROOT = ResourcePaths.SETTINGS_KEY_DATA_ROOT

    def __init__(self, *, settings: Optional[SettingsService] = None):
        self.settings = settings or SettingsService.get_instance()

    def resource_paths(self):
        return ResourcePaths.build(settings=self.settings, create=True)

    def manifest_path(self) -> Path:
        override = (self.settings.get_string(self.SETTINGS_KEY_MANIFEST_OVERRIDE, "") or "").strip()
        if override:
            path = Path(override).expanduser()
            if path.exists():
                return path

        try:
            from importlib.resources import files

            return Path(str(files("app.resources").joinpath("resource_manifest.json")))
        except Exception:
            return Path("app/resources/resource_manifest.json").resolve()

    def load_manifest(self) -> Dict[str, object]:
        path = self.manifest_path()
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def list_entries(self) -> List[ResourceEntry]:
        raw = self.load_manifest()
        rows = raw.get("resources", [])
        entries: List[ResourceEntry] = []
        for item in rows if isinstance(rows, list) else []:
            try:
                entries.append(
                    ResourceEntry(
                        id=str(item.get("id") or "").strip(),
                        display_name=str(item.get("display_name") or item.get("id") or "").strip(),
                        version=str(item.get("version") or "").strip(),
                        type=str(item.get("type") or "resource").strip(),
                        required=bool(item.get("required")),
                        payload_kind=str(item.get("payload_kind") or "manual_import").strip(),
                        download_url=str(item.get("download_url") or "").strip(),
                        size_bytes=int(item.get("size_bytes") or 0),
                        checksum=str(item.get("checksum") or "").strip().lower(),
                        local_install_subdir=str(item.get("local_install_subdir") or "").strip(),
                        filenames=[str(v).strip() for v in (item.get("filenames") or []) if str(v).strip()],
                        description=str(item.get("description") or "").strip(),
                    )
                )
            except Exception as exc:
                logger.warning("Skipping invalid resource manifest row: %s", exc)
        return [entry for entry in entries if entry.id]

    def get_entry(self, resource_id: str) -> Optional[ResourceEntry]:
        target = str(resource_id or "").strip()
        if not target:
            return None
        for entry in self.list_entries():
            if entry.id == target:
                return entry
        return None

    def resolve_install_paths(self, entry: ResourceEntry) -> List[Path]:
        base = self.resource_paths().data_root
        subdir = Path(entry.local_install_subdir or ".")
        target_dir = base / subdir
        return [target_dir / name for name in entry.filenames]

    def resolve_bundled_install_paths(self, entry: ResourceEntry) -> List[Path]:
        bundled_root = ResourcePaths.resolve_bundled_resources_root()
        subdir = Path(entry.local_install_subdir or ".")
        target_dir = bundled_root / subdir
        return [target_dir / name for name in entry.filenames]

    def resolve_candidate_install_path_sets(self, entry: ResourceEntry) -> List[List[Path]]:
        candidates: List[List[Path]] = []

        primary = self.resolve_install_paths(entry)
        if primary:
            candidates.append(primary)

        bundled = self.resolve_bundled_install_paths(entry)
        if bundled and bundled != primary:
            candidates.append(bundled)

        return candidates

    def get_status(self, resource_id: str) -> ResourceStatus:
        entry = self.get_entry(resource_id)
        if entry is None:
            return ResourceStatus(
                resource_id=str(resource_id or ""),
                state="not_configured",
                message="Resource not declared in manifest.",
                install_paths=[],
            )

        candidate_sets = self.resolve_candidate_install_path_sets(entry)
        if not candidate_sets:
            return ResourceStatus(entry.id, "not_configured", "No target filenames configured.", [])

        install_paths = candidate_sets[0]
        resolved_paths: List[Path] | None = None
        for path_set in candidate_sets:
            if all(path.exists() for path in path_set):
                resolved_paths = path_set
                break

        if resolved_paths is None:
            if entry.payload_kind == "downloadable" and not entry.download_url:
                msg = "Download URL is not configured."
                return ResourceStatus(entry.id, "not_configured", msg, install_paths)
            flattened = [path for path_set in candidate_sets for path in path_set]
            return ResourceStatus(entry.id, "missing", "Resource files are missing.", flattened)

        if entry.checksum and len(resolved_paths) == 1:
            actual = self._sha256(resolved_paths[0])
            if actual.lower() != entry.checksum.lower():
                return ResourceStatus(
                    entry.id,
                    "corrupted",
                    "Checksum mismatch detected.",
                    resolved_paths,
                )

        return ResourceStatus(entry.id, "installed", "Resource is installed.", resolved_paths)

    def get_all_statuses(self) -> List[ResourceStatus]:
        return [self.get_status(entry.id) for entry in self.list_entries()]

    def install_from_file(self, resource_id: str, source_path: Path, *, overwrite: bool = True) -> ResourceStatus:
        entry = self.get_entry(resource_id)
        if entry is None:
            raise ValueError(f"Unknown resource_id: {resource_id}")
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(source_path)

        install_paths = self.resolve_install_paths(entry)
        if not install_paths:
            raise ValueError(f"Resource has no target paths: {resource_id}")

        target = install_paths[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise FileExistsError(target)

        shutil.copy2(source_path, target)
        return self.get_status(resource_id)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()
