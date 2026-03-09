# NLP Processing Checkpoint Plan

Date: 2026-03-09

## Purpose

This document saves the current implementation plan for bringing `process with NLP`
to the same engineering maturity level as staged `extract terms`, without losing
the confirmed repo context discovered during the Task 30 follow-up work.

## Confirmed entry points

- Regular-project UI path:
  - `app/ui/documents_view.py`
  - `app/ui/workers.py::ProcessWorker`
  - `app/services/process_service.py::process_document()`
- Reference-scale CLI path:
  - `scripts/process_reference_corpus.py`
  - `docs/REFERENCE_PROJECT_GUIDE.md`
- Current persistence/crash state:
  - `app/infra/sa_models.py::ProcessorRun`
  - `app/services/db_service.py::recover_from_crash()`

## Saved baseline concept

The initial concept worth preserving for later implementation was:

- add a durable DB-backed run ledger for NLP processing
- emit structured progress state, not only `(current, total, doc_name)`
- support cooperative cancel/pause/resume at deterministic boundaries
- add a dedicated extraction-grade progress dialog for regular-project NLP runs
- add a verify/refresh contract for prepared source identity if a prepared-NLP
  workflow is introduced later

## Corrected after deeper repo review

The deeper audit changes the implementation shape in several important ways.

### 1. Reference corpus must remain CLI-only

Confirmed in `docs/REFERENCE_PROJECT_GUIDE.md` and `app/ui/documents_view.py`:

- UI `Process` / `Re-process` is intentionally blocked for reference corpora
- large reference NLP processing must continue to run via
  `scripts/process_reference_corpus.py`

This means the future premium progress UI applies to regular projects first.
Reference-scale work should reuse the same run-state contract, but not re-enable
multi-hour UI writes.

### 2. First production implementation should not copy the benchmark fixture model

For `extract terms`, a prepared fixture DB is a benchmark/runtime harness tool.
For real NLP processing, the first safe production design should instead:

- process directly against the main DB
- keep write scope bounded to one document or one chunk checkpoint
- persist resumable run state in the main DB

A full copied working DB plus merge-back protocol is only a later optional design
if remote/offline processing becomes a real product requirement.

### 3. Existing legacy processing state is too weak

Current `processor_run` is not enough for staged/cancelable/resumable NLP:

- `status` only supports `running/ok/failed`
- no `last_doc_id`
- no `docs_total/docs_failed/chunks_total/chunks_completed`
- no `params_hash`
- no resume gating

Also, `DBService.recover_from_crash()` currently only knows the legacy
`running -> failed` recovery path.

### 4. UI parity should follow the extract-terms contract

The desired target is not a generic spinner. It should match the terms flow:

- stage label
- run id
- doc progress
- chunk progress
- last processed doc id
- elapsed / last activity
- bounded activity log
- pause/resume/cancel buttons
- cooperative close behavior

## Recommended patch series

### PATCH-NLP-01: durable processor run state

Files:

- `app/infra/migrations/...`
- `app/infra/sa_models.py`
- `app/services/process_service.py`
- `app/domain/dto.py`

Requirements:

- add staged/resumable run state for NLP processing
- include:
  - `status`
  - `stage`
  - `last_doc_id`
  - `docs_total`
  - `docs_processed`
  - `docs_failed`
  - `chunks_total`
  - `chunks_completed`
  - `params_hash`
  - `error_message`

### PATCH-NLP-02: structured service callbacks

Files:

- `app/services/process_service.py`
- `scripts/process_reference_corpus.py`

Requirements:

- add `progress_callback` and `state_callback`
- preserve deterministic `doc_id ASC` ordering
- expose cooperative `cancel_check` / `pause_check`
- keep safe checkpoint boundaries at end-of-document or end-of-chunk only

### PATCH-NLP-03: regular-project progress UI

Files:

- `app/ui/workers.py`
- `app/ui/documents_view.py`
- `app/ui/dialogs/nlp_process_progress_dialog.py`

Requirements:

- add worker state signal
- add `pause/resume/cancel`
- mirror the staged extraction progress dialog contract
- keep all UI mutations on the main thread

### PATCH-NLP-04: CLI resume and verify contract

Files:

- `scripts/process_reference_corpus.py`
- docs

Requirements:

- add `--resume-run-id` or equivalent resume selection
- add `--verify-only` / contract-check mode
- refuse resume when `params_hash` or source identity changed

### PATCH-NLP-05: crash recovery and compatibility

Files:

- `app/services/db_service.py`
- `app/infra/sa_models.py`
- tests

Requirements:

- update crash recovery for the new run-state model
- keep legacy `processor_run` migration path explicit
- ensure cancelled/staged runs are not incorrectly marked as hard failures

### PATCH-NLP-06: optional future staging/offline concept

Only if product requirements later demand detached/offline NLP processing:

- introduce prepared manifest / staging DB contract
- define merge-back protocol explicitly
- keep this out of the first implementation wave

## Non-negotiable invariants

- reference corpora remain CLI-only for real NLP processing
- regular-project UI may get a premium progress dialog, but not at the cost of
  long write transactions
- resume must be deterministic and gated by run parameters
- cancel must leave the DB consistent and resumable
- no force-termination of NLP workers

## Related follow-up for extract terms

When the NLP plan is implemented, the next convergence step for term extraction is:

- align run-state vocabulary and progress dialog semantics between NLP and terms
- then evaluate whether token/POS snapshots from NLP can replace sentence re-parse
  inside `TermExtractionService`
