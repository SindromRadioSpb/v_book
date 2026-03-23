# Next Wave after Epics 4/5/6 — Audit & Plan

> **Status:** Approved 2026-03-24
> **Audit date:** 2026-03-24
> **Schema version at audit:** v47
> **Test baseline at audit:** 1708 passed, 0 failed, 30 skipped
> **Approved plan:** Next Wave Phases 0–6 (PATCH-00..PATCH-06)

---

## 1. Confirmed Delivered Scope

All three epics confirmed complete by code, tests, and git history.

### Epic 4 — Term Extraction Pro (schema v43–v44)

| Feature | Evidence |
|---------|----------|
| `params_hash` reproducibility + resume gating | `term_extraction_service._build_term_extract_params_hash()` |
| `best_keyness` storage + index | migration 043, `term_cluster.best_keyness` |
| Weirdness stored at extraction time | `_store_termhood_metrics_for_project()` |
| Staleness warning + Recalculate button | `terms_view.py` |
| Sort presets (keyness / weirdness / termhood) | `terms_view.py` |
| `min_doc_freq` filter | `terms_view.py` + service layer |
| N-gram size + include_np persistence | QSettings |

### Epic 5 — TM Safety & Layered Extraction (schema v45–v46)

| Wave | Feature | Evidence |
|------|---------|----------|
| 5A | Provenance columns (`promoted_from_cluster_id`, `promoted_at_params_hash`, `promoted_at_run_id`) | migration 045 |
| 5A | `source_status` computed (linked / source_cluster_missing / manual) | `user_dictionary_service` |
| 5A | Impact preview before Full Overwrite | `get_overwrite_impact()` |
| 5B | `ngram_n_set` on `term_cluster` | migration 046 |
| 5B | Three extraction modes (Full Overwrite / Merge / Replace Layer) | `term_extraction_service` |
| 5C | `min_freq` → display-time filter (algo_version v2) | service + UI |
| 5C | All candidates stored regardless of threshold | removed extraction-time filter |
| 5D | Hidden count, min_freq tooltip, resume log note | `terms_view.py` |
| 5D | Quick presets, freq-distribution label, growth warning | `terms_view.py` |
| 5D | Recent threshold history, store_hapax toggle | `terms_view.py` + QSettings |

### Epic 6 — Dictionary Maturity (schema v47)

| Wave | Feature | Evidence |
|------|---------|----------|
| 6A | `noise_source` + `noise_updated_at` on `lemma` | migration 047 |
| 6A | `orphaned_lemma_id` on `tm_entry` (snapshot before DELETE) | migration 047 |
| 6A | R2 guard (batch translate skips `user_edit+approved`) | `batch_mt_translate_service` |
| 6A | `source_lifecycle` computation (linked / source_missing / manual / auto_only) | `dictionary_service.compute_source_lifecycle()` |
| 6B | Entity Class column (col 9, shift) | `models_qt.LemmaTableModel` |
| 6B | Noise badge with provenance suffix (auto / manual / legacy) | `models_qt.LemmaTableModel` col 8 |
| 6B | Semantic tooltips (noise provenance + NER class) | `_noise_provenance_tooltip()`, `_entity_class_tooltip()` |
| 6B | Project-wide noise counter in status bar | `DictionaryService.count_noise_lemmas()` |
| 6B | Column contract locked: 13 columns, col 5 Translation editable | regression tests |
| 6C | User guide + completion report | `epic6_dictionary_guide.md`, `epic6_completion.md` |

---

## 2. Test Baseline (post-Epics 4/5/6)

| Metric | Value |
|--------|-------|
| Total passed | **1708** |
| Total failed | **0** |
| Skipped (dev-DB required) | 30 |
| Epic-specific tests | 159 (13 files) |
| Runtime | ~153s |

Key coverage confirmed:
- 68/68 targeted Epic 5/6 tests green (2026-03-24 run)
- Cross-model column regression tests in place (col 5 editable guard)
- Axis isolation test: noise provenance ≠ source lifecycle in tooltip text

---

## 3. Confirmed Gaps (evidence-based)

| Gap | Severity | Resolution in Next Wave |
|-----|----------|------------------------|
| No unified semantic contract doc | HIGH | PATCH-01 |
| No cross-surface consistency matrix | HIGH | PATCH-02 |
| No canonical UI vocabulary | MEDIUM | PATCH-03 |
| Axis 2 (`source_lifecycle`) not surfaced in Dictionary view | MEDIUM | PATCH-04 |
| No manual QA matrix | MEDIUM | PATCH-05 |
| No user-facing maturity summary | MEDIUM | PATCH-06 |
| No operator guide | LOW | PATCH-06 |

**Confirmed NOT gaps (already addressed):**
- Roadmap `ROADMAP_PREMIUM_PRO.md` — updated 2026-03-23, accurate
- All epic completion reports — current and accurate
- Test suite — 1708/0, no regression
- Column contract — locked with regression tests

---

## 4. Semantic Drift Found (requires PATCH-01 + PATCH-02)

| Term | Terms view | Dictionary view | TM panel |
|------|-----------|-----------------|----------|
| "noise" | no such field on clusters | `is_noise` + badge | `is_noise` filter checkbox |
| "source" | `source_status` (cluster-centric) | `source_lifecycle` (lemma-centric, not surfaced) | Src col (●) |
| "status" | extraction run status | lemma classification status | entry status (approved/rejected/draft) |
| "valid" | not used | `Valid (auto/manual)` badge | `Approved` ≠ Valid |

---

## 5. Approved Execution Plan

### PATCH-00 — Audit consolidation ✅
- `docs/next_wave_audit.md` (this file)
- Memory: test baseline → 1708/0
- Memory: Next Wave plan approved

### PATCH-01 — Semantic contract doc
- `docs/SEMANTIC_CONTRACT.md`
- 7 sections: stable/derived fields, provenance, source lifecycle, display-time vs rebuild-time, destructive ops, write-policy, project-wide counts

### PATCH-02 — Cross-surface consistency matrix
- `docs/CROSS_SURFACE_MATRIX.md`
- Terms / Dictionary / TM compared across 8 concepts
- Explicit Decision per divergence

### PATCH-03 — Canonical UI vocabulary
- `docs/UI_VOCABULARY.md`
- 15+ terms, normative, one term = one meaning

### PATCH-04 — Axis 2 in Dictionary (docs correction, no code)
- **Decision revised 2026-03-24:** `source_lifecycle` is a TM entry concept. For lemmas visible in Dictionary view, lifecycle is always "linked" by definition. Column would always be green = no user value.
- Action: Update `CROSS_SURFACE_MATRIX.md` with accurate decision + rationale (done).
- Update memory `project_epic6_source_lifecycle_status.md` (done).
- No code change. No test change.

### PATCH-05 — Manual QA matrix
- `docs/MANUAL_QA_MATRIX.md`
- 25+ scenarios: Dictionary / Terms / TM / cross-surface

### PATCH-06 — Release-facing consolidation
- `docs/MATURITY_SUMMARY.md`
- `docs/OPERATOR_GUIDE.md`
- Update `docs/ROADMAP_PREMIUM_PRO.md` (add Next Wave section)

---

## 6. Risk Matrix

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| PATCH-04 shifts column indices → regression | MEDIUM | Extend existing column regression tests before code change |
| Semantic contract creates confusion if not linked from completion docs | LOW | Cross-reference from epic6_completion.md |
| Manual QA matrix becomes stale after PATCH-04 | LOW | Include Axis 2 scenarios in PATCH-05 (written after code) |
| Roadmap Next Wave section conflicts with existing structure | LOW | Add as new section, don't modify existing delivered entries |

---

## 7. Out of Scope (this wave)

- New broad epics
- Schema changes (v47 is stable)
- Batch Translate write-policy full matrix (R3/R4 modes)
- Import/Export Premium (Iteration 5 of roadmap)
- Performance History (Iteration 6 of roadmap)
- Legacy data retroactive cleanup
- Refactoring of existing services
