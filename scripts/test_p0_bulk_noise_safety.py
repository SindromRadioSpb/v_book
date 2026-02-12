"""P0 Safety: Smoke Test for Bulk Noise Marking

Tests confirmation and progress features for bulk operations.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_worker_creation():
    """Test BulkNoiseUpdateWorker can be created."""
    from app.ui.workers import BulkNoiseUpdateWorker

    print("=" * 60)
    print("P0 Safety Smoke Test: Bulk Noise Marking")
    print("=" * 60)

    # Test 1: Create worker for Lemma
    print("\n[Test 1] Create BulkNoiseUpdateWorker for Lemma")
    worker = BulkNoiseUpdateWorker(
        model_class="Lemma",
        item_ids=[1, 2, 3],
        is_noise=True
    )
    print(f"  [OK] Worker created: model_class={worker.model_class}, items={len(worker.item_ids)}")

    # Test 2: Create worker for TermCluster
    print("\n[Test 2] Create BulkNoiseUpdateWorker for TermCluster")
    worker = BulkNoiseUpdateWorker(
        model_class="TermCluster",
        item_ids=[10, 20, 30, 40],
        is_noise=False
    )
    print(f"  [OK] Worker created: model_class={worker.model_class}, items={len(worker.item_ids)}")

    # Test 3: Check cancel method
    print("\n[Test 3] Check cancel functionality")
    assert worker._cancelled == False, "Worker should not be cancelled initially"
    worker.cancel()
    assert worker._cancelled == True, "Worker should be cancelled after cancel()"
    print("  [OK] Cancel method works correctly")

    print("\n" + "=" * 60)
    print("[OK] ALL TESTS PASSED")
    print("=" * 60)
    print("\nManual UI Testing Required:")
    print("1. Select 150 lemmas in Dictionary view -> Mark as Noise")
    print("   -> Should show confirmation dialog")
    print("2. Select 1500 lemmas -> Mark as Valid")
    print("   -> Should show progress dialog with cancel button")
    print("3. Click Cancel during progress")
    print("   -> Operation should stop gracefully")
    return True


if __name__ == "__main__":
    success = test_worker_creation()
    sys.exit(0 if success else 1)
