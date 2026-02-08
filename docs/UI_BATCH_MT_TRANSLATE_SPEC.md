# UI Batch MT Translate - Specification

**Feature:** Batch MT translation for Dictionary, Terms, and Translation Management tabs
**Version:** 1.0
**Date:** 2026-02-08
**Status:** DRAFT (PATCH-UI-BATCH-T00)

---

## 1. Feature Overview

### 1.1 User Story

As a user, I want to translate multiple selected rows in Dictionary/Terms/Translation Management tables via MT providers, so that I can quickly fill or update translations in bulk without manual entry.

### 1.2 Scope

**In Scope:**
- Multi-select support (Ctrl/Shift selection, non-contiguous)
- Provider selection (chain or force specific provider)
- Write mode selection (fill empty, overwrite, skip non-empty)
- Background execution (no UI freeze)
- Progress dialog with cancel support
- Per-row error handling (continue on failure)
- Structured logging (trace_id, provider_id, cache_hit, latency_ms)
- Integration into all 3 tabs: Dictionary, Terms, Translation Management

**Out of Scope:**
- Auto-translation on import (separate feature)
- Bulk language pair changes (only translates existing pairs)
- Translation history viewer in batch dialog
- Undo/redo support (manual revert only)

---

## 2. Current State Audit

### 2.1 Tab Mapping: Dictionary

| Property | Value |
|----------|-------|
| **UI File** | `app/ui/dictionary_view.py` |
| **Model Class** | `LemmaTableModel` (app/ui/models_qt.py:62-190) |
| **Data Source** | `LemmaStats` DTO (`lemma_text`, `translation`, `status`) |
| **Translation Column** | Column 4 (editable) |
| **DB Table** | `tm_entry` |
| **DB Fields** | `kind="lemma"`, `src_text=lemma_text`, `translation`, `status`, `origin` |
| **Write Method** | `on_translation_edited()` (dictionary_view.py:263-342) |
| **Write Logic** | Creates/updates `TMEntry` with:<br>- `kind="lemma"`<br>- `src_lang="he"`, `tgt_lang="ru"` (HARDCODED)<br>- `status="approved"`, `origin="user_edit"` |
| **Multi-Select** | ExtendedSelection ENABLED |
| **Context Menu** | "Why?" action exists |
| **Source Text Field** | `lemma.lemma_text` (Hebrew lemma) |

**Constraints:**
- Language pair HARDCODED to he→ru
- Always sets status="approved" for user edits
- Uses project_id context

### 2.2 Tab Mapping: Terms

| Property | Value |
|----------|-------|
| **UI File** | `app/ui/terms_view.py` |
| **Model Class** | `TermClusterTableModel` (app/ui/models_qt.py:192-337) |
| **Data Source** | `ClusterStats` DTO (`representative_he`, `translation`, `translation_status`) |
| **Translation Column** | Column 11 (editable) |
| **DB Table** | `tm_entry` |
| **DB Fields** | `kind="term_cluster"`, `src_text=representative_he`, `src_norm`, `translation`, `status`, `origin` |
| **Write Method** | `on_translation_edited()` (terms_view.py:405-485) |
| **Write Logic** | Creates/updates `TMEntry` with:<br>- `kind="term_cluster"`<br>- `src_lang="he"`, `tgt_lang="ru"` (HARDCODED)<br>- `src_norm=normalize_for_tm(representative_he, "term_cluster")`<br>- `status="approved"`, `origin="user_edit"`<br>- `source_ref="terms_view_inline_edit"` |
| **Multi-Select** | ExtendedSelection ENABLED (line 129) |
| **Context Menu** | "Why?" action exists |
| **Background Worker** | `TranslationResolveWorker` runs automatically on load |
| **Source Text Field** | `cluster.representative_he` (Hebrew representative term) |

**Constraints:**
- Language pair HARDCODED to he→ru
- Always sets status="approved" for user edits
- Uses normalization for src_norm field
- Uses project_id context

### 2.3 Tab Mapping: Translation Management

| Property | Value |
|----------|-------|
| **UI File** | `app/ui/translation_management_panel.py` |
| **Model Class** | `TranslationManagementTableModel` (app/ui/models_qt.py:343-440) |
| **Data Source** | `TMEntryDTO` (`tm_id`, `src_text`, `translation`, `status`, `origin`, `src_lang`, `tgt_lang`) |
| **Translation Column** | Column 3 (editable) |
| **DB Table** | `tm_entry` (DIRECT access via service) |
| **DB Fields** | All fields pre-exist, only updates `translation` |
| **Write Method** | `on_translation_edited()` (translation_management_panel.py:492-537) |
| **Write Logic** | Uses `TranslationAdminService.update_translation()`:<br>- Updates `translation` field ONLY<br>- Preserves existing `status`, `origin`, `kind`<br>- Creates history entry automatically |
| **Multi-Select** | NOT SET (defaults to SingleSelection) - **NEEDS FIX** |
| **Bulk Actions** | Approve, Reject, Deprecate buttons exist (for status, not translation) |
| **Background Worker** | `TMSearchWorker` for search/filter |
| **Source Text Field** | `entry.src_text` (any language, stored in DB) |
| **Language Pairs** | Mixed (he→ru, en→he, etc., stored in DB) |

**Constraints:**
- Language pairs vary by entry (not hardcoded)
- Preserves existing status (doesn't change to "approved" like other tabs)
- No project_id filter by default (global TM view)
- Uses TranslationAdminService (more sophisticated than direct ORM)

### 2.4 Summary Table

| Feature | Dictionary | Terms | Translation Mgmt |
|---------|-----------|-------|------------------|
| Translation Column | 4 | 11 | 3 |
| Multi-Select | ✅ ExtendedSelection | ✅ ExtendedSelection | ❌ SingleSelection (FIX NEEDED) |
| Source Language | he (hardcoded) | he (hardcoded) | varies (from DB) |
| Target Language | ru (hardcoded) | ru (hardcoded) | varies (from DB) |
| Source Text Field | `lemma_text` | `representative_he` | `src_text` |
| Status on Edit | "approved" | "approved" | preserved |
| Origin on Edit | "user_edit" | "user_edit" | preserved |
| Normalization | No | Yes (src_norm) | Already normalized |
| Service Layer | Direct ORM | Direct ORM | TranslationAdminService |

---

## 3. Design: Unified Batch Operation Contract

### 3.1 Service Interface

**NEW SERVICE:** `app/services/batch_mt_translate_service.py`

```python
class BatchMTTranslateService:
    """Service for batch MT translation of table rows."""

    def execute_batch(
        self,
        session: Session,
        items: List[BatchTranslateItem],
        options: BatchTranslateOptions,
    ) -> BatchTranslateResult:
        """Execute batch translation.

        Args:
            session: DB session (caller manages transaction)
            items: List of items to translate
            options: Execution options

        Returns:
            BatchTranslateResult with summary and per-row results
        """
        pass
```

**Data Classes:**

```python
@dataclass
class BatchTranslateItem:
    """Single item to translate."""
    entity_type: str  # "lemma" | "term_cluster" | "tm_entry"
    entity_id: int | str  # Row identifier (lemma_text | representative_he | tm_id)
    source_text: str
    src_lang: str
    tgt_lang: str
    current_translation: str | None
    project_id: int | None

@dataclass
class BatchTranslateOptions:
    """Options for batch translation."""
    provider_mode: str  # "chain" | "force:<provider_id>"
    write_mode: str  # "FILL_EMPTY" | "OVERWRITE" | "SKIP_NON_EMPTY"
    chunk_size: int = 50
    stop_on_error: bool = False
    dry_run: bool = False

@dataclass
class BatchTranslateRowResult:
    """Result for a single row."""
    entity_id: int | str
    source_text: str
    old_translation: str | None
    new_translation: str | None
    provider_id: str | None
    cache_hit: bool
    latency_ms: int | None
    error_message: str | None
    skipped: bool

@dataclass
class BatchTranslateResult:
    """Overall batch result."""
    total: int
    succeeded: int
    skipped: int
    failed: int
    row_results: List[BatchTranslateRowResult]
    trace_id: str
    elapsed_ms: int
```

### 3.2 Write Strategy by Tab

**Dictionary:**
- Use existing pattern from `on_translation_edited()`
- Create/update `TMEntry` with kind="lemma", status="approved", origin="mt_batch"
- Hardcoded src_lang="he", tgt_lang="ru"

**Terms:**
- Use existing pattern from `on_translation_edited()`
- Create/update `TMEntry` with kind="term_cluster", status="approved", origin="mt_batch"
- Compute src_norm via `normalize_for_tm()`
- Hardcoded src_lang="he", tgt_lang="ru"

**Translation Management:**
- Use `TranslationAdminService.update_translation()`
- Update translation field ONLY, preserve status/origin
- Use actual src_lang/tgt_lang from entry

### 3.3 Origin Value

Add new origin value: **"mt_batch"**

**Rationale:**
- Distinguishes batch MT translations from inline user edits ("user_edit")
- Distinguishes from automatic MT ("mt_auto")
- Allows filtering/auditing of batch operations

**Migration:**
- Check `tm_entry` table origin CHECK constraint
- Add "mt_batch" to allowed values if not present

---

## 4. UI/UX Design

### 4.1 Provider Selection UX

**NOT per-tab selection** - use global settings-driven chain by default.

**Dialog Options:**
- Radio button: "Use provider chain (recommended)" [default]
- Radio button: "Force provider:" + dropdown (local_nllb, deepl, microsoft, libretranslate)
- Link button: "MT Provider Settings..." (opens ProviderSettingsDialog)

**Settings Persistence:**
- Remember last choice via QSettings key: `batch_translate/provider_mode`
- Remember last forced provider via: `batch_translate/last_forced_provider`

### 4.2 Write Mode UX

**Dialog Options (Radio buttons):**
- ( ) **Fill empty only** - only translate rows with empty/null translation [default]
- ( ) **Overwrite existing** - translate ALL selected rows, replace existing translations
- ( ) **Skip non-empty** - skip rows with existing translations (no changes)

**Settings Persistence:**
- Remember last choice via QSettings key: `batch_translate/write_mode`

**Special Case - Translation Management:**
- Add checkbox: "Preserve status for approved entries"
  - If checked: skip rows with status="approved" (even in OVERWRITE mode)
  - Default: CHECKED (premium feature-safe default)

### 4.3 Confirm Dialog

**Title:** "Batch Translate Selected Rows"

**Layout:**
```
Selected rows: N

Provider mode:
  ( ) Use provider chain (recommended)
  ( ) Force provider: [dropdown]

Write mode:
  ( ) Fill empty only
  ( ) Overwrite existing
  ( ) Skip non-empty (no changes)

[✓] Remember my choices

[ Settings... ]  [ Cancel ]  [ Translate ]
```

**Validation:**
- Disable "Translate" button if no rows selected (should never happen, action disabled)
- Show warning if N > 500: "Large selection (N rows). This may take several minutes. Continue?"

### 4.4 Progress Dialog

**Title:** "Translating..."

**Layout:**
```
Translating rows... [Cancel]

[■■■■■■■■■░░░░░░░░░░] 45%

Succeeded: 23
Skipped: 5
Failed: 2
Remaining: 20

Estimated time remaining: 30 seconds
```

**Behavior:**
- Modal dialog (blocks UI, but doesn't freeze app)
- Cancel button: graceful cancel (finish current item, rollback uncommitted chunk)
- Progress bar: determinate (shows actual progress)
- Live counts update as rows complete
- Estimated time based on average latency per row

### 4.5 Result Dialog

**Title:** "Translation Complete"

**Layout:**
```
Translation completed successfully!

Total: 50
Succeeded: 45
Skipped: 3
Failed: 2

[View Details...]  [Close]
```

**"View Details" (optional):**
- Shows scrollable list of failed rows with error messages
- Format: "Row 23 (source text): Error message"

### 4.6 Integration Points

**Dictionary Tab:**
- Add toolbar button: "Translate Selected..." (icon: language + batch)
- Add context menu item: "Translate Selected..." (above "Why?")
- Keyboard shortcut: Ctrl+Shift+M (M for MT)
- Disable if no rows selected

**Terms Tab:**
- Same as Dictionary (toolbar + context menu + shortcut)

**Translation Management Tab:**
- Add button next to "Approve Selected": "Translate Selected..."
- Same keyboard shortcut: Ctrl+Shift+M
- Disable if no rows selected

---

## 5. Background Execution

### 5.1 Worker Pattern

**NEW WORKER:** `app/ui/workers.py` - `BatchTranslateWorker`

```python
class BatchTranslateWorker(QThread):
    """Background worker for batch translation."""

    # Signals
    progress = pyqtSignal(int, int)  # (completed, total)
    row_completed = pyqtSignal(str, bool)  # (entity_id, success)
    finished = pyqtSignal(object)  # BatchTranslateResult
    error = pyqtSignal(str)

    def __init__(
        self,
        items: List[BatchTranslateItem],
        options: BatchTranslateOptions,
        tab_type: str,  # "dictionary" | "terms" | "tm"
    ):
        super().__init__()
        self.items = items
        self.options = options
        self.tab_type = tab_type
        self._cancel_requested = False

    def run(self):
        """Execute batch translation in background."""
        try:
            service = BatchMTTranslateService()
            db_service = DBService.get_instance()

            with db_service.get_session() as session:
                # Process in chunks
                result = service.execute_batch(
                    session, self.items, self.options,
                    progress_callback=self._on_progress,
                    cancel_check=lambda: self._cancel_requested
                )

                self.finished.emit(result)
        except Exception as e:
            logger.exception("Batch translate worker failed")
            self.error.emit(str(e))

    def cancel(self):
        """Request graceful cancel."""
        self._cancel_requested = True
```

### 5.2 Chunked Commits

**Strategy:**
- Process items in chunks (default: 50 rows per chunk)
- Commit after each chunk completes successfully
- If chunk fails: rollback chunk, log error, continue to next chunk (if stop_on_error=False)

**Rationale:**
- Avoids huge transactions (SQLite WAL limits)
- Provides incremental progress (user sees results appear)
- Allows partial success (some chunks commit even if later chunks fail)
- Enables graceful cancel (commit completed chunks, rollback current)

**Implementation:**
```python
for chunk in chunks(items, chunk_size):
    try:
        for item in chunk:
            if cancel_check():
                break
            translate_and_write(item)
            progress_callback(completed, total)

        session.commit()  # Commit chunk

    except Exception as e:
        session.rollback()  # Rollback failed chunk
        if stop_on_error:
            raise
        log_chunk_error(e)
        continue  # Move to next chunk
```

---

## 6. Data Integrity

### 6.1 Constraint Validation

**tm_entry Table Constraints:**
- `origin` CHECK: Must be in allowed list (add "mt_batch")
- `status` CHECK: Must be in allowed list (use "approved" for Dictionary/Terms)
- `kind` CHECK: Must be in allowed list ("lemma", "term_cluster", etc.)

**Validation Before Write:**
- Validate language codes (ISO 639-1 format)
- Validate source text not empty
- Validate translation not empty (for OVERWRITE/FILL_EMPTY modes)

### 6.2 Normalization

**Terms Tab Only:**
- Compute `src_norm` via `normalize_for_tm(src_lang, source_text, kind)`
- Use same normalization as `on_translation_edited()` to avoid duplicates

**Dictionary Tab:**
- No normalization (src_norm = NULL or same as src_text)

### 6.3 Conflict Resolution

**Existing TM Entry:**
- Dictionary/Terms: UPDATE existing entry (by project_id + kind + src_text or src_norm)
- TM panel: UPDATE by tm_id (direct reference)

**Unique Key:**
- Dictionary: (project_id, kind="lemma", src_text)
- Terms: (project_id, kind="term_cluster", src_norm)
- TM: tm_id (primary key)

---

## 7. Observability

### 7.1 Structured Logging

**Per-Batch Log (INFO level):**
```json
{
  "event": "batch_translate_start",
  "trace_id": "uuid4",
  "tab_type": "dictionary",
  "total_items": 50,
  "provider_mode": "chain",
  "write_mode": "FILL_EMPTY",
  "chunk_size": 50
}
```

**Per-Row Log (DEBUG level):**
```json
{
  "event": "batch_translate_row",
  "trace_id": "uuid4",
  "entity_id": "שלום",
  "source_text": "שלום",
  "provider_id": "local_nllb",
  "cache_hit": false,
  "latency_ms": 1250,
  "translation": "привет",
  "status": "success"
}
```

**Per-Batch Summary (INFO level):**
```json
{
  "event": "batch_translate_complete",
  "trace_id": "uuid4",
  "total": 50,
  "succeeded": 45,
  "skipped": 3,
  "failed": 2,
  "elapsed_ms": 65000
}
```

### 7.2 Error Logging

**Per-Row Error (WARNING level):**
```json
{
  "event": "batch_translate_row_error",
  "trace_id": "uuid4",
  "entity_id": "שלום",
  "error_type": "ProviderError",
  "error_message": "Local NLLB model not loaded",
  "provider_id": "local_nllb"
}
```

---

## 8. Settings Keys

**QSettings Hierarchy:**

```ini
[batch_translate]
provider_mode = "chain"  # or "force:local_nllb"
last_forced_provider = "local_nllb"
write_mode = "FILL_EMPTY"
chunk_size = 50
remember_choices = true

[batch_translate_tm]
preserve_approved = true
```

---

## 9. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| **Language pair mismatch** (Dictionary/Terms hardcoded he→ru, but user has other projects) | Users can't batch translate non-he→ru lemmas/terms | Document limitation; future enhancement to detect language from project settings |
| **Large batches freeze UI** | Poor UX, app appears hung | Use QThread worker, show progress dialog, enable cancel |
| **Transaction too large** (1000+ rows) | SQLite WAL limits, memory pressure | Use chunked commits (50 rows per chunk) |
| **Per-row errors break entire batch** | User loses all work if one row fails | Continue on error (default), log per-row errors, show summary |
| **Provider rate limits** | Cloud providers throttle, batch fails | Respect rate limits via circuit breaker, allow user to retry failed rows |
| **Status conflict** (TM panel overwriting "approved" entries) | Users accidentally overwrite curated translations | Add checkbox "Preserve status for approved entries" (default: checked) |
| **Origin constraint violation** | Batch fails if "mt_batch" not in allowed values | Check constraint before deployment, add migration if needed |

---

## 10. Future Enhancements

**Not in Scope for PATCH-UI-BATCH-T01 through T05:**

- Language auto-detect for source text
- Configurable language pairs per tab (remove hardcoded he→ru)
- Batch translate by filter (e.g., "all lemmas with freq > 10")
- Resume partial batches (save progress on cancel)
- Undo/redo for batch operations
- Batch translation history viewer
- Export batch results to CSV
- Parallel translation (multiple workers)

---

## 11. Testing Strategy

### 11.1 Unit Tests

**NEW FILE:** `tests/test_ui_batch_mt_translate_service.py`

- Test service with MockProvider (deterministic output)
- Test write_mode behaviors (FILL_EMPTY, OVERWRITE, SKIP_NON_EMPTY)
- Test per-row error handling (continue vs stop_on_error)
- Test chunk commits (verify partial success)
- Test constraint validation (empty source, invalid language codes)

### 11.2 UI Tests (Headless)

**NEW FILE:** `tests/test_ui_batch_translate_dialogs.py`

- Test dialog creation (confirm dialog, progress dialog)
- Test selection extraction logic (multi-select rows)
- Test settings persistence (QSettings keys)

### 11.3 Integration Tests

**Manual (DoD Evidence):**
- Scenario 1: Dictionary - select 10 lemmas, FILL_EMPTY, chain provider
- Scenario 2: Terms - select 5 terms (non-contiguous), OVERWRITE, force local_nllb
- Scenario 3: TM - select 20 entries, SKIP_NON_EMPTY
- Scenario 4: Cancel mid-batch (verify partial commit, no corruption)
- Scenario 5: Providers disabled (verify actionable error)
- Scenario 6: Large batch (500+ rows) with progress reporting

---

**END OF SPECIFICATION**

---

**Next Steps (Implementation):**
1. PATCH-UI-BATCH-T01: Implement `BatchMTTranslateService` + `BatchTranslateWorker`
2. PATCH-UI-BATCH-T02: UI integration for Dictionary tab
3. PATCH-UI-BATCH-T03: UI integration for Terms tab
4. PATCH-UI-BATCH-T04: UI integration for Translation Management tab (+ ExtendedSelection fix)
5. PATCH-UI-BATCH-T05: Hardening + DoD evidence

**Approval Required:** User must review this spec before proceeding to PATCH-UI-BATCH-T01.
