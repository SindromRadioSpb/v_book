"""File hashing utilities."""

import hashlib
from pathlib import Path


def sha256_file(file_path: Path) -> str:
    """Calculate SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


def sha256_text(text: str) -> str:
    """Calculate SHA256 hash of a string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
