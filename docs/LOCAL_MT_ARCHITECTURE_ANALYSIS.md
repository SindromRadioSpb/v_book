# Local MT Architecture Analysis (PATCH-00)

**Date:** 2026-02-07
**Status:** Analysis Complete
**Purpose:** Identify integration points for LocalNLLBProvider and LocalSeamlessProvider

---

## Executive Summary

Local MT providers (NLLB + Seamless M4T) will integrate into existing provider architecture with minimal changes. All infrastructure is ready:
- ✅ BaseProvider contract defined
- ✅ ProvidersRegistry for registration
- ✅ Provider chain with fallback
- ✅ Circuit breaker + rate limiter
- ✅ MT cache with glossary_hash
- ✅ GlossaryBuilderService for approved terms

**New components needed:**
- Model Resource Manager (manifest-based verification)
- Worker process (spawn-safe, IPC-based)
- Sentence segmentation (quality enhancement)
- Glossary postprocess (term replacement after translation)
- LocalNLLBProvider + LocalSeamlessProvider implementations

---

## 1. Current Architecture Analysis

### 1.1 BaseProvider Contract

**File:** `app/infra/translators/base_provider.py`

**Abstract methods (MUST implement):**
```python
class BaseProvider(ABC):
    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique ID: 'local_nllb', 'local_seamless'"""
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """'Local NLLB (Offline)', 'Local Seamless (Offline)'"""
        pass

    @property
    @abstractmethod
    def supports_glossary(self) -> bool:
        """True (postprocessing)"""
        pass

    @abstractmethod
    def translate(self, request: TranslationRequest) -> TranslationResult:
        """MUST NOT raise exceptions - return error_kind on failure"""
        pass
```

**Optional methods (can override):**
```python
def supports_batch(self) -> bool:
    """True for LocalNLLBProvider (worker supports batching)"""
    return False

def get_model_version(self) -> str:
    """Return model ID + backend for cache key"""
    return "nllb-200-distilled-1.3B-ctranslate2"

def healthcheck(self) -> bool:
    """Verify model installed + worker alive"""
    return True
```

### 1.2 TranslationErrorKind Taxonomy

**Existing errors:**
- `NETWORK` - Connection timeout (not applicable for local)
- `AUTH` - Invalid API key (not applicable for local)
- `RATE_LIMIT` - Rate limit exceeded (not applicable for local)
- `QUOTA` - Quota exceeded (not applicable for local)
- `SERVER` - Server error (not applicable for local)
- `INVALID_REQUEST` - Bad request (applicable: invalid language pair)
- `UNSUPPORTED` - Feature not supported (applicable: unsupported language pair)
- `UNKNOWN` - Catch-all

**New errors needed for Local MT:**
- `MODEL_MISSING` - Model not installed → map to UNSUPPORTED
- `OOM` - Out of memory → map to SERVER
- `TIMEOUT` - Inference timeout → map to NETWORK (even though offline)
- `INFERENCE_ERROR` - Model inference failed → map to SERVER

**Strategy:** Use existing taxonomy, map local errors to closest match.

### 1.3 Provider Chain Integration

**File:** `app/services/translation_service.py`
**Method:** `_translate_via_provider_chain()`

**Current chain order (configurable via settings):**
```python
chain = settings.get_json("mt/providers/chain", default=[])
# Example: ["deepl", "microsoft", "libretranslate", "mock"]
```

**Proposed chain order (with local MT):**
```python
chain = ["local_nllb", "local_seamless", "deepl", "microsoft", "libretranslate"]
```

**Integration points:**
1. **Registration:** Add to ProvidersRegistry at startup
2. **Health check:** Skip provider if `healthcheck()` returns False
3. **Circuit breaker:** Track failures, open circuit if threshold reached
4. **Rate limiter:** No rate limit for local (set very high or skip)
5. **Cache:** Use existing cache infrastructure (glossary_hash included)
6. **Glossary:** Use GlossaryBuilderService + postprocess after translation

### 1.4 MT Cache Integration

**File:** `app/services/translation_service.py`
**Method:** `_build_cache_key()`

**Current cache key:**
```python
cache_key = sha256(
    normalized_text
    + "|" + src_lang
    + "|" + tgt_lang
    + "|" + provider_id
    + "|" + glossary_hash
)
```

**Required for Local MT:**
```python
cache_key = sha256(
    normalized_text
    + "|" + src_lang
    + "|" + tgt_lang
    + "|" + provider_id
    + "|" + model_id  # NEW: "facebook/nllb-200-distilled-1.3B"
    + "|" + backend   # NEW: "ctranslate2" or "transformers"
    + "|" + glossary_hash
)
```

**Action:** Update `_build_cache_key()` to include `model_id` and `backend` from `request.meta`

### 1.5 GlossaryBuilderService Integration

**File:** `app/services/glossary_builder_service.py`

**Usage in provider chain:**
```python
# Build canonical glossary (already done in P1-T05)
canonical_glossary = glossary_service.build_canonical_glossary(
    src_lang="he",
    tgt_lang="ru"
)

# For Local MT: glossary_postprocess instead of provider payload
# (because NLLB/Seamless don't support glossary natively)
```

**Local MT glossary strategy:**
1. **Before translation:** Build canonical glossary (existing)
2. **During translation:** Skip glossary payload (local MT doesn't support)
3. **After translation:** Apply glossary_postprocess (replace terms in translated text)

### 1.6 Circuit Breaker + Rate Limiter

**Circuit Breaker:**
- **Applies to local MT:** YES (track timeouts, OOM, inference errors)
- **Failure threshold:** 3 (same as external providers)
- **Cooldown:** 60 seconds

**Rate Limiter:**
- **Applies to local MT:** NO (unlimited offline requests)
- **Configuration:** Set `requests_per_minute=9999` or skip entirely

---

## 2. New Components Architecture

### 2.1 Model Resource Manager

**File:** `app/services/local_models/model_resource_manager.py`

**Responsibilities:**
- Get models root directory (`%LOCALAPPDATA%\HDLE\models` on Windows)
- Load/verify manifest.json (sha256, size, languages, backend)
- Check if model installed (`is_installed()`)
- Mark degraded if manifest invalid

**Manifest format:**
```json
{
  "model_id": "facebook/nllb-200-distilled-1.3B",
  "backend": "ctranslate2",
  "package_sha256": "abc123...",
  "size_bytes": 1234567890,
  "languages": {
    "source": ["heb_Hebr"],
    "target": ["rus_Cyrl"]
  },
  "created_at": "2026-02-07T12:34:56Z"
}
```

**Integration points:**
- `LocalNLLBProvider.healthcheck()` → calls `model_manager.is_installed("nllb-200-distilled-1.3B", "ctranslate2")`

### 2.2 Worker Process

**File:** `app/infra/local_mt/worker_process.py`

**Architecture:**
```
Main Process (UI)
    ↓ IPC (multiprocessing.connection)
Worker Process (spawn context)
    ↓ loads model
    ↓ inference loop
```

**Protocol:**
- **Request:** `{"type": "ping"}` → Response: `{"ok": true}`
- **Request:** `{"type": "translate", "request": {...}}` → Response: `{"ok": true, "result": "...", "meta": {...}}`
- **Request:** `{"type": "shutdown"}` → Worker exits

**Safety:**
- Windows-safe: `multiprocessing.get_context("spawn")`
- Timeouts: client-side timeout (provider waits max X seconds)
- No hangs: worker uses try/except, never raises uncaught exceptions

**Integration points:**
- `LocalNLLBProvider.__init__()` → starts worker
- `LocalNLLBProvider.translate()` → sends request to worker
- `LocalNLLBProvider.__del__()` → shuts down worker

### 2.3 Sentence Segmentation

**File:** `app/services/local_mt/segmentation.py`

**Algorithm:**
```
Input: "שלום עולם! זה טסט. עוד משפט?"

1. Normalize: \r\n→\n, trim
2. Split by: . ! ? … \n (preserve separators)
3. Result:
   segments = ["שלום עולם!", "זה טסט.", "עוד משפט?"]
   separators = ["", "", ""]

4. Hard limits: max_chars_per_segment=1000 (NLLB degrades on long inputs)

Reassembly: segments[0] + separators[0] + segments[1] + separators[1] + ...
```

**Integration points:**
- `LocalNLLBProvider.translate()`:
  1. Segment input
  2. Translate each segment via worker (batch if supported)
  3. Reassemble with original separators

### 2.4 Glossary Postprocess

**File:** `app/services/local_mt/glossary_postprocess.py`

**Algorithm:**
```
Input:
  translated_text = "Привет мир! Это тест."
  approved_terms = [
    {"source": "שלום", "target": "ПРИВЕТ"},
    {"source": "עולם", "target": "МИР"}
  ]

1. Sort terms by source length DESC (longer terms win)
2. For each term:
   - Find all occurrences of source in translated_text
   - Replace with target (word boundaries)
3. Return: "ПРИВЕТ МИР! Это тест."
   + meta: {"glossary_applied": true, "replacements": 2}
```

**Integration points:**
- `LocalNLLBProvider.translate()`:
  1. Translate via worker
  2. Get canonical glossary from GlossaryBuilderService
  3. Apply glossary_postprocess to translated text
  4. Return result with `used_glossary=True`

---

## 3. Integration Points Summary

### 3.1 Files to Create

**Core components:**
1. `app/services/local_models/model_resource_manager.py`
2. `app/infra/local_mt/worker_process.py`
3. `app/services/local_mt/segmentation.py`
4. `app/services/local_mt/glossary_postprocess.py`

**Providers:**
5. `app/infra/translators/providers/local_nllb_provider.py`
6. `app/infra/translators/providers/local_seamless_provider.py`

**Scripts:**
7. `scripts/models/install_local_mt_models.py`

**Tests:**
8. `tests/test_local_mt_segmentation.py`
9. `tests/test_local_mt_glossary_postprocess.py`
10. `tests/test_local_nllb_provider.py` (unit + integration)

**Docs:**
11. `docs/LOCAL_MT.md`

### 3.2 Files to Modify

**Minimal changes (integration only):**
1. `app/services/translation_service.py`
   - Update `_build_cache_key()` to include `model_id` + `backend`
   - Register local providers at startup (optional, can be in registry)

2. `app/infra/translators/providers_registry.py`
   - Register LocalNLLBProvider and LocalSeamlessProvider

3. Settings (QSettings keys)
   - `mt/providers/chain` → prepend `["local_nllb", "local_seamless"]`
   - `mt/local/models_root` → `%LOCALAPPDATA%\HDLE\models` (default)

### 3.3 Dependencies (External Packages)

**Required:**
- `transformers>=4.30.0` (for baseline backend)
- `torch>=2.0.0` (already in project for Stanza)
- `sentencepiece>=0.1.99` (for NLLB tokenizer)

**Optional (for CTranslate2 backend):**
- `ctranslate2>=3.20.0` (faster inference, quantization support)

**Installation strategy:**
- Add to `pyproject.toml` under `[project.optional-dependencies]`
- Create `local-mt` extra: `pip install -e .[local-mt]`

---

## 4. Risk Analysis

### 4.1 Technical Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Model download size (1.3GB NLLB, 9GB Seamless)** | HIGH | Download on-demand via CLI script, not bundled in installer |
| **Worker process crash** | MEDIUM | Circuit breaker opens after 3 failures, fallback to external providers |
| **OOM on large inputs** | MEDIUM | Sentence segmentation + hard limits (max_tokens=512) |
| **Windows spawn context overhead** | LOW | Amortized across many translations (worker stays alive) |
| **Glossary postprocess accuracy** | LOW | Use word boundaries, test on Hebrew edge cases |

### 4.2 UX Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| **User doesn't install models** | MEDIUM | Health check returns False, local providers skipped gracefully |
| **First translation slow (model loading)** | LOW | Show progress indicator "Loading model..." |
| **Disk space (10GB+ for both models)** | MEDIUM | Document requirements, provide disk space check in installer |

---

## 5. Decision Log

### Decision 1: Glossary Strategy
**Options:**
- A) Fine-tune NLLB with custom dictionary (complex, slow)
- B) Postprocess translated text with term replacement (simple, fast)

**Decision:** B (Glossary postprocess)
**Rationale:** NLLB doesn't support glossaries natively, postprocessing is deterministic and testable

### Decision 2: Worker Architecture
**Options:**
- A) Thread-based (in-process)
- B) Process-based (spawn context)

**Decision:** B (Process-based)
**Rationale:** Avoid GIL contention, proper isolation, Windows-safe

### Decision 3: Model Backend Priority
**Options:**
- A) CTranslate2 only (fastest)
- B) Transformers only (simplest)
- C) CTranslate2 preferred, Transformers fallback

**Decision:** C (Hybrid)
**Rationale:** CTranslate2 faster (3-4x) but requires conversion, Transformers as baseline

### Decision 4: Cache Key Strategy
**Options:**
- A) Include model_id + backend in cache key
- B) Use only provider_id

**Decision:** A (Granular keying)
**Rationale:** Different models produce different translations, cache should reflect this

---

## 6. Next Steps (PATCH-01 onwards)

**PATCH-01:** Model Resource Manager (2 days)
- Implement `model_resource_manager.py`
- Manifest format + validation
- Tests for manifest verification

**PATCH-02:** CLI Script for Model Installation (2 days)
- `install_local_mt_models.py`
- Hugging Face Hub integration
- SHA256 verification

**PATCH-03:** Worker Process (3 days)
- `worker_process.py`
- IPC protocol (ping/translate/shutdown)
- Timeout + error handling

**PATCH-04:** Sentence Segmentation (2 days)
- `segmentation.py`
- Preserve separators for reassembly
- Hard limits (max_chars, max_tokens)

**PATCH-05:** Glossary Postprocess (2 days)
- `glossary_postprocess.py`
- Word boundary replacement
- Replacement count tracking

**PATCH-06:** LocalNLLBProvider (3 days)
- Implement provider
- Health check + worker integration
- Segmentation + glossary postprocess

**PATCH-07:** LocalSeamlessProvider (2 days)
- Similar to NLLB but different model

**PATCH-08:** Provider Chain Integration (2 days)
- Register providers
- Update chain order
- Health check before adding to chain

**PATCH-09:** Cache Keying Update (1 day)
- Update `_build_cache_key()` for model_id + backend

**PATCH-10:** Documentation (1 day)
- `docs/LOCAL_MT.md`
- Installation guide
- License notes (CC-BY-NC 4.0)

---

## 7. Acceptance Criteria (DoD)

**Provider Integration:**
- ✅ LocalNLLBProvider and LocalSeamlessProvider exist
- ✅ Registered in ProvidersRegistry
- ✅ Participate in provider chain
- ✅ Health check degrades gracefully (model missing → skip provider)

**Offline:**
- ✅ Translation works without internet (if models installed)
- ✅ No network calls after model installation

**UI Non-Blocking:**
- ✅ Inference in worker process (UI never freezes)
- ✅ Timeouts work correctly

**Cache:**
- ✅ Cache key includes provider+model+backend+glossary_hash
- ✅ Hit rate increases on second run

**Quality:**
- ✅ Sentence segmentation enabled
- ✅ Max segment length enforced
- ✅ Glossary postprocess works

**Glossary:**
- ✅ Approved terms applied via postprocess
- ✅ Replacement count tracked
- ✅ Deterministic (same terms → same replacements)

**Documentation:**
- ✅ `docs/LOCAL_MT.md` describes installation, paths, license

---

**End of PATCH-00 Analysis**
