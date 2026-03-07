# Performance Scale Audit: Hewiki Reference Project (2026-03-07)

## Status
- **Approved for development** by operator (2026-03-07)
- Architectural choice confirmed: **Variant A — Reference DB read-only, user layers in user DB**
- This document is the authoritative planning baseline for PERF-SCALE patch series

## Audited DB
- Path (writable local copy): `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`
- Original reference (read-only): `M:\V_book\HDLE_Processing\hewiki_gpu_processing.db`
- Project ID: `1` — "🌐 Hebrew Wikipedia Baseline"
- DB size: **17.1 GB**
- WAL: 0 MB (clean at audit time)
- Total indexes: 119

---

## 1. Real Scale Measurements

| Table | Row count | Notes |
|---|---:|---|
| `source_document` | 387,645 | Wikipedia articles |
| `document_sentence` | 13,388,138 | All segmented sentences |
| `lemma` | 2,072,852 | Unique lemmas, project_id=1 |
| `tm_entry` | 2,074,241 | TM entries |
| `lemma_project_stat` | 2,072,852 | Per-project lemma stats |
| **`lemma_doc_stat`** | **104,177,943** | **CRITICAL — 104M rows, largest table** |
| `ngram` | 3,641 | N-gram index |
| `term_cluster` | 2,261 | Extracted term clusters |

**Key ratio:** `lemma_doc_stat` has ~50 rows per lemma on average (104M / 2M), meaning each lemma
appears in ~50 documents on average. Any unindexed JOIN or GROUP BY through this table on a
hot path is catastrophic.

---

## 2. Confirmed Performance Violations

### 2.1 SLO breach — picker_page_search
- **Measured p95: 2.09s** vs SLO budget **1.50s** (source: `build/perf_hewiki_audit.json:95`)
- Query plan: TEMP B-TREE for ORDER BY on both `picker_page_empty` and `picker_page_search`
  (source: `docs/PERF_QUERY_PLANS_HEWIKI.md:105`, `:123`)
- Root cause: LIKE-based text predicate + no FTS5 + sort not covered by any index

### 2.2 Write-gate bottleneck — import.table.lemma
- Stable TOP-1 bottleneck across 3/3 stability runs (source: `docs/PERF_BASELINE_REF_2026-03-06.md`)
- Max hold: **~270ms** (post PATCH-03)
- Root cause: `lemma_doc_stat` writes during import — not just 2M lemma rows, but 104M stat rows

### 2.3 No concurrent operation coordination
- **MISSING** single-writer policy (source: `docs/PERF_IMPLEMENTATION_AUDIT.md` §5.3)
- Multiple heavy workers (NLP processing, batch translate, niqqud bootstrap, TTS, import)
  can fire simultaneously with no coordination
- All compete for the same SQLite write lock on a 17 GB database
- `busy_timeout=15000ms` is a fallback, not an architectural solution

### 2.4 Single DBService singleton — reads compete with writes
- **PARTIAL** dual read/write path (source: `docs/PERF_IMPLEMENTATION_AUDIT.md` §1.2)
- All UI list views and all mutation workers share one SQLAlchemy engine
- Under heavy write load, read latency spikes are unavoidable with this topology

### 2.5 TEMP B-TREE disk spill
- `PRAGMA temp_store` not set explicitly — defaults to FILE on most platforms
- `picker_page_empty` also uses TEMP B-TREE despite empty search
- `temp_store=MEMORY` + `mmap_size` not configured
- Affects every ORDER BY that cannot be served from an index

---

## 3. Root Cause Summary (5 causes)

### C1 — Reference project treated identically to a small user project
A 17 GB / 104M-row corpus runs through the same code paths as a user's 200-document project.
Dictionary count, search, picker, TM panel — all hit massive tables without special handling.
User-interactive operations (translate, audio, pronunciation) are enabled on reference project,
triggering heavy writes to an already oversized database.

### C2 — No operation coordination (Operations Center MISSING)
No central registry or priority queue for long-running operations. The following can all run
simultaneously with no serialization:
- NLP processing worker
- batch translate worker
- niqqud bootstrap worker
- TTS generation worker
- project import worker
- UI-initiated saves

Each contends for the same write lock. Contention is nondeterministic and degrades
non-linearly as the number of concurrent writers grows.

### C3 — Single DB engine: reads degrade under write pressure
`DBService` singleton with one SQLAlchemy engine (`app/services/db_service.py:11-43`).
SQLite WAL allows one writer + multiple readers, but only if they use separate connections.
A single shared engine pool means readers queue behind writers.

### C4 — LIKE search instead of FTS5 for document picker
`picker_page_search` uses `lower(d.file_name) LIKE lower(?)` on 387K rows.
TEMP B-TREE for ORDER BY. FTS5 infrastructure exists in project (`fts_manager.py`) but
is not applied to `source_document`.

### C5 — `lemma_doc_stat` 104M rows — hidden cost in import and aggregation
Not visible from table counts of other tables. Every import of a reference-scale project
writes 100M+ rows to `lemma_doc_stat`. Any aggregating query through this table without
a tight covering index is a full scan of 104M rows.

---

## 4. Approved Architecture: Variant A — Reference DB Read-Only + User Overlay

```
hewiki_gpu_processing.db  [READ-ONLY, ATTACH]
    source_document        (387K rows)
    document_sentence      (13M rows)
    lemma                  (2M rows)
    lemma_doc_stat         (104M rows)
    tm_entry               (baseline TM, read-only)
    lemma_project_stat     (2M rows)
    ...all reference data...

hdle_premium.db  [READ-WRITE, primary user DB]
    dict_project           (is_reference=1 flag for hewiki project)
    ref_project_overlay    (user translations, audio, pronunciation for ref items)
    tm_entry               (user-created/edited TM entries)
    audio_queue_item       (user audio)
    sentence_pronunciation (user pronunciation overrides)
    ...all user-mutable layers...
```

**Connection contract:**
- `ReadOnlyDatabaseManager` — separate engine, `PRAGMA query_only=ON`, no WAL writes
- `DatabaseManager` (existing) — user DB, all mutations routed here
- `DBService.get_ref_session()` — read-only session from reference engine
- `DBService.get_write_session()` — write session for user DB only
- Reference engine never participates in write-gate or import transactions

**Benefits:**
- No write contention from reference reads
- WAL overhead for reference DB = 0
- No risk of accidental writes to 17 GB corpus
- User DB stays small (no 104M-row tables)
- Reference DB can be shared read-only across multiple user DB instances

---

## 5. Patch Series Plan (PERF-SCALE)

### PATCH-I (quick win, no schema change): PRAGMA hardening
**Files:** `app/infra/db.py`
**Change:** Add to `set_sqlite_pragma` event handler:
```python
cursor.execute("PRAGMA synchronous=NORMAL")   # WAL-safe, faster than FULL
cursor.execute("PRAGMA temp_store=MEMORY")    # all TEMP B-TREE ops in RAM
cursor.execute("PRAGMA mmap_size=268435456")  # 256MB memory-mapped I/O
cursor.execute("PRAGMA cache_size=-65536")    # 64MB page cache
```
**Impact:** `temp_store=MEMORY` directly removes disk spill for TEMP B-TREE ORDER BY.
Expected improvement on `picker_page_empty` and `picker_page_search`.
**Risk:** Very low. WAL + synchronous=NORMAL is the standard recommended combination.
**Tests:** Re-run `scripts/perf_harness.py` on hewiki sandbox, compare p95.

---

### PATCH-D (P0): FTS5 for document picker search — closes SLO breach
**Files:**
- `app/infra/migrations/027_reference_fts_picker.sql` (new)
- `app/services/document_service.py`
- `app/ui/dialogs/document_picker_dialog.py`

**Migration:**
```sql
CREATE VIRTUAL TABLE IF NOT EXISTS document_name_fts
    USING fts5(file_name, tag, content=source_document, content_rowid=doc_id);

INSERT INTO document_name_fts(document_name_fts) VALUES('rebuild');

CREATE TRIGGER doc_name_fts_ai AFTER INSERT ON source_document BEGIN
    INSERT INTO document_name_fts(rowid, file_name, tag)
    VALUES (new.doc_id, new.file_name, new.tag);
END;
CREATE TRIGGER doc_name_fts_au AFTER UPDATE ON source_document BEGIN
    INSERT INTO document_name_fts(document_name_fts, rowid, file_name, tag)
    VALUES ('delete', old.doc_id, old.file_name, old.tag);
    INSERT INTO document_name_fts(rowid, file_name, tag)
    VALUES (new.doc_id, new.file_name, new.tag);
END;
CREATE TRIGGER doc_name_fts_ad AFTER DELETE ON source_document BEGIN
    INSERT INTO document_name_fts(document_name_fts, rowid, file_name, tag)
    VALUES ('delete', old.doc_id, old.file_name, old.tag);
END;
```

**Also add composite index for empty-search ORDER BY:**
```sql
CREATE INDEX IF NOT EXISTS idx_doc_corpus_doc_id_desc
    ON source_document(corpus_id, doc_id DESC);
```

**Service change:** `document_service.py` — when search text is non-empty, use FTS5 MATCH
path; empty search uses existing index path (now with composite index above).

**Expected result:** `picker_page_search` p95 from 2.09s to < 100ms.
**Stop-gate:** `picker_page_search p95 <= 1.50s` verified by `scripts/perf_harness.py`.

---

### PATCH-A (P0): Reference DB Read-Only Dual-DB Architecture
**Files:**
- `app/infra/db.py` — new `ReadOnlyDatabaseManager` class
- `app/services/db_service.py` — `attach_reference()`, `get_ref_session()`, `get_write_session()`
- `app/infra/sa_models.py` — `DictProject.is_reference: Mapped[bool]`, `DictProject.ref_db_path: Mapped[str]`
- `app/infra/migrations/027_reference_fts_picker.sql` — (or 028) `ALTER TABLE dict_project ADD COLUMN is_reference INTEGER DEFAULT 0`, `ref_db_path TEXT`
- `app/ui/project_view.py` / panels — reference badge, disable destructive actions
- `app/services/dictionary_service.py` — route to `get_ref_session()` when `project.is_reference`
- `app/services/document_service.py` — same routing
- `app/services/sentences_workspace_service.py` — same routing
- `app/services/term_extraction_service.py` — same routing

**ReadOnlyDatabaseManager contract:**
- Engine URL: `sqlite:///path?mode=ro&uri=true` (Python sqlite3 URI mode)
- PRAGMAs on connect: `PRAGMA query_only=ON`, `PRAGMA journal_mode=WAL` (read),
  `PRAGMA busy_timeout=5000`, `PRAGMA temp_store=MEMORY`
- No migration application
- No FTS health check writes
- No `tm_global` backfill

**UI contract for reference projects:**
- Tab header shows "🌐" badge and "Reference Corpus" tooltip
- Disabled: "Translate All", "Delete Project", "Import Bundle", "Add Document"
- Enabled (read-only overlays): view translations, audio playback (if pre-generated),
  pronunciation view, concordance search
- All mutation actions that reach reference DB raise `ReferenceProjectReadOnlyError`

**Tests:**
- `tests/test_reference_ro_mode.py` — attach, read succeeds, write raises ReferenceProjectReadOnlyError
- `tests/test_dual_db_routing.py` — project.is_reference=True routes to ref session

---

### PATCH-B (P0): Operations Center — concurrent operation coordinator
**Files:**
- `app/services/operations_center.py` (NEW)
- `app/ui/widgets/operations_status_bar.py` (NEW, minimal statusbar widget)
- Wiring in: `app/ui/workers.py` (ProcessWorker, SentenceNiqqudBootstrapWorker,
  BatchTranslateWorker, AudioGenerationWorker, ProjectImportWorker)

**Contract:**
```
OperationsCenter (singleton)
  max_concurrent_heavy_writers: int = 1
  max_concurrent_reference_ops: int = 1
  running: Dict[str, OperationRecord]
  queue: PriorityQueue

  def submit(op: Operation) -> OperationHandle
  def cancel(op_id: str)
  def get_status() -> List[OperationRecord]

  Signals: op_started(id, name), op_progress(id, pct), op_finished(id), op_cancelled(id)
```

**Priority rules:**
- `INTERACTIVE` (user-triggered single-item saves) — always immediate
- `USER_BULK` (batch translate, niqqud bootstrap on user project) — enqueue if writer busy
- `REFERENCE_PROCESSING` (any op on reference project) — lowest priority, yield to USER_BULK

**Tests:**
- `tests/test_operations_center.py` — queue ordering, cancel, max-concurrent enforcement

---

### PATCH-C (P1): Read/Write engine separation for user DB
**Files:**
- `app/infra/db.py` — `DatabaseManager` gains `read_engine` (second SQLAlchemy engine, same path)
- `app/services/db_service.py` — `get_read_session()` factory for list views
- `app/services/dictionary_service.py`, `document_service.py`,
  `sentences_workspace_service.py`, `term_extraction_service.py` — use `get_read_session()`

**Why this works with SQLite WAL:** WAL allows concurrent readers on a separate connection
even while a writer holds a write lock. With a shared engine pool, readers may queue behind
writers. With a dedicated read engine, reads proceed independently.

---

### PATCH-E (P1): Lemma FTS5 + Count TTL cache
**Files:**
- `app/infra/migrations/029_lemma_fts.sql` (new)
- `app/infra/query_cache.py` (NEW — TTLQueryCache, thread-safe, in-memory)
- `app/services/dictionary_service.py` — `count_lemmas()` uses TTL cache (TTL=30s)
- `app/services/document_service.py` — `get_documents_total_count()` uses TTL cache
- `app/services/term_extraction_service.py` — `count_term_clusters()` uses TTL cache

**Lemma FTS migration:**
```sql
CREATE VIRTUAL TABLE IF NOT EXISTS lemma_fts
    USING fts5(lemma_text, pos, content=lemma, content_rowid=lemma_id);
INSERT INTO lemma_fts(lemma_fts) VALUES('rebuild');
```

---

### PATCH-J (P1): Reference Corpus Processing Mode
- Corpus processing (NLP, niqqud, TTS, translate) available only via CLI scripts,
  not via standard UI mutation paths
- UI shows "Corpus Processing" button → opens dedicated Processing Console dialog
  (not the standard BatchProgressDialogV3)
- Processing Console enforces: one stage at a time, checkpoint-resume, explicit
  operator confirmation before each stage

---

### PATCH-K (P2): Pipeline stage throttler
- `scripts/process_reference_corpus_batch.py` — add `--sequential` mode (default)
- Stages run in order: NLP → terms → niqqud → translate → TTS
- Each stage waits for previous to fully commit + `PRAGMA wal_checkpoint(FULL)`
- Between stages: explicit sleep + GC to release memory from previous stage's model

---

## 6. Execution Order

```
PATCH-I  → PATCH-D  → PATCH-A  → PATCH-B  → PATCH-C  → PATCH-E  → PATCH-J  → PATCH-K
(5 min)    (index+   (dual-db   (ops       (rw        (fts+      (ref       (pipeline
            FTS5)     arch)      center)    engines)   cache)     UI mode)   throttle)
```

Stop-gates between patches:
- After PATCH-I: `picker_page_empty` p95 measurably improved (TEMP B-TREE still present but RAM-only)
- After PATCH-D: `picker_page_search` p95 <= 1.50s confirmed by perf harness
- After PATCH-A: `test_reference_ro_mode.py` passes, no writes possible to reference DB from UI
- After PATCH-B: `test_operations_center.py` passes, no concurrent heavy writers under load test
- After PATCH-C: concurrent reader+writer integration test passes within p95 budget

---

## 7. Risk Register

| Risk | Patch | Severity | Mitigation |
|---|---|---|---|
| FTS5 rebuild on 387K docs takes long time on first migration | PATCH-D | Medium | Rebuild in background worker, not in migration transaction; show progress |
| ATTACH read-only DB breaks existing session code that assumes single DB | PATCH-A | High | Strict routing via `get_ref_session()` / `get_write_session()`; add guard assertions |
| Operations Center deadlock if worker holds lock and waits for queue | PATCH-B | Medium | Timeout on enqueue (5s default); fallback: run immediate with warning |
| `lemma_doc_stat` 104M rows — any new query accidentally doing full scan | All | High | Add query-plan assertions in tests for all new queries touching this table |
| `temp_store=MEMORY` increases RAM usage under high sort load | PATCH-I | Low | Monitor; cap `cache_size`; revert if OOM on constrained machines |

---

## 8. Definition of Done

- [ ] PATCH-I applied; `picker_page_search` TEMP B-TREE confirmed in RAM (not disk spill)
- [ ] PATCH-D applied; migration adds `document_name_fts` + triggers + composite index
- [ ] `picker_page_search` p95 <= 1.50s on hewiki sandbox (`scripts/perf_harness.py`)
- [ ] PATCH-A: `ReadOnlyDatabaseManager` implemented + `DictProject.is_reference` schema
- [ ] PATCH-A: All mutation operations raise `ReferenceProjectReadOnlyError` for reference projects
- [ ] PATCH-A: UI reference badge + disabled actions wired
- [ ] PATCH-B: `OperationsCenter` singleton with priority queue + wired into 4+ workers
- [ ] PATCH-C: `get_read_session()` used in all 4 list-view services
- [ ] All new tests pass; existing regression suites pass
- [ ] Docs: architecture diagram updated to reflect dual-DB model
- [ ] Commit per patch; rollback notes documented

---

## 9. Commit Series (planned)

```
docs(perf): add hewiki scale audit and PERF-SCALE patch series plan

PATCH-I:  perf(pragma): add temp_store=MEMORY, mmap_size, cache_size, synchronous=NORMAL
PATCH-D:  perf(fts5): add document_name_fts + composite index, route picker search to FTS5
PATCH-A:  feat(arch): reference DB read-only dual-DB architecture + is_reference project flag
PATCH-B:  feat(ops): operations center singleton with priority queue + worker wiring
PATCH-C:  perf(db): separate read/write engines for user DB
PATCH-E:  perf(cache): lemma FTS5 + TTL count cache for dictionary/documents/terms
PATCH-J:  feat(ref): reference corpus processing mode (CLI-only, not UI mutations)
PATCH-K:  perf(pipeline): sequential stage throttler for reference corpus pipeline
```

---

## 10. Implemented UI-Layer Performance Patches (2026-03-07)

These patches were implemented in response to the UI performance audit and freeze measurements
on the hewiki reference project. They are independent of the dual-DB architecture (PATCH-A)
and provide immediate improvements on the single-DB path.

---

### PATCH-G ✅ — QAbstractTableModel virtualization (Documents + Sentences tabs)
**Commit:** `PATCH-G: perf(ui): replace QTableWidget with QAbstractTableModel+QTableView`

**Problem:** `QTableWidget` allocates a `QTableWidgetItem` per cell. At 250 rows × 12 cols =
3,000 heap objects per page load — serialized from DB to Python to Qt. Any re-render (sort,
resize, selection change) touched all allocated items.

**Fix:**
- `DocumentsTableModel(QAbstractTableModel)` — 12-col model, `update_rows()` batch push
- `SentencesTableModel(QAbstractTableModel)` — 8-col model, niqqud QC badge colors
- `_current_dtos: List[SentenceDTO]` cache — eliminates all `item(row, N).text()` cell reads
- `selectionModel().selectedRows()` replaces `selectedItems()` throughout
- `rename_committed = pyqtSignal(int, str)` drives rename from model `setData()`

**Result:** Page navigation O(1) model swap instead of O(rows × cols) item allocation.

---

### PATCH-H ✅ — Anti-stale request_id guards
**Commit:** `PATCH-H: perf(anti-stale): request_id guards for sentences + user_dict async load`

**Problem:** Rapid tab switching or filter changes could deliver stale worker results to the
UI, replacing current data with outdated rows.

**Fix:**
- `_SentencesLoadWorker` carries `request_id` in all signals
- `SentencesView._active_request_id` — stale responses silently dropped
- `UserDictItemsPageWorker` — same pattern for dictionaries tab

---

### PATCH-P ✅ — Two-stage worker + migration 030 sort indexes
**Commit:** `PATCH-P: perf(sentences): two-stage worker + covering indexes + SUM fast path`

**Measurements (hewiki):**
| Query | Before | After |
|---|---|---|
| `tm_entry ORDER BY updated_at DESC` | 426 ms | <5 ms |
| `source_document ORDER BY imported_at DESC` | 137 ms | <5 ms |
| `SUM(sentence_count)` unfiltered COUNT | >2 s | ~10 ms |

**Fixes:**
1. **Migration 030** — 5 covering indexes for default sort columns:
   - `idx_tm_entry_proj_updated_at(project_id, updated_at DESC)`
   - `idx_doc_corpus_imported_at(corpus_id, imported_at DESC)`
   - `idx_doc_corpus_sentence_count_sum(corpus_id, sentence_count)` (for SUM fast path)
   - `idx_doc_corpus_sentence_count_cov`, `idx_doc_corpus_token_count_cov`
2. **`count_sentences()` fast path** — `SUM(sentence_count)` over `source_document` rows
   instead of 3-table JOIN COUNT on 13M rows (~10ms vs >2s)
3. **Two-stage `_SentencesLoadWorker`** — emits `page_ready` immediately after
   `list_sentences()`, `count_ready` after `count_sentences()`. UI shows row data without
   waiting for the COUNT query.

---

### PATCH-Q ✅ — Corpus ID denormalization for O(page_size) sentence pagination
**Commit:** `PATCH-Q: perf(sentences): denormalize corpus_id for O(page_size) pagination`

**Root cause:** Even after PATCH-P, `list_sentences()` page query took **~584 seconds** on
hewiki. The nested-loop JOIN `document_sentence → source_document → source_corpus` with
`ORDER BY sentence_id LIMIT 100` forced SQLite to build a TEMP B-TREE over all 13M rows
before applying LIMIT.

**Query plan before:**
```
SEARCH sd USING COVERING INDEX idx_doc_corpus_doc_id_desc (corpus_id=?)
SEARCH ds USING COVERING INDEX idx_sentence_doc (doc_id=?)
USE TEMP B-TREE FOR ORDER BY     ← sorts 13M rows, then LIMIT 100
```

**Fix — migration 031:**
```sql
ALTER TABLE document_sentence ADD COLUMN corpus_id INTEGER;
UPDATE document_sentence SET corpus_id = (SELECT corpus_id FROM source_document ...);
CREATE INDEX idx_sentence_corpus_sent_id ON document_sentence(corpus_id, sentence_id);
```

**Query plan after:**
```
SEARCH document_sentence USING INDEX idx_sentence_corpus_sent_id (corpus_id=?)
→ O(page_size) covering index scan, no TEMP B-TREE
```

**Expected result:** `list_sentences()` page query <5ms (from 584s).

**Service changes:**
- `list_sentences()` — `WHERE corpus_id IN (project_corpus_ids)` replaces 3-table JOIN
- `count_sentences()` filtered path — same
- `get_page_sentence_ids()`, `get_all_filtered_sentence_ids()` — same
- `_get_project_corpus_ids()` helper (fast, few rows per project)

**Migration note:** One-time backfill on 13M rows takes ~30–120s on first app startup.

---

## 11. Migration Application Status (hewiki reference DB)

| Migration | Applied | Time |
|---|---|---|
| 030 (sort indexes) | ✅ 2026-03-07 | 4.5s |
| 031 (corpus_id backfill) | ✅ 2026-03-07 | see task output |

DB path: `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`

---

*Audit date: 2026-03-07*
*Skill pack applied: `premium_desktop_pyqt_sqlite` — SKILL_01 (repo audit), SKILL_02 (patch planner),
SKILL_03 (migrations), SKILL_05 (DB lock mitigation), SKILL_09 (scoring/canonical layer)*
