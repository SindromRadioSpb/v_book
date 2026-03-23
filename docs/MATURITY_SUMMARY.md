# Maturity Summary — HDLE Premium after Epics 4/5/6

> **Date:** 2026-03-24
> **Schema version:** v47 (migrations 043–047)
> **Test suite:** 1708 passed, 0 failed
> **Applies to:** HDLE Premium, post-Epics 4/5/6 delivery wave

---

## What Changed

Three engineering epics (4, 5, 6) were delivered between 2026-02-xx and 2026-03-23. This document summarises what the product can do now that it couldn't do before.

---

## Before Epics 4/5/6

| Area | State |
|------|-------|
| Term Extraction | No reproducibility — same parameters could produce different results across runs |
| Term Metrics | Keyness and weirdness computed on-the-fly but not stored; could not be sorted without recomputation |
| min_freq | Applied at extraction time — changing it required full re-extraction |
| TM Safety | Re-extracting terms silently broke links between term clusters and TM entries |
| Extraction modes | Only one mode: delete everything and re-extract from scratch |
| Dictionary observability | Noise classification visible but no provenance — user couldn't tell if noise was set manually or by the classifier, or when |
| Entity Class | Not surfaced in Dictionary table |
| TM entry preservation | No indicator of whether a TM entry's source cluster still exists |

---

## After Epics 4/5/6

### Epic 4 — Term Extraction Pro

**Reproducibility and informed decision-making.**

- **Extraction runs are reproducible:** Every run stores a `params_hash` — a fingerprint of the parameters used. If you run again with the same settings, the system recognises the run as a valid resume target.
- **Metrics are stored, not recomputed:** Keyness (statistical significance in domain vs. reference) and Weirdness (domain specificity ratio) are stored at extraction time. Sort by keyness or weirdness without re-extracting.
- **Staleness detection:** If the reference corpus changes after extraction, the system warns you that stored keyness/weirdness may be outdated. A "Recalculate" button updates just the metrics without re-extracting clusters.
- **min_doc_freq filter:** Filter clusters by minimum number of documents they appear in (distinct from frequency threshold).
- **Sort presets:** One-click presets for Keyness, Weirdness, Termhood, Frequency.

### Epic 5 — TM Safety & Layered Extraction

**Protect curated work; give precise control over extraction scope.**

- **TM provenance:** Every TM entry created from a term cluster stores a permanent snapshot: which cluster it came from, which extraction run, with what parameters. Even after the cluster is deleted, the entry retains this history.
- **Impact preview:** Before running Full Overwrite, the system shows how many TM entries would lose their cluster link. No silent data loss.
- **Three extraction modes:**
  - *Full Overwrite* — delete all clusters, re-extract from scratch. TM entries preserved.
  - *Merge* — add new clusters without deleting existing ones. Useful for adding a new n-gram layer.
  - *Replace Layer* — delete only a specific n-gram size layer (e.g., bigrams), re-extract just that layer. Other layers and NP chunks untouched.
- **min_freq is now a display-time filter:** Change the frequency threshold instantly without re-extracting. All candidates are stored. The spinner now filters the view, not the database.
- **Hidden count indicator:** When min_freq > 1, the status bar shows how many clusters are below the current threshold.
- **Quick presets:** One-click frequency threshold buttons (All / Common / Strict / High).
- **Freq distribution:** A summary label shows how clusters are distributed across frequency brackets, helping you choose the right threshold.
- **Store hapax toggle:** On large corpora, exclude frequency-1 terms from storage to reduce database bloat.

### Epic 6 — Dictionary Maturity

**Make the database's knowledge visible and trustworthy.**

- **Noise provenance:** Every noise/valid classification now records who set it (NLP pipeline vs. user manual override) and when. Legacy records are clearly labeled "source unknown (legacy data)" — not as an error, but as transparency about data age.
- **Entity Class column:** Named entity recognition results (PER, ORG, GPE, LOC, FAC, MISC) now appear as a dedicated column in the Dictionary table, with hover tooltips explaining each class.
- **Semantic tooltips:** Hover over the Noise column to see the full classification provenance (who, when). Hover over Entity Class to see the full class name.
- **Project-wide noise counter:** The Dictionary status bar shows the total number of noise lemmas in the project, independent of the current search filter — a health metric rather than a search projection.
- **TM entry preservation through cleanup:** When the pipeline removes orphaned lemmas from the corpus, it now snapshots the lemma ID before deletion. TM entries retain evidence of their origin even after the source lemma is gone.
- **Batch Translate safety:** Batch MT translation no longer overwrites TM entries that have been manually edited and approved by the user.

---

## Schema Changes (v42 → v47)

| Migration | Table | Change | Purpose |
|-----------|-------|--------|---------|
| 043 | `term_extract_run` | `+params_hash TEXT` | Reproducibility fingerprint |
| 043 | `term_cluster` | `+best_keyness REAL` + index | Keyness sort support |
| 044 | `term_extract_run` | `+reference_project_id INTEGER` | Reference corpus tracking |
| 045 | `tm_entry` | `+promoted_from_cluster_id INTEGER` | Provenance snapshot |
| 045 | `tm_entry` | `+promoted_at_params_hash TEXT` | Provenance snapshot |
| 045 | `tm_entry` | `+promoted_at_run_id INTEGER` | Provenance snapshot |
| 046 | `term_cluster` | `+ngram_n_set TEXT` + index | Layer-aware extraction modes |
| 047 | `lemma` | `+noise_source TEXT` | Noise provenance |
| 047 | `lemma` | `+noise_updated_at TEXT` | Noise provenance timestamp |
| 047 | `tm_entry` | `+orphaned_lemma_id INTEGER` | Orphan cleanup snapshot |

---

## Test Coverage

- **1708 automated tests**, 0 failures
- 159 epic-specific tests across 13 test files
- Cross-model column regression tests ensure column indices stay stable across epics
- Axis isolation test ensures noise provenance and source lifecycle tooltips never mix content

---

## What Is Not Included

These capabilities were not part of Epics 4/5/6 and remain on the roadmap:

- Import/Export Premium (Iteration 5)
- Performance History dashboard (Iteration 6)
- Batch Translate write-policy full matrix (FILL_EMPTY, OVERWRITE_MT_ONLY modes)
- Translation status column in Dictionary view
- Source lifecycle indicator in Dictionary view (requires separate design — see `CROSS_SURFACE_MATRIX.md`)
