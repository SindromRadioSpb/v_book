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
| Process button | Disabled · tooltip points to `python scripts/process_reference_corpus.py --project-id <id>` |
| Re-process button | Disabled · tooltip points to `python scripts/process_reference_corpus.py --project-id <id> --reprocess-all --dry-run` |
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

### Re-process all currently processed docs

```powershell
python scripts/process_reference_corpus.py `
    --project-id 1 `
    --db-path hdle_premium.db `
    --reprocess-all `
    --dry-run
```

Operator note:

- processing / reprocess modes now skip snapshot-coverage preamble work unless
  a snapshot-specific mode is requested
- on the approved hewiki dev/test DB, a bounded `--reprocess-all --dry-run --max-docs 20`
  planning pass dropped from multi-minute startup to low-seconds wall time
- heavy reprocess writes now share the same safety gate as other heavy
  reference-corpus write workflows:
  - use `--backup-db-path <healthy-backup>` before a real write run
  - use `--preflight-only` to validate the package without writing
  - protected baseline/main DB targets stay blocked unless
    `--allow-protected-db-heavy-write` is passed explicitly
- the governance dialog now exposes both a rebuild dry-run CLI and a rebuild
  preflight CLI template; it still does not expose a one-click write command
- persisted per-document snapshot stats now back the normal
  readiness/governance snapshot summary path
- operators now also have explicit companion commands for those stats:
  - `--verify-snapshot-stats` to detect drift without writing
  - `--rebuild-snapshot-stats` to refresh stats under the existing backup /
    preflight / protected-target contract

### Preflight a reference rebuild package without writing

```powershell
python scripts/process_reference_corpus.py `
    --project-id 1 `
    --db-path hdle_premium.db `
    --reprocess-all `
    --backup-db-path path\\to\\healthy_backup.db `
    --preflight-only
```

### Verify a reprocess resume contract without writing

```powershell
python scripts/process_reference_corpus.py `
    --project-id 1 `
    --db-path hdle_premium.db `
    --reprocess-all `
    --resume-run-id 387620 `
    --verify-only
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

### Audit sentence snapshot coverage without writing

```powershell
python scripts/process_reference_corpus.py `
    --project-id 1 `
    --db-path hdle_premium.db `
    --backfill-snapshots `
    --coverage-only
```

### Verify persisted snapshot stats without writing

```powershell
python scripts/process_reference_corpus.py `
    --project-id 1 `
    --db-path hdle_premium.db `
    --verify-snapshot-stats `
    --max-docs 5000
```

### Preflight a persisted snapshot-stats rebuild package without writing

```powershell
python scripts/process_reference_corpus.py `
    --project-id 1 `
    --db-path hdle_premium.db `
    --rebuild-snapshot-stats `
    --backup-db-path path\\to\\healthy_backup.db `
    --preflight-only `
    --max-docs 5000
```

### Backfill sentence snapshots for already processed docs

```powershell
python scripts/process_reference_corpus.py `
    --project-id 1 `
    --db-path hdle_premium.db `
    --backfill-snapshots `
    --chunk-size 5000 `
    --merge-batch-size 1000 `
    --segment-quick-check-timeout 0.5
```

### Run a bounded late-scale backfill probe on a disposable sandbox

```powershell
python scripts/process_reference_corpus.py `
    --project-id 1 `
    --db-path build\bench\hewiki_snapshot_diag.db `
    --backfill-snapshots `
    --doc-offset 60000 `
    --max-docs 60000 `
    --chunk-size 5000 `
    --probe-out build\logs\nlp_root_cause\snapshot_probe.jsonl `
    --probe-every-chunks 1
```

### Verify a snapshot-backfill resume contract without writing

```powershell
python scripts/process_reference_corpus.py `
    --project-id 1 `
    --db-path hdle_premium.db `
    --backfill-snapshots `
    --resume-run-id 387620 `
    --verify-only
```

### How it differs from the UI worker

| Aspect | UI ProcessWorker | CLI process_reference_corpus.py |
|--------|-----------------|--------------------------------|
| Session scope | One session per document | One session per document |
| Run state | Regular-project UI now uses the same DB-backed batch `processor_run` state, but the controls stay blocked for reference corpora | DB-backed batch `processor_run` state with stage/chunk/doc counters, deterministic `--resume-latest`, explicit `--resume-run-id`, and `--verify-only` preflight for processing, `--reprocess-all`, and snapshot-backfill runs |
| Cancellation | Regular-project UI now has pause/resume/cancel at document checkpoints, but reference corpora must still use the CLI path | Cooperative resume-at-checkpoint model; interrupted work can be resumed only when the stored contract still matches and the persisted run is in `paused`, `cancelled`, or `failed` state |
| Coverage audit | Not exposed for reference corpora | `--backfill-snapshots --coverage-only` gives a read-only snapshot coverage report before any backfill write |
| Concurrent use of app | Reasonable for small regular-project selections only | Preferred for long reference-scale runs; app can remain open |
| Suitable for 387 K docs | No | Yes |

### Snapshot backfill notes

- This mode is intended for legacy processed corpora that predate migration
  `038_sentence_nlp_snapshot`.
- The run contract stays deterministic by scanning the full processed-doc slice
  and only creating missing snapshot rows per document.
- Backfill is designed to enrich `sentence_nlp_snapshot` only; it does not
  re-run full NLP processing and does not rewrite lemma or term data.
- The post-run integrity verification now defaults to
  `--integrity-checkpoint-mode none`.
  Aggressive modes such as `truncate` are kept only as explicit diagnostic
  overrides while the late-scale durability investigation remains open.
- The storage path is now staged for legacy backfill:
  - rows are staged into `sentence_nlp_snapshot_stage`
  - then merged into `sentence_nlp_snapshot` in bounded batches
  - a bounded physical verification runs after every super-chunk
- Durability knobs for heavy runs:
  - `--merge-batch-size`
  - `--segment-quick-check-timeout`
- For operator decision-making, measure coverage and backfill on the large
  legacy reference project, not on tiny regular-project probes:
  - small regular projects can be used as smoke checks
  - the real convergence decision should be based on the reference-scale
    project, e.g. `ID=1` on the approved hewiki DB
- Operational caution from the `2026-03-10` hewiki probe:
  - a full-scale snapshot backfill on `ID=1` in the approved dev/test DB
    completed in about `105` minutes but was followed by
    `database disk image is malformed`
  - disposable sandbox controls later showed the same corruption on
    `120k` docs with `truncate`, while a fresh `120k` control run with
    `--integrity-checkpoint-mode none` completed successfully
  - however, a later full-scale rerun on the restored approved dev/test DB
    still corrupted `sentence_nlp_snapshot` even with the safer default
    `--integrity-checkpoint-mode none`
  - a later storage redesign wave then validated a bounded real run on the
    restored approved dev/test DB:
    - `ID=1`
    - `max_docs=10000`
    - `chunk_size=5000`
    - `merge_batch_size=1000`
    - `segment_quick_check_timeout=0.5`
    - result: `ok/completed`, `stage_rows_remaining=0`, post-run `db_open` ok
  - the next real-db staged tier then extended that same approved dev/test DB
    from `10k` to `50k` cumulative covered docs:
    - extension run: `doc_offset=10000`, `max_docs=40000`
    - result: `ok/completed`, `stage_rows_remaining=0`, post-run `db_open` ok
    - cumulative coverage after the run:
      - `49999` fully covered docs
      - `20.1938%` sentence coverage
      - `12.8983%` doc coverage
  - the next real-db staged tier then extended that same approved dev/test DB
    from `50k` to `120k` cumulative covered docs:
    - extension run: `doc_offset=50000`, `max_docs=70000`
    - result: `ok/completed`, `stage_rows_remaining=0`, post-run `db_open` ok
    - runtime: `3495.7 s`
    - cumulative coverage after the run:
      - `119999` fully covered docs
      - `38.1812%` sentence coverage
      - `30.9564%` doc coverage
  - until the integrity issue is fixed, use `--coverage-only` on large
    reference projects and do not run the full backfill on the main install DB
  - the CLI now includes a post-run physical integrity gate before a snapshot
    backfill can be marked successful, but this does not repair the already
    damaged `hewiki_gpu_processing test.db`
  - use `scripts/repair_db_corruption.py --diagnose-only --verbose` to confirm
    the current state of a suspect DB before attempting any further heavy
    backfill run
  - the approved dev/test DB has since been restored from a safe pre-corruption
    backup and is usable again, but the full `ID=1` backfill must still stay
    blocked until the durability bug itself is fixed
  - after the later staged redesign evidence wave reached `120k` cumulative
    docs, the track moved into a controlled hold-state:
    - bounded validation accepted
    - full-volume validation deferred
    - main install DB rollout blocked
    - freshness/version work blocked
  - the operator decision gate and future heavy-run package now live in:
    - `docs/NLP_SNAPSHOT_BACKFILL_DECISION_GATE.md`
  - heavy snapshot-backfill writes now require a successful preflight with an
    explicit `--backup-db-path`
  - heavy `--reprocess-all` writes now use the same backup/preflight gate
  - heavy snapshot-backfill writes against the protected baseline/main DB stay
    blocked unless the operator crosses the explicit decision gate with
    `--allow-protected-db-heavy-write`
  - heavy `--reprocess-all` writes against the protected baseline/main DB now
    use the same explicit override gate
  - the UI now surfaces read-only readiness/reporting:
    - Documents shows snapshot coverage + latest backfill summary
    - Terms shows the last extraction source mix
  - these UI surfaces are observational only:
    - they do not start heavy backfill
    - they do not imply production approval
    - for explicit coverage checks use `Copy Coverage CLI` or run
      `--backfill-snapshots --coverage-only` manually
    - `Bounded validated` now reflects bounded validation evidence, not merely
      the existence of any snapshot-backfill run

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
