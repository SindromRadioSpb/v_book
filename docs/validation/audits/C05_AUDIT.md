# C05 — Audit Report: NP Chunk Extraction

> Wave completed: 2026-03-26
> Status: **PARTIAL**
> Auditor: post-wave automated audit

---

## 1. Scope of this wave

**What was done:**
- Gold corpus: 7 cases covering NOUN+NOUN, NOUN+ADJ+NOUN, STOP_POS breaking, DET article merging (`merge_standalone_articles`), max_len enforcement, all-STOP_POS empty result, and a max-length (5-token) NP.
- Oracle: `tests/validation/oracles/oracle_np.py` — calls `extract_np_chunks_from_sentence()`, normalizes actual using `n` key for span length, compares `(surface_text, length)` key sets.
- Tests: `tests/validation/test_v05_np_extraction.py` — 6 test methods.
- All tests pass. No Stanza required (pre-tokenized input).
- Gold calibration: C05_04 updated — DET `"ה"` + `"ילד"` merge → `"הילד"` (surfaces corrected for `merge_standalone_articles` behavior).

**What was NOT in scope:**
- NPs longer than 5 tokens (max_len is an absolute limit by design)
- Ambiguous NP boundaries (where human annotation would disagree)
- Morphological validation inside NP tokens (C05 takes pre-POS-tagged input)
- Interaction with n-gram extractor on overlapping spans

---

## 2. Product contract now validated

**Contract:**

| Claim | Gold evidence | Oracle check |
|---|---|---|
| NOUN+NOUN is a valid 2-token NP | C05_01 | set key match |
| NOUN+ADJ+NOUN produces 3 NP sub-spans | C05_02 | 3-element set match |
| STOP_POS (VERB) breaks the NP window | C05_03 | only post-VERB segment present |
| `merge_standalone_articles`: `"ה"` (DET) + following NOUN → merged surface | C05_04 | merged strings `"הילד"` in result |
| max_len=2 excludes spans of length 3+ | C05_05 | only length-2 spans present |
| All-STOP_POS input produces no NP chunks | C05_06 | empty actual set |
| Length-5 span is present in 5-token all-nominal input | C05_07 | subset match + min_count |
| Length is reported as span width (token count) | All cases | `length` key in oracle key |

**Oracle comparison detail (two modes):**
- Cases C05_01–C05_06: exact set match on `(surface_text, length)` keys. Missing chunks and extra chunks are both detected.
- Case C05_07: **subset match** — only verifies that specified chunks are present; does not verify the full set. Extra chunks are not reported as failures.

**What the oracle does NOT guarantee:**
Token indices in original sentence. Character offsets. Internal morphology of NP tokens. Whether the NP is semantically coherent. Anything about POS tags inside the extracted chunk.

---

## 3. What is now guaranteed in practice

- STOP_POS segmentation boundary behavior is verified: a VERB between two nominal sequences creates two separate NP windows.
- `merge_standalone_articles` is now a **documented, tested contract**: standalone `"ה"` (DET) merges with the following NOUN surface form. This is visible in C05_04 gold and oracle string equality.
- min_len/max_len boundaries are tested: lengths below min_len are excluded (C05_03, single NOUN before VERB), lengths above max_len are excluded (C05_05).

---

## 4. What defects are now caught automatically

- **D07 (regression):** Any change to STOP_POS list that allows VERB, PRON, ADP, etc. to appear inside an NP span.
- **D07:** `merge_standalone_articles` behavior reverting (DET no longer merging with NOUN).
- **D07:** min_len or max_len boundaries shifting.
- **D07:** All-STOP_POS input producing phantom chunks.
- **D01/D06:** Gold mismatch after intentional algorithm change.
- **D04 (non-determinism):** Different chunk sets on repeat calls.

---

## 5. What remains NOT covered

- **C05_07 uses subset match, not exact match.** The 5-token case verifies the max-length span is present and a minimum count is met, but extra unexpected chunks would not fail the test. This is a deliberate oracle choice (sub-span combinatorics), but it means some phantom chunks could go undetected for this case.
- **Ambiguous boundary cases:** E.g., ADJ at the start of a segment that could be either a modifier of the previous noun or the start of a new NP — not tested.
- **DET not as first token:** What happens if DET appears as a non-first token in a segment? Gold only covers DET as first (C05_04). Middle-position DET behavior is untested.
- **Multiple DET tokens in one span:** `"ה ילד ה גדול"` (two standalone DET tokens) — merge behavior not verified.
- **min_len=1:** Not tested. Unigram NPs are architecturally possible but unverified.
- **Interaction with C04:** No test for the case where the same token sequence produces both an ngram and an NP chunk (they are independent extractors, but joint coverage is not validated).

---

## 6. Required follow-up

**C05 v2 additions:**
1. DET in non-first position — verify it is treated as part of a NOUN surface (or rejected).
2. Two consecutive standalone DET tokens — verify merge behavior.
3. A case that confirms extra-chunk absence for the 5-token scenario (convert C05_07 to exact match or add an explicit extra-chunk rejection case).
4. ADJ-led NP span (to confirm MODIFIER_POS can begin a segment in the absence of DET).

---

## 7. DoD verdict

**PARTIAL**

All 7 gold cases pass. STOP_POS boundary, DET merge, min/max_len, and empty-result cases are confirmed.

Not PASS because:
- C05_07 uses subset match — extra chunks in the 5-token case would not be caught.
- DET in non-first position and multiple-DET scenarios are untested.
- Token indices are not validated (only surface_text and length).

---

## 8. Files changed in this wave

| File | Role |
|---|---|
| `tests/validation/gold/c05_np_extraction.json` | Gold — 7 cases; C05_04 corrected for `merge_standalone_articles` (DET+NOUN merged surfaces) |
| `tests/validation/oracles/oracle_np.py` | Oracle — `n` key normalization; supports exact + subset match modes |
| `tests/validation/test_v05_np_extraction.py` | 6 test methods |

---

## 9. Regression / baseline impact

- Validation suite (non-Stanza): **104 passed**.
- C05 contributes 6 test nodes.

---

## 10. Executive summary

C05 validates NP chunk extraction including STOP_POS window segmentation, DET article merging, and min/max_len enforcement. The `merge_standalone_articles` behavior (standalone `"ה"` + NOUN → merged surface) is now a verified, documented contract. The primary structural limitation is C05_07: the 5-token maximum-length case uses subset match, meaning extra unexpected chunks would not fail the test. DET behavior in non-first token positions is unverified. The oracle validates surface strings and span lengths but says nothing about token indices or internal morphology. Status is PARTIAL; C05 v2 should convert C05_07 to exact match (or add an extra-chunk rejection case) and cover the untested DET positioning scenarios.

---

## Follow-up checklist

- [x] Update methodology status
- [x] Update audit index
- [ ] Add C05 v2: DET in non-first position
- [ ] Add C05 v2: two consecutive standalone DET tokens
- [ ] Convert C05_07 to exact match OR add separate extra-chunk rejection test
- [ ] Verify interaction with C04 on shared token sequences (joint coverage gap)
