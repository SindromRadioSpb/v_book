"""Reference corpus setup services (Hybrid: Download + Local Processing)."""

from .download_service import ReferenceDownloadService
from .manifest import ReferenceManifest, ManifestEntry
from .state import SetupState, SetupStage

__all__ = [
    "ReferenceDownloadService",
    "ReferenceManifest",
    "ManifestEntry",
    "SetupState",
    "SetupStage",
]
