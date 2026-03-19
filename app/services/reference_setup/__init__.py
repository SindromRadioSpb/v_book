"""Reference corpus setup services (Hybrid: Download + Local Processing)."""

from .download_service import ReferenceDownloadService
from .local_processing_service import LocalProcessingService
from .manifest import EMBEDDED_MANIFEST, ManifestEntry, ReferenceManifest
from .state import SetupStage, SetupState

__all__ = [
    "ReferenceDownloadService",
    "LocalProcessingService",
    "ReferenceManifest",
    "ManifestEntry",
    "EMBEDDED_MANIFEST",
    "SetupState",
    "SetupStage",
]
