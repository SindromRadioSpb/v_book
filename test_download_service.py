"""Test script for ReferenceDownloadService."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.reference_setup import (
    EMBEDDED_MANIFEST,
    ReferenceDownloadService,
    SetupState,
)


def test_manifest():
    """Test manifest loading."""
    print("=" * 80)
    print("TEST 1: Manifest Loading")
    print("=" * 80)

    entry = EMBEDDED_MANIFEST.get_latest()
    if entry:
        print(f"[OK] Latest entry: {entry.name}")
        print(f"  Version: {entry.version}")
        print(f"  URL: {entry.url}")
        print(f"  Size: {entry.size_bytes / 1024**3:.2f} GB")
        print(f"  Compression: {entry.compression}")
        print(f"  SHA256: {entry.sha256 or '(not set)'}")
        print(f"  Description: {entry.description}")
    else:
        print("[FAIL] No manifest entries found")

    print()


def test_state_persistence():
    """Test state persistence."""
    print("=" * 80)
    print("TEST 2: State Persistence")
    print("=" * 80)

    # Create test state
    state_file = Path("test_state.json")
    state = SetupState(mode="download")
    state.mark_started()
    state.update_progress(
        bytes_downloaded=1000000,
        total_bytes=2500000000,
    )
    state.download_speed_bps = 1024 * 1024  # 1 MB/s

    # Save
    state.save_to_file(state_file)
    print(f"[OK] State saved to {state_file}")

    # Load
    loaded_state = SetupState.load_from_file(state_file)
    if loaded_state:
        print("[OK] State loaded successfully")
        print(f"  Mode: {loaded_state.mode}")
        print(f"  Stage: {loaded_state.stage.value}")
        print(f"  Progress: {loaded_state.get_progress_percentage():.2f}%")
        print(f"  Downloaded: {loaded_state.bytes_downloaded:,} bytes")
        print(f"  Speed: {loaded_state.download_speed_bps / 1024:.0f} KB/s")
        eta = loaded_state.get_eta_seconds()
        if eta:
            print(f"  ETA: {eta / 3600:.1f} hours")
    else:
        print("[FAIL] Failed to load state")

    # Cleanup
    if state_file.exists():
        state_file.unlink()

    print()


def test_download_service_init():
    """Test download service initialization."""
    print("=" * 80)
    print("TEST 3: Download Service Initialization")
    print("=" * 80)

    download_dir = Path("test_downloads")
    state_file = Path("test_download_state.json")

    service = ReferenceDownloadService(download_dir, state_file)
    print("[OK] Service initialized")
    print(f"  Download dir: {service.download_dir}")
    print(f"  State file: {service.state_file}")
    print(f"  Can resume: {service.can_resume()}")

    entry = service.get_latest_entry()
    if entry:
        print(f"[OK] Got latest manifest entry: {entry.name}")
    else:
        print("[FAIL] No manifest entry available")

    # Cleanup
    if state_file.exists():
        state_file.unlink()

    print()


def test_progress_tracking():
    """Test progress tracking."""
    print("=" * 80)
    print("TEST 4: Progress Tracking")
    print("=" * 80)

    state = SetupState(mode="download")
    state.total_bytes = 2500000000  # 2.5 GB

    # Simulate download progress
    checkpoints = [0, 250000000, 500000000, 1250000000, 2500000000]  # 0%, 10%, 20%, 50%, 100%

    for checkpoint in checkpoints:
        state.bytes_downloaded = checkpoint
        state.download_speed_bps = 10 * 1024 * 1024  # 10 MB/s

        pct = state.get_progress_percentage()
        eta = state.get_eta_seconds()

        print(f"Downloaded: {checkpoint / 1024**3:.2f} GB ({pct:.1f}%)", end="")
        if eta:
            print(f" | ETA: {eta / 60:.1f} min")
        else:
            print(" | Complete!")

    print()


def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("REFERENCE DOWNLOAD SERVICE - TEST SUITE")
    print("=" * 80)
    print()

    try:
        test_manifest()
        test_state_persistence()
        test_download_service_init()
        test_progress_tracking()

        print("=" * 80)
        print("ALL TESTS PASSED [OK]")
        print("=" * 80)

    except Exception as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
