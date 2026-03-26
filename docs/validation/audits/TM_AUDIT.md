# TM — Audit Report: TM Projection Validation

> Wave 1 completed: 2026-03-26 — materialize_project_lemmas_to_tm (kind='lemma')
> Wave 2 completed: 2026-03-26 — user_dict pathway + _attach_source_links + tm_global propagation
> Status: **PARTIAL** (kind='lemma' + user_dict validated; inline_edit + batch_MT not yet tested)
> Auditor: post-wave automated audit

---

## 1. Scope of this wave

### Wave 1 (2026-03-26) — materialize_project_lemmas_to_tm

**What was done:**
- Repo audit: traced all pathways that create `tm_entry` rows. Critical finding: `TermExtractionService` does NOT create tm_entry rows — TM projection is a separate, explicitly-triggered step.
- Gold corpus: `tests/validation/gold/ctm_tm_projection.json` — 10 scenarios + architectural gap documentation.
- Oracle: `tests/validation/oracles/oracle_tm.py` — wraps `TranslationAdminService.materialize_project_lemmas_to_tm`.
- Integration tests: `tests/validation/test_vtm_tm_projection.py` — 27 tests across 7 test classes. All pass.
- Architectural gap documented: no bulk projection function exists for `kind='term_cluster'`.

### Wave 2 (2026-03-26) — user_dict pathway, _attach_source_links, tm_global propagation

**What was done:**
- Gold corpus: `tests/validation/gold/ctm2_user_dict_pathway.json` — 10 scenarios covering user_dict add pathway.
- Integration tests: `tests/validation/test_vtm2_user_dict_pathway.py` — 25 tests across 10 test classes. All pass.
- Contracts validated: kind='term_cluster' creation, source_ref, TMGlobal inheritance, entry reuse, cluster_id/_attach_source_links, lemma_id link, promoted_from_cluster_id first-only, item field updates, stats dict, tm_global propagation.

**What remains NOT in scope:**
- Inline edit pathway (`terms_view.py:1817`) — kind='term_cluster' with status='approved'
- Batch MT pathway (`batch_mt_translate_service`) — kind='term_cluster' and kind='lemma'
- `kind='ngram'` and `kind='surface'` TM creation
- `uq_tm_entry` conflict scenarios (concurrent materialization)

---

## 2. Product contract now validated

### Wave 1: `materialize_project_lemmas_to_tm` contract

**`materialize_project_lemmas_to_tm` contract:**

| Claim | Test class | How verified |
|---|---|---|
| Creates one tm_entry per Lemma row | TestSTM01 | count == lemma count |
| kind = 'lemma' | TestSTM01 | field assertion |
| status = 'draft' | TestSTM01 | field assertion |
| origin = 'import' | TestSTM01 | field assertion |
| src_lang / tgt_lang from project definition | TestSTM01 | he/ru assertion |
| translation = '' (empty, not NULL) | TestSTM01 | field assertion |
| src_text = lemma.lemma_text | TestSTM01 | exact string match |
| src_norm = norm_text when norm_text is set | TestSTM02 | src_norm ≠ lemma_text |
| src_norm = lemma_text when norm_text is null | TestSTM02 | fallback verified |
| src_norm = lemma_text when norm_text is whitespace | TestSTM02 | coalesce(nullif(trim(…))) |
| is_noise propagated from lemma | TestSTM04 | field assertion |
| noise_reason propagated from lemma | TestSTM04 | field assertion |
| INSERT OR IGNORE: double run → no duplicates | TestSTM05 | count stable after 2nd call |
| Pre-existing tm_entry not duplicated | TestSTM06 | count = existing + new only |
| Pre-existing translation NOT overwritten | TestSTM06 | translation, status unchanged |
| Stats dict has all required keys | TestSTM07 | set inclusion check |
| Stats.inserted = final - initial | TestSTM07 | numeric assertion |
| dry_run=True: zero rows created | TestSTM08 | count == 0 |
| tm_entry.lemma_id → correct Lemma.lemma_id | TestSTM09 | FK value assertion |
| materialize creates ONLY kind='lemma' | TestSTM10 | term_cluster count == 0 |

### Wave 2: `_materialize_tm_entries_for_items` contract

| Claim | Test class | How verified |
|---|---|---|
| Creates new TMEntry for kind='term_cluster' | TestSUD01 | stats.created == 1 |
| entry.kind = 'term_cluster' | TestSUD01 | field assertion |
| source_ref = 'user_dictionary_add' | TestSUD01 | field assertion |
| Default status='draft', origin='import' when no TMGlobal | TestSUD01 | field assertion |
| Default translation='' when no TMGlobal | TestSUD01 | field assertion |
| Reuses existing entry by (project_id, kind, src_lang, tgt_lang, src_norm) | TestSUD02 | stats.reused=1, count stable |
| Empty items list → zero stats and no entries | TestSUD03 | stats == {0,0,0}, count == 0 |
| translation/status/origin inherited from TMGlobal when exists | TestSUD04 | field assertion |
| item.origin_tm_entry_id updated to entry.tm_id after materialize | TestSUD05 | FK value assertion |
| item.src_norm updated to canonical norm after materialize | TestSUD05 | non-empty check |
| entry.cluster_id set when origin_entity_type='term_cluster' | TestSUD06 | FK value assertion |
| entry.cluster_id remains None when no origin_entity_id | TestSUD06 | None assertion |
| entry.lemma_id set when kind='lemma' + origin_entity_type='lemma' | TestSUD07 | FK value assertion |
| promoted_from_cluster_id set on first cluster link | TestSUD08 | value == cluster_id |
| promoted_from_cluster_id never overwritten once set | TestSUD08 | remains first cluster_id |
| stats dict has keys: created, reused, linked | TestSUD09 | key set assertion |
| linked increments for both new and reused items | TestSUD09 | linked == 2 for 2 items |
| TMGlobal propagation: existing linked entries updated | TestSUD10 | stale entry translation updated |
| New entry gets tm_global_id when TMGlobal exists | TestSUD10 | FK value assertion |

**Critical architectural finding (confirmed by tests):**
`TermExtractionService` has zero `TMEntry` imports or creation calls. After an extraction run completes, the TM is not updated automatically. TM projection is a separate step, triggered by:
1. `materialize_project_lemmas_to_tm` — batch, `kind='lemma'` only
2. `user_dictionary_service._materialize_tm_entries_for_items` — per-user-action, all kinds
3. `terms_view.py` inline edit — per-user-action, `kind='term_cluster'`
4. `batch_mt_translate_service` — per-MT-run, `kind='term_cluster'` and `kind='lemma'`

**None of these run automatically as part of extraction.**

---

## 3. What is now guaranteed in practice

- The `materialize_project_lemmas_to_tm` function produces correct, complete `tm_entry` rows from `Lemma` rows with verified field contracts.
- The function is idempotent: running it multiple times does not duplicate rows or overwrite user translations.
- `src_norm` fallback logic (empty/null `norm_text` → use `lemma_text`) is verified — a refactor of the coalesce logic will be caught.
- Noise propagation (is_noise, noise_reason from lemma → tm_entry) is verified.
- The architectural gap — no `kind='term_cluster'` bulk projection — is now formally documented and test-confirmed.

---

## 4. What defects are now caught automatically

**From Wave 1 (materialize_project_lemmas_to_tm):**
- **D07 (regression):** Any change to field values produced by `materialize_project_lemmas_to_tm` (status, origin, src_norm logic).
- **D07:** Materialization creating duplicate rows (losing idempotency).
- **D07:** Pre-existing translations being overwritten by materialization.
- **D07:** `lemma_id` linkage silently broken (FK pointing to wrong row).
- **D07:** `dry_run=True` creating rows (dry_run protection broken).
- **D03 (invariant):** `kind='term_cluster'` count != 0 after materialization (would indicate unintended behavior).

**From Wave 2 (_materialize_tm_entries_for_items):**
- **D07:** source_ref lost or changed from `"user_dictionary_add"`.
- **D07:** Default status/origin wrong when no TMGlobal (draft/import).
- **D07:** TMGlobal translation/status/origin not inherited on new entry creation.
- **D07:** Entry reuse broken — duplicate rows created on second add of same src_norm.
- **D07:** `cluster_id` or `lemma_id` not set by `_attach_source_links`.
- **D07:** `promoted_from_cluster_id` silently overwritten on re-promotion.
- **D07:** `item.origin_tm_entry_id` not updated after materialize.
- **D07:** TMGlobal propagation broken — stale entries not updated when a new item is processed.

---

## 5. What remains NOT covered

**By-design architectural gap (NOT a bug):**
- `kind='term_cluster'` has no bulk materialization function. To surface extraction results in TM, a user must explicitly add terms to the dictionary, run batch MT, or use inline edit. This is documented in `ctm_tm_projection.json` as `by_design_architectural_gap`.

**Out of scope after Wave 2 (testable but not yet covered):**
- `terms_view.py` inline edit pathway (`terms_view.py:1817`): creates `kind='term_cluster'` with `status='approved'`, `origin='user_edit'`. Requires PyQt6 UI fixture — not suitable for in-memory validation corpus.
- `batch_mt_translate_service._write_term_cluster` and `_write_lemma`: creates entries per MT run. Complex async worker dependency.
- `uq_tm_entry` conflict scenarios: concurrent materialization calls. Not suitable for single-session in-memory tests.
- `kind='ngram'` and `kind='surface'` entry pathways.

---

## 6. Required follow-up

**TM v3 (optional, low priority):**

1. Test `terms_view.py` inline edit pathway — requires a different test strategy (service-layer isolation or UI mock).
2. Test `batch_mt_translate_service` pathway — requires MT worker mock.
3. Consider whether a `materialize_project_clusters_to_tm` batch function is needed — architectural decision.

---

## 7. DoD verdict

**PARTIAL** (reduced gap after Wave 2)

After Wave 2: 52 tests pass (27 Wave 1 + 25 Wave 2). Two pathways now validated:
- `materialize_project_lemmas_to_tm` — kind='lemma' batch projection
- `_materialize_tm_entries_for_items` — user_dict add pathway, all kinds

Still PARTIAL (not PASS) because:
- `terms_view.py` inline edit and `batch_mt_translate_service` pathways are not tested.
- These require UI/worker fixtures beyond the in-memory SQLite validation corpus scope.
- The `kind='term_cluster'` bulk materialization gap remains by-design.

The primary TM validation obligation (user-visible TM creation pathways) is materially met: the two main service-layer pathways are validated. The remaining untested pathways (inline_edit, batch_MT) are secondary and have higher test-fixture complexity.

---

## 8. Files changed in this wave

### Wave 1
| File | Role |
|---|---|
| `tests/validation/gold/ctm_tm_projection.json` | Gold — 10 scenarios + architectural gap documentation |
| `tests/validation/oracles/oracle_tm.py` | Oracle — wraps materialize_project_lemmas_to_tm |
| `tests/validation/test_vtm_tm_projection.py` | 27 integration tests; In-Memory SQLite |

### Wave 2
| File | Role |
|---|---|
| `tests/validation/gold/ctm2_user_dict_pathway.json` | Gold — 10 scenarios for user_dict add pathway |
| `tests/validation/test_vtm2_user_dict_pathway.py` | 25 integration tests; In-Memory SQLite |
| `docs/validation/audits/TM_AUDIT.md` | This file (updated) |
| `docs/validation/AUDIT_INDEX.md` | Updated: TM next required action updated |
| `docs/validation/VALIDATION_METHODOLOGY.md` | Updated: test count updated |

---

## 9. Regression / baseline impact

- Validation suite (non-Stanza): **156 passed** (104 prior + 27 Wave 1 + 25 Wave 2).
- Main baseline (--ignore=tests/validation): **1751 passed** (unchanged).
- Both TM test files use In-Memory SQLite, no GPU, fast (~1.4s for 27 + ~1.7s for 25 tests).

---

## 10. Executive summary

Wave 1 produced a significant architectural finding: `TermExtractionService` does not create `tm_entry` rows. TM projection is entirely decoupled from extraction and requires explicit calls to one of four pathways. The `materialize_project_lemmas_to_tm` pathway (batch, kind='lemma') was validated in Wave 1 with 27 tests covering field values, src_norm fallback, noise propagation, idempotency, partial-update behavior, dry_run, and `lemma_id` linkage.

Wave 2 validated the user-dict add pathway (`_materialize_tm_entries_for_items`): kind='term_cluster' creation, TMGlobal translation/status/origin inheritance, entry reuse by src_norm, `_attach_source_links` contracts (cluster_id, lemma_id, promoted_from_cluster_id first-only), item field updates after materialize, and TMGlobal propagation to existing linked entries. 25 additional tests, all passing.

Status remains PARTIAL because the inline_edit pathway (`terms_view.py:1817`) and batch MT pathway (`batch_mt_translate_service`) require UI/worker test fixtures beyond the in-memory corpus scope. These are low-priority follow-ups. The two primary service-layer TM creation contracts are now validated.

---

## Follow-up checklist

- [x] Update VALIDATION_METHODOLOGY.md: TM stage added, test count updated
- [x] Update AUDIT_INDEX.md: TM status updated
- [x] **TM v2: test user_dictionary_service._materialize_tm_entries_for_items (kind='term_cluster')**
- [x] TM v2: test _attach_source_links (cluster_id / lemma_id linkage via service)
- [x] TM v2: test tm_global propagation (translation/status/origin from global)
- [ ] TM v3 (optional): test terms_view.py inline edit pathway
- [ ] TM v3 (optional): test batch_mt_translate_service pathway
- [ ] Architectural decision: should a `materialize_project_clusters_to_tm` batch function exist?
