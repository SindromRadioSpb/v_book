# Term Extraction Pro — User Guide (Epic 4)

> Relevant for: HDLE Premium, Terms view
> Updated: 2026-03-23

---

## What Epic 4 Delivers

Epic 4 turned the Terms view from a one-shot extraction tool into a **reproducible, measurable, and controllable** terminological workspace.

Before: extract once, see some terms, hope the result was meaningful.
After: track *why* a term ranks where it ranks, compare across reference corpora, know when your metrics are stale, and re-run only what needs to change.

---

## Extraction Parameters

### N-gram Size Selection

Control which multi-word sequences are extracted via the **Bigrams** and **Trigrams** checkboxes:

| Bigrams | Trigrams | Extracted |
|---------|----------|-----------|
| ☑ | ☐ | 2-word sequences only |
| ☐ | ☑ | 3-word sequences only |
| ☑ | ☑ | Both bigrams and trigrams |
| ☐ | ☐ | Blocked — validation error shown |

Each size is extracted independently. Your selection is saved and restored when you reopen the view.

### Include Noun Phrases (NP)

The **Include NPs** checkbox controls whether the NLP pipeline extracts syntactic noun phrases in addition to n-grams. This is independent of bigram/trigram selection — you can have NPs only, n-grams only, or both.

### Min Frequency (min_freq)

The minimum occurrence count a term must have to appear in the table. This is a **display-time filter** — all terms are stored in the database regardless of this threshold. Changing the slider does not re-extract; it only changes which rows are shown.

### Min Document Frequency (Min doc freq)

A separate filter: the minimum number of *documents* a term must appear in. Terms appearing 10 times in one document score the same `freq_abs` as a term appearing 2 times in 5 documents — but very differently on `doc_freq`.

Use `min_doc_freq ≥ 2` to filter out terms that are suspicious domain jargon from a single source document.

---

## Termhood Metrics

### Keyness (LLR)

**What it measures:** How statistically unusual this term is in your domain corpus compared to a general reference corpus. A high keyness score means the term appears much more often here than in general language — a strong signal it is domain-specific terminology.

**Algorithm:** Log-Likelihood Ratio (LLR). Higher = more domain-specific.

**Requires:** A reference corpus (general corpus project) configured in the Terms view. Without a reference corpus, Keyness shows `N/A`.

**When stored:** At the end of each extraction run, if a reference corpus is configured. Stored in `term_cluster.best_keyness`.

### Weirdness

**What it measures:** Domain specificity ratio — `freq_in_domain / freq_in_reference`. A value > 1.0 means the term is proportionally more frequent in your domain than in general language. Values < 1.0 mean the term is underrepresented in your domain.

**When stored:** Same pass as Keyness, at the end of each extraction run.

### Termhood

A composite metric combining Keyness, Weirdness, and frequency:

```
Termhood ≈ log(Keyness) × log(Weirdness) × log(Freq)
```

Used by the **termhood** sort preset. Requires both Keyness and Weirdness to be non-NULL.

### PMI / Dice / LLR (association measures)

For multi-word terms, these measure the association strength between constituent words:

| Metric | Meaning |
|--------|---------|
| PMI | Pointwise Mutual Information — how much more often these words co-occur than by chance |
| Dice | Harmonic mean of relative co-occurrence — balanced between precision and recall |
| LLR | Log-Likelihood Ratio — statistical significance of co-occurrence |

---

## Sort Presets

The **Sort** dropdown (preset_combo) controls what the table is sorted by:

| Preset | Primary sort |
|--------|-------------|
| `freq` | Absolute frequency (most common first) |
| `strong` | PMI (strongest word associations first) |
| `balanced` | Dice score |
| `termhood` | Composite termhood score |
| `keyness` | LLR keyness — requires reference corpus |
| `weirdness` | Weirdness ratio — requires reference corpus |

`keyness` and `weirdness` presets use the stored database columns — pure SQL sort, no Python-side computation, fast even on large projects.

---

## Staleness Warning

If you change the reference corpus after an extraction run, Keyness and Weirdness values in the table are **stale** — they were computed against the old reference.

The Terms view shows a warning label:

```
⚠ Keyness/Weirdness may be outdated — Recalculate
```

Click **Recalculate** to recompute only the metrics (no re-extraction needed). This runs `_store_termhood_metrics_for_project()` in a background worker — fast, cancellable.

The warning disappears after recalculation or after a full re-extraction.

---

## Extraction Reproducibility

Every extraction run stores a **params_hash** — a 16-character SHA-256 fingerprint of the exact parameters used:

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

**What this means for you:** If you try to resume a paused extraction with different settings, the system detects the mismatch and starts a fresh run. Your previous run is preserved and a new one begins — you never silently get a mixed result.

Note: `min_freq` is *not* in the hash because it is a display-time filter, not an extraction parameter. Changing min_freq does not invalidate a run.

---

## Troubleshooting

**Keyness / Weirdness shows N/A for all rows:**
No reference corpus is configured. Go to the Terms view reference selector and choose a general corpus project. Then click **Recalculate** or run a new extraction.

**"⚠ Keyness/Weirdness may be outdated":**
You changed the reference corpus since the last extraction. Click **Recalculate** — no need to re-run the full extraction.

**Keyness / Weirdness is NULL after recalculation:**
The reference corpus has no processed documents, or it is the same project as the target (self-comparison produces undefined keyness).

**Terms I expected are not showing:**
Check `min_freq` and `min_doc_freq` sliders — they may be filtering out your terms. Reduce them to 1 to see all stored candidates.

**Extraction rejected my Resume — "params changed":**
The extraction parameters changed since the last run (different n-gram sizes, NP setting, etc.). A fresh run was started automatically. The previous run's data is preserved in `term_extract_run` history.

**The Termhood column shows N/A:**
Termhood requires both Keyness and Weirdness. Configure a reference corpus and run extraction (or recalculate).
