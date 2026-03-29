"""Data Transfer Objects for project exchange."""

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class ExportStageId(StrEnum):
    """Stable stage identities for the project export pipeline."""

    PREPARE_CONTEXT = "prepare_context"
    PREFLIGHT_CHECKS = "preflight_checks"
    CREATE_STAGING_DB = "create_staging_db"
    APPLY_SCHEMA = "apply_schema"
    ATTACH_HOST_DB = "attach_host_db"
    PREPARE_FTS = "prepare_fts"
    RESOLVE_PROJECT_SCOPE = "resolve_project_scope"
    COPY_TABLES = "copy_tables"
    EXPORT_PRONUNCIATION_METADATA = "export_pronunciation_metadata"
    BUILD_MANIFEST = "build_manifest"
    PRUNE_PAYLOAD = "prune_payload"
    FINALIZE_SQLITE = "finalize_sqlite"
    BUILD_BUNDLE = "build_bundle"
    VALIDATE_ARTIFACT = "validate_artifact"
    CLEANUP_TEMP_STATE = "cleanup_temp_state"
    COMPLETED = "completed"


@dataclass
class ExportStageRecord:
    """Observed export stage transition."""

    stage_id: str
    stage_label: str
    status: str
    started_at: float
    ended_at: float | None = None
    elapsed_seconds: float = 0.0
    detail: str | None = None


@dataclass
class ExportArtifactInfo:
    """Post-build artifact validation details."""

    bundle_size_bytes: int
    payload_quick_check: str
    manifest_project_name: str
    total_rows: int
    validation_method: str = "bundle_format.read_bundle+payload.quick_check"


@dataclass
class ExportOptions:
    """Options for project export."""

    include_snapshots: bool = True  # Include project_snapshot table
    include_pronunciation_metadata: bool = False  # Include pronunciation metadata TSV sidecar


@dataclass
class ImportOptions:
    """Options for project import."""

    rename_if_conflict: bool = True  # Auto-rename project if name exists
    custom_name: str | None = None  # Override project name


@dataclass
class ImportPreflightReport:
    """Read-only import preview against the current host DB."""

    manifest: "ManifestInfo"
    host_schema_version: int
    original_project_name: str
    final_project_name: str
    name_conflict: bool = False
    total_rows: int = 0
    warnings: list[str] = field(default_factory=list)


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
    bundle_path: Path | None = None
    manifest: ManifestInfo | None = None
    elapsed_seconds: float = 0.0
    error_message: str | None = None
    final_stage_id: str | None = None
    final_stage_label: str | None = None
    stage_history: list[ExportStageRecord] = field(default_factory=list)
    artifact_info: ExportArtifactInfo | None = None


@dataclass
class ImportReport:
    """Result of import operation."""

    success: bool
    new_project_id: int | None = None
    new_project_name: str | None = None
    table_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    error_message: str | None = None
