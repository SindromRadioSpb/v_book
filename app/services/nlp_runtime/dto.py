"""DTOs for NLP runtime diagnostics and provenance."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class NlpRuntimeStatus:
    """Normalized runtime truth for configured/effective NLP execution."""

    configured_engine_id: str
    effective_engine_id: str | None
    package_installed: bool
    model_present: bool
    pipeline_init_ok: bool
    smoke_ok: bool
    cuda_available: bool
    runtime_mode: str
    fallback_used: bool
    error_code: str | None = None
    error_detail: str | None = None
    remediation: str = ""
    engine_version: str | None = None
    model_id: str | None = None
    model_path: str | None = None
    managed_runtime_source_kind: str | None = None
    managed_runtime_source_path: str | None = None
    managed_runtime_ownership: str | None = None
    managed_runtime_bundled_payload_root: str | None = None

    @property
    def stanza_ready(self) -> bool:
        return bool(
            self.configured_engine_id == "stanza"
            and self.effective_engine_id == "stanza"
            and self.package_installed
            and self.model_present
            and self.pipeline_init_ok
            and self.smoke_ok
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
