# Reference Project — Administrator Guide

**Scope:** HDLE Premium · PERF-SCALE PATCH-A
**Audience:** System administrator / project owner
**Last updated:** 2026-03-09

---

## 1. Purpose

A **Reference Project** is a project whose source documents originate from an external,
pre-processed corpus (e.g. Hebrew Wikipedia, 387 K documents).  It is designated
read-only at the project level so that:

- source documents cannot be accidentally added, deleted, or reprocessed through the UI;
- NLP processing (which takes hours for a corpus of this scale) is routed through
  a dedicated CLI script that uses per-document WAL-safe transactions instead of
  a single long write session;
- the external SQLite database backing the corpus is mounted with OS-level write
  protection (`SQLite URI mode=ro` + `PRAGMA query_only=ON`), providing two
  independent layers of write prevention.

Users can still browse documents, run term extraction, manage translations, and
generate audio for a reference project — only document-mutation operations are blocked.

---

## 2. Architecture

```
mark_reference_project.py (CLI)
    │  writes dict_project.is_reference = 1
    │           dict_project.ref_db_path = <path>
    ▼
main.py  (startup, after crash recovery)
    │  scans dict_project WHERE is_reference = 1
    │  calls DBService.attach_reference(project_id, ref_db_path) for each
    ▼
ReadOnlyDatabaseManager
    ├── SQLite URI: file:<path>?mode=ro   ← OS refuses all writes at file level
    └── PRAGMA query_only = ON            ← SQLAlchemy session refuses all writes

documents_view.py  (UI layer, on project open)
    ├── reads project.is_reference → sets is_reference_corpus = True
    ├── _configure_reference_corpus_ui()  ← disables Add / Delete / Process buttons
    ├── on_add_files / on_add_folder      ← hard guard + user dialog
    └── on_process / on_reprocess         ← hard guard + CLI instructions dialog
```

Two completely independent protection layers ensure that even a code path that
bypasses one layer cannot write to the reference corpus.

---

## 3. Prerequisites

| Requirement | Details |
|-------------|---------|
| HDLE Premium | PERF-SCALE PATCH-A or later (schema version ≥ 28) |
| Python venv activated | `.\.venv\Scripts\Activate.ps1` |
| Main database | `hdle_premium.db` (or path set via `--db-path` / `HDLE_DB_PATH`) |
| External reference DB | SQLite `.db` file produced by the GPU processing pipeline (optional — absence is non-fatal; UI protection still activates) |
| Application closed | The CLI script modifies the DB directly; run it while the app is closed or before first launch |

---

## 4. Step-by-Step Procedure

### 4.1  Find the project ID

```powershell
cd J:\Project_Vibe\V_book
.\.venv\Scripts\Activate.ps1

python scripts/mark_reference_project.py `
    --db-path hdle_premium.db `
    --list
```

Example output:

```
    ID  is_ref  name                                      ref_db_path
------------------------------------------------------------------------------------------
     1       -  Hebrew Wikipedia (hewiki)
     2       -  My Study Project
     3       -  Technical Texts

3 project(s), 0 reference project(s).
```

Note the `ID` of the project you want to designate as a reference project.

---

### 4.2  Mark the project as reference

```powershell
python scripts/mark_reference_project.py `
    --db-path hdle_premium.db `
    --project-id 1 `
    --ref-db-path "J:\Project_Vibe\ref_corpora\hewiki_gpu_processing.db"
```

**Parameters:**

| Parameter | Description |
|-----------|-------------|
| `--db-path` | Path to the main HDLE Premium SQLite database |
| `--project-id` | Numeric project ID from Step 4.1 |
| `--ref-db-path` | Absolute path to the external read-only reference database file |

Expected output:

```
[OK] Project 1 'Hebrew Wikipedia (hewiki)' marked as reference.
     ref_db_path = J:\Project_Vibe\ref_corpora\hewiki_gpu_processing.db
```

> **Note:** If the `ref-db-path` file does not yet exist, the script prints a WARNING
> but still marks the project. The UI protection layer will activate on next launch;
> the physical RO mount will be skipped until the file is present.

---

### 4.3  Restart the application

The reference flag is read once at startup.  Close and reopen HDLE Premium.

On startup the application automatically:

1. Scans `dict_project` for all rows with `is_reference = 1`.
2. Calls `DBService.attach_reference(project_id, ref_db_path)` for each.
3. Opens a read-only SQLite connection for each reference DB found on disk.

Startup log (check `hdle_premium.log` or the console):

```
INFO  Reference DB attached: project 1 → J:\...\hewiki_gpu_processing.db
```

If the file is missing:

```
WARNING  Reference DB file not found for project 1 (path: ...); project will
         remain read-only in UI but physical RO mount skipped.
```

---

### 4.4  Verify in the UI

Open the project in the application.  Navigate to the **Documents** tab.

Expected state:

| UI element | Expected |
|------------|----------|
| Blue information banner | Visible: "This is a Reference Corpus (read-only documents)" |
| Add Files button | Disabled · tooltip: "Cannot add documents to reference corpus (read-only)" |
| Add Folder button | Disabled · tooltip: same |
| Delete button | Disabled · tooltip: "Cannot delete documents from reference corpus (read-only)" |
| Process button | Disabled · tooltip: "NLP processing of reference corpus is CLI-only. Use: `python scripts/process_reference_corpus.py`" |
| Re-process button | Disabled · same tooltip |
| Document list / search / filters | Fully functional |
| Terms / Translation / Audio tabs | Fully functional (read-write for overlays) |

---

### 4.5  Remove the reference designation (rollback)

```powershell
python scripts/mark_reference_project.py `
    --db-path hdle_premium.db `
    --project-id 1 `
    --unmark
```

Expected output:

```
[OK] Project 1 'Hebrew Wikipedia (hewiki)' unmarked (back to normal writable project).
```

Restart the application.  All document mutation operations become available again.

---

## 5. NLP Processing of a Reference Corpus

Large reference corpora must be processed through the dedicated CLI script.
The UI blocks `Process` and `Re-process` for reference projects to prevent
accidental multi-hour write sessions that would hold a WAL lock for the entire duration.

### Basic usage

```powershell
python scripts/process_reference_corpus.py `
    --project-id 1 `
    --db-path hdle_premium.db `
    --no-mock
```

### Dry run (no DB writes)

```powershell
python scripts/process_reference_corpus.py `
    --project-id 1 `
    --db-path hdle_premium.db `
    --dry-run
```

### Smoke test (first 100 documents only)

```powershell
python scripts/process_reference_corpus.py `
    --project-id 1 `
    --db-path hdle_premium.db `
    --no-mock `
    --max-docs 100
```

### Resume the latest matching interrupted batch

```powershell
python scripts/process_reference_corpus.py `
    --project-id 1 `
    --db-path hdle_premium.db `
    --resume-latest
```

### Resume an explicit interrupted batch run

```powershell
python scripts/process_reference_corpus.py `
    --project-id 1 `
    --db-path hdle_premium.db `
    --resume-run-id 387620
```

### Verify a resume contract without writing

```powershell
python scripts/process_reference_corpus.py `
    --project-id 1 `
    --db-path hdle_premium.db `
    --resume-run-id 387620 `
    --verify-only
```

### How it differs from the UI worker

| Aspect | UI ProcessWorker | CLI process_reference_corpus.py |
|--------|-----------------|--------------------------------|
| Session scope | One session per document | One session per document |
| Run state | Regular-project UI now uses the same DB-backed batch `processor_run` state, but the controls stay blocked for reference corpora | DB-backed batch `processor_run` state with stage/chunk/doc counters, deterministic `--resume-latest`, explicit `--resume-run-id`, and `--verify-only` preflight |
| Cancellation | Regular-project UI now has pause/resume/cancel at document checkpoints, but reference corpora must still use the CLI path | Cooperative resume-at-checkpoint model; interrupted work can be resumed only when the stored contract still matches and the persisted run is in `paused`, `cancelled`, or `failed` state |
| Concurrent use of app | Reasonable for small regular-project selections only | Preferred for long reference-scale runs; app can remain open |
| Suitable for 387 K docs | No | Yes |

### Inter-chunk sleep

Add `--chunk-sleep 0.1` (seconds) to yield WAL write capacity to other writers
between chunks if the application is running concurrently:

```powershell
python scripts/process_reference_corpus.py `
    --project-id 1 `
    --db-path hdle_premium.db `
    --no-mock `
    --chunk-sleep 0.1
```

---

## 6. Verification Checklist

After completing the procedure, verify each item:

- [ ] `--list` shows `is_ref = YES` for the target project
- [ ] Application starts without errors in the log related to reference DB attach
- [ ] Documents tab shows the blue reference corpus banner
- [ ] Add Files, Add Folder, Delete buttons are disabled
- [ ] Process and Re-process buttons are disabled with correct tooltip
- [ ] Document search and filters work normally
- [ ] Terms, Translation, Audio tabs are accessible and writable
- [ ] Attempting drag-and-drop onto the Documents tab shows the warning dialog
- [ ] `python scripts/process_reference_corpus.py --dry-run` completes with exit code 0

---

## 7. Troubleshooting

### Banner does not appear after restart

**Cause:** `is_reference` flag was not written to the database, or a different DB
file is being used.

**Fix:**
```powershell
# Confirm the flag is set in the DB the app actually uses
python scripts/mark_reference_project.py --db-path hdle_premium.db --list

# Confirm which DB the app loaded (check startup log)
# Look for: "Database initialized" line and the db_path argument used
```

---

### "Reference DB file not found" in startup log

**Cause:** The path stored in `ref_db_path` does not exist on disk.

**Effect:** Non-fatal — UI protection (buttons disabled, banner visible) still
activates.  Only the physical OS-level RO mount is skipped.

**Fix:**
```powershell
# Re-mark with correct path once the file is available
python scripts/mark_reference_project.py `
    --db-path hdle_premium.db `
    --project-id 1 `
    --ref-db-path "J:\correct\path\to\hewiki_gpu_processing.db"
```

---

### Add Files button remains enabled

**Cause:** Project `is_general_corpus` or `is_reference` flags were not read
correctly during `load_corpus()`. This can happen if the project tab was open
before the DB was updated.

**Fix:** Close the project tab and reopen it, or restart the application.

---

### Schema error: "no such column: is_reference"

**Cause:** Migration 028 has not been applied.  This normally runs automatically
on first startup after upgrading.

**Fix:**
```powershell
# Force migration by starting the application once
python -m app.main --db-path hdle_premium.db

# Or apply manually
python -c "
from app.services.db_service import DBService
DBService.initialize('hdle_premium.db')
print('Migrations applied')
"
```

---

### Process script exits with code 2

The CLI script returns exit code 2 when one or more documents fail NLP processing.
Errors are logged per document; successful documents are committed.

```powershell
# Check error details
python scripts/process_reference_corpus.py `
    --project-id 1 --db-path hdle_premium.db --no-mock 2>&1 | Select-String "ERROR"
```

Resume is safe:

- the script still skips already-processed documents on fresh non-resume runs
- `--resume-latest` reuses the latest matching incomplete batch run only if the
  stored run contract still matches the deterministic source slice and NLP
  parameters
- `--resume-run-id` lets the operator resume a specific incomplete run when
  multiple interrupted runs exist
- `--verify-only` performs the same contract validation without writing
- rows still marked `status='running'` are not treated as safe resume targets;
  wait for the active run to finish or recover it first

---

### Process script exits with code 3

The CLI script returns exit code 3 when `--verify-only` or `--resume-run-id`
fails contract validation.

Typical causes:

- the selected run ID does not exist
- the stored source slice no longer matches `--max-docs` / project selection
- NLP engine parameters changed
- the selected run is already complete or still marked `running`

---

## 8. Related files

| File | Description |
|------|-------------|
| `scripts/mark_reference_project.py` | CLI tool to mark / unmark / list reference projects |
| `scripts/process_reference_corpus.py` | WAL-safe CLI NLP processor for reference corpora |
| `app/infra/reference_guard.py` | `ReferenceProjectReadOnlyError` + `assert_not_reference_project()` |
| `app/infra/db.py` | `ReadOnlyDatabaseManager` (SQLite URI mode=ro) |
| `app/services/db_service.py` | `attach_reference()` / `get_ref_session()` / `detach_reference()` |
| `app/ui/documents_view.py` | UI reference detection + `_configure_reference_corpus_ui()` |
| `app/infra/migrations/028_reference_project.sql` | Schema: `is_reference`, `ref_db_path` columns |
| `docs/PERF_SCALE_AUDIT_HEWIKI_2026-03-07.md` | Architecture decision record (Variant A rationale) |
