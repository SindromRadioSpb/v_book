# P1 Translation Pro - Implementation Plan

**Status:** PATCH-P1-T03 (MT Provider Chain Integration)
**Date:** 2026-02-07
**Owner:** Staff Engineer/Architect

---

## PATCH-P1-T00: Foundation (COMPLETE)

- Created base architecture docs
- Defined provider contract (`BaseProvider`, `TranslationRequest`, `TranslationResult`)
- Defined `TranslationErrorKind` taxonomy for fallback logic
- Created `ProvidersRegistry` singleton

---

## PATCH-P1-T01: Provider Base Classes (COMPLETE)

**Files:**
- `app/infra/translators/base_provider.py` - Abstract base class
- `app/infra/translators/providers_registry.py` - Registry singleton

**Contract:**
```python
class BaseProvider(ABC):
    @property
    def provider_id(self) -> str: ...
    @property
    def display_name(self) -> str: ...
    @property
    def supports_glossary(self) -> bool: ...

    def translate(self, request: TranslationRequest) -> TranslationResult:
        """MUST NOT raise exceptions. Return error_kind on failure."""
        pass
```

**TranslationErrorKind:**
- `NETWORK` - Connection timeout, network errors
- `AUTH` - Invalid API key, unauthorized
- `RATE_LIMIT` - 429 rate limit exceeded
- `QUOTA` - 402/403 quota exceeded
- `SERVER` - 500/502/503/504 server errors
- `INVALID_REQUEST` - 400 bad request
- `UNSUPPORTED` - Feature not supported (e.g., language pair)
- `UNKNOWN` - Catch-all for unexpected errors

---

## PATCH-P1-T02: Provider Implementations (COMPLETE)

**Files:**
- `app/infra/translators/providers/mock_provider.py` - For testing
- `app/infra/translators/providers/deepl_provider.py` - DeepL Pro/Free
- `app/infra/translators/providers/libretranslate_provider.py` - LibreTranslate (free/self-hosted)
- `app/infra/translators/providers/microsoft_translator_provider.py` - Azure Cognitive Services

**Tests:** `tests/test_p1_translation_providers_offline.py` (14/14 PASS)

---

## PATCH-P1-T03: TranslationService Integration (IN PROGRESS)

### Integration Point

**File:** `app/services/translation_service.py`
**Method:** `resolve_translation(..., use_mt: bool = False)`
**Location:** Line 104-105 (after MT cache lookup, before returning empty result)

**Existing comment:**
```python
# 5. MT provider (not implemented yet - would go here)
# result = self._query_mt_provider(...)
```

**Design Decision:**
- **Two `TranslationResult` classes exist:**
  - `app.services.translation_service.TranslationResult` (existing, for TM/dict/MT unified API)
  - `app.infra.translators.base_provider.TranslationResult` (new, for MT providers)
- **Solution:** Internal method `_translate_via_provider_chain()` uses provider's `TranslationResult`, then maps to service `TranslationResult`
- **Minimal Risk:** No changes to public API, only add new internal method

---

### Settings Keys

Settings stored in `QSettings` (INI format) via `SettingsService`.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `mt/providers/enabled` | bool | `False` | Master switch for MT providers (feature-safe default: OFF) |
| `mt/providers/chain` | JSON list | `[]` | Provider chain in priority order (e.g., `["deepl", "libretranslate", "mock"]`) |
| `mt/providers/allow_fallback_default` | bool | `True` | Allow fallback to next provider on error (can be overridden per request) |

**Key Naming Convention:**
- Follow existing `SettingsService` pattern (forward slashes for hierarchy)
- Use lowercase, underscores for multi-word keys

**Safe Defaults:**
- `mt/providers/enabled=False` → MT disabled by default (no surprise API calls)
- `mt/providers/chain=[]` → Empty chain (explicit configuration required)
- If chain empty → return `UNSUPPORTED` error with clear message (no crash)

---

### Fallback Policy (by TranslationErrorKind)

| ErrorKind | Fallback? | Log Level | Reason | Notes |
|-----------|-----------|-----------|--------|-------|
| `NETWORK` | ✅ Yes | INFO | `"NETWORK"` | Transient error, try next provider |
| `SERVER` | ✅ Yes | INFO | `"SERVER"` | Transient error, try next provider |
| `RATE_LIMIT` | ✅ Yes | WARNING | `"RATE_LIMIT"` | Transient error, try next provider |
| `QUOTA` | ✅ Yes | WARNING | `"QUOTA"` | Provider out of quota, try next |
| `UNSUPPORTED` | ✅ Yes | INFO | `"UNSUPPORTED"` | Language pair not supported, try next |
| `UNKNOWN` | ✅ Yes | WARNING | `"UNKNOWN"` | Unknown error, try next |
| `AUTH` | ✅ Yes | **ERROR** | `"AUTH_CONFIG_ISSUE"` | Invalid API key = misconfiguration, but fallback allowed |
| `INVALID_REQUEST` | ✅ Yes | ERROR | `"INVALID_REQUEST_CONFIG_ISSUE"` | Bad request = misconfiguration, but fallback allowed |
| **allow_fallback=False** | ❌ No | INFO | `"ALLOW_FALLBACK_FALSE"` | Stop after first attempt (user-requested) |
| **No more providers** | ❌ No | WARNING | `"NO_MORE_PROVIDERS"` | Exhausted chain |

**Fallback Decision Logic:**
1. If `allow_fallback=False` → Stop after first attempt, return error
2. If error is `AUTH` or `INVALID_REQUEST` → Log as **CONFIG_ISSUE**, but continue fallback
3. If error is transient (`NETWORK`, `SERVER`, `RATE_LIMIT`, `QUOTA`, `UNSUPPORTED`, `UNKNOWN`) → Continue fallback
4. If no more providers → Stop, return last error (or aggregated "ALL_PROVIDERS_FAILED")

---

### Structured Logging Schema

**Event: `provider_attempt`** (logged for each hop in chain)

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `trace_id` | str | Stable ID for request (UUID4) | `"a1b2c3d4-..."` |
| `provider_id` | str | Provider identifier | `"deepl"` |
| `display_name` | str | Human-readable name | `"DeepL Pro"` |
| `attempt_index` | int | 1-indexed attempt number | `1` (first), `2` (second), ... |
| `chain_total` | int | Total providers in chain | `3` |
| `src_lang` | str | Source language (ISO 639-1) | `"he"` |
| `tgt_lang` | str | Target language (ISO 639-1) | `"ru"` |
| `latency_ms` | int | Time taken for this attempt (ms) | `1234` |
| `used_glossary` | bool | Whether glossary was sent | `True` |
| `glossary_hash_present` | bool | Whether glossary hash exists | `True` |
| `cache_hit` | bool | Whether result from cache | `False` (cache in P1-T04) |
| `error_kind` | str or null | Error type if failed | `"NETWORK"`, `null` if success |
| `error_message` | str or null | Error message (sanitized) | `"Connection timeout"` |
| `decision` | str | Action taken | `"CONTINUE_FALLBACK"`, `"STOP_SUCCESS"`, `"STOP_FAIL"` |
| `fallback_reason` | str or null | Why fallback/stop occurred | `"NETWORK"`, `"ALLOW_FALLBACK_FALSE"`, `null` if success |

**Sanitization:**
- ❌ **Never log:** API keys, raw secrets, PII
- ✅ **Always sanitize:** Error messages (strip sensitive data)

**Final Event: `translation_completed`** (success)

| Field | Type | Description |
|-------|------|-------------|
| `trace_id` | str | Same as attempts |
| `total_attempts` | int | Number of attempts made |
| `final_provider` | str | Provider that succeeded |
| `total_latency_ms` | int | Sum of all attempts |

**Final Event: `translation_failed`** (all providers failed)

| Field | Type | Description |
|-------|------|-------------|
| `trace_id` | str | Same as attempts |
| `total_attempts` | int | Number of attempts made |
| `failure_reason` | str | Why translation failed (aggregated) |

---

### Implementation Outline

**New Method: `_translate_via_provider_chain()`**

```python
def _translate_via_provider_chain(
    self,
    session: Session,
    src_text: str,
    src_lang: str,
    tgt_lang: str,
    glossary: Optional[Any] = None,
    allow_fallback: bool = True,
    trace_id: str = "",
) -> TranslationResult:
    """
    Translate via provider chain with fallback logic.

    Returns:
        TranslationResult (service class, not provider class)
    """
    # 1. Get settings
    chain = settings.get_json("mt/providers/chain", default=[])
    enabled = settings.get_bool("mt/providers/enabled", default=False)

    if not enabled or not chain:
        return TranslationResult(
            source="none",
            notes="MT disabled or no providers configured"
        )

    # 2. Generate trace_id if missing
    if not trace_id:
        trace_id = str(uuid.uuid4())

    # 3. Build TranslationRequest (provider format)
    request = TranslationRequest(
        source_text=src_text,
        source_lang=src_lang,
        target_lang=tgt_lang,
        glossary=glossary,
        trace_id=trace_id,
        allow_fallback=allow_fallback,
    )

    # 4. Iterate provider chain
    registry = ProvidersRegistry()
    for index, provider_id in enumerate(chain, start=1):
        provider = registry.get(provider_id)
        if not provider:
            self._log_provider_attempt({
                "trace_id": trace_id,
                "provider_id": provider_id,
                "attempt_index": index,
                "chain_total": len(chain),
                "decision": "SKIP_MISSING",
                "fallback_reason": "PROVIDER_NOT_REGISTERED",
            })
            continue

        # Measure latency
        start = time.perf_counter()
        result = provider.translate(request)
        latency_ms = int((time.perf_counter() - start) * 1000)

        # Log attempt
        self._log_provider_attempt({
            "trace_id": trace_id,
            "provider_id": provider_id,
            "display_name": provider.display_name,
            "attempt_index": index,
            "chain_total": len(chain),
            "src_lang": src_lang,
            "tgt_lang": tgt_lang,
            "latency_ms": latency_ms,
            "used_glossary": result.used_glossary,
            "error_kind": result.error_kind.value if result.error_kind else None,
            "error_message": result.error_message,
            "decision": "STOP_SUCCESS" if result.is_success else "CONTINUE_FALLBACK",
        })

        # Success → return immediately
        if result.is_success:
            self._log_translation_completed(trace_id, index, latency_ms, provider_id)
            return self._map_provider_result_to_service(result)

        # Failure → apply fallback policy
        if not allow_fallback:
            self._log_translation_failed(trace_id, index, "ALLOW_FALLBACK_FALSE")
            return self._map_provider_result_to_service(result)

        # Continue to next provider

    # 5. All providers failed
    self._log_translation_failed(trace_id, len(chain), "NO_MORE_PROVIDERS")
    return TranslationResult(source="none", notes="All MT providers failed")
```

**Helper: `_map_provider_result_to_service()`**

```python
def _map_provider_result_to_service(
    self,
    provider_result: base_provider.TranslationResult
) -> translation_service.TranslationResult:
    """Map provider TranslationResult to service TranslationResult."""
    return translation_service.TranslationResult(
        translation=provider_result.translated_text or None,
        source="mt" if provider_result.is_success else "none",
        confidence=0.8 if provider_result.is_success else None,
        provider=provider_result.provider_id,
        matched_on="mt_chain",
        notes=provider_result.error_message if provider_result.is_error else None,
    )
```

---

### Manual Test Scenarios

**Test 1: NETWORK fail → fallback success**
1. Configure chain: `["mock_fail_network", "mock_success"]`
2. Set `allow_fallback=True`
3. Translate text
4. **Expected:**
   - Attempt 1: `mock_fail_network` → `NETWORK` error → `CONTINUE_FALLBACK`
   - Attempt 2: `mock_success` → success → `STOP_SUCCESS`
   - Final: translation returned from `mock_success`

**Test 2: AUTH fail → CONFIG_ISSUE logged + fallback**
1. Configure chain: `["deepl_invalid_key", "mock_success"]`
2. Set `allow_fallback=True`
3. Translate text
4. **Expected:**
   - Attempt 1: `deepl_invalid_key` → `AUTH` error → logged as **ERROR** with `AUTH_CONFIG_ISSUE` → `CONTINUE_FALLBACK`
   - Attempt 2: `mock_success` → success → `STOP_SUCCESS`

**Test 3: allow_fallback=False → stop after first**
1. Configure chain: `["mock_fail_network", "mock_success"]`
2. Set `allow_fallback=False`
3. Translate text
4. **Expected:**
   - Attempt 1: `mock_fail_network` → `NETWORK` error → `STOP_FAIL` (reason: `ALLOW_FALLBACK_FALSE`)
   - No attempt 2
   - Final: error returned

---

## PATCH-P1-T04: Cache + Circuit Breaker (FUTURE)

- MT cache integration (check cache before provider call)
- Circuit breaker per provider (state: CLOSED → OPEN → HALF_OPEN)
- Rate limiting per provider
- Cache TTL and invalidation

---

## PATCH-P1-T05: UI Integration (FUTURE)

- Settings UI for provider configuration
- Provider status dashboard (success rate, latency, circuit breaker state)
- Cache metrics (hit rate, size)
- Glossary sync UI

---

## Appendix: Provider Credentials

**Storage:** `app.infra.security.CredentialStore` (AES-256-GCM, OS keyring)

**Key Format:**
- DeepL: `mt_provider_deepl_api_key`
- Google: `mt_provider_google_api_key`
- Microsoft: `mt_provider_microsoft_api_key`
- LibreTranslate: No API key (public instance or self-hosted)

**Retrieval:**
```python
from app.infra.security import CredentialStore

with db_service.get_session() as session:
    cred_store = CredentialStore(session)
    api_key = cred_store.get_credential("mt_provider_deepl_api_key")
```

---

**End of P1_TRANSLATION_PRO_PLAN.md**
