# C05 — Audit Report: NP Chunk Extraction

> Wave 1 completed: 2026-03-26 — core pipeline + STOP_POS segmentation + DET merge + min/max_len
> Wave 2 completed: 2026-03-26 — DET non-first, multiple DET, ADJ-led NP, C05_07 exact match
> Status: **VALIDATED**
> Auditor: post-wave automated audit

---

## 1. Scope of this wave

### Wave 1 (2026-03-26) — core pipeline

**What was done:**
- Gold corpus: 7 cases covering NOUN+NOUN, NOUN+ADJ+NOUN, STOP_POS breaking, DET article merging (`merge_standalone_articles`), max_len enforcement, all-STOP_POS empty result, and a max-length (5-token) NP.
- Oracle: `tests/validation/oracles/oracle_np.py` — calls `extract_np_chunks_from_sentence()`, normalizes actual using `n` key for span length, compares `(surface_text, length)` key sets.
- Tests: `tests/validation/test_v05_np_extraction.py` — 6 test methods.
- All tests pass. No Stanza required (pre-tokenized input).
- Gold calibration: C05_04 updated — DET `"ה"` + `"ילד"` merge → `"הילד"` (surfaces corrected for `merge_standalone_articles` behavior).

### Wave 2 (2026-03-26) — DET positioning, multiple DET, ADJ-led NP, C05_07 exact match

**What was done:**
- Gold corpus: `tests/validation/gold/c05v2_np_extraction.json` — 3 cases.
- Gold update: `c05_np_extraction.json` C05_07 converted from subset match (`expected_chunks_contain`, min_count=7) to exact match (`expected_chunks`, 9 chunks). Classification: Stale gold correction (exact count was derivable from code; was not enumerated in Wave 1).
- Tests: `tests/validation/test_v05v2_np_extraction.py` — 12 tests across 5 test classes.
- No implementation changes — all gaps were gold/test coverage gaps.

**Key findings confirmed from source code (np_extractor.py):**

- **DET in non-first position** (`_is_valid_np_span`, lines 172–175): DET is NOT in STOP_POS, so it never breaks the segment. But for non-first tokens, the check is `pos not in CORE_NP_POS and pos not in MODIFIER_POS` — DET is in neither set → any span where DET is at position 1+ is REJECTED by design. Sub-span starting AT the DET (DET as first token of sub-span) remains valid.
- **Multiple DET**: For [ה, ילד, ה, גדול] — only the first [DET, NOUN] bigram is valid. Second DET blocks all bridge spans that would need DET at a non-first position.
- **ADJ-led NP span**: `is_valid_np_token(ADJ, is_first=True)` → True (ADJ ∈ MODIFIER_POS). ADJ can open a segment. [ADJ, NOUN] and [ADJ, NOUN, NOUN] are both valid.
- **C05_07 exact set**: Full enumeration confirms 9 chunks for [NOUN×3, ADJ×2] input. ADJ+ADJ bigram at positions [3,4] has no CORE_NP → rejected. No phantom chunks possible — oracle now enforces exact set.

**What remains NOT in scope after Wave 2:**
- Token indices validation (oracle key is `(surface_text, length)`, not position)
- min_len=1 unigram NP behavior
- Interaction with C04 on overlapping token sequences
- Very long NPs (>5 tokens, blocked by max_len by design)

---

## 2. Product contract now validated

**NP chunk extraction pipeline (backed by gold + tests):**

| Claim | Gold evidence | Oracle |
|---|---|---|
| NOUN+NOUN NP | C05_01 | exact set key match |
| NOUN+ADJ+NOUN sub-spans (3 chunks) | C05_02 | exact set key match |
| STOP_POS (VERB) breaks segment | C05_03 | exact set key match |
| merge_standalone_articles: "ה"+NOUN → merged surface | C05_04 | merged string in result |
| max_len=2 excludes spans of length 3+ | C05_05 | exact set key match |
| all-STOP_POS → no chunks | C05_06 | empty actual set |
| 5-token all-nominal input: exactly 9 chunks (no phantom chunks) | C05_07 (exact) | exact set key match |
| DET at non-first position → span REJECTED | C05v2_01 | exact set key match + inline _is_valid_np_span |
| Sub-span starting AT DET (DET as first token) → VALID | C05v2_01 | exact set key match |
| Second DET blocks all bridge spans | C05v2_02 | exact set key match + count |
| ADJ (MODIFIER_POS) can open a segment | C05v2_03 | exact set key match + inline |
| ADJ+ADJ alone (no CORE_NP) → REJECTED | inline test | _is_valid_np_span(["ADJ","ADJ"]) → False |

**Oracle comparison:**
- All cases (including updated C05_07) now use exact set match on `(surface_text, length)` keys. Both missing and extra chunks are detected.
- Residual blind spot: token indices/offsets not validated. Not a primary use case gap (NP extraction is used for term clustering by surface form, not position).

---

## 3. What is now guaranteed in practice

- Any regression in STOP_POS segmentation will fail immediately.
- `merge_standalone_articles` behavior (standalone ה + NOUN → merged surface) is a verified, documented contract.
- DET positioning contract: DET allowed only as first token of a span. Any span with DET at non-first position is rejected. Sub-spans starting at DET are valid.
- Multiple DET: only the first [DET, NOUN] bigram survives; second DET prevents bridge spans.
- ADJ-led NPs: confirmed valid by design.
- The 5-token case is now exact-match: phantom chunks cannot appear silently.

---

## 4. What defects are now caught automatically

- **D07 (regression):** STOP_POS list modified (VERB allowed in NP span).
- **D07:** `merge_standalone_articles` no longer merging standalone ה.
- **D07:** min_len or max_len boundaries shifting.
- **D07:** `_is_valid_np_span` allowing DET at non-first position (would produce extra chunks in C05v2_01/02).
- **D07:** Phantom extra chunks appearing in any all-nominal sequence (C05_07 is now exact).
- **D07:** ADJ incorrectly removed from MODIFIER_POS (would break C05v2_03).
- **D01/D06:** Gold mismatch after intentional algorithm change.
- **D04 (non-determinism):** Different chunk sets on repeat calls.

---

## 5. What remains NOT covered

- **Token indices:** Oracle key = `(surface_text, length)`. Token indices are NOT validated. Not a blocking gap for primary use cases (term clustering uses surface form).
- **min_len=1 unigrams:** Architecturally supported by `_is_valid_np_span` but not in gold.
- **Interaction with C04:** No test for shared token sequences producing both n-grams and NP chunks (they are independent extractors).
- **NPs > 5 tokens:** Blocked by max_len=5 design parameter — not a gap.

---

## 6. Required follow-up

**No mandatory follow-up after Wave 2.**

Optional (low priority):
- If token index validation becomes relevant to downstream use, enhance oracle to include position-based key.
- min_len=1 unigram case if unigram NPs are added to the product.

---

## 7. DoD verdict

**VALIDATED**

After Wave 2: 24 test nodes pass (12 Wave 1/existing + 12 Wave 2). All primary contracts confirmed:
- Core pipeline: NOUN+NOUN, NOUN+ADJ+NOUN sub-spans, STOP_POS segmentation, DET merge, min/max_len, all-STOP_POS empty
- DET positioning: non-first DET rejection + sub-span validity — confirmed from code + gold
- Multiple DET: bridge-span blocking confirmed from code + gold
- ADJ-led NP: MODIFIER_POS opens segment — confirmed from code + gold
- C05_07 exact match: exactly 9 chunks, no phantom chunks possible

VALIDATED (not PARTIAL) because:
- All Wave 1 coverage gaps are now closed with gold evidence and exact oracle match
- All DET/ADJ behavior claims are confirmed from actual code path, not inferred
- Phantom-chunk silent gap is closed: C05_07 converted to exact match
- Residual non-coverage points (token indices, min_len=1) are not silent defect classes for primary use cases

---

## 8. Files changed in this wave

### Wave 1
| File | Role |
|---|---|
| `tests/validation/gold/c05_np_extraction.json` | Gold — 7 cases; C05_04 corrected for merge_standalone_articles |
| `tests/validation/oracles/oracle_np.py` | Oracle — n key normalization; exact + subset match modes |
| `tests/validation/test_v05_np_extraction.py` | 6 test methods |

### Wave 2
| File | Role |
|---|---|
| `tests/validation/gold/c05_np_extraction.json` | C05_07 converted: subset → exact match, 9 chunks enumerated (Stale gold correction) |
| `tests/validation/gold/c05v2_np_extraction.json` | 3 edge cases (DET non-first, multiple DET, ADJ-led NP) |
| `tests/validation/test_v05v2_np_extraction.py` | 12 tests across 5 test classes |
| `docs/validation/audits/C05_AUDIT.md` | Updated: Wave 2 + VALIDATED verdict |
| `docs/validation/AUDIT_INDEX.md` | Updated: C05 Partial → Validated, baseline 211→223 |
| `docs/validation/VALIDATION_METHODOLOGY.md` | Updated: v1.6→v1.7, C05v2 row, count 211→223 |

---

## 9. Regression / baseline impact

- Validation suite (non-Stanza): **223 passed** (211 prior + 12 C05v2).
- C05 total: 24 test nodes (12 Wave 1 + 12 Wave 2).
- No implementation changes → zero regression risk in main baseline (1751).

---

## 10. Executive summary

C05 Wave 1 validated the NP extraction core pipeline: STOP_POS segmentation, DET merge, min/max_len, all-STOP_POS empty result. The `merge_standalone_articles` contract (standalone ה + NOUN → merged surface) was documented and tested. Key gap: C05_07 used subset match (min_count=7, no phantom-chunk detection).

C05 Wave 2 closed all remaining gaps — all were coverage gaps, not code defects. DET in non-first position: confirmed from `_is_valid_np_span` lines 172–175 — DET is not in CORE_NP_POS or MODIFIER_POS, so non-first DET → span rejected; sub-span starting at DET remains valid. Multiple DET: second DET blocks all bridge spans; only first [DET, NOUN] bigram extracted. ADJ-led NP: ADJ ∈ MODIFIER_POS, `is_valid_np_token(ADJ, is_first=True)` → True — opens segments by design. C05_07: exact enumeration yields 9 chunks (ADJ+ADJ rejected for no CORE_NP); converted to exact match — phantom chunks cannot appear silently.

Status advances from PARTIAL to **VALIDATED**: all DET/ADJ positioning contracts are documented and pinned; phantom-chunk gap is closed; no silent defect class remains for primary NP extraction use cases.

---

## Follow-up checklist

- [x] Update methodology status
- [x] Update audit index
- [x] Add C05 v2: DET in non-first position (C05v2_01)
- [x] Add C05 v2: multiple standalone DET tokens (C05v2_02)
- [x] Convert C05_07 to exact match (Stale gold correction)
- [x] Add C05 v2: ADJ-led NP span (C05v2_03)
- [x] Verify DET/ADJ behavior from actual NP code path (confirmed from np_extractor.py)
