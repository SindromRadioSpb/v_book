# C02 — Audit Report: Tokenization and Morphology

> Wave 6a completed: 2026-03-27 — infrastructure preparation; 10 smoke tests
> Status: **INFRA PREPARED — IMPLEMENTATION PENDING**
> Auditor: post-wave automated audit

---

## 1. Scope of this wave

### Wave 6a (2026-03-27) — Infrastructure preparation

**What was done:**
- Confirmed: `stanza 1.11.1` installed (core dep in `pyproject.toml`).
- Confirmed: Hebrew model available at `%LOCALAPPDATA%\StanfordNLP\stanza\Cache\1.11.0\resources\he\` (~696 MB, processors: tokenize, pos, lemma, depparse, ner, backward_charlm, forward_charlm).
- Confirmed: `StanzaEngine` at `app/infra/nlp_engines/stanza_engine.py` wraps `stanza.Pipeline(lang="he", processors="tokenize,pos,lemma")` into `list[Sentence[Token(text, lemma, pos, morph)]]`.
- `requires_stanza` marker registered in `pytest.ini`.
- `conftest.py` updated: `_stanza_he_model_available()` added (cheap filesystem check); `requires_stanza` updated to use it (was: package-only check; now: package + model directory).
- Oracle skeleton: `tests/validation/oracles/oracle_token_morph.py` — `validate_token_morphology()` calls `StanzaEngine.process()`, compares token count, text, pos, lemma, morph_contains (partial), morph (exact optional).
- Gold skeleton: `tests/validation/gold/c02_token_morph.json` — 3 smoke cases calibrated against stanza 1.11.1. Contains `TODO_wave_6b` section documenting what implementation wave must cover.
- Tests: `tests/validation/test_v02_token_morph.py` — 10 tests, all pass when stanza + model available, all skip otherwise.
- Setup guide: `docs/validation/STANZA_HE_PREP.md` — PowerShell-only setup, preflight, run commands, environment caveats.

**Gold smoke cases (calibrated against stanza 1.11.1):**

| Case | Input | Tokens | Key contract |
|---|---|---|---|
| C02_SMOKE_01 | `שלום` | 1 | INTJ, morph="" |
| C02_SMOKE_02 | `הכלב רץ` | 3 | ה DET + כלב NOUN + רץ VERB (prefix detachment) |
| C02_SMOKE_03 | `ספר גדול` | 2 | ספר NOUN + גדול ADJ |

**Smoke test breakdown (10 tests):**

| Class | Tests | What they verify |
|---|---|---|
| `TestStanzaInfraSmoke` | 6 | package import, model dir, engine init, empty text, Sentence type, Token fields |
| `TestC02SmokeCases` | 4 | 3 calibrated gold cases + inline DET prefix pin |

**What this wave does NOT claim:**
- It does NOT validate the morphology contract across word classes.
- It does NOT validate lemma paradigms (plural forms, verb conjugations).
- It does NOT validate POS consistency across inflected forms.
- It does NOT validate multi-sentence segmentation.
- It does NOT advance C02 status to PARTIAL or VALIDATED.

---

## 2. C02 Input/Output Contract (draft — not yet validated)

**Engine call:**
```python
from app.infra.nlp_engines.stanza_engine import StanzaEngine
engine = StanzaEngine(use_gpu=False)
sentences: list[Sentence] = engine.process(input_text: str)
```

**Output structure:**
```
list[Sentence]
  Sentence.text: str          — sentence surface text
  Sentence.tokens: list[Token]
    Token.text:  str          — surface form of the word
    Token.lemma: str          — lemma (fallback: equals text if Stanza returns None)
    Token.pos:   str          — Universal POS tag (NOUN, VERB, ADJ, DET, PROPN, INTJ, X, ...)
    Token.morph: str          — morphological features "Key=Val|Key=Val..." or "" (not None)
```

**Confirmed edge cases (from Wave 6a):**
- Empty string → `[]` (confirmed by `test_empty_text_returns_empty_list`)
- Whitespace-only → `[]` (confirmed)
- Hebrew DET prefix detachment: `"הכלב"` → `[Token("ה", DET), Token("כלב", NOUN)]` — 2 tokens from 1 surface word (confirmed by SMOKE_02 + inline pin)
- `Token.morph` is always `str`, never `None` — `_format_feats(None)` → `""` in StanzaEngine (confirmed by SMOKE_01 + token fields test)

**Not yet confirmed (Wave 6b):**
- Verb lemma for past/present/future forms
- Plural noun lemma reduction
- Feminine form lemma
- Multi-sentence boundary alignment
- Sentence text reconstruction from tokens

---

## 3. What is guaranteed after Wave 6a

- **Skip behaviour is deterministic:** when stanza package or `he/` model dir is absent, all 10 C02 tests skip. No chaotic failures, no import errors leaking into the test runner.
- **Marker is registered:** `pytest -m requires_stanza` works without warning.
- **Infra is wired end-to-end:** StanzaEngine initializes, processes Hebrew text, returns correct types.
- **DET prefix detachment is pinned:** `"הכלב"` → 3 tokens — this boundary is important for C05 (NP extractor) which expects pre-detached tokens.
- **Non-Stanza baseline is unchanged:** 247 passed (C02 tests deselected by `-k "not v02 and not stanza"`).
- **Setup is reproducible:** STANZA_HE_PREP.md documents every PowerShell command needed to reproduce the environment.

---

## 4. What remains NOT covered (Wave 6b required)

| Gap | Impact |
|---|---|
| Lemma paradigm: plural, verb conjugations | C03 aggregation relies on correct lemmatization |
| POS consistency across inflected forms | C04/C05 extractors assume stable POS per lemma |
| Multi-sentence boundary alignment | C01↔C02 contract boundary |
| Feminine/plural morphology features | Morphological analysis contract |
| `sentence.text` content contract | Not validated — does it reconstruct from tokens? |
| Determinism test | Same input → same output on two calls |
| Stanza version pinning policy | What to do when model version changes |

---

## 5. Required follow-up

**Wave 6b (C02 implementation — mandatory):**
1. Calibrate lemma paradigm gold: plural nouns (כלבים → כלב), past/pres verb forms (רץ/רצה/ירוץ → רוץ).
2. Add POS consistency tests: same lemma regardless of inflection.
3. Add multi-sentence test: input with 2 sentences → 2 Sentence objects.
4. Add morphological feature contract tests: Gender=Fem, Number=Plur, Tense=Pres.
5. Add determinism test.
6. Add `sentence.text` content validation.
7. Pin TODO_wave_6b list in gold file.
8. Advance status: INFRA PREPARED → PARTIAL (after key morphology contracts covered) or VALIDATED.

**Optional (low priority):**
- Test STANZA_HOME override path.
- Benchmark pipeline init time and token throughput.

---

## 6. Skip behaviour specification

| Environment | Behaviour |
|---|---|
| stanza package not installed | `requires_stanza = skipif(True)` → all 10 tests skip |
| stanza installed, `he/` dir absent | `_stanza_he_model_available()` False → all 10 tests skip |
| stanza installed, model dir present, pipeline init fails | `stanza_engine` fixture calls `pytest.skip()` → 4 infra init tests + 4 smoke tests skip; 2 tests (package import + model dir) still pass |
| stanza + model fully available | All 10 tests pass |

---

## 7. DoD verdict

**INFRA PREPARED — IMPLEMENTATION PENDING**

Not PARTIAL and not VALIDATED because:
- No morphology contract is validated (no lemma paradigm, no feature coverage).
- 3 smoke cases prove infra wiring only, not correctness across word classes.
- The gap between "model is available" and "morphology output is correct" is documented in TODO_wave_6b and this audit.

INFRA PREPARED (not "abstractly deferred") because:
- stanza package installed and in core deps.
- Hebrew model downloaded and available locally.
- StanzaEngine wraps model correctly.
- Oracle, gold structure, test file, marker, skip behaviour all exist and work.
- PowerShell setup guide covers every preparation step.
- The next wave can start implementing morphology gold immediately without any setup work.

---

## 8. Files changed in this wave

| File | Role |
|---|---|
| `pytest.ini` | `requires_stanza` marker registered |
| `tests/validation/conftest.py` | `_stanza_he_model_available()` added; `requires_stanza` updated |
| `tests/validation/oracles/oracle_token_morph.py` | Oracle — `validate_token_morphology()` |
| `tests/validation/gold/c02_token_morph.json` | Gold — 3 smoke cases + TODO_wave_6b |
| `tests/validation/test_v02_token_morph.py` | 10 tests (6 infra + 4 smoke) |
| `docs/validation/STANZA_HE_PREP.md` | PowerShell setup guide |
| `docs/validation/audits/C02_AUDIT.md` | This file |
| `docs/validation/AUDIT_INDEX.md` | C02: Deferred → Infra Prepared |
| `docs/validation/VALIDATION_METHODOLOGY.md` | v1.8 → v1.9; C02 row updated; commands updated |
| `docs/validation/DEFECT_PLAYBOOK.md` | D05 updated: Windows path, PowerShell commands |

---

## 9. Regression / baseline impact

- Non-Stanza validation suite: **247 passed** (unchanged).
- C02 (requires stanza + he model): **10 passed** when infra available, 10 skipped otherwise.
- Total when all available: 257.
- Main baseline (--ignore=tests/validation): 1751 passed (no implementation changes).

---

## 10. Executive summary

C02 was marked "abstractly deferred" for all prior waves. Wave 6a converts this to a concrete,
reproducible state: stanza is installed, the Hebrew model is on disk, the engine is wired,
the oracle exists, the test file exists, the skip mechanism is correct, and the setup guide
documents every required PowerShell command.

Three calibrated smoke cases prove the pipeline works end-to-end: שלום (INTJ, morph=""),
הכלב רץ (DET prefix detachment → 3 tokens), ספר גדול (NOUN+ADJ). The DET prefix detachment
case is particularly important because it pins the boundary between C02 (tokenization) and
C05 (NP extractor): "הכלב" must produce [ה DET, כלב NOUN], not a single token.

Status is INFRA PREPARED — not PARTIAL. The gap between INFRA PREPARED and PARTIAL is the
morphology contract: no lemma paradigm is validated, no POS consistency across inflected
forms is tested, no morphological feature coverage exists. Wave 6b will close these gaps.

---

## Follow-up checklist

- [x] Register `requires_stanza` in pytest.ini
- [x] Add `_stanza_he_model_available()` to conftest.py
- [x] Update `requires_stanza` to use model directory check
- [x] Confirm stanza package installed + version
- [x] Confirm Hebrew model available + location documented
- [x] Confirm StanzaEngine output format (text, lemma, pos, morph as str)
- [x] Create oracle skeleton (`oracle_token_morph.py`)
- [x] Create gold skeleton with 3 smoke cases (`c02_token_morph.json`)
- [x] Create test file with 10 tests (`test_v02_token_morph.py`)
- [x] Create PowerShell setup guide (`STANZA_HE_PREP.md`)
- [x] Pin DET prefix detachment as explicit boundary contract
- [x] Document skip behaviour for all three failure modes
- [x] Update AUDIT_INDEX.md
- [x] Update VALIDATION_METHODOLOGY.md
- [x] Update DEFECT_PLAYBOOK.md D05
- [ ] Wave 6b: lemma paradigm gold (plural, verb conjugations)
- [ ] Wave 6b: POS consistency across inflected forms
- [ ] Wave 6b: multi-sentence input test
- [ ] Wave 6b: morphological feature coverage
- [ ] Wave 6b: determinism test
