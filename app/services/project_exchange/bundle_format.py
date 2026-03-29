"""Bundle format handling: ZIP creation, extraction, validation."""

import contextlib
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

from app.infra.security import validate_file_size, validate_path_security
from app.infra.security.policy import MAX_BUNDLE_SIZE
from app.services.project_exchange.constants import (
    CHECKSUMS_FILENAME,
    MANIFEST_FILENAME,
    PAYLOAD_FILENAME,
    PRONUNCIATION_METADATA_FILENAME,
)
from app.services.project_exchange.dto import ManifestInfo

logger = logging.getLogger(__name__)


class BundleFormatError(Exception):
    """Raised when bundle format is invalid."""

    pass


def create_bundle(
    payload_path: Path,
    manifest: ManifestInfo,
    out_path: Path,
    *,
    extra_files: dict[str, Path] | None = None,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> None:
    """Create a .hdleproj bundle (ZIP) from payload and manifest.

    Args:
        payload_path: Path to payload.sqlite
        manifest: ManifestInfo object
        out_path: Output .hdleproj path

    Raises:
        BundleFormatError: If bundle creation fails
    """
    # Validate output path
    validate_path_security(out_path, operation="export_bundle")

    # Compute checksums
    logger.info("Computing checksums...")
    checksums = _compute_checksums(payload_path, manifest, extra_files=extra_files or {})
    if progress_callback:
        progress_callback("Computing checksums...", 1, 6)

    # Create ZIP
    logger.info(f"Creating bundle: {out_path}")
    temp_out_path = out_path.with_suffix(f"{out_path.suffix}.partial")
    temp_out_path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(FileNotFoundError):
        temp_out_path.unlink()
    try:
        with zipfile.ZipFile(temp_out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            # Add manifest.json
            manifest_json = json.dumps(manifest.to_dict(), indent=2)
            zf.writestr(MANIFEST_FILENAME, manifest_json)
            if progress_callback:
                progress_callback("Writing manifest...", 2, 6)

            # Add payload.sqlite
            zf.write(payload_path, PAYLOAD_FILENAME)
            if progress_callback:
                progress_callback("Writing payload...", 4, 6)

            # Add checksums.json
            checksums_json = json.dumps(checksums, indent=2)
            zf.writestr(CHECKSUMS_FILENAME, checksums_json)
            if progress_callback:
                progress_callback("Writing checksums...", 5, 6)

            # Add optional sidecar files (metadata-only sections)
            for arcname, local_path in (extra_files or {}).items():
                validate_path_security(local_path, operation="export_bundle")
                zf.write(local_path, arcname)
            if progress_callback:
                progress_callback("Finalizing bundle...", 6, 6)

        os.replace(temp_out_path, out_path)

        logger.info(
            f"Bundle created successfully: {out_path} ({out_path.stat().st_size / 1024 / 1024:.1f} MB)"
        )
    except Exception as e:
        logger.exception("Failed to create bundle")
        with contextlib.suppress(FileNotFoundError):
            temp_out_path.unlink()
        raise BundleFormatError(f"Failed to create bundle: {e}") from e


def read_bundle(bundle_path: Path, extract_dir: Path) -> tuple[ManifestInfo, Path]:
    """Read and validate a .hdleproj bundle, extract to temp dir.

    Args:
        bundle_path: Path to .hdleproj file
        extract_dir: Temp directory for extraction

    Returns:
        Tuple of (ManifestInfo, payload_path)

    Raises:
        BundleFormatError: If bundle is invalid or tampered
    """
    # Security validation
    validate_path_security(bundle_path, operation="import_bundle")
    validate_file_size(bundle_path, MAX_BUNDLE_SIZE)

    # Validate ZIP structure
    logger.info(f"Validating bundle: {bundle_path}")
    _validate_zip_structure(bundle_path)

    # Safe extraction
    logger.info(f"Extracting bundle to: {extract_dir}")
    _safe_extract(bundle_path, extract_dir)

    # Read manifest
    manifest_path = extract_dir / MANIFEST_FILENAME
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest_data = json.load(f)
        manifest = ManifestInfo.from_dict(manifest_data)
    except Exception as e:
        raise BundleFormatError(f"Invalid manifest.json: {e}") from e

    # Verify checksums
    logger.info("Verifying checksums...")
    checksums_path = extract_dir / CHECKSUMS_FILENAME
    try:
        with open(checksums_path, encoding="utf-8") as f:
            stored_checksums = json.load(f)
    except Exception as e:
        raise BundleFormatError(f"Invalid checksums.json: {e}") from e

    payload_path = extract_dir / PAYLOAD_FILENAME
    extra_files: dict[str, Path] = {}
    pron_path = extract_dir / PRONUNCIATION_METADATA_FILENAME
    if pron_path.exists():
        extra_files[PRONUNCIATION_METADATA_FILENAME] = pron_path
    actual_checksums = _compute_checksums(payload_path, manifest, extra_files=extra_files)

    if stored_checksums != actual_checksums:
        raise BundleFormatError(
            f"Checksum mismatch! Bundle may be corrupted or tampered.\n"
            f"Expected: {stored_checksums}\n"
            f"Actual: {actual_checksums}"
        )

    logger.info("Bundle validation passed")
    return manifest, payload_path


def validate_bundle_artifact(bundle_path: Path) -> dict[str, object]:
    """Validate a finished bundle artifact and return structured evidence."""

    temp_dir = Path(tempfile.mkdtemp(prefix="hdle_bundle_validate_"))
    try:
        manifest, payload_path = read_bundle(bundle_path, temp_dir)
        payload_conn = sqlite3.connect(str(payload_path))
        try:
            quick_check_rows = [
                str(row[0]) for row in payload_conn.execute("PRAGMA quick_check(1)").fetchall()
            ]
        finally:
            payload_conn.close()

        if not quick_check_rows or any(row.lower() != "ok" for row in quick_check_rows):
            raise BundleFormatError(
                "Payload quick_check failed during artifact validation: "
                + ("; ".join(quick_check_rows) if quick_check_rows else "empty result")
            )

        return {
            "bundle_size_bytes": int(bundle_path.stat().st_size),
            "payload_quick_check": quick_check_rows[0],
            "manifest_project_name": str(manifest.project_name),
            "total_rows": int(sum((manifest.table_counts or {}).values())),
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def peek_manifest(bundle_path: Path) -> ManifestInfo:
    """Quick-read manifest from bundle without full extraction/validation.

    Used for UI preview before import.

    Args:
        bundle_path: Path to .hdleproj file

    Returns:
        ManifestInfo object

    Raises:
        BundleFormatError: If manifest cannot be read
    """
    # Basic security checks
    validate_path_security(bundle_path, operation="import_bundle")
    validate_file_size(bundle_path, MAX_BUNDLE_SIZE)

    try:
        with zipfile.ZipFile(bundle_path, "r") as zf:
            if MANIFEST_FILENAME not in zf.namelist():
                raise BundleFormatError(f"Bundle missing {MANIFEST_FILENAME}")

            manifest_bytes = zf.read(MANIFEST_FILENAME)
            manifest_data = json.loads(manifest_bytes.decode("utf-8"))
            return ManifestInfo.from_dict(manifest_data)
    except zipfile.BadZipFile as e:
        raise BundleFormatError(f"Invalid ZIP file: {e}") from e
    except Exception as e:
        raise BundleFormatError(f"Failed to read manifest: {e}") from e


def _compute_checksums(
    payload_path: Path,
    manifest: ManifestInfo,
    *,
    extra_files: dict[str, Path] | None = None,
) -> dict:
    """Compute SHA256 checksums for payload and manifest.

    Args:
        payload_path: Path to payload.sqlite
        manifest: ManifestInfo object

    Returns:
        Dict with keys: manifest_sha256, payload_sha256
    """
    # Payload checksum
    payload_sha256 = _compute_file_sha256(payload_path)

    # Manifest checksum (from serialized JSON, consistent formatting)
    manifest_json = json.dumps(manifest.to_dict(), indent=2, sort_keys=True)
    manifest_sha256 = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()

    checksums = {
        "manifest_sha256": manifest_sha256,
        "payload_sha256": payload_sha256,
    }
    for name, file_path in (extra_files or {}).items():
        checksums[f"extra_sha256::{name}"] = _compute_file_sha256(file_path)
    return checksums


def _compute_file_sha256(file_path: Path) -> str:
    """Compute SHA256 hash of a file.

    Args:
        file_path: Path to file

    Returns:
        SHA256 hex digest
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


def _validate_zip_structure(bundle_path: Path) -> None:
    """Validate ZIP structure and contents.

    Args:
        bundle_path: Path to .hdleproj file

    Raises:
        BundleFormatError: If structure is invalid
    """
    try:
        with zipfile.ZipFile(bundle_path, "r") as zf:
            # Check for required entries
            entries = set(zf.namelist())
            required = {MANIFEST_FILENAME, PAYLOAD_FILENAME, CHECKSUMS_FILENAME}
            allowed_optional = {PRONUNCIATION_METADATA_FILENAME}

            if not required.issubset(entries):
                raise BundleFormatError(
                    f"Invalid bundle structure. Missing required entries: {required - entries}"
                )
            unknown = entries - required - allowed_optional
            if unknown:
                raise BundleFormatError(f"Invalid bundle structure. Unknown entries: {unknown}")

            # Check uncompressed size (zip bomb protection)
            total_size = sum(info.file_size for info in zf.infolist())
            if total_size > MAX_BUNDLE_SIZE:
                raise BundleFormatError(
                    f"Bundle uncompressed size ({total_size / 1024 / 1024:.1f} MB) "
                    f"exceeds limit ({MAX_BUNDLE_SIZE / 1024 / 1024:.1f} MB)"
                )

            # Check for path traversal attacks
            for name in entries:
                if ".." in name or name.startswith("/") or name.startswith("\\"):
                    raise BundleFormatError(f"Unsafe path in bundle: {name}")
                if ":" in name:  # Windows absolute path
                    raise BundleFormatError(f"Absolute path in bundle: {name}")

    except zipfile.BadZipFile as e:
        raise BundleFormatError(f"Invalid ZIP file: {e}") from e


def _safe_extract(bundle_path: Path, extract_dir: Path) -> None:
    """Safely extract bundle to directory.

    Args:
        bundle_path: Path to .hdleproj file
        extract_dir: Extraction directory

    Raises:
        BundleFormatError: If extraction fails
    """
    extract_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(bundle_path, "r") as zf:
            # Extract with path safety checks
            for member in zf.infolist():
                # Double-check path safety (already validated in _validate_zip_structure)
                if ".." in member.filename or member.filename.startswith(("/", "\\")):
                    raise BundleFormatError(f"Path traversal attempt: {member.filename}")

                # Extract
                zf.extract(member, extract_dir)

    except zipfile.BadZipFile as e:
        raise BundleFormatError(f"Extraction failed: {e}") from e
