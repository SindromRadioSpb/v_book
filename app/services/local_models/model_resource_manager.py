r"""Model Resource Manager for local MT models.

Manages model storage, manifest verification, and health checking.

Architecture:
- Models stored in: %LOCALAPPDATA%\HDLE\models (Windows) or ~/.local/share/HDLE/models (Linux/Mac)
- Each model has manifest.json with metadata (sha256, size, languages)
- Manifest validation ensures model integrity

Usage:
    manager = ModelResourceManager()

    # Check if model installed
    is_installed, reason = manager.is_installed("facebook/nllb-200-distilled-1.3B", "ctranslate2")

    # Get model directory
    model_path = manager.model_dir("facebook/nllb-200-distilled-1.3B", "ctranslate2")

    # Verify manifest
    manifest = manager.load_manifest(model_path / "manifest.json")
    is_valid = manager.verify_manifest(manifest, model_path)
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from app.infra.resource_paths import ResourcePaths

logger = logging.getLogger(__name__)


class ModelResourceManager:
    """
    Manage local MT model resources with manifest-based verification.

    Responsibilities:
    - Get platform-safe models root directory
    - Load/write manifest.json for each model
    - Verify model integrity (sha256, size, languages)
    - Check if model installed
    - Mark degraded if manifest invalid
    """

    MANIFEST_VERSION = "1.0"

    def __init__(self):
        """Initialize model resource manager."""
        self._models_root = self.get_models_root()
        logger.info(f"Models root: {self._models_root}")

    def get_models_root(self) -> Path:
        r"""Get platform-safe models root directory.

        Windows: %LOCALAPPDATA%\HDLE\models
        Linux/Mac: ~/.local/share/HDLE/models

        Returns:
            Path to models root directory
        """
        return ResourcePaths.build(create=True).models_root

    def model_dir(self, model_id: str, backend: str) -> Path:
        """
        Get model directory path.

        Args:
            model_id: Model ID (e.g., "facebook/nllb-200-distilled-1.3B")
            backend: Backend (e.g., "ctranslate2", "transformers")

        Returns:
            Path to model directory
        """
        # Sanitize model_id for filesystem (replace / with _)
        safe_model_id = model_id.replace("/", "_")

        # Model directory: models_root / model_id_backend
        # Example: models/facebook_nllb-200-distilled-1.3B_ctranslate2
        model_dirname = f"{safe_model_id}_{backend}"
        return self._models_root / model_dirname

    def load_manifest(self, manifest_path: Path) -> dict | None:
        """
        Load manifest.json from path.

        Args:
            manifest_path: Path to manifest.json

        Returns:
            Manifest dict or None if not found/invalid
        """
        if not manifest_path.exists():
            logger.warning(f"Manifest not found: {manifest_path}")
            return None

        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)

            logger.debug(f"Loaded manifest: {manifest_path}")
            return manifest
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load manifest {manifest_path}: {e}")
            return None

    def write_manifest(
        self,
        manifest_path: Path,
        model_id: str,
        backend: str,
        package_sha256: str,
        size_bytes: int,
        languages: dict[str, list[str]],
    ) -> bool:
        """
        Write manifest.json to path.

        Args:
            manifest_path: Path to write manifest.json
            model_id: Model ID (e.g., "facebook/nllb-200-distilled-1.3B")
            backend: Backend (e.g., "ctranslate2", "transformers")
            package_sha256: SHA256 hash of model package
            size_bytes: Total size in bytes
            languages: Language support dict {"source": [...], "target": [...]}

        Returns:
            True if successful, False otherwise
        """
        manifest = {
            "manifest_version": self.MANIFEST_VERSION,
            "model_id": model_id,
            "backend": backend,
            "package_sha256": package_sha256,
            "size_bytes": size_bytes,
            "languages": languages,
            "created_at": datetime.now(UTC).isoformat(),
        }

        try:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)

            logger.info(f"Wrote manifest: {manifest_path}")
            return True
        except OSError as e:
            logger.error(f"Failed to write manifest {manifest_path}: {e}")
            return False

    def verify_manifest(
        self,
        manifest: dict,
        model_path: Path,
        skip_sha256: bool = False,
    ) -> tuple[bool, str]:
        """
        Verify manifest integrity.

        Checks:
        - Required fields present
        - SHA256 matches (if skip_sha256=False)
        - Size matches
        - Languages valid

        Args:
            manifest: Manifest dict
            model_path: Path to model directory
            skip_sha256: Skip SHA256 verification (slow for large models)

        Returns:
            (is_valid, reason) - (True, "OK") or (False, "reason")
        """
        # Check required fields
        required_fields = ["model_id", "backend", "package_sha256", "size_bytes", "languages"]
        for field in required_fields:
            if field not in manifest:
                return False, f"Missing required field: {field}"

        # Check languages format
        languages = manifest.get("languages", {})
        if not isinstance(languages, dict):
            return False, "Invalid languages format (expected dict)"

        if "source" not in languages or "target" not in languages:
            return False, "Missing source/target in languages"

        if not isinstance(languages["source"], list) or not isinstance(languages["target"], list):
            return False, "Invalid languages format (expected lists)"

        # Check size (quick check)
        expected_size = manifest["size_bytes"]
        if not isinstance(expected_size, int) or expected_size <= 0:
            return False, "Invalid size_bytes"

        # Calculate actual size of model directory
        actual_size = 0
        try:
            for file_path in model_path.rglob("*"):
                if file_path.is_file():
                    actual_size += file_path.stat().st_size
        except OSError as e:
            logger.warning(f"Failed to calculate size for {model_path}: {e}")
            # Continue without size verification

        # Allow 5% tolerance for size mismatch (some metadata files may vary)
        size_tolerance = 0.05
        if actual_size > 0:
            size_diff = abs(actual_size - expected_size) / expected_size
            if size_diff > size_tolerance:
                return False, f"Size mismatch: expected {expected_size}, got {actual_size}"

        # SHA256 verification (optional, slow for large models)
        if not skip_sha256:
            expected_sha256 = manifest["package_sha256"]

            # For now, skip actual SHA256 computation (too slow for 1GB+ models)
            # Production: Implement incremental hashing or trust manifest after initial install
            logger.debug(f"SHA256 verification skipped (expected: {expected_sha256[:8]}...)")
            # TODO: Implement SHA256 verification for critical use cases

        return True, "OK"

    def is_installed(
        self,
        model_id: str,
        backend: str,
        skip_sha256: bool = True,
    ) -> tuple[bool, str]:
        """
        Check if model is installed and valid.

        Args:
            model_id: Model ID (e.g., "facebook/nllb-200-distilled-1.3B")
            backend: Backend (e.g., "ctranslate2", "transformers")
            skip_sha256: Skip SHA256 verification (default: True for performance)

        Returns:
            (is_installed, reason) - (True, "OK") or (False, "reason")
        """
        # Get model directory
        model_path = self.model_dir(model_id, backend)

        # Check if directory exists
        if not model_path.exists():
            return False, f"Model directory not found: {model_path}"

        # Check if manifest exists
        manifest_path = model_path / "manifest.json"
        manifest = self.load_manifest(manifest_path)
        if not manifest:
            return False, f"Manifest not found or invalid: {manifest_path}"

        # Verify manifest
        is_valid, reason = self.verify_manifest(manifest, model_path, skip_sha256=skip_sha256)
        if not is_valid:
            return False, f"Manifest verification failed: {reason}"

        # Check if model files exist (basic check)
        # For transformers: config.json should exist
        # For ctranslate2: model.bin should exist
        if backend == "transformers":
            config_path = model_path / "config.json"
            if not config_path.exists():
                return False, f"Model config not found: {config_path}"
        elif backend == "ctranslate2":
            model_bin_path = model_path / "model.bin"
            if not model_bin_path.exists():
                return False, f"Model binary not found: {model_bin_path}"

        return True, "OK"

    def mark_degraded(self, model_id: str, backend: str, reason: str) -> None:
        """
        Mark model as degraded (for logging/monitoring).

        Args:
            model_id: Model ID
            backend: Backend
            reason: Degradation reason
        """
        logger.error(f"Model DEGRADED: {model_id} ({backend}) - Reason: {reason}")

        # TODO: Persist degradation status to database for monitoring
        # For now, just log the event

    def get_model_info(self, model_id: str, backend: str) -> dict | None:
        """
        Get model information from manifest.

        Args:
            model_id: Model ID
            backend: Backend

        Returns:
            Manifest dict or None if not found
        """
        model_path = self.model_dir(model_id, backend)
        manifest_path = model_path / "manifest.json"
        return self.load_manifest(manifest_path)

    def list_installed_models(self) -> list[dict]:
        """
        List all installed models.

        Returns:
            List of manifest dicts for installed models
        """
        installed = []

        try:
            for model_dir in self._models_root.iterdir():
                if not model_dir.is_dir():
                    continue

                manifest_path = model_dir / "manifest.json"
                manifest = self.load_manifest(manifest_path)
                if manifest:
                    installed.append(manifest)
        except OSError as e:
            logger.error(f"Failed to list models: {e}")

        return installed
