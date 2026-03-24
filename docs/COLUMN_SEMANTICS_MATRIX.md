# Column Semantics Matrix — HDLE Premium

> **Status:** Normative (approved 2026-03-24)
> **Scope:** Terms view · Dictionary view · Translation Management (TM) panel
> **Schema version:** v47
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
| 6 | PMI | `best_pmi` | float\|None | any / None | Pointwise Mutual Information (bigrams only; None for unigrams/NP) | None ❌ |
| 7 | LLR | `best_llr` | float\|None | any / None | Log-Likelihood Ratio (bigrams only) | None ❌ |
| 8 | Dice | `best_dice` | float\|None | 0–1 / None | Dice coefficient (bigrams only) | None ❌ |
| 9 | Weirdness | `weirdness` | float\|None | any / None | Domain specificity vs. reference corpus (>1 = more domain-specific) | Partial ✓ |
| 10 | Keyness | `best_keyness` / `keyness_llr` | float\|None | any / None | LLR-based statistical distinctiveness in domain | Partial ✓ |
| 11 | Termhood | `termhood_score` | float\|None | any / None | Composite: log(Keyness) × log(Weirdness) × log(Freq) | Partial ✓ |
| 12 | Translation | `translation` | str\|None | text / None | Current translation (editable) | None |
| 13 | Source | `translation_source` | str\|None | `tm` `dict` `mt_cache` `mt` `none` | **Translation lineage** — where the translation was obtained. NOT entity type. | None ❌ |
| 14 | Status | `translation_status` | str\|None | `approved` `draft` `none` | Translation review state | None ❌ |
| 15 | Noise | `is_noise`, `noise_source` | int\|None, str\|None | Noise(auto/manual) / Valid(auto/manual) / legacy / empty | NLP classifier verdict + who set it | Partial (Epic 6B) |
| 16 | Last Review | `last_grade`, `in_user_dictionary_count` | str\|None, int | grade string / empty | Last spaced-repetition grade (empty if not in UD) | None |
| 17 | Niqqud | `pronunciation_text` | str\|None | text / None | Hebrew vowel diacritics | ✓ |
| 18 | Audio | `audio_status` | str\|None | status string / None | Audio file availability | ✓ |

**⚠ Missing column — entity Kind:**
`ClusterStats` DTO does not expose `source_kinds` (the `term_cluster.source_kinds` field: `"ngram"`, `"np"`, or comma-separated combination). Without this column, users cannot tell whether a row is an n-gram or NP chunk. This is the primary entity observability gap for Terms view.

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
| 2 | Kind | `kind` | str | `lemma` `ngram` `term_cluster` `surface` | **Entity type** — what this TM entry represents | None ❌ |
| 3 | Source | `src_text` | str | any Hebrew | **The Hebrew term being translated** (NOT translation lineage) | None ❌ — NAME COLLISION: this "Source" = source text, not translation source |
| 4 | Translation | `translation` | str | text | Target language translation (editable) | None |
| 5 | Status | `status` | str | `draft` `approved` `rejected` `deprecated` | Translation review workflow state | None ❌ |
| 6 | Scope | `project_id` | int\|None | None → "Global" / int → "Project N" | Whether entry is project-specific or global | None ❌ |
| 7 | Origin | `origin` | str | `user_edit` `import` `mt_accept` `mt_auto` `merge` | How the TM entry was created | None ❌ |
| 8 | Source Ref | `source_ref` | str\|None | ref string / None | Link to originating sentence/document | None |
| 9 | Updated | `updated_at` | str | ISO date | Date of last modification | None |
| 10 | Noise | `is_noise`, `noise_reason` | int\|None, str\|None | Noise / Valid / empty | NLP noise verdict (axis 1 provenance; note: uses `noise_reason`, NOT `noise_source`) | Partial (Epic 6B) |
| 11 | Last Review | `last_grade`, `in_user_dictionary_count` | str\|None, int | grade string / empty | Last spaced-repetition grade | None |
| 12 | Niqqud | `pronunciation_text` | str\|None | text / None | Hebrew vowel diacritics | ✓ |
| 13 | Audio | `audio_status` | str\|None | status string / None | Audio file availability | ✓ |
| 14 | Src | `source_status` (computed property) | str | `linked` `source_cluster_missing` `manual` | **Cluster linkage state** — only meaningful for `kind=term_cluster`. Green=linked, Red=cluster deleted, Grey=manual entry | Partial (Epic 5A) |

**⚠ Name collision — "Source" (col 3):**
TM col 3 header is "Source" but contains `src_text` (the Hebrew input text). This collides with "Source" in Terms/Dictionary where it means translation lineage. **Canonical fix: rename to "Term"** (the Hebrew term being translated).

**⚠ Missing column — TM Noise provenance suffix:**
TM col 10 shows `noise_reason` in tooltip but NOT `noise_source` (lemma-level field). The `(auto)` / `(manual)` suffix shown in Dictionary is absent in TM. Tracked as PATCH-07 in the Next Wave plan.

---

## 4. Cross-surface "Source" disambiguation

"Source" is currently overloaded across surfaces:

| Surface | Col | Header | Actual meaning |
|---------|-----|--------|----------------|
| Terms | 13 | Source | Translation lineage (`tm`/`dict`/`mt_cache`/`mt`/`none`) |
| Dictionary | 6 | Source | Translation lineage (same semantics as Terms) |
| TM | 3 | Source | `src_text` — the Hebrew term being translated |

**Decision:** TM col 3 "Source" → rename to **"Term"**. Terms/Dictionary "Source" (translation lineage) retains the name but gains a clarifying tooltip.

---

## 5. Silent / misleading values — canonical definitions

| Surface | Column | Value | What it means | What it must NOT look like |
|---------|--------|-------|---------------|--------------------------|
| Terms | Source (col 13) | `none` | No translation has been linked yet | ❌ Not an error / not "broken source" |
| Terms | Source (col 13) | `tm` | Translation came from Translation Memory | |
| Terms | Source (col 13) | `mt_cache` | Translation from previously cached MT result | |
| Terms | — (missing) | — | N/A | ❌ User cannot tell ngram from NP |
| Dictionary | Noise | *(empty)* | Lemma not yet classified | ❌ Not "valid by default" |
| Dictionary | Noise | `Noise` (no suffix) | Legacy record — source unknown (pre-v47) | ❌ Not an error |
| TM | Src (col 14) | ⚫ grey bullet | Entry created manually, no cluster source | ❌ Not an error |
| TM | Src (col 14) | 🔴 red bullet | Source cluster was deleted (e.g., after Full Overwrite) | ❌ Not an error; TM entry is still valid |
| TM | Kind (col 2) | `term_cluster` | TM entry was promoted from a Terms cluster | |
| TM | Kind (col 2) | `lemma` | TM entry linked directly to a Dictionary lemma | |

---

## 6. Entity Kind surfacing gap

**Current state:** Entity Kind (ngram / NP chunk) is stored in `term_cluster.source_kinds` but NOT surfaced in any UI column in Terms view.

**Impact:** Users cannot distinguish:
- A 3-word term that is a **trigram** (n=3, extracted by n-gram extraction)
- A 3-word term that is an **NP chunk** (extracted by NLP noun-phrase parser, any length, independent of n-gram settings)

**Target state (PATCH-01 of Semantic Surfacing Wave):**
- Add `source_kinds: str | None` to `ClusterStats` DTO
- Add a "Kind" column to `TermClusterTableModel` (after Members, before metrics)
- Display values: `n-gram` (for `source_kinds="ngram"`), `NP` (for `source_kinds="np"`), `n-gram+NP` (for mixed)
- Header tooltip: explains the difference between n-gram and NP extraction

---

## 7. Tooltip coverage gaps (prioritised)

❌ = missing, ✓ = present, Partial = present but incomplete

| Priority | Surface | Column | Gap |
|----------|---------|--------|-----|
| P1 | Terms | Source (col 13) | No tooltip; "none" looks like error |
| P1 | Terms | *(missing Kind col)* | Entity type not surfaced at all |
| P1 | TM | Kind (col 2) | No tooltip for lemma/ngram/term_cluster/surface |
| P1 | TM | Source→Term (col 3) | No tooltip; name "Source" collides with translation lineage |
| P1 | TM | Origin (col 7) | No tooltip for user_edit/import/mt_accept/mt_auto/merge |
| P2 | Terms | Freq (col 3) | No tooltip |
| P2 | Terms | DocFreq (col 4) | No tooltip |
| P2 | Terms | Members (col 5) | No tooltip |
| P2 | Terms | PMI/LLR/Dice (col 6-8) | No tooltip (PMI only meaningful for bigrams) |
| P2 | Terms | Status (col 14) | No tooltip for approved/draft/none |
| P2 | Dictionary | POS (col 2) | No tooltip |
| P2 | Dictionary | Source (col 6) | No tooltip |
| P2 | Dictionary | Status (col 7) | No tooltip for approved/draft/none/auto |
| P2 | TM | Status (col 5) | No tooltip for draft/approved/rejected/deprecated |
| P2 | TM | Scope (col 6) | No tooltip for Global vs Project |
| P3 | Terms | Translation (col 12) | No tooltip (editable column) |
| P3 | All | UD (col 0) | No tooltip for badge meaning |

---

## 8. Planned remediation (Semantic Surfacing Wave)

| Patch | Scope | Description |
|-------|-------|-------------|
| PATCH-00 | Docs | This document (COLUMN_SEMANTICS_MATRIX.md) |
| PATCH-01 | Terms | Add Kind column — surface `source_kinds` (ngram/NP/mixed) |
| PATCH-02 | TM | Rename col 3 "Source" → "Term" to eliminate name collision |
| PATCH-03 | All | P1 tooltip hardening: Source(Terms), Kind/Origin/Term(TM) |
| PATCH-04 | All | P2 tooltip hardening: Freq/DocFreq/Members/PMI/LLR/Dice/Status/POS/Scope |
| PATCH-05 | Tests | Column presence + tooltip content tests |
| PATCH-06 | Docs | Update OPERATOR_GUIDE.md, MATURITY_SUMMARY.md, UI_VOCABULARY.md |
