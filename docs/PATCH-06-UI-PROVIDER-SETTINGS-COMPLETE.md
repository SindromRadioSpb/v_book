# PATCH-06: UI (MT Provider Settings) - COMPLETE

**Date:** 2026-02-08
**Status:** ✅ COMPLETE
**Task:** Extend Provider Settings Dialog with advanced configuration UI

---

## Overview

Extended the existing `ProviderSettingsDialog` with advanced configuration UI for Google Cloud Translate provider:
- ✅ Added google_cloud_translate to provider registry
- ✅ New "Advanced Settings" tab for auth, budget guards, retry policy
- ✅ Service Account JSON upload/clear functionality
- ✅ Budget guards configuration (chars/requests per period)
- ✅ Retry policy configuration (max retries, backoff, jitter)
- ✅ Usage tracking display (current minute/day/month usage)
- ✅ Diagnostics placeholder (test API connection)
- ✅ Added to batch translate dialog force provider list
- ✅ All existing tests pass (15 tests)

**Test Coverage:** 15 existing UI tests pass, no regressions

---

## Files Modified

### 1. `app/ui/provider_settings_dialog.py` (+400 lines)

**Changes:**

1. **Added imports** for advanced configuration:
```python
from app.infra.translators.provider_config import (
    ProviderAuthMode,
    ProviderAuthConfig,
    ProviderLimitsConfig,
    ProviderRetryPolicy,
)
from app.infra.translators.provider_config_manager import ProviderConfigManager
from app.services.mt_usage_tracker import MTUsageTracker
from app.infra.security import CredentialStore
from app.services.db_service import DBService
```

2. **Added google_cloud_translate to PROVIDERS registry**:
```python
"google_cloud_translate": {
    "name": "Google Cloud Translate (Official v3)",
    "default_rate_limit": 60,
    "default_enabled": False,  # Disabled until auth configured
    "supports_advanced": True,  # Requires Service Account JSON
},
```

3. **Extended __init__** to initialize config manager:
```python
self.config_manager = ProviderConfigManager(settings_service)
self.advanced_widgets = {}  # For advanced config widgets
```

4. **Added "Advanced Settings" tab** with:
   - Provider selector (currently only google_cloud_translate)
   - Authentication section (SA JSON upload/clear)
   - Budget guards section (chars/requests per period)
   - Retry policy section (max retries, backoff, jitter)
   - Usage tracking section (current minute/day/month)
   - Diagnostics section (test API connection placeholder)

5. **Implemented key methods**:
   - `_create_advanced_settings_tab()` - Main advanced tab
   - `_create_gcp_settings()` - Google Cloud specific UI
   - `_load_gcp_sa_json()` - Load SA JSON from file
   - `_clear_gcp_sa_json()` - Clear stored credentials
   - `_refresh_gcp_usage()` - Display current usage statistics
   - `_test_gcp_connection()` - Test API connection (placeholder)
   - `_load_gcp_advanced_settings()` - Load config from QSettings
   - `_save_gcp_advanced_settings()` - Save config to QSettings

---

### 2. `app/ui/dialogs/batch_translate_dialog.py` (+1 line)

**Change:** Added `google_cloud_translate` to force provider dropdown:
```python
self.provider_combo.addItems([
    "google_translate",
    "google_cloud_translate",  # NEW
    "local_nllb",
    "deepl",
    "microsoft",
    "libretranslate",
])
```

---

### 3. `tests/test_provider_settings_dialog.py` (+2 lines)

**Change:** Updated test for 7 providers instead of 5:
```python
def test_chain_list_populated(dialog):
    """Chain list contains all providers."""
    # 7 providers: google_translate, google_cloud_translate, deepl, microsoft,
    # libretranslate, local_nllb, local_seamless
    assert dialog.chain_list.count() == 7
```

---

## UI Components Breakdown

### Advanced Settings Tab

```
┌─ Advanced Settings Tab ─────────────────────────────────────┐
│                                                               │
│ Provider: [Google Cloud Translate (Official v3) ▼]           │
│                                                               │
│ ┌─ Authentication ───────────────────────────────────────┐   │
│ │ Service Account JSON: [Load from File...] [Clear]     │   │
│ │ ✓ Service Account configured (project: my-project-123)│   │
│ └─────────────────────────────────────────────────────────┘   │
│                                                               │
│ ┌─ Budget Guards (Fail-Closed) ───────────────────────────┐  │
│ │ Max chars per request:  [10000    ] chars              │  │
│ │ Max chars per day:      [0        ] chars (0 = unlimited)│ │
│ │ Max chars per month:    [500000   ] chars (0 = unlimited)│ │
│ │ Max requests per minute:[60       ] req/min            │  │
│ │ Max requests per day:   [0        ] req (0 = unlimited)│  │
│ └─────────────────────────────────────────────────────────┘  │
│                                                               │
│ ┌─ Retry Policy (429 Rate Limit) ──────────────────────────┐ │
│ │ Max retries:        [3      ]                           │ │
│ │ Base backoff:       [1000   ] ms                        │ │
│ │ Jitter:             [✓] Use jitter (prevent thundering..│ │
│ └─────────────────────────────────────────────────────────┘  │
│                                                               │
│ ┌─ Current Usage ──────────────────────────────────────────┐ │
│ │ • This minute: 5 requests, 1250 chars                   │ │
│ │ • Today: 123 requests, 45000 chars                      │ │
│ │ • This month: 2000 requests, 350000 chars               │ │
│ │                                                          │ │
│ │ [Refresh Usage]                                         │ │
│ └─────────────────────────────────────────────────────────┘  │
│                                                               │
│ ┌─ Diagnostics ────────────────────────────────────────────┐ │
│ │ [Test API Connection]                                   │ │
│ └─────────────────────────────────────────────────────────┘  │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

---

## Features Implemented

### 1. Service Account JSON Management

**Load from File:**
- Opens QFileDialog to select JSON file
- Validates JSON structure (checks for `project_id` field)
- Saves to CredentialStore (encrypted at rest)
- Shows preview with project ID

**Clear:**
- Confirmation dialog before clearing
- Removes credential from CredentialStore
- Updates preview to show "Not configured"

**Security:**
- JSON never logged (only project_id shown)
- Stored in OS keyring + AES-256-GCM encrypted DB
- Clear separation from config (config has reference ID only)

### 2. Budget Guards Configuration

**Configurable Limits:**
- `max_chars_per_request`: 100-100,000 chars (default: 10,000)
- `max_chars_per_day`: 0 = unlimited, 1-10,000,000 (default: 0)
- `max_chars_per_month`: 0 = unlimited, 1-100,000,000 (default: 500,000 - free tier)
- `max_requests_per_minute`: 1-1,000 req/min (default: 60)
- `max_requests_per_day`: 0 = unlimited, 1-1,000,000 (default: 0)

**Special Value Display:**
- `0` shown as "Unlimited" in spinbox
- Suffix indicates unit (chars, req/min, etc.)

**Fail-Closed Policy:**
- Always enforced (cannot be disabled for official APIs)
- Requests rejected when limit exceeded

### 3. Retry Policy Configuration

**Configurable Parameters:**
- `max_retries`: 0-10 retries (default: 3)
- `base_backoff_ms`: 100-60,000 ms (default: 1000)
- `use_jitter`: Checkbox (default: enabled)

**Exponential Backoff:**
- Formula: `backoff = base_ms * (2 ** attempt)`
- Jitter: ±25% randomization to prevent thundering herd

### 4. Usage Tracking Display

**Real-Time Statistics:**
- Current minute: requests + chars
- Today: requests + chars
- This month: requests + chars

**Refresh Button:**
- Manually refresh usage statistics
- Auto-refreshes on tab load

**Error Handling:**
- Shows error message if DB unavailable
- Graceful degradation (shows "Loading..." initially)

### 5. Force Provider in Batch Translate

**Added to Dropdown:**
- Users can now select `google_cloud_translate` in batch translate dialog
- Format: `force:google_cloud_translate`
- Bypasses provider chain, directly uses GCP provider

---

## User Workflow

### Initial Setup (First-Time Configuration)

1. **Open Settings:**
   - From batch translate dialog: Click "Settings..." button
   - Opens "MT Provider Settings" dialog

2. **Navigate to Advanced Tab:**
   - Click "Advanced Settings" tab
   - Select "Google Cloud Translate (Official v3)" in dropdown

3. **Configure Authentication:**
   - Click "Load from File..." button
   - Select Service Account JSON file
   - Confirm "✓ Service Account configured (project: xxx)" appears

4. **Configure Budget Guards:**
   - Set `max_chars_per_month` to free tier limit (500,000)
   - Adjust other limits as needed
   - Leave per-day limits at 0 (unlimited) or set conservative values

5. **Save Settings:**
   - Click "OK" button
   - Settings saved to QSettings
   - Credentials saved to CredentialStore

6. **Enable Provider:**
   - Go back to "Rate Limits" tab
   - Check "Enabled" for Google Cloud Translate
   - Click "OK"

### Monitoring Usage

1. **View Current Usage:**
   - Open "MT Provider Settings"
   - Navigate to "Advanced Settings" tab
   - Select "Google Cloud Translate"
   - Usage statistics displayed in "Current Usage" section

2. **Refresh Statistics:**
   - Click "Refresh Usage" button
   - Statistics update from mt_usage table

### Testing Connection (Placeholder)

1. **Test API:**
   - Click "Test API Connection" button
   - (Currently shows placeholder message - implementation in PATCH-07)

---

## Settings Storage

### QSettings (INI Format)

**Location:** `%APPDATA%\HDLE_Premium\HDLE_Premium.ini` (Windows)

**Keys:**
```ini
[mt/providers/google_cloud_translate]
enabled=false
rate_limit=60
auth_mode=service_account_json
service_account_credential_id=mt_provider:google_cloud_translate:service_account_json
max_chars_per_request=10000
max_chars_per_day=0
max_chars_per_month=500000
max_requests_per_minute=60
max_requests_per_day=0
max_retries=3
base_backoff_ms=1000
use_jitter=true
fail_closed=true
```

### CredentialStore (Encrypted DB)

**Table:** `credentials` (created in migration 008)

**Entry:**
```
credential_id: "mt_provider:google_cloud_translate:service_account_json"
encrypted_value: <AES-256-GCM encrypted JSON>
created_at: 2026-02-08 12:00:00
```

**Security:**
- Master key stored in OS keyring (Windows Credential Manager)
- AES-256-GCM encryption at rest
- JSON never logged, only project_id shown in UI

---

## Testing Results

### Existing Tests

```bash
pytest tests/test_provider_settings_dialog.py -v
```

**Output:**
```
collected 15 items

test_dialog_creation PASSED
test_dialog_default_values PASSED
test_rate_limit_range PASSED
test_change_rate_limit PASSED
test_enable_disable_provider PASSED
test_save_settings PASSED
test_cancel_does_not_save PASSED
test_chain_list_populated PASSED  # Fixed (7 providers)
test_move_up PASSED
test_move_down PASSED
test_move_up_at_top_does_nothing PASSED
test_move_down_at_bottom_does_nothing PASSED
test_restore_defaults PASSED
test_restore_defaults_cancelled PASSED
test_load_saved_settings PASSED

15 passed in 1.62s
```

**Result:** ✅ ALL TESTS PASS (no regressions)

### Manual Testing

✅ Dialog opens successfully
✅ Advanced Settings tab renders correctly
✅ Service Account JSON upload works
✅ Budget guards spinboxes functional
✅ Retry policy checkboxes/spinboxes functional
✅ Usage tracking displays correctly
✅ Settings save/load roundtrip works

---

## Architecture Decisions

### 1. Extend Existing Dialog vs. New Dialog

**Decision:** Extend existing `ProviderSettingsDialog`.

**Rationale:**
- Consistent UX (all provider settings in one place)
- Reuse existing tabs (Rate Limits, Chain)
- Add "Advanced Settings" for provider-specific config

**Benefits:**
- Less code duplication
- Users don't need to learn new UI
- Advanced settings optional (hidden for simple providers)

### 2. Provider Selector in Advanced Tab

**Design:**
```python
self.advanced_provider_combo = QComboBox()
for provider_id, provider_info in self.PROVIDERS.items():
    if provider_info.get("supports_advanced", False):
        self.advanced_provider_combo.addItem(...)
```

**Future-Proofing:**
- Only providers with `supports_advanced=True` shown
- Easy to add DeepL API, Azure Translator, etc.
- Switch between providers without reopening dialog

### 3. Usage Tracking Refresh

**Decision:** Manual refresh button (not auto-refresh).

**Rationale:**
- Avoids DB polling overhead
- User controls when to check usage
- Simple implementation (no timers)

**Future:** Could add auto-refresh on tab activation.

### 4. Test Connection Placeholder

**Decision:** Placeholder button for now, implementation in PATCH-07.

**Rationale:**
- PATCH-06 focuses on UI/settings
- PATCH-07 will integrate provider into app (test connection requires provider registration)
- Button present to show future capability

---

## Known Limitations

### 1. Test Connection Not Implemented

**Current State:** Button shows placeholder message.

**Future (PATCH-07):**
- Translate test phrase (e.g., "Hello" → Russian)
- Show success/error dialog
- Verify auth + config

### 2. Single Advanced Provider

**Current State:** Only google_cloud_translate has advanced settings.

**Future:**
- Add DeepL API (API key auth, usage tracking)
- Add Azure Translator (subscription key auth)
- Generalize UI components for reuse

### 3. No Usage Graphs

**Current State:** Text display only (requests + chars).

**Future:**
- Add QChart graphs (daily/monthly trends)
- Export usage reports (CSV)
- Usage alerts (approaching limit)

---

## Next Steps

### Immediate (PATCH-07)

✅ UI implementation complete
✅ Settings save/load works
✅ Tests pass

**Ready for:** PATCH-07 - Integration (register provider, wire to services)

**TODO in PATCH-07:**
- Register GoogleCloudTranslateProvider in providers_registry
- Update BatchMTTranslateService to provide session for usage tracking
- Implement test connection functionality
- Add provider to default chain
- Test end-to-end batch translation with GCP provider

### After PATCH-07

⏳ PATCH-08 - Documentation (user guide, setup instructions, release notes)

---

## Files Summary

**Modified:**
- `app/ui/provider_settings_dialog.py` (+400 lines)
- `app/ui/dialogs/batch_translate_dialog.py` (+1 line)
- `tests/test_provider_settings_dialog.py` (+2 lines)
- `docs/PATCH-06-UI-PROVIDER-SETTINGS-COMPLETE.md` (this file)

**Total LOC Added:** ~600 lines (including docs)

**Test Coverage:** 15 existing tests pass, no regressions

---

**PATCH-06 Status:** ✅ COMPLETE
**Next Patch:** PATCH-07 (Integration - register provider, wire to services)
