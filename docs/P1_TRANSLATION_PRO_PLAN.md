# P1 Translation Pro Implementation Plan

**Date:** 2026-02-07
**Iteration:** 4 (Premium-Pro Roadmap)
**Epic:** Epic 3 (Translation Provider Abstraction + MT Integration) + Epic 4 (Term Extraction Pro)
**Status:** PATCH-P1-T00 (Docs + Recon) - IN PROGRESS

---

## Executive Summary

This document describes the implementation plan for **P1 Translation Pro**, which adds:

1. **MT Provider Abstraction** - Pluggable translation providers (DeepL, Google, LibreTranslate, etc.)
2. **Fallback Chain** - Automatic provider failover with circuit breaker and rate limiting
3. **Glossary Builder** - Extract approved terms and format for each provider
4. **MT Cache with TTL** - Cache translations with glossary-aware keying
5. **Term Extraction Presets** - Reproducible extraction configs with explainability

**Guiding Principles:**
- Keyboard-first UI
- Deterministic UX (versioned state, crash-safe)
- Performance budget: cache hit path < 10ms, hit rate >80%
- Minimal regression risk: incremental PATCH commits
- Documentation-driven: read first, code second

---

## 1. Current Architecture (Recon Findings)

### 1.1 TranslationService

**Location:** `app/services/translation_service.py`

**Current State:**
- ✅ Implements precedence order: TM → Dict → MT cache → MT provider
- ✅ `TranslationResult` dataclass for explainability
- ✅ `use_mt: bool` flag already added
- ❗ **Line 104-105:** "MT provider (not implemented yet - would go here)" ← **OUR TASK**

**Current Precedence Order:**
```python
def resolve_translation(..., use_mt: bool = False) -> TranslationResult:
    # 1. TM override (project-scoped, then global)
    # 2. TM aliases
    # 3. Offline dict (by priority)
    # 4. MT cache (if use_mt=True)
    # 5. MT provider (TODO - not implemented)
    # 6. None
```

**Key Methods:**
- `resolve_translation()` - main entry point
- `_lookup_tm()` - TM entries with status=approved
- `_lookup_tm_aliases()` - TM aliases
- `_lookup_dict()` - Offline dictionaries
- `_lookup_mt_cache()` - MT cache lookup
- ❌ `_query_mt_provider()` - **NOT IMPLEMENTED** (our task)

### 1.2 Approved Terms (Glossary Source)

Multiple sources for "approved" terms:

1. **TermCard** (`app/infra/sa_models.py:362`)
   - Fields: `status IN ('auto','needs_review','approved','rejected')`
   - Used for: Manual term curation

2. **TermCluster** (`app/infra/sa_models.py:516`)
   - Fields: `curation_status IN ('auto','needs_review','approved','rejected')`
   - Fields: `pinned_translation` (for override)
   - Used for: Extracted term curation

3. **TMEntry** (`app/infra/sa_models.py:563`)
   - Fields: `status IN ('draft','approved','rejected','deprecated')`
   - Fields: `approved_at`, `approved_by`
   - Used for: Translation Memory entries

4. **DictEntry** (`app/infra/sa_models.py:652`)
   - Fields: `status IN ('approved','draft','deprecated')`
   - Fields: `priority` (for ranking)
   - Used for: Offline dictionary entries

**Glossary Strategy:**
- **Primary source:** TMEntry (status='approved') + TermCluster (curation_status='approved', pinned_translation != NULL)
- **Secondary source:** DictEntry (status='approved', priority > 0)
- **Exclusion:** TermCard with status='rejected' (avoid these in MT)

### 1.3 Database Migrations

**Location:** `app/infra/migrations/`

**Current Schema:** v8 (007_security_audit_log.sql + 008_credentials_table.sql)

**Migration Files:**
- 001_init.sql (v1)
- 002_term_extraction.sql (v2-3)
- 003_doc_nlp_metrics.sql (v3-4)
- 004_concordance_index.sql (v4)
- 005_m8_term_curation.sql (v5)
- 006_m7_translation_memory.sql (v6)
- 007_security_audit_log.sql (v7)
- 008_credentials_table.sql (v8)

**Next Migration:** 009_mt_cache_ttl.sql (v9)
- Extend mt_cache table with TTL fields
- Add glossary_hash column
- Add model_version column

**Migration Runner:** `app/infra/db_service.py` (DBService.apply_migrations)

### 1.4 Settings and Configuration

**Location:** `app/infra/settings.py` (SettingsService)

**Current Pattern:**
- Uses QSettings (INI format, cross-platform)
- Storage: User-scoped (e.g., `~/.config/HDLE_Premium/HDLE_Premium.conf` on Linux)
- Methods:
  - `get_string(key, default)` / `set_value(key, value)`
  - `get_json(key, default)` / `set_json(key, value)` - for complex types
  - `get_bool()`, `get_int()`, `get_bytes()`

**Existing Keys (examples):**
- `window/geometry` - window geometry
- `window/state` - window state
- `table/{table_id}/header_state` - table column state

**New Keys for P1:**
```python
# Provider chain configuration
"mt/provider_chain": ["deepl", "libretranslate", "google"]  # JSON list

# Per-provider settings
"mt/provider/deepl/api_key": "ENCRYPTED"  # via CredentialStore
"mt/provider/deepl/enabled": true
"mt/provider/deepl/requests_per_min": 60
"mt/provider/libretranslate/api_url": "https://libretranslate.com/"
"mt/provider/google/api_key": "ENCRYPTED"

# MT cache settings
"mt/cache_ttl_days": 7
"mt/cache_enabled": true

# Circuit breaker settings (per provider)
"mt/circuit_breaker/deepl/fail_threshold": 3
"mt/circuit_breaker/deepl/cooldown_seconds": 60

# Glossary settings
"mt/glossary_max_entries": 1000
"mt/glossary_include_aliases": true
```

### 1.5 Credential Storage

**Location:** `app/infra/security/credentials.py` (CredentialStore)

**Current State:**
- ✅ Implemented in P0 Security Hardening
- Uses AES-256-GCM encryption at rest
- Master key stored in OS keyring (keyring library)
- Methods:
  - `store_credential(key, value)` - encrypt and store
  - `get_credential(key)` - decrypt and retrieve
  - `delete_credential(key)` - securely delete

**Usage for P1:**
```python
from app.infra.security import CredentialStore

cred_store = CredentialStore()

# Store API key
cred_store.store_credential("mt_provider_deepl_api_key", "YOUR_API_KEY")

# Retrieve API key
api_key = cred_store.get_credential("mt_provider_deepl_api_key")
```

### 1.6 Worker Pattern (UI Thread Safety)

**Location:** `app/ui/workers.py`

**Current Pattern:**
- All long operations (>100ms) run in worker threads
- Use Qt signals for progress updates
- Example: `ProcessWorker`, `ImportWorker`, `ExportWorker`

**Pattern for P1:**
```python
class MTTranslationWorker(QRunnable):
    """Worker for MT translation requests (>100ms)."""

    def __init__(self, translation_service, segments, ...):
        super().__init__()
        self.signals = WorkerSignals()
        # ...

    def run(self):
        try:
            results = self.translation_service.translate_batch(...)
            self.signals.finished.emit(results)
        except Exception as e:
            self.signals.error.emit(str(e))
```

**UI Integration:**
- Never block main thread
- Show progress indicator for operations >1s
- Support cancellation for operations >5s

---

## 2. Design Decisions

### 2.1 Provider API Contract

**File:** `app/infra/translators/base_provider.py` (NEW)

**Dataclasses:**

```python
from dataclasses import dataclass
from typing import Optional, Dict
from enum import Enum

@dataclass
class TranslationRequest:
    """Request to translate a single segment."""
    source_text: str
    source_lang: str  # ISO 639-1 (e.g., "he", "en")
    target_lang: str  # ISO 639-1 (e.g., "ru", "en")
    glossary: Optional['CanonicalGlossary'] = None
    glossary_hash: str = ""  # SHA256 hex of glossary JSON
    options: Dict = None  # Provider-specific options (deterministic JSON)
    trace_id: str = ""  # For logging and debugging
    allow_fallback: bool = True
    timeout_seconds: float = 10.0

class TranslationErrorKind(Enum):
    """Taxonomy of translation errors for fallback logic."""
    NETWORK = "network"  # Connection failed, timeout
    AUTH = "auth"  # Invalid API key, unauthorized
    RATE_LIMIT = "rate_limit"  # Rate limit exceeded (429)
    QUOTA = "quota"  # Quota exceeded (402, 403)
    SERVER = "server"  # Server error (500, 502, 503, 504)
    INVALID_REQUEST = "invalid_request"  # Bad request (400)
    UNSUPPORTED = "unsupported"  # Feature not supported (e.g., language pair)
    UNKNOWN = "unknown"  # Catch-all for unexpected errors

@dataclass
class TranslationResult:
    """Result of translation request with provenance."""
    translated_text: str = ""
    provider_id: str = ""  # e.g., "deepl", "google"
    used_glossary: bool = False
    cache_hit: bool = False
    latency_ms: int = 0
    error_kind: Optional[TranslationErrorKind] = None
    error_message: Optional[str] = None
    meta: Dict = None  # Provider-specific metadata (e.g., detected_source_lang)
```

**BaseProvider Interface:**

```python
from abc import ABC, abstractmethod

class BaseProvider(ABC):
    """Abstract base class for MT providers."""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique provider ID (e.g., 'deepl', 'google')."""
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable provider name (e.g., 'DeepL Pro')."""
        pass

    @property
    @abstractmethod
    def supports_glossary(self) -> bool:
        """Whether this provider supports glossary payloads."""
        pass

    @property
    def supports_batch(self) -> bool:
        """Whether this provider supports batch translation."""
        return False  # Default: False (override if supported)

    @abstractmethod
    def translate(self, request: TranslationRequest) -> TranslationResult:
        """
        Translate a single segment.

        MUST NOT raise exceptions - return TranslationResult with error_kind instead.
        """
        pass

    def get_model_version(self) -> str:
        """Get model version for cache key (default: 'v1')."""
        return "v1"

    def healthcheck(self) -> bool:
        """Optional health check (default: True)."""
        return True
```

### 2.2 Provider Chain Policy

**Location:** `app/services/translation_service.py` (ENHANCE)

**Chain Configuration:**
- Stored in settings: `"mt/provider_chain"` (JSON list)
- Default: `["deepl", "libretranslate", "google"]`
- User-configurable via Settings UI

**Fallback Rules:**

| Error Kind | Action | Retry on Same Provider? | Fallback to Next? | Log Level |
|-----------|--------|------------------------|------------------|-----------|
| `NETWORK` | Fallback | ❌ No | ✅ Yes | WARNING |
| `SERVER` | Fallback | ❌ No | ✅ Yes | WARNING |
| `RATE_LIMIT` | Fallback | ❌ No | ✅ Yes | WARNING |
| `QUOTA` | Fallback | ❌ No | ✅ Yes | ERROR |
| `AUTH` | Fallback | ❌ No | ✅ Yes (log config issue) | ERROR |
| `INVALID_REQUEST` | Fallback | ❌ No | ✅ Yes (log config issue) | ERROR |
| `UNSUPPORTED` | Fallback | ❌ No | ✅ Yes | INFO |
| `UNKNOWN` | Fallback | ❌ No | ✅ Yes | ERROR |

**Circuit Breaker Skip:**
- If circuit is OPEN → skip provider immediately
- Log: `"Skipping provider 'deepl' (circuit OPEN)"`

**Rate Limiter Skip:**
- If rate limit exceeded → skip provider immediately
- Log: `"Skipping provider 'deepl' (rate limit exceeded)"`

**Logging:**
```python
logger.info(f"[{trace_id}] Attempt 1/3: provider='deepl', latency={latency_ms}ms, result='{result[:50]}...'")
logger.warning(f"[{trace_id}] Attempt 1 failed: provider='deepl', error={error_kind}, message='{error_message}', fallback_to='libretranslate'")
logger.info(f"[{trace_id}] Attempt 2/3: provider='libretranslate', latency={latency_ms}ms, result='{result[:50]}...'")
logger.info(f"[{trace_id}] Success: provider='libretranslate', total_latency={total_ms}ms")
```

### 2.3 Circuit Breaker (Per Provider)

**File:** `app/infra/translators/circuit_breaker.py` (NEW)

**States:**
- `CLOSED`: Normal operation (pass all requests)
- `OPEN`: Failing (block all requests)
- `HALF_OPEN`: Testing (allow 1 request to probe)

**Configuration (per provider):**
```python
fail_threshold: int = 3  # Consecutive failures to trigger OPEN
cooldown_seconds: int = 60  # Wait before HALF_OPEN trial
```

**State Transitions:**
```
CLOSED --[3 failures]--> OPEN --[60s cooldown]--> HALF_OPEN --[success]--> CLOSED
                                                   |
                                                   [failure]
                                                   |
                                                   v
                                                  OPEN (reset cooldown)
```

**Implementation:**
```python
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

@dataclass
class CircuitBreaker:
    """Per-provider circuit breaker."""
    provider_id: str
    fail_threshold: int = 3
    cooldown_seconds: int = 60

    # State (in-memory, reset on app restart)
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    last_failure_time: Optional[datetime] = None

    def record_success(self):
        """Record successful request."""
        self.consecutive_failures = 0
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            logger.info(f"Circuit breaker for '{self.provider_id}' CLOSED (success after HALF_OPEN)")

    def record_failure(self):
        """Record failed request."""
        self.consecutive_failures += 1
        self.last_failure_time = utc_now()

        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit breaker for '{self.provider_id}' OPEN again (failure during HALF_OPEN)")
        elif self.consecutive_failures >= self.fail_threshold:
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit breaker for '{self.provider_id}' OPEN (threshold={self.fail_threshold})")

    def can_attempt(self) -> bool:
        """Check if request should be allowed."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check cooldown
            if self.last_failure_time:
                elapsed = (utc_now() - self.last_failure_time).total_seconds()
                if elapsed >= self.cooldown_seconds:
                    self.state = CircuitState.HALF_OPEN
                    logger.info(f"Circuit breaker for '{self.provider_id}' HALF_OPEN (cooldown expired)")
                    return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            return True  # Allow 1 probe request

        return False
```

**Storage:**
- In-memory (reset on app restart)
- Optional: Persist to QSettings for cross-session memory

### 2.4 Rate Limiter (Per Provider)

**File:** `app/infra/translators/rate_limiter.py` (NEW)

**Algorithm:** Token Bucket

**Configuration (per provider):**
```python
requests_per_min: int = 60  # Bucket capacity
```

**Implementation:**
```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class RateLimiter:
    """Token bucket rate limiter (per provider)."""
    provider_id: str
    requests_per_min: int = 60

    # State (in-memory)
    tokens: float = 60.0
    last_refill_time: datetime = None

    def __post_init__(self):
        if self.last_refill_time is None:
            self.last_refill_time = utc_now()

    def can_attempt(self) -> bool:
        """Check if request should be allowed (non-blocking)."""
        self._refill_tokens()

        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        else:
            logger.debug(f"Rate limit exceeded for '{self.provider_id}' (tokens={self.tokens:.2f})")
            return False

    def _refill_tokens(self):
        """Refill tokens based on elapsed time."""
        now = utc_now()
        elapsed_seconds = (now - self.last_refill_time).total_seconds()
        refill_rate = self.requests_per_min / 60.0  # Tokens per second

        tokens_to_add = elapsed_seconds * refill_rate
        self.tokens = min(self.tokens + tokens_to_add, float(self.requests_per_min))
        self.last_refill_time = now
```

**UI Behavior:**
- When rate limit exceeded → immediate fallback to next provider
- No sleep in UI thread

### 2.5 GlossaryBuilderService

**File:** `app/services/glossary_builder_service.py` (NEW)

**Purpose:** Build canonical glossary from approved terms

**Data Model:**

```python
from dataclasses import dataclass
from typing import List

@dataclass
class GlossaryEntry:
    """Single glossary entry (source → target)."""
    source_term: str
    target_term: str
    canonical_key: str  # Stable sort key (normalized source term)
    priority_score: float = 0.0  # Higher = more important (optional)

@dataclass
class CanonicalGlossary:
    """Canonical glossary representation (provider-agnostic)."""
    entries: List[GlossaryEntry]
    source_lang: str
    target_lang: str

    # Stats
    total_entries: int = 0
    truncated_entries: int = 0  # If provider has size limit
    bytes_estimate: int = 0
```

**Algorithm:**

1. **Collect approved terms:**
   ```python
   # TMEntry: status='approved'
   # TermCluster: curation_status='approved' AND pinned_translation IS NOT NULL
   # DictEntry: status='approved' AND priority > 0
   ```

2. **Normalize and deduplicate:**
   ```python
   # For each source_term:
   #   - Normalize: normalize_for_tm(src_lang, source_term, kind)
   #   - Canonical key: normalized.norm

   # If multiple target_term for same source_term:
   #   - Pick highest priority (TM > Dict)
   #   - Tie-breaker: most recent updated_at
   ```

3. **Stable sort:**
   ```python
   # Sort by canonical_key, then source_term (deterministic)
   sorted(entries, key=lambda e: (e.canonical_key, e.source_term))
   ```

4. **Truncate if needed:**
   ```python
   # If len(entries) > provider.max_glossary_entries:
   #   - Keep top N by priority_score
   #   - Log truncation
   ```

**Provider Adapters:**

```python
class GlossaryBuilderService:
    def to_deepl_format(self, glossary: CanonicalGlossary) -> str:
        """
        DeepL format: TSV (tab-separated)
        source_term\ttarget_term\n
        """
        lines = [f"{e.source_term}\t{e.target_term}" for e in glossary.entries]
        return "\n".join(lines)

    def to_libretranslate_format(self, glossary: CanonicalGlossary) -> Dict:
        """
        LibreTranslate format: JSON dict
        {"source_term": "target_term", ...}
        """
        return {e.source_term: e.target_term for e in glossary.entries}

    def to_google_format(self, glossary: CanonicalGlossary) -> List[Dict]:
        """
        Google format: JSON list of dicts
        [{"source": "source_term", "target": "target_term"}, ...]
        """
        return [{"source": e.source_term, "target": e.target_term} for e in glossary.entries]
```

**Glossary Hash (for cache key):**

```python
import hashlib
import json

def compute_glossary_hash(glossary: CanonicalGlossary) -> str:
    """Compute SHA256 hash of canonical glossary (deterministic)."""
    # Serialize to JSON with sorted keys
    payload = {
        "source_lang": glossary.source_lang,
        "target_lang": glossary.target_lang,
        "entries": [
            {"source": e.source_term, "target": e.target_term}
            for e in sorted(glossary.entries, key=lambda x: (x.canonical_key, x.source_term))
        ]
    }
    json_str = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(json_str.encode('utf-8')).hexdigest()
```

### 2.6 MT Cache Schema (SQLite)

**Migration:** `app/infra/migrations/009_mt_cache_ttl.sql` (NEW)

**Table:** `mt_cache` (extend existing or create new)

```sql
-- Extend existing mt_cache table (if exists) or create new
CREATE TABLE IF NOT EXISTS mt_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key TEXT UNIQUE NOT NULL,  -- SHA256 hex (see cache key formula below)
    provider_id TEXT NOT NULL,  -- e.g., 'deepl', 'google'
    src_lang TEXT NOT NULL,  -- ISO 639-1 (e.g., 'he')
    tgt_lang TEXT NOT NULL,  -- ISO 639-1 (e.g., 'ru')
    norm_text_hash TEXT NOT NULL,  -- SHA256(normalized source text)
    glossary_hash TEXT NOT NULL,  -- SHA256(canonical glossary JSON) or '' if no glossary
    model_version TEXT NOT NULL,  -- Provider model version (e.g., 'deepl-v2', 'google-nmt-v1')
    options_hash TEXT NOT NULL,  -- SHA256(canonical options JSON) or '' if no options
    created_at TEXT NOT NULL,  -- UTC timestamp (ISO 8601)
    expires_at TEXT NOT NULL,  -- UTC timestamp (ISO 8601)
    hit_count INTEGER NOT NULL DEFAULT 0,
    last_hit_at TEXT,  -- UTC timestamp (ISO 8601, nullable)
    translated_text TEXT NOT NULL,
    meta_json TEXT NOT NULL DEFAULT '{}',  -- Provider-specific metadata (JSON)

    -- Indexes
    INDEX idx_mt_cache_expires_at (expires_at),
    INDEX idx_mt_cache_provider (provider_id, src_lang, tgt_lang)
);
```

**Cache Key Formula:**

```python
import hashlib
import json

def compute_cache_key(
    provider_id: str,
    src_lang: str,
    tgt_lang: str,
    normalized_text: str,
    glossary_hash: str,
    model_version: str,
    options: Dict
) -> str:
    """Compute cache key (SHA256 hex)."""
    # Canonicalize options (sorted keys)
    options_json = json.dumps(options or {}, ensure_ascii=False, sort_keys=True)
    options_hash = hashlib.sha256(options_json.encode('utf-8')).hexdigest()

    # Compute normalized text hash
    norm_text_hash = hashlib.sha256(normalized_text.encode('utf-8')).hexdigest()

    # Concatenate components
    components = [
        provider_id,
        src_lang,
        tgt_lang,
        norm_text_hash,
        glossary_hash,
        model_version,
        options_hash
    ]
    cache_key_input = "|".join(components)

    return hashlib.sha256(cache_key_input.encode('utf-8')).hexdigest()
```

**TTL Configuration:**
- Default: 7 days
- Setting: `"mt/cache_ttl_days": 7`
- Cleanup: Background task or on-demand (DELETE WHERE expires_at < utc_now())

**Metrics (per run):**
```python
@dataclass
class MTCacheMetrics:
    """MT cache metrics for current run."""
    cache_hits: int = 0
    cache_misses: int = 0
    cache_errors: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total > 0 else 0.0
```

**DoD Gate:**
- On second run of identical segments: hit rate >80%

### 2.7 Term Extraction Pro

**Location:** `app/services/term_extraction_service.py` (ENHANCE)

**Presets:**

| Preset ID | Name | Use Case | Config |
|-----------|------|----------|--------|
| `pmi_high` | PMI High | General terminology | ngram_range=(2,3), min_freq=5, min_df=2, score=PMI |
| `llr_medium` | LLR Medium | Domain-specific | ngram_range=(2,4), min_freq=3, min_df=2, score=LLR |
| `dice_low` | Dice Low | Rare terms | ngram_range=(2,3), min_freq=2, min_df=1, score=Dice |
| `termhood_high` | Termhood High | Academic/technical | weirdness + keyness_llr, reference_corpus required |

**Preset Registry:**

```python
@dataclass
class ExtractionPreset:
    """Reproducible extraction configuration."""
    preset_id: str
    name: str
    version: str  # For reproducibility (e.g., "1.0")
    ngram_range: Tuple[int, int]
    pos_patterns: List[str]  # e.g., ["NOUN+NOUN", "ADJ+NOUN"]
    min_freq: int
    min_df: int  # Minimum document frequency
    scoring_config: Dict  # Weights for different measures
    normalization_mode: str  # e.g., "strict", "relaxed"
```

**Reference Corpus Selection:**
- Reuse M5.4 `general_corpus_id` field in DictProject
- UI: Dropdown in Terms panel (already implemented in `app/ui/terms_view.py`)

**Explainability ("Why Ranked #1?"):**

```python
@dataclass
class TermExplanation:
    """Explainability for term ranking."""
    term: str
    rank: int
    total_candidates: int

    # Metrics
    f_d: int  # Frequency in domain corpus
    N_d: int  # Total tokens in domain corpus
    f_r: int  # Frequency in reference corpus
    N_r: int  # Total tokens in reference corpus

    weirdness: float
    keyness_llr: float
    termhood_score: float

    # Formula breakdown
    formula: str  # e.g., "termhood = 0.5*weirdness + 0.5*keyness_llr"

    # Top contexts (KWIC)
    top_contexts: List[str]  # Top 5 sentence contexts
```

**UI Integration:**
- Context menu in Terms table: "Why ranked #1?"
- Dialog: Scrollable (no fixed heights), Esc closes, focus returns

---

## 3. Settings Keys

All settings stored in `QSettings` (INI format, user-scoped).

### 3.1 Provider Chain

```ini
[mt]
provider_chain=["deepl", "libretranslate", "google"]
```

### 3.2 Per-Provider Settings

```ini
[mt/provider/deepl]
enabled=true
api_key=<stored in CredentialStore>
requests_per_min=60
fail_threshold=3
cooldown_seconds=60

[mt/provider/libretranslate]
enabled=true
api_url="https://libretranslate.com/"
requests_per_min=120

[mt/provider/google]
enabled=false
api_key=<stored in CredentialStore>
requests_per_min=60
```

### 3.3 MT Cache Settings

```ini
[mt/cache]
enabled=true
ttl_days=7
```

### 3.4 Glossary Settings

```ini
[mt/glossary]
max_entries=1000
include_aliases=true
```

---

## 4. File Structure (Where to Add)

### 4.1 New Files

```
app/
├── infra/
│   └── translators/
│       ├── __init__.py  # NEW
│       ├── base_provider.py  # NEW (dataclasses + BaseProvider)
│       ├── providers_registry.py  # NEW (provider registry)
│       ├── circuit_breaker.py  # NEW
│       ├── rate_limiter.py  # NEW
│       └── providers/
│           ├── __init__.py  # NEW
│           ├── mock_provider.py  # NEW (deterministic mock)
│           ├── deepl_provider.py  # NEW
│           ├── libretranslate_provider.py  # NEW
│           └── microsoft_translator_provider.py  # NEW (or google)
├── services/
│   ├── translation_service.py  # ENHANCE (add provider chain)
│   └── glossary_builder_service.py  # NEW
└── ui/
    └── why_ranked_dialog.py  # NEW (explainability UI)

tests/
├── test_p1_translation_provider_base.py  # NEW
├── test_p1_translation_providers_offline.py  # NEW
├── test_p1_translation_chain.py  # NEW
├── test_p1_translation_resilience.py  # NEW
├── test_p1_glossary_builder.py  # NEW
├── test_p1_mt_cache.py  # NEW
├── test_p1_mt_cache_hit_rate_gate.py  # NEW
├── test_p1_term_presets_reproducible.py  # NEW
├── test_p1_term_explainability.py  # NEW
└── test_p1_translation_edge_cases.py  # NEW

docs/
├── P1_TRANSLATION_PRO_PLAN.md  # THIS FILE
├── PROVIDER_SETUP_GUIDE.md  # NEW
└── UI_DOD_EVIDENCE_P1_TRANSLATION_PRO.md  # NEW (PATCH-08)
```

### 4.2 Modified Files

```
app/services/translation_service.py
  - Add _query_mt_provider() method
  - Add provider chain logic
  - Add fallback policy
  - Add circuit breaker + rate limiter integration

app/services/term_extraction_service.py
  - Add preset registry
  - Add explain_term_ranking() method

app/ui/terms_view.py
  - Add "Why ranked #1?" context menu action
  - Wire to WhyRankedDialog

app/infra/migrations/009_mt_cache_ttl.sql
  - Extend mt_cache table (or create if not exists)

docs/ROADMAP_PREMIUM_PRO.md
  - Update Iteration 4 status (mark as IN PROGRESS)
```

---

## 5. Dependencies

### 5.1 Existing Dependencies (Verify)

Check `pyproject.toml` or `requirements.txt`:

- ✅ `requests` or `httpx` (for HTTP API calls)
- ✅ `keyring` (for credential storage, already added in P0)
- ✅ `cryptography` (for encryption, already added in P0)

### 5.2 New Dependencies (If Needed)

**If requests not available:**
- Fall back to standard library: `urllib.request` + `json` + timeout handling
- Less ergonomic but zero dependencies

**Provider-specific SDKs (optional):**
- `deepl` (official DeepL Python SDK) - OPTIONAL
- `google-cloud-translate` (Google Cloud Translation) - OPTIONAL
- For MVP: Use direct HTTP API calls (no SDKs)

---

## 6. Testing Strategy

### 6.1 Unit Tests (70%)

- Provider base contract (dataclasses, enums)
- Provider registry (register, list, get)
- Mock provider (deterministic output)
- Circuit breaker (state transitions)
- Rate limiter (token bucket)
- Glossary builder (hashing, conflict resolution, provider adapters)
- MT cache (roundtrip, TTL, glossary_hash invalidation)

### 6.2 Integration Tests (20%)

- Provider chain with fallback (mock providers)
- Circuit breaker integration (trigger OPEN, cooldown, HALF_OPEN)
- Rate limiter integration (exceed limit → fallback)
- MT cache hit rate gate (>80% on second run)
- Term extraction presets (reproducibility)

### 6.3 E2E Tests (10%)

- Full translation workflow (TM → Dict → MT)
- Explainability dialog (UI test)
- Settings persistence (QSettings roundtrip)

### 6.4 Performance Tests

- Cache lookup < 10ms
- Provider chain decision < 1ms (in-memory checks only)
- Hit rate >80% on second run (DoD gate)

---

## 7. Risks and Mitigations

### 7.1 Risks

1. **API rate limits** (High)
   - Mitigation: Circuit breaker + rate limiter + fallback chain

2. **Glossary format compatibility** (Medium)
   - Mitigation: Provider adapters + unit tests for each format

3. **Network errors and timeouts** (Medium)
   - Mitigation: Timeout on all requests, fallback on NETWORK error

4. **Provider API changes** (Medium)
   - Mitigation: Version detection (model_version), graceful degradation

5. **Security (API keys)** (High)
   - Mitigation: CredentialStore (AES-256-GCM + OS keyring), already implemented in P0

### 7.2 Fallback Strategy

If all providers fail:
- Return `TranslationResult()` (empty, source="none")
- Log structured error with trace_id
- UI shows "MT unavailable" message (non-blocking)
- User can still manually translate or import from dictionary

---

## 8. Next Steps (PATCH-P1-T01)

After PATCH-P1-T00 (docs) is approved:

1. **PATCH-P1-T01:** BaseProvider + Registry + Errors + Mock
   - Create `app/infra/translators/base_provider.py`
   - Create `app/infra/translators/providers_registry.py`
   - Create `app/infra/translators/providers/mock_provider.py`
   - Create `tests/test_p1_translation_provider_base.py`
   - Verify: `python -m compileall -q app tests`
   - Verify: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_p1_translation_provider_base.py -q`

---

**End of Plan - Ready for Review**
