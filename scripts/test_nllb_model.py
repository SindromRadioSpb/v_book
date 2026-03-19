#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test NLLB model translation (direct test without UI integration).

This script tests the installed NLLB model directly using the worker process.

Usage:
    python scripts/test_nllb_model.py
"""
import sys
from pathlib import Path

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.infra.local_mt import start_worker, WorkerRequest, WorkerError
from app.services.local_models import ModelResourceManager


def test_nllb_translation():
    """Test NLLB model translation."""
    print("=" * 60)
    print("NLLB Model Translation Test")
    print("=" * 60)

    # Initialize model manager
    manager = ModelResourceManager()
    model_id = "facebook/nllb-200-distilled-1.3B"
    backend = "ctranslate2"

    # Check if model installed
    print(f"\n1. Checking if model installed...")
    is_installed, reason = manager.is_installed(model_id, backend)

    if not is_installed:
        print(f"   [FAIL] Model not installed: {reason}")
        print(f"\n   Install with:")
        print(
            f"   python scripts/install_local_mt_model.py --model nllb-200-distilled-1.3B --backend ctranslate2"
        )
        return False

    print(f"   [OK] Model installed: {manager.model_dir(model_id, backend)}")

    # Get model path
    model_path = manager.model_dir(model_id, backend)

    # Start worker
    print(f"\n2. Starting worker process...")
    try:
        worker = start_worker(
            model_path=model_path,
            backend=backend,
            model_id=model_id,
            timeout=30.0,
        )
        print(f"   [OK] Worker started successfully")
    except WorkerError as e:
        print(f"   [FAIL] Worker failed to start: {e}")
        return False

    try:
        # Test translations
        test_cases = [
            # English → Hebrew
            {
                "text": "Hello world",
                "source_lang": "eng_Latn",
                "target_lang": "heb_Hebr",
                "description": "English -> Hebrew",
            },
            # Hebrew → English
            {
                "text": "שלום עולם",
                "source_lang": "heb_Hebr",
                "target_lang": "eng_Latn",
                "description": "Hebrew -> English",
            },
            # English → Russian
            {
                "text": "Hello world",
                "source_lang": "eng_Latn",
                "target_lang": "rus_Cyrl",
                "description": "English -> Russian",
            },
            # Hebrew → Russian
            {
                "text": "שלום עולם",
                "source_lang": "heb_Hebr",
                "target_lang": "rus_Cyrl",
                "description": "Hebrew -> Russian",
            },
            # Technical term
            {
                "text": "database management system",
                "source_lang": "eng_Latn",
                "target_lang": "heb_Hebr",
                "description": "Technical term (EN->HE)",
            },
        ]

        print(f"\n3. Running translation tests...")
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n   Test {i}/{len(test_cases)}: {test_case['description']}")
            print(f"   Source: {test_case['text']}")

            request = WorkerRequest(
                text=test_case["text"],
                source_lang=test_case["source_lang"],
                target_lang=test_case["target_lang"],
                request_id=f"test-{i}",
            )

            try:
                result = worker.translate(request)

                if result.error:
                    print(f"   [FAIL] Translation failed: {result.error}")
                else:
                    print(f"   [OK] Translation: {result.text}")
                    print(f"        Inference time: {result.inference_time_ms:.2f} ms")

            except WorkerError as e:
                print(f"   [FAIL] Error: {e}")

        print(f"\n4. Shutting down worker...")
        worker.shutdown()
        print(f"   [OK] Worker shut down successfully")

        print("\n" + "=" * 60)
        print("[SUCCESS] Test completed successfully!")
        print("=" * 60)
        return True

    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        worker.shutdown()
        return False


if __name__ == "__main__":
    success = test_nllb_translation()
    sys.exit(0 if success else 1)
