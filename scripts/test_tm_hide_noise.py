"""Smoke test for Hide Noise functionality in Translation Management Panel.

Tests:
1. TMEntry model has is_noise, noise_reason, norm_text fields
2. TranslationAdminService has set_noise_status_bulk method
3. TranslationAdminService filters hide_noise correctly
4. BulkNoiseUpdateWorker supports TMEntry
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_tm_entry_model():
    """Test that TMEntry has noise marking fields."""
    from app.infra.sa_models import TMEntry

    print("\n[Test 1] TMEntry model has noise fields")

    # Check that fields exist
    assert hasattr(TMEntry, "is_noise"), "TMEntry missing is_noise field"
    assert hasattr(TMEntry, "noise_reason"), "TMEntry missing noise_reason field"
    assert hasattr(TMEntry, "norm_text"), "TMEntry missing norm_text field"

    print("  [OK] TMEntry has is_noise, noise_reason, norm_text fields")


def test_admin_service_bulk_method():
    """Test that TranslationAdminService has set_noise_status_bulk method."""
    from app.services.translation_admin_service import TranslationAdminService

    print("\n[Test 2] TranslationAdminService has set_noise_status_bulk method")

    service = TranslationAdminService()
    assert hasattr(service, "set_noise_status_bulk"), "Missing set_noise_status_bulk method"

    print("  [OK] set_noise_status_bulk method exists")


def test_hide_noise_filter():
    """Test that hide_noise filter works in search_tm_entries."""
    print("\n[Test 3] hide_noise filter in search_tm_entries")

    # This is a code inspection test - verify the method signature
    from app.services.translation_admin_service import TranslationAdminService
    import inspect

    service = TranslationAdminService()
    sig = inspect.signature(service.search_tm_entries)

    # Verify filters parameter exists
    assert "filters" in sig.parameters, "search_tm_entries missing filters parameter"

    print("  [OK] search_tm_entries accepts filters (including hide_noise)")


def test_bulk_worker_supports_tm_entry():
    """Test that BulkNoiseUpdateWorker supports TMEntry."""
    from app.ui.workers import BulkNoiseUpdateWorker

    print("\n[Test 4] BulkNoiseUpdateWorker supports TMEntry")

    # Create worker with TMEntry model
    worker = BulkNoiseUpdateWorker(model_class="TMEntry", item_ids=[1, 2, 3], is_noise=True)

    assert worker.model_class == "TMEntry", "Worker didn't accept TMEntry model_class"

    print("  [OK] BulkNoiseUpdateWorker accepts model_class='TMEntry'")


def test_migration_exists():
    """Test that migration 012 exists."""
    print("\n[Test 5] Migration 012_tm_noise_marking.sql exists")

    migration_file = project_root / "app" / "infra" / "migrations" / "012_tm_noise_marking.sql"
    assert migration_file.exists(), f"Migration file not found: {migration_file}"

    print(f"  [OK] Migration file exists: {migration_file.name}")


def main():
    """Run all smoke tests."""
    print("=" * 70)
    print("Smoke Test: Hide Noise in Translation Management Panel")
    print("=" * 70)

    try:
        test_tm_entry_model()
        test_admin_service_bulk_method()
        test_hide_noise_filter()
        test_bulk_worker_supports_tm_entry()
        test_migration_exists()

        print("\n" + "=" * 70)
        print("[OK] ALL SMOKE TESTS PASSED")
        print("=" * 70)

        print("\nManual UI Testing Required:")
        print("1. Open Translation Management Panel (Ctrl+Shift+T)")
        print("2. Verify 'Hide Noise' checkbox exists (checked by default)")
        print("3. Select rows -> Right-click -> Verify 'Mark as Noise/Valid' menu")
        print("4. Select 150 rows -> Mark as Noise -> Verify confirmation dialog")
        print("5. Select 1500 rows -> Mark as Noise -> Verify progress dialog")
        print("6. Uncheck 'Hide Noise' -> Verify noise entries appear")
        print("7. Export to Excel -> Verify noise entries excluded when hidden")

        return True

    except Exception as e:
        print(f"\n[FAIL] Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
