# Task 16: Premium Progress UI - Pre-Flight Report

## Executive Summary

**Problem**: Premium Progress UI remains static (0/632, Speed/ETA "calculating...", empty activity log) during real translation.

**Root Cause**: `TranslateAllFilteredWorker` passes `progress_callback=None` to `BatchMTTranslateService.execute_batch()`, causing UI updates **only after entire 200-item batch completes** (can be 1-2 minutes without updates).

---

## Two Translation Paths (Current Implementation)

### PATH 1: "All pages (filtered)" ✅ USES PREMIUM UI
**File**: `app/ui/dictionary_view.py:861-911`

- **Worker**: `TranslateAllFilteredWorker`
- **Dialog**: `BatchProgressDialogV3` (premium)
- **Signals connected**:
  - `progress` → `update_progress`
  - `stats_updated` → `update_counts`
  - `row_translated` → `add_recent_item`
  - Pause/Resume/Cancel → worker methods
- **Worker storage**: `self._batch_worker` ✓ (correct)
- **Dialog storage**: Local variable (not `self._progress_dialog`) ⚠️ (minor concern, PyQt parent usually prevents GC)

### PATH 2: "Current page" ❌ USES OLD UI
**File**: `app/ui/dictionary_view.py:912-961`

- **Worker**: `BatchTranslateWorker` (old)
- **Dialog**: `BatchProgressDialog` (old, NOT V3!)
- **Signals connected**: Only `progress` (missing `stats_updated`, `row_translated`)
- **Problem**: Old path doesn't use premium UI at all!

---

## Top 3 Root Causes (Ranked by Impact)

### 🔥 CAUSE #1: Worker doesn't emit progress during BatchMTTranslateService execution
**Evidence**: `app/ui/workers.py:1798-1804`

```python
chunk_result = batch_service.execute_batch(
    session=session,
    items=items,  # 200 items (id_fetch_chunk)
    options=options,  # chunk_size=25 inside
    progress_callback=None,  # ⚠️ NO CALLBACK!
    cancel_check=lambda: self._cancel_requested,
)
```

**What happens**:
1. Worker fetches 200 IDs from DB (id_fetch_chunk)
2. Passes 200 items to `BatchMTTranslateService.execute_batch()`
3. Service translates 200 items in 8 sub-chunks (200/25 = 8)
4. Service calls `progress_callback` after each 25-item sub-chunk
5. **BUT worker passed `progress_callback=None`**, so NO callbacks!
6. Worker emits progress **ONLY after entire 200-item batch completes** (line 1819)

**Impact**: With 632 items:
- Batch 1: 200 items, ~1-2 min → UI stays at "0/632 (0%)"
- Batch 2: 200 items, ~1-2 min → UI jumps to "200/632 (31%)"
- Batch 3: 200 items, ~1-2 min → UI jumps to "400/632 (63%)"
- Batch 4: 32 items → UI jumps to "632/632 (100%)"

**User perception**: "UI is frozen/stuck" during first 1-2 minutes.

**Service supports callbacks**: `app/services/batch_mt_translate_service.py:153-154`

```python
# Progress callback
if progress_callback:
    progress_callback(completed, len(items))
```

**Fix**: Pass real callback to emit progress/stats during service execution.

---

### ⚠️ CAUSE #2: Two paths use different workers + dialogs (code duplication)
**Evidence**:
- PATH 1 (All pages): TranslateAllFilteredWorker + BatchProgressDialogV3
- PATH 2 (Current page): BatchTranslateWorker + BatchProgressDialog (old)

**Impact**:
- Current page doesn't use premium UI
- Code duplication (two workers, two dialogs)
- Inconsistent UX between scopes

**Fix** (per task_16.md Patch 1): Unify both paths into single pipeline with `ProgressAwareBatchTranslateWorker`.

---

### 📝 CAUSE #3: Missing heartbeat/stage updates in dialog
**Evidence**: `BatchProgressDialogV3` has:
- ✅ Elapsed time tracking
- ✅ ETA/Speed calculation
- ❌ NO QTimer for auto-updates
- ❌ NO "Stage" label (Initializing/Fetching/Translating/Waiting provider)
- ❌ NO "Last activity: Xs ago" label

**Impact**: Even if progress updates come slowly, UI looks "dead" without:
- Elapsed time ticking every second
- Stage showing current phase
- Heartbeat indicator

**Fix** (per task_16.md Patch 2): Add QTimer (500ms) for elapsed/heartbeat updates, add Stage label.

---

## Signal Signatures Verification

### TranslateAllFilteredWorker signals (`app/ui/workers.py:1590-1597`):
```python
progress = pyqtSignal(int, int)        # (completed, total) ✅
stats_updated = pyqtSignal(int, int, int)  # (succeeded, skipped, failed) ✅
row_translated = pyqtSignal(str, str, bool)  # (entity_id, translation, success) ✅
finished = pyqtSignal(object)          # BatchTranslateResult ✅
error = pyqtSignal(str) ✅
paused = pyqtSignal() ✅
resumed = pyqtSignal() ✅
```

### BatchProgressDialogV3 slots (`app/ui/dialogs/batch_progress_dialog_v3.py`):
```python
def update_progress(self, completed: int, total: int)  # Line 181 ✅
def update_counts(self, succeeded: int, skipped: int, failed: int)  # Line 196 ✅
def add_recent_item(self, entity_id: str, translation: str, success: bool)  # Line 227 ✅
```

**Signatures match** ✅ - no type mismatch issues.

---

## Worker/Dialog Lifecycle

### dictionary_view.py:910:
```python
worker.start()
self._batch_worker = worker  # ✅ Stored in self
```

### dictionary_view.py:878:
```python
progress_dialog = BatchProgressDialogV3(parent=self, total=filtered_count)
progress_dialog.show()
# ⚠️ NOT stored in self._progress_dialog
```

**Analysis**:
- Worker stored correctly (prevents GC)
- Dialog not stored, but has `parent=self`, so PyQt keeps reference
- **Minor concern**: If `dictionary_view` is closed during translation, dialog might not receive proper cleanup
- **Not critical** for current static UI bug, but should fix in final patch

---

## Next Steps (Following task_16.md order)

### PATCH 1: Pass progress_callback to BatchMTTranslateService ⚡ P0
**Goal**: Fix static UI by emitting progress during service execution.

**Changes**:
1. In `TranslateAllFilteredWorker.run()`, define callback:
   ```python
   def on_item_progress(completed_in_batch, total_in_batch):
       # Update worker-level completed
       # Emit progress/stats signals
   ```
2. Pass callback to `batch_service.execute_batch(progress_callback=on_item_progress)`
3. Test: Progress should update every 25 items (translation_chunk), not every 200

### PATCH 2: Add heartbeat/stage to BatchProgressDialogV3
**Goal**: Make UI feel "alive" even during slow updates.

**Changes**:
1. Add QTimer (500ms) → update elapsed time, mark last activity
2. Add Stage label (Initializing/Fetching/Translating/Waiting/Paused/Cancelling)
3. Add `stage_updated` signal to worker
4. Emit stages at key points

### PATCH 3: Unify two paths (optional, but recommended)
**Goal**: Current page should also use premium UI.

**Changes**:
1. Modify `BatchTranslateWorker` to emit same signals as `TranslateAllFilteredWorker`
2. OR: Use `TranslateAllFilteredWorker` with `IDsListTargetSource` for Current page
3. Both paths → BatchProgressDialogV3

---

## Diagnostic Flag

Add to `app/infra/config.py` or environment:
```python
HDLE_DEBUG_PROGRESS = os.getenv("HDLE_DEBUG_PROGRESS", "0") == "1"
```

Log in worker:
- Timestamps for each stage (count/fetch/translate/commit)
- Provider call latencies
- Progress emit frequency

---

## Summary

| Issue | Priority | Fix Complexity |
|-------|----------|----------------|
| Worker doesn't pass progress_callback | 🔥 P0 | LOW (10 lines) |
| Missing heartbeat/stage in dialog | ⚠️ P1 | MEDIUM (50 lines) |
| Two paths use different UIs | 📝 P2 | HIGH (100+ lines) |

**Recommendation**: Start with P0 (progress_callback), then P1 (heartbeat), defer P2 (unify paths) if time-constrained.
