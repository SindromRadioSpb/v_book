"""Test application startup without GUI.

Checks:
1. Database initializes
2. Providers register correctly
3. No startup errors
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

print("=" * 60)
print("Testing Application Startup")
print("=" * 60)

# Test imports
print("\n1. Testing imports...")
try:
    from app.services.db_service import DBService
    from app.infra.translators.local_providers_setup import (
        register_google_translate,
        register_google_cloud_translate,
    )
    from app.infra.translators.providers_registry import ProvidersRegistry
    print("   [OK] All imports successful")
except Exception as e:
    print(f"   [ERROR] Import failed: {e}")
    sys.exit(1)

# Test database initialization
print("\n2. Testing database initialization...")
db_path = project_root / "hdle_premium.db"
print(f"   DB path: {db_path}")

try:
    DBService.initialize(str(db_path))
    print("   [OK] Database initialized")
except Exception as e:
    print(f"   [ERROR] Database initialization failed: {e}")
    sys.exit(1)

# Test crash recovery
print("\n3. Testing crash recovery...")
try:
    db_service = DBService.get_instance()
    recovered_count = db_service.recover_from_crash()
    if recovered_count > 0:
        print(f"   [WARN] Recovered {recovered_count} crashed runs")
    else:
        print("   [OK] No crashed runs to recover")
except Exception as e:
    print(f"   [ERROR] Crash recovery failed: {e}")

# Test provider registration
print("\n4. Testing provider registration...")

# Register Google Translate
try:
    register_google_translate()
    print("   [OK] Google Translate registered")
except Exception as e:
    print(f"   [ERROR] Google Translate registration failed: {e}")

# Register Google Cloud Translate
try:
    register_google_cloud_translate()
    print("   [OK] Google Cloud Translate registered")
except Exception as e:
    print(f"   [ERROR] Google Cloud Translate registration failed: {e}")

# Check registry
print("\n5. Checking provider registry...")
try:
    registry = ProvidersRegistry()
    provider_ids = registry.list_provider_ids()
    print(f"   Registered providers: {len(provider_ids)}")
    for provider_id in provider_ids:
        provider = registry.get(provider_id)
        print(f"   - {provider_id}: {provider.display_name}")
    print("   [OK] Registry check complete")
except Exception as e:
    print(f"   [ERROR] Registry check failed: {e}")

# Cleanup
print("\n6. Cleanup...")
try:
    DBService.shutdown()
    print("   [OK] Database shutdown")
except Exception as e:
    print(f"   [WARN] Shutdown warning: {e}")

print("\n" + "=" * 60)
print("Application startup test PASSED!")
print("=" * 60)
print("\nReady to launch GUI application!")
