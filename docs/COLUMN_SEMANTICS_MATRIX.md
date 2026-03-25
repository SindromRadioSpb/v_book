# Column Semantics Matrix — HDLE Premium

> **Status:** Normative (approved 2026-03-24, updated 2026-03-25)
> **Scope:** Terms view · Dictionary view · Translation Management (TM) panel
> **Schema version:** v51
> **See also:** `docs/SEMANTIC_CONTRACT.md`, `docs/UI_VOCABULARY.md`, `docs/CROSS_SURFACE_MATRIX.md`

---

## Purpose

This document is the canonical reference for what every column in every table surface means,
what backing field it reads from, and what its possible values represent.

It exists to prevent three recurring failure modes:
1. **Same word, different meaning** — "Source" means three different things across surfaces.
2. **Missing entity type** — users cannot tell whether a row is an n-gram or an NP chunk from the UI.
3. **Silent values** — values like `none`, `null`, or empty cell look like errors but are defined states.

Use this document before adding tooltips, renaming columns, or writing column-level tests.

---

## Vocabulary decisions (non-negotiable)

| Term | Canonical meaning | Do NOT use for |
|------|-------------------|----------------|
| **Kind** | Entity type: what kind of linguistic unit this row represents (ngram, np, lemma, term_cluster, surface) | Translation lineage |
| **Source** | Translation lineage: where the translation was obtained (tm, dict, mt_cache, mt, none) | Entity type; source text |
| **Term** / **Source Term** | The Hebrew text being translated (src_text in TM) | Translation lineage |
| **Status** | Workflow / review state of a translation (draft, approved, rejected) | Noise state; run status |
| **Noise** | NLP classifier verdict on whether this unit is noise (not meaningful content) | Status; kind |
| **Origin** | How a TM entry was created (user_edit, import, mt_accept, mt_auto, merge) | Translation lineage source |
| **Src** | TM-panel-only: cluster linkage status (linked / source_cluster_missing / manual) | Kind; Source |

---

## 1. Terms View (`TermClusterTableModel`)

**Row DTO:** `ClusterStats` (app/domain/dto.py)
**Source table:** `term_cluster` JOIN aggregates

| Col | Header | Backing field(s) | Type | Possible values | Semantic meaning | Current tooltip |
|-----|--------|-----------------|------|-----------------|-----------------|-----------------|
| 0 | UD | `in_user_dictionary_count`, `study_state` | int, str\|None | count ≥ 0 | User Dictionary inclusion badge | None (custom brush) |
| 1 | Term | `representative_he` | str | any Hebrew | Representative surface form of the cluster | None |
| 2 | Lemma | `representative_lemma` | str\|None | any Hebrew / None | Base lemma of the cluster representative | None |
| 3 | Freq | `freq_abs` | int | ≥ 0 | Total occurrences in corpus | None ❌ |
| 4 | DocFreq | `doc_freq` | int | ≥ 0 | Number of distinct documents containing term | None ❌ |
| 5 | Members | `members_count` | int | ≥ 1 | Number of surface form variants in cluster | None ❌ |
| 6 | **Kind** | `source_kinds` | str\|None | `ngram` `np` `ngram,np` / None→`?` | **Entity type** — what extraction method produced this cluster | ✓ (added v48) |
| 7 | PMI | `best_pmi` | float\|None | any / None | Pointwise Mutual Information (bigrams only; None for unigrams/NP) | ✓ |
| 8 | LLR | `best_llr` | float\|None | any / None | Log-Likelihood Ratio (bigrams only) | ✓ |
| 9 | Dice | `best_dice` | float\|None | 0–1 / None | Dice coefficient (bigrams only) | ✓ |
| 10 | Weirdness | `weirdness` | float\|None | any / None | Domain specificity vs. reference corpus (>1 = more domain-specific) | Partial ✓ |
| 11 | Keyness | `best_keyness` / `keyness_llr` | float\|None | any / None | LLR-based statistical distinctiveness in domain | Partial ✓ |
| 12 | Termhood | `termhood_score` | float\|None | any / None | Composite: log(Keyness) × log(Weirdness) × log(Freq) | Partial ✓ |
| 13 | Translation | `translation` | str\|None | text / None | Current translation (editable) | None |
| 14 | Source | `translation_source` | str\|None | `tm` `dict` `mt_cache` `mt` `none` | **Translation lineage** — where the translation was obtained. NOT entity type. | ✓ |
| 15 | Status | `translation_status` | str\|None | `approved` `draft` `none` | Translation review state | ✓ |
| 16 | Noise | `is_noise`, `noise_source` | int\|None, str\|None | `Noise (auto)` `Noise (manual)` `Valid (auto)` `Valid (manual)` `Noise` (legacy) `Valid` (legacy) / empty | NLP classifier verdict + who set it | ✓ (v48) |
| 17 | Last Review | `last_grade`, `in_user_dictionary_count` | str\|None, int | grade string / empty | Last spaced-repetition grade (empty if not in UD) | None |
| 18 | Niqqud | `pronunciation_text` | str\|None | text / None | Hebrew vowel diacritics | ✓ |
| 19 | Audio | `audio_status` | str\|None | status string / None | Audio file availability | ✓ |

**Filters:** Kind column is filterable via TermsFilterDialog (Kind section: ngram / np / ngram,np checkboxes; Noise section: 5 composite states). Filter button in toolbar.

**"Source" = none explanation:**
`translation_source = "none"` means no translation has been linked to this cluster yet. It is a defined state, NOT an error. Tooltip must say this explicitly.

---

## 2. Dictionary View (`LemmaTableModel`)

**Row DTO:** `LemmaStats` (app/domain/dto.py)
**Source table:** `lemma` JOIN aggregates

| Col | Header | Backing field(s) | Type | Possible values | Semantic meaning | Current tooltip |
|-----|--------|-----------------|------|-----------------|-----------------|-----------------|
| 0 | UD | `in_user_dictionary_count`, `study_state` | int, str\|None | count ≥ 0 | User Dictionary inclusion badge | None (custom brush) |
| 1 | Lemma | `lemma_text` | str | any Hebrew | Base form (lemma) of the word | None |
| 2 | POS | `pos` | str\|None | noun, verb, adj, etc. | Part of speech tag from NLP pipeline | None ❌ |
| 3 | Frequency | `freq_abs` | int | ≥ 0 | Total occurrences in corpus | None ❌ |
| 4 | Doc Freq | `doc_freq` | int | ≥ 0 | Number of distinct documents containing lemma | None ❌ |
| 5 | Translation | `translation` | str\|None | text / None | Current translation (editable) | None |
| 6 | Source | `translation_source` (from TranslationResult cache) | str | `tm` `dict` `mt_cache` `mt` `none` | **Translation lineage** — same semantics as Terms col 13 | None ❌ |
| 7 | Status | `status` | str | `approved` `draft` `none` `auto` | Translation review state | None ❌ |
| 8 | Noise | `is_noise`, `noise_source` | int\|None, str\|None | Noise(auto/manual) / Valid(auto/manual) / legacy / empty | NLP classifier verdict + provenance | ✓ (Epic 6B) |
| 9 | Entity Class | `entity_class` | str\|None | PER, ORG, GPE, LOC, FAC, MISC / None | NER class from NLP pipeline | ✓ (Epic 6B) |
| 10 | Last Review | `last_grade`, `in_user_dictionary_count` | str\|None, int | grade string / empty | Last spaced-repetition grade | None |
| 11 | Niqqud | `pronunciation_text` | str\|None | text / None | Hebrew vowel diacritics | ✓ |
| 12 | Audio | `audio_status` | str\|None | status string / None | Audio file availability | ✓ |

---

## 3. Translation Management Panel (`TranslationManagementTableModel`)

**Row DTO:** `TMEntryDTO` (app/domain/dto.py)
**Source table:** `tm_entry` JOIN aggregates

| Col | Header | Backing field(s) | Type | Possible values | Semantic meaning | Current tooltip |
|-----|--------|-----------------|------|-----------------|-----------------|-----------------|
| 0 | UD | `in_user_dictionary_count`, `study_state` | int, str\|None | count ≥ 0 | User Dictionary inclusion badge | None (custom brush) |
| 1 | ID | `tm_id` | int | positive int | Internal TM entry identifier | None |
| 2 | Kind | `kind` | str | `lemma` `ngram` `term_cluster` `surface` | **Entity type** — what this TM entry represents | ✓ (v48) |
| 3 | **Term** | `src_text` | str | any Hebrew | **The Hebrew term being translated** (renamed from "Source" in v48 to eliminate name collision) | ✓ (v48) |
| 4 | Translation | `translation` | str | text | Target language translation (editable) | None |
| 5 | Status | `status` | str | `draft` `approved` `rejected` `deprecated` | Translation review workflow state | None ❌ |
| 6 | Scope | `project_id` | int\|None | None → "Global" / int → "Project N" | Whether entry is project-specific or global | ✓ (v48) |
| 7 | Origin | `origin` | str | `user_edit` `import` `mt_accept` `mt_auto` `merge` | How the TM entry was created | ✓ (v48) |
| 8 | Source Ref | `source_ref` | str\|None | ref string / None | Link to originating sentence/document | None |
| 9 | Updated | `updated_at` | str | ISO date | Date of last modification | None |
| 10 | Noise | `is_noise`, `noise_source`, `noise_reason` | int\|None, str\|None, str\|None | `Noise (auto)` `Noise (manual)` `Valid (auto)` `Valid (manual)` / legacy / empty | NLP noise verdict + provenance (Axis 1); noise_reason shown in tooltip as "why" | ✓ (v48) |
| 11 | Last Review | `last_grade`, `in_user_dictionary_count` | str\|None, int | grade string / empty | Last spaced-repetition grade | None |
| 12 | Niqqud | `pronunciation_text` | str\|None | text / None | Hebrew vowel diacritics | ✓ |
| 13 | Audio | `audio_status` | str\|None | status string / None | Audio file availability | ✓ |
| 14 | Src | `source_status` (computed property) | str | `linked` `source_cluster_missing` `manual` | **Cluster linkage state** — only meaningful for `kind=term_cluster`. Green=linked, Red=cluster deleted, Grey=manual entry | Partial (Epic 5A) |

**Filters:** FilterDialog (accessed via "Filters" button) has two sections: Kind (lemma/ngram/term_cluster/surface) and Noise (5 composite states matching the canonical vocabulary). Settings persisted in QSettings.

---

## 4. Cross-surface "Source" disambiguation

"Source" is now unambiguous across surfaces (resolved in v48):

| Surface | Col | Header | Actual meaning |
|---------|-----|--------|----------------|
| Terms | 14 | Source | Translation lineage (`tm`/`dict`/`mt_cache`/`mt`/`none`) |
| Dictionary | 6 | Source | Translation lineage (same semantics as Terms) |
| TM | 3 | **Term** | `src_text` — the Hebrew term being translated (renamed from "Source" in v48) |

**Resolved in v48:** TM col 3 renamed from "Source" → **"Term"** to eliminate the name collision with translation-lineage "Source" in other surfaces.

---

## 5. Silent / misleading values — canonical definitions

| Surface | Column | Value | What it means | What it must NOT look like |
|---------|--------|-------|---------------|--------------------------|
| Terms | Source (col 14) | `none` | No translation has been linked yet | ❌ Not an error / not "broken source" |
| Terms | Source (col 14) | `tm` | Translation came from Translation Memory | |
| Terms | Source (col 14) | `mt_cache` | Translation from previously cached MT result | |
| Terms | Kind (col 6) | `ngram` | Extracted as statistical n-gram | |
| Terms | Kind (col 6) | `np` | Extracted as NLP noun-phrase chunk | |
| Terms | Kind (col 6) | `ngram,np` | Both extraction methods found this cluster | |
| Terms | Kind (col 6) | `?` | source_kinds is NULL (legacy pre-v48 rows) | ❌ Not an error |
| Dictionary | Noise | *(empty)* | Lemma not yet classified | ❌ Not "valid by default" |
| Dictionary | Noise | `Noise` (no suffix) | Legacy record — source unknown (pre-v47) | ❌ Not an error |
| TM | Src (col 14) | ⚫ grey bullet | Entry created manually, no cluster source | ❌ Not an error |
| TM | Src (col 14) | 🔴 red bullet | Source cluster was deleted (e.g., after Full Overwrite) | ❌ Not an error; TM entry is still valid |
| TM | Kind (col 2) | `term_cluster` | TM entry was promoted from a Terms cluster | |
| TM | Kind (col 2) | `lemma` | TM entry linked directly to a Dictionary lemma | |

---

## 6. Entity Kind surfacing — resolved in v48

`term_cluster.source_kinds` is now surfaced as Kind column (col 6) in Terms view.
Values: `ngram`, `np`, `ngram,np` (comma-separated, sorted).
`?` = source_kinds is NULL (legacy rows created before v48 extraction pipeline).

Users can now distinguish:
- A 3-word term that is a **trigram** (n=3, extracted by n-gram extraction) → `ngram`
- A 3-word term that is an **NP chunk** (extracted by NLP noun-phrase parser) → `np`
- A cluster found by both methods → `ngram,np`

Multi-select Kind filter available via TermsFilterDialog (Filters button in Terms toolbar).

---

## 7. Tooltip coverage gaps (prioritised)

❌ = missing, ✓ = present, Partial = present but incomplete

| Priority | Surface | Column | Status |
|----------|---------|--------|--------|
| P1 | Terms | Kind (col 6) | ✓ Added in v48 (header + cell tooltip) |
| P1 | Terms | Source (col 14) | ✓ Added in v48 (explains "none" = unlinked) |
| P1 | TM | Kind (col 2) | ✓ Added in v48 |
| P1 | TM | Term (col 3) | ✓ Renamed + tooltip added in v48 |
| P1 | TM | Scope (col 6) | ✓ Added in v48 |
| P1 | TM | Origin (col 7) | ✓ Added in v48 |
| P1 | Terms | Noise (col 16) | ✓ Added in v48 (who/when) |
| P1 | TM | Noise (col 10) | ✓ Added in v48 (who/when + noise_reason why) |
| P2 | Terms | Freq (col 3) | ❌ No tooltip |
| P2 | Terms | DocFreq (col 4) | ❌ No tooltip |
| P2 | Terms | Members (col 5) | ❌ No tooltip |
| P2 | Terms | PMI/LLR/Dice (col 7-9) | ✓ Added in v48 |
| P2 | Terms | Status (col 15) | ✓ Added in v48 |
| P2 | Dictionary | POS (col 2) | ❌ No tooltip |
| P2 | Dictionary | Source (col 6) | ❌ No tooltip |
| P2 | Dictionary | Status (col 7) | ❌ No tooltip |
| P2 | TM | Status (col 5) | ❌ No tooltip |
| P3 | Terms | Translation (col 13) | ❌ No tooltip (editable column) |
| P3 | All | UD (col 0) | ❌ No tooltip for badge meaning |

---

## 8. Semantic Surfacing Wave — completion status (v51)

| Patch | Scope | Description | Status |
|-------|-------|-------------|--------|
| PATCH-00 | Docs | COLUMN_SEMANTICS_MATRIX.md created | ✓ Done |
| PATCH-01 | Terms + TM | Kind column + TM Source→Term rename + P1 tooltips | ✓ Done (commit 5a9e9e0) |
| PATCH-02..07 | All | Noise provenance unification — schema-backed noise_source axis | ✓ Done (commit 78b6869) |
| — | Docs | This document updated to v48 | ✓ Done |
| migration 048–051 | DB | noise_source backfill across 3 incremental passes; structural db.py fix | ✓ Done (commits 957f53a, 3beb841, af167c9) |
| bugfix | TM service | `propagate_to_entries()` was overwriting `noise_source` with NULL on every bulk action | ✓ Fixed (commit 72e625b) |
| bugfix | TM UI | QMessageBox race — stale search worker overwrote fresh noise_source badges | ✓ Fixed (commit 1ae9884) |
| — | Docs | Normative docs updated to schema v51 | ✓ Done (2026-03-25) |
| Remaining P2 | Terms+Dict | Freq/DocFreq/Members/POS/Status tooltips | ⏳ Future |
