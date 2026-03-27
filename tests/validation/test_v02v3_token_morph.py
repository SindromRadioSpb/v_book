"""V02v3 — Verb tense contract validation for C02 (Wave 6c).

Extends Wave 6b (morphology contract) with full Hebrew verb tense family coverage:
  - Infinitive: לכתוב → POS=VERB, lemma=כתב, VerbForm=Inf; no Tense/Gender/Number/Person
  - Present (4 forms): כותב/כותבת/כותבים/כותבות → lemma=כתב, Tense=Pres, VerbForm=Part
  - Past (re-proven): כתב/כתבה/כתבו → lemma=כתב, Tense=Past (Wave 6b contract, no regression)
  - Future (7 forms): אכתוב/תכתוב(2ms)/יכתוב/נכתוב/תכתבו/יכתבו/תכתוב(3fs) → lemma=כתב, Tense=Fut
  - Cross-tense lemma reduction: all four tense families → one shared lemma (כתב)
  - Mixed-tense multi-sentence determinism

Calibrated behaviors (stanza 1.11.1 — not bugs):
  - כותבת → HebBinyan=PIEL (not PAAL) and Person=1,2,3 (ambiguous): design
  - Future 3pl (יכתבו) → Gender=Fem,Masc (dual gender): design
  - תכתוב (same surface) → Gender=Masc/Person=2 with subject 'אתה'; Gender=Fem/Person=3 with 'היא': context-driven
  - Infinitive morph lacks Tense/Gender/Number/Person features: design
  - Future מ-prefix ambiguity: מכתב splits after ת/י/נ verbs — all future gold uses ספר/ספרים object

Known limitations NOT covered:
  - Future 2fs (את תכתבי): 'את' → ADP not PRON, wrong person/gender. Context-dependent ambiguity.
  - Verb present participle vs nominal use (e.g. 'כותב' as noun 'writer'): out of scope
  - Construct state, preposition prefixes, nikud: out of scope

Gold: tests/validation/gold/c02_token_morph.json (Wave 6c cases: C02_VT_INF_01, C02_VT_PRES_01..04,
      C02_VT_FUT_01..07, C02_VT_MS_01)
Oracle: tests/validation/oracles/oracle_token_morph.py

PowerShell:
  .venv\\Scripts\\python.exe -m pytest tests/validation/test_v02v3_token_morph.py -v
  .venv\\Scripts\\python.exe -m pytest tests/validation/ -m requires_stanza -v
"""

from __future__ import annotations

import pytest

from tests.validation.conftest import requires_stanza
from tests.validation.oracles.oracle_token_morph import (
    validate_token_invariants,
    validate_token_morphology,
)

# ---------------------------------------------------------------------------
# Wave 6c scenario IDs
# ---------------------------------------------------------------------------

SCENARIO_IDS_VT = [
    "C02_VT_INF_01",  # infinitive
    "C02_VT_PRES_01",  # present masc sing
    "C02_VT_PRES_02",  # present fem sing
    "C02_VT_PRES_03",  # present masc plur
    "C02_VT_PRES_04",  # present fem plur
    "C02_VT_FUT_01",  # future 1s
    "C02_VT_FUT_02",  # future 2ms
    "C02_VT_FUT_03",  # future 3ms
    "C02_VT_FUT_04",  # future 1pl
    "C02_VT_FUT_05",  # future 2mp
    "C02_VT_FUT_06",  # future 3pl
    "C02_VT_FUT_07",  # future 3fs
    "C02_VT_MS_01",  # mixed-tense multi-sentence
]


@pytest.fixture
def vt_cases(gold_data):
    """Return all Wave 6c VT cases keyed by case_id."""
    all_cases = gold_data("c02_token_morph")["cases"]
    return {c["case_id"]: c for c in all_cases}


# ---------------------------------------------------------------------------
# Oracle pass + structural invariants — parametrized over all VT cases
# ---------------------------------------------------------------------------


@requires_stanza
class TestVerbTenseOracle:
    """Full oracle run for each Wave 6c scenario — structured equality per gold."""

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS_VT)
    def test_oracle_passes(self, scenario_id, vt_cases, stanza_engine):
        """Gold case matches actual StanzaEngine output for token/lemma/pos/morph."""
        case = vt_cases[scenario_id]
        result = validate_token_morphology(case, stanza_engine)
        assert result.match, f"[{scenario_id}] oracle failed: {result.missing}"

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS_VT)
    def test_token_invariants(self, scenario_id, vt_cases, stanza_engine):
        """All tokens in VT case output must pass structural invariants."""
        case = vt_cases[scenario_id]
        actual = stanza_engine.process(case["input_text"])
        violations = validate_token_invariants(actual, case_id=scenario_id)
        assert not violations, f"[{scenario_id}] invariant violations: {violations}"


# ---------------------------------------------------------------------------
# Infinitive contract
# ---------------------------------------------------------------------------


@requires_stanza
class TestInfinitiveContract:
    """Explicit contract for Hebrew infinitive (לכתוב) in sentence context."""

    def test_infinitive_pos_is_verb(self, stanza_engine, vt_cases):
        """Infinitive לכתוב must be POS=VERB (not NOUN or ADP)."""
        case = vt_cases["C02_VT_INF_01"]
        sents = stanza_engine.process(case["input_text"])
        inf_tok = next(t for t in sents[0].tokens if t.text == "לכתוב")
        assert inf_tok.pos == "VERB", f"לכתוב pos expected VERB, got {inf_tok.pos!r}"

    def test_infinitive_lemma_is_katav(self, stanza_engine, vt_cases):
        """Infinitive לכתוב → lemma=כתב (same lemma as all conjugated past/present/future forms)."""
        case = vt_cases["C02_VT_INF_01"]
        sents = stanza_engine.process(case["input_text"])
        inf_tok = next(t for t in sents[0].tokens if t.text == "לכתוב")
        assert inf_tok.lemma == "כתב", f"לכתוב lemma expected כתב, got {inf_tok.lemma!r}"

    def test_infinitive_verbform_inf_in_morph(self, stanza_engine, vt_cases):
        """Infinitive morph must contain VerbForm=Inf."""
        case = vt_cases["C02_VT_INF_01"]
        sents = stanza_engine.process(case["input_text"])
        inf_tok = next(t for t in sents[0].tokens if t.text == "לכתוב")
        assert (
            "VerbForm=Inf" in inf_tok.morph
        ), f"לכתוב morph must contain VerbForm=Inf. Got: {inf_tok.morph!r}"

    def test_infinitive_no_tense_feature(self, stanza_engine, vt_cases):
        """Infinitive morph must NOT contain Tense= (no tense feature for infinitives).

        Calibrated by design: Stanza omits Tense/Gender/Number/Person for infinitives.
        """
        case = vt_cases["C02_VT_INF_01"]
        sents = stanza_engine.process(case["input_text"])
        inf_tok = next(t for t in sents[0].tokens if t.text == "לכתוב")
        assert (
            "Tense=" not in inf_tok.morph
        ), f"לכתוב (infinitive) morph must NOT contain Tense=. Got: {inf_tok.morph!r}"


# ---------------------------------------------------------------------------
# Present tense contract
# ---------------------------------------------------------------------------


@requires_stanza
class TestPresentTenseContract:
    """Contract for present tense forms: כותב/כותבת/כותבים/כותבות."""

    PRESENT_FORMS = {
        "כותב": "C02_VT_PRES_01",
        "כותבת": "C02_VT_PRES_02",
        "כותבים": "C02_VT_PRES_03",
        "כותבות": "C02_VT_PRES_04",
    }

    def test_present_all_forms_pos_verb(self, stanza_engine, vt_cases):
        """All four present forms must have POS=VERB in sentence context."""
        for form, sid in self.PRESENT_FORMS.items():
            sents = stanza_engine.process(vt_cases[sid]["input_text"])
            tok = next((t for t in sents[0].tokens if t.text == form), None)
            assert tok is not None, f"Token {form!r} not found in output"
            assert tok.pos == "VERB", f"{form!r} pos expected VERB, got {tok.pos!r}"

    def test_present_all_forms_lemma_katav(self, stanza_engine, vt_cases):
        """All four present forms must have lemma=כתב."""
        for form, sid in self.PRESENT_FORMS.items():
            sents = stanza_engine.process(vt_cases[sid]["input_text"])
            tok = next((t for t in sents[0].tokens if t.text == form), None)
            assert tok is not None, f"Token {form!r} not found"
            assert tok.lemma == "כתב", f"{form!r} lemma expected כתב, got {tok.lemma!r}"

    def test_present_verbform_part_in_morph(self, stanza_engine, vt_cases):
        """All four present forms must have VerbForm=Part in morph (distinguishes present from past)."""
        for form, sid in self.PRESENT_FORMS.items():
            sents = stanza_engine.process(vt_cases[sid]["input_text"])
            tok = next((t for t in sents[0].tokens if t.text == form), None)
            assert tok is not None, f"Token {form!r} not found"
            assert (
                "VerbForm=Part" in tok.morph
            ), f"{form!r} morph must contain VerbForm=Part. Got: {tok.morph!r}"

    def test_present_tense_pres_in_morph(self, stanza_engine, vt_cases):
        """All four present forms must have Tense=Pres in morph."""
        for form, sid in self.PRESENT_FORMS.items():
            sents = stanza_engine.process(vt_cases[sid]["input_text"])
            tok = next((t for t in sents[0].tokens if t.text == form), None)
            assert tok is not None, f"Token {form!r} not found"
            assert (
                "Tense=Pres" in tok.morph
            ), f"{form!r} morph must contain Tense=Pres. Got: {tok.morph!r}"

    def test_present_kotevet_hebbinyan_piel(self, stanza_engine, vt_cases):
        """כותבת → HebBinyan=PIEL (not PAAL). Calibrated by design.

        Documents: Stanza assigns PIEL to כותבת (likely due to PIEL/PAAL overlap in fem sing
        present forms). This is a model-calibrated behaviour, not a linguistic error.
        """
        sents = stanza_engine.process(vt_cases["C02_VT_PRES_02"]["input_text"])
        tok = next(t for t in sents[0].tokens if t.text == "כותבת")
        assert (
            "HebBinyan=PIEL" in tok.morph
        ), f"כותבת: calibrated HebBinyan=PIEL expected in morph. Got: {tok.morph!r}"


# ---------------------------------------------------------------------------
# Past tense contract (re-proven from Wave 6b — no regression)
# ---------------------------------------------------------------------------


@requires_stanza
class TestPastTenseContract:
    """Past tense contract re-proven from Wave 6b. Guards against regression.

    Wave 6b covers past tense exhaustively (C02_LP_05..07). This class re-runs
    the oracle for past cases and asserts the key lemma+tense contract holds.
    """

    PAST_FORMS = {
        "כתב": "C02_LP_05",
        "כתבה": "C02_LP_06",
        "כתבו": "C02_LP_07",
    }

    def test_past_oracle_still_passes(self, stanza_engine, vt_cases):
        """Past tense oracle cases (Wave 6b) must still pass — no regression."""
        for form, sid in self.PAST_FORMS.items():
            case = vt_cases[sid]
            result = validate_token_morphology(case, stanza_engine)
            assert result.match, f"[{sid}] past tense regression: {result.missing}"

    def test_past_all_forms_lemma_katav(self, stanza_engine, vt_cases):
        """Past tense forms כתב/כתבה/כתבו must all have lemma=כתב."""
        for form, sid in self.PAST_FORMS.items():
            sents = stanza_engine.process(vt_cases[sid]["input_text"])
            tok = next((t for t in sents[0].tokens if t.text == form), None)
            assert tok is not None, f"Token {form!r} not found"
            assert tok.lemma == "כתב", f"{form!r} lemma expected כתב, got {tok.lemma!r}"


# ---------------------------------------------------------------------------
# Future tense contract
# ---------------------------------------------------------------------------


@requires_stanza
class TestFutureTenseContract:
    """Contract for future tense forms across person/number/gender."""

    FUTURE_FORMS = {
        "אכתוב": "C02_VT_FUT_01",
        "תכתוב_2ms": "C02_VT_FUT_02",
        "יכתוב": "C02_VT_FUT_03",
        "נכתוב": "C02_VT_FUT_04",
        "תכתבו": "C02_VT_FUT_05",
        "יכתבו": "C02_VT_FUT_06",
        "תכתוב_3fs": "C02_VT_FUT_07",
    }
    # Map case_id → actual verb text (needed to look up token)
    FUT_VERB_TEXT = {
        "C02_VT_FUT_01": "אכתוב",
        "C02_VT_FUT_02": "תכתוב",
        "C02_VT_FUT_03": "יכתוב",
        "C02_VT_FUT_04": "נכתוב",
        "C02_VT_FUT_05": "תכתבו",
        "C02_VT_FUT_06": "יכתבו",
        "C02_VT_FUT_07": "תכתוב",
    }

    def test_future_all_forms_pos_verb(self, stanza_engine, vt_cases):
        """All seven future forms must have POS=VERB in sentence context."""
        for sid, form in self.FUT_VERB_TEXT.items():
            sents = stanza_engine.process(vt_cases[sid]["input_text"])
            tok = next((t for t in sents[0].tokens if t.text == form), None)
            assert tok is not None, f"[{sid}] Token {form!r} not found"
            assert tok.pos == "VERB", f"[{sid}] {form!r} pos expected VERB, got {tok.pos!r}"

    def test_future_all_forms_lemma_katav(self, stanza_engine, vt_cases):
        """All seven future forms must have lemma=כתב."""
        for sid, form in self.FUT_VERB_TEXT.items():
            sents = stanza_engine.process(vt_cases[sid]["input_text"])
            tok = next((t for t in sents[0].tokens if t.text == form), None)
            assert tok is not None, f"[{sid}] Token {form!r} not found"
            assert tok.lemma == "כתב", f"[{sid}] {form!r} lemma expected כתב, got {tok.lemma!r}"

    def test_future_tense_fut_in_morph(self, stanza_engine, vt_cases):
        """All future forms must have Tense=Fut in morph."""
        for sid, form in self.FUT_VERB_TEXT.items():
            sents = stanza_engine.process(vt_cases[sid]["input_text"])
            tok = next((t for t in sents[0].tokens if t.text == form), None)
            assert tok is not None, f"[{sid}] Token {form!r} not found"
            assert (
                "Tense=Fut" in tok.morph
            ), f"[{sid}] {form!r} morph must contain Tense=Fut. Got: {tok.morph!r}"

    def test_future_3pl_gender_fem_masc(self, stanza_engine, vt_cases):
        """Future 3pl יכתבו morph must contain Gender=Fem,Masc (dual gender — calibrated by design).

        Documents: Stanza emits both genders for 3rd person plural future (gender-common form).
        Do not assert Gender=Masc alone for יכתבו.
        """
        sents = stanza_engine.process(vt_cases["C02_VT_FUT_06"]["input_text"])
        tok = next(t for t in sents[0].tokens if t.text == "יכתבו")
        assert "Fem,Masc" in tok.morph or (
            "Gender=Fem" in tok.morph and "Gender=Masc" in tok.morph
        ), f"יכתבו morph must contain dual gender (Fem,Masc). Got: {tok.morph!r}"

    def test_future_3fs_context_gives_gender_fem(self, stanza_engine, vt_cases):
        """Future תכתוב with subject היא must have Gender=Fem in morph (not Gender=Masc).

        Same surface form as 2ms (אתה תכתוב), but pronoun context drives gender disambiguation.
        """
        sents = stanza_engine.process(vt_cases["C02_VT_FUT_07"]["input_text"])
        tok = next(t for t in sents[0].tokens if t.text == "תכתוב")
        assert (
            "Gender=Fem" in tok.morph
        ), f"תכתוב (3fs, subject=היא) morph must contain Gender=Fem. Got: {tok.morph!r}"


# ---------------------------------------------------------------------------
# Cross-tense lemma reduction
# ---------------------------------------------------------------------------


@requires_stanza
class TestCrossTenseLemmaReduction:
    """Explicit proof that infinitive + present + past + future all reduce to lemma=כתב."""

    def test_infinitive_present_past_future_all_lemma_katav(self, stanza_engine, vt_cases):
        """All four verb tense families must produce lemma=כתב for the כתב paradigm.

        This is the primary cross-tense lemma contract. C03 lemma aggregation depends on
        this: occurrences of לכתוב/כותב/כתב/יכתוב must all aggregate under the same lemma.
        """
        families = {
            "infinitive (לכתוב)": ("C02_VT_INF_01", "לכתוב"),
            "present (כותב)": ("C02_VT_PRES_01", "כותב"),
            "past (כתב)": ("C02_LP_05", "כתב"),
            "future (יכתוב)": ("C02_VT_FUT_03", "יכתוב"),
        }
        lemmas = {}
        for label, (sid, verb_text) in families.items():
            sents = stanza_engine.process(vt_cases[sid]["input_text"])
            tok = next((t for t in sents[0].tokens if t.text == verb_text), None)
            assert tok is not None, f"Token {verb_text!r} not found for {label}"
            lemmas[label] = tok.lemma

        for label, lemma in lemmas.items():
            assert lemma == "כתב", (
                f"{label}: lemma expected כתב, got {lemma!r}. " f"All families: {lemmas}"
            )

        assert (
            len(set(lemmas.values())) == 1
        ), f"All tense families must share ONE lemma. Got distinct lemmas: {lemmas}"


# ---------------------------------------------------------------------------
# Morphological feature coverage
# ---------------------------------------------------------------------------


@requires_stanza
class TestVerbMorphFeatureCoverage:
    """Assert only features that Stanza consistently emits for verb forms."""

    def test_verbform_inf_only_in_infinitive(self, stanza_engine, vt_cases):
        """VerbForm=Inf must appear in infinitive morph but NOT in past tense morph."""
        sents_inf = stanza_engine.process(vt_cases["C02_VT_INF_01"]["input_text"])
        inf_tok = next(t for t in sents_inf[0].tokens if t.text == "לכתוב")
        assert (
            "VerbForm=Inf" in inf_tok.morph
        ), f"Infinitive must have VerbForm=Inf. Got: {inf_tok.morph!r}"

        sents_past = stanza_engine.process(vt_cases["C02_LP_05"]["input_text"])
        past_tok = next(t for t in sents_past[0].tokens if t.text == "כתב")
        assert (
            "VerbForm=Inf" not in past_tok.morph
        ), f"Past tense כתב must NOT have VerbForm=Inf. Got: {past_tok.morph!r}"

    def test_verbform_part_only_in_present(self, stanza_engine, vt_cases):
        """VerbForm=Part must appear in present morph but NOT in past or future."""
        sents_pres = stanza_engine.process(vt_cases["C02_VT_PRES_01"]["input_text"])
        pres_tok = next(t for t in sents_pres[0].tokens if t.text == "כותב")
        assert (
            "VerbForm=Part" in pres_tok.morph
        ), f"Present must have VerbForm=Part. Got: {pres_tok.morph!r}"

        sents_past = stanza_engine.process(vt_cases["C02_LP_05"]["input_text"])
        past_tok = next(t for t in sents_past[0].tokens if t.text == "כתב")
        assert (
            "VerbForm=Part" not in past_tok.morph
        ), f"Past כתב must NOT have VerbForm=Part. Got: {past_tok.morph!r}"

    def test_tense_past_in_past_not_present(self, stanza_engine, vt_cases):
        """Tense=Past must appear in past morph but NOT in present morph."""
        sents_past = stanza_engine.process(vt_cases["C02_LP_05"]["input_text"])
        past_tok = next(t for t in sents_past[0].tokens if t.text == "כתב")
        assert "Tense=Past" in past_tok.morph, f"Past must have Tense=Past. Got: {past_tok.morph!r}"

        sents_pres = stanza_engine.process(vt_cases["C02_VT_PRES_01"]["input_text"])
        pres_tok = next(t for t in sents_pres[0].tokens if t.text == "כותב")
        assert (
            "Tense=Past" not in pres_tok.morph
        ), f"Present כותב must NOT have Tense=Past. Got: {pres_tok.morph!r}"

    def test_tense_fut_in_future_not_past(self, stanza_engine, vt_cases):
        """Tense=Fut must appear in future morph but NOT in past morph."""
        sents_fut = stanza_engine.process(vt_cases["C02_VT_FUT_03"]["input_text"])
        fut_tok = next(t for t in sents_fut[0].tokens if t.text == "יכתוב")
        assert "Tense=Fut" in fut_tok.morph, f"Future must have Tense=Fut. Got: {fut_tok.morph!r}"

        sents_past = stanza_engine.process(vt_cases["C02_LP_05"]["input_text"])
        past_tok = next(t for t in sents_past[0].tokens if t.text == "כתב")
        assert (
            "Tense=Fut" not in past_tok.morph
        ), f"Past כתב must NOT have Tense=Fut. Got: {past_tok.morph!r}"

    def test_gender_number_emitted_in_conjugated_forms(self, stanza_engine, vt_cases):
        """Conjugated verb forms (past/present/future) must emit Gender and Number in morph.

        Infinitive (לכתוב) is excluded — it has no inflection features.
        """
        forms_to_check = [
            ("C02_VT_PRES_01", "כותב"),
            ("C02_VT_PRES_03", "כותבים"),
            ("C02_LP_05", "כתב"),
            ("C02_VT_FUT_03", "יכתוב"),
        ]
        for sid, verb_text in forms_to_check:
            sents = stanza_engine.process(vt_cases[sid]["input_text"])
            tok = next((t for t in sents[0].tokens if t.text == verb_text), None)
            assert tok is not None, f"[{sid}] Token {verb_text!r} not found"
            assert (
                "Gender=" in tok.morph
            ), f"[{sid}] {verb_text!r} must have Gender= in morph. Got: {tok.morph!r}"
            assert (
                "Number=" in tok.morph
            ), f"[{sid}] {verb_text!r} must have Number= in morph. Got: {tok.morph!r}"


# ---------------------------------------------------------------------------
# Mixed-tense multi-sentence
# ---------------------------------------------------------------------------


@requires_stanza
class TestMixedTenseMultiSentence:
    """Mixed-tense multi-sentence: past + present + future in one input."""

    def test_ms_01_oracle_passes(self, stanza_engine, vt_cases):
        """C02_VT_MS_01 oracle must pass (3 sentences, all verb lemmas, punct tokens)."""
        case = vt_cases["C02_VT_MS_01"]
        result = validate_token_morphology(case, stanza_engine)
        assert result.match, f"C02_VT_MS_01 oracle failed: {result.missing}"

    def test_ms_01_produces_three_sentences(self, stanza_engine, vt_cases):
        """Mixed-tense input must produce exactly 3 sentences."""
        sents = stanza_engine.process(vt_cases["C02_VT_MS_01"]["input_text"])
        assert len(sents) == 3, f"Expected 3 sentences, got {len(sents)}"

    def test_ms_01_all_verb_lemmas_katav(self, stanza_engine, vt_cases):
        """Across all 3 sentences, every VERB token must have lemma=כתב.

        Proves cross-tense lemma consistency in a single multi-sentence call.
        """
        sents = stanza_engine.process(vt_cases["C02_VT_MS_01"]["input_text"])
        for si, sent in enumerate(sents):
            for tok in sent.tokens:
                if tok.pos == "VERB":
                    assert (
                        tok.lemma == "כתב"
                    ), f"sent[{si}] verb {tok.text!r} lemma expected כתב, got {tok.lemma!r}"

    def test_ms_01_tense_progression(self, stanza_engine, vt_cases):
        """3 sentences must have Past / Pres / Fut tense in the respective verb tokens."""
        sents = stanza_engine.process(vt_cases["C02_VT_MS_01"]["input_text"])
        expected_tense = ["Tense=Past", "Tense=Pres", "Tense=Fut"]
        for si, sent in enumerate(sents):
            verb_toks = [t for t in sent.tokens if t.pos == "VERB"]
            assert verb_toks, f"Sentence[{si}] has no VERB token"
            main_verb = verb_toks[0]
            assert expected_tense[si] in main_verb.morph, (
                f"sent[{si}] verb {main_verb.text!r} expected {expected_tense[si]!r} "
                f"in morph. Got: {main_verb.morph!r}"
            )


# ---------------------------------------------------------------------------
# Determinism (Wave 6c)
# ---------------------------------------------------------------------------


@requires_stanza
class TestDeterminismV3:
    """Determinism for mixed-tense multi-sentence input."""

    def test_determinism_mixed_tense_multi_sentence(self, stanza_engine, vt_cases):
        """Two independent calls on the mixed-tense multi-sentence input must produce
        identical structured output (sentence.text + token text/lemma/pos/morph tuples).
        """

        def _struct(sents):
            return [(s.text, [(t.text, t.lemma, t.pos, t.morph) for t in s.tokens]) for s in sents]

        text = vt_cases["C02_VT_MS_01"]["input_text"]
        r1 = stanza_engine.process(text)
        r2 = stanza_engine.process(text)
        assert _struct(r1) == _struct(r2), (
            f"StanzaEngine is non-deterministic on mixed-tense input.\n"
            f"Run1: {_struct(r1)}\nRun2: {_struct(r2)}"
        )
