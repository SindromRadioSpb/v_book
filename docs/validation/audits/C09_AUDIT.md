# C09 — Audit Report: Extraction Modes

> Wave completed: 2026-03-26 (commit ebfdc9f)
> Status: **VALIDATED**
> Auditor: post-wave automated audit

---

## 1. Scope of this wave

**What was done:**
- Gold corpus: `c09_extraction_modes.json` — 6 state-transition scenarios + TM preservation invariant (scenario definitions, not direct oracle cases).
- Integration tests: `tests/validation/test_v09_extraction_modes.py` — 23 tests across 7 test classes using In-Memory SQLite + `TermExtractAccumulator` seeding. No Stanza, no NLP collection required.
- All 23 tests pass.
- Fix applied: model class corrected from `TmEntry` (wrong) to `TMEntry` (correct); primary key corrected from `entry_id` to `tm_id`; column names corrected to `src_lang`, `tgt_lang`, `src_text`, `src_norm`, `translation`, `status`, `origin`.

**Why the fix mattered:** The original fixture used wrong column names. On SQLite in-memory, SQLAlchemy would have silently created rows without the required fields, resulting in TM preservation tests running against an empty TM — trivially passing but proving nothing. The fix ensures TM rows are actually present before verifying the preservation invariant.

**What was NOT in scope:**
- NLP collection stage (Stanza → NgamExtractor → NPExtractor pipeline feeding the accumulator)
- TM entry creation from extraction (only preservation, not creation)
- Association measure thresholds as storage gates
- Concurrent extraction (two workers on same project)
- Cross-project isolation

---

## 2. Product contract now validated

**Three extraction modes (backed by tests):**

| Contract | Test class | How verified |
|---|---|---|
| Full Overwrite deletes ALL term_cluster and ngram rows before inserting | TestS01_FullOverwrite | `_clear_existing_terms` → cluster count = 0; then finalize → new clusters present |
| Overwrite does not touch TM entries | TestTMPreservationInvariant | tm_entry count before = tm_entry count after overwrite |
| Merge preserves all existing cluster IDs | TestS02_MergePreservesExisting | all pre-existing IDs still in cluster table |
| Merge adds new clusters alongside existing | TestS02_MergePreservesExisting | new surfaces appear; old ones not removed |
| Merge (INSERT OR IGNORE) does not overwrite existing ngrams | TestS02_MergePreservesExisting | existing ngram surface unchanged |
| Replace Layer deletes only clusters with matching `ngram_n_set` | TestS03_ReplaceLayerPreservesOtherLayers | bigrams removed; trigrams and NP clusters survive |
| Replace Layer does NOT delete TM entries | TestTMPreservationInvariant | tm_entry count unchanged |
| store_hapax=False: freq_abs=1 rows NOT stored | TestS04_StoreHapaxOff | hapax surface absent from cluster table |
| store_hapax=False: freq_abs≥2 rows ARE stored | TestS04_StoreHapaxOff | non-hapax surface present |
| min_freq is NOT a storage gate | TestS05_StoreHapaxOn | rows with freq below min_freq appear in DB |
| store_hapax=True stores hapax terms | TestS05_StoreHapaxOn | freq_abs=1 surface present after finalization |
| Overwrite twice with same input → same cluster set | TestS06_OverwriteIdempotency | surface set equal; cluster count equal |
| Zero-document overwrite is idempotent | TestS06_OverwriteIdempotency | cluster count = 0 after second overwrite with no data |
| TM entries are never deleted by any of the three modes | TestTMPreservationInvariant | all 3 modes tested separately |

**Critical semantic finding confirmed by tests:**
`min_freq` is a **display-only filter**, not a storage gate. Terms with `freq_abs < min_freq` are stored in the DB during finalization. They are hidden in the UI but exist in the database. Any code change that promotes `min_freq` to a storage gate would break `test_min_freq_is_not_a_storage_gate`.

---

## 3. What is now guaranteed in practice

- A refactoring of `_clear_existing_terms` that accidentally touches `tm_entry` rows will fail immediately.
- A bug in `_clear_terms_for_layer` that bleeds into adjacent layers (e.g., deleting trigrams when replacing bigrams) will be caught.
- Any change to the hapax gating point (e.g., moving the `freq_abs >= 2` filter from `_store_staged_ngrams` to a display layer) will fail.
- Two successive identical overwrite runs are guaranteed to produce the same state — non-determinism in the finalization path is detected.

---

## 4. What defects are now caught automatically

- **D07 (regression):** Overwrite leaking into TM entries.
- **D07:** Replace Layer deleting wrong layers (trigrams deleted when bigrams requested).
- **D07:** Merge becoming overwrite (existing clusters disappear).
- **D07:** Hapax filter moving from storage layer to display layer (or vice versa).
- **D07:** Non-deterministic finalization producing different cluster counts on repeat.
- **D03 (invariant violation):** TM count decreasing after any extraction mode.

---

## 5. What remains NOT covered

**Explicitly out of scope by design:**

- **NLP collection stage:** The oracle seeds `TermExtractAccumulator` directly, bypassing Stanza + NgamExtractor + NPExtractor. Bugs in those components that produce incorrect accumulator rows are not caught by C09.
- **TM entry creation:** C09 verifies TM rows are NOT deleted. It does not verify that new TM rows are correctly created from extraction output (correct `kind`, `src_text`, `src_norm`, `cluster_id` linkage). This is the primary gap for the TM layer.
- **Association measure thresholds as storage gates:** PMI/Dice/LLR threshold filtering is not tested in C09.
- **Concurrent extraction:** Two workers running on the same project simultaneously — not tested.
- **Cross-project isolation:** Extraction in project A affecting project B — not tested.
- **Performance:** All tests use in-memory SQLite with tiny datasets (3–5 rows). Production scale behavior is unverified.
- **Content correctness of stored terms:** Tests verify presence/absence of cluster rows, not that the content of those rows is semantically correct.

---

## 6. Required follow-up

**TM validation corpus (next mandatory wave):**
C09 closes the "don't break what's there" contract for extraction modes. But the "build what the user needs" contract — that extraction correctly projects results into `tm_entry` — is entirely untested. This is the primary next step.

Required TM corpus must verify:
- After extraction, `tm_entry` rows exist for `kind=ngram`, `kind=term_cluster` (or appropriate kind values).
- `src_text` / `src_norm` in TM entries match expected extraction output.
- `cluster_id` foreign key in `tm_entry` points to the correct cluster row.
- Re-extraction does not duplicate TM entries (if projection is idempotent).
- TM entry `kind` values for different extraction types (lemma vs. ngram vs. NP) are correctly assigned.

---

## 7. DoD verdict

**VALIDATED**

All 23 tests pass. State transitions for all three extraction modes are verified. Store_hapax semantics confirmed. Idempotency confirmed. TM preservation invariant confirmed across all modes.

The scope is precisely bounded: what is validated is the extraction layer state machine (term_cluster + ngram + store_hapax + modes). The TM projection layer is explicitly not covered and is the next required wave.

---

## 8. Files changed in this wave

| File | Role |
|---|---|
| `tests/validation/gold/c09_extraction_modes.json` | Gold — 6 state-transition scenarios + TM invariant definition |
| `tests/validation/test_v09_extraction_modes.py` | 23 integration tests; In-Memory SQLite; accumulator seeding pattern |

**Fix applied in this wave:**
`TMEntry` schema used correctly (was: `TmEntry`, `entry_id`, `canonical_key`, `source_he`, `target_ru` — all wrong). Corrected to: `TMEntry`, `tm_id`, `src_lang`, `tgt_lang`, `src_text`, `src_norm`, `translation`, `status`, `origin`. Without this fix, TM preservation tests would have been vacuously true.

---

## 9. Regression / baseline impact

- Validation suite (non-Stanza): **104 passed** (post C09 wave).
- Main baseline (--ignore=tests/validation): **1751 passed**.
- C09 contributes 23 test nodes.
- In-Memory SQLite used — no file locks, no torch DLL issue, fast (1.34s for 23 tests).

---

## 10. Executive summary

C09 validates the extraction mode state machine: Full Overwrite, Merge, and Replace Layer produce the correct DB state transitions, store_hapax=False correctly gates hapax at storage (not display), min_freq is confirmed as display-only, and TM entries are invariantly preserved across all three modes. The key fix in this wave — correcting the TMEntry model usage — was non-trivial: without it, TM preservation tests would have been testing an empty table (vacuously true). The remaining gap is the TM projection layer: C09 proves TM rows survive extraction, but does not prove they are correctly created by extraction. This gap — that the product's user-facing output (the TM with translations) is not validated — makes TM validation corpus the mandatory next step, not a suggestion.

---

## Follow-up checklist

- [x] Update VALIDATION_METHODOLOGY.md: C09 status changed from "Gold defined, test pending" to "Validated"
- [x] Update audit index
- [ ] **Build TM validation corpus: verify tm_entry creation from extraction output**
- [ ] TM corpus must cover: kind assignment, src_text/src_norm, cluster_id linkage, idempotency
- [ ] Consider adding C09 v2: concurrent extraction (two workers, same project)
- [ ] Consider adding C09 v2: cross-project isolation test
- [ ] Confirm no assumption changes for C10 (full pipeline round-trip) from C09 findings
