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

**Symptom:** `pytest.skip("stanza not installed or Hebrew 'he' model directory not found")`
or: `pytest.skip("Stanza Hebrew model unavailable: ...")`

**Procedure:**

1. This is expected in CI environments without model download. Do NOT treat C02 skips as failures in CI.

2. Check which skip path triggered:

   **Path A — stanza not installed:**
   ```powershell
   cd E:\projects\Project_Vibe\V_book
   .\.venv\Scripts\python.exe -c "import stanza; print(stanza.__version__)"
   ```
   If ImportError: install stanza:
   ```powershell
   .\.venv\Scripts\pip.exe install "stanza>=1.7.0"
   ```

   **Path B — he/ model directory missing:**
   ```powershell
   .\.venv\Scripts\python.exe -c "
   from tests.validation.conftest import _stanza_he_model_available
   print('model available:', _stanza_he_model_available())
   "
   ```
   If False: download the Hebrew model (~700 MB):
   ```powershell
   .\.venv\Scripts\python.exe -c "import stanza; stanza.download('he')"
   ```
   Default cache location (Windows):
   ```
   C:\Users\<user>\AppData\Local\StanfordNLP\stanza\Cache\<version>\resources\he\
   ```
   Override with `$env:STANZA_HOME = "D:\stanza_models"` before downloading.

   **Path C — model directory present but pipeline load fails:**
   Run the preflight:
   ```powershell
   .\.venv\Scripts\python.exe -c "
   from app.infra.nlp_engines.stanza_engine import StanzaEngine
   e = StanzaEngine(use_gpu=False)
   print('OK, version:', e.get_version())
   "
   ```
   If this fails: model files may be corrupt. Re-download: delete `he/` dir and repeat step B.

3. Full setup guide: `docs/validation/STANZA_HE_PREP.md`

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

## Architectural Finding — TM Projection Is Not Automatic

Confirmed by Wave 1 repo audit (2026-03-26):

**`TermExtractionService` does NOT create `tm_entry` rows.**

After extraction completes (term_cluster + ngram tables updated), the TM is not automatically populated. TM projection is a separate, explicitly-triggered step with four pathways:

| Pathway | Function | Kind | Idempotent |
|---|---|---|---|
| Batch lemma materialize | `translation_admin_service.materialize_project_lemmas_to_tm` | lemma | Yes (INSERT OR IGNORE) |
| User dict add | `user_dictionary_service._materialize_tm_entries_for_items` | all | Yes (check-then-insert) |
| Inline edit | `terms_view.py:1817` | term_cluster | Yes (check-then-insert) |
| Batch MT | `batch_mt_translate_service._write_term_cluster/lemma` | term_cluster, lemma | Yes (check-then-insert) |

**No bulk projection exists for `kind='term_cluster'`** — that pathway requires user action.

If a test expects TM rows after extraction but finds none: this is by design, not a defect.

---

## Quick Reference — Oracle Modules

| Oracle | What it calls | Key comparison |
|--------|---------------|----------------|
| oracle_sentence | SentenceSplitter.split() | ordered list of sentence strings (order-sensitive) |
| oracle_ngram | extract_ngrams_from_sentence() | (surface, n, pos_tuple) |
| oracle_np | extract_np_chunks_from_sentence() | (surface, length) |
| oracle_canonicalization | canonicalize_hebrew_term() | canonical string |
| oracle_canonicalization | choose_representative_term() | representative string |
| oracle_measures | compute_pmi/dice/llr/tscore() | float with tolerance |
| oracle_noise | classify_text() / classify_phrase() | entity_class, is_noise, noise_reason |
| oracle_lemma_agg | simulate_aggregation() | freq + docs per lemma |
| oracle_token_morph | validate_token_morphology() | token count, text, pos, lemma, morph_contains (partial), morph (exact) |
