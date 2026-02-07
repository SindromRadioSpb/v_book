"""Reference corpus download service with resume support."""

import hashlib
import logging
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from .manifest import ReferenceManifest, ManifestEntry, EMBEDDED_MANIFEST
from .state import SetupState, SetupStage

logger = logging.getLogger(__name__)


class DownloadError(Exception):
    """Download-related error."""
    pass


class ReferenceDownloadService:
    """Service for downloading pre-processed reference corpus."""

    CHUNK_SIZE = 8192  # 8 KB chunks for download
    RESUME_THRESHOLD = 1024 * 1024  # Resume if > 1 MB already downloaded

    def __init__(self, download_dir: Path, state_file: Path):
        """
        Initialize download service.

        Args:
            download_dir: Directory for downloaded files
            state_file: Path to state JSON file
        """
        self.download_dir = download_dir
        self.state_file = state_file
        self.download_dir.mkdir(parents=True, exist_ok=True)

        # Load or create state
        self.state = SetupState.load_from_file(state_file) or SetupState()
        self.manifest = EMBEDDED_MANIFEST  # Use embedded manifest by default

    def load_manifest_from_url(self, url: str) -> bool:
        """
        Load manifest from URL (optional, fallback to embedded).

        Args:
            url: Manifest URL

        Returns:
            True if loaded successfully
        """
        try:
            manifest = ReferenceManifest()
            manifest.load_from_url(url)
            self.manifest = manifest
            logger.info(f"Loaded manifest from {url}")
            return True
        except Exception as e:
            logger.warning(f"Could not load manifest from {url}: {e}")
            logger.info("Using embedded manifest as fallback")
            return False

    def get_latest_entry(self) -> Optional[ManifestEntry]:
        """Get latest manifest entry."""
        return self.manifest.get_latest()

    def download(
        self,
        entry: ManifestEntry,
        progress_callback: Optional[Callable[[SetupState], None]] = None,
    ) -> Path:
        """
        Download reference corpus database.

        Args:
            entry: Manifest entry to download
            progress_callback: Callback for progress updates

        Returns:
            Path to downloaded file

        Raises:
            DownloadError: If download fails
        """
        output_path = self.download_dir / f"{entry.name}.db"
        if entry.compression == "zst":
            output_path = output_path.with_suffix(".db.zst")

        temp_path = output_path.with_suffix(output_path.suffix + ".part")

        try:
            # Check if already completed
            if output_path.exists() and self._verify_checksum(output_path, entry.sha256):
                logger.info(f"File already downloaded and verified: {output_path}")
                self.state.update_progress(
                    stage=SetupStage.COMPLETED,
                    bytes_downloaded=entry.size_bytes,
                    total_bytes=entry.size_bytes,
                )
                self._save_state()
                if progress_callback:
                    progress_callback(self.state)
                return output_path

            # Resume download if partial file exists
            start_byte = 0
            if temp_path.exists() and temp_path.stat().st_size > self.RESUME_THRESHOLD:
                start_byte = temp_path.stat().st_size
                logger.info(f"Resuming download from {start_byte:,} bytes")
                self.state.bytes_downloaded = start_byte
            else:
                # Start fresh
                if temp_path.exists():
                    temp_path.unlink()
                self.state = SetupState(mode="download")

            # Update state
            self.state.mark_started()
            self.state.update_progress(
                stage=SetupStage.DOWNLOADING,
                total_bytes=entry.size_bytes,
            )
            self._save_state()

            # Download with resume support
            logger.info(f"Downloading {entry.url} → {temp_path}")
            self._download_with_resume(
                entry.url,
                temp_path,
                start_byte,
                entry.size_bytes,
                progress_callback,
            )

            # Verify checksum
            logger.info("Verifying checksum...")
            self.state.update_progress(stage=SetupStage.VERIFYING)
            self._save_state()
            if progress_callback:
                progress_callback(self.state)

            if not self._verify_checksum(temp_path, entry.sha256):
                raise DownloadError(f"Checksum mismatch for {temp_path}")

            # Move to final location
            temp_path.rename(output_path)

            # Decompress if needed
            if entry.compression == "zst":
                logger.info("Decompressing...")
                self.state.update_progress(stage=SetupStage.DECOMPRESSING)
                self._save_state()
                if progress_callback:
                    progress_callback(self.state)

                decompressed_path = self._decompress_zstd(output_path)
                output_path.unlink()  # Remove compressed file
                output_path = decompressed_path

            # Mark completed
            self.state.mark_completed()
            self._save_state()
            if progress_callback:
                progress_callback(self.state)

            logger.info(f"Download complete: {output_path}")
            return output_path

        except Exception as e:
            error_msg = f"Download failed: {e}"
            logger.error(error_msg)
            self.state.mark_failed(error_msg)
            self._save_state()
            if progress_callback:
                progress_callback(self.state)
            raise DownloadError(error_msg) from e

    def _download_with_resume(
        self,
        url: str,
        output_path: Path,
        start_byte: int,
        total_bytes: int,
        progress_callback: Optional[Callable[[SetupState], None]],
    ):
        """Download file with HTTP Range support for resume."""
        headers = {}
        if start_byte > 0:
            headers["Range"] = f"bytes={start_byte}-"

        request = urllib.request.Request(url, headers=headers)

        with urllib.request.urlopen(request, timeout=30) as response:
            mode = "ab" if start_byte > 0 else "wb"
            with open(output_path, mode) as f:
                start_time = time.time()
                bytes_since_last_update = 0
                UPDATE_INTERVAL = 0.5  # Update every 0.5 seconds

                while True:
                    chunk = response.read(self.CHUNK_SIZE)
                    if not chunk:
                        break

                    f.write(chunk)
                    self.state.bytes_downloaded += len(chunk)
                    bytes_since_last_update += len(chunk)

                    # Update progress at intervals
                    elapsed = time.time() - start_time
                    if elapsed >= UPDATE_INTERVAL:
                        # Calculate speed
                        speed = bytes_since_last_update / elapsed if elapsed > 0 else 0
                        self.state.download_speed_bps = speed

                        # Save state and callback
                        self._save_state()
                        if progress_callback:
                            progress_callback(self.state)

                        # Reset counters
                        start_time = time.time()
                        bytes_since_last_update = 0

    def _verify_checksum(self, file_path: Path, expected_sha256: str) -> bool:
        """
        Verify file SHA256 checksum.

        Args:
            file_path: Path to file
            expected_sha256: Expected SHA256 hex digest

        Returns:
            True if checksum matches
        """
        if not expected_sha256:
            logger.warning("No checksum provided, skipping verification")
            return True

        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                sha256.update(chunk)

        actual = sha256.hexdigest()
        matches = actual == expected_sha256

        if not matches:
            logger.error(f"Checksum mismatch: expected {expected_sha256}, got {actual}")

        return matches

    def _decompress_zstd(self, compressed_path: Path) -> Path:
        """
        Decompress zstd file (fallback to gzip if zstd unavailable).

        Args:
            compressed_path: Path to .zst file

        Returns:
            Path to decompressed file

        Raises:
            DownloadError: If decompression fails
        """
        output_path = compressed_path.with_suffix("")  # Remove .zst extension

        logger.info(f"Decompressing {compressed_path} → {output_path}")

        # Try zstandard first
        try:
            import zstandard as zstd

            dctx = zstd.ZstdDecompressor()
            with open(compressed_path, "rb") as ifh:
                with open(output_path, "wb") as ofh:
                    dctx.copy_stream(ifh, ofh)

            logger.info("Decompression complete (zstd)")
            return output_path

        except ImportError:
            logger.warning("zstandard not available, trying fallback decompression methods")

            # Fallback to gzip if extension is .gz
            if compressed_path.suffix == ".gz":
                import gzip
                import shutil

                with gzip.open(compressed_path, "rb") as f_in:
                    with open(output_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)

                logger.info("Decompression complete (gzip)")
                return output_path
            else:
                raise DownloadError(
                    "zstandard library not available and file is not gzip. "
                    "For Python 3.14+, please use uncompressed database or install Python 3.11-3.13"
                )

    def _save_state(self):
        """Save current state to file."""
        self.state.save_to_file(self.state_file)

    def cancel(self):
        """Cancel download."""
        logger.info("Download cancelled")
        self.state.mark_cancelled()
        self._save_state()

    def can_resume(self) -> bool:
        """Check if download can be resumed."""
        return self.state.can_resume()
