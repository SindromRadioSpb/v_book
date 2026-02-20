"""Data Transfer Objects for project exchange."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ExportOptions:
    """Options for project export."""

    include_snapshots: bool = True  # Include project_snapshot table
    include_pronunciation_metadata: bool = False  # Include pronunciation metadata TSV sidecar


@dataclass
class ImportOptions:
    """Options for project import."""

    rename_if_conflict: bool = True  # Auto-rename project if name exists
    custom_name: Optional[str] = None  # Override project name


@dataclass
class ManifestInfo:
    """Bundle manifest metadata."""

    bundle_format_version: int
    app_version: str
    schema_version: int
    project_name: str
    project_src_lang: str
    project_tgt_lang: str
    exported_at: str  # ISO 8601 timestamp
    table_counts: dict[str, int]  # {table_name: row_count}
    pronunciation_metadata_count: int = 0

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            "bundle_format_version": self.bundle_format_version,
            "app_version": self.app_version,
            "schema_version": self.schema_version,
            "project_name": self.project_name,
            "project_src_lang": self.project_src_lang,
            "project_tgt_lang": self.project_tgt_lang,
            "exported_at": self.exported_at,
            "table_counts": self.table_counts,
            "pronunciation_metadata_count": self.pronunciation_metadata_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ManifestInfo":
        """Create from dict (JSON deserialization)."""
        return cls(
            bundle_format_version=data["bundle_format_version"],
            app_version=data["app_version"],
            schema_version=data["schema_version"],
            project_name=data["project_name"],
            project_src_lang=data["project_src_lang"],
            project_tgt_lang=data["project_tgt_lang"],
            exported_at=data["exported_at"],
            table_counts=data["table_counts"],
            pronunciation_metadata_count=int(data.get("pronunciation_metadata_count") or 0),
        )


@dataclass
class ExportReport:
    """Result of export operation."""

    success: bool
    bundle_path: Optional[Path] = None
    manifest: Optional[ManifestInfo] = None
    elapsed_seconds: float = 0.0
    error_message: Optional[str] = None


@dataclass
class ImportReport:
    """Result of import operation."""

    success: bool
    new_project_id: Optional[int] = None
    new_project_name: Optional[str] = None
    table_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    error_message: Optional[str] = None
