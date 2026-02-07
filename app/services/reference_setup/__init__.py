"""Reference corpus setup services (Hybrid: Download + Local Processing)."""

from .download_service import ReferenceDownloadService
from .local_processing_service import LocalProcessingService
from .manifest import ReferenceManifest, ManifestEntry, EMBEDDED_MANIFEST
from .state import SetupState, SetupStage

__all__ = [
    "ReferenceDownloadService",
    "LocalProcessingService",
    "ReferenceManifest",
    "ManifestEntry",
    "EMBEDDED_MANIFEST",
    "SetupState",
    "SetupStage",
]
