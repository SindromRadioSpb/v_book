"""Reference corpus manifest management."""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class ManifestEntry:
    """Entry for a downloadable reference corpus artifact."""

    name: str  # "hewiki_ref_processed_v20260207"
    version: str  # "20260207"
    url: str  # Download URL
    sha256: str  # SHA256 checksum
    size_bytes: int  # File size
    compression: str  # "zst" or "none"
    created_at: str  # ISO timestamp
    description: str  # Human-readable description

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "version": self.version,
            "url": self.url,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "compression": self.compression,
            "created_at": self.created_at,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ManifestEntry":
        """Create from dictionary."""
        return cls(**data)


class ReferenceManifest:
    """Manifest for reference corpus artifacts."""

    # TEMPORARY: GitHub Release URL (will update after PATCH-06)
    # TODO: Replace with actual GitHub Release URL after pre-processing
    DEFAULT_MANIFEST_URL = "https://raw.githubusercontent.com/SindromRadioSpb/v_book/main/ref_corpora/manifests/hewiki_ref_manifest.json"

    def __init__(self, manifest_path: Optional[Path] = None):
        """
        Initialize manifest.

        Args:
            manifest_path: Path to local manifest file (optional)
        """
        self.manifest_path = manifest_path
        self.entries: dict[str, ManifestEntry] = {}

    def load_from_file(self, path: Path):
        """Load manifest from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.entries = {
            name: ManifestEntry.from_dict(entry_data)
            for name, entry_data in data.get("entries", {}).items()
        }

    def load_from_url(self, url: str):
        """
        Load manifest from URL.

        Args:
            url: URL to manifest JSON

        Raises:
            RuntimeError: If download fails
        """
        import urllib.request

        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))

            self.entries = {
                name: ManifestEntry.from_dict(entry_data)
                for name, entry_data in data.get("entries", {}).items()
            }
        except Exception as e:
            raise RuntimeError(f"Failed to load manifest from {url}: {e}")

    def get_latest(self) -> Optional[ManifestEntry]:
        """Get latest manifest entry by version."""
        if not self.entries:
            return None

        # Sort by version (assumes YYYYMMDD format)
        sorted_entries = sorted(
            self.entries.values(),
            key=lambda e: e.version,
            reverse=True
        )
        return sorted_entries[0]

    def get_by_version(self, version: str) -> Optional[ManifestEntry]:
        """Get manifest entry by version."""
        for entry in self.entries.values():
            if entry.version == version:
                return entry
        return None

    def save_to_file(self, path: Path):
        """Save manifest to JSON file."""
        data = {
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "entries": {
                name: entry.to_dict()
                for name, entry in self.entries.items()
            }
        }

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


# Fallback embedded manifest (will be updated after PATCH-06)
EMBEDDED_MANIFEST = ReferenceManifest()
EMBEDDED_MANIFEST.entries = {
    "hewiki_ref_baseline": ManifestEntry(
        name="hewiki_ref_baseline",
        version="20260207",
        # TEMPORARY: Placeholder URL (will be updated after PATCH-06 processing)
        # For Python 3.14+: use uncompressed .db file (zstd not available)
        # For Python 3.11-3.13: use .db.zst for smaller download
        url="https://github.com/SindromRadioSpb/v_book/releases/download/v1.1.0/hewiki_ref_processed_v20260207.db",
        sha256="",  # Will be filled after PATCH-06
        size_bytes=2500000000,  # ~2.5 GB estimate
        compression="none",  # Changed from "zst" due to Python 3.14 compatibility
        created_at="2026-02-07T00:00:00Z",
        description="Hebrew Wikipedia Baseline (387,639 documents, fully processed)",
    )
}
