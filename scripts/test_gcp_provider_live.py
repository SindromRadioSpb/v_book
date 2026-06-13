"""Test Google Cloud Translate provider with real SA JSON.

Tests:
1. Load SA JSON from file
2. Initialize provider
3. Translate test phrase
4. Display result
"""

import os
import sys
import json
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.infra.translators.providers.google_cloud_translate_provider import (
    GoogleCloudTranslateProvider,
)
from app.infra.translators.base_provider import TranslationRequest
from app.infra.translators.provider_config import (
    ProviderConfig,
    ProviderAuthConfig,
    ProviderAuthMode,
    ProviderLimitsConfig,
)
from app.infra.translators.provider_config_manager import ProviderConfigManager
from app.infra.settings import SettingsService


def test_live_translation():
    """Test translation with real API key."""
    print("=" * 60)
    print("Testing Google Cloud Translate Provider (Live API)")
    print("=" * 60)

    # SA JSON path — read from environment variable (never hardcode credentials)
    sa_json_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not sa_json_path:
        print(
            "[ERROR] GOOGLE_APPLICATION_CREDENTIALS is not set.\n"
            "  Set it to the path of your service account JSON key file:\n"
            "  $env:GOOGLE_APPLICATION_CREDENTIALS = 'C:\\keys\\hdle-translate-sa.json'"
        )
        return False

    print(f"\n1. Loading Service Account JSON from file...")
    print(f"   Path: {sa_json_path}")

    try:
        with open(sa_json_path, "r", encoding="utf-8") as f:
            sa_json_str = f.read()
            sa_info = json.loads(sa_json_str)

        project_id = sa_info.get("project_id", "unknown")
        print(f"   [OK] SA JSON loaded successfully")
        print(f"   Project ID: {project_id}")

    except FileNotFoundError:
        print(f"   [ERROR] SA JSON file not found at: {sa_json_path}")
        return False
    except json.JSONDecodeError as e:
        print(f"   [ERROR] Invalid JSON: {e}")
        return False
    except Exception as e:
        print(f"   [ERROR] Failed to load SA JSON: {e}")
        return False

    # Create temporary config with SA JSON from file
    print(f"\n2. Creating provider config...")
    config = ProviderConfig(
        provider_id="google_cloud_translate",
        auth=ProviderAuthConfig(
            mode=ProviderAuthMode.SERVICE_ACCOUNT_JSON,
            service_account_path=sa_json_path,  # Use file path for test
        ),
        limits=ProviderLimitsConfig(
            max_chars_per_request=10000,
            max_requests_per_minute=60,
        ),
    )
    print(f"   [OK] Config created")

    # Create mock config manager that returns our test config
    class MockConfigManager:
        def load_config(self, provider_id):
            return config

        def get_credential(self, credential_id):
            return None

    # Initialize provider
    print(f"\n3. Initializing provider...")
    provider = GoogleCloudTranslateProvider(
        config_manager=MockConfigManager(),
    )
    print(f"   [OK] Provider initialized")
    print(f"   Provider ID: {provider.provider_id}")
    print(f"   Display name: {provider.display_name}")

    # Test translations
    test_cases = [
        ("Hello", "en", "ru"),
        ("Good morning", "en", "he"),
        ("Thank you", "en", "ru"),
    ]

    print(f"\n4. Testing translations...")
    print("-" * 60)

    success_count = 0
    for i, (source_text, src_lang, tgt_lang) in enumerate(test_cases, 1):
        print(f"\nTest {i}/{len(test_cases)}:")
        print(f'  Source: "{source_text}" ({src_lang})')
        print(f"  Target: {tgt_lang}")

        request = TranslationRequest(
            source_text=source_text,
            source_lang=src_lang,
            target_lang=tgt_lang,
            trace_id=f"test-{i}",
        )

        result = provider.translate(request)

        if result.is_success:
            print(f"  [OK] Translation successful!")
            # Safely encode result for Windows console
            try:
                print(f'  Result: "{result.translated_text}"')
            except UnicodeEncodeError:
                print(f"  Result: <{len(result.translated_text)} chars> (Unicode display issue)")
            print(f"  Latency: {result.latency_ms}ms")
            print(f"  Provider: {result.provider_id}")
            success_count += 1
        else:
            print(f"  [ERROR] Translation failed!")
            print(f"  Error kind: {result.error_kind}")
            print(f"  Error message: {result.error_message}")

    print("\n" + "=" * 60)
    print(f"Results: {success_count}/{len(test_cases)} translations successful")

    if success_count == len(test_cases):
        print("[OK] All tests PASSED!")
        print("=" * 60)
        return True
    else:
        print(f"[FAIL] {len(test_cases) - success_count} tests FAILED")
        print("=" * 60)
        return False


if __name__ == "__main__":
    try:
        success = test_live_translation()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
