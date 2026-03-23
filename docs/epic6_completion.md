# Epic 6 — Dictionary Maturity: Completion Report

> Status: 6A ✔ · 6B ✔ · 6C ✔
> Completed: 2026-03-23
> Tests added: 75 (13 Epic 6A + 31 Epic 6B PATCH-01 + 31 Epic 6B PATCH-02)
> Total suite after Epic 6: 1708 passed, 0 failures

---

## Narrative

Epic 6 had one overarching goal:

> **Backend truth → product truth.**

Epic 6A made provenance *correct* in the database — recording who classified each lemma as noise/valid, when, and whether any source link was preserved after cleanup.

Epic 6B made that provenance *visible* in daily work — surfacing it as badges, tooltips, and a status-bar metric directly in the table the user looks at all day.

Without 6A, there was nothing to show. Without 6B, 6A would have been invisible. Together they close the gap between what the system knows and what the user sees.

---

## Scope by Layer

### Epic 6A — Noise Provenance (Service + Schema)

- `Lemma` table: `noise_source` ("auto" | "manual" | NULL) + `noise_updated_at` (ISO8601 UTC)
- `tm_entry` table: `orphaned_lemma_id` (snapshot of lemma_id before orphan DELETE)
- `ProcessService._create_or_get_lemmas()`: new lemmas get `noise_source="auto"` at creation
- `ProcessService._cleanup_orphaned_lemmas_for_ids()`: snapshots `orphaned_lemma_id` before DELETE
- `DictionaryService.compute_source_lifecycle()`: computes `linked / source_missing / manual / auto_only`
- `BatchMTTranslateService._write_lemma()`: R2 guard — skips `user_edit+approved` entries unless `force_global_update=True`
- `BulkNoiseUpdateWorker`: sets `noise_source="manual"` + `noise_updated_at` on manual noise changes

### Epic 6B PATCH-01 — Column Contract + Status Bar

- `LemmaTableModel`: Entity Class inserted at col 9; Last Review→10, Niqqud→11, Audio→12
- Noise column (col 8): `noise_source` suffix badge (auto / manual / legacy)
- `DictionaryService.count_noise_lemmas()`: COUNT query for status bar
- `DictionarySearchWorker`: `noise_count_ready = pyqtSignal(int)` emitted after each search
- `DictionaryView`: split status bar into result count + project-wide noise count label

### Epic 6B PATCH-02 — Semantic Tooltips

- `LemmaTableModel` col 8 (Noise): tooltip — noise provenance axis
- `LemmaTableModel` col 9 (Entity Class): tooltip — NER class description
- `TranslationManagementTableModel` col 10 (Noise): tooltip — `noise_reason` code in human-readable form
- Helper functions: `_noise_provenance_tooltip()`, `_entity_class_tooltip()`, `_tm_noise_tooltip()`
- Axis isolation enforced by dedicated test

---

## Column Contract — LemmaTableModel

After Epic 6B, the canonical column indices are:

| Index | Header | Editable | Notes |
|-------|--------|----------|-------|
| 0 | UD | — | Study state indicator |
| 1 | Lemma | — | Hebrew text |
| 2 | POS | — | |
| 3 | Freq | — | |
| 4 | Docs | — | |
| 5 | Translation | **yes** | Inline edit |
| 6 | Source | — | |
| 7 | Status | — | |
| 8 | Noise | — | Badge + provenance tooltip (Epic 6B) |
| 9 | Entity Class | — | NER class + description tooltip (Epic 6B) |
| 10 | Last Review | — | *(was col 9 before Epic 6B)* |
| 11 | Niqqud | — | *(was col 10 before Epic 6B)* |
| 12 | Audio | — | *(was col 11 before Epic 6B)* |

**Total: 13 columns.** All other Qt models (TermClusterTableModel, TranslationManagementTableModel, TermCardTableModel, UserDictionaryItemsTableModel) were **not** shifted — their Niqqud column remains at their respective pre-existing indices.

---

## Noise Badge Semantics

### In LemmaTableModel (col 8)

| Badge | Condition | Tooltip |
|-------|-----------|---------|
| `Noise (auto)` | `is_noise=1, noise_source="auto"` | "Automatically classified as noise by NLP pipeline\nDate: YYYY-MM-DD" |
| `Noise (manual)` | `is_noise=1, noise_source="manual"` | "Manually marked as noise\nDate: YYYY-MM-DD" |
| `Valid (auto)` | `is_noise=0, noise_source="auto"` | "Automatically classified as valid by NLP pipeline\nDate: YYYY-MM-DD" |
| `Valid (manual)` | `is_noise=0, noise_source="manual"` | "Manually confirmed as valid\nDate: YYYY-MM-DD" |
| `Noise` | `is_noise=1, noise_source=NULL` | "Noise — source unknown (legacy data)" |
| `Valid` | `is_noise=0, noise_source=NULL` | "Valid — source unknown (legacy data)" |
| *(empty)* | `is_noise=NULL` | "Not yet classified" |

**Date shown only-if-known:** when `noise_updated_at` is NULL, the date line is omitted. Legacy records do not show an empty "Date:" field. This is intentional — absence of provenance metadata is stated explicitly, not left as a blank field that could suggest a bug.

---

## Tooltip Semantics

### Semantic Axes — intentionally separate

Epic 6B surfaces **Axis 1** (noise provenance) as UI tooltips. **Axis 2** (source lifecycle) is computed in the service layer and surfaced in the TM panel (for `term_cluster` entries). It is **not yet surfaced** as a tooltip/badge in Dictionary rows — this is a deliberate gap, not an omission.

| Axis | Where surfaced | Data source |
|------|---------------|-------------|
| Axis 1: Noise provenance | Dictionary col 8 tooltip | `noise_source`, `noise_updated_at` |
| Axis 2: Source lifecycle | TM panel col 14 (term_cluster only) | `source_status` property, `cluster_id`, `promoted_from_cluster_id` |

Surfacing Axis 2 in Dictionary rows would require adding `orphaned_lemma_id` to `LemmaStats` DTO and the search query — this is a tracked future extension.

### Vocabulary — Axis 1 (noise provenance)

- `auto` — NLP pipeline decision
- `manual` — user decision
- `legacy` / `NULL` — pre-Epic 6A record, no provenance stored
- `not yet classified` — `is_noise` is NULL

### Vocabulary — Axis 2 (source lifecycle)

- `linked` — entity still exists in active corpus extraction
- `source_missing` — source was deleted after this entry was created (entry preserved)
- `manual` — created manually, no corpus source link
- `auto_only` — created automatically, no user interaction

---

## Status Bar Semantics

The noise counter in the Dictionary status bar (`Noise: N`) is a **project-wide health metric**.

- It counts `is_noise=1` lemmas for the current project, independent of the active search filter.
- If the filter shows 20 rows and the counter shows 47 — the project has 47 noise lemmas total; only some may appear in the current filter.
- Future extension: a second indicator for noise count *within the current filter* could be added separately, without changing the project-wide metric.

---

## Regression Evidence

### Test coverage added in Epic 6

| File | Tests | What is covered |
|------|-------|----------------|
| `test_epic6a_lemma_provenance.py` | 13 | Schema columns, auto noise_source on create, orphan snapshot, idempotency, R2 guard, compute_source_lifecycle (6 states) |
| `test_epic6b_dictionary_observability.py` | 13 | Column count = 13, Noise badge variants (7 parametrized), Entity Class col, Translation editability (regression), count_noise_lemmas, DTO propagation |
| `test_epic6b_noise_tooltips.py` | 31 | All 7 noise provenance states, date logic, NER class lookup (6 codes + unknown + None), TM noise_reason codes, axis isolation |

### Column index regression tests (cross-model)

`test_cross_view_niqqud_column.py` and `test_cross_view_ud_due_marker.py` lock in column indices for all five Qt models. These tests will fail immediately if any future change shifts column positions unexpectedly.

### Full suite baseline

| Point in time | Passed | Failed |
|---------------|--------|--------|
| Pre-Epic 6 baseline | 1547 | 2 (pre-existing, unrelated) |
| Post-Epic 6B PATCH-02 | 1708 | 0 |

---

## Definition of Done

- [x] Noise provenance stored in DB (noise_source, noise_updated_at)
- [x] Orphaned lemma snapshot before DELETE (orphaned_lemma_id)
- [x] R2 guard: approved user_edit entries not overwritten by MT batch (unless force mode)
- [x] LemmaTableModel: Entity Class col at index 9, column shift correct
- [x] Noise badge in col 8 shows provenance suffix (auto / manual / legacy)
- [x] Status bar: project-wide noise count via DictionarySearchWorker signal
- [x] Noise col tooltip: who set the state, with date when known
- [x] Entity Class col tooltip: human-readable NER class description
- [x] TM Noise col tooltip: noise_reason code in human-readable form
- [x] Semantic axes separated and isolation enforced by test
- [x] Legacy records handled without broken-looking UI (no empty date fields)
- [x] No UI thread violations (all new work via signals)
- [x] 75 new tests added; full suite 1708 passed
- [x] Cross-model column index regression tests updated and passing
- [x] This completion report written
