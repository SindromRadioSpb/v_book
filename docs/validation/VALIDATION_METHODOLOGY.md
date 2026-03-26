# Validation Methodology — HDLE Premium NLP Pipeline

> Version: 1.3 (updated 2026-03-26: C08 v2 completed — borderline cases + profile contract; count 156→174)
> Scope: Reproducible, database-free validation of the Hebrew NLP extraction pipeline.

---

## 1. Purpose

This methodology enables any developer to verify that the NLP extraction pipeline
produces correct, deterministic output **without** a populated production database.
It operates on pre-computed gold corpora (JSON) and pure unit-level oracle calls.

**Goals:**
- Catch regressions when pipeline components are modified
- Serve as executable specification for each algorithm
- Enable CI/CD validation without GPU or Stanza model download

---

## 2. Architecture — Three-Source Oracle

Each test category has three independent verification sources:

| Source | Role |
|--------|------|
| **Gold corpus** (`tests/validation/gold/`) | Pre-annotated expected outputs |
| **Invariant checker** | Mathematical / logical invariants that must always hold |
| **Differential comparator** | Before/after comparison across extraction modes |

---

## 3. Pipeline Stage Coverage

| Stage | Corpus ID | Oracle Module | Test File | Stanza? |
|-------|-----------|---------------|-----------|---------|
| Sentence splitting | C01 | oracle_sentence | test_v01 | No |
| Tokenization + morphology | C02 | (deferred) | (deferred) | **Yes** |
| Lemma aggregation | C03 | oracle_lemma_agg | test_v03 | No |
| N-gram extraction | C04 | oracle_ngram | test_v04 | No |
| NP chunk extraction | C05 | oracle_np | test_v05 | No |
| Canonicalization | C06 | oracle_canonicalization | test_v06 | No |
| Association measures | C07 | oracle_measures | test_v07 | No |
| Noise classification | C08 | oracle_noise | test_v08 | No |
| Noise borderline + profile contract | C08v2 | oracle_noise | test_v08v2 | No |
| Extraction modes | C09 | (integration) | test_v09 | No |
| TM projection (lemma kind) | CTM | oracle_tm | test_vtm | No |
| TM user_dict pathway | CTM2 | (integration) | test_vtm2 | No |
| Full pipeline round-trip | C10 | (deferred) | (deferred) | **Yes** |

C02 and C10 require Stanza and a pre-downloaded Hebrew model. They are marked
`@pytest.mark.requires_stanza` and skipped if Stanza is unavailable.

---

## 4. Gold Corpus Format

Each corpus file is a JSON document under `tests/validation/gold/`:

```json
{
  "corpus_id": "C04",
  "description": "...",
  "notes": "...",
  "cases": [
    {
      "case_id": "C04_01",
      "description": "...",
      "input": { ... },
      "expected_ngrams": [ ... ],
      "expected_count": 1
    }
  ]
}
```

**Invariants:** Corpus files that include an `"invariants"` key specify
mathematical properties that must hold for all outputs (e.g. `docs <= freq`).

---

## 5. Oracle Result Contract

Every oracle function returns an `OracleResult`:

```python
@dataclass
class OracleResult:
    case_id: str          # e.g. "C04_01"
    match: bool           # True iff all expected values match actual
    expected: Any         # Expected value(s)
    actual: Any           # Actual value(s) from implementation
    missing: list         # Items expected but not found in actual
    extra: list           # Items found in actual but not expected
    notes: str            # Human-readable context
```

A test passes iff `result.match == True`.

---

## 6. Running the Validation Suite

### All non-Stanza tests (fast, no GPU required)
```powershell
cd E:\projects\Project_Vibe\V_book
.\.venv\Scripts\python.exe -m pytest tests/validation/ -v -k "not v02 and not stanza"
```
Expected: **174 passed, 0 failed** (as of C08 Wave 2, 2026-03-26).

### Stanza-dependent tests (requires model)
```powershell
.\.venv\Scripts\python.exe -m pytest tests/validation/ -v -m requires_stanza
```

### Full regression (excludes validation to avoid torch DLL issue in headless context)
```powershell
.\.venv\Scripts\python.exe -m pytest --ignore=tests/validation -x -q
```
Expected: **1751 passed** (baseline post-Epics 4/5/6/7, C09 wave).

---

## 7. Acceptance Criteria

A pipeline component is considered **validated** when:

1. All gold cases for its corpus ID pass
2. All invariant tests pass
3. Determinism test passes (same input → same output on two independent calls)
4. No regressions in the broader test suite (1751 baseline)

---

## 8. Known Limitations and Deferrals

| Item | Status | Reason |
|------|--------|--------|
| C02 tokenization | Deferred | Requires Stanza + Hebrew model |
| C10 full pipeline | Deferred | Requires Stanza + populated corpus |
| C09 extraction modes | **Validated** (2026-03-26) | 23 tests, In-Memory SQLite; TM creation layer not in scope |
| TM projection (lemma) | **Partial** (2026-03-26) | Wave 1: 27 tests (kind='lemma' batch materialize); Wave 2: 25 tests (user_dict pathway, _attach_source_links, tm_global propagation). Inline_edit + batch_MT deferred (require UI/worker fixtures). |
| Noise classification | **Validated** (2026-03-26) | Wave 2: borderline inputs, ratio-check boundary (len>2), phrase ≥50% inclusive, profile architecture contract. Profiles not implemented as code — classifier is profile-agnostic. |
| Canonicalization: prefix semantics | Known limitation | מדינה → דינה (מ stripped as prefix) |
| Dice at c_xy=0 | By design | Returns 0.0, not None (n not a Dice parameter) |

---

## 9. Corpus Audit Index

Each corpus has a post-wave audit document tracking validated contracts, gaps, and required follow-ups.

See: `docs/validation/AUDIT_INDEX.md` for the full status map.

Per-corpus audit docs: `docs/validation/audits/CXX_AUDIT.md`

---

## 10. Adding New Gold Cases

1. Add a case dict to the relevant `tests/validation/gold/cXX_*.json`
2. Run oracle manually to verify expected values match actual
3. If adding a new corpus (CXX), add oracle module + integration test
4. Run full validation suite: `pytest tests/validation/ -v -k "not stanza"`
5. Update this document if acceptance criteria change
