# Operator Guide — HDLE Premium

> **Version:** post-Epics 4/5/6 (schema v47)
> **Audience:** Advanced users, power operators, team leads
> **Date:** 2026-03-24

This guide explains the semantics of the subsystems introduced in Epics 4/5/6. It complements the user-facing guides (`epic4_user_guide.md`, `epic5d_ux_guide.md`, `epic6_dictionary_guide.md`) with more depth on what the system is doing and why.

---

## 1. Understanding Term Extraction Runs

### Params Hash

Every extraction run stores a `params_hash` — a 16-character fingerprint of the parameters that affect output. When you click Extract again with the same settings, the system checks whether the new hash matches the stored one. If it matches, the run can be resumed from its last checkpoint.

**What is included in params_hash:**
- `algo_version` (currently v2)
- `enable_ngrams` (yes/no)
- `include_np` (yes/no)
- `ngram_ns` (e.g., [2, 3])
- `np_max_len`
- `store_hapax` (yes/no)

**What is NOT included:**
- `min_freq` — this is a display-time filter, not an extraction parameter
- `overwrite` — execution mode, not output-affecting

**Practical consequence:** You can freely change `min_freq` between extraction runs without invalidating your checkpoint. Changing `algo_version`, `enable_ngrams`, `ngram_ns`, or `store_hapax` creates a new run.

### Keyness and Weirdness Staleness

Keyness (Log-Likelihood Ratio against reference corpus) and Weirdness (domain specificity ratio) are stored at extraction time. If you later change the reference corpus or update it, the stored values no longer reflect the current reference. The staleness warning in Terms view alerts you to this.

**What to do:**
- Click "Recalculate" — this updates stored metrics without re-extracting clusters.
- Recalculate is fast (no corpus re-scan needed).
- After recalculate, the staleness warning disappears.

---

## 2. Choosing Extraction Mode

### Full Overwrite
**When to use:** First extraction, or when you want to completely rebuild from current corpus state.

**What it deletes:** All `term_cluster` and ngram rows for the project.

**What it preserves:** TM entries. Every TM entry retains `promoted_from_cluster_id` — a permanent record of which cluster it came from. Even after Full Overwrite, you can see that a TM entry was originally based on cluster N.

**Before running:** The system shows an impact preview if linked TM entries exist. This is informational — TM entries are preserved regardless.

### Merge
**When to use:** You've already extracted bigrams and want to add trigrams without losing existing work.

**What it does:** Adds new clusters and n-grams. Never deletes existing data. If a new cluster has the same `canonical_key` as an existing one, new members are linked to the existing cluster.

**Limitation:** Frequencies in existing clusters are not updated (additive-only).

### Replace Layer
**When to use:** You want to re-extract bigrams specifically, without touching trigrams, NPs, or manually curated data.

**What it deletes:** Only clusters with `ngram_n_set = "[2]"` (for bigrams), etc. Clusters from other layers survive.

**Limitation:** NP layer cannot be replaced individually (NP-only re-run is not supported; use Merge instead).

---

## 3. Reading Dictionary Provenance

### Noise Column

The Noise column shows two things:
1. **Classification result:** Noise or Valid
2. **Provenance suffix:** (auto) or (manual) — who set it

| What you see | What it means |
|-------------|---------------|
| `Noise (auto)` | NLP pipeline classified this as noise during processing |
| `Noise (manual)` | User explicitly marked this as noise |
| `Valid (auto)` | NLP pipeline classified this as content-bearing |
| `Valid (manual)` | User explicitly confirmed this as valid |
| `Noise` | Legacy record — classified before provenance tracking (pre-2026-03-23). Source unknown. |
| `Valid` | Legacy record — same as above |
| *(empty)* | Not yet classified |

**Hover for details:** The tooltip shows the full provenance (who, when). For legacy records, it says "source unknown (legacy data)" — this is correct and expected, not a bug.

### Noise Counter in Status Bar

`Noise: N` shows the total number of noise lemmas in the **entire project**, regardless of any search filter you have active. This is a health metric: you always see the full picture.

This counter does NOT change when you type in the search box or apply filters.

### Entity Class Column

Named Entity Recognition results. Common codes:

| Code | Meaning |
|------|---------|
| PER | Person name |
| ORG | Organization |
| GPE | Geo-political entity (country, city, etc.) |
| LOC | Location (non-geo-political) |
| FAC | Facility (building, airport, etc.) |
| MISC | Miscellaneous named entity |

Empty cell = no named entity detected for this lemma.

---

## 4. TM Entry Provenance

### The Src Column (●)

The Src column shows the relationship between a TM entry and its source term cluster:

| Indicator | Meaning |
|-----------|---------|
| ● green | Entry is linked to an active cluster |
| ● red | Source cluster was deleted (e.g., after Full Overwrite); entry preserved |
| ● grey | Entry was created manually — no cluster source |

**When you see red:** This is not an error. The TM entry's translation is still valid and will still be used. The red indicator just means the source terminology cluster no longer exists (typically because you re-extracted with different parameters). The entry retains `promoted_from_cluster_id` as a permanent record of where it came from.

**Hover for details:** The tooltip shows the cluster ID that the entry was promoted from, and the params_hash of the extraction run at promotion time.

### Batch Translate Safety

Batch MT translation respects user curation:
- Entries with `origin = "user_edit"` AND `status = "approved"` are **never overwritten** by Batch Translate.
- This protects your manually reviewed translations from being overwritten by machine translation.

---

## 5. Handling Legacy Data

Records created before schema v47 (2026-03-23) lack provenance metadata:
- Lemmas without `noise_source` show "Noise" / "Valid" badges without suffix
- Hover tooltips say "source unknown (legacy data)"
- TM entries without `orphaned_lemma_id` do not show the red "source missing" state

**What to do:** Nothing is required. Legacy records work correctly; they just lack the provenance information introduced in Epic 6. As you reprocess documents, new lemmas will get proper provenance.

---

## 6. Operational Checks

### After Full Overwrite
1. Verify TM entries are still present (Src col should be ● red for previously linked entries — this is correct)
2. Run "Recalculate" if you want fresh keyness/weirdness values against the current reference corpus

### After Reprocessing Documents
1. Open Dictionary — noise badges should now show "(auto)" suffix for reprocessed lemmas
2. Status bar noise count may change — this is expected as the classifier re-evaluates lemmas

### After Batch Translate
1. Check that user-approved entries were not overwritten (Src col ● green + Status = Approved)
2. If you suspect an overwrite, filter by `status = approved` and check translation values against your records

---

## 7. Quick Reference — Important Numbers

| Metric | Value | Source |
|--------|-------|--------|
| Schema version | v47 | Confirmed at startup in logs |
| algo_version (term extraction) | v2 | `TERM_EXTRACT_ALGO_VERSION` constant |
| Test suite | 1708 passed, 0 failed | `pytest -v` |
| max query latency (terms list) | < 3ms | Epic 5D perf audit (synthetic data) |
| max query latency (count) | < 2ms | Epic 5D perf audit (synthetic data) |
