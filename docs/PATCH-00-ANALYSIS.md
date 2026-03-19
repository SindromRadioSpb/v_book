# PATCH-00: Bug Analysis - Dictionary Hang & Terms Crash

## Architecture Flow Map

### 1. UI Layer (Dictionary/Terms)
- User selects rows → "Translate Selected..."
- `on_batch_translate()` → Shows `BatchTranslateDialog`
- User selects:
  - Provider Mode: chain / force:<provider_id>
  - Write Mode: FILL_EMPTY / OVERWRITE / SKIP_NON_EMPTY
- Creates `BatchTranslateWorker` (QThread)
- Worker runs in background, emits signals (progress, finished, error)

### 2. Service Layer
- `BatchMTTranslateService.execute_batch()`:
  - Accepts List[BatchTranslateItem]
  - Splits into chunks (default: 50)
  - For each item: calls `TranslationService.resolve_translation()`
  - Writes results via `_write_lemma()` / `_write_term_cluster()` / `_write_tm_entry()`
  - Commits per chunk

### 3. Provider Layer
- `TranslationService.resolve_translation()`:
  - Uses provider chain or force provider
  - Calls `ProvidersRegistry.get()` → `LocalNLLBProvider.translate()`
  - `LocalNLLBProvider`:
    - Initializes `LocalMTWorker` (lazy, once per session)
    - Segments text if >512 tokens
    - Sends IPC request to worker process
    - Waits for response with timeout
    - Applies glossary postprocessing (TM overlay)

### 4. Worker Process (multiprocessing)
- `LocalMTWorker`:
  - Spawns new process with `_worker_main()`
  - Loads CTranslate2 model (20-30s first time, ~2.6 GB)
  - IPC loop: poll(60s) → recv() → translate → send()
  - Critical: Clears inherited logging handlers to avoid spawn issues

---

## Bug #1: Dictionary Hang (Infinite)

### Symptoms
- UI calls batch translate on Dictionary tab
- Progress dialog appears
- UI freezes or hangs indefinitely
- No error message, no crash, just hang

### Potential Root Causes (Code Analysis)

#### 1. Worker Startup Timeout
**File**: `app/infra/local_mt/worker_process.py:414`
**Code**:
```python
# Wait for worker to be ready (ping)
# Model loading can take 60-120 seconds on slower systems
```

**Issue**: If timeout not properly set, parent process may wait forever.

**Evidence**:
- `LocalMTWorker.__init__()` calls `_start_worker()`
- Needs to ping worker to confirm readiness
- If worker dies during model loading → parent hangs waiting for response

#### 2. IPC Connection Deadlock
**File**: `app/infra/local_mt/worker_process.py:399-411`
**Code**:
```python
parent_conn, child_conn = multiprocessing.Pipe()
self.process = ctx.Process(target=_worker_main, args=(child_conn, ...))
self.process.start()
```

**Issue**: If worker process crashes during startup, parent may hang on conn.recv().

#### 3. Blocking UI Thread (False Positive)
**File**: `app/ui/workers.py:1181`
**Code**:
```python
with db_service.get_session() as session:
    result = service.execute_batch(...)
```

**Verdict**: This runs in QThread (not UI thread), so likely NOT the cause.

### Diagnostic Additions Needed
1. Log worker startup duration with timeout
2. Log worker process PID and status
3. Add startup timeout (90s recommended)
4. Log IPC request/response with correlation ID

---

## Bug #2: Terms Crash

### Symptoms
- UI calls batch translate on Terms tab
- App crashes or shows error dialog
- Exception raised, worker may or may not complete

### Potential Root Causes (Code Analysis)

#### 1. Normalization Error
**File**: `app/services/batch_mt_translate_service.py:433`
**Code**:
```python
normalized = normalize_for_tm(item.src_lang, item.source_text, "term_cluster")
src_norm = normalized.norm
```

**Issue**: `normalize_for_tm()` may raise exception for:
- Empty or None source_text
- Invalid Unicode characters
- Language code mismatch

**Evidence**: Terms may have complex multi-word expressions with special chars.

#### 2. Database Constraint Violation
**File**: `app/services/batch_mt_translate_service.py:440-464`
**Code**:
```python
stmt = select(TMEntry).where(
    TMEntry.project_id == item.project_id,
    TMEntry.kind == "term_cluster",
    TMEntry.src_norm == src_norm,
)
```

**Issue**: If `src_norm` is None or empty, WHERE clause may fail.

**Schema**: `tm_entry.src_norm` is NOT NULL → IntegrityError if null.

#### 3. Session/Transaction Error
**File**: `app/ui/workers.py:1181`
**Code**:
```python
with db_service.get_session() as session:
    result = service.execute_batch(...)
```

**Issue**: If exception occurs mid-batch, session may be invalid for subsequent chunks.

### Diagnostic Additions Needed
1. Wrap `normalize_for_tm()` with try/except and log input on error
2. Validate `src_norm` before INSERT (check not None, not empty)
3. Add per-row error handling in `_write_term_cluster()`
4. Log entity_id + exception for failed rows

---

## Test Preconditions

### Model Installation
- [x] Model exists: `J:\HDLE\models\facebook_nllb-200-distilled-1.3B_ctranslate2`
- [x] Model size: 1.3 GB (model.bin)
- [x] Tokenizer files present

### Test Data
- [x] Test file exists: `J:\Project_Vibe/V_book -info files/Тестовые тексты/Test_Translation.txt`
- [x] Content: 3 Hebrew sentences
- [ ] Project created: "Test_Translation" (NEED TO CREATE)

### Provider Registration
- [ ] Check: `app.main` calls `initialize_local_providers()` at startup
- [ ] Verify: local_nllb registered in ProvidersRegistry
- [ ] Test: Worker can start and translate

---

## Reproduction Plan

### Dictionary Hang Reproduction
1. Create "Test_Translation" project
2. Import test file → process documents
3. Open Dictionary tab
4. Select 10-20 rows without translation
5. Translate Selected → Force provider: local_nllb → Fill empty only
6. **Monitor**:
   - Worker startup log
   - IPC request/response
   - Timeout triggers
   - Process status

### Terms Crash Reproduction
1. Same project
2. Extract terms (Terms tab → Extract Terms)
3. Select 10-20 term clusters without translation
4. Translate Selected → same settings
5. **Monitor**:
   - normalize_for_tm() calls
   - src_norm values before INSERT
   - Exception stack traces
   - Database errors

---

## Minimal Diagnostic Telemetry (Safe to Add)

### 1. Job ID Correlation
**File**: `app/services/batch_mt_translate_service.py:98`
**Add**:
```python
trace_id = str(uuid.uuid4())  # Already exists
logger.info(
    f"[JOB:{trace_id[:8]}] Batch translate start: total={len(items)}, "
    f"provider_mode={options.provider_mode}, write_mode={options.write_mode}"
)
```

### 2. Worker Startup Duration
**File**: `app/infra/local_mt/worker_process.py:394`
**Add**:
```python
import time
start_time = time.perf_counter()
logger.info(f"[WORKER] Starting worker for {self.model_id}")
# ... existing code ...
elapsed = time.perf_counter() - start_time
logger.info(f"[WORKER] Worker ready: {self.model_id} ({elapsed:.1f}s)")
```

### 3. Chunk Progress
**File**: `app/services/batch_mt_translate_service.py:146`
**Add**:
```python
logger.debug(
    f"[JOB:{trace_id[:8]}] Committed chunk {chunk_start}-{chunk_end}: "
    f"succeeded={chunk_succeeded}, failed={chunk_failed}"
)
```

### 4. Per-Row Error Context
**File**: `app/services/batch_mt_translate_service.py:345`
**Add**:
```python
logger.warning(
    f"[JOB:{trace_id[:8]}] Row translation failed: "
    f"entity_id={item.entity_id}, entity_type={item.entity_type}, "
    f"source_text='{item.source_text[:50]}...', error={str(e)}"
)
```

---

## Next Steps

1. Add minimal telemetry (above)
2. Create Test_Translation project programmatically
3. Reproduce both bugs with telemetry enabled
4. Capture logs + stack traces
5. Confirm root causes
6. Proceed to PATCH-01 (redesign)
