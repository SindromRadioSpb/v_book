# Google Cloud Translate API v3 Provider - Implementation Plan

**Date:** 2026-02-08
**Status:** PATCH-00 - Discovery Complete
**Target:** Add official Google Cloud Translation API (Advanced v3) provider with enterprise-grade security

---

## Executive Summary

This plan adds `google_cloud_translate` provider to HDLE Premium, providing:
- **Official Google Cloud Translation API v3 (Advanced)** via `google-cloud-translate` SDK
- **Secure credential storage** using existing `CredentialStore` (OS keyring + AES-256-GCM)
- **Budget guards** (max chars per request/minute/day/month, fail-closed)
- **Rate limit handling** (429 retry with exponential backoff, 403 classification)
- **Unified UX** for all providers (auth, limits, retry policy, diagnostics)

---

## Architecture Discovery

### Existing Provider Infrastructure

**BaseProvider Contract** (`app/infra/translators/base_provider.py`):
```python
class BaseProvider(ABC):
    @property @abstractmethod
    def provider_id(self) -> str
    @property @abstractmethod
    def display_name(self) -> str
    @property @abstractmethod
    def supports_glossary(self) -> bool
    @abstractmethod
    def translate(request: TranslationRequest) -> TranslationResult
    def healthcheck(self) -> bool
```

**ProvidersRegistry** (`app/infra/translators/providers_registry.py`):
- Singleton registry: `register(provider)`, `get(provider_id)`, `list_providers()`
- Providers register at app startup (see `app/main.py`)

**Force Provider Mode** (M11 implementation):
- Format: `"force:<provider_id>"` (e.g., `"force:google_cloud_translate"`)
- Implementation: `BatchMTTranslateService._translate_and_write()` line 290-347
- Directly calls `provider.translate()` without fallback

**Provider Chain Mode**:
- Format: `"chain"`
- Uses `TranslationService.resolve_translation()` to try providers in order
- Chain order configured in UI (Provider Settings Dialog, Tab 2)

### Secure Credential Storage (Already Exists! ✅)

**CRITICAL FINDING:** HDLE Premium already has production-grade credential storage:

**File:** `app/infra/security/credentials.py`

**Architecture:**
- **Master key:** Stored in OS keyring (Windows Credential Manager, macOS Keychain, Linux Secret Service)
  - Service: `"HDLE_Premium"`
  - Key: `"master_encryption_key"`
- **Credential values:** Encrypted with AES-256-GCM, stored in `credentials` table
- **Database table:**
  ```sql
  CREATE TABLE credentials (
      key TEXT PRIMARY KEY,
      encrypted_value TEXT NOT NULL,
      updated_at TEXT
  )
  ```

**API:**
```python
from app.infra.security import CredentialStore

with db_service.get_session() as session:
    store = CredentialStore(session)
    store.set_credential("google_cloud_translate_api_key", "AIza...")
    api_key = store.get_credential("google_cloud_translate_api_key")
    store.delete_credential("google_cloud_translate_api_key")
```

**Security Properties:**
- ✅ Master key never touches disk (OS keyring)
- ✅ All values encrypted at rest (AES-256-GCM with auth tag)
- ✅ Tamper detection via auth tag
- ✅ Key rotation supported (`reset_master_key()`)

**RESULT:** We do NOT need to implement PATCH-02 (secure secrets storage) - it already exists!

### Provider Settings UI

**File:** `app/ui/provider_settings_dialog.py`

**Current Implementation:**
- **Tab 1: Rate Limits** - requests per minute per provider
- **Tab 2: Provider Chain** - drag-drop reordering
- **Master enable checkbox** - global MT enable/disable

**Hardcoded Provider List:**
```python
PROVIDERS = {
    "google_translate": {...},  # Free web scraping
    "deepl": {...},
    "microsoft": {...},
    "libretranslate": {...},
    "local_nllb": {...},
    "local_seamless": {...},
}
```

**GAP:** No auth UI, no budget guards UI, no retry policy UI, no test credentials button.

**TODO:** Extend to support:
- Auth configuration (API key / Service Account JSON)
- Budget guards (chars per request/minute/day/month)
- Retry policy (max retries, backoff)
- Test credentials button

### Usage Tracking (Needs Implementation)

**CRITICAL GAP:** No usage tracking for budget guards.

**TODO:** Create `mt_usage` table to track:
- `provider_id`, `ts_bucket_minute`, `chars_used`, `requests_count`
- Atomic counters for fail-closed budget enforcement

---

## Implementation Decisions

### 1. Authentication Method

**Supported Auth Modes:**
- **API Key** - Google Cloud Translation API v2 (Basic) supports API keys
- **Service Account JSON** - Google Cloud Translation API v3 (Advanced) requires OAuth/SA

**Decision:**
- Support **both** modes in UI
- v3 provider will **reject API key mode** with clear error:
  > "Google Cloud Translation API v3 requires Service Account JSON. API keys are only supported in v2 (Basic). Please configure Service Account credentials or use a different provider."

**Future Option:** Create separate `google_cloud_translate_basic_v2` provider for API key support if needed.

### 2. Secrets Storage Format

**Credential Keys:**
- API Key: `"mt_provider:google_cloud_translate:api_key"`
- Service Account JSON: `"mt_provider:google_cloud_translate:service_account_json"`

**Storage:**
- Use existing `CredentialStore` (OS keyring + encrypted DB)
- No plaintext on disk
- UI shows "Configured ✅" / "Not set" (no reveal button for security)

### 3. Budget Guards & Limits

**Config Storage:** QSettings (same as existing rate limits)

**Settings Keys:**
```python
"mt/providers/google_cloud_translate/max_chars_per_request" = 10000  # Safe default
"mt/providers/google_cloud_translate/max_requests_per_minute" = 60
"mt/providers/google_cloud_translate/max_chars_per_minute" = 300000
"mt/providers/google_cloud_translate/max_chars_per_day" = 5000000
"mt/providers/google_cloud_translate/max_chars_per_month" = 50000000
"mt/providers/google_cloud_translate/fail_closed" = true
```

**Enforcement:**
1. Before each translation: check `len(text)` vs limits
2. Query `mt_usage` table for current counters
3. If exceeded: fail-closed (return error, do NOT translate)
4. If success: increment counters atomically

### 4. Error Handling Policy

**429 (Rate Limit):**
- Retry with exponential backoff + jitter
- Respect `Retry-After` header if present
- Max retries: 3 (configurable)
- Base backoff: 1000ms, max backoff: 10000ms

**403 (Forbidden) Classification:**
- `PERMISSION_DENIED` → "Service account lacks required permissions (roles/cloudtranslate.user)"
- `BILLING_DISABLED` → "Billing not enabled for project"
- `QUOTA_EXCEEDED` → "Monthly quota exceeded"
- Generic 403 → "Authentication or authorization error"

**User-Friendly Messages:**
- Never log API key / JSON content
- Log only: trace_id, provider_id, error_code, char_count
- UI shows actionable error: "Click here to configure credentials" or "Quota exceeded, upgrade plan"

### 5. Logging Policy

**Allowed in Logs:**
- `job_id`, `trace_id`, `provider_id`
- `source_lang`, `target_lang`, `char_count` (length of text)
- Error codes (`429`, `403`, `PERMISSION_DENIED`)
- Timing metrics (`latency_ms`)

**FORBIDDEN in Logs:**
- API key (even partial)
- Service account JSON (any part)
- Full source text (only log length)
- Full translated text (only log length)

---

## Patch Series

### ~~PATCH-02~~ - Secure secrets storage ✅ ALREADY EXISTS

**No implementation needed!** Use existing `app/infra/security/credentials.py`.

### PATCH-01 - Dependency + packaging readiness

1. Add to `pyproject.toml`:
   ```toml
   "google-cloud-translate>=3.15.0",
   "google-auth>=2.28.0",
   ```

2. Update `build/v_book.spec` hiddenimports:
   ```python
   hiddenimports=[
       # ... existing ...
       'google.cloud.translate_v3',
       'google.auth',
       'google.api_core',
       'grpc',
   ]
   ```

3. Create diagnostic script:
   - `scripts/diag_google_cloud_translate_import.py`
   - Test: import SDK, print versions, exit

### PATCH-03 - Provider config schema (unified for all providers)

**File:** `app/infra/translators/provider_config.py` (new)

**Classes:**
```python
@dataclass
class ProviderAuthConfig:
    mode: str  # "none" | "api_key" | "service_account_json"
    api_key_credential_id: Optional[str]
    service_account_credential_id: Optional[str]

@dataclass
class ProviderLimitsConfig:
    max_chars_per_request: int = 10000
    max_requests_per_minute: int = 60
    max_chars_per_minute: int = 300000
    max_chars_per_day: int = 5000000
    max_chars_per_month: int = 50000000
    fail_closed: bool = True

@dataclass
class ProviderRetryPolicy:
    max_retries: int = 3
    base_backoff_ms: int = 1000
    max_backoff_ms: int = 10000
    retry_on_status: List[int] = [429, 503]
```

**Backward compatibility:**
- Existing providers (google_translate, deepl, etc.) default to `mode="none"`
- Limits optional (read-only defaults in UI)

### PATCH-04 - Implement `google_cloud_translate_provider.py`

**File:** `app/infra/translators/providers/google_cloud_translate_provider.py`

**Implementation:**
1. Check auth mode (reject if api_key for v3)
2. Initialize client from service account JSON
3. Translate request:
   - Check budget guards before API call
   - Call v3 API
   - Record usage atomically
4. Error handling:
   - 429 → retry with backoff
   - 403 → classify (permission/billing/quota)
   - Network errors → retry policy
5. Logging:
   - trace_id, provider_id, char_count, latency_ms
   - NO secrets, NO full text

### PATCH-05 - Usage counters (for budget guards)

**Migration:** `app/infra/migrations/009_mt_usage_tracking.sql`

```sql
CREATE TABLE IF NOT EXISTS mt_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT NOT NULL,
    ts_bucket_minute TEXT NOT NULL,  -- YYYYMMDDHHMM
    chars_used INTEGER NOT NULL DEFAULT 0,
    requests_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    UNIQUE(provider_id, ts_bucket_minute)
);

CREATE INDEX IF NOT EXISTS idx_mt_usage_provider_ts
    ON mt_usage(provider_id, ts_bucket_minute);
```

**Service:** `app/services/mt_usage_tracker.py`

```python
class MTUsageTracker:
    def can_spend(self, provider_id: str, chars: int, limits: ProviderLimitsConfig) -> Tuple[bool, str]
    def record_spend(self, provider_id: str, chars: int, requests: int = 1) -> None
```

### PATCH-06 - UI: MT Provider Settings (unified UX)

**Update:** `app/ui/provider_settings_dialog.py`

**Add Tab 3: Authentication**

For each provider:
- Dropdown: "None" | "API Key" | "Service Account JSON"
- If API Key:
  - Masked text field
  - "Save" button → CredentialStore
  - "Configured ✅" / "Not set"
  - "Clear" button
- If Service Account JSON:
  - "Choose file..." button
  - "Configured ✅" / "Not set"
  - "Clear" button
- "Test Credentials" button (calls healthcheck with small test translation)

**Update Tab 1: Rate Limits & Budget Guards**

Add fields:
- Max chars per request
- Max chars per minute/day/month
- Fail-closed toggle (default ON for official APIs)

**Add Tab 4: Retry Policy**

Show defaults, optionally editable:
- Max retries
- Base backoff / Max backoff
- Retry on status codes

**Unified Layout:**
For all providers, show same sections (collapsed if "Not applicable"):
- Enabled checkbox
- Auth (if supported)
- Limits & budget guards
- Retry policy

### PATCH-07 - Integration: provider chain + force provider lists

1. Register `google_cloud_translate` in `app/main.py`:
   ```python
   from app.infra.translators.providers.google_cloud_translate_provider import GoogleCloudTranslateProvider
   registry.register(GoogleCloudTranslateProvider())
   ```

2. Add to `ProviderSettingsDialog.PROVIDERS`:
   ```python
   "google_cloud_translate": {
       "name": "Google Cloud Translate (Official v3)",
       "default_rate_limit": 60,
       "default_enabled": False,  # Requires credentials
   }
   ```

3. Add to `BatchTranslateDialog` force provider dropdown (dynamic list from registry)

### PATCH-08 - Documentation + release notes

**Create:** `docs/INTEGRATION_GOOGLE_CLOUD_TRANSLATE.md`

**Contents:**
- How to get Google Cloud project
- How to enable Cloud Translation API
- How to create service account + download JSON
- Required IAM roles: `roles/cloudtranslate.user`
- How to set up billing alerts
- Cost estimation (free tier: 500k chars/month, then $20/million)

**Update:** `docs/RELEASE_NOTES_M12.md` (or append to README)

---

## Tests

### Unit Tests

**File:** `tests/test_google_cloud_translate_provider.py`

- ✅ `test_v3_rejects_api_key_mode` - API key auth returns error
- ✅ `test_service_account_auth` - SA JSON loads correctly
- ✅ `test_budget_guard_max_chars_per_request` - Exceeding limit fails
- ✅ `test_retry_policy_on_429` - Mock 429, verify backoff
- ✅ `test_403_classification` - Mock different 403 causes
- ✅ `test_no_secrets_in_logs` - Assert API key/JSON never logged

**File:** `tests/test_mt_usage_tracker.py`

- ✅ `test_can_spend_within_limits` - Under limit → True
- ✅ `test_can_spend_exceed_daily` - Over daily limit → False
- ✅ `test_record_spend_atomic` - Concurrent requests don't double-count

### Integration Tests (Mocked)

**File:** `tests/test_google_cloud_translate_integration.py`

- Mock `google.cloud.translate_v3.TranslationServiceClient`
- Test 429 + Retry-After
- Test 403 → user-friendly error
- Test success → TM entry created

### Manual Smoke (Real Credentials Required)

1. ✅ Configure service account JSON in UI
2. ✅ Add to provider chain
3. ✅ Dictionary: translate 2 rows → success
4. ✅ Terms: translate 2 rows → success
5. ✅ Force provider: select google_cloud_translate → success
6. ✅ Budget guard: set max_requests_per_minute=1, translate 2 rows → second fails
7. ✅ Invalid JSON: paste invalid JSON → user-friendly error, no crash

### Packaging Test

1. ✅ Build onedir: `pyinstaller --clean build/v_book.spec`
2. ✅ Run exe, configure google_cloud_translate
3. ✅ Translate 1-2 rows via official provider → success

---

## Definition of Done

### Functional
- ✅ `google_cloud_translate` provider available in **chain** and **force**
- ✅ UI allows configuring **service account JSON** (API key rejected with clear error)
- ✅ Real translations work (Dictionary + Terms)

### Security
- ✅ Secrets never logged or displayed in plaintext
- ✅ Secrets stored in CredentialStore (OS keyring + encrypted DB)
- ✅ "Clear credentials" button works

### Reliability
- ✅ 403/429 → user-friendly errors, retry/backoff for 429
- ✅ Budget guards fail-closed
- ✅ Logs have trace_id/job_id, NO secrets, NO full text

### UX (Premium)
- ✅ Unified UI for all providers (Auth/Limits/Retry/Diagnostics tabs)
- ✅ "Test credentials" button

### QA Evidence
- ✅ Unit + integration tests green
- ✅ Manual smoke passed
- ✅ PyInstaller build works

### Git
- ✅ Commit only after tests pass
- ✅ Message: `feat(mt): add google_cloud_translate v3 provider with secure secrets + budget guards + 403/429 handling`

---

## Risks & Mitigations

### Risk 1: PyInstaller + grpc/protobuf packaging

**Mitigation:**
- Add explicit hiddenimports in spec
- Test build early (PATCH-01)
- Diagnostic script catches import errors pre-coding

### Risk 2: Budget guard race conditions

**Mitigation:**
- Atomic DB operations (INSERT ... ON CONFLICT)
- Transaction isolation
- Unit tests for concurrent access

### Risk 3: Service account JSON size limit

**Mitigation:**
- CredentialStore has `CREDENTIAL_VALUE_MAX_LENGTH = 100000` (100KB)
- SA JSON typically ~2-3KB, safe margin

### Risk 4: Breaking existing providers

**Mitigation:**
- Backward compatibility: new config optional
- Existing providers default to `auth_mode="none"`
- Unit tests for all providers after schema change

---

## Cost Estimation (for documentation)

**Google Cloud Translation API v3 Pricing (2026):**
- **Free tier:** 500,000 characters/month (never expires)
- **Paid:** $20 per 1 million characters

**Example Usage:**
- Hebrew Wikipedia baseline: 387k documents, ~10M tokens → ~50M characters
- Batch translate 1000 lemmas (avg 5 chars/lemma) → 5k characters → **FREE**
- Batch translate 10k lemmas → 50k characters → **FREE**
- Translate entire baseline (50M chars) → **$1000** (one-time)

**Recommendation:** Set budget guard `max_chars_per_month=500000` to stay in free tier.

---

## Next Steps

1. **User Approval** - Review this plan, approve or request changes
2. **PATCH-01** - Add dependencies + diagnostic script
3. **PATCH-03** - Provider config schema
4. **PATCH-04** - Implement provider
5. **PATCH-05** - Usage tracking
6. **PATCH-06** - UI
7. **PATCH-07** - Integration
8. **PATCH-08** - Documentation
9. **Manual smoke test** (requires real Google Cloud project + SA JSON)
10. **Git commit + release**

---

**Plan Status:** ✅ Ready for review and approval
