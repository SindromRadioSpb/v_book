# Handoff Status — HDLE Premium NLP Validation Layer

> Last updated: 2026-03-27 (Wave 6c complete)
> Authority: docs/validation/AUDIT_INDEX.md (canonical status) + docs/validation/VALIDATION_METHODOLOGY.md v2.1
> Read this file FIRST before starting any validation wave in Codex.

---

## Current Status

| Corpus | Stage | Status | Tests |
|---|---|---|---|
| C01 | Sentence splitting | **Validated** | Wave 2 done |
| C02 | Tokenization + morphology | **Validated** (Wave 6c) | 93 (10+30+53) |
| C03 | Lemma aggregation | **Validated** | Wave 2 done |
| C04 | N-gram extraction | **Validated** | Wave 2 done |
| C05 | NP chunk extraction | **Validated** | Wave 2 done |
| C06 | Canonicalization | **Validated** | Wave 2 done |
| C07 | Association measures | **Validated** | done |
| C08 | Noise classification | **Validated** | Wave 2 done |
| C09 | Extraction modes | **Validated** | done |
| C10 | Full pipeline round-trip | **Deferred** | 0 — next release gate |
| TM | TM projection | **Partial** | 52 (27+25) — inline_edit+batch_MT deferred |

---

## What Is Already Proven

### C02 — Tokenization + Morphology (93 tests, stanza 1.11.1)
- DET prefix detachment: `הכלב` → `[ה DET, כלב NOUN]` — boundary for C05
- Noun lemma paradigms: masc plural → masc sing lemma; fem plural → fem sing lemma
- Adjective lemma: all gender/number forms → masc sing lemma (גדול)
- Verb past (3 forms): כתב/כתבה/כתבו → lemma=כתב, Tense=Past
- Verb infinitive: לכתוב → pos=VERB, lemma=כתב, VerbForm=Inf, NO Tense/Gender/Number/Person
- Verb present (4 forms): כותב/כותבת/כותבים/כותבות → lemma=כתב, Tense=Pres, VerbForm=Part
- Verb future (7 forms): אכתוב/תכתוב(2ms)/יכתוב/נכתוב/תכתבו/יכתבו/תכתוב(3fs) → lemma=כתב, Tense=Fut
- Cross-tense lemma reduction: inf+pres+past+fut all → כתב (first-class assertion)
- Multi-sentence behavior: sent.text includes terminal period; PUNCT token per sentence
- Determinism: identical output on two independent calls (both single and multi-sentence)
- Token structural invariants: text/pos non-empty str; lemma/morph as str, never None

### Calibrated-by-design behaviors (not bugs, not to be "fixed")
- All pronouns (הוא/היא/הם/הן/אני/אתה/אנחנו) → lemma=הוא
- Fem noun paradigm: כלבה → lemma=כלבה (not כלב) — separate paradigm
- כותבת → HebBinyan=PIEL (not PAAL), Person=1,2,3 (ambiguous)
- Future 3pl יכתבו → Gender=Fem,Masc (dual gender)
- Same surface form תכתוב: Gender=Masc/Person=2 (subject=אתה) vs Gender=Fem/Person=3 (subject=היא)
- Infinitive morph: VerbForm=Inf + HebBinyan + Voice only; no inflection features
- Future מ-prefix split: מכתב → [מ ADP + כתב NOUN] after ת/י/נ future verbs — gold uses ספר

### Other validated corpora (C03–C09)
- C03: lemma aggregation — hapax, all-doc lemma, empty doc, stress
- C04: n-gram extraction — NOUN+ADJ+NOUN trigram, PUNCT boundary, mixed script
- C05: NP chunk extraction — DET non-first rejection, multiple DET bridge, ADJ-led NP
- C06: canonicalization — prefix כ/ש/ב/ל/מ, geresh, collision (כמות↔מות documented)
- C07: association measures — Dice n-independence, LLR at c_xy=0
- C08: noise classification — borderline inputs, ratio-check boundary, profile architecture
- C09: extraction modes — store_hapax + min_freq semantics confirmed
- TM Wave 1+2: kind='lemma' batch materialize, user_dict pathway, _attach_source_links, tm_global propagation

---

## What Is NOT Yet Release-Complete

### TM projection — status: Partial
- Covered: `kind='lemma'` batch materialize (27 tests), user_dict pathway (25 tests)
- NOT covered: `inline_edit` pathway, `batch_MT` pathway (require UI/worker fixtures)
- TM v3 (optional): close inline_edit + batch_MT if fixtures can be built without UI thread

### C10 — Full pipeline round-trip — status: Deferred
- Requires: Stanza + he model available in run env + populated test corpus
- Blocked on: TM pathway coverage decision (inline_edit needed or explicitly out-of-scope?)
- C10 = release gate: when C10 passes, the full pipeline is considered validated end-to-end

### Canonicalization (C06) — known remaining gaps
- Over-stripping: מדינה→דינה, שמחה→מחה (character-level prefix, no semantic awareness)
- These are documented limitations, not open defects — no fix planned unless premium tier requires it

### Real profile layer
- ALGORITHM_PROFILES.md confirmed: profiles are NOT implemented as code — classifier is profile-agnostic
- precise/balanced/recall profiles are post-processing filters, not a separate code layer
- No validation corpus needed until a code layer is implemented

### Production-scale validation
- All current gold is small-corpus (unit-level)
- Production-scale validation (real Hebrew Wikipedia content through full pipeline) = C10 scope

---

## Next Recommended Steps (priority order)

1. **TM v3 decision gate** — decide: are inline_edit + batch_MT in or out of C10 scope?
   - If in: build UI/worker fixtures + add Wave 3 to TM_AUDIT
   - If out: update TM_AUDIT + AUDIT_INDEX to mark TM as explicitly Partial-by-design
2. **C10 execution** — full pipeline round-trip with populated corpus
   - Depends on: C02 Validated ✅, TM decision resolved ✅
   - Creates: C10_AUDIT.md, test_v10_pipeline.py
3. **C06 premium hardening** (optional) — if product requires morphology-aware canonicalization
4. **C07 v2** (optional) — trigram None case, T-score positive, large N edge cases

---

## Baselines (hard — must not regress)

```
Main (--ignore=tests/validation): 1751 passed, 0 failed
Validation non-Stanza:            247 passed, 0 failed
C02 Stanza (requires model):       93 passed (or 93 skipped if model unavailable)
TM validation:                     52 passed (in non-Stanza suite)
```

**Combined when all available:** 2091 (1751 + 247 + 93)

---

## Commands (PowerShell only)

```powershell
cd E:\projects\Project_Vibe\V_book

# --- Baselines ---

# Non-Stanza validation (fast, CI-safe) — must be 247 passed
.\.venv\Scripts\python.exe -m pytest tests/validation/ -q -k "not v02 and not stanza"

# Main baseline — must be 1751 passed
.\.venv\Scripts\python.exe -m pytest --ignore=tests/validation -x -q

# --- C02 Stanza-dependent ---

# All C02 waves together — 93 passed (or skipped)
.\.venv\Scripts\python.exe -m pytest tests/validation/ -v -m requires_stanza

# Individual C02 waves
.\.venv\Scripts\python.exe -m pytest tests/validation/test_v02_token_morph.py -v      # 10 tests (Wave 6a)
.\.venv\Scripts\python.exe -m pytest tests/validation/test_v02v2_token_morph.py -v    # 30 tests (Wave 6b)
.\.venv\Scripts\python.exe -m pytest tests/validation/test_v02v3_token_morph.py -v    # 53 tests (Wave 6c)

# --- Full validation ---
.\.venv\Scripts\python.exe -m pytest tests/validation/ -v

# --- Stanza preflight (before running C02 tests) ---
.\.venv\Scripts\python.exe -c "import stanza; print(stanza.__version__)"
.\.venv\Scripts\python.exe -c "
import stanza.resources.common as src
from pathlib import Path
d = Path(src.DEFAULT_MODEL_DIR) / 'he'
print('HE model:', 'OK' if d.exists() else 'MISSING', d)
"
```

---

## Hard Guardrails

- **Do not reopen C02** scope unless corpus evidence requires it (new Stanza version or production bug)
- **Do not rewrite calibrated gold** without running calibration on the actual engine first
- **Do not "fix" by-design Stanza behaviors** listed in §Calibrated-by-design above
- **Do not mix corpus scopes** in one commit (C02 change + C05 change = two commits)
- **Validation-first**: calibrate actual engine output before writing gold — never from intuition
- **Keep changes bounded and test-backed**: every gold addition = one calibration run + one passing test
- **Docs are mandatory**: no wave is done without updating AUDIT_INDEX + audit doc + VALIDATION_METHODOLOGY

---

## Key File Map

| File | Purpose |
|---|---|
| `docs/validation/AUDIT_INDEX.md` | Canonical corpus status map |
| `docs/validation/VALIDATION_METHODOLOGY.md` | Methodology version + pipeline coverage table |
| `docs/validation/STANZA_HE_PREP.md` | Stanza setup + run commands |
| `docs/validation/DEFECT_PLAYBOOK.md` | Defect classification: bug / stale gold / by-design |
| `docs/validation/audits/C02_AUDIT.md` | C02 wave history + calibrated verb matrix |
| `docs/validation/audits/TM_AUDIT.md` | TM wave history + open pathways |
| `tests/validation/gold/c02_token_morph.json` | C02 gold (Waves 6a/6b/6c) |
| `tests/validation/oracles/oracle_token_morph.py` | C02 oracle functions |
| `tests/validation/conftest.py` | Shared fixtures: stanza_engine, gold_data, requires_stanza |
| `AGENTS.md §12` | Validation subsystem rules for Codex |

---

## Starter Prompt for Codex

```
Read handoff_wave_status.md and docs/validation/AUDIT_INDEX.md first.
Then read the audit doc for the target corpus: docs/validation/audits/<CXX>_AUDIT.md.
Follow AGENTS.md §12 and docs/validation/VALIDATION_METHODOLOGY.md.

Target: [FILL IN — e.g. "close TM v3 inline_edit pathway" or "execute C10 round-trip"]

Work format: Repo audit findings → patch plan → gold additions → tests → docs → DoD

Constraints:
- PowerShell commands only
- Calibrate actual engine output before writing gold
- Preserve baselines from handoff_wave_status.md §Baselines
- Do not widen scope beyond the stated target corpus
- Final report: files changed, test counts before/after, calibrated behaviors, open limitations
```
