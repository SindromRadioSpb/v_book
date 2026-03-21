# Epic 4: Term Extraction Pro

**Status:** Complete
**Schema:** v43 (migration 043), v44 (migration 044)

---

## Patch Series

| Patch | Status | Description |
|-------|--------|-------------|
| PATCH-01 | ✅ done | Migration 043: params_hash + best_keyness schema |
| PATCH-02 | ✅ done | params_hash gating, include_np/ngram_ns persistence |
| PATCH-03 | ✅ done | 19 tests: hash contract + config persistence |
| fix     | ✅ done | Validation error when ngram_ns empty |
| PATCH-04 | ✅ done | Docs + Bigrams/Trigrams/Keyness/Weirdness tooltips |
| PATCH-05 | ✅ done | _store_termhood_metrics_for_project(), DTO, sortable Keyness col |
| PATCH-06 | ✅ done | 7 tests: best_keyness batch logic, scoping, NULL contract |
| PATCH-07 | ✅ done | Store weirdness at extraction time (same pass as keyness) |
| PATCH-08 | ✅ done | Recalculate Keyness/Weirdness button + staleness indicator |
| PATCH-09 | ✅ done | keyness / weirdness sort presets in preset_combo |
| PATCH-10 | ✅ done | min_doc_freq filter (separate from min_freq_abs) |

---

## Delivered (PATCH-01..06)

### params_hash — Extraction Reproducibility

Every term extraction run stores a `params_hash` in `term_extract_run`.

**Canonical payload** (SHA-256[:16], JSON `sort_keys=True, separators=(',',':')`):

```json
{
  "algo_version": 1,
  "enable_ngrams": true,
  "include_np": false,
  "min_freq": 2,
  "ngram_ns": [2, 3],
  "np_max_len": 5
}
```

- `overwrite` is **not** included — execution mode, not a result parameter.
- `ngram_ns` is always sorted ascending.
- `algo_version` is bumped in `TermExtractionService._TERM_EXTRACT_ALGO_VERSION` when
  extraction logic changes without UI param changes.

**Resume gating:** computed hash must match stored `params_hash`. NULL rows (pre-migration 043)
pass through for backward compat.

---

### N-gram Size Selection (UI)

| Bigrams | Trigrams | `ngram_ns` | Meaning |
|---------|----------|-----------|---------|
| ☑ | ☐ | `(2,)` | bigrams only |
| ☐ | ☑ | `(3,)` | trigrams only |
| ☑ | ☑ | `(2, 3)` | bigrams + trigrams |
| ☐ | ☐ | blocked | validation error shown |

Each size is extracted independently. Persisted via QSettings (`terms_view/ngram_ns_json`).

---

### include_np Persistence (Bug Fix)

`include_np` checkbox was hardcoded to `True` on every view open.
Now saved/restored via QSettings (`terms_view/include_np`).

---

### best_keyness — Stored Keyness Column

**Column:** `term_cluster.best_keyness REAL` (migration 043).

- **NULL** = not computed (no reference corpus at extraction time).
- **0.0** = computed and equals zero.

**When stored:** After `_cluster_terms()` finalization, if `general_corpus_id` is set.

**Algorithm:** LLR (log-likelihood ratio) — same as `_compute_keyness_llr()`.

**Performance:** Batch IN-lookup (1000 keys/batch) + batch UPDATE (500 rows/commit).

**UI:** Keyness column (col 10) prefers `best_keyness` over query-time `keyness_llr`.
Sortable via `MultiSortProxyModel` numeric sort.

---

## Planned (PATCH-07..10)

### PATCH-07 — Store weirdness at extraction time

**Problem:** `term_cluster.weirdness` column exists since M5.1 but is **never populated**.
Only computed at query-time in `_list_clusters_with_termhood()`.

**Solution:** Extend `_store_termhood_metrics_for_project()` (rename from
`_store_best_keyness_for_project`) to store both `best_keyness` and `weirdness` in the same
pass — one batch UPDATE per cluster, no second scan.

**DTO:** `ClusterStats.weirdness` reads from stored column in `list_clusters()`; falls back to
query-time value in `_list_clusters_with_termhood()` if stored is NULL.

**Tests:** mirror PATCH-06 pattern for weirdness.

---

### PATCH-08 — Recalculate Keyness/Weirdness + staleness indicator

**Problem:** When user changes reference corpus, `best_keyness` and `weirdness` are stale
without a full re-extraction.

**Solution:**

1. **Staleness tracking:** Store `reference_project_id` snapshot in `term_extract_run`
   (new column `reference_project_id INTEGER`, migration 044). On Terms view load, compare
   stored snapshot with current `general_corpus_id`. If mismatch → show warning label.

2. **Recalculate button:** Small worker `RecalculateKeynesWorker` (reuses
   `_store_termhood_metrics_for_project()`) — runs only the metrics computation stage
   without re-extracting ngrams/NP/clustering. Progress dialog, cancel support.

**UI:** Warning label: `"⚠ Keyness/Weirdness may be outdated — Recalculate"` (clickable).
Shown only when reference has changed since last extraction.

---

### PATCH-09 — keyness / weirdness sort presets

**Problem:** `preset_combo` has only `freq / strong / balanced / termhood`. Keyness and
Weirdness as primary sort require switching to `termhood` preset (which computes all three
metrics at query-time), slow for large projects.

**Solution:** Add `keyness` and `weirdness` to `preset_combo`. In `list_clusters()`:
- `keyness` → `ORDER BY term_cluster.best_keyness DESC NULLS LAST`
- `weirdness` → `ORDER BY term_cluster.weirdness DESC NULLS LAST`

These use stored columns → pure SQL sort, no Python-side computation.

---

### PATCH-10 — min_doc_freq filter

**Problem:** `Min freq` filters by `freq_abs` (absolute token count). A term appearing
10 times in one document is ranked equally with a term appearing 2 times in 5 documents.
`doc_freq` is a better signal for terminological reliability.

**Solution:** Add `Min doc freq` spin box (range 1–50, default 1) alongside existing
`Min freq`. Persisted via QSettings (`terms_view/min_doc_freq`). Passed to `list_clusters()`
as `min_doc_freq` parameter → `WHERE term_cluster.doc_freq >= :min_doc_freq`.

---

## Schema Changes

### Migration 043 (done)

```sql
ALTER TABLE term_extract_run ADD COLUMN params_hash TEXT;
ALTER TABLE term_cluster ADD COLUMN best_keyness REAL;
CREATE INDEX IF NOT EXISTS idx_term_cluster_keyness
    ON term_cluster(project_id, best_keyness DESC);
```

### Migration 044 (planned — PATCH-08)

```sql
ALTER TABLE term_extract_run ADD COLUMN reference_project_id INTEGER;
```

Stores the `general_corpus_id` snapshot at the time of extraction. Used to detect
staleness when the reference corpus is later changed.

---

## Tooltips

| Element | Tooltip explains |
|---------|-----------------|
| Weirdness col | Domain specificity ratio; >1.0 = more frequent in domain; stored at extraction |
| Keyness col | LLR significance; source (stored/query-time); requires reference corpus |
| Termhood col | Composite: log(Keyness) × log(Weirdness) × log(Freq) |
| Bigrams checkbox | Independent size — bigrams only = 2-word sequences only |
| Trigrams checkbox | Independent size — trigrams only = 3-word sequences only |

---

## Troubleshooting

**"Resume rejected" (params changed):**
params_hash mismatch — previous run used different settings. Fresh run starts automatically.

**best_keyness / weirdness is NULL after extraction:**
No reference corpus configured. Set via Terms view → reference project selector.
Then re-run extraction (or use Recalculate after PATCH-08).

**"⚠ Keyness/Weirdness may be outdated" warning:**
Reference corpus was changed since last extraction. Click "Recalculate" or re-run extraction.

**keyness/weirdness preset shows N/A for all rows:**
Reference corpus not set, or extraction ran before reference was configured.
Set reference → Recalculate.
