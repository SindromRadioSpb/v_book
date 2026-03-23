# Semantic Contract — HDLE Premium

> **Status:** Normative (approved 2026-03-24)
> **Scope:** All subsystems touching terms, dictionary, translation memory
> **Schema version:** v47
> **Authority:** This document takes precedence over inline descriptions in epic completion reports.

---

## Purpose

This document defines the canonical semantic rules for all persistent data and computed properties in HDLE Premium. It is normative: when code, UI copy, or documentation conflicts with a rule here, **the rule here wins** and the conflicting artifact must be corrected.

---

## Section 1 — Stable vs. Derived Fields

### Rule 1.1: Stable fields are stored in the database
A field is **stable** if it persists between sessions. Stable fields are stored in SQLite tables, have migrations, and are indexed if queried frequently.

Examples of stable fields:
- `lemma.noise_source` — who classified the lemma
- `term_cluster.ngram_n_set` — which n-gram layers produced this cluster
- `tm_entry.promoted_from_cluster_id` — cluster at time of promotion

### Rule 1.2: Derived fields are computed in the service layer
A field is **derived** if it is computed from stable fields at read time. Derived fields are **never stored in the database, never indexed, and never filtered at the SQL layer**.

Examples of derived fields:
- `source_status` — computed from `cluster_id`, `promoted_from_cluster_id` (Epic 5A)
- `source_lifecycle` — computed from `lemma_id`, `orphaned_lemma_id`, `origin` (Epic 6A)
- `noise_badge_label` — computed from `is_noise`, `noise_source` (Epic 6B)

### Rule 1.3: Derived fields live in service methods or model helpers
Location: `app/services/*.py` or `app/ui/models_qt.py` helper functions.
Location must be documented in the relevant epic completion report.

---

## Section 2 — Provenance Semantics

### Rule 2.1: Snapshot fields record state at a point in time
A **snapshot field** captures the value of another field at the moment of a specific operation. After writing, snapshot fields are never updated again.

Snapshot fields in v47:

| Field | Table | Captures | Trigger |
|-------|-------|----------|---------|
| `promoted_from_cluster_id` | `tm_entry` | `cluster_id` at promotion | TM entry created from cluster |
| `promoted_at_params_hash` | `tm_entry` | extraction `params_hash` at promotion | TM entry created from cluster |
| `promoted_at_run_id` | `tm_entry` | `run_id` at promotion | TM entry created from cluster |
| `orphaned_lemma_id` | `tm_entry` | `lemma_id` before orphan cleanup DELETE | `_cleanup_orphaned_lemmas_for_ids()` |

### Rule 2.2: Snapshot fields are plain integers, not foreign keys
Snapshot fields use `INTEGER` with no `REFERENCES` constraint (or `ON DELETE SET NULL`). This is intentional: the referenced row may be deleted, and the snapshot must survive.

Rationale: if a cluster is re-extracted (deleted + recreated), the old `promoted_from_cluster_id` must remain as evidence of the original source.

### Rule 2.3: Noise provenance fields record classifier identity and time
`lemma.noise_source`: who last classified the lemma.
- `"auto"` — NLP classifier (set by `_create_or_get_lemmas()` or reprocess)
- `"manual"` — user override (set by `BulkNoiseUpdateWorker`)
- `NULL` — legacy data (classified before Epic 6A, 2026-03-23)

`lemma.noise_updated_at`: ISO8601 UTC timestamp of last classification. `NULL` for legacy.

### Rule 2.4: "Legacy data" means pre-provenance, not corrupt
A record with `noise_source=NULL` or `noise_updated_at=NULL` is **legacy** — it was created before provenance tracking existed. It is not corrupt or invalid. UI must communicate this clearly (e.g. "source unknown (legacy data)") without implying an error.

---

## Section 3 — Source Lifecycle Semantics

Source lifecycle is modelled along two independent axes. **These axes must never be mixed** in a single badge, tooltip, or filter.

### Axis 1 — Noise Provenance (who/when classified noise/valid)
- **Source:** `lemma.is_noise`, `lemma.noise_source`, `lemma.noise_updated_at`
- **Surface:** Dictionary view, col 8 (Noise badge + tooltip)
- **Question answered:** "Who said this lemma is noise, and when?"
- **States:** `Noise (auto)`, `Noise (manual)`, `Valid (auto)`, `Valid (manual)`, `Noise` (legacy), `Valid` (legacy), *(unclassified)*

### Axis 2 — Source Lifecycle (is the corpus link intact?)
- **Source:** `tm_entry.lemma_id`, `tm_entry.orphaned_lemma_id`, `tm_entry.origin`
- **Surface:** TM panel col (Src ●). Dictionary view — surfaced in PATCH-04 (Next Wave).
- **Question answered:** "Is this entry still linked to an active corpus lemma?"
- **States:** `linked`, `source_missing`, `manual`, `auto_only`

### Rule 3.1: Axis 1 tooltip must not mention corpus links
Noise provenance tooltip shows: who classified, date. Never mentions cluster_id, lemma_id, or corpus linkage.

### Rule 3.2: Axis 2 tooltip must not mention noise classification
Source lifecycle tooltip shows: linkage state, orphaned_lemma_id if applicable. Never mentions is_noise or noise_source.

### Rule 3.3: Axis 2 computed by `DictionaryService.compute_source_lifecycle()`
Signature:
```python
def compute_source_lifecycle(
    lemma_id: int | None,
    orphaned_lemma_id: int | None,
    origin: str | None,
) -> str:  # "linked" | "source_missing" | "manual" | "auto_only"
```

---

## Section 4 — Display-Time vs. Rebuild-Time Semantics

### Rule 4.1: Display-time parameters do not affect stored data
A parameter is **display-time** if changing it requires only a UI refresh (no re-extraction, no DB write).

Display-time parameters (Terms view):
- `min_freq` — shows/hides clusters below threshold (Epic 5C)
- Column sort order — UI-only

### Rule 4.2: Rebuild-time parameters are part of params_hash
A parameter is **rebuild-time** if changing it requires a new extraction run. Rebuild-time parameters are included in `params_hash`.

Rebuild-time parameters in `params_hash` (algo_version v2, Epic 5C):
```python
{
    "algo_version": 2,
    "enable_ngrams": bool,
    "include_np": bool,
    "min_freq": None,       # REMOVED from hash in Epic 5C
    "ngram_ns": list[int],
    "np_max_len": int,
    "store_hapax": bool,    # Added in Epic 5D
}
```

### Rule 4.3: min_doc_freq is rebuild-time; min_freq is display-time
- `min_doc_freq`: extraction-time — how many documents a cluster must appear in. Part of params_hash. Changing requires re-extract.
- `min_freq`: display-time — how many occurrences to show. NOT in params_hash. Changing triggers instant UI refresh.

### Rule 4.4: Staleness warning applies to rebuild-time metrics only
Keyness and weirdness are stored at extraction time from the reference corpus state. If the reference corpus changes after extraction, stored values are stale. The staleness warning in Terms view (Epic 4) applies to stored keyness/weirdness only — not to display-time filters.

---

## Section 5 — Destructive Operation Semantics

### Rule 5.1: "Destructive" means data that cannot be trivially recreated
An operation is destructive if it deletes data that either:
- required user curation (TM entries, manual noise overrides), or
- cannot be exactly reproduced by re-running the pipeline (due to external data changes)

### Rule 5.2: Destructive operations always snapshot before DELETE
Before any destructive DELETE, snapshot fields must be written:

| Operation | Pre-DELETE snapshot |
|-----------|---------------------|
| Full Overwrite (term extraction) | — clusters have no user curation; TM entries preserved via promoted_from_cluster_id |
| Orphan cleanup (lemma DELETE) | `orphaned_lemma_id ← lemma_id` written to all linked `tm_entry` rows |

### Rule 5.3: Full Overwrite preserves TM entries
`Full Overwrite` extraction mode deletes all `term_cluster` and `ngram` rows for a project but **does not delete** `tm_entry` rows. TM entries carry `promoted_from_cluster_id` as permanent evidence of their origin cluster.

### Rule 5.4: Impact preview is mandatory for Full Overwrite when risk is detected
Before executing Full Overwrite, `get_overwrite_impact()` is called. If `linked_tm_entries > 0`, the impact preview dialog must be shown. User must explicitly confirm.

### Rule 5.5: Merge and Replace Layer are non-destructive by design
- **Merge:** adds to existing data only. No DELETE.
- **Replace Layer:** deletes only the target `ngram_n_set` layer. Clusters from other layers survive.

---

## Section 6 — Write-Policy Rules (Batch Translate)

### Rule 6.1: R1 — No silent duplicates
`INSERT OR IGNORE` semantics: if a TM entry for `(project_id, lemma_id)` already exists, the INSERT is silently skipped. No duplicate is created, no error is raised.

### Rule 6.2: R2 — User-approved entries are never overwritten by MT
If `tm_entry.origin = "user_edit"` AND `tm_entry.status = "approved"`, Batch Translate skips the entry.

Exception: `force_global_update=True` (admin-only flag, not exposed in standard UI).

Implementation: `BatchMTTranslateService._write_lemma()` (Epic 6A).

### Rule 6.3: Future write modes are explicitly deferred (not implemented)
The following modes are documented here for future reference but are **not implemented in v47**:
- `FILL_EMPTY` — translate only entries with no existing translation
- `OVERWRITE_MT_ONLY` — overwrite only `origin="mt_auto"` entries
- `OVERWRITE_ALL` — overwrite all entries including user-approved (with explicit warning)

Any implementation of these modes must update this section.

---

## Section 7 — Project-Wide vs. Filtered Counts

### Rule 7.1: Status bar metrics are project-wide
Counts shown in status bars are computed over the entire project, independent of the current search filter.

| Surface | Metric | Source |
|---------|--------|--------|
| Dictionary status bar | Noise count | `DictionaryService.count_noise_lemmas(project_id)` |
| Terms status bar | Hidden by min_freq count | second COUNT without freq filter |

Rationale: status bar counts are **health metrics**, not search projections. Users should see the full picture even when filtered to a subset.

### Rule 7.2: "Found: N" always reflects the current filter
The primary result count ("Found: N") always reflects the current search + filter state. It changes as the user types or adjusts filters.

### Rule 7.3: Hidden count delta is a display-time signal
"Hidden by min freq: N" = `unfiltered_count − filtered_count`. This is a display-time computation emitted via `TermsSearchWorker.count_unfiltered_ready`. It signals the user that more data exists below the current threshold without changing the filter.

---

## Cross-References

| Topic | Canonical source |
|-------|-----------------|
| Noise badge variants (7 states) | `docs/epic6_completion.md` §Column Contract |
| source_lifecycle states (4 states) | `docs/epic5a_completion.md` §source_status + `docs/epic6_completion.md` §Epic 6A |
| params_hash construction | `docs/epic4_term_extraction_pro.md` §params_hash |
| Extraction mode dispatch | `docs/epic5b_extraction_modes.md` §Three Modes |
| min_freq display-time contract | `docs/epic5c_candidate_persistence.md` |
| Cross-surface consistency decisions | `docs/CROSS_SURFACE_MATRIX.md` |
| Canonical UI term definitions | `docs/UI_VOCABULARY.md` |
