# TM — Audit Report: TM Projection Validation

> Wave completed: 2026-03-26 (Wave 1 of 5-wave plan)
> Status: **PARTIAL**
> Auditor: post-wave automated audit

---

## 1. Scope of this wave

**What was done:**
- Repo audit: traced all pathways that create `tm_entry` rows. Critical finding: `TermExtractionService` does NOT create tm_entry rows — TM projection is a separate, explicitly-triggered step.
- Gold corpus: `tests/validation/gold/ctm_tm_projection.json` — 10 scenarios + architectural gap documentation.
- Oracle: `tests/validation/oracles/oracle_tm.py` — wraps `TranslationAdminService.materialize_project_lemmas_to_tm`.
- Integration tests: `tests/validation/test_vtm_tm_projection.py` — 27 tests across 7 test classes. All pass.
- Architectural gap documented: no bulk projection function exists for `kind='term_cluster'`.

**What was NOT in scope:**
- `kind='term_cluster'` TM creation (no bulk function exists — architectural gap)
- `kind='ngram'` TM creation
- `kind='surface'` TM creation
- User-triggered TM creation via `user_dictionary_service._materialize_tm_entries_for_items`
- Inline edit pathway (`terms_view.py:1817`)
- Batch MT pathway (`batch_mt_translate_service`)
- TM Global propagation (`tm_global` linkage)
- Promotion provenance fields (`promoted_from_cluster_id`, `promoted_at_params_hash`)

---

## 2. Product contract now validated

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

- **D07 (regression):** Any change to field values produced by `materialize_project_lemmas_to_tm` (status, origin, src_norm logic).
- **D07:** Materialization creating duplicate rows (losing idempotency).
- **D07:** Pre-existing translations being overwritten by materialization.
- **D07:** `lemma_id` linkage silently broken (FK pointing to wrong row).
- **D07:** `dry_run=True` creating rows (dry_run protection broken).
- **D03 (invariant):** `kind='term_cluster'` count != 0 after materialization (would indicate unintended behavior).

---

## 5. What remains NOT covered

**By-design architectural gap (NOT a bug):**
- `kind='term_cluster'` has no bulk materialization function. To surface extraction results in TM, a user must explicitly add terms to the dictionary, run batch MT, or use inline edit. This is documented in `ctm_tm_projection.json` as `by_design_architectural_gap`.

**Out of scope for this wave (testable but not yet covered):**
- `user_dictionary_service._materialize_tm_entries_for_items`: creates entries for any kind, with `tm_global` link lookup. Not tested in validation corpus.
- `terms_view.py` inline edit pathway: creates `kind='term_cluster'` with `status='approved'`, `origin='user_edit'`. Not tested.
- `batch_mt_translate_service._write_term_cluster`: creates `kind='term_cluster'` with `status='approved'`, `origin='mt_auto'`. Not tested.
- `_attach_source_links`: sets provenance fields (`promoted_from_cluster_id`, etc.). Not tested.
- `tm_global` propagation: if a `TMGlobal` row exists for the canonical, its translation/status/origin are propagated to the new `TMEntry`. Not tested.
- `uq_tm_entry` conflict scenarios: what happens when two concurrent materialization calls hit the same row simultaneously. Not tested.

---

## 6. Required follow-up

**TM v2 (recommended, not yet scheduled):**

1. Test `user_dictionary_service._materialize_tm_entries_for_items` — the pathway that creates `kind='term_cluster'` entries.
2. Test `_attach_source_links` — verify `cluster_id`, `lemma_id` linkage is set correctly.
3. Test `tm_global` propagation — verify that existing global TM translations propagate to new entries.
4. Consider whether a `materialize_project_clusters_to_tm` function is needed (currently a missing batch pathway) — architectural decision, not a test gap per se.

---

## 7. DoD verdict

**PARTIAL**

All 27 tests pass. The `materialize_project_lemmas_to_tm` contract is fully validated.

Not PASS because:
- Only `kind='lemma'` pathway is tested. Three other creation pathways (user_dict, inline_edit, batch_MT) are not validated.
- `tm_global` propagation is not tested.
- The `kind='term_cluster'` bulk materialization gap is documented but not a blocker — it is by-design.

The wave closes the primary gap identified after C09: "extraction correctly creates TM entries". The finding refines this: extraction does not create TM entries at all — a separate projection step does. That projection step (for `kind='lemma'`) is now validated.

---

## 8. Files changed in this wave

| File | Role |
|---|---|
| `tests/validation/gold/ctm_tm_projection.json` | Gold — 10 scenarios + architectural gap documentation |
| `tests/validation/oracles/oracle_tm.py` | Oracle — wraps materialize_project_lemmas_to_tm |
| `tests/validation/test_vtm_tm_projection.py` | 27 integration tests; In-Memory SQLite |
| `docs/validation/audits/TM_AUDIT.md` | This file |
| `docs/validation/AUDIT_INDEX.md` | Updated: TM status Planned→Partial; C09 follow-up note added |
| `docs/validation/VALIDATION_METHODOLOGY.md` | Updated: TM stage added; counts updated |

**Fix in this wave:** `Library(description=...)` → `Library(name=...)` only (`Library` has no `description` column).

---

## 9. Regression / baseline impact

- Validation suite (non-Stanza): **131 passed** (104 prior + 27 new).
- Main baseline (--ignore=tests/validation): **1751 passed** (unchanged).
- TM projection tests use In-Memory SQLite, no GPU, fast (~1.4s for 27 tests).

---

## 10. Executive summary

Wave 1 produced a significant architectural finding: `TermExtractionService` does not create `tm_entry` rows. TM projection is entirely decoupled from extraction and requires an explicit call to one of four pathways. The `materialize_project_lemmas_to_tm` pathway (the primary batch projection) is now fully validated: field values, src_norm fallback, noise propagation, idempotency, partial-update behavior, dry_run, and `lemma_id` linkage are all confirmed by 27 passing tests. The architectural gap — no bulk projection for `kind='term_cluster'` — is documented as by-design: term_cluster entries enter TM only via user actions or batch MT. Status is PARTIAL because three other TM creation pathways remain untested; those are lower-priority follow-ups. The primary C09 gap ("TM creation not verified") is now materially closed for the `kind='lemma'` pathway.

---

## Follow-up checklist

- [x] Update VALIDATION_METHODOLOGY.md: TM stage added, test count updated
- [x] Update AUDIT_INDEX.md: TM status Planned→Partial
- [ ] **TM v2: test user_dictionary_service._materialize_tm_entries_for_items (kind='term_cluster')**
- [ ] TM v2: test _attach_source_links (cluster_id / lemma_id linkage via service)
- [ ] TM v2: test tm_global propagation (translation/status/origin from global)
- [ ] Architectural decision: should a `materialize_project_clusters_to_tm` batch function exist?
- [ ] Confirm STM10 gap is acceptable to product stakeholders (term_cluster in TM requires user action)
