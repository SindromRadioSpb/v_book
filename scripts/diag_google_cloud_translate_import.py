"""Diagnostic script for Google Cloud Translate import check.

Purpose:
- Test that google-cloud-translate and google-auth are importable
- Check package versions
- Detect packaging issues early (before UI/code)
- NO network calls, NO real API usage

Usage:
    python scripts/diag_google_cloud_translate_import.py

Expected output:
    [OK] google-cloud-translate: 3.15.3
    [OK] google-auth: 2.28.2
    [OK] All imports successful
"""

import sys


def main():
    """Test imports and print versions."""
    print("=" * 60)
    print("Google Cloud Translate Import Diagnostic")
    print("=" * 60)

    errors = []

    # 1. Test google-cloud-translate
    try:
        import google.cloud.translate_v3
        from google.cloud import translate_v3

        # Check if client class exists
        assert hasattr(
            translate_v3, "TranslationServiceClient"
        ), "TranslationServiceClient not found"

        # Try to get version (may not be available, that's OK)
        try:
            import google.cloud.translate

            version = getattr(google.cloud.translate, "__version__", "unknown")
        except (ImportError, AttributeError):
            version = "unknown"

        print(f"[OK] google-cloud-translate: {version}")
        print(f"  - Module: {google.cloud.translate_v3.__file__}")
        print(f"  - TranslationServiceClient: OK")

    except ImportError as e:
        errors.append(f"[FAIL] google-cloud-translate import failed: {e}")
        print(errors[-1])
    except AssertionError as e:
        errors.append(f"[FAIL] google-cloud-translate verification failed: {e}")
        print(errors[-1])

    # 2. Test google-auth
    try:
        import google.auth
        from google.oauth2 import service_account

        # Check version
        version = getattr(google.auth, "__version__", "unknown")

        print(f"[OK] google-auth: {version}")
        print(f"  - Module: {google.auth.__file__}")
        print(f"  - service_account: {service_account.__file__}")

    except ImportError as e:
        errors.append(f"[FAIL] google-auth import failed: {e}")
        print(errors[-1])

    # 3. Test grpc (transitive dependency, often causes packaging issues)
    try:
        import grpc

        version = getattr(grpc, "__version__", "unknown")
        print(f"[OK] grpc: {version}")
        print(f"  - Module: {grpc.__file__}")

    except ImportError as e:
        # grpc is optional for v2 REST, so just warn
        print(f"[WARN] grpc not available (optional for REST): {e}")

    # 4. Test google-api-core
    try:
        import google.api_core

        version = getattr(google.api_core, "__version__", "unknown")
        print(f"[OK] google-api-core: {version}")

    except ImportError as e:
        errors.append(f"[FAIL] google-api-core import failed: {e}")
        print(errors[-1])

    # Summary
    print("=" * 60)

    if errors:
        print(f"FAILED: {len(errors)} error(s) detected")
        for error in errors:
            print(f"  - {error}")
        print("")
        print("Fix:")
        print("  pip install -e .")
        print("  # or")
        print("  pip install google-cloud-translate==3.15.3 google-auth==2.28.2")
        sys.exit(1)
    else:
        print("[OK] All imports successful")
        print("[OK] Ready for google_cloud_translate provider implementation")
        sys.exit(0)


if __name__ == "__main__":
    main()
