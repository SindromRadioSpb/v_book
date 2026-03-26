# Defect Playbook — NLP Validation Failures

> Use this guide when a test in `tests/validation/` fails.
> Each section maps a failure pattern to a root cause and fix procedure.

---

## Defect Taxonomy

| Code | Category | Typical Symptom |
|------|----------|-----------------|
| D01 | Gold mismatch | Expected ≠ actual; implementation changed |
| D02 | Key format mismatch | Oracle key-set comparison fails (e.g. list vs string) |
| D03 | Invariant violation | `docs > freq`, `match=False` from invariant check |
| D04 | Non-determinism | Same input produces different output on two calls |
| D05 | Deferred component | `requires_stanza` test fails because model unavailable |
| D06 | Stale gold | Gold was written speculatively; implementation differs by design |
| D07 | Regression | Previously passing test now fails after code change |

---

## D01 — Gold Mismatch (implementation changed)

**Symptom:** `AssertionError: Case CXX_YY: expected='foo', actual='bar'`

**Procedure:**
1. Check git log for recent changes to the relevant service/extractor
2. Determine if the change is intentional (algorithm update) or a bug
3. If intentional: update gold JSON to match new behavior; update test docstrings
4. If a bug: revert the implementation change; do not touch gold

**Example:** After changing prefix stripping in `canonicalizer.py`,
`C06_03` may fail → update `expected_canonical` in `c06_canonicalization.json`.

---

## D02 — Key Format Mismatch

**Symptom:** `missing=[['ספר לימוד', 2, ('NOUN', 'NOUN')]]`, `extra=[['ספר לימוד', 2, 'NOUN|NOUN']]`
(same data, different representation)

**Procedure:**
1. Locate the `_*_key()` function in the oracle module
2. Add normalization to convert both gold and actual to the same canonical type
3. Example fix (oracle_ngram.py):
   ```python
   if isinstance(pos, str):
       pos = tuple(pos.split("|"))
   ```

---

## D03 — Invariant Violation

**Symptom:** `INVARIANT VIOLATED: lemma 'X' docs(5) > freq(3)`

**Procedure:**
1. This is always a real bug — `docs <= freq` must hold by definition
2. Locate the aggregation write path (service layer + DB query)
3. Check for double-counting in `doc_count` computation
4. Check if `freq` is being reset without updating `doc_count`

---

## D04 — Non-Determinism

**Symptom:** `AssertionError: compute_pmi is non-deterministic`

**Procedure:**
1. Check for use of `set` or `dict` iteration in the function (ordering not guaranteed)
2. Check for random-number generators or `os.urandom()`
3. Check for shared mutable state (class-level caches, module globals)
4. Fix: use `sorted()` where ordering matters; avoid side effects

---

## D05 — Stanza Model Unavailable

**Symptom:** `pytest.skip("Stanza 'he' model not available")`

**Procedure:**
1. This is expected in CI environments without GPU/model download
2. To run locally: download the Hebrew Stanza model
   ```python
   import stanza
   stanza.download('he')
   ```
3. Do not treat Stanza skips as failures in CI

---

## D06 — Stale Gold

**Symptom:** Test fails; investigation shows gold was written speculatively
and never matched actual implementation.

**Procedure:**
1. Run the oracle interactively to capture actual values:
   ```python
   from app.domain.term_extraction.canonicalizer import canonicalize_hebrew_term
   print(canonicalize_hebrew_term("מְדִינָה", "מדינה"))  # → "דינה"
   ```
2. Update gold to match actual (D06 does NOT imply a bug)
3. Add a `"notes"` field explaining the discrepancy (e.g. "known limitation")
4. Document in `VALIDATION_METHODOLOGY.md §8` if it represents a known edge case

---

## D07 — Regression

**Symptom:** Test was passing on `main`; fails on a feature branch.

**Procedure:**
1. Run `git bisect` to find the introducing commit
2. Check if the regression is in the NLP component or in the oracle/gold
3. If in NLP component: fix the implementation; do not relax gold
4. If in oracle: the oracle may have a bug → fix the oracle, not the gold

---

## Quick Reference — Oracle Modules

| Oracle | What it calls | Key comparison |
|--------|---------------|----------------|
| oracle_sentence | SentenceSplitter.split() | set of sentence strings |
| oracle_ngram | extract_ngrams_from_sentence() | (surface, n, pos_tuple) |
| oracle_np | extract_np_chunks_from_sentence() | (surface, length) |
| oracle_canonicalization | canonicalize_hebrew_term() | canonical string |
| oracle_canonicalization | choose_representative_term() | representative string |
| oracle_measures | compute_pmi/dice/llr/tscore() | float with tolerance |
| oracle_noise | classify_text() / classify_phrase() | entity_class, is_noise, noise_reason |
| oracle_lemma_agg | simulate_aggregation() | freq + docs per lemma |
