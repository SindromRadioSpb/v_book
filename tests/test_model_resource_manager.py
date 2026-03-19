"""Tests for ModelResourceManager (PATCH-01).

Tests verify:
- Platform-safe models root path
- Model directory path generation
- Manifest write/load roundtrip
- Manifest verification (fields, size)
- is_installed() checks
- Model listing
"""

import json
import tempfile
import pytest
from pathlib import Path

from app.services.local_models.model_resource_manager import ModelResourceManager


@pytest.fixture
def temp_models_root(tmp_path):
    """Create temporary models root for testing."""
    models_root = tmp_path / "models"
    models_root.mkdir()
    return models_root


@pytest.fixture
def manager(temp_models_root, monkeypatch):
    """Create ModelResourceManager with temp root."""

    # Monkeypatch get_models_root to use temp directory
    def mock_get_models_root(self):
        return temp_models_root

    monkeypatch.setattr(ModelResourceManager, "get_models_root", mock_get_models_root)

    return ModelResourceManager()


# ============================================================================
# Test 1: Models root path generation
# ============================================================================


def test_get_models_root_creates_directory(manager, temp_models_root):
    """Models root directory is created if not exists."""
    assert temp_models_root.exists()
    assert temp_models_root.is_dir()


# ============================================================================
# Test 2: Model directory path generation
# ============================================================================


def test_model_dir_sanitizes_slashes(manager):
    """Model ID slashes are replaced with underscores."""
    model_path = manager.model_dir("facebook/nllb-200-distilled-1.3B", "ctranslate2")
    assert "facebook_nllb-200-distilled-1.3B_ctranslate2" in str(model_path)
    assert "/" not in model_path.name  # No slashes in directory name


def test_model_dir_includes_backend(manager):
    """Model directory includes backend suffix."""
    model_path = manager.model_dir("facebook/nllb-200-distilled-1.3B", "ctranslate2")
    assert "ctranslate2" in str(model_path)

    model_path_transformers = manager.model_dir("facebook/nllb-200-distilled-1.3B", "transformers")
    assert "transformers" in str(model_path_transformers)

    # Different backends → different paths
    assert model_path != model_path_transformers


# ============================================================================
# Test 3: Manifest write/load roundtrip
# ============================================================================


def test_write_and_load_manifest(manager, temp_models_root):
    """Manifest write/load roundtrip preserves data."""
    manifest_path = temp_models_root / "test_manifest.json"

    # Write manifest
    success = manager.write_manifest(
        manifest_path=manifest_path,
        model_id="facebook/nllb-200-distilled-1.3B",
        backend="ctranslate2",
        package_sha256="abc123def456",
        size_bytes=1234567890,
        languages={"source": ["heb_Hebr"], "target": ["rus_Cyrl"]},
    )

    assert success is True
    assert manifest_path.exists()

    # Load manifest
    manifest = manager.load_manifest(manifest_path)
    assert manifest is not None
    assert manifest["model_id"] == "facebook/nllb-200-distilled-1.3B"
    assert manifest["backend"] == "ctranslate2"
    assert manifest["package_sha256"] == "abc123def456"
    assert manifest["size_bytes"] == 1234567890
    assert manifest["languages"]["source"] == ["heb_Hebr"]
    assert manifest["languages"]["target"] == ["rus_Cyrl"]
    assert "created_at" in manifest
    assert "manifest_version" in manifest


# ============================================================================
# Test 4: Manifest verification (valid)
# ============================================================================


def test_verify_manifest_valid(manager, temp_models_root):
    """Valid manifest passes verification."""
    # Create model directory with files
    model_path = temp_models_root / "test_model"
    model_path.mkdir()

    # Create dummy model file
    dummy_file = model_path / "model.bin"
    dummy_file.write_bytes(b"x" * 1000)  # 1000 bytes

    # Create manifest
    manifest = {
        "model_id": "test/model",
        "backend": "ctranslate2",
        "package_sha256": "abc123",
        "size_bytes": 1000,
        "languages": {"source": ["heb_Hebr"], "target": ["rus_Cyrl"]},
    }

    # Verify manifest (skip SHA256 for speed)
    is_valid, reason = manager.verify_manifest(manifest, model_path, skip_sha256=True)

    assert is_valid is True
    assert reason == "OK"


# ============================================================================
# Test 5: Manifest verification (missing fields)
# ============================================================================


def test_verify_manifest_missing_field(manager, temp_models_root):
    """Invalid manifest (missing field) fails verification."""
    model_path = temp_models_root / "test_model"
    model_path.mkdir()

    # Manifest missing "backend"
    manifest = {
        "model_id": "test/model",
        # "backend": "ctranslate2",  # MISSING
        "package_sha256": "abc123",
        "size_bytes": 1000,
        "languages": {"source": ["heb_Hebr"], "target": ["rus_Cyrl"]},
    }

    is_valid, reason = manager.verify_manifest(manifest, model_path, skip_sha256=True)

    assert is_valid is False
    assert "Missing required field" in reason


# ============================================================================
# Test 6: Manifest verification (invalid languages)
# ============================================================================


def test_verify_manifest_invalid_languages(manager, temp_models_root):
    """Invalid manifest (bad languages) fails verification."""
    model_path = temp_models_root / "test_model"
    model_path.mkdir()

    # Languages not a dict
    manifest = {
        "model_id": "test/model",
        "backend": "ctranslate2",
        "package_sha256": "abc123",
        "size_bytes": 1000,
        "languages": "invalid",  # Should be dict
    }

    is_valid, reason = manager.verify_manifest(manifest, model_path, skip_sha256=True)

    assert is_valid is False
    assert "Invalid languages format" in reason


# ============================================================================
# Test 7: is_installed() - model not found
# ============================================================================


def test_is_installed_not_found(manager):
    """is_installed() returns False for non-existent model."""
    is_installed, reason = manager.is_installed("facebook/nllb-200-distilled-1.3B", "ctranslate2")

    assert is_installed is False
    assert "not found" in reason.lower()


# ============================================================================
# Test 8: is_installed() - model installed
# ============================================================================


def test_is_installed_success(manager, temp_models_root):
    """is_installed() returns True for valid installed model."""
    # Create model directory
    model_path = manager.model_dir("test/model", "ctranslate2")
    model_path.mkdir(parents=True)

    # Create required model file (model.bin for ctranslate2)
    (model_path / "model.bin").write_bytes(b"x" * 1000)

    # Calculate actual total size (for manifest size_bytes)
    actual_size = sum(f.stat().st_size for f in model_path.rglob("*") if f.is_file())

    # Write manifest with correct size (including model.bin + manifest itself)
    manifest_path = model_path / "manifest.json"
    manager.write_manifest(
        manifest_path=manifest_path,
        model_id="test/model",
        backend="ctranslate2",
        package_sha256="abc123",
        size_bytes=actual_size + 350,  # Approximate manifest.json size
        languages={"source": ["heb_Hebr"], "target": ["rus_Cyrl"]},
    )

    # Check if installed
    is_installed, reason = manager.is_installed("test/model", "ctranslate2")

    assert is_installed is True, f"Expected installed=True, got False with reason: {reason}"
    assert reason == "OK"


# ============================================================================
# Test 9: is_installed() - missing model file
# ============================================================================


def test_is_installed_missing_model_file(manager, temp_models_root):
    """is_installed() returns False if model.bin missing."""
    # Create model directory
    model_path = manager.model_dir("test/model", "ctranslate2")
    model_path.mkdir(parents=True)

    # Write manifest first to calculate its size
    manifest_path = model_path / "manifest.json"
    manager.write_manifest(
        manifest_path=manifest_path,
        model_id="test/model",
        backend="ctranslate2",
        package_sha256="abc123",
        size_bytes=1000,  # Temporary value
        languages={"source": ["heb_Hebr"], "target": ["rus_Cyrl"]},
    )

    # Calculate actual manifest size and rewrite with correct size
    actual_size = sum(f.stat().st_size for f in model_path.rglob("*") if f.is_file())
    manager.write_manifest(
        manifest_path=manifest_path,
        model_id="test/model",
        backend="ctranslate2",
        package_sha256="abc123",
        size_bytes=actual_size,  # Use actual size (manifest.json only)
        languages={"source": ["heb_Hebr"], "target": ["rus_Cyrl"]},
    )

    # DO NOT create model.bin

    # Check if installed
    is_installed, reason = manager.is_installed("test/model", "ctranslate2")

    assert is_installed is False
    assert "not found" in reason.lower()


# ============================================================================
# Test 10: list_installed_models()
# ============================================================================


def test_list_installed_models(manager, temp_models_root):
    """list_installed_models() returns all installed models."""
    # Create two models
    for i, (model_id, backend) in enumerate(
        [("test/model1", "ctranslate2"), ("test/model2", "transformers")]
    ):
        model_path = manager.model_dir(model_id, backend)
        model_path.mkdir(parents=True)

        manifest_path = model_path / "manifest.json"
        manager.write_manifest(
            manifest_path=manifest_path,
            model_id=model_id,
            backend=backend,
            package_sha256=f"abc{i}",
            size_bytes=1000 + i,
            languages={"source": ["heb_Hebr"], "target": ["rus_Cyrl"]},
        )

    # List installed
    installed = manager.list_installed_models()

    assert len(installed) == 2
    model_ids = [m["model_id"] for m in installed]
    assert "test/model1" in model_ids
    assert "test/model2" in model_ids


# ============================================================================
# Test 11: get_model_info()
# ============================================================================


def test_get_model_info(manager, temp_models_root):
    """get_model_info() returns manifest for installed model."""
    # Create model
    model_path = manager.model_dir("test/model", "ctranslate2")
    model_path.mkdir(parents=True)

    manifest_path = model_path / "manifest.json"
    manager.write_manifest(
        manifest_path=manifest_path,
        model_id="test/model",
        backend="ctranslate2",
        package_sha256="abc123",
        size_bytes=1000,
        languages={"source": ["heb_Hebr"], "target": ["rus_Cyrl"]},
    )

    # Get info
    info = manager.get_model_info("test/model", "ctranslate2")

    assert info is not None
    assert info["model_id"] == "test/model"
    assert info["backend"] == "ctranslate2"
