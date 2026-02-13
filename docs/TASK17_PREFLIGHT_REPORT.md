# Task 17: Fix Empty Recent Activity - Pre-Flight Report

## Executive Summary

**Problem**: Recent activity panel in `BatchProgressDialogV3` is **empty/static** during translation, despite UI elements and signal connections existing.

**Root Cause**: Worker emits `row_translated` events **ONLY after batch completes** (every 200 items, ~1-2 min delay) AND **only for first 100 items** AND **doesn't emit SKIP events**.

---

## Pre-flight Analysis: Chain Breakage Points

### ✅ UI Elements Exist (BatchProgressDialogV3)

**File**: `app/ui/dialogs/batch_progress_dialog_v3.py:52-53, 168-179, 256-289`

```python
# Line 53: Ring buffer
self.recent_items = deque(maxlen=5)

# Lines 168-179: UI widget
self.activity_log = QTextEdit()
self.activity_log.setReadOnly(True)
self.activity_log.setMaximumHeight(100)

# Lines 256-289: Method to add items
def add_recent_item(self, entity_id: str, translation: str, success: bool):
    """Add item to recent activity log."""
    if success:
        icon = "[+]"
        color = "#4caf50"
        text = f"{entity_id} -> {translation}"
    else:
        icon = "[x]"
        color = "#f44336"
        text = f"{entity_id}: {translation}"

    self.recent_items.append((icon, text, color))
    self.activity_log.setHtml("<br>".join(html_lines))
```

**Status**: ✅ UI components correctly implemented

---

### ✅ Signal Defined in Worker

**File**: `app/ui/workers.py:1593`

```python
row_translated = pyqtSignal(str, str, bool)  # (entity_id, translation, success)
```

**Status**: ✅ Signal exists with correct signature

---

### ✅ Signal Connected in Views

**Files**: `app/ui/dictionary_view.py:896`, `app/ui/terms_view.py:1114`

```python
worker.row_translated.connect(progress_dialog.add_recent_item)  # Direct connection
```

**Status**: ✅ Signal properly connected

---

### 🔥 PROBLEM #1: Events Emitted ONLY After Batch Completes (Not Real-Time)

**File**: `app/ui/workers.py:1864-1876`

```python
# AFTER execute_batch() completes (200 items processed!)
chunk_result = batch_service.execute_batch(...)

# Only NOW emit events for this entire batch
for row_result in chunk_result.row_results:
    success = (not row_result.skipped and not row_result.error_message)
    self.row_completed.emit(row_result.entity_id, success)

    # Emit row_translated for activity log
    if len(all_row_results) <= 100:  # ⚠️ LIMIT!
        if success and row_result.new_translation:
            translation = row_result.new_translation[:50]
            self.row_translated.emit(row_result.entity_id, translation, True)
        elif row_result.error_message:
            self.row_translated.emit(row_result.entity_id, row_result.error_message[:50], False)
```

**Problem**:
- Events emitted **after entire batch (200 items) completes**
- With 632 items:
  - Batch 1 (200 items): ~1-2 min → THEN emit 200 events at once
  - Batch 2 (200 items): ~1-2 min → THEN emit 200 events at once
  - Batch 3 (200 items): ~1-2 min → THEN emit 200 events at once
  - Batch 4 (32 items): ~10-20 sec → THEN emit 32 events
- **UI sees burst of 200 events every 1-2 minutes**, not real-time

---

### 🔥 PROBLEM #2: Only First 100 Items Get Events

**File**: `app/ui/workers.py:1870`

```python
if len(all_row_results) <= 100:  # Activity log for first 100 items
    if success and row_result.new_translation:
        self.row_translated.emit(...)
    elif row_result.error_message:
        self.row_translated.emit(...)
```

**Problem**:
- After first 100 items, **NO MORE events emitted**
- With 632 items: activity stops after first 100
- User sees activity for ~first minute, then **silence** for remaining 4-5 minutes

---

### 🔥 PROBLEM #3: SKIP Events Not Emitted

**File**: `app/ui/workers.py:1871-1875`

```python
if success and row_result.new_translation:
    self.row_translated.emit(row_result.entity_id, translation, True)
elif row_result.error_message:
    self.row_translated.emit(row_result.entity_id, error_message, False)
# ⚠️ NO ELSE for row_result.skipped!
```

**Problem**:
- `row_result.skipped` items are **never emitted**
- User doesn't see `[SKIP] already translated` events
- Activity log incomplete

---

### ✅ BatchMTTranslateService Provides Per-Item Data

**File**: `app/services/batch_mt_translate_service.py:47-57`

```python
@dataclass
class BatchTranslateRowResult:
    entity_id: str
    source_text: str
    old_translation: Optional[str]
    new_translation: Optional[str]
    provider_id: Optional[str]
    cache_hit: bool
    latency_ms: Optional[int]
    error_message: Optional[str]
    skipped: bool  # ✅ Flag exists!
```

**Status**: ✅ Service provides all necessary data (success/skip/fail)

---

## Root Cause Summary

| Issue | Location | Impact |
|-------|----------|--------|
| 🔥 **Events emitted only after batch completes** | `workers.py:1864` | Activity updates every 1-2 min (burst), not real-time |
| 🔥 **100-item limit** | `workers.py:1870` | Activity stops after first 100 items |
| 🔥 **SKIP events not emitted** | `workers.py:1871-1875` | Incomplete activity log (missing skipped items) |

---

## Solution Design

### PATCH-01: Emit Events During Batch Execution (Real-Time)

**Strategy**: Use existing `progress_callback` mechanism from Task 16.

**Current** (Task 16):
```python
def on_batch_progress(completed_in_batch, total_in_batch):
    global_completed = offset + completed_in_batch
    self.progress.emit(global_completed, total)
    self.stage_updated.emit(...)
```

**Enhancement**: Extract last row result from `chunk_result` and emit immediately:

```python
def on_batch_progress(completed_in_batch, total_in_batch):
    # Existing progress update
    self.progress.emit(...)

    # NEW: Emit activity for last completed item
    if completed_in_batch > 0:
        # Get last result from sub-chunk
        last_idx = completed_in_batch - 1
        if last_idx < len(current_chunk_results):
            row_result = current_chunk_results[last_idx]
            self._emit_activity_event(row_result)
```

**Problem**: `progress_callback` doesn't pass row results, only counts.

**Better Solution**: Add `item_callback` to `BatchMTTranslateService.execute_batch()`.

---

### PATCH-02: Add item_callback to BatchMTTranslateService

**File**: `app/services/batch_mt_translate_service.py`

**Change**: Add optional `item_callback` parameter:

```python
def execute_batch(
    self,
    session: Session,
    items: List[BatchTranslateItem],
    options: BatchTranslateOptions,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    item_callback: Optional[Callable[[BatchTranslateRowResult], None]] = None,  # NEW
) -> BatchTranslateResult:
```

Call `item_callback` after each item processed:

```python
for result in chunk_results:
    if item_callback:
        item_callback(result)  # Real-time per-item notification
```

**Risk**: LOW - optional parameter, doesn't break existing callers.

---

### PATCH-03: Worker Emits All Event Types with Throttling

**File**: `app/ui/workers.py`

**Changes**:

1. Add throttling state:
```python
self._last_activity_emit = 0.0
self._activity_throttle_interval = 0.1  # 100ms = max 10 events/sec
```

2. Pass `item_callback` to service:
```python
def _emit_activity_from_row_result(self, row_result):
    """Emit activity event with throttling."""
    now = time.time()

    # Throttle unless FAIL (priority)
    if row_result.error_message:
        # FAIL: emit immediately
        pass
    else:
        # OK/SKIP: throttle
        if now - self._last_activity_emit < self._activity_throttle_interval:
            return  # Skip this event

    self._last_activity_emit = now

    # Determine event type and emit
    if row_result.skipped:
        # SKIP event
        msg = "already translated"
        self.row_translated.emit(row_result.entity_id, msg, False)
    elif row_result.error_message:
        # FAIL event
        error_short = row_result.error_message[:50]
        self.row_translated.emit(row_result.entity_id, error_short, False)
    elif row_result.new_translation:
        # OK event
        translation = row_result.new_translation[:50]
        self.row_translated.emit(row_result.entity_id, translation, True)

chunk_result = batch_service.execute_batch(
    ...
    item_callback=self._emit_activity_from_row_result,  # NEW
)
```

3. Remove old post-batch emission code (lines 1864-1876) - no longer needed.

---

### PATCH-04: Update Dialog to Show All Event Types

**File**: `app/ui/dialogs/batch_progress_dialog_v3.py:256-289`

**Current**:
```python
def add_recent_item(self, entity_id: str, translation: str, success: bool):
    if success:
        icon = "[+]"
        text = f"{entity_id} -> {translation}"
    else:
        icon = "[x]"
        text = f"{entity_id}: {translation}"
```

**Enhancement**: Distinguish SKIP vs FAIL:

```python
def add_recent_item(self, entity_id: str, translation: str, success: bool):
    if success:
        # OK event
        icon = "[+]"
        color = "#4caf50"
        text = f"{entity_id} -> {translation}"
    else:
        # Distinguish SKIP vs FAIL
        if "already" in translation.lower() or "skip" in translation.lower():
            # SKIP event
            icon = "[~]"
            color = "#ff9800"
            text = f"{entity_id} ({translation})"
        else:
            # FAIL event
            icon = "[x]"
            color = "#f44336"
            text = f"{entity_id}: {translation}"
```

---

## Next Steps (Implementation Order)

1. ✅ **Pre-flight complete** - root cause identified
2. **PATCH-01**: Add `item_callback` to `BatchMTTranslateService.execute_batch()`
3. **PATCH-02**: Worker uses `item_callback` with throttling + emit all event types
4. **PATCH-03**: Remove old post-batch emission code
5. **PATCH-04**: Update dialog to distinguish SKIP vs FAIL
6. **PATCH-05**: Add diagnostic logging (`HDLE_DEBUG_PROGRESS=1`)
7. **Test**: Create `test_task17_recent_activity.py`
8. **Manual smoke**: Test on "Физика" project (858 clusters)

---

## References

- **Task file**: `task_17.md`
- **Worker**: `app/ui/workers.py:1583-1890` (TranslateAllFilteredWorker)
- **Dialog**: `app/ui/dialogs/batch_progress_dialog_v3.py:256-289` (add_recent_item)
- **Service**: `app/services/batch_mt_translate_service.py:78-180` (execute_batch)
- **Previous work**: Task 16 (Premium Progress UI with heartbeat)
