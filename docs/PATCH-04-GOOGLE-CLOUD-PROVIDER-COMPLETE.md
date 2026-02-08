# PATCH-04: Google Cloud Translate Provider - COMPLETE

**Date:** 2026-02-08
**Status:** ✅ COMPLETE
**Task:** Implement google_cloud_translate_provider.py (Official API v3)

---

## Overview

Implemented production-grade Google Cloud Translation API v3 provider with:
- ✅ Service Account JSON authentication (API key rejected for v3)
- ✅ Budget guards (max chars per request, per-request validation)
- ✅ 429 retry with exponential backoff + jitter
- ✅ 403 error classification (permission/billing/quota/API disabled)
- ✅ Secure credential loading (CredentialStore)
- ✅ Comprehensive error handling (NO exceptions leaked)
- ✅ Privacy-safe logging (NO secrets, NO full text)

**Test Coverage:** 16 unit tests, **ALL PASS** ✅

---

## Files Created

### 1. `app/infra/translators/providers/google_cloud_translate_provider.py` (485 lines)

**Class:** `GoogleCloudTranslateProvider`

**Key Methods:**
- `translate(request)` → TranslationResult (main entry point)
- `_initialize_client()` → Load SA JSON, create Google Cloud client
- `_translate_with_retry()` → Retry loop with exponential backoff
- `_calculate_backoff()` → Exponential backoff with optional jitter
- `_classify_403_error()` → User-friendly 403 error messages

**Architecture:**
```python
translate(request)
  ↓
1. Initialize client (lazy, once)
   - Load SA JSON from CredentialStore
   - Create google.cloud.translate_v3.TranslationServiceClient
2. Validate budget guards
   - Check max_chars_per_request
   - TODO (PATCH-05): Check usage tracking
3. Translate with retry
   - Call API (translate_text)
   - On 429: retry with backoff
   - On 403: classify error
   - On success: return translated text
4. Return TranslationResult
   - Never raise exceptions
   - Log trace_id, char_count, latency
   - NEVER log secrets or full text
```

**Example Usage:**
```python
from app.infra.translators.providers.google_cloud_translate_provider import (
    GoogleCloudTranslateProvider,
)
from app.infra.translators.base_provider import TranslationRequest

provider = GoogleCloudTranslateProvider()

request = TranslationRequest(
    source_text="שלום",
    source_lang="he",
    target_lang="ru",
    trace_id="test-123",
)

result = provider.translate(request)

if result.is_success:
    print(f"Translation: {result.translated_text}")
else:
    print(f"Error: {result.error_message}")
```

---

### 2. `tests/test_google_cloud_translate_provider.py` (340 lines)

**Test Coverage:** 16 tests, **ALL PASS** ✅

**Test Classes:**
- `TestApiKeyRejection` (1 test) - v3 rejects API key mode
- `TestServiceAccountAuth` (2 tests) - SA JSON loading, project_id validation
- `TestBudgetGuards` (1 test) - max_chars_per_request enforcement
- `TestRetryPolicy` (2 tests) - 429 retry, max retries exceeded
- `Test403Classification` (4 tests) - Permission/billing/quota/API disabled
- `TestBackoffCalculation` (2 tests) - Exponential backoff, jitter
- `TestProviderMeta` (4 tests) - provider_id, display_name, capabilities

**Key Tests:**
```python
def test_api_key_mode_rejected():
    """v3 rejects API key with clear error."""
    # Config with API_KEY mode
    # translate() returns AUTH error
    # Error message mentions "Service Account JSON" and "v2"

def test_retry_on_429():
    """429 retries with exponential backoff."""
    # Mock client: 429, 429, success
    # 3 API calls made
    # Result succeeds on 3rd attempt
    # meta["attempt"] == 3

def test_403_classification():
    """403 errors classified into actionable messages."""
    # "Permission denied" → "Ensure roles/cloudtranslate.user"
    # "Billing not enabled" → "Enable billing at console.cloud.google.com/billing"
    # "Quota exceeded" → "Check quota usage or upgrade plan"
```

**Test Results:**
```
16 passed, 2 warnings in 2.16s
```

**Warnings:**
```
DeprecationWarning: Type google._upb._message.MessageMapContainer uses PyType_Spec...
```
Non-critical protobuf/Python 3.13 compatibility warning.

---

## Implementation Details

### 1. Authentication Strategy

**Supported:**
- ✅ Service Account JSON (from CredentialStore or file path)

**Rejected:**
- ❌ API Key (v3 requires OAuth/SA, returns clear error)
- ❌ NONE mode (returns clear error to configure credentials)

**SA JSON Loading:**
```python
# From CredentialStore (encrypted DB)
if config.auth.service_account_credential_id:
    sa_json_str = config_mgr.get_credential(credential_id)
    sa_info = json.loads(sa_json_str)

# From file
elif config.auth.service_account_path:
    with open(config.auth.service_account_path) as f:
        sa_info = json.load(f)

# Create credentials
credentials = service_account.Credentials.from_service_account_info(sa_info)
client = translate_v3.TranslationServiceClient(credentials=credentials)
```

**Security:**
- SA JSON NEVER logged (even on error)
- Only project_id logged for debugging
- Credential IDs referenced, not values

### 2. Budget Guards

**Per-Request Validation:**
```python
char_count = len(request.source_text)
if char_count > config.limits.max_chars_per_request:
    return TranslationResult(
        error_kind=TranslationErrorKind.INVALID_REQUEST,
        error_message=f"Text too long: {char_count} chars (max {max_chars})"
    )
```

**Usage Tracking (TODO PATCH-05):**
```python
# Check chars per day/month, requests per minute
if config.limits.has_budget_guards():
    # Query mt_usage table
    # If exceeded: fail-closed (return error)
    # If OK: record_spend(provider_id, char_count)
```

### 3. Retry Policy

**429 (Rate Limit):**
```python
while attempt <= max_retries:
    try:
        response = client.translate_text(request)
        return success
    except TooManyRequests:
        if not should_retry(429, attempt):
            return rate_limit_error
        backoff_ms = calculate_backoff(attempt, base_ms, max_ms, use_jitter)
        time.sleep(backoff_ms / 1000.0)
        attempt += 1
```

**Backoff Formula:**
```python
backoff = min(base_ms * (2 ** attempt), max_ms)
if use_jitter:
    jitter = random.uniform(0.75, 1.25)  # +/- 25%
    backoff = int(backoff * jitter)
```

**Example:**
- Attempt 0: 1000ms (base)
- Attempt 1: 2000ms (base * 2^1)
- Attempt 2: 4000ms (base * 2^2)
- Attempt 3: 8000ms (base * 2^3)
- Attempt 4: 10000ms (capped to max)

### 4. Error Classification

**403 → User-Friendly Messages:**

| API Error | User-Friendly Message | Action |
|-----------|----------------------|--------|
| "permission denied" | Service account lacks permissions | Add `roles/cloudtranslate.user` role |
| "billing not enabled" | Billing not enabled | Enable billing at console.cloud.google.com |
| "quota exceeded" | Quota limit reached | Check quota usage or upgrade |
| "api not enabled" | Translation API not enabled | Enable at console.cloud.google.com/apis |
| Generic 403 | Authorization error | Generic fallback message |

**Example:**
```python
def _classify_403_error(error_message: str) -> str:
    if "permission" in error_message.lower():
        return (
            "Permission denied: Service account lacks required permissions. "
            "Ensure it has 'roles/cloudtranslate.user' role in IAM settings."
        )
    # ... other classifications
```

### 5. Logging Policy

**Allowed in Logs:**
- ✅ `trace_id`, `provider_id`, `attempt`
- ✅ `char_count` (length of text)
- ✅ `latency_ms`, `project_id`
- ✅ Error codes (`429`, `403`, `PERMISSION_DENIED`)

**FORBIDDEN in Logs:**
- ❌ API key (N/A for v3)
- ❌ Service account JSON (any part)
- ❌ Full source text (only length)
- ❌ Full translated text (only length)

**Example:**
```python
logger.info(
    f"[{self.provider_id}] [{trace_id}] Success "
    f"(chars: {len(request.source_text)}, latency: {latency_ms}ms)"
)
# NOT: f"Translated '{source_text}' to '{translated_text}'"
```

---

## Testing Evidence

### Unit Tests

```bash
pytest tests/test_google_cloud_translate_provider.py -v
```

**Output:**
```
collected 16 items

test_api_key_mode_rejected PASSED
test_sa_json_from_credential_store PASSED
test_sa_json_missing_project_id PASSED
test_max_chars_per_request_exceeded PASSED
test_retry_on_429 PASSED
test_max_retries_exceeded_on_429 PASSED
test_403_classification[Permission denied] PASSED
test_403_classification[Billing not enabled] PASSED
test_403_classification[Quota exceeded] PASSED
test_403_classification[API is not enabled] PASSED
test_backoff_without_jitter PASSED
test_backoff_with_jitter PASSED
test_provider_id PASSED
test_display_name PASSED
test_supports_glossary PASSED
test_supports_batch PASSED

16 passed, 2 warnings in 2.16s
```

**Result:** ✅ ALL TESTS PASS

### Manual Smoke Test (Deferred)

⏳ **Requires real Google Cloud project + SA JSON**

**Steps** (to run later):
1. Create Google Cloud project
2. Enable Cloud Translation API
3. Create service account with `roles/cloudtranslate.user`
4. Download SA JSON
5. Configure in UI (PATCH-06)
6. Translate 1-2 rows via force provider
7. Verify translation appears in TM

---

## Lessons Learned

### 1. Lazy Client Initialization

**Problem:** Client initialization may fail (no SA JSON, invalid JSON, API disabled).

**Solution:** Defer initialization until first `translate()` call:
```python
def translate(request):
    try:
        self._initialize_client()  # Lazy, once
    except ValueError as e:
        return TranslationResult(error_kind=AUTH, error_message=str(e))
```

**Benefits:**
- Provider registration doesn't block app startup
- Errors returned as TranslationResult (not exceptions)
- Healthcheck can detect config issues early

### 2. Exponential Backoff with Jitter

**Why jitter?**
- Multiple concurrent requests hitting 429 at same time
- Without jitter: all retry at same time → thundering herd
- With jitter: retries spread over time window

**Implementation:**
```python
backoff = base_ms * (2 ** attempt)
if use_jitter:
    jitter = random.uniform(0.75, 1.25)  # +/- 25%
    backoff = int(backoff * jitter)
```

**Result:** Retries distributed, reduces server load spikes.

### 3. User-Friendly 403 Messages

**Anti-pattern:**
```
Error: 403 Forbidden
```

**Best practice:**
```
Permission denied: Service account lacks required permissions.
Ensure it has 'roles/cloudtranslate.user' role in IAM settings.
```

**Benefits:**
- User knows exactly what's wrong
- Actionable guidance (add role, enable billing, etc.)
- Reduces support requests

### 4. No Exceptions in translate()

**BaseProvider contract:** `translate()` MUST NOT raise exceptions.

**Implementation:**
```python
def translate(request):
    try:
        # ... all logic
    except Exception as e:
        return TranslationResult(
            error_kind=UNKNOWN,
            error_message=f"Unexpected error: {e}"
        )
```

**Benefits:**
- Caller doesn't need try/except
- Errors handled uniformly (error_kind enum)
- Chain mode can fallback to next provider

---

## Known Limitations

### 1. Usage Tracking Not Implemented (PATCH-05)

**Current State:**
- Per-request limit enforced (`max_chars_per_request`)
- Usage tracking deferred to PATCH-05

**Workaround:**
- Set conservative `max_chars_per_request` (e.g., 5000)
- Monitor Google Cloud Console for usage

**Future (PATCH-05):**
- Query `mt_usage` table before translation
- Fail-closed if chars_per_day/month exceeded
- Atomic `record_spend()` after success

### 2. Glossary Support Not Implemented

**Current State:** `supports_glossary = False`

**Future:**
- Upload glossary via Cloud Translation API
- Pass glossary reference in translate request
- Requires UI for glossary management

### 3. Batch Translation Not Implemented

**Current State:** One-by-one translation

**Future:**
- Use `batch_translate_text()` API
- Requires async result polling
- Suitable for large batch jobs (1000+ rows)

---

## Next Steps

### Immediate (PATCH-05)

✅ Provider implementation ready
✅ Tests pass

**Ready for:** PATCH-05 - Usage Tracking (mt_usage table)

**TODO in PATCH-05:**
- Create `mt_usage` table (migration)
- Implement `MTUsageTracker` service
- Integrate into provider (`can_spend()`, `record_spend()`)
- Test concurrent access (atomic counters)

### After PATCH-05

⏳ PATCH-06 - UI (MT Provider Settings)
⏳ PATCH-07 - Integration (register provider, add to UI lists)
⏳ PATCH-08 - Documentation (setup guide, release notes)

---

## Files Summary

**Created:**
- `app/infra/translators/providers/google_cloud_translate_provider.py` (485 lines)
- `tests/test_google_cloud_translate_provider.py` (340 lines)
- `docs/PATCH-04-GOOGLE-CLOUD-PROVIDER-COMPLETE.md` (this file)

**Total LOC:** ~850 lines

**Test Coverage:** 16 tests, 100% PASS

---

**PATCH-04 Status:** ✅ COMPLETE
**Next Patch:** PATCH-05 (Usage Tracking for Budget Guards)
