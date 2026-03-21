# Epic 4: Term Extraction Pro

**Status:** In progress
**Schema:** v43 (migration 043)

---

## What Changed

### params_hash — Extraction Reproducibility

Every term extraction run now stores a `params_hash` in `term_extract_run`.

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

- `overwrite` is **not** included — it is an execution mode, not a result parameter.
- `ngram_ns` is always sorted ascending.
- `algo_version` is bumped in `TermExtractionService._TERM_EXTRACT_ALGO_VERSION` when
  extraction logic changes in a way that invalidates old results without changing UI params.

**Resume gating:** When resuming a staged run, the computed hash must match the stored
`params_hash`. Old rows (NULL hash, pre-migration 043) pass through for backward compat.

---

### N-gram Size Selection (UI)

**Before:** `ngram_ns=(2, 3)` hardcoded.

**After:** Two independent checkboxes in the extraction controls:

| Bigrams | Trigrams | `ngram_ns` | Meaning |
|---------|----------|-----------|---------|
| ☑ | ☐ | `(2,)` | bigrams only |
| ☐ | ☑ | `(3,)` | trigrams only |
| ☑ | ☑ | `(2, 3)` | bigrams + trigrams |
| ☐ | ☐ | blocked | validation error shown |

Each size is extracted independently — trigrams-only extracts **only** 3-word sequences,
not "trigrams plus lower orders". Persisted via QSettings (`terms_view/ngram_ns_json`).

---

### include_np Persistence (Bug Fix)

`include_np` checkbox was hardcoded to `True` on every view open.
Now it is saved/restored via QSettings (`terms_view/include_np`).

---

### best_keyness — Stored Keyness Column

**New column:** `term_cluster.best_keyness REAL` (migration 043).

- **NULL** = not computed (reference corpus not configured at extraction time).
- **0.0** = computed and equals zero (term equally distributed between domain and reference).

**When stored:** At the end of term extraction finalization, if a reference corpus is
configured for the project (`dict_project.general_corpus_id`).

**Algorithm:** LLR (log-likelihood ratio) keyness — same formula as `_compute_keyness_llr()`
used by the `termhood` query-time preset.

**Performance:** Batch lookup (1000 canonical keys per IN query) + batch UPDATE (500 rows per
commit). Avoids N+1 queries that the query-time path uses.

**UI:** The Keyness column (col 10 in Terms table) prefers `best_keyness` (stored) over
`keyness_llr` (query-time). The column is sortable via `MultiSortProxyModel` numeric sort.

---

## Tooltips

| Column | Tooltip explains |
|--------|-----------------|
| Weirdness | Domain specificity ratio vs reference; >1.0 = more frequent in domain |
| Keyness | LLR statistical significance; source (stored/query-time) shown |
| Termhood | Composite score used by `termhood` preset |
| Bigrams checkbox | Independent size; Bigrams only = 2-word sequences only |
| Trigrams checkbox | Independent size; Trigrams only = 3-word sequences only |

---

## Index

```sql
CREATE INDEX idx_term_cluster_keyness ON term_cluster(project_id, best_keyness DESC);
```

Accepted as sufficient for Epic 4. Revisit if Terms view adds additional filter conditions
(is_noise, curation_status) that would benefit from a composite index.

---

## Troubleshooting

**"Resume rejected" (params changed):**
Not an error — params_hash mismatch means a previous run used different settings.
The UI will start a fresh run automatically. Old staged data is left in `term_extract_accumulator`
until the new run's `overwrite=True` clears existing terms.

**best_keyness is NULL after extraction:**
No reference corpus is configured for this project.
Set one via: Terms view → reference project selector → select a project.
Then re-run extraction.

**Keyness shows stale value after changing reference corpus:**
`best_keyness` is stored at extraction time. Re-run extraction to update stored values.
The query-time `termhood` preset always computes fresh values against the current reference.

---

## Schema Changes (migration 043)

```sql
ALTER TABLE term_extract_run ADD COLUMN params_hash TEXT;
ALTER TABLE term_cluster ADD COLUMN best_keyness REAL;
CREATE INDEX IF NOT EXISTS idx_term_cluster_keyness
    ON term_cluster(project_id, best_keyness DESC);
```

Migration is additive — no data loss, backward-compatible with existing rows.
