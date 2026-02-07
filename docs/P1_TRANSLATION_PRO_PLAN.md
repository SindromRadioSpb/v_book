# P1 Translation Pro - Implementation Plan

**Status:** PATCH-P1-T05 (GlossaryBuilderService) → task_4_MT_local (Local MT Providers)
**Date:** 2026-02-07
**Owner:** Staff Engineer/Architect

**Updated Plan:**
```
✅ P1-T00 through P1-T04 (COMPLETE)
🔜 P1-T05: GlossaryBuilderService (3-5 days)
🔥 task_4_MT_local: Local MT Providers (2-3 weeks, HIGH PRIORITY)
⏭️  P1-T07: Term Extraction Pro
⏭️  P1-T08: Hardening + DoD Evidence
```

**Note:** P1-T06 (MT Cache migration) merged into P1-T04 - no separate migration needed.

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

## PATCH-P1-T03: TranslationService Integration (COMPLETE)

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

## PATCH-P1-T04: Cache + Circuit Breaker + Rate Limiter (COMPLETE)

### Overview

Enhances provider chain with:
1. **MT Cache** - Cache successful translations per provider (SQLite, TTL-based)
2. **Circuit Breaker** - Prevent cascading failures (CLOSED/OPEN/HALF_OPEN states)
3. **Rate Limiter** - Prevent hitting provider rate limits (token bucket algorithm)

### MT Cache

**Table:** `mt_cache` (created in schema v6 - M7 Translation Memory migration)

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS mt_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider VARCHAR(50) NOT NULL,
    request_key VARCHAR(64) NOT NULL,     -- SHA256 hash
    src_lang VARCHAR(10) NOT NULL,
    tgt_lang VARCHAR(10) NOT NULL,
    src_text TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    used_glossary BOOLEAN NOT NULL DEFAULT 0,
    glossary_hash VARCHAR(64),
    project_id INTEGER,
    created_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0,
    last_hit_at TIMESTAMP
);
CREATE UNIQUE INDEX idx_mt_cache_key ON mt_cache(provider, request_key);
CREATE INDEX idx_mt_cache_expiration ON mt_cache(expires_at);
```

**Cache Key Formula:**
```python
def _build_cache_key(self, request, provider_id) -> str:
    """Build cache key from request + provider_id.

    Formula: SHA256(normalized_text|src_lang|tgt_lang|provider_id|glossary_hash)
    """
    normalized_text = request.source_text.strip().lower()
    glossary_hash = request.glossary_hash or ""

    key_input = (
        f"{normalized_text}|{request.source_lang}|{request.target_lang}|"
        f"{provider_id}|{glossary_hash}"
    )
    return hashlib.sha256(key_input.encode('utf-8')).hexdigest()
```

**Cache Lookup:**
- Called before provider translation attempt
- Checks expiration (`expires_at > now`)
- Updates `hit_count` and `last_hit_at` on hit
- Returns `ProviderTranslationResult` with `cache_hit=True`

**Cache Store:**
- Only stores **successful** translations
- Sets `expires_at = now + TTL` (default 7 days)
- Stores full request context (src_text, languages, glossary_hash, project_id)

**Settings:**
- `mt/cache_enabled` (bool, default: `True`)
- `mt/cache_ttl_days` (int, default: `7`)

### Circuit Breaker

**File:** `app/infra/reliability/circuit_breaker.py`

**States:**
- `CLOSED` - Normal operation (allow all requests)
- `OPEN` - Blocking requests (provider failed repeatedly)
- `HALF_OPEN` - Testing recovery (allow 1 test request)

**Transitions:**
```
CLOSED --[failure_threshold reached]--> OPEN
OPEN --[cooldown_period expired]--> HALF_OPEN
HALF_OPEN --[test request succeeds]--> CLOSED
HALF_OPEN --[test request fails]--> OPEN
```

**Algorithm:**
1. **CLOSED state:**
   - Allow all requests
   - Track consecutive failures per provider
   - If `failure_count >= failure_threshold` → transition to OPEN

2. **OPEN state:**
   - Block all requests (skip provider in chain)
   - After `cooldown_seconds` elapsed → transition to HALF_OPEN

3. **HALF_OPEN state:**
   - Allow 1 test request
   - Success → reset failures, transition to CLOSED
   - Failure → transition back to OPEN (cooldown resets)

**Settings:**
- `mt/circuit_breaker/enabled` (bool, default: `True`)
- `mt/circuit_breaker/failure_threshold` (int, default: `3`)
- `mt/circuit_breaker/cooldown_seconds` (int, default: `60`)

**Integration:**
```python
# Before provider call
if not self._circuit_breaker.is_request_allowed(provider_id):
    logger.warning(f"Circuit breaker OPEN for {provider_id}, skipping")
    continue  # Skip to next provider

# After provider call
if result.is_success:
    self._circuit_breaker.record_success(provider_id)
else:
    self._circuit_breaker.record_failure(provider_id)
```

### Rate Limiter

**File:** `app/infra/reliability/rate_limiter.py`

**Algorithm:** Token Bucket
- Each provider has a bucket with tokens (capacity = requests_per_minute)
- Each request consumes 1 token
- Tokens refill at rate `requests_per_minute / 60.0` tokens/second
- If no tokens available:
  - Wait up to `max_wait_seconds` for token refill
  - If wait exceeds limit → return `False` (rate limit exceeded)

**Configuration:**
```python
# In TranslationService.__init__()
self._rate_limiter.configure_provider("deepl", requests_per_minute=60)
self._rate_limiter.configure_provider("libretranslate", requests_per_minute=120)
```

**Integration:**
```python
# Before provider call
if not self._rate_limiter.acquire(provider_id, max_wait_seconds=5.0):
    logger.warning(f"Rate limit exceeded for {provider_id}, skipping")
    continue  # Skip to next provider
```

**Status Monitoring:**
```python
status = self._rate_limiter.get_status("deepl")
# Returns: {"tokens": 45.3, "capacity": 60.0, "refill_rate": 1.0}
```

### Provider Chain Integration

**Updated Flow:**
```
1. Check settings (enabled, chain)
2. Generate trace_id
3. For each provider in chain:
   a. Check circuit breaker (skip if OPEN)
   b. Check rate limiter (skip if no tokens)
   c. Check cache (return if hit)
   d. Call provider.translate()
   e. Record circuit breaker result
   f. Store in cache (if success)
   g. Return (if success) or continue (if error + allow_fallback)
4. All providers failed → return error
```

**Logging Updates:**
- `cache_hit` field added to `provider_attempt` logs
- Circuit breaker state logged when OPEN
- Rate limiter wait time logged

### Tests

**File:** `tests/test_p1_mt_cache_circuit_breaker.py` (6/6 PASS)

**Circuit Breaker Tests:**
1. `test_circuit_breaker_state_transitions` - CLOSED → OPEN → HALF_OPEN → CLOSED
2. `test_circuit_breaker_half_open_failure_back_to_open` - HALF_OPEN → OPEN on failure
3. `test_circuit_breaker_opens_after_failures` - Integration with provider chain

**Rate Limiter Tests:**
4. `test_rate_limiter_allows_within_limit` - Allows requests within limit
5. `test_rate_limiter_blocks_over_limit` - Blocks requests over limit
6. `test_rate_limiter_waits_if_max_wait_allows` - Waits for token refill

**Note:** Full cache integration tests (hit/miss/expiration) require real SQLite database and are deferred to separate integration test suite.

### Deliverables

- ✅ MT cache implementation (`_lookup_provider_cache()`, `_store_in_cache()`, `_build_cache_key()`)
- ✅ Circuit breaker module (`app/infra/reliability/circuit_breaker.py`)
- ✅ Rate limiter module (`app/infra/reliability/rate_limiter.py`)
- ✅ Provider chain integration (cache check before call, store after success)
- ✅ Unit tests for circuit breaker state machine and rate limiter
- ✅ Documentation updates

---

## PATCH-P1-T05: GlossaryBuilderService (IN PROGRESS)

### Overview

Builds canonical glossary payload from approved terms for MT provider chain.

**Goals:**
1. Extract approved terms from database (status='approved')
2. Build canonical glossary format (deterministic, stable sort)
3. Compute glossary_hash (SHA256) for cache keying
4. Provide provider-specific adapters (DeepL, Google, Microsoft formats)
5. Handle conflicts (duplicate source terms with different targets)

### Canonical Glossary Format

**Data Structure:**
```python
@dataclass
class GlossaryEntry:
    source_term: str          # Original source term
    target_term: str          # Approved translation
    canonical_key: str        # Normalized key for dedup (lowercase, strip)
    priority_score: float     # Higher = more important (default: 1.0)

@dataclass
class CanonicalGlossary:
    entries: List[GlossaryEntry]
    source_lang: str          # e.g., "he" (Hebrew)
    target_lang: str          # e.g., "ru" (Russian)
    glossary_hash: str        # SHA256 of deterministic JSON
    total_entries: int
    truncated: bool           # True if hit provider limit
    size_bytes: int           # Estimate for provider payload
```

**Deterministic Sorting:**
1. Sort by `canonical_key` (stable tie-breaker)
2. If duplicate keys → select highest priority_score
3. If same priority → select first by source_term alphabetically

**Glossary Hash Computation:**
```python
def compute_glossary_hash(canonical: CanonicalGlossary) -> str:
    """Compute deterministic hash for cache keying.

    Formula: SHA256(JSON with sorted keys)
    """
    payload = {
        "source_lang": canonical.source_lang,
        "target_lang": canonical.target_lang,
        "entries": [
            {"source": e.source_term, "target": e.target_term}
            for e in canonical.entries
        ]
    }
    # Sort keys for determinism
    json_str = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(json_str.encode('utf-8')).hexdigest()
```

### Provider-Specific Adapters

**DeepL Format:**
```python
def to_deepl_format(canonical: CanonicalGlossary) -> Dict:
    """Convert to DeepL glossary format.

    DeepL supports TSV format: source\ttarget\n
    Max entries: 5000 (configurable)
    """
    entries_tsv = "\n".join(
        f"{e.source_term}\t{e.target_term}"
        for e in canonical.entries[:5000]
    )
    return {
        "format": "tsv",
        "entries": entries_tsv,
        "source_lang": canonical.source_lang.upper(),
        "target_lang": canonical.target_lang.upper(),
    }
```

**Microsoft Translator Format:**
```python
def to_microsoft_format(canonical: CanonicalGlossary) -> Dict:
    """Convert to Microsoft Custom Translator format.

    Microsoft supports dictionary (parallel arrays)
    Max entries: 10000 (configurable)
    """
    return {
        "translations": [
            {
                "from": e.source_term,
                "to": e.target_term
            }
            for e in canonical.entries[:10000]
        ]
    }
```

**LibreTranslate Format:**
```python
def to_libretranslate_format(canonical: CanonicalGlossary) -> Dict:
    """LibreTranslate does not support glossaries natively.

    Return empty dict, provider will skip glossary.
    """
    return {}
```

### Conflict Resolution Policy

**Scenario:** Same source_term with multiple target_terms

**Policy:**
1. Group by canonical_key (normalized source_term)
2. Within group: select entry with highest priority_score
3. If same priority: select first alphabetically by source_term (stable)
4. Log warning: "Glossary conflict: '{source}' has multiple targets, selected '{target}'"

**Example:**
```python
# Input terms:
# - "כלב" → "собака" (priority: 2.0)
# - "כלב" → "пёс" (priority: 1.0)

# After conflict resolution:
# - "כלב" → "собака" (selected, higher priority)
```

### Integration with TranslationService

**Usage in Provider Chain:**
```python
# In TranslationService._translate_via_provider_chain()

# Build glossary once per request
glossary_service = GlossaryBuilderService(session)
canonical = glossary_service.build_canonical_glossary(
    src_lang="he",
    tgt_lang="ru",
    project_id=project_id
)

# Compute hash for cache key
glossary_hash = canonical.glossary_hash

# Convert to provider format
if provider.supports_glossary:
    provider_glossary = glossary_service.to_provider_format(
        canonical,
        provider_id=provider.provider_id
    )
    request.glossary = provider_glossary
else:
    request.glossary = None
    logger.info(f"Provider {provider.provider_id} does not support glossaries")
```

### Settings Keys

**Added Settings:**
- `mt/glossary/max_entries_default` (int, default: `5000`) - Default max entries
- `mt/glossary/max_entries_deepl` (int, default: `5000`) - DeepL-specific limit
- `mt/glossary/max_entries_microsoft` (int, default: `10000`) - Microsoft-specific limit

### Database Query

**Query approved terms:**
```sql
SELECT source_term, target_term, priority_score
FROM tm_entry
WHERE status = 'approved'
  AND src_lang = ?
  AND tgt_lang = ?
  AND (project_id = ? OR project_id IS NULL)
ORDER BY priority_score DESC, source_term ASC
```

### Tests

**File:** `tests/test_p1_glossary_builder.py` (5-8 tests)

**Test Coverage:**
1. `test_build_canonical_glossary_deterministic` - Same inputs → same hash
2. `test_conflict_resolution_priority` - Higher priority wins
3. `test_conflict_resolution_stable_sort` - Same priority → alphabetical
4. `test_to_deepl_format` - TSV format correct
5. `test_to_microsoft_format` - JSON format correct
6. `test_truncation_at_max_entries` - Respects provider limits
7. `test_empty_glossary_graceful` - No approved terms → empty glossary
8. `test_glossary_hash_changes_on_content_change` - Hash invalidation

### Deliverables

- ✅ `app/services/glossary_builder_service.py` (new file)
- ✅ Tests: `tests/test_p1_glossary_builder.py` (5-8 tests)
- ✅ Integration: Update `TranslationService._translate_via_provider_chain()`
- ✅ Documentation: Update this section

---

## task_4_MT_local: Local MT Providers (PLANNED - HIGH PRIORITY)

### Overview

Add offline-capable local MT providers (NLLB + Seamless M4T) integrated into existing provider chain.

**Models:**
- Primary: `facebook/nllb-200-distilled-1.3B` (CC-BY-NC 4.0, internal use OK)
- Fallback: `facebook/seamless-m4t-v2-large` (CC-BY-NC 4.0, internal use OK)

**Language Pair:** Hebrew (`heb_Hebr`) → Russian (`rus_Cyrl`)

**Architecture:**
- Worker-based inference (no UI blocking)
- Sentence segmentation (NLLB quality degrades on long inputs)
- Glossary postprocess (uses approved terms from P1-T05)
- Full integration with existing cache/circuit breaker/rate limiter

**Dependencies:**
- ✅ BaseProvider contract (P1-T01)
- ✅ Provider chain (P1-T03)
- ✅ Circuit breaker + rate limiter (P1-T04)
- ✅ MT cache (P1-T04)
- 🔜 **GlossaryBuilderService (P1-T05)** - REQUIRED for glossary postprocess

**Implementation Plan:** See `task_4_MT_local.md` for detailed 10-PATCH breakdown

**Estimated Timeline:** 2-3 weeks after P1-T05 complete

---

## PATCH-P1-T07: Term Extraction Pro (FUTURE)

- Term extraction presets (PMI, LLR, Dice, Keyness, Weirdness)
- Reference corpus selection UI
- Explainability: "Why ranked #1?"
- Reproducibility (preset_version + config → stable results)

---

## PATCH-P1-T08: Hardening + DoD Evidence (FUTURE)

- Edge case handling (no providers, misconfigured keys, huge glossaries)
- Performance verification (cache hit rate >80%, latency budgets)
- UI DoD evidence documentation
- Final integration tests

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
