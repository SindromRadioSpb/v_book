"""Test worker process startup directly.

This script tests the LocalMTWorker initialization to diagnose startup issues.
"""

import logging
import sys
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

from app.services.local_models import ModelResourceManager
from app.infra.local_mt.worker_process import LocalMTWorker


def test_worker_startup():
    """Test worker startup."""
    print("\n" + "=" * 80)
    print("WORKER PROCESS STARTUP TEST")
    print("=" * 80)

    # Step 1: Check model installation
    print("\n[STEP 1] Checking model installation...")
    model_manager = ModelResourceManager()
    model_id = "facebook/nllb-200-distilled-1.3B"
    backend = "ctranslate2"

    is_installed, reason = model_manager.is_installed(model_id, backend)
    print(f"  Model installed: {is_installed}")
    if not is_installed:
        print(f"  Reason: {reason}")
        print("\n  [ERROR] Model not installed!")
        return

    model_path = model_manager.model_dir(model_id, backend)
    print(f"  Model path: {model_path}")

    # Step 2: Start worker
    print("\n[STEP 2] Starting worker process...")
    print("  This may take 60-120 seconds for model loading...")

    try:
        worker = LocalMTWorker(
            model_path=model_path,
            backend=backend,
            model_id=model_id,
            timeout=30.0,
        )
        print("\n  [OK] Worker started successfully!")

        # Step 3: Test ping
        print("\n[STEP 3] Testing worker ping...")
        if worker.ping(timeout=5):
            print("  [OK] Worker is alive and responding!")
        else:
            print("  [ERROR] Worker not responding to ping!")
            return

        # Step 4: Test translation
        print("\n[STEP 4] Testing translation...")
        from app.infra.local_mt.worker_process import WorkerRequest

        request = WorkerRequest(
            text="hello",
            source_lang="eng_Latn",
            target_lang="rus_Cyrl",
        )

        result = worker.translate(request)
        print(f"  Input: {request.text}")
        print(f"  Output: {result.text}")
        print(f"  Latency: {result.inference_time_ms:.1f}ms")
        print("\n  [OK] Translation successful!")

        # Shutdown
        worker.shutdown()
        print("\n[OK] All tests passed!")

    except Exception as e:
        print(f"\n  [ERROR] Worker startup failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    print("\n" + "=" * 80)
    print("SUCCESS: Worker is functioning correctly")
    print("=" * 80)


if __name__ == "__main__":
    test_worker_startup()
