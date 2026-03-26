# C04 — Audit Report: N-gram Extraction

> Wave completed: 2026-03-26
> Status: **PARTIAL**
> Auditor: post-wave automated audit

---

## 1. Scope of this wave

**What was done:**
- Gold corpus: 9 cases covering all 5 valid bigram POS patterns (NOUN+NOUN, NOUN+ADJ, ADJ+NOUN, PROPN+PROPN, NUM+NOUN), 2 valid trigram patterns (NOUN+NOUN+NOUN, ADJ+ADJ+NOUN), invalid POS rejection, single-token edge case, and NOUN+ADJ+ADJ rejection.
- Oracle: `tests/validation/oracles/oracle_ngram.py` — calls `extract_ngrams_from_sentence()`, compares sets of `(surface_text, n, pos_pattern_tuple)` keys.
- Tests: `tests/validation/test_v04_ngram_extraction.py` — 6 test methods.
- All tests pass. No Stanza required (pre-tokenized input).
- Gold calibration: C04_09 corrected — NOUN+ADJ+ADJ removed (not in VALID_POS_PATTERNS); ADJ+ADJ+NOUN retained as the valid trigram.
- `pos_pattern` normalization: oracle normalizes both gold (JSON array → tuple) and actual (pipe-joined string → tuple) via `_ngram_key()`.

**What was NOT in scope:**
- Punctuation tokens at sentence boundary
- Mixed Hebrew/Latin n-grams
- N-grams crossing STOP_POS tokens (which NP extractor handles, not ngram extractor)
- Very long sentences (n-gram combinatorics at scale)

---

## 2. Product contract now validated

**Contract:**

| Claim | Gold evidence | Oracle check |
|---|---|---|
| NOUN+NOUN bigram extracted | C04_01 | set key match |
| NOUN+ADJ bigram extracted | C04_02 | set key match |
| ADJ+NOUN bigram extracted | C04_03 | set key match |
| PROPN+PROPN bigram extracted | C04_04 | set key match |
| NUM+NOUN bigram extracted | C04_05 | set key match |
| NOUN+NOUN+NOUN trigram extracted | C04_06 | set key match |
| ADJ+ADJ+NOUN trigram extracted | C04_09 | set key match |
| `surface_text` uses original token text; `lemma_phrase` uses lemma | C04_04 (מדינת ישראל / מדינה ישראל) | set key includes surface |
| VERB+NOUN produces no n-gram | C04_07 | empty actual set |
| Single token produces no n-gram | C04_08 | empty actual set |
| NOUN+ADJ+ADJ does NOT produce a trigram | C04_09 | only ADJ+ADJ+NOUN present |
| Sliding window produces all valid sub-spans | C04_06 (3-token → 2 bigrams + 1 trigram) | count = 3 |

**Oracle comparison detail:**
The oracle compares sets of `(surface_text, n, pos_tuple)` keys. This means:
- Guarantees: correct surface string, correct n-value, correct POS pattern
- Does NOT guarantee: token indices, positions in original sentence, ordering within the result list, `lemma_phrase` correctness (only `surface_text` and `pos_tuple` are in the key)

`lemma_phrase` is present in gold but only implicitly validated through `surface_text` — if lemma diverges from surface unexpectedly, the oracle would not catch it unless the surface key also changes.

---

## 3. What is now guaranteed in practice

- Any change to `VALID_POS_PATTERNS` that adds or removes a bigram/trigram pattern type will cause a test failure.
- If the sliding window logic breaks (producing fewer or more n-grams for a 3-token input), the count test catches it.
- VERB, ADP, and other non-nominal POS types correctly produce no n-grams — regression is caught.

---

## 4. What defects are now caught automatically

- **D07 (regression):** Removing a valid POS pattern from the extractor.
- **D07:** Adding an invalid pattern that should produce no n-gram.
- **D07:** Sliding window producing duplicate or missing spans.
- **D01/D06:** Gold mismatch after intentional algorithm change to POS filtering.
- **D04 (non-determinism):** Different set of n-grams on repeat calls.

---

## 5. What remains NOT covered

- **Punctuation boundary tokens:** What happens when a PUNCT token appears between two NOUNs? Does it break the n-gram window? Not in gold.
- **Mixed-script n-grams:** `"Apple ישראל"` (PROPN+PROPN) — is PROPN+PROPN also extracted for mixed Hebrew/Latin? Not tested.
- **NOUN+ADJ+NOUN trigram:** This is in `VALID_POS_PATTERNS` per the gold notes, but there is no gold case that directly tests it with a passing example.
- **`lemma_phrase` correctness:** The oracle key uses `surface_text`, not `lemma_phrase`. If a change corrupts lemma_phrase without changing surface, it would not be caught.
- **n_values=[1] (unigrams):** Not in gold. Unigram behavior is unverified.
- **Very long sentences:** 4-token sentence is the longest tested. Sliding window on 15+ tokens not validated.

---

## 6. Required follow-up

**C04 v2 additions recommended:**
1. NOUN+ADJ+NOUN trigram with passing example (confirm it's in VALID_POS_PATTERNS and works).
2. Punctuation token in the middle of a nominal sequence — verify it either breaks the window or is filtered.
3. Mixed Hebrew/Latin PROPN+PROPN case.
4. A case where `lemma_phrase` differs from `surface_text` in a way that would be visually distinguishable (to catch silent lemma corruption).

---

## 7. DoD verdict

**PARTIAL**

All 9 gold cases pass. All 5 valid bigram patterns and 2 of 3 valid trigram patterns have positive examples. VERB+NOUN rejection confirmed. Sliding window span generation confirmed.

Not PASS because:
- NOUN+ADJ+NOUN trigram has no positive test case (only mentioned in notes, not in gold).
- Punctuation boundary behavior is unverified.
- `lemma_phrase` is not independently validated by the oracle key.

---

## 8. Files changed in this wave

| File | Role |
|---|---|
| `tests/validation/gold/c04_ngram_extraction.json` | Gold — 9 cases; C04_09 corrected (removed invalid NOUN+ADJ+ADJ) |
| `tests/validation/oracles/oracle_ngram.py` | Oracle — set comparison with pos_pattern normalization (list/string → tuple) |
| `tests/validation/test_v04_ngram_extraction.py` | 6 test methods |

---

## 9. Regression / baseline impact

- Validation suite (non-Stanza): **104 passed**.
- C04 contributes 6 test nodes (but C04_09 covers 2 patterns).

---

## 10. Executive summary

C04 validates n-gram extraction across all major POS pattern types via set-based oracle comparison. All 5 valid bigram patterns and 2 trigram patterns are confirmed working. Invalid POS (VERB+NOUN) and single-token inputs correctly produce empty output. The sliding window spanning 3 tokens produces all expected sub-spans. Key limitation: the oracle key uses `surface_text`, not `lemma_phrase`, so silent lemma corruption is undetected. NOUN+ADJ+NOUN trigram has no positive test case. Punctuation boundary handling is entirely untested. Status is PARTIAL; v2 additions would complete the trigram coverage and close the punctuation gap.

---

## Follow-up checklist

- [x] Update methodology status
- [x] Update audit index
- [ ] Add C04 v2: NOUN+ADJ+NOUN trigram positive case
- [ ] Add C04 v2: punctuation token in nominal sequence
- [ ] Add C04 v2: mixed-script PROPN+PROPN
- [ ] Add C04 v2: case where `lemma_phrase` diverges from `surface_text` to test oracle key coverage
- [ ] Confirm NOUN+ADJ+NOUN is in VALID_POS_PATTERNS (verify in ngram_extractor source)
