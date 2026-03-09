# Task 30 Implementation Plan (2026-03-09)

## Scope

This plan is based on the approved Task 30 audit executed against:

- DB path: `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- Verified runtime contract: `python -m app.main --db-path "<path above>"`
- Verified schema version on target DB: `35`

This document records the implementation order for the confirmed findings only.
It is intentionally patch-oriented and conservative.

## Confirmed constraints

- Target app: PyQt6 desktop application with SQLite WAL.
- Heavy reference-scale DB:
  - `source_document`: ~387k rows
  - `document_sentence`: ~13.3M rows
  - `lemma`: ~2.07M rows
  - `lemma_doc_stat`: ~104.1M rows
- Long operations must remain worker-safe and UI-thread safe.
- Changes must preserve WAL-safe transaction behavior and keep diffs minimal.

## Confirmed findings driving implementation

### 1. Translation overlay workers are not fully hardened

- `TranslationResolveWorker` currently opens a write session even though it performs read-only overlay work.
- `TermsView` auto-translation flow does not have Dictionary-style anti-stale sequencing.
- `TranslateTextDialog` still uses forceful thread shutdown (`terminate()`) on cancel/close.

### 2. Instrumentation has drifted from live service paths

- `scripts/query_plan_audit.py` no longer reflects the real document picker service path.
- Some older perf docs are stale compared to current code.

### 3. Large-scale bottleneck is still term extraction aggregation

- `lemma_doc_stat` rollup remains the dominant large-project query risk.
- `collect_queryplan_evidence.py` measured `extract_terms_lemma_rollup` at ~136s on the approved DB.

### 4. Runtime readiness is inconsistent across feature families

- MT health and audio health use different readiness semantics.
- Runtime data/log roots resolve outside the repo workspace.
- Resource registry reports niqqud resources missing while bootstrap health still reports real inference readiness.

## Patch series

### PATCH-01: Worker safety hardening for translation overlays and ad-hoc translation

Status: implemented on 2026-03-09

Files:

- `app/ui/workers.py`
- `app/ui/terms_view.py`
- `app/ui/translate_text_dialog.py`
- `tests/test_terms_worker_lifecycle.py`
- `tests/test_translation_worker_read_session.py`
- `tests/test_translate_text_dialog_lifecycle.py`

Goals:

- Route read-only translation overlay work through `get_read_session()`.
- Add anti-stale sequencing to `TermsView` translation overlays.
- Replace ad-hoc translation `terminate()` flow with cooperative cancel handling.
- Ensure stale/retired worker completions do not mutate visible UI state.

Expected effect:

- Lower write-lock pressure from passive overlay reads.
- Eliminate stale overlay flashes in Terms after rapid paging/filtering.
- Remove unsafe thread termination from ad-hoc translation dialog flow.

Validation:

- Targeted pytest slice for worker lifecycle and dialog lifecycle.
- Existing translation and anti-stale regressions must still pass.
- Result: implemented and validated by
  `tests/test_terms_worker_lifecycle.py`,
  `tests/test_translation_worker_read_session.py`,
  `tests/test_translate_text_dialog_lifecycle.py`.

### PATCH-02: Diagnostic/perf evidence alignment

Status: implemented on 2026-03-09

Files:

- `scripts/query_plan_audit.py`
- `scripts/collect_queryplan_evidence.py`
- `docs/PERF_HARNESS.md`
- `docs/PERFORMANCE_SLO.md`

Goals:

- Align diagnostic scripts with current service-layer queries.
- Record target DB schema version and path in perf artifacts.
- Keep before/after perf comparisons reproducible on the approved DB.

Expected effect:

- Remove false bottlenecks caused by stale benchmark SQL.
- Preserve trustworthy perf evidence for future optimization patches.

Validation:

- Re-run perf harness and query-plan collection on the approved DB.
- Compare new artifacts under `build/logs/`.
- Result: implemented; refreshed artifacts include schema-aware outputs and
  live-service query-plan capture under `build/logs/task30/`.

### PATCH-03: Large-project query path mitigation

Status: planned follow-up

Files:

- `app/services/term_extraction_service.py`
- `app/infra/migrations/*`
- `tests/*perf*`

Goals:

- Reduce or remove hot-path aggregation over `lemma_doc_stat` where feasible.
- Introduce indexed/materialized helper strategy if direct query optimization is insufficient.

Current note:

- The confirmed live `TermExtractionService` path in the current repo re-parses
  processed sentences and does not directly execute the diagnostic
  `lemma_doc_stat` rollup query collected in the evidence pack.
- Do not land a production perf rewrite here until the caller and desired
  replacement path are re-confirmed against the real extraction workflow.

Expected effect:

- Significant reduction in term extraction tail latency on reference-scale projects.

Validation:

- Query-plan evidence and bounded timing probes on the approved DB.
- Regression tests for determinism and WAL safety.

### PATCH-04: Readiness and health semantics cleanup

Status: implemented on 2026-03-09

Files:

- `app/services/health_check_service.py`
- related settings/provider tests

Goals:

- Unify readiness semantics for MT and audio providers.
- Make configured vs enabled vs optional reporting consistent.
- Document known runtime-root/resource-root assumptions.
- Treat explicit `pronunciation/phonikud/model_path` or `PHONIKUD_MODEL_PATH`
  as a valid installed niqqud resource source, even when the model lives
  outside the managed `data_root`.

Validation:

- Self-check JSON comparisons.
- Targeted provider config tests.
- Result: implemented; MT health now respects master enable + per-provider
  enable + chain membership semantics, matching audio-style readiness reporting.
- Result: implemented; resource registry now recognizes explicit external
  Phonikud model paths, so health/wizard state matches real inference readiness.

## Out of scope for PATCH-01

- Full dual-DB reference/user overlay architecture.
- Out-of-process worker architecture.
- Materialized large-project summary tables.
- Batch translate/audio coordinator expansion beyond the touched translation overlay paths.

## Evidence commands

```powershell
python -m app.main --self-check db_open --db-path "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db"
python -m app.main --self-check health --db-path "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db"
python scripts\perf_harness.py --db-path "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db" --runs 5 --warmup 1 --out build\logs\task30\perf_harness_hewiki_test.json
python scripts\collect_queryplan_evidence.py --db-path "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db" --project-id 1 --search-term wiki --out-dir build\logs\task30
```

## DoD for the first implementation wave

- Translation overlay worker uses read session only.
- Terms overlay results are request-sequenced and stale-safe.
- Translate Text dialog no longer force-terminates worker threads.
- Query-plan/perf artifacts record approved DB identity more explicitly.
- MT health no longer reports disabled providers as configured/active.
- New targeted tests cover lifecycle and stale-result behavior.
- Existing touched-path regressions pass on local temp-root-safe pytest runs.
