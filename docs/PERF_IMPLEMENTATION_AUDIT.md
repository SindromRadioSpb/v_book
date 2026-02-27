# Performance/Scalability Audit - Implemented vs Recommended Map (Hewiki Scale)

Date: 2026-02-27
Audited commit: `536e3cb` (HEAD)
Target DB context: `M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db`
Applied skill pack: `premium_desktop_pyqt_sqlite` (focus modules: SKILL_05, SKILL_06, SKILL_07, SKILL_12, SKILL_13)

## Scope and method
This is an evidence-based audit (no implementation changes in this task). Claims are grounded in:
- repository code (file + line references),
- executed validation/tests/perf runs,
- existing docs and generated perf artifacts.

## Preconditions and verification run in this audit
### Mandatory docs reviewed
- `docs/PERFORMANCE_SLO.md`
- `docs/PERF_HARNESS.md`
- `docs/PERF_QUERY_PLANS_HEWIKI.md`
- `docs/UI_DOD_EVIDENCE_RELEASE_INSTALL.md`
- `docs/UI_DOD_EVIDENCE_DOCUMENTS_PAGINATION.md`
- `docs/AUDIO_PLAYER_V2.md`
- `docs/PROJECT_EXCHANGE.md`
- `docs/TM_NOISE_SYNC_TRIGGERS.md`
- `docs/KEYBOARD_SHORTCUTS.md`
- `docs/KEYBOARD_INTERACTIONS.md`

### Preconditions and regressions
- `python scripts/prebuild_validate.py --profile reference-ro --db-path "M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db" --skip-quick-check`
  - Result: `PASS_WITH_SKIPS` (write checks intentionally skipped for `reference-ro` profile).
- `python -m pytest tests/test_phonikud_import_available.py tests/test_sqlite_busy_retry.py tests/test_dictionary_pagination_flow.py tests/test_document_picker_flow.py tests/test_project_delete_flow.py -q`
  - Result: `12 passed`.
- `python -m pytest tests/test_project_exchange.py -k "cancel_returns_cancelled_report" -q`
  - Result: `1 passed`.
- `python -m pytest tests/test_task13_trigger_sync.py -q`
  - Result: `7 passed`.

### Perf measurements executed on target hewiki DB
- `python scripts/perf_harness.py --db-path "M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db" --runs 5 --warmup 1 --out build/perf_hewiki_audit.json`
- `python scripts/query_plan_audit.py --db-path "M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db" --out build/PERF_QUERY_PLANS_HEWIKI_AUDIT_20260227.md`

Observed p95 against `docs/PERFORMANCE_SLO.md` budgets:
- `dictionary_first_page`: 0.002s vs budget 0.50s (PASS) (`build/perf_hewiki_audit.json:32`)
- `dictionary_count`: 0.199s vs budget 1.50s (PASS) (`build/perf_hewiki_audit.json:53`)
- `picker_page_empty`: 0.058s vs budget 0.30s (PASS) (`build/perf_hewiki_audit.json:74`)
- `picker_page_search`: 2.090s vs budget 1.50s (FAIL) (`build/perf_hewiki_audit.json:95`)

## Blind spots (explicit)
1. Read-only DB constraints vs migration/index checks:
- `reference-ro` profile skips write checks, so migration/index creation cannot be re-validated on the target readonly DB in this run (`scripts/prebuild_validate.py:36`, `scripts/prebuild_validate.py:408`, `scripts/prebuild_validate.py:416`).

2. Installer vs dev-run parity:
- Spec includes ONNX/phonikud hiddenimports, and there are release smoke docs/scripts, but parity still depends on actually running frozen smoke for each build (`hdle_premium_installer.spec:94-97`, `scripts/prebuild_fast_gates.ps1:25-48`, `docs/UI_DOD_EVIDENCE_RELEASE_INSTALL.md:176-187`).

3. SQLite lock contention hotspots:
- Import path uses `BEGIN IMMEDIATE` for a full-table loop transaction (`app/services/project_exchange/import_engine.py:329-385`), which can block other writers for long windows on huge bundles.

4. Per-row SQL risks in Qt models:
- `app/ui/models_qt.py` data models are DTO-driven with no DB session/execute calls in `data()` (scan evidence), but large `QTableWidget` usage still risks UI-side overhead (`app/ui/documents_view.py:310`, `app/ui/sentences_view.py:222`).

---

## A) Executive summary
### What is already strong
- Core pagination exists across Documents/Dictionary/Terms/Sentences/User Dictionaries service layer (LIMIT/OFFSET + filtered counts).
- Dictionary has premium anti-stale behavior and staged render (rows first, expensive overlays/count deferred).
- Worker/session hygiene is generally solid: worker-scoped sessions and rollback/close patterns are common.
- Export has cancellation wiring and chunk-aware loops.
- Installer spec and prebuild gates include ONNX/phonikud contract checks.

### Top current bottlenecks at hewiki scale
1. Document picker text-search p95 exceeds SLO (`2.09s > 1.50s`) and query plan still reports temp sort b-tree (`build/PERF_QUERY_PLANS_HEWIKI_AUDIT_20260227.md:123`).
2. Import path keeps one `BEGIN IMMEDIATE` transaction across full table import (lock contention risk under concurrent activity).
3. No system-level write serialization policy (many direct commits across UI/service paths), so lock behavior depends on ad-hoc retries.

### Top 3 recommendations
1. **P0**: Make import cancelable and reduce lock window (cancel checks + commit/savepoint boundaries).
2. **P0**: Fix document picker search path to hit SLO (index-friendly predicate/order strategy; preserve deterministic pagination).
3. **P0/P1**: Introduce explicit read/write DB separation policy (at least separate read engine; then dual-DB architecture processing-ro + user-rw).

---

## B) Implemented vs Recommended matrix
Status legend: `IMPLEMENTED` / `PARTIAL` / `MISSING` / `UNKNOWN`

| Method | Status | Evidence | Risk if missing | Recommendation | Priority | Tests/Evidence to add |
|---|---|---|---|---|---|---|
| **1.1 PRAGMAs: WAL / synchronous / busy_timeout** | PARTIAL | WAL + busy timeout are set per connection: `app/infra/db.py:30-33` (blame: `5cfdc7b`, `5e463b21`); `synchronous` is not explicitly set in DB manager. | Inconsistent durability/latency behavior across environments if SQLite default differs. | Explicitly set `PRAGMA synchronous` policy (`NORMAL` or `FULL` by release profile) and verify at startup self-check. | P1 | Add `tests/test_db_pragmas_contract.py` asserting effective pragma values on fresh connection. |
| **1.2 Separate read/write connections (UI read vs worker write engines)** | PARTIAL | Single DB singleton/engine path: `app/services/db_service.py:11-43`. Project exchange uses raw sqlite connections separately (`app/services/project_exchange/import_engine.py`, `export_engine.py`). | Read latency spikes and lock waits under heavy writes. | Add a dedicated read-only/read-optimized engine for UI list views; keep writes on separate engine/session factory. | P0 | Integration test: concurrent writer + paged reader latency stays within budget. |
| **1.3 Read-only mode for processing DB + writable user DB separation** | PARTIAL | `mode=ro` exists in self-check/inspection only (`app/main.py:471-487`, `app/infra/db_path_resolver.py:137`), but runtime DBService uses one writable DB path. | Either accidental writes to huge processing DB, or inability to isolate user-generated state cleanly. | Implement explicit dual-path runtime contract: processing DB mounted ro + user DB rw for mutable layers. | P0 | New integration tests for dual-db routing; read-only processing DB must still allow user edits in user DB. |
| **1.4 Index coverage for WHERE+ORDER BY+LIMIT/OFFSET** | PARTIAL | Perf indexes added (`app/infra/migrations/026_perf_indexes.sql:7-10`), but query plan still shows temp sort b-tree in picker queries (`build/PERF_QUERY_PLANS_HEWIKI_AUDIT_20260227.md:105`, `:123`). | p95 regressions on large projects (confirmed picker search SLO breach). | Add index/query rewrite for picker search order path to avoid temp b-tree in dominant flows. | P0 | Add query-plan regression test + perf harness gate for `picker_page_search`. |
| **2.1 Server-side pagination everywhere (Documents/Dictionary/Terms/Sentences/UD)** | IMPLEMENTED | Documents: `fetch_documents_page`/`get_documents_total_count` (`app/services/document_service.py:229-267`); Dictionary: `search_lemmas`/`count_lemmas` (`app/services/dictionary_service.py:21`, `:92`); Terms: `list_term_clusters`/`count_term_clusters` (`app/services/term_extraction_service.py:671`, `:808`); Sentences: `list_sentences`/`count_sentences` (`app/services/sentences_workspace_service.py:37`, `:134`); UD: `query_items(...limit, offset)` (`app/services/user_dictionary_service.py:1045-1099`). | Without this, table views would freeze/load all rows. | Keep as invariant; enforce in tests for any new list endpoint. | P2 | Keep existing suites; add contract test that new list services reject unbounded fetch by default. |
| **2.2 ORDER BY before LIMIT/OFFSET with stable secondary sort** | PARTIAL | Documents stable tie-breaker `doc_id` (`app/services/document_service.py:447-449`); Dictionary tie-breaker `lemma_id` (`app/services/dictionary_service.py:157-159`); Sentences secondary `sent_index` (`app/services/sentences_workspace_service.py:83-85`); Terms ranking order lacks explicit PK tie-breaker in presets (`app/services/term_extraction_service.py:762-778`). | Non-deterministic page boundaries, duplicates/skips between pages. | Add deterministic secondary key (`cluster_id`) to all Terms ranking presets and matching count/list flows. | P1 | Add `tests/test_terms_stable_sort_pagination.py`. |
| **2.3 Debounce + request_id anti-stale (search/filter/sort)** | PARTIAL | Implemented in Documents (`app/ui/documents_view.py:189-192`, `:533-565`, blame `0be3de86`), Dictionary (`app/ui/dictionary_view.py:456-458`, `:503`, `:551-557`), Terms (`app/ui/terms_view.py:449-450`, `:492`); Sentences uses debounce+worker but drops updates when worker active (`app/ui/sentences_view.py:312-316`); User Dictionaries `load_items` is direct sync call (`app/ui/user_dictionaries_view.py:892-903`) without request_id anti-stale. | Stale or dropped UI state during rapid typing/filter changes; perceived jitter/hang. | Standardize `request_id + stale-drop` pattern for Sentences and User Dictionaries list reloads. | P1 | Add UI tests mirroring dictionary anti-stale behavior for Sentences and UD. |
| **2.4 Remove heavy joins from first paint; 2-stage load** | PARTIAL | Dictionary worker emits rows first then count (`app/ui/workers.py:1015-1038`) and overlays deferred (`app/ui/dictionary_view.py:538-542`, blame `6c19e900`); Terms worker computes count before emit (`app/ui/workers.py:1088-1113`); UD load_items does sync row+overlay path (`app/ui/user_dictionaries_view.py:902-913`). | Slow first paint and "frozen" feel on huge data. | Replicate dictionary staged-load pattern for Terms and UD item tables. | P1 | Add first-paint latency probes in perf harness + UI smoke evidence. |
| **3.1 Worker signal contract (stages, counts, progress)** | IMPLEMENTED | Rich signal contracts across workers (`app/ui/workers.py`: e.g., `BatchTranslateWorker` `1670-1678`, `TranslateAllFilteredWorker` `1858-1866`, pronunciation/audio workers with `progress/stage/stats`). | Weak observability and inconsistent UX if missing. | Keep signal contract checklist for new long ops. | P2 | Contract tests for worker signals (emission order + terminal state). |
| **3.2 Cancel boundary inside loops (quick cancel 1-3 sec)** | PARTIAL | Export uses cancel callback wired to worker (`app/services/project_exchange/worker.py:40-45`, blame `47a1ca3d`; `export_engine.py:69`, `:174-175`, `:274-287`); Import worker has cancel flag but engine call has no cancel callback (`app/services/project_exchange/worker.py:100-104`, blame `ee7bacee`; `import_engine.py` signature has no cancel arg). | Long-running operation appears unresponsive to cancel; user may kill app. | Add `cancel_check` to import engine and check at safe boundaries (table/chunk loop) with clean rollback. | P0 | Add `test_import_cancel_returns_cancelled_report` + cancel-ack latency assertion. |
| **3.3 Session isolation per worker job; rollback in except; close in finally** | IMPLEMENTED | Worker-scoped sessions via `with db_service.get_session()` are widespread (`app/ui/workers.py` many call sites); import engine rollback+finally close (`app/services/project_exchange/import_engine.py:390`, `:137-145`). | Cross-thread session reuse bugs and stuck transactions. | Keep pattern mandatory in code review checklist. | P2 | Add lint-like guard test for workers opening shared/global sessions. |
| **4.1 QTableView + QAbstractTableModel (no QTableWidget for big data)** | PARTIAL | QTableView used in Dictionary/Terms/UD (`app/ui/dictionary_view.py:312-315`, `app/ui/terms_view.py:205-208`, `app/ui/user_dictionaries_view.py:355-358`); Documents and Sentences still use QTableWidget (`app/ui/documents_view.py:310`, `app/ui/sentences_view.py:222`). | Higher UI memory/paint overhead at scale; weaker virtualization behavior. | Migrate Documents and Sentences tables to QAbstractTableModel + QTableView incrementally. | P1 | Add UI regression tests for sort/select/context menu parity after migration. |
| **4.2 No SQL in model.data(); DTO-first** | IMPLEMENTED | `app/ui/models_qt.py` models are pure DTO renderers; no DB session/execute calls found in model methods (scan of file). | Per-cell DB calls would destroy scalability. | Keep strict "no DB in model" invariant. | P2 | Add static grep test to fail if `get_session/execute` appears in `models_qt.py`. |
| **4.3 Virtualized selectors (no huge combobox; picker dialog with paging)** | PARTIAL | Document picker dialog is paged, debounced, anti-stale (`app/ui/dialogs/document_picker_dialog.py:44`, `:181-209`); Sentences uses it (`app/ui/sentences_view.py:37`, `:474`). No generalized virtualized picker pattern for all potentially large selectors. | Large selector widgets can freeze when cardinality grows. | Reuse `DocumentPickerDialog` pattern for any >1k-item selector path. | P1 | Add guideline + smoke tests for large-selector entrypoints. |
| **5.1 Export/import lock behavior; chunked snapshot** | PARTIAL | Export is cancelable and stage/chunk aware (`app/services/project_exchange/export_engine.py:223-287`, `:696-708`); Import keeps one `BEGIN IMMEDIATE` transaction across table loop (`app/services/project_exchange/import_engine.py:329-385`) though inserts are chunked (`:522-526`). | Long write lock window during import; higher SQLITE_BUSY risk. | Split import into bounded transactional phases/savepoints while preserving atomicity guarantees where required. | P0 | Add lock-contention integration test (import + concurrent UI write/read). |
| **5.2 Retry/backoff only for SQLITE_BUSY + rollback hygiene** | PARTIAL | Retry helper matches locked errors only (`app/infra/db_retry.py:18-22`) and runs rollback callback (`:28-43`, `:155-159`); usage is selective, not universal across all write paths. | Inconsistent lock recovery, intermittent user-facing failures. | Centralize write wrappers for all high-contention writes; keep retry strictly to lock errors. | P0 | Add coverage report for retry wrapper usage on critical write flows. |
| **5.3 Single writer policy (serialization/queue)** | MISSING | No dedicated single-writer coordinator module found; many direct commits in UI/services (`rg` evidence across `app/ui/*` and `app/services/*`). | Burst write contention and nondeterministic lock behavior at scale. | Introduce lightweight single-writer gate/queue for high-contention mutation paths. | P0 | Add deterministic writer-queue tests under concurrent producers. |
| **6.1 Cached counts/facets (TTL) and/or approximate counts while typing** | PARTIAL | TM has project-lemma cache (`app/ui/translation_management_panel.py:392`, `:854-874`); no broad TTL/approx count strategy for Dictionary/Terms/Sentences/UD interactive filtering. | Repeated expensive counts under rapid filter changes. | Add short TTL count cache + optional deferred exact count strategy for interactive filters. | P1 | Add perf test for repeated filter changes with stable p95. |
| **6.2 Materialized search index tables (lemma_search etc.)** | PARTIAL | `term_search` model exists (`app/infra/sa_models.py:542`) and is included in exchange constants; FTS triggers reference it (`app/infra/fts_manager.py:69-87`). No `lemma_search` table/path found. | Large-table search paths remain dependent on contains scans for lemmas. | Introduce `lemma_search` (materialized or FTS-backed) for heavy lemma contains-search workloads. | P2 | Add migration + backfill idempotency tests; query-plan assertions. |
| **6.3 FTS5 for contains search (title/term)** | PARTIAL | FTS5 infra exists (`app/infra/fts_manager.py`) and Concordance uses `MATCH` (`app/services/concordance_service.py:193`); Dictionary/Terms/Document filters use `contains/ilike` (`app/services/dictionary_service.py:139`, `app/services/term_extraction_service.py:745-758`, `app/services/document_service.py:144-145`). | Contains search p95 degradation on very large datasets. | Add FTS-backed search path for picker/title/term contains; retain fallback for compatibility. | P1 | Add A/B perf harness metrics comparing LIKE vs FTS path on hewiki-scale DB. |
| **7.1 Processing DB vs User DB separation via bundles** | PARTIAL | Bundle import/export is present (`app/services/project_exchange/*`), but runtime DB access is single-path singleton (`app/services/db_service.py`). | User writes and heavy processing data compete in same DB file lifecycle. | Move toward runtime dual-db model (processing ro + user rw overlay, bundle-aware sync points). | P1 | Add end-to-end tests for dual-db consistency and bundle round-trip. |
| **7.2 Operations Center (queue, priorities, unified long-op diagnostics)** | MISSING | No dedicated operations-center module/API found in current app code/docs search. | Fragmented long-op control and diagnostics; harder incident triage. | Add minimal Operations Center registry: operation queue, priorities, unified progress/cancel telemetry. | P2 | Add integration tests for queue ordering, cancellation, and diagnostics events. |
| **7.3 Profiling/perf gate as release gate (budgets + evidence)** | PARTIAL | Perf harness + SLO docs exist (`scripts/perf_harness.py`, `docs/PERFORMANCE_SLO.md`, `docs/PERF_HARNESS.md`); prebuild fast gates focus on spec/onnx checks (`scripts/prebuild_fast_gates.ps1:25-48`), no perf budget enforcement in gate scripts (`rg` under `scripts`). | Regressions can ship without explicit p95 gate failure. | Add CI/prebuild perf gate step that fails release when SLO budgets are exceeded. | P1 | Add `scripts/perf_gate.py` + test fixture validating fail/pass behavior by budget file. |

---

## C) Evidence map (code/docs)
### Database and retry infrastructure
- DB connect and PRAGMA setup: `app/infra/db.py:23`, `:30-33` (blame `5cfdc7b`, `5e463b21`).
- DB singleton/session entry: `app/services/db_service.py:11-43`.
- Lock retry policy and rollback callback: `app/infra/db_retry.py:18-22`, `:28-43`, `:74-108`, `:155-159`.

### Pagination, sort, anti-stale, staged load
- Documents pagination + stable sort: `app/services/document_service.py:229-267`, `:447-449`.
- Documents debounce + request_id anti-stale: `app/ui/documents_view.py:189-192`, `:533-565` (blame `0be3de86`).
- Dictionary pagination/filter + stable tie-break: `app/services/dictionary_service.py:21`, `:92`, `:157-159`.
- Dictionary two-stage UX: worker rows/count split (`app/ui/workers.py:1015-1038`) + deferred overlays (`app/ui/dictionary_view.py:538-542`, `:547-563`, blame `6c19e900`).
- Terms pagination/count: `app/services/term_extraction_service.py:671`, `:808`.
- Terms sort presets without explicit PK tie-break: `app/services/term_extraction_service.py:762-778`.
- Sentences pagination service: `app/services/sentences_workspace_service.py:37`, `:83-85`, `:134`.
- Sentences reload drop-when-busy pattern: `app/ui/sentences_view.py:312-316`.
- User Dictionaries paged query: `app/services/user_dictionary_service.py:1045-1099`.
- User Dictionaries sync load path: `app/ui/user_dictionaries_view.py:892-913`.

### Worker/cancel/session safety
- Export worker cancel wiring: `app/services/project_exchange/worker.py:40-45` (blame `47a1ca3d`).
- Import worker call has no cancel callback: `app/services/project_exchange/worker.py:100-104` (blame `ee7bacee`).
- Import long transaction: `app/services/project_exchange/import_engine.py:329-385` (blame `ee7bacee` / `99cf18b3`).
- Import rollback/finally close: `app/services/project_exchange/import_engine.py:390`, `:137-145`.

### Query plans and measured bottlenecks
- SLO contract: `docs/PERFORMANCE_SLO.md:14-31`.
- Harness metric generation: `scripts/perf_harness.py:97-98`.
- Measured p95 breach (`picker_page_search`): `build/perf_hewiki_audit.json:95`.
- Query plan temp sort evidence: `build/PERF_QUERY_PLANS_HEWIKI_AUDIT_20260227.md:105`, `:123`.

### Indexes and FTS
- Perf index migration: `app/infra/migrations/026_perf_indexes.sql:7-10`.
- Baseline lemma/doc indexes: `app/infra/migrations/001_init.sql:423-425`, `:420`.
- FTS manager + trigger wiring: `app/infra/fts_manager.py:16-25`, `:69-87`.
- Concordance FTS `MATCH`: `app/services/concordance_service.py:193`.

### Packaging/release parity
- Installer hiddenimports for phonikud/onnxruntime: `hdle_premium_installer.spec:94-97`, `:169-171` (blame includes `fbbc8abf`, `9cdd1458`).
- Prebuild release gates (spec + frozen ONNX checks): `scripts/prebuild_fast_gates.ps1:25-48`.
- Frozen release smoke expectations: `docs/UI_DOD_EVIDENCE_RELEASE_INSTALL.md:176-187`.

---

## D) Prioritized patch roadmap (incremental, regression-safe)

### P0 - Remove lock/cancel/SLO-critical blockers
#### PATCH P0-01: Import cancelability + bounded lock windows
- Scope:
  - add `cancel_check` from UI worker to import engine,
  - check cancel at table/chunk boundaries,
  - replace monolithic transaction with safe phase boundaries/savepoints where possible.
- Target files:
  - `app/services/project_exchange/worker.py`
  - `app/services/project_exchange/import_engine.py`
  - `tests/test_project_exchange.py` (new cancel+latency cases)
- Tests:
  - `test_import_cancel_returns_cancelled_report`
  - `test_import_cancel_ack_p95_under_1s` (controlled fixture)
  - existing `tests/test_project_exchange.py`
- DoD:
  - cancel is acknowledged quickly,
  - no partial corruption on cancellation,
  - rollback path verified.

#### PATCH P0-02: Picker search SLO recovery
- Scope:
  - tune picker query path to reduce temp-sort cost in common search patterns,
  - preserve deterministic ORDER BY + pagination.
- Target files:
  - `app/services/document_service.py`
  - `app/ui/dialogs/document_picker_dialog.py` (if UI query mode options are needed)
  - migration file for supporting index if required.
- Tests/evidence:
  - query-plan assertion test (no temp sort on primary path),
  - perf harness rerun with `picker_page_search p95 <= 1.50s`.
- DoD:
  - SLO restored on hewiki benchmark profile,
  - pagination correctness unchanged.

#### PATCH P0-03: Write contention policy baseline
- Scope:
  - introduce lightweight single-writer gate for high-contention write flows,
  - route critical bulk writes through shared serialization point.
- Target files:
  - new infra/service writer gate module,
  - selected high-contention write call sites.
- Tests:
  - concurrent producer test proving no SQLITE_BUSY leak to UI in nominal load.
- DoD:
  - deterministic write ordering for enrolled flows,
  - lower lock error incidence under synthetic contention.

### P1 - Latency and UX resilience improvements
#### PATCH P1-01: Uniform anti-stale + staged first paint
- Scope:
  - bring Sentences and User Dictionaries onto request_id anti-stale pattern,
  - stage count/overlays after first rows render.
- Target files:
  - `app/ui/sentences_view.py`
  - `app/ui/user_dictionaries_view.py`
  - `app/ui/workers.py`
- Tests:
  - UI stale-response tests equivalent to dictionary coverage.
- DoD:
  - rapid filter typing never applies stale payload,
  - first paint remains responsive.

#### PATCH P1-02: Deterministic Terms sorting
- Scope:
  - add stable secondary sort key (`cluster_id`) for all ranking presets.
- Target files:
  - `app/services/term_extraction_service.py`
  - `tests/test_dictionary_terms_pagination.py` (extend)
- DoD:
  - no duplicate/skip across page boundaries under static dataset.

#### PATCH P1-03: Runtime DB policy hardening
- Scope:
  - explicit `PRAGMA synchronous` policy,
  - introduce separate read engine for list paths.
- Target files:
  - `app/infra/db.py`
  - `app/services/db_service.py`
  - docs for runtime DB policy.
- Tests:
  - pragma contract test,
  - reader-under-writer integration latency test.

### P2 - Architectural scaling track
#### PATCH P2-01: Dual DB architecture (processing ro + user rw)
- Scope:
  - explicit split of immutable processing corpus and mutable user layers.
- Target files:
  - DB path resolver, DB service wiring, migration policy docs.
- Tests:
  - e2e dual-db CRUD + exchange round-trip.

#### PATCH P2-02: Operations Center
- Scope:
  - centralized operation queue, priorities, cancel/status diagnostics.
- Target files:
  - new operations center service + UI diagnostics panel hooks.
- Tests:
  - queue ordering/cancel/telemetry integration tests.

#### PATCH P2-03: Search acceleration layer
- Scope:
  - `lemma_search` (materialized or FTS-backed), extended FTS usage for heavy contains paths.
- Tests:
  - migration/backfill idempotency,
  - query-plan + perf regressions.

---

## E) Risk analysis
| Risk | Current state | Impact | Mitigation path |
|---|---|---|---|
| Lock contention (import vs UI writes) | Import uses `BEGIN IMMEDIATE` over full import loop | UI write stalls / busy errors | P0-01 + P0-03 |
| Readonly constraints hide migration/index issues | `reference-ro` skips write validations | False confidence for migration/index readiness | Run separate writable validation DB in release checklist |
| Installer/dev parity drift | Spec is hardened, but perf parity is not a gate | Installed app may pass smoke but miss perf budgets | Add perf gate into release flow (P1/P2) |
| Query p95 regression on huge text search | Picker text search already breaches SLO | Perceived slowness in key navigation flow | P0-02 + query-plan tests |
| Per-row UI overhead in non-model tables | Docs/Sentences use QTableWidget | Render/interaction degradation at scale | P1 migration to model/view |

---

## F) Measurement plan and performance budgets
### Metrics to collect per release candidate
1. Query latency (`p50`, `p95`) for:
- `dictionary_first_page`
- `dictionary_count`
- `picker_page_empty`
- `picker_page_search`

2. Lock/retry telemetry:
- count of SQLITE_BUSY retries per operation,
- retry success ratio,
- terminal failures after retry budget.

3. Cancel responsiveness:
- export cancel acknowledgement latency,
- import cancel acknowledgement latency (new, after P0-01).

4. UI responsiveness:
- time to first rows rendered for paged views,
- stale-response drop counters.

### Enforced budgets (from `docs/PERFORMANCE_SLO.md`)
- `dictionary_first_page p95 <= 0.50s`
- `dictionary_count p95 <= 1.50s`
- `picker_page_empty p95 <= 0.30s`
- `picker_page_search p95 <= 1.50s`
- `export cancel acknowledgement p95 <= 1.0s`

### Gate recommendation
- Add a perf gate script that consumes `build/perf_*.json` and fails prebuild/release if any p95 budget is violated.
- Persist query-plan audit artifact and fail if critical queries regress to full scans/temp sorts outside accepted exceptions.

---

## Audit conclusion
- The project already contains a strong foundation for hewiki-scale operation (pagination, anti-stale in key panels, workerized long ops, WAL/busy-timeout, packaging checks).
- The highest-value gap is concentrated in **P0 lock/cancel/search-latency fixes**, especially import lock windows and picker search p95.
- After P0 and P1 roadmap items, the codebase is positioned for P2 architectural scaling (dual DB and operations center) without high regression risk.
