# Cross-Surface Consistency Matrix

> **Status:** Normative (approved 2026-03-24)
> **Scope:** Terms view · Dictionary view · Translation Memory (TM) panel
> **Schema version:** v47
> **See also:** `docs/SEMANTIC_CONTRACT.md`, `docs/UI_VOCABULARY.md`

---

## Purpose

This document maps concepts across the three main data surfaces (Terms, Dictionary, TM) and records explicit decisions for each divergence. When a concept is handled differently across surfaces, the divergence is either:

- **LEGITIMATE** — different surfaces have genuinely different models; document it
- **ALIGN** — surfaces should use the same pattern; document the target state
- **TARGETED POLISH** — minor wording inconsistency; fix in PATCH-04 or doc correction

---

## Concept 1 — Noise

| Aspect | Terms view | Dictionary view | TM panel |
|--------|-----------|-----------------|----------|
| Field | No noise field on `term_cluster` | `lemma.is_noise` (0/1/NULL) | `tm_entry.is_noise` (0/1/NULL) |
| Provenance | N/A | `noise_source` (auto/manual/NULL) | `noise_reason` code (NOISE_PUNCT_ONLY, etc.) |
| Badge | None | "Noise (auto)", "Noise (manual)", "Noise" (legacy) | Noise badge in TM panel |
| Tooltip | N/A | Noise provenance tooltip (who/when) | `noise_reason` code → human-readable |
| Filter | None | Hide Noise checkbox | Hide Noise checkbox |

**Decision: LEGITIMATE DIVERGENCE**

Noise in Dictionary = NLP classifier result on lemma (word-level).
Noise in TM = entry-level flag, often inherited from lemma or set by pipeline.
Different data sources, different provenance models. Do not force unification.

Action: Document both in `docs/UI_VOCABULARY.md` with explicit scoping.

---

## Concept 2 — Source / Provenance

| Aspect | Terms view | Dictionary view | TM panel |
|--------|-----------|-----------------|----------|
| Concept | Extraction run (params_hash, algo_version) | `source_lifecycle` (corpus link state) — **NOT SURFACED** | `source_status` (cluster link state) — Src col (●) |
| Field | `term_extract_run.params_hash`, `term_cluster.ngram_n_set` | `lemma_id`, `orphaned_lemma_id`, `origin` | `cluster_id`, `promoted_from_cluster_id` |
| UI indicator | Staleness warning label | *(none — PATCH-04 target)* | Src col ● (green/red/grey) |
| Tooltip | Staleness detail | *(none — PATCH-04 target)* | `promoted_from_cluster_id` + `params_hash` |

**Decision: DEFERRED — semantic mismatch confirmed by code audit**

`source_lifecycle` is a **TM entry** concept. It answers: "Does this TM entry's source lemma still exist?" The function `compute_source_lifecycle()` takes `tm_entry.lemma_id`, `tm_entry.orphaned_lemma_id`, `tm_entry.origin` as inputs.

Dictionary view shows **lemmas**. If a lemma is visible in Dictionary view, it EXISTS in the database. Therefore:
- Any TM entry linked to this lemma has `lemma_id = this_lemma_id` (still set)
- `source_lifecycle` for that TM entry would always be `"linked"`
- The `source_missing` state only appears for TM entries whose lemma was deleted — but deleted lemmas do not appear in Dictionary view

To surface `source_lifecycle` in Dictionary view, we would need to:
1. Add `orphaned_lemma_id` and `origin` (TM entry fields) to `LemmaStats` DTO
2. Add a LEFT OUTER JOIN to `tm_entry` in `search_lemmas()` query (complex, multiple TM entries per lemma)
3. Accept that the column would always show "linked" for every visible lemma

This does not provide user value. The TM panel (which shows TM entries, including detached ones) is the correct surface for `source_lifecycle`.

**What would be useful in a future extension (outside this wave):**
- A column in Dictionary view showing "translation status" (has translation / missing / MT-only / approved)
- This is a different concept from `source_lifecycle` and needs its own design

**Next Wave PATCH-04 is therefore a no-code patch.** The CROSS_SURFACE_MATRIX decision is updated here. The memory note `project_epic6_source_lifecycle_status.md` is updated to reflect this conclusion.

---

## Concept 3 — Status

| Aspect | Terms view | Dictionary view | TM panel |
|--------|-----------|-----------------|----------|
| Term | "Run status" (implicit) | No explicit status column | `tm_entry.status` |
| Values | Extraction run: running / complete / failed | N/A | approved / rejected / draft |
| UI surface | Progress dialog during extraction | N/A | Status column |
| User can change | No (read-only run state) | N/A | Yes (inline or via action) |

**Decision: LEGITIMATE DIVERGENCE**

"Status" means three different things across surfaces. No unification needed. The word "status" must be qualified in context: "run status", "entry status", "lemma status".

Action: `docs/UI_VOCABULARY.md` must define each scoped variant separately.

---

## Concept 4 — Valid / Approved

| Aspect | Terms view | Dictionary view | TM panel |
|--------|-----------|-----------------|----------|
| Term | Not used | "Valid (auto)" / "Valid (manual)" badge | "Approved" |
| Meaning | N/A | NLP classifier says not-noise (is_noise=0) | User explicitly confirmed this translation |
| Source | N/A | `is_noise=0, noise_source` | `tm_entry.status='approved'` |
| Set by | N/A | NLP classifier or user manual override | User action |

**Decision: LEGITIMATE DIVERGENCE, DOCUMENT TO PREVENT CONFUSION**

"Valid" = NLP classifier says this lemma is not noise.
"Approved" = user said this translation is correct.

These are different concepts on different objects (lemma vs. TM entry). However, a user could confuse them ("valid" might sound like user-approved).

Action: `docs/UI_VOCABULARY.md` must define both with explicit "not to be confused with" note. Badge label "Valid" is correct and should not be changed.

---

## Concept 5 — Hidden Counts

| Aspect | Terms view | Dictionary view | TM panel |
|--------|-----------|-----------------|----------|
| Mechanism | "Hidden by min freq: N" in status bar | None | None |
| Trigger | When `unfiltered_count > filtered_count` (min_freq > 1) | N/A | N/A |
| Signal type | `TermsSearchWorker.count_unfiltered_ready` | — | — |

**Decision: LEGITIMATE ASYMMETRY**

Hidden counts in Terms are a direct consequence of the `min_freq` display-time filter (Epic 5C/5D). Dictionary and TM panel do not have display-time frequency filters of this kind. No action needed.

Note: Dictionary view does have noise filter (Hide Noise checkbox) but it doesn't expose a "hidden count" because the count of noise lemmas is already shown project-wide in the status bar.

---

## Concept 6 — Project-Wide vs. Filtered Counts in Status Bar

| Aspect | Terms view | Dictionary view | TM panel |
|--------|-----------|-----------------|----------|
| Primary count ("Found") | Filtered | Filtered | Filtered |
| Secondary count | "Hidden by min freq: N" (filtered delta) | "Noise: N" (project-wide) | None |
| Secondary count semantics | Display-time delta | Health metric | N/A |

**Decision: LEGITIMATE DIVERGENCE**

Terms secondary count = relative to current filter (how much is hidden).
Dictionary secondary count = absolute health metric (independent of filter).
Both are intentional design choices documented in their respective epics.

Action: `docs/UI_VOCABULARY.md` and `docs/SEMANTIC_CONTRACT.md` §7 document this explicitly.

---

## Concept 7 — Destructive Path Messaging

| Aspect | Terms view | Dictionary view | TM panel |
|--------|-----------|-----------------|----------|
| Destructive operation | Full Overwrite | None currently | None currently |
| Impact preview | Yes — `get_overwrite_impact()` dialog | No | No |
| What's preserved | TM entries + provenance | N/A | N/A |

**Decision: LEGITIMATE ASYMMETRY**

Only Term Extraction has a destructive re-extraction mode. Dictionary and TM panel do not have bulk-delete or rebuild operations with equivalent risk. No unification needed.

Future: If Dictionary ever gets a "reprocess lemmas" bulk operation, the Full Overwrite impact preview pattern (Epic 5A) should be reused.

---

## Concept 8 — Legacy Data Handling

| Aspect | Terms view | Dictionary view | TM panel |
|--------|-----------|-----------------|----------|
| Pre-provenance records | params_hash=NULL (pre-v43 runs) — not resumable | noise_source=NULL (pre-v47 lemmas) — badge without suffix | promoted_from_cluster_id=NULL (pre-v45 entries) — Src = grey |
| UI treatment | Resume gating: NULL rows pass through (backward compat) | "Noise" / "Valid" (no "(auto)" or "(manual)") | Src col grey |
| Tooltip | N/A | "source unknown (legacy data)" | Grey = manual (no cluster source) |

**Decision: CONSISTENT PATTERN, EXPLICIT BY DESIGN**

All three surfaces handle legacy (pre-provenance) records by:
1. Showing the data they have (is_noise, source state)
2. Omitting provenance details that don't exist (no fake date, no fake source)
3. Adding a qualifier where needed ("legacy data", no suffix)

This is the intended pattern. Do not backfill provenance retroactively.

---

## Summary Decision Table

| Concept | Decision | Action |
|---------|----------|--------|
| Noise | LEGITIMATE DIVERGENCE | Document in UI_VOCABULARY |
| Source / provenance | TARGETED POLISH | PATCH-04: add Lifecycle col to Dictionary |
| Status | LEGITIMATE DIVERGENCE | Document scoped variants in UI_VOCABULARY |
| Valid vs. Approved | LEGITIMATE DIVERGENCE + DOCUMENT | Add "not to be confused" note in UI_VOCABULARY |
| Hidden counts | LEGITIMATE ASYMMETRY | No action |
| Project-wide vs. filtered | LEGITIMATE DIVERGENCE | Already documented in SEMANTIC_CONTRACT §7 |
| Destructive path messaging | LEGITIMATE ASYMMETRY | Document pattern for future operations |
| Legacy data | CONSISTENT PATTERN | No action |

---

## Open Questions (not decisions)

1. **Should Dictionary filter show a "hidden count" for noise-filtered lemmas?**
   Deferred. Current design: project-wide noise count is always visible in status bar regardless of filter. This may be sufficient.

2. **Should TM panel expose source_lifecycle (Axis 2) as a dedicated column?**
   TM panel currently shows `source_status` (Axis 1, cluster-centric). `source_lifecycle` (Axis 2) is only needed for lemma-centric view. Dictionary view is the right surface. Not needed in TM panel.

3. **Should Terms view expose noise at cluster level?**
   Clusters are extracted from corpus statistics, not from individual lemmas. Noise is a lemma-level concept. Applying it to clusters would require aggregation (e.g., "X% of member lemmas are noise"). Not planned for this wave.
