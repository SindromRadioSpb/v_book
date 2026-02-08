# PATCH-03: Provider Config Schema - COMPLETE

**Date:** 2026-02-08
**Status:** ✅ COMPLETE
**Task:** Create unified configuration schema for all MT providers

---

## Overview

Created dataclasses and manager for provider authentication, limits, retry policy, and UI metadata. Ensures backward compatibility with existing providers (google_translate, deepl, local_nllb, etc.).

**Key Achievement:** Unified config schema that works for both free providers (no auth) and official APIs (auth required).

---

## Files Created

### 1. `app/infra/translators/provider_config.py` (350+ lines)

**Dataclasses:**
- `ProviderAuthMode` (Enum): `NONE` | `API_KEY` | `SERVICE_ACCOUNT_JSON`
- `ProviderAuthConfig`: Auth mode + credential IDs (references to CredentialStore)
- `ProviderLimitsConfig`: Budget guards (chars/requests per minute/day/month, fail-closed)
- `ProviderRetryPolicy`: Retry behavior (max retries, backoff, status codes)
- `ProviderUiMeta`: UI display metadata (name, capabilities, defaults)
- `ProviderConfig`: Aggregates all configs into single object

**Helper Functions:**
- `get_*_key(provider_id)`: QSettings keys for all config fields
- `get_api_key_credential_id(provider_id)`: CredentialStore key for API key
- `get_service_account_credential_id(provider_id)`: CredentialStore key for SA JSON

**Example Usage:**
```python
from app.infra.translators.provider_config import (
    ProviderConfig,
    ProviderAuthConfig,
    ProviderAuthMode,
    ProviderLimitsConfig,
)

# Google Cloud Translate config
config = ProviderConfig(
    provider_id="google_cloud_translate",
    auth=ProviderAuthConfig(
        mode=ProviderAuthMode.SERVICE_ACCOUNT_JSON,
        service_account_credential_id="mt_provider:google_cloud_translate:service_account_json",
    ),
    limits=ProviderLimitsConfig(
        max_chars_per_month=500000,  # Free tier
        fail_closed=True,
    ),
)
```

---

### 2. `app/infra/translators/provider_config_manager.py` (260+ lines)

**Class:** `ProviderConfigManager`

**Methods:**
- `load_config(provider_id)` → ProviderConfig from QSettings
- `save_config(config)` → Save to QSettings (NOT credentials)
- `get_credential(credential_id)` → Load from CredentialStore
- `set_credential(credential_id, value)` → Save to CredentialStore (encrypted)
- `delete_credential(credential_id)` → Remove from CredentialStore
- `is_enabled(provider_id)` → Check enabled status
- `set_enabled(provider_id, enabled)` → Set enabled status

**Backward Compatibility:**
- Existing providers default to `auth_mode=NONE`
- Legacy `rate_limit` key mapped to `max_requests_per_minute`
- Missing config fields use safe defaults

**Example Usage:**
```python
from app.infra.translators.provider_config_manager import ProviderConfigManager
from app.infra.settings import SettingsService
from app.infra.security import CredentialStore
from app.services.db_service import DBService

settings = SettingsService.get_instance()
with DBService.get_instance().get_session() as session:
    cred_store = CredentialStore(session)
    config_mgr = ProviderConfigManager(settings, cred_store)

    # Load config
    config = config_mgr.load_config("google_cloud_translate")

    # Check auth configured
    if config.auth.is_configured():
        # Get API key from secure storage
        api_key = config_mgr.get_credential(config.auth.api_key_credential_id)
```

---

### 3. `tests/test_provider_config.py` (200+ lines)

**Test Coverage:** 19 unit tests, **ALL PASS** ✅

**Test Classes:**
- `TestProviderAuthConfig` (6 tests) - Auth modes, is_configured()
- `TestProviderLimitsConfig` (2 tests) - Defaults, budget guards detection
- `TestProviderRetryPolicy` (4 tests) - Defaults, should_retry() logic
- `TestProviderConfigManager` (4 tests) - Load/save roundtrip, backward compatibility
- `TestCredentialHelpers` (2 tests) - Credential ID format
- `TestProviderUiMeta` (1 test) - UI metadata defaults

**Key Tests:**
```python
def test_service_account_configured_via_credential_id():
    """SA configured when credential ID set."""
    auth = ProviderAuthConfig(
        mode=ProviderAuthMode.SERVICE_ACCOUNT_JSON,
        service_account_credential_id="mt_provider:test:service_account_json",
    )
    assert auth.is_configured()  # PASS

def test_backward_compatibility_legacy_rate_limit():
    """Legacy 'rate_limit' key still works."""
    config_manager.settings.set_value("mt/providers/legacy/rate_limit", 120)
    config = config_manager.load_config("legacy_provider")
    assert config.limits.max_requests_per_minute == 120  # PASS
```

---

## Architecture Decisions

### 1. Credential Storage Separation

**Settings (QSettings INI):**
- Auth mode: `"none"` | `"api_key"` | `"service_account_json"`
- Credential IDs (references): `"mt_provider:<provider_id>:api_key"`
- Limits: max chars/requests per period
- Enabled status

**CredentialStore (OS keyring + encrypted DB):**
- API key plaintext (encrypted at rest)
- Service account JSON plaintext (encrypted at rest)

**Rationale:**
- Settings are user-visible, easy to backup/restore
- Credentials are secret, never visible in UI or logs
- Separation of concerns: config vs. secrets

### 2. Backward Compatibility Strategy

**Problem:** Existing providers (google_translate, deepl) don't use new schema.

**Solution:**
- `ProviderConfigManager.load_config()` returns defaults for missing keys
- Legacy `rate_limit` key mapped to `max_requests_per_minute`
- Auth mode defaults to `NONE` (no auth required)

**Result:** Existing providers work unchanged, no migration needed.

### 3. Optional vs. Required Limits

**Required (always present):**
- `max_chars_per_request` (default: 10000)
- `max_requests_per_minute` (default: 60)
- `fail_closed` (default: True)

**Optional (None if not set):**
- `max_chars_per_day`
- `max_chars_per_month`
- `max_requests_per_day`

**Rationale:**
- Free providers (scraping, local NLLB) don't need daily/monthly limits
- Official APIs (Google Cloud) need strict budget guards
- Flexibility for different provider types

---

## Testing Results

### Unit Tests

```bash
pytest tests/test_provider_config.py -v
```

**Output:**
```
============================= test session starts =============================
collected 19 items

tests/test_provider_config.py::TestProviderAuthConfig::test_default_none_mode PASSED
tests/test_provider_config.py::TestProviderAuthConfig::test_api_key_configured PASSED
tests/test_provider_config.py::TestProviderAuthConfig::test_api_key_not_configured PASSED
tests/test_provider_config.py::TestProviderAuthConfig::test_service_account_configured_via_credential_id PASSED
tests/test_provider_config.py::TestProviderAuthConfig::test_service_account_configured_via_path PASSED
tests/test_provider_config.py::TestProviderAuthConfig::test_service_account_not_configured PASSED
tests/test_provider_config.py::TestProviderLimitsConfig::test_defaults PASSED
tests/test_provider_config.py::TestProviderLimitsConfig::test_budget_guards_detected PASSED
tests/test_provider_config.py::TestProviderRetryPolicy::test_defaults PASSED
tests/test_provider_config.py::TestProviderRetryPolicy::test_should_retry_429 PASSED
tests/test_provider_config.py::TestProviderRetryPolicy::test_should_not_retry_403 PASSED
tests/test_provider_config.py::TestProviderRetryPolicy::test_custom_retry_statuses PASSED
tests/test_provider_config.py::TestProviderConfigManager::test_load_default_config PASSED
tests/test_provider_config.py::TestProviderConfigManager::test_save_and_load_config PASSED
tests/test_provider_config.py::TestProviderConfigManager::test_backward_compatibility_legacy_rate_limit PASSED
tests/test_provider_config.py::TestProviderConfigManager::test_enabled_status PASSED
tests/test_provider_config.py::TestCredentialHelpers::test_api_key_credential_id PASSED
tests/test_provider_config.py::TestCredentialHelpers::test_service_account_credential_id PASSED
tests/test_provider_config.py::TestProviderUiMeta::test_defaults PASSED

============================= 19 passed in 0.74s ==============================
```

**Result:** ✅ ALL TESTS PASS

---

## Lessons Learned

### 1. Dataclasses for Type Safety

Using `@dataclass` instead of dicts provides:
- **Type hints** → Better IDE autocomplete
- **Default values** → Less boilerplate
- **is_configured()** methods → Clean validation

**Before (dict):**
```python
auth = {"mode": "api_key", "key_id": "..."}
if auth.get("mode") == "api_key" and auth.get("key_id"):
    # Use auth
```

**After (dataclass):**
```python
auth = ProviderAuthConfig(mode=ProviderAuthMode.API_KEY, api_key_credential_id="...")
if auth.is_configured():
    # Use auth
```

### 2. Credential IDs Instead of Values

**Anti-pattern:**
```python
config = {"api_key": "sk-1234..."}  # Plaintext in config!
```

**Best practice:**
```python
config = ProviderAuthConfig(api_key_credential_id="mt_provider:google:api_key")
# Later: api_key = cred_store.get_credential(config.api_key_credential_id)
```

**Benefits:**
- Config safe to log, backup, share
- Credentials encrypted, never in plaintext

### 3. Backward Compatibility via Defaults

**Strategy:**
- New fields optional (default values)
- Legacy keys honored (e.g., `rate_limit`)
- Existing code works unchanged

**Result:** Zero migration needed for existing providers.

---

## Next Steps

### Immediate (PATCH-04)

✅ Config schema ready
✅ Config manager ready
✅ Tests pass

**Ready for:** PATCH-04 - Implement `google_cloud_translate_provider.py`

**Provider will use:**
```python
config = config_mgr.load_config("google_cloud_translate")
if config.auth.mode == ProviderAuthMode.SERVICE_ACCOUNT_JSON:
    sa_json = config_mgr.get_credential(config.auth.service_account_credential_id)
    credentials = service_account.Credentials.from_service_account_info(json.loads(sa_json))
    client = translate_v3.TranslationServiceClient(credentials=credentials)
```

### Future (After PATCH-04)

⏳ Update existing providers to use new schema (optional, for consistency)
⏳ UI implementation (PATCH-06) to edit configs

---

## Files Summary

**Created:**
- `app/infra/translators/provider_config.py` (350 lines)
- `app/infra/translators/provider_config_manager.py` (260 lines)
- `tests/test_provider_config.py` (200 lines)
- `docs/PATCH-03-PROVIDER-CONFIG-COMPLETE.md` (this file)

**Total LOC:** ~850 lines

**Test Coverage:** 19 tests, 100% PASS

---

**PATCH-03 Status:** ✅ COMPLETE
**Next Patch:** PATCH-04 (Google Cloud Translate Provider Implementation)
