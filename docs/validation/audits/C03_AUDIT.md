# C03 — Audit Report: Lemma Aggregation

> Wave completed: 2026-03-26
> Status: **PARTIAL**
> Auditor: post-wave automated audit

---

## 1. Scope of this wave

**What was done:**
- Gold corpus defined: 1 multi-document scenario with 3 docs / 12 tokens / 5 distinct lemmas (`c03_lemma_aggregation.json`).
- Oracle implemented: `tests/validation/oracles/oracle_lemma_agg.py` — `simulate_aggregation()` (pure Python, no DB, no Stanza). Verifies freq per lemma, docs per lemma, and three invariants.
- Integration tests: `tests/validation/test_v03_lemma_aggregation.py` — 12 test methods covering individual lemma checks, invariants, and total token count.
- All 12 tests pass. No Stanza required.

**What was NOT in scope:**
- Multiple different corpus configurations (only 1 scenario in gold)
- Edge cases: lemma appearing in every document vs. exactly one
- Conflicting freq/docs inputs (where a buggy implementation might produce docs > freq)
- Surface form aggregation — the oracle takes pre-lemmatized tokens; it does not test that different surface forms map to the same lemma
- Performance on large corpora (thousands of documents)

---

## 2. Product contract now validated

**Contract (backed by gold + oracle + tests):**

| Claim | Gold evidence | Oracle check |
|---|---|---|
| `freq` = total token occurrences across all docs | C03 corpus (ילד: 3+1=4) | exact integer comparison |
| `docs` = count of distinct documents where lemma appears | C03 corpus (ילד: 2 docs, גדול: 3 docs) | exact integer comparison |
| Same lemma appearing multiple times in one doc is counted once in `docs` | ילד in DOC_01 (3×) → docs=1 for that doc | exact comparison |
| Invariant `docs ≤ freq` holds for all lemmas | All 5 lemmas | `test_invariants` |
| No duplicate lemma entries in aggregate | 5 distinct lemmas | `no_duplicate_lemma` invariant |
| `sum(freq)` == total token count | 12 tokens → sum=12 | `total_tokens_match` invariant |
| Determinism: same documents → same aggregates | All cases | `test_determinism` |

---

## 3. What is now guaranteed in practice

- Any implementation change that breaks the freq-counting or doc-counting logic for the 3-document scenario will be caught.
- The `docs ≤ freq` invariant is **structurally enforced** by the oracle on every run — not just on gold cases. If a refactored aggregation accidentally produces docs=3 when freq=2, it fails immediately.
- The total token sum invariant catches double-counting bugs (a common failure mode in aggregation rewrites).

**Important scope note:** The oracle simulates the aggregation algorithm in pure Python. It does **not** call the actual DB-level aggregation service. What is proven: the algorithm is correct for the gold scenario. What is not proven: the DB service produces the same output as the algorithm.

---

## 4. What defects are now caught automatically

- **D07 (regression):** Any code change that alters freq counting (e.g., forgetting to count repeated occurrences in one doc).
- **D03 (invariant violation):** If `docs > freq` appears in any output — caught by invariant test regardless of gold case.
- **D07:** Docs counted as 2 when lemma appears in only 1 document.
- **D07:** Total freq sum not matching expected token count (double-counting regression).
- **D04 (non-determinism):** Same document set producing different aggregates.

---

## 5. What remains NOT covered

- **Only 1 gold scenario** (3 docs, 12 tokens, 5 lemmas). A corpus with 1000 documents or a lemma appearing in every document is not validated.
- **Frequency vs. docs conflict edge cases:** A buggy implementation that counts docs=freq for every lemma would pass the gold case but violate the invariant — however the invariant test IS present, so this class is partially covered.
- **Zero-frequency lemmas:** What happens if a lemma is in the vocabulary but appears 0 times? Not tested.
- **Surface form aggregation:** The oracle takes pre-lemmatized token lists. Whether `ילד`, `ילדים`, `ילדה` all correctly map to lemma `ילד` before reaching the aggregation stage is NOT tested here — that belongs to C02.
- **DB-level aggregation:** The oracle uses a pure Python simulation. The actual service writing to SQLite is not called in C03 tests.

---

## 6. Required follow-up

**Gold expansion (C03 v2):**
1. Add a corpus where one lemma appears in **every** doc (verify docs = doc_count_max).
2. Add a corpus where a lemma appears exactly **once** in exactly **one** doc (freq=1, docs=1 — hapax case).
3. Add a corpus with **overlapping multi-frequency** lemmas to stress-test the double-counting guard.
4. Add an **empty document** (no tokens) — what happens to docs count?

**Not currently needed:** DB-level integration test for aggregation service (belongs to a different test layer, not validation corpus).

---

## 7. DoD verdict

**PARTIAL**

All 12 tests pass. Three invariants are enforced. The algorithm is correct for the tested scenario.

Not PASS because:
- Only 1 corpus scenario; no edge cases for hapax, all-doc lemma, or empty document.
- Oracle does not call the actual DB aggregation service — this is intentional (DB-free design) but means the full pipeline is not covered.

---

## 8. Files changed in this wave

| File | Role |
|---|---|
| `tests/validation/gold/c03_lemma_aggregation.json` | Gold — 1 corpus, 5 expected aggregates, 3 invariants |
| `tests/validation/oracles/oracle_lemma_agg.py` | Oracle — pure Python simulation + invariant checks |
| `tests/validation/test_v03_lemma_aggregation.py` | 12 tests: individual lemma checks + invariants + determinism |

---

## 9. Regression / baseline impact

- Validation suite (non-Stanza): **104 passed**.
- C03 contributes 12 test nodes.
- No environment caveats.

---

## 10. Executive summary

C03 validates the freq/docs aggregation algorithm against a single 3-document gold scenario and enforces three structural invariants: `docs ≤ freq`, no duplicate lemma entries, and total token count match. The oracle is pure Python and requires no DB or Stanza. All tests pass. The critical limitation is coverage breadth: only one scenario, no hapax edge case, no all-document lemma case. The structural invariants are the strongest part of this corpus — they run on every output, not just gold cases, meaning a newly introduced double-counting bug would fail even without expanding gold. The gap is that the DB-level aggregation service is not called; what is proven is the algorithm, not the full pipeline. C03 v2 should add 3–4 edge case scenarios before the aggregation layer is considered fully validated.

---

## Follow-up checklist

- [x] Update methodology status
- [x] Update audit index
- [ ] **Add C03 v2 gold scenarios: hapax lemma, all-doc lemma, empty document**
- [ ] Decide whether DB-level aggregation service test belongs in C03 or a separate integration suite
- [ ] Confirm no assumption changes for downstream C04/C05 (they don't depend on C03 oracle outputs)
