# CODEX PROMPT: Batch Translation System - Production Fix

## Context

**Product**: HDLE Premium - Professional Hebrew-Russian CAT Tool
**Issue**: Batch translation для Dictionary и Terms tabs не работает
**Priority**: P0 (блокирующий функционал)
**Current Status**: V2 implementation созда, но НЕ интегрирована, старый код сломан

---

## Critical Errors (Must Fix)

### Error #1: Terms Tab Crash
```
TypeError: BatchTranslateWorker.__init__() got an unexpected keyword argument 'context'
File: app/ui/terms_view.py:596
```

**Root Cause**: API mismatch - `BatchTranslateWorker` expects `tab_type`, but terms_view passes `context`

### Error #2: Dictionary Tab - Worker Timeout/Death
```
[Worker] Loading model... (ctranslate2)
WARNING: Worker ping timeout: facebook/nllb-200-distilled-1.3B
ERROR: Worker process died during startup
ERROR: Worker startup error: Worker failed to start (failed after 240.0s)
```

**Root Cause**: Worker process crashes during CTranslate2 model loading (unknown cause)

### Error #3: Force Provider Not Supported
```
WARNING: Force provider 'local_nllb' requested but not yet supported.
```

**Root Cause**: BatchMTTranslateService doesn't implement force provider mode

---

## PHASE 0: Pre-Implementation Research (MANDATORY)

### 0.1 Read All Documentation
**CRITICAL**: Read these files BEFORE any code changes:

**Architecture & Context:**
- [ ] `README.md` - Project overview
- [ ] `docs/PATCH_SERIES_BATCH_V2.md` - Current V2 implementation status
- [ ] `docs/PATCH-00-ANALYSIS.md` - Bug analysis from yesterday
- [ ] `docs/INTEGRATION_GUIDE_V2.md` - How to integrate V2
- [ ] `MEMORY.md` (auto memory) - Recent milestones and lessons

**Code Inventory:**
- [ ] `app/services/batch_mt_translate_service.py` - OLD service (currently used)
- [ ] `app/services/batch_translate_engine_v2.py` - NEW engine (not integrated)
- [ ] `app/ui/workers.py` - OLD worker (`BatchTranslateWorker`)
- [ ] `app/ui/workers_batch_v2.py` - NEW worker (`BatchTranslateWorkerV2`)
- [ ] `app/ui/dictionary_view.py` - Dictionary tab (uses OLD worker)
- [ ] `app/ui/terms_view.py` - Terms tab (uses OLD worker)
- [ ] `app/infra/local_mt/worker_process.py` - Worker process for local MT
- [ ] `app/infra/translators/providers/local_nllb_provider.py` - Local NLLB provider

**Related Systems:**
- [ ] `app/infra/translators/providers_registry.py` - Provider registry
- [ ] `app/services/translation_service.py` - Translation resolution
- [ ] `app/domain/dto.py` - Check `ClusterStats` and `LemmaStats` attributes

### 0.2 Verify Preconditions
**Before ANY code changes, verify:**

**Model Installation:**
```bash
# Run these checks:
ls -lh "J:\HDLE\models\facebook_nllb-200-distilled-1.3B_ctranslate2"
# Expected: model.bin (~1.3GB), tokenizer files present

python -c "from pathlib import Path; p = Path(r'C:\Users\Win10_Game_OS\AppData\Local\HDLE\models\facebook_nllb-200-distilled-1.3B_ctranslate2'); print(f'Via junction: {p.resolve()}')"
# Expected: Resolves to J:\HDLE\models\...
```

**CTranslate2 Installation:**
```bash
python -c "import ctranslate2; print(f'CTranslate2 version: {ctranslate2.__version__}')"
# Expected: No errors, version printed

python -c "from transformers import NllbTokenizer; print('Tokenizer OK')"
# Expected: No errors
```

**Provider Registration:**
```bash
python -c "from app.infra.translators.providers_registry import ProvidersRegistry; r = ProvidersRegistry(); print(f'Providers: {list(r._providers.keys())}')"
# Expected: Should include 'local_nllb' or empty (lazy init)
```

**Test Project:**
```bash
# Verify Test_Translation project exists
python scripts/test_batch_translate_e2e_v2.py
# Expected: Project created or exists, 3 docs imported
```

### 0.3 Identify Blind Spots
**Answer these questions BEFORE planning:**

1. **API Contracts:**
   - What are the EXACT parameters for `BatchTranslateWorker.__init__()`?
   - What are the EXACT parameters for `BatchTranslateWorkerV2.__init__()`?
   - What attributes does `ClusterStats` have? (translation vs pinned_translation)
   - What attributes does `LemmaStats` have?

2. **Worker Process:**
   - WHY does worker die after 240s? Is it:
     - CTranslate2 crash?
     - Memory issue (1.3GB model too large)?
     - Permission issue with junction?
     - Missing dependencies in spawn context?
   - How to diagnose: Check worker logs, add more telemetry

3. **Provider Chain vs Force:**
   - Does `TranslationService.resolve_translation()` support force provider?
   - Does `BatchMTTranslateService` implement force provider?
   - If not, what needs to be added?

4. **Integration Status:**
   - Which code is currently active? OLD or NEW?
   - Can we safely switch to V2?
   - What's the rollback plan?

### 0.4 Risk Assessment
**High-Risk Areas (handle with care):**

1. **Worker Process Lifecycle:**
   - Spawning subprocess with CTranslate2 is fragile
   - Timeout too short → hang, too long → bad UX
   - Must handle: startup failure, runtime crash, clean shutdown

2. **Database Transactions:**
   - Chunked commits can leave partial state
   - Session management in QThread context
   - Rollback on error

3. **UI Thread Blocking:**
   - Any DB/network call in UI thread = freeze
   - Must use QThread for ALL heavy operations

4. **Backward Compatibility:**
   - Users may have ongoing translations
   - Don't break existing functionality
   - Gradual migration OLD → NEW

---

## PHASE 1: Diagnostic & Root Cause Analysis

### PATCH-FIX-00: Diagnose Worker Crash

**Objective**: Find out WHY worker process dies during model loading

**Steps:**

1. **Add Worker Diagnostic Script:**
   ```python
   # scripts/diagnose_worker_crash.py
   # Minimal script to load model OUTSIDE of app context
   # Test: Can CTranslate2 load model in standalone process?
   ```

2. **Test Scenarios:**
   - [ ] Standalone: Load model in simple Python script → works?
   - [ ] Multiprocessing: Load model in spawn process → works?
   - [ ] With logging: Check if logging handlers cause issue
   - [ ] Memory: Monitor RAM usage during load (1.3GB model)

3. **Check Dependencies in Worker:**
   - [ ] Are all imports available in spawned process?
   - [ ] Are environment variables inherited?
   - [ ] Is PYTHONPATH correct?

4. **Expected Findings:**
   - Either: CTranslate2 works standalone but fails in spawn → fix spawn context
   - Or: CTranslate2 fails everywhere → model corrupted or missing deps
   - Or: Timeout is real (model loads but >240s) → increase timeout further

**Output**: Root cause document with clear diagnosis

**DoD**:
- [ ] Worker crash root cause identified
- [ ] Reproducible test case created
- [ ] Fix approach documented

### PATCH-FIX-01: Fix API Mismatches

**Objective**: Align all code to consistent API

**Steps:**

1. **Inventory Current State:**
   ```bash
   # Find all calls to BatchTranslateWorker
   grep -r "BatchTranslateWorker(" app/ui/

   # Find all calls to BatchTranslateWorkerV2
   grep -r "BatchTranslateWorkerV2(" app/ui/
   ```

2. **Define Single Source of Truth:**
   - Choose: Use OLD worker OR NEW worker (not both)
   - Recommendation: Use NEW (`BatchTranslateWorkerV2`) - it's better designed
   - Document parameter contract in docstring

3. **Fix Terms View:**
   ```python
   # app/ui/terms_view.py
   # Change:
   worker = BatchTranslateWorker(items, options, context="terms")
   # To:
   worker = BatchTranslateWorkerV2(items, options, tab_type="terms")
   ```

4. **Fix Dictionary View:**
   ```python
   # app/ui/dictionary_view.py
   # Same fix
   worker = BatchTranslateWorkerV2(items, options, tab_type="dictionary")
   ```

**DoD**:
- [ ] All UI code uses same worker (V2)
- [ ] No API mismatch errors
- [ ] Syntax valid, imports work

### PATCH-FIX-02: Fix Force Provider Support

**Objective**: Implement `force:<provider_id>` mode in service layer

**Options:**

**Option A: Fix OLD Service** (Quick fix)
```python
# app/services/batch_mt_translate_service.py
# In _translate_and_write():
if options.provider_mode.startswith("force:"):
    provider_id = options.provider_mode.split(":", 1)[1]
    # Get provider from registry
    # Call provider.translate() directly
```

**Option B: Use NEW Engine** (Better, already implemented)
```python
# BatchTranslateEngineV2 already supports force provider
# Just switch UI to use V2
```

**Recommendation**: Option B (use V2 engine)

**DoD**:
- [ ] Force provider mode works
- [ ] Test: `force:local_nllb` translates using NLLB
- [ ] Test: Invalid provider → clear error message

---

## PHASE 2: Implementation Patches

### PATCH-FIX-03: Switch to V2 Engine (Atomic Migration)

**Objective**: Migrate Dictionary and Terms to use V2 worker + engine

**Steps:**

1. **Update Dictionary View:**
   ```python
   # app/ui/dictionary_view.py
   from app.ui.workers_batch_v2 import BatchTranslateWorkerV2
   from app.ui.dialogs.batch_progress_dialog_v2 import BatchProgressDialogV2
   from app.services.batch_translate_engine_v2 import BatchTranslateItem, BatchTranslateOptions

   def on_batch_translate(self):
       # ... existing code ...

       # Create worker V2
       worker = BatchTranslateWorkerV2(
           items=items,
           options=options,
           tab_type="dictionary",
       )

       # Create progress dialog V2
       progress_dialog = BatchProgressDialogV2(parent=self, total=len(items))

       # Connect signals
       worker.progress.connect(progress_dialog.update_progress)
       worker.stage_changed.connect(progress_dialog.update_stage)
       worker.finished.connect(lambda r: self.on_batch_finished_v2(r, progress_dialog))
       worker.error.connect(lambda e: self.on_batch_error_v2(e, progress_dialog))
       progress_dialog.cancel_requested.connect(worker.cancel)

       # Start
       worker.start()
       self._batch_worker = worker

   def on_batch_finished_v2(self, result, dialog):
       # Update counts
       dialog.update_counts(result.succeeded, result.skipped, result.failed)
       dialog.set_completed()

       # Show summary
       # Refresh data
       self.load_lemmas()
   ```

2. **Update Terms View:**
   - Same changes as Dictionary
   - Use `tab_type="terms"`

3. **Keep OLD Code (Safety):**
   - DON'T delete old worker/service yet
   - Keep for rollback if needed

**DoD**:
- [ ] Dictionary uses V2
- [ ] Terms uses V2
- [ ] Progress dialog shows stages
- [ ] Cancel works
- [ ] OLD code still present (safety)

### PATCH-FIX-04: Fix Worker Process Crash

**Based on findings from PATCH-FIX-00, implement fix:**

**Scenario 1: Timeout too short**
```python
# Increase timeout to 300s (5 minutes)
if not self.ping(timeout=300):
```

**Scenario 2: Missing dependencies in spawn**
```python
# In _worker_main(), add sys.path fix:
import sys
sys.path.insert(0, '/path/to/project')
```

**Scenario 3: Logging handlers issue (already fixed)**
- Already cleared in worker_main

**Scenario 4: CTranslate2 GPU issue**
```python
# Force CPU mode:
translator = ctranslate2.Translator(model_path, device="cpu", compute_type="int8")
```

**Scenario 5: Memory issue**
```python
# Add memory check before loading
import psutil
available_gb = psutil.virtual_memory().available / (1024**3)
if available_gb < 3:
    raise WorkerError(f"Insufficient memory: {available_gb:.1f}GB available, need 3GB")
```

**DoD**:
- [ ] Worker loads model successfully
- [ ] Startup time logged
- [ ] Error messages clear
- [ ] Works on slower systems

---

## PHASE 3: Testing & Validation

### Test Suite (All Must Pass)

**1. Syntax & Import Tests:**
```bash
python -c "import py_compile; py_compile.compile('app/ui/dictionary_view.py', doraise=True)"
python -c "import py_compile; py_compile.compile('app/ui/terms_view.py', doraise=True)"
python -c "from app.ui.workers_batch_v2 import BatchTranslateWorkerV2; print('OK')"
python -c "from app.services.batch_translate_engine_v2 import BatchTranslateEngineV2; print('OK')"
```

**2. Worker Diagnostic Test:**
```bash
python scripts/diagnose_worker_crash.py
# Expected: Model loads, no crash, timing logged
```

**3. E2E Test (Automated):**
```bash
python scripts/test_batch_translate_e2e_v2.py
# Expected: Exit code 0, 5 lemmas + 5 terms translated
```

**4. Manual UI Test (Critical):**

**Test Case 1: Dictionary - First Run**
- Launch app
- Open Test_Translation project
- Dictionary tab → select 5 rows without translation
- Translate Selected → Force provider: local_nllb → Fill empty only → Translate
- **Expected**:
  - Progress dialog appears
  - Stage: "Initializing translation engine..." (~2s)
  - Stage: "Translating..." (first time: 2-5 min for model load)
  - Stage: "Finalizing..." (~1s)
  - Dialog: "Translation completed! Succeeded: 5"
  - Translations appear in table

**Test Case 2: Dictionary - Second Run**
- Select another 5 rows
- Translate Selected (same settings)
- **Expected**:
  - Much faster (~10-30s, model already loaded)
  - Succeeded: 5

**Test Case 3: Terms - First Run**
- Terms tab → select 5 clusters
- Translate Selected → same settings
- **Expected**:
  - No crash
  - Translation completes
  - Succeeded: 5

**Test Case 4: Cancel**
- Select 20+ rows
- Start translation
- Click Cancel mid-process
- **Expected**:
  - Dialog: "Cancelling..."
  - Job stops gracefully
  - Partial results saved
  - UI responsive

**Test Case 5: Error Handling**
- Disconnect network (if using cloud providers)
- Try translation
- **Expected**:
  - Clear error message
  - No crash
  - Fallback to local_nllb works

**5. Performance Test:**
- Translate 50 rows in Dictionary
- **Expected**:
  - First run: <6 minutes (model load + translate)
  - Second run: <1 minute (translate only)
  - UI responsive throughout
  - No memory leaks

**6. Stress Test:**
- Translate 100+ rows
- **Expected**:
  - Completes without crash
  - Memory usage stable
  - Chunked commits work

---

## Definition of Done (DoD)

### Functional Requirements:
- [x] Dictionary: Batch translate works without hang
- [x] Terms: Batch translate works without crash
- [x] Force provider: `force:local_nllb` uses NLLB directly
- [x] Write modes: fill_empty, overwrite, skip_nonempty all work
- [x] Cancel: Stops gracefully, partial results saved
- [x] Progress: Real-time updates, clear stages

### Non-Functional Requirements:
- [x] Performance: Second run <1 minute for 50 rows
- [x] Reliability: No crashes, clear error messages
- [x] UX: UI responsive, progress visible, cancel works
- [x] Observability: Logs show job ID, timing, errors

### Quality Gates:
- [x] All syntax/import tests pass
- [x] E2E test passes (exit code 0)
- [x] Manual UI test: all 6 test cases pass
- [x] No regressions in other features
- [x] Documentation updated

### Code Quality:
- [x] No TODOs or FIXMEs in committed code
- [x] Error handling comprehensive
- [x] Logging consistent (job ID correlation)
- [x] Comments explain WHY, not WHAT

### Production Readiness:
- [x] Rollback plan documented
- [x] User-facing error messages clear
- [x] Performance acceptable on slow systems
- [x] Memory usage reasonable (<4GB peak)

---

## Risk Mitigation

### If Worker Still Crashes:
- **Plan B**: Disable local_nllb, use cloud providers only
- **Plan C**: Load model in main process (slow but stable)
- **Plan D**: External worker process (separate .exe)

### If Performance Poor:
- Reduce chunk size (50 → 20)
- Add parallel translation (multiple workers)
- Cache translations more aggressively

### If UI Freezes:
- Double-check: no DB calls in UI thread
- Add more progress updates
- Reduce chunk size

---

## Git Workflow

**Commit Strategy:**
- One commit per PATCH-FIX (atomic)
- Clear commit messages with before/after
- Co-authored-by tag

**Commit Template:**
```
fix(mt): [PATCH-FIX-XX] <short description>

Problem: <what was broken>
Root Cause: <why it was broken>
Solution: <how it's fixed>

Changes:
- file1.py: description
- file2.py: description

Tested:
- Test case 1: result
- Test case 2: result

DoD: <checklist of requirements met>

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

---

## Success Criteria

**Minimum Viable:**
- Dictionary: translate 10 rows successfully
- Terms: translate 10 rows successfully
- No crashes, no hangs

**Production Quality:**
- All 6 manual test cases pass
- E2E test passes
- Performance acceptable
- Error messages clear

**Premium Quality:**
- First-run UX smooth (<5 min total)
- Second-run fast (<30s for 50 rows)
- Cancel works predictably
- Progress updates informative

---

## Final Checklist Before Commit

- [ ] Read all documentation (Phase 0.1)
- [ ] Verify preconditions (Phase 0.2)
- [ ] Answer blind spot questions (Phase 0.3)
- [ ] Run diagnostic tests (PATCH-FIX-00)
- [ ] Fix API mismatches (PATCH-FIX-01)
- [ ] Implement force provider (PATCH-FIX-02)
- [ ] Migrate to V2 (PATCH-FIX-03)
- [ ] Fix worker crash (PATCH-FIX-04)
- [ ] All tests pass (Phase 3)
- [ ] DoD checklist complete
- [ ] Code reviewed (self or pair)
- [ ] Commit message clear
- [ ] User can reproduce success

---

## Notes for Implementation

**Philosophy:**
- **Measure twice, cut once** - thorough research before coding
- **Fail fast, fail clearly** - explicit error messages
- **Progressive enhancement** - make it work, then make it fast
- **Premium quality** - no shortcuts, no hacks

**Anti-Patterns to Avoid:**
- ❌ Coding without reading docs first
- ❌ Fixing symptoms instead of root cause
- ❌ Committing without testing
- ❌ Leaving TODO comments
- ❌ Breaking backward compatibility without plan

**Best Practices:**
- ✅ Read docs → understand → plan → implement → test → commit
- ✅ One PATCH = one problem = one commit
- ✅ Test after every change
- ✅ Clear error messages for users
- ✅ Observability (logs, metrics, traces)

---

END OF CODEX PROMPT
