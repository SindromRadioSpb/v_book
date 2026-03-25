# Canonical UI Vocabulary — HDLE Premium

> **Status:** Normative (approved 2026-03-24, updated 2026-03-25)
> **Scope:** All UI text, tooltip copy, dialog messages, log messages, docs
> **Schema version:** v51
> **See also:** `docs/SEMANTIC_CONTRACT.md`, `docs/CROSS_SURFACE_MATRIX.md`

---

## Purpose

One term → one meaning. This vocabulary is the authoritative reference for UI copy writers, developers, and documentation authors. When adding new UI text, look up the appropriate term here first. Do not invent synonyms for established terms.

---

## Core Terms

### Noise
**Definition:** A linguistic unit classified as not useful for translation — typically punctuation-only, number-only, very short fragments, or other non-content tokens.

**Scope:** Dictionary view (`lemma.is_noise`), Terms view (`term_cluster.is_noise`), TM panel (`tm_entry.is_noise`). All three tables have `noise_source` since schema v48.

**Canonical noise status vocabulary (all surfaces, v48):**

| Status string | `is_noise` | `noise_source` | Meaning |
|---------------|-----------|----------------|---------|
| `Noise (auto)` | 1 | `"auto"` | Classified as noise by NLP pipeline |
| `Noise (manual)` | 1 | `"manual"` | User manually marked as noise |
| `Valid (auto)` | 0 | `"auto"` | Classified as valid by NLP pipeline |
| `Valid (manual)` | 0 | `"manual"` | User manually confirmed as valid |
| `Noise` (no suffix) | 1 | NULL | Legacy noise record (pre-v48) |
| `Valid` (no suffix) | 0 | NULL | Legacy valid record (pre-v48) |
| *(empty)* | NULL | NULL | Not yet classified (unclassified) |

**Usage in UI:**
- Badge in Noise column: one of the 7 states above
- Multi-select Noise filter in FilterDialog (Dictionary + TM) / TermsFilterDialog (Terms): 5 options — `noise_auto`, `noise_manual`, `valid_auto`, `valid_manual`, `unclassified`
- Status bar: "Noise: N" (project-wide count of `is_noise=1` rows, independent of filter)

**Not to be confused with:**
- "Invalid" — not a synonym; "noise" is a specific classifier output, not a judgment of quality
- "Rejected" — rejection is a TM entry status set by the user; noise is a lemma-level classifier output

---

### Valid
**Definition:** A linguistic unit classified as content-bearing — potentially useful for translation or study.

**Scope:** Dictionary view (`lemma.is_noise=0`), Terms view (`term_cluster.is_noise=0`), TM panel (`tm_entry.is_noise=0`).

**Usage in UI:**
- Badge: "Valid" (state), "Valid (auto)", "Valid (manual)"

**Not to be confused with:**
- "Approved" — see below; approval is user-level on TM entries; "Valid" is classifier-level on lemmas
- "Correct" — "Valid" makes no claim about translation accuracy

---

### Approved
**Definition:** A TM entry whose translation has been explicitly confirmed as correct by the user.

**Scope:** TM panel (`tm_entry.status = 'approved'`).

**Usage in UI:**
- Status column: "Approved"
- Guard messaging: "This entry is user-approved and will not be overwritten automatically"

**Not to be confused with:**
- "Valid" — see above

---

### Auto
**Definition:** A classification or value set by an automated process (NLP classifier, MT engine, extraction pipeline) without user involvement.

**Scope:** Noise provenance (`noise_source = "auto"`), TM entry origin (`origin = "mt_auto"`).

**Usage in UI:**
- Badge suffix: "Noise (auto)", "Valid (auto)"
- Tooltip: "Automatically classified by NLP pipeline"

---

### Manual
**Definition:** A classification or value set by an explicit user action.

**Scope:** Noise provenance (`noise_source = "manual"`), TM entry origin (`origin = "user_edit"`, `"manual"`).

**Usage in UI:**
- Badge suffix: "Noise (manual)", "Valid (manual)"
- Tooltip: "Manually marked by user"

---

### Legacy Data
**Definition:** Records created before the provenance tracking system was introduced (before schema v48 for `term_cluster`/`tm_entry`, before v47 for `lemma`). These records have valid classification data (`is_noise`, translation, etc.) but lack provenance metadata (`noise_source`).

**Scope:** Any record with `noise_source = NULL`.

**Usage in UI:**
- Badge: "Noise" (no suffix), "Valid" (no suffix)
- Tooltip: "source unknown (legacy data)"
- Never show an empty field for date — omit the date line entirely

**Important:** Legacy data is not corrupt. Do not display it as an error or warning.

**Note on schema v48–v51 backfill:** All `is_noise IS NOT NULL` rows in fully migrated
databases (schema ≥ v51) should have `noise_source` populated. Any remaining
`noise_source=NULL` rows are either: (a) unclassified (`is_noise=NULL`), or (b) created
by a code path that did not set `noise_source` — treat these as legacy data.

---

### Source Missing
**Definition (Dictionary):** A TM entry whose source lemma was deleted during orphan cleanup. The entry is preserved with `orphaned_lemma_id` as evidence. The corpus link is broken but the translation remains valid.

**Scope:** Dictionary view — source_lifecycle state (`source_missing`), surfaced in PATCH-04.

**Usage in UI:**
- Lifecycle col ●: red
- Tooltip: "Source lemma was removed from corpus — entry preserved (lemma ID: N)"

**Not to be confused with:**
- "Source Cluster Missing" — see below

---

### Source Cluster Missing
**Definition (TM panel):** A TM entry whose source term cluster was deleted during re-extraction. The entry is preserved with `promoted_from_cluster_id` as evidence. The cluster link is broken but the translation remains valid.

**Scope:** TM panel — source_status state (`source_cluster_missing`), Src col ●.

**Usage in UI:**
- Src col ●: red
- Tooltip: "Source cluster was removed — entry preserved (cluster ID: N)"

---

### Hidden by Filter
**Definition:** Items that exist in the database but are excluded from the current view by a display-time filter. They are not deleted; changing the filter reveals them.

**Scope:** Terms view — hidden by `min_freq` threshold.

**Usage in UI:**
- Status bar: "Hidden by min freq: N"
- Tooltip on spinner: "Display-time filter only. All candidates stored. Change freely."

**Not to be confused with:**
- Filtered out by search text — that is a search result, not a hidden count

---

### Project-Wide Count
**Definition:** A metric computed over all items in a project, independent of the current search filter or display settings.

**Scope:** Dictionary status bar ("Noise: N").

**Usage in UI:**
- Always shown without filter qualification
- Does not change when user types in search box or adjusts display filters

**Not to be confused with:**
- "Found: N" — which always reflects the current filter

---

### Recalculate
**Definition:** Recompute stored metrics (keyness, weirdness) from the current reference corpus, without re-extracting term clusters. Faster than Rebuild. Does not change which clusters exist.

**Scope:** Terms view — Recalculate button (Epic 4).

**Usage in UI:**
- Button label: "Recalculate"
- Progress: "Recalculating keyness / weirdness…"

---

### Rebuild / Full Overwrite
**Definition:** Delete all existing term clusters and n-gram data for the project, then run extraction from scratch. Destructive at the cluster level; TM entries are preserved via provenance snapshot.

**Scope:** Terms view — "Full Overwrite" mode in extraction mode combo.

**Usage in UI:**
- Mode label: "Full Overwrite"
- Impact dialog: "This will delete N clusters. N linked TM entries will be preserved."

**Not to be confused with:**
- "Recalculate" — which only updates stored metrics, not clusters
- "Replace Layer" — which deletes only one n-gram layer

---

### Reprocess
**Definition:** Re-run the NLP pipeline on document text — re-lemmatize, re-classify noise, re-detect entities. May update `noise_source` to "auto" and `noise_updated_at`. Does not delete TM entries.

**Scope:** Used in background documentation; not yet exposed as an explicit UI action in v47.

**Usage:** Reserve this term for NLP pipeline re-runs. Do not use "Reprocess" as a synonym for extraction or re-extraction.

---

### Replace Layer
**Definition:** Delete only the term clusters belonging to a specific n-gram size layer (`ngram_n_set`), then re-extract that layer. Other layers and NP chunks are preserved.

**Scope:** Terms view — "Replace Layer" mode in extraction mode combo (Epic 5B).

**Usage in UI:**
- Mode label: "Replace Layer"
- Scope clarification: shows which layer (e.g., "Replacing bigrams [2]")

---

### Merge
**Definition:** Run extraction in additive mode — new clusters and n-grams are added; existing data is not deleted. Existing clusters with matching `canonical_key` receive new members.

**Scope:** Terms view — "Merge" mode in extraction mode combo (Epic 5B).

**Usage in UI:**
- Mode label: "Merge"

---

### Linked (source state)
**Definition:** An entry or record that has an active connection to its source object (cluster, lemma). The source still exists in the database.

**Scope:**
- TM panel: `source_status = "linked"` (cluster exists)
- Dictionary: `source_lifecycle = "linked"` (lemma exists) — PATCH-04

**Usage in UI:**
- Src / Lifecycle col ●: green

---

### Freq Distribution
**Definition:** A summary of how term clusters are distributed across frequency brackets: freq=1, freq=2–4, freq=5–9, freq=10+. Used in Terms view to help users choose `min_freq` threshold.

**Scope:** Terms view status area (Epic 5D).

**Usage in UI:**
- Label: "Freq dist: 1→245  2–4→183  5–9→91  10+→34"

---

### Params Hash
**Definition:** A 16-character SHA-256 prefix that uniquely identifies a set of extraction parameters. Used to detect whether a new run is compatible with a saved checkpoint (resume gating).

**Scope:** Terms view, run persistence layer (Epic 4).

**Usage in UI:**
- Not shown to users in normal operation
- Shown in TM entry tooltip (Src col): "Extracted with params: abc123..."
- Log message on mismatch: "params changed: resume not valid"

---

## Terms NOT to Use (deprecated or ambiguous)

| Avoid | Use instead | Reason |
|-------|-------------|--------|
| "Invalid" | "Noise" | "Invalid" implies user judgment; "Noise" is a classifier output |
| "Broken link" | "Source missing" / "Source cluster missing" | Too generic; doesn't communicate preservation |
| "Deleted" (for lemma in tooltips) | "Removed from corpus" | "Deleted" implies user intent; cleanup is automated |
| "Stale" (for general data) | "Stale keyness/weirdness" | Reserve "stale" specifically for stored keyness/weirdness vs. reference corpus drift |
| "Re-extract" (button label) | "Full Overwrite" / "Rebuild" | Ambiguous about scope and destructiveness |
| "Recalculate" (for full extraction) | "Full Overwrite" | "Recalculate" is specifically for metric updates without cluster changes |
| "Source" (TM col 3 header) | "Term" | Renamed in v48; "Source" in TM was colliding with translation-lineage "Source" |
| "n-gram+NP" / "ngram+np" | "ngram,np" | Canonical separator is comma-sorted; `+` was a display bug in v47 tooltips |
