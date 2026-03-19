"""Tests for Model Installer (PATCH-02).

Tests verify:
- Model registry access
- Directory hash calculation
- Model verification
- Installation checks
"""

import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from install_local_mt_model import ModelInstaller, MODEL_REGISTRY


@pytest.fixture
def temp_models_root(tmp_path):
    """Create temporary models root for testing."""
    models_root = tmp_path / "models"
    models_root.mkdir()
    return models_root


@pytest.fixture
def installer(temp_models_root, monkeypatch):
    """Create ModelInstaller with temp root."""
    # Mock ModelResourceManager to use temp directory
    from app.services.local_models.model_resource_manager import ModelResourceManager

    def mock_get_models_root(self):
        return temp_models_root

    monkeypatch.setattr(ModelResourceManager, "get_models_root", mock_get_models_root)

    return ModelInstaller()


# ============================================================================
# Test 1: Model registry access
# ============================================================================


def test_model_registry_contains_nllb():
    """Model registry contains NLLB model."""
    assert "nllb-200-distilled-1.3B" in MODEL_REGISTRY

    model_info = MODEL_REGISTRY["nllb-200-distilled-1.3B"]
    assert model_info["hf_model_id"] == "facebook/nllb-200-distilled-1.3B"
    assert model_info["size_gb"] > 0
    assert "source" in model_info["languages"]
    assert "target" in model_info["languages"]


def test_model_registry_contains_seamless():
    """Model registry contains Seamless M4T model."""
    assert "seamless-m4t-v2-large" in MODEL_REGISTRY

    model_info = MODEL_REGISTRY["seamless-m4t-v2-large"]
    assert model_info["hf_model_id"] == "facebook/seamless-m4t-v2-large"
    assert model_info["size_gb"] > 0


# ============================================================================
# Test 2: Directory hash calculation
# ============================================================================


def test_calculate_directory_hash(installer, tmp_path):
    """Directory hash is deterministic."""
    # Create test directory
    test_dir = tmp_path / "test_hash"
    test_dir.mkdir()

    # Create files
    (test_dir / "file1.txt").write_text("content1")
    (test_dir / "file2.txt").write_text("content2")
    (test_dir / "subdir").mkdir()
    (test_dir / "subdir" / "file3.txt").write_text("content3")

    # Calculate hash twice
    hash1 = installer._calculate_directory_hash(test_dir)
    hash2 = installer._calculate_directory_hash(test_dir)

    assert hash1 == hash2
    assert len(hash1) == 64  # SHA256 hex digest


def test_calculate_directory_hash_empty(installer, tmp_path):
    """Empty directory has valid hash."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    hash_value = installer._calculate_directory_hash(empty_dir)
    assert len(hash_value) == 64


# ============================================================================
# Test 3: Check backend availability
# ============================================================================


def test_check_transformers(installer):
    """Check if transformers backend is available."""
    # May succeed or fail depending on environment
    result = installer._check_transformers()
    assert isinstance(result, bool)


def test_check_ctranslate2_fallback(installer):
    """Check ctranslate2 with graceful fallback if not installed."""
    # May succeed or fail depending on environment
    result = installer._check_ctranslate2()
    assert isinstance(result, bool)


# ============================================================================
# Test 4: Get CTranslate2 model ID
# ============================================================================


def test_get_ct2_model_id_nllb(installer):
    """Get CTranslate2 model ID for NLLB."""
    ct2_id = installer._get_ct2_model_id("facebook/nllb-200-distilled-1.3B")
    assert ct2_id == "michaelfeil/ct2fast-nllb-200-distilled-1.3B"


def test_get_ct2_model_id_unknown(installer):
    """Unknown model returns None."""
    ct2_id = installer._get_ct2_model_id("unknown/model")
    assert ct2_id is None


# ============================================================================
# Test 5: List installed models
# ============================================================================


def test_list_installed_models_empty(installer, caplog):
    """List installed models when none installed."""
    import logging

    caplog.set_level(logging.INFO)
    installer.list_installed_models()
    assert "No models installed" in caplog.text


def test_list_installed_models_with_models(installer, temp_models_root):
    """List installed models shows manifests."""
    # Create mock model directory
    model_path = temp_models_root / "test_model_ctranslate2"
    model_path.mkdir()

    # Create manifest
    manifest = {
        "model_id": "test/model",
        "backend": "ctranslate2",
        "package_sha256": "abc123",
        "size_bytes": 1000000,
        "languages": {"source": ["heb_Hebr"], "target": ["rus_Cyrl"]},
    }
    (model_path / "manifest.json").write_text(json.dumps(manifest))

    # List models
    installer.list_installed_models()
    # Should not raise exception


# ============================================================================
# Test 6: Verify model
# ============================================================================


def test_verify_model_unknown(installer):
    """Verify unknown model returns False."""
    result = installer.verify_model("unknown-model", "ctranslate2")
    assert result is False


def test_verify_model_not_installed(installer):
    """Verify non-installed model returns False."""
    result = installer.verify_model("nllb-200-distilled-1.3B", "ctranslate2")
    assert result is False


# ============================================================================
# Test 7: Install model validation
# ============================================================================


def test_install_model_unknown(installer, caplog):
    """Install unknown model returns False."""
    result = installer.install_model("unknown-model", "ctranslate2")
    assert result is False
    assert "Unknown model" in caplog.text


def test_install_model_unknown_backend(installer, caplog):
    """Install with unknown backend returns False."""
    result = installer.install_model("nllb-200-distilled-1.3B", "unknown-backend")
    assert result is False
    assert "Unknown backend" in caplog.text


# ============================================================================
# Test 8: Install model already installed
# ============================================================================


def test_install_model_already_installed(installer, temp_models_root):
    """Install model that's already installed."""
    # Create installed model
    model_path = installer.manager.model_dir("facebook/nllb-200-distilled-1.3B", "ctranslate2")
    model_path.mkdir(parents=True)

    # Create model file
    (model_path / "model.bin").write_bytes(b"x" * 1000)

    # Calculate size and write manifest
    actual_size = sum(f.stat().st_size for f in model_path.rglob("*") if f.is_file())
    manifest_path = model_path / "manifest.json"
    installer.manager.write_manifest(
        manifest_path=manifest_path,
        model_id="facebook/nllb-200-distilled-1.3B",
        backend="ctranslate2",
        package_sha256="abc123",
        size_bytes=actual_size + 350,
        languages={"source": ["heb_Hebr"], "target": ["rus_Cyrl"]},
    )

    # Try to install (should skip)
    result = installer.install_model("nllb-200-distilled-1.3B", "ctranslate2", force=False)
    assert result is True  # Returns True (already installed)
