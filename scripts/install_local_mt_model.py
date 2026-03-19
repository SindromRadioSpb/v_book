#!/usr/bin/env python3
r"""Install local MT models from Hugging Face Hub.

This script downloads and installs MT models for offline translation.

Usage:
    # Install NLLB model (CTranslate2 backend, recommended)
    python scripts/install_local_mt_model.py --model nllb-200-distilled-1.3B --backend ctranslate2

    # Install NLLB model (Transformers backend)
    python scripts/install_local_mt_model.py --model nllb-200-distilled-1.3B --backend transformers

    # Install Seamless M4T model
    python scripts/install_local_mt_model.py --model seamless-m4t-v2-large --backend transformers

    # List installed models
    python scripts/install_local_mt_model.py --list

    # Verify installed model
    python scripts/install_local_mt_model.py --verify nllb-200-distilled-1.3B --backend ctranslate2

Supported Models:
    - nllb-200-distilled-1.3B: NLLB-200 (1.3B parameters, ~2.6GB)
    - seamless-m4t-v2-large: Seamless M4T v2 Large (~9GB)

Supported Backends:
    - ctranslate2: Faster inference, quantization support (recommended for NLLB)
    - transformers: Native PyTorch, simpler setup

Platform Paths:
    Windows: %LOCALAPPDATA%\HDLE\models
    Linux/Mac: ~/.local/share/HDLE/models

Requirements:
    - huggingface_hub (pip install huggingface_hub)
    - ctranslate2 (pip install ctranslate2) [optional, for ctranslate2 backend]
    - transformers (pip install transformers)
    - torch (pip install torch)
"""

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# ============================================================================
# Model Registry
# ============================================================================

MODEL_REGISTRY = {
    "nllb-200-distilled-1.3B": {
        "hf_model_id": "facebook/nllb-200-distilled-1.3B",
        "size_gb": 2.6,
        "languages": {
            "source": ["heb_Hebr", "eng_Latn", "rus_Cyrl", "fra_Latn", "deu_Latn"],
            "target": ["heb_Hebr", "eng_Latn", "rus_Cyrl", "fra_Latn", "deu_Latn"],
        },
        "description": "NLLB-200 Distilled (1.3B parameters) - Supports 200 languages",
    },
    "seamless-m4t-v2-large": {
        "hf_model_id": "facebook/seamless-m4t-v2-large",
        "size_gb": 9.0,
        "languages": {
            "source": ["heb_Hebr", "eng_Latn", "rus_Cyrl", "fra_Latn", "deu_Latn"],
            "target": ["heb_Hebr", "eng_Latn", "rus_Cyrl", "fra_Latn", "deu_Latn"],
        },
        "description": "Seamless M4T v2 Large - Multimodal MT with speech support",
    },
}


# ============================================================================
# Model Installer
# ============================================================================


class ModelInstaller:
    """Install and verify local MT models."""

    def __init__(self):
        """Initialize installer."""
        # Import here to avoid hard dependency
        try:
            from app.services.local_models.model_resource_manager import ModelResourceManager

            self.manager = ModelResourceManager()
        except ImportError as e:
            logger.error(f"Failed to import ModelResourceManager: {e}")
            sys.exit(1)

    def install_model(
        self,
        model_name: str,
        backend: str,
        force: bool = False,
    ) -> bool:
        """
        Install model from Hugging Face Hub.

        Args:
            model_name: Model name from registry (e.g., "nllb-200-distilled-1.3B")
            backend: Backend ("ctranslate2" or "transformers")
            force: Force reinstall if already exists

        Returns:
            True if successful, False otherwise
        """
        # Check if model in registry
        if model_name not in MODEL_REGISTRY:
            logger.error(f"Unknown model: {model_name}")
            logger.info(f"Available models: {', '.join(MODEL_REGISTRY.keys())}")
            return False

        model_info = MODEL_REGISTRY[model_name]
        hf_model_id = model_info["hf_model_id"]

        # Check if already installed
        is_installed, reason = self.manager.is_installed(hf_model_id, backend)
        if is_installed and not force:
            logger.info(f"Model already installed: {hf_model_id} ({backend})")
            logger.info(f"Use --force to reinstall")
            return True

        # Check backend requirements
        if backend == "ctranslate2":
            if not self._check_ctranslate2():
                return False
        elif backend == "transformers":
            if not self._check_transformers():
                return False
        else:
            logger.error(f"Unknown backend: {backend}")
            logger.info("Supported backends: ctranslate2, transformers")
            return False

        # Show installation info
        logger.info(f"Installing model: {model_name}")
        logger.info(f"  Hugging Face ID: {hf_model_id}")
        logger.info(f"  Backend: {backend}")
        logger.info(f"  Size: ~{model_info['size_gb']} GB")
        logger.info(f"  Description: {model_info['description']}")

        # Get model directory
        model_path = self.manager.model_dir(hf_model_id, backend)
        logger.info(f"  Install path: {model_path}")

        # Create directory
        model_path.mkdir(parents=True, exist_ok=True)

        # Download model
        if backend == "ctranslate2":
            success = self._download_ctranslate2(hf_model_id, model_path)
        else:  # transformers
            success = self._download_transformers(hf_model_id, model_path)

        if not success:
            logger.error("Model download failed")
            return False

        # Calculate SHA256 (for manifest)
        logger.info("Calculating SHA256 hash...")
        package_sha256 = self._calculate_directory_hash(model_path)

        # Calculate total size
        size_bytes = sum(f.stat().st_size for f in model_path.rglob("*") if f.is_file())

        # Write manifest
        manifest_path = model_path / "manifest.json"
        success = self.manager.write_manifest(
            manifest_path=manifest_path,
            model_id=hf_model_id,
            backend=backend,
            package_sha256=package_sha256,
            size_bytes=size_bytes,
            languages=model_info["languages"],
        )

        if not success:
            logger.error("Failed to write manifest")
            return False

        # Verify installation
        is_installed, reason = self.manager.is_installed(hf_model_id, backend)
        if not is_installed:
            logger.error(f"Installation verification failed: {reason}")
            return False

        logger.info(f"✓ Model installed successfully: {hf_model_id} ({backend})")
        logger.info(f"  Total size: {size_bytes / (1024**3):.2f} GB")
        logger.info(f"  SHA256: {package_sha256[:16]}...")

        return True

    def _check_ctranslate2(self) -> bool:
        """Check if CTranslate2 is installed."""
        try:
            import ctranslate2

            logger.debug(f"CTranslate2 version: {ctranslate2.__version__}")
            return True
        except ImportError:
            logger.error("CTranslate2 not installed")
            logger.info("Install with: pip install ctranslate2")
            return False

    def _check_transformers(self) -> bool:
        """Check if Transformers is installed and importable.

        On Windows, torch CUDA DLL loading can fail (WinError 1114) when Qt has
        already initialized its runtime in the same process (e.g. pytest-qt).
        Catch OSError in addition to ImportError so the installer remains robust.
        """
        try:
            import transformers

            logger.debug(f"Transformers version: {transformers.__version__}")
            return True
        except ImportError:
            logger.error("Transformers not installed")
            logger.info("Install with: pip install transformers")
            return False
        except OSError as e:
            logger.warning(f"Transformers import failed (DLL load error): {e}")
            return False

    def _download_ctranslate2(self, hf_model_id: str, model_path: Path) -> bool:
        """
        Download CTranslate2-converted model from Hugging Face Hub.

        Args:
            hf_model_id: Hugging Face model ID
            model_path: Local path to save model

        Returns:
            True if successful, False otherwise
        """
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            logger.error("huggingface_hub not installed")
            logger.info("Install with: pip install huggingface_hub")
            return False

        try:
            import ctranslate2
        except ImportError:
            logger.error("ctranslate2 not installed")
            logger.info("Install with: pip install ctranslate2")
            return False

        # Check if CTranslate2 version exists on Hub
        # For NLLB, use michaelfeil/ct2fast-nllb-200-distilled-1.3B
        ct2_model_id = self._get_ct2_model_id(hf_model_id)
        if not ct2_model_id:
            logger.warning(f"No pre-converted CTranslate2 model found for {hf_model_id}")
            logger.info("Downloading Transformers model and converting...")
            # Fallback: download transformers model and convert
            return self._download_and_convert_to_ct2(hf_model_id, model_path)

        logger.info(f"Downloading CTranslate2 model from: {ct2_model_id}")

        try:
            snapshot_download(
                repo_id=ct2_model_id,
                local_dir=str(model_path),
                local_dir_use_symlinks=False,
            )
            logger.info("Download complete")
            return True
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return False

    def _get_ct2_model_id(self, hf_model_id: str) -> Optional[str]:
        """Get CTranslate2 model ID from Hugging Face Hub."""
        # Known CTranslate2 conversions
        ct2_mappings = {
            "facebook/nllb-200-distilled-1.3B": "michaelfeil/ct2fast-nllb-200-distilled-1.3B",
        }
        return ct2_mappings.get(hf_model_id)

    def _download_and_convert_to_ct2(self, hf_model_id: str, model_path: Path) -> bool:
        """Download Transformers model and convert to CTranslate2."""
        try:
            from huggingface_hub import snapshot_download
            import ctranslate2
        except ImportError as e:
            logger.error(f"Missing dependency: {e}")
            return False

        # Download transformers model to temp directory
        temp_path = model_path.parent / f"{model_path.name}_temp"
        temp_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"Downloading Transformers model: {hf_model_id}")
        try:
            snapshot_download(
                repo_id=hf_model_id,
                local_dir=str(temp_path),
                local_dir_use_symlinks=False,
            )
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return False

        # Convert to CTranslate2
        logger.info("Converting to CTranslate2 format...")
        try:
            converter = ctranslate2.converters.TransformersConverter(str(temp_path))
            converter.convert(str(model_path), quantization="int8")
            logger.info("Conversion complete")

            # Clean up temp directory
            import shutil

            shutil.rmtree(temp_path)

            return True
        except Exception as e:
            logger.error(f"Conversion failed: {e}")
            return False

    def _download_transformers(self, hf_model_id: str, model_path: Path) -> bool:
        """
        Download Transformers model from Hugging Face Hub.

        Args:
            hf_model_id: Hugging Face model ID
            model_path: Local path to save model

        Returns:
            True if successful, False otherwise
        """
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            logger.error("huggingface_hub not installed")
            logger.info("Install with: pip install huggingface_hub")
            return False

        logger.info(f"Downloading Transformers model: {hf_model_id}")

        try:
            snapshot_download(
                repo_id=hf_model_id,
                local_dir=str(model_path),
                local_dir_use_symlinks=False,
            )
            logger.info("Download complete")
            return True
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return False

    def _calculate_directory_hash(self, directory: Path) -> str:
        """
        Calculate SHA256 hash of all files in directory.

        Args:
            directory: Directory to hash

        Returns:
            SHA256 hex digest
        """
        hasher = hashlib.sha256()

        # Sort files for deterministic hashing
        files = sorted(directory.rglob("*"))

        for file_path in files:
            if not file_path.is_file():
                continue

            # Hash file path (relative to directory)
            rel_path = file_path.relative_to(directory)
            hasher.update(str(rel_path).encode("utf-8"))

            # Hash file content (in chunks to handle large files)
            with open(file_path, "rb") as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)

        return hasher.hexdigest()

    def list_installed_models(self) -> None:
        """List all installed models."""
        installed = self.manager.list_installed_models()

        if not installed:
            logger.info("No models installed")
            return

        logger.info(f"Installed models ({len(installed)}):")
        for manifest in installed:
            model_id = manifest.get("model_id", "unknown")
            backend = manifest.get("backend", "unknown")
            size_bytes = manifest.get("size_bytes", 0)
            size_gb = size_bytes / (1024**3)

            logger.info(f"  - {model_id} ({backend})")
            logger.info(f"    Size: {size_gb:.2f} GB")
            logger.info(f"    Languages: {manifest.get('languages', {})}")

    def verify_model(self, model_name: str, backend: str) -> bool:
        """
        Verify installed model.

        Args:
            model_name: Model name from registry
            backend: Backend

        Returns:
            True if valid, False otherwise
        """
        if model_name not in MODEL_REGISTRY:
            logger.error(f"Unknown model: {model_name}")
            return False

        hf_model_id = MODEL_REGISTRY[model_name]["hf_model_id"]

        is_installed, reason = self.manager.is_installed(hf_model_id, backend)

        if is_installed:
            logger.info(f"✓ Model verified: {hf_model_id} ({backend})")
            return True
        else:
            logger.error(f"✗ Model verification failed: {reason}")
            return False


# ============================================================================
# CLI
# ============================================================================


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Install local MT models from Hugging Face Hub",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--model",
        type=str,
        help="Model name to install (e.g., nllb-200-distilled-1.3B)",
    )

    parser.add_argument(
        "--backend",
        type=str,
        choices=["ctranslate2", "transformers"],
        help="Backend to use (ctranslate2 or transformers)",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reinstall if already exists",
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List installed models",
    )

    parser.add_argument(
        "--verify",
        type=str,
        help="Verify installed model",
    )

    parser.add_argument(
        "--show-models",
        action="store_true",
        help="Show available models in registry",
    )

    args = parser.parse_args()

    installer = ModelInstaller()

    # Show available models
    if args.show_models:
        logger.info("Available models:")
        for model_name, info in MODEL_REGISTRY.items():
            logger.info(f"  - {model_name}")
            logger.info(f"    HF ID: {info['hf_model_id']}")
            logger.info(f"    Size: ~{info['size_gb']} GB")
            logger.info(f"    Description: {info['description']}")
        return 0

    # List installed models
    if args.list:
        installer.list_installed_models()
        return 0

    # Verify model
    if args.verify:
        if not args.backend:
            logger.error("--backend required for --verify")
            return 1

        success = installer.verify_model(args.verify, args.backend)
        return 0 if success else 1

    # Install model
    if args.model:
        if not args.backend:
            logger.error("--backend required for --model")
            return 1

        success = installer.install_model(
            model_name=args.model,
            backend=args.backend,
            force=args.force,
        )
        return 0 if success else 1

    # No action specified
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
