# Chunked Term Extraction Plan

Date: 2026-03-09

## Problem

`extract_terms_for_project()` was previously a single large collect/finalize pass:

- re-parse all processed `document_sentence` rows in one logical run
- keep large in-memory counters before final writes
- restart from scratch after cancellation/failure

This was acceptable for small projects, but weak for large corpora and long-running
reference workflows.

## Implemented in this iteration

### 1. Staged run state

New schema:

- `term_extract_run`
- `term_extract_accumulator`

Purpose:

- persist run parameters and progress by document batches
- store staged aggregate counters before final write
- allow retry/resume after interrupted collect phase

### 2. Chunked collect phase

Overwrite mode now runs in two stages:

1. collect processed docs in deterministic `doc_id ASC` batches
2. upsert aggregate counters into `term_extract_accumulator`

Batch properties:

- bounded by `batch_size`
- committed after every batch
- resumable via `last_doc_id`
- safe to cancel before finalization

### 3. Atomic finalization

After staged collect completes:

- existing term tables are cleared
- staged counters are stored into `ngram` / `ngram_project_stat`
- clusters are built
- staged rows are deleted

Finalization is one transaction, so visible term tables are not partially overwritten
if this phase fails.

## Runtime contract

Current public API:

- `TermExtractionService.extract_terms_for_project(...)`

Current behavior:

- `overwrite=True` -> chunked staged pipeline
- `overwrite=False` -> legacy path retained for compatibility

Resume contract:

- latest matching staged run is resumed automatically
- if processed-doc count changed since the staged run was created, resume is refused
  and a fresh run is created instead

## Current UI behavior

- Terms extraction remains worker-threaded
- status text now receives stage messages from the chunked service
- Terms confirmation dialog explicitly states that extraction is resumable
- if a staged run is cancelled, re-running extraction resumes it

## Bench evidence on approved DB

Target DB:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`

Artifacts:

- `build\logs\pipeline_bench_report_20260309_021420.md`
- `build\logs\pipeline_bench_report_20260309_030439.md`

Observed `extract_terms` stage timings on the same DB/slice:

- pre-chunked staging patch, `doc_limit=30`: `13.960 s`
- post-chunked staging patch, `doc_limit=30`: `15.431 s`

Interpretation:

- small-slice runtime regressed slightly because run-state staging adds overhead
- the trade-off is intentional: resumability and bounded collect memory for large projects

## Remaining follow-ups

### Follow-up A: richer extraction progress UI

- add cancel/resume controls in Terms UI
- show doc progress and finalization stage explicitly
- optional reuse of premium batch progress dialog with extraction-specific labels

### Follow-up B: bigger-slice benchmark refresh

- rerun `extract_terms` on a larger bounded slice after this patch
- record stage time separately from sandbox DB clone/bootstrap overhead

### Follow-up C: deeper architecture tier if needed

If reference-scale runs are still too long:

- compute term candidates during NLP processing instead of re-parsing sentences later
- or persist token/POS sequence data needed for deterministic term extraction
- or materialize per-run / per-project helper tables for direct finalize paths

## Files touched in this wave

- `app/infra/migrations/036_term_extract_chunked.sql`
- `app/infra/sa_models.py`
- `app/domain/dto.py`
- `app/services/term_extraction_service.py`
- `app/ui/workers.py`
- `app/ui/terms_view.py`
- `tests/test_term_extraction_service_large_project.py`
