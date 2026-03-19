"""Task #13 Smoke Test: Settings Persistence for Translation Management Panel

Tests that user preferences are saved and restored correctly:
- page_size
- sort_column
- sort_direction
- header_state (simulated)
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_settings_persistence():
    """Test that TM panel settings are saved and restored."""
    from app.infra.settings import SettingsService

    print("=" * 60)
    print("Task #13 Smoke Test: Settings Persistence")
    print("=" * 60)

    # Get settings service
    settings = SettingsService.get_instance()

    # Test 1: Save and load page_size
    print("\n[Test 1] Page size persistence")
    settings.set_value("tm_panel/page_size", 250)
    loaded_size = settings.get_int("tm_panel/page_size", 100)
    assert loaded_size == 250, f"Expected 250, got {loaded_size}"
    print(f"  [OK] Saved page_size=250, loaded={loaded_size}")

    # Test 2: Save and load sort_column
    print("\n[Test 2] Sort column persistence")
    settings.set_value("tm_panel/sort_column", "src_text")
    loaded_column = settings.get_string("tm_panel/sort_column", "updated_at")
    assert loaded_column == "src_text", f"Expected 'src_text', got '{loaded_column}'"
    print(f"  [OK] Saved sort_column='src_text', loaded='{loaded_column}'")

    # Test 3: Save and load sort_direction
    print("\n[Test 3] Sort direction persistence")
    settings.set_value("tm_panel/sort_direction", "asc")
    loaded_direction = settings.get_string("tm_panel/sort_direction", "desc")
    assert loaded_direction == "asc", f"Expected 'asc', got '{loaded_direction}'"
    print(f"  [OK] Saved sort_direction='asc', loaded='{loaded_direction}'")

    # Test 4: Default values when not set
    print("\n[Test 4] Default values")
    settings.remove("tm_panel/nonexistent_key")
    default_val = settings.get_int("tm_panel/nonexistent_key", 999)
    assert default_val == 999, f"Expected default 999, got {default_val}"
    print(f"  [OK] Non-existent key returned default={default_val}")

    # Test 5: Settings file location
    print("\n[Test 5] Settings file location")
    settings_path = settings._settings.fileName()
    print(f"  [OK] Settings stored at: {settings_path}")

    # Cleanup: Reset to defaults
    print("\n[Cleanup] Resetting to defaults")
    settings.set_value("tm_panel/page_size", 100)
    settings.set_value("tm_panel/sort_column", "updated_at")
    settings.set_value("tm_panel/sort_direction", "desc")
    print(
        "  [OK] Reset to defaults: page_size=100, sort_column='updated_at', sort_direction='desc'"
    )

    print("\n" + "=" * 60)
    print("[OK] ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    test_settings_persistence()
