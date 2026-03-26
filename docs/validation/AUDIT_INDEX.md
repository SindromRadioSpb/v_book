# Validation Audit Index

> Last updated: 2026-03-27 (C02 Wave 6a — infra prep)
> Maintainer: update after every completed corpus wave
> Rule: status "Validated" requires all tests passing + core contract proven; "Partial" means tests pass but known contract gaps exist; "Deferred" means no tests yet

---

## Current corpus status map

| Corpus | Stage | Status | Audit doc | Next required action | Last meaningful update | Notes |
|---|---|---|---|---|---|---|
| C01 | Sentence splitting | Validated | [C01_AUDIT.md](audits/C01_AUDIT.md) | Optional: Latin abbreviation expansion, ellipsis exception | 2026-03-26 | Wave 2: abbreviation bug fixed + borderline cases; known limitations documented (Latin abbrev, ellipsis) |
| C02 | Tokenization + morphology | Infra Prepared | [C02_AUDIT.md](audits/C02_AUDIT.md) | **C02 Wave 6b** (mandatory): lemma paradigm gold, POS consistency, multi-sentence, morph features, determinism | 2026-03-27 | Wave 6a: stanza 1.11.1 installed; he/ model available; StanzaEngine wired; oracle + gold skeleton + 10 smoke tests; requires_stanza marker registered; DET prefix detachment pinned |
| C03 | Lemma aggregation | Validated | [C03_AUDIT.md](audits/C03_AUDIT.md) | Optional: DB-level aggregation service integration test if service becomes independently testable | 2026-03-26 | Wave 2: hapax in isolation, all-doc lemma (non-uniform freq), empty document, stress, all-empty corpus; parametrized invariants (3×6=18); oracle extra-aggregate check |
| C04 | N-gram extraction | Validated | [C04_AUDIT.md](audits/C04_AUDIT.md) | Optional: unigram extraction if added, nikud in pre-tokenized input | 2026-03-26 | Wave 2: NOUN+ADJ+NOUN trigram positive case, PUNCT boundary, mixed-script PROPN+PROPN, validate_ngram_lemmas() secondary oracle (lemma divergence) |
| C05 | NP chunk extraction | Validated | [C05_AUDIT.md](audits/C05_AUDIT.md) | Optional: token index validation if position-based clustering added | 2026-03-26 | Wave 2: DET non-first rejection, multiple DET bridge blocking, ADJ-led NP, C05_07 exact match (9 chunks, no phantom gap) |
| C06 | Canonicalization | Validated | [C06_AUDIT.md](audits/C06_AUDIT.md) | Optional: morphological analysis to fix over-stripping | 2026-03-26 | Wave 2: prefix כ/ש, multi-token nikud, mixed script, geresh, collision (כמות↔מות) all documented |
| C07 | Association measures | Validated | [C07_AUDIT.md](audits/C07_AUDIT.md) | C07 v2 (optional): trigram None case, T-score positive, large N | 2026-03-26 | Core measure semantics proven; Dice n-independence verified; LLR at c_xy=0 verified |
| C08 | Noise classification | Validated | [C08_AUDIT.md](audits/C08_AUDIT.md) | Optional: profile filter layer if implemented | 2026-03-26 | Wave 2: borderline cases, ratio-check boundary, phrase 50% inclusive, profile architecture contract. Key finding: profiles not implemented as code — classifier is profile-agnostic. |
| C09 | Extraction modes | Validated | [C09_AUDIT.md](audits/C09_AUDIT.md) | **Build TM validation corpus** (mandatory next wave) | 2026-03-26 | State machine fully verified; store_hapax + min_freq semantics confirmed; TM creation not in scope |
| C10 | Full pipeline round-trip | Deferred | — | Build after C02 closure and TM validation corpus | 2026-03-26 | Requires Stanza + populated corpus; depends on C02 and TM layer being validated first |
| TM | TM projection validation | Partial | [TM_AUDIT.md](audits/TM_AUDIT.md) | **TM v3** (optional): test inline_edit + batch_MT pathways | 2026-03-26 | Wave 1: kind='lemma' materialize (27 tests). Wave 2: user_dict pathway + _attach_source_links + tm_global propagation (25 tests). 52 total. Inline_edit and batch_MT require UI/worker fixtures — deferred. |

---

## Priority order for next wave

1. **C02 Wave 6b** — lemma paradigm gold, POS consistency across inflections, multi-sentence, morph feature coverage, determinism
2. **C10** — deferred until C02 + TM are closed

---

## Mandatory maintenance rules

1. After every completed corpus wave, create or update its audit doc in `docs/validation/audits/`.
2. After every completed corpus wave, update this index (status, last update, next required action).
3. If VALIDATION_METHODOLOGY.md status is stale (e.g., shows "test pending" for a completed corpus), update it in the same wave.
4. If a new edge case family is discovered, record in the audit doc whether it is:
   - Bug → fix implementation, do not update gold
   - Stale gold (D06) → update gold with notes
   - Known limitation (by design) → document in gold notes + VALIDATION_METHODOLOGY.md §8
5. If a corpus clearly needs v2, it is NOT optional — it must appear as "Next required action" here and in the corpus audit doc.
6. A corpus with status "Validated" means: all tests pass AND the core contract is proven AND there are no silent defect classes for the primary use cases. Edge cases may be open but must not affect primary correctness claims.

---

## Test baseline (as of 2026-03-26)

| Suite | Count | Status |
|---|---|---|
| Main (--ignore=tests/validation) | 1751 passed, 0 failed | Green |
| Validation non-Stanza | 247 passed, 0 failed | Green (unchanged — C02 deselected by -k filter) |
| Validation Stanza (C02, C10) | Skipped (model unavailable) | Expected |
| Validation C02 (requires stanza + he model) | 10 passed (or 10 skipped if model unavailable) | Green when infra available |
| Total | 2008 when all available (1751 main + 247 non-Stanza + 10 C02) | No combined run due to torch DLL in headless context |
