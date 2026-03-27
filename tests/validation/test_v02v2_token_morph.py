"""V02v2 — Tokenization and morphology implementation wave (C02 Wave 6b).

Extends Wave 6a (infra smoke) with real morphology contract validation:
  - Lemma paradigms: noun plural, adjective gender/number, verb conjugation
  - POS consistency across inflected forms
  - Morphological feature coverage: Gender, Number, Tense, PronType
  - Multi-sentence behavior: sentence count, sentence.text, PUNCT token
  - Determinism: same input → identical structured output on two calls
  - Token structural invariants: all token fields are non-empty/non-None str

Known calibrated-by-design behaviors (not bugs):
  - Fem pronoun (היא) → lemma הוא (masc): Stanza canonical lemma for pronouns
  - Fem noun (כלבה) → lemma כלבה (not כלב): Stanza treats masc/fem noun as separate paradigms
  - Multi-sentence sent.text includes terminal period: 'ספר גדול.' (not 'ספר גדול')
  - Verb POS is context-dependent: isolated 'כתב' → NOUN; in sentence → VERB

All tests are @requires_stanza gated.
Skip behaviour: see docs/validation/STANZA_HE_PREP.md and conftest.py.

Oracle: validate_token_morphology() + validate_token_invariants()
Gold: tests/validation/gold/c02_token_morph.json (Wave 6b cases: C02_LP_01..07, C02_MS_01)

PowerShell:
  .venv\\Scripts\\python.exe -m pytest tests/validation/test_v02v2_token_morph.py -v
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
# Scenario IDs — Wave 6b lemma paradigm cases
# ---------------------------------------------------------------------------

SCENARIO_IDS_LP = [
    "C02_LP_01",  # ספרים גדולים — masc plural noun+adj
    "C02_LP_02",  # הספרים הגדולים — definite plural + double DET
    "C02_LP_03",  # עיר גדולה — fem sing noun+adj
    "C02_LP_04",  # ערים גדולות — fem plural noun+adj
    "C02_LP_05",  # הוא כתב ספר — verb past 3ms
    "C02_LP_06",  # היא כתבה ספר — verb past 3fs (fem pron→masc lemma)
    "C02_LP_07",  # הם כתבו ספרים — verb past 3pl
]


@pytest.fixture
def lp_cases(gold_data):
    """Return Wave 6b LP cases keyed by case_id."""
    all_cases = gold_data("c02_token_morph")["cases"]
    return {c["case_id"]: c for c in all_cases}


# ---------------------------------------------------------------------------
# Parametrized oracle coverage — all LP cases must pass validate_token_morphology
# ---------------------------------------------------------------------------


@requires_stanza
class TestLemmaParadigmOracle:
    """Full oracle run for each LP scenario — structured equality per gold."""

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS_LP)
    def test_oracle_passes(self, scenario_id, lp_cases, stanza_engine):
        """Gold case matches actual StanzaEngine output for token/lemma/pos/morph."""
        case = lp_cases[scenario_id]
        result = validate_token_morphology(case, stanza_engine)
        assert result.match, f"[{scenario_id}] oracle failed: {result.missing}"

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS_LP)
    def test_token_invariants(self, scenario_id, lp_cases, stanza_engine):
        """All tokens in LP case output must pass structural invariants."""
        case = lp_cases[scenario_id]
        actual = stanza_engine.process(case["input_text"])
        violations = validate_token_invariants(actual, case_id=scenario_id)
        assert not violations, f"[{scenario_id}] invariant violations: {violations}"


# ---------------------------------------------------------------------------
# Named lemma reduction contracts
# ---------------------------------------------------------------------------


@requires_stanza
class TestLemmaReductions:
    """Pin specific lemma reduction facts that downstream (C03/C04/C05) depends on."""

    def test_noun_masc_plur_reduces_to_masc_sing_lemma(self, stanza_engine, lp_cases):
        """ספרים (masc plur) must have lemma=ספר (masc sing).

        C03 aggregation depends on this: plural occurrences must aggregate to
        the singular lemma, not stay as ספרים.
        """
        case = lp_cases["C02_LP_01"]
        actual = {t.text: t for t in stanza_engine.process(case["input_text"])[0].tokens}
        assert (
            actual["ספרים"].lemma == "ספר"
        ), f"ספרים must reduce to lemma ספר. Got: {actual['ספרים'].lemma!r}"

    def test_adj_all_inflected_forms_reduce_to_masc_sing_lemma(self, stanza_engine, lp_cases):
        """גדולה, גדולים, גדולות — all must have lemma=גדול (masc sing).

        All four gender/number forms of the same adjective share one lemma.
        C04/C05 rely on stable ADJ lemma for ngram/NP extraction.
        """
        # LP_03: גדולה (fem sing) → גדול
        sent_03 = stanza_engine.process(lp_cases["C02_LP_03"]["input_text"])[0]
        adj_03 = next(t for t in sent_03.tokens if t.text == "גדולה")
        assert adj_03.lemma == "גדול", f"גדולה lemma expected גדול, got {adj_03.lemma!r}"

        # LP_04: גדולות (fem plur) → גדול
        sent_04 = stanza_engine.process(lp_cases["C02_LP_04"]["input_text"])[0]
        adj_04 = next(t for t in sent_04.tokens if t.text == "גדולות")
        assert adj_04.lemma == "גדול", f"גדולות lemma expected גדול, got {adj_04.lemma!r}"

        # LP_01: גדולים (masc plur) → גדול
        sent_01 = stanza_engine.process(lp_cases["C02_LP_01"]["input_text"])[0]
        adj_01 = next(t for t in sent_01.tokens if t.text == "גדולים")
        assert adj_01.lemma == "גדול", f"גדולים lemma expected גדול, got {adj_01.lemma!r}"

    def test_verb_all_past_conjugations_share_one_lemma(self, stanza_engine, lp_cases):
        """כתב (3ms), כתבה (3fs), כתבו (3pl) — all must have lemma=כתב.

        Verb lemma is gender-and-number-independent for past tense PAAL binyan.
        C03 aggregation will see all three forms as instances of the same lemma.
        """
        verb_tokens = {}
        for sid, form in [("C02_LP_05", "כתב"), ("C02_LP_06", "כתבה"), ("C02_LP_07", "כתבו")]:
            sent = stanza_engine.process(lp_cases[sid]["input_text"])[0]
            tok = next(t for t in sent.tokens if t.text == form)
            verb_tokens[form] = tok.lemma

        assert verb_tokens["כתב"] == "כתב", f"כתב lemma expected כתב, got {verb_tokens['כתב']!r}"
        assert verb_tokens["כתבה"] == "כתב", f"כתבה lemma expected כתב, got {verb_tokens['כתבה']!r}"
        assert verb_tokens["כתבו"] == "כתב", f"כתבו lemma expected כתב, got {verb_tokens['כתבו']!r}"
        # All three must agree
        assert (
            len(set(verb_tokens.values())) == 1
        ), f"All three verb forms must share one lemma. Got: {verb_tokens}"

    def test_fem_noun_plur_reduces_to_fem_sing_lemma(self, stanza_engine, lp_cases):
        """ערים (fem plur) must have lemma=עיר (fem sing), NOT a masc form.

        Documents: fem noun paradigm keeps fem lemma (unlike adj which always uses masc).
        This is a calibrated-by-design distinction, not inconsistency.
        """
        sent = stanza_engine.process(lp_cases["C02_LP_04"]["input_text"])[0]
        noun = next(t for t in sent.tokens if t.text == "ערים")
        assert (
            noun.lemma == "עיר"
        ), f"ערים (fem plur) lemma expected עיר (fem sing). Got: {noun.lemma!r}"


# ---------------------------------------------------------------------------
# POS consistency
# ---------------------------------------------------------------------------


@requires_stanza
class TestPOSConsistency:
    """POS must be stable across inflected forms within the same word class."""

    def test_noun_pos_stable_across_number(self, stanza_engine, lp_cases):
        """Singular and plural noun forms must both get NOUN pos."""
        # ספר (sing) from LP_05
        sent_sing = stanza_engine.process(lp_cases["C02_LP_05"]["input_text"])[0]
        tok_sing = next(t for t in sent_sing.tokens if t.text == "ספר")
        # ספרים (plur) from LP_01
        sent_plur = stanza_engine.process(lp_cases["C02_LP_01"]["input_text"])[0]
        tok_plur = next(t for t in sent_plur.tokens if t.text == "ספרים")
        assert tok_sing.pos == "NOUN", f"ספר pos expected NOUN, got {tok_sing.pos!r}"
        assert tok_plur.pos == "NOUN", f"ספרים pos expected NOUN, got {tok_plur.pos!r}"

    def test_adj_pos_stable_across_gender_and_number(self, stanza_engine, lp_cases):
        """All four adj forms (masc/fem × sing/plur) must get ADJ pos."""
        forms = {
            "גדול": lp_cases["C02_SMOKE_03"]["input_text"],  # masc sing (smoke)
            "גדולה": lp_cases["C02_LP_03"]["input_text"],  # fem sing
            "גדולים": lp_cases["C02_LP_01"]["input_text"],  # masc plur
            "גדולות": lp_cases["C02_LP_04"]["input_text"],  # fem plur
        }
        for form, input_text in forms.items():
            sent = stanza_engine.process(input_text)[0]
            tok = next((t for t in sent.tokens if t.text == form), None)
            assert tok is not None, f"Token {form!r} not found in output"
            assert tok.pos == "ADJ", f"{form!r} pos expected ADJ, got {tok.pos!r}"

    def test_verb_pos_stable_across_person_gender_number(self, stanza_engine, lp_cases):
        """All three verb forms (כתב/כתבה/כתבו) in sentence context must get VERB pos."""
        forms = {
            "כתב": lp_cases["C02_LP_05"]["input_text"],
            "כתבה": lp_cases["C02_LP_06"]["input_text"],
            "כתבו": lp_cases["C02_LP_07"]["input_text"],
        }
        for form, input_text in forms.items():
            sent = stanza_engine.process(input_text)[0]
            tok = next((t for t in sent.tokens if t.text == form), None)
            assert tok is not None, f"Token {form!r} not found"
            assert tok.pos == "VERB", f"{form!r} pos expected VERB, got {tok.pos!r}"


# ---------------------------------------------------------------------------
# Morph feature coverage
# ---------------------------------------------------------------------------


@requires_stanza
class TestMorphFeatureCoverage:
    """Pin presence of key morphological features in expected positions."""

    def test_fem_gender_in_noun(self, stanza_engine, lp_cases):
        """Feminine noun עיר must have Gender=Fem in morph string."""
        sent = stanza_engine.process(lp_cases["C02_LP_03"]["input_text"])[0]
        tok = next(t for t in sent.tokens if t.text == "עיר")
        assert "Gender=Fem" in tok.morph, f"עיר morph must contain Gender=Fem. Got: {tok.morph!r}"

    def test_plur_number_in_noun_and_adj(self, stanza_engine, lp_cases):
        """Plural forms must have Number=Plur in morph string."""
        sent = stanza_engine.process(lp_cases["C02_LP_01"]["input_text"])[0]
        for tok in sent.tokens:
            assert (
                "Number=Plur" in tok.morph
            ), f"Token {tok.text!r} in ספרים גדולים must have Number=Plur. Got: {tok.morph!r}"

    def test_tense_past_in_verb(self, stanza_engine, lp_cases):
        """Past tense verb כתב must have Tense=Past in morph string."""
        sent = stanza_engine.process(lp_cases["C02_LP_05"]["input_text"])[0]
        tok = next(t for t in sent.tokens if t.text == "כתב")
        assert "Tense=Past" in tok.morph, f"כתב morph must contain Tense=Past. Got: {tok.morph!r}"

    def test_prontype_prs_in_pronoun(self, stanza_engine, lp_cases):
        """Personal pronouns must have PronType=Prs in morph string."""
        for sid in ["C02_LP_05", "C02_LP_06", "C02_LP_07"]:
            sent = stanza_engine.process(lp_cases[sid]["input_text"])[0]
            pron = sent.tokens[0]  # first token is always the pronoun in LP_05..07
            assert pron.pos == "PRON", f"[{sid}] first token expected PRON, got {pron.pos!r}"
            assert (
                "PronType=Prs" in pron.morph
            ), f"[{sid}] {pron.text!r} morph must contain PronType=Prs. Got: {pron.morph!r}"


# ---------------------------------------------------------------------------
# Multi-sentence behavior
# ---------------------------------------------------------------------------


@requires_stanza
class TestMultiSentence:
    """Multi-sentence input produces correct sentence count, text, and PUNCT tokens."""

    def test_ms_01_oracle_passes(self, stanza_engine, lp_cases):
        """Full oracle check for C02_MS_01 multi-sentence case."""
        case = lp_cases["C02_MS_01"]
        result = validate_token_morphology(case, stanza_engine)
        assert result.match, f"C02_MS_01 oracle failed: {result.missing}"

    def test_ms_01_produces_two_sentences(self, stanza_engine):
        """'ספר גדול. עיר גדולה.' must produce exactly 2 Sentence objects."""
        sents = stanza_engine.process("ספר גדול. עיר גדולה.")
        assert len(sents) == 2, f"Expected 2 sentences, got {len(sents)}"

    def test_ms_01_sentence_text_includes_period(self, stanza_engine):
        """sentence.text must include the terminal period for each sentence.

        C01↔C02 boundary: StanzaEngine's sent.text includes the period
        ('ספר גדול.'), unlike C01 SentenceSplitter which detaches it.
        """
        sents = stanza_engine.process("ספר גדול. עיר גדולה.")
        assert (
            sents[0].text == "ספר גדול."
        ), f"First sentence text expected 'ספר גדול.', got {sents[0].text!r}"
        assert (
            sents[1].text == "עיר גדולה."
        ), f"Second sentence text expected 'עיר גדולה.', got {sents[1].text!r}"

    def test_ms_01_punct_token_per_sentence(self, stanza_engine):
        """Each sentence must include a PUNCT token for the terminal period.

        Stanza tokenizes '.' as a separate PUNCT token within each sentence.
        """
        sents = stanza_engine.process("ספר גדול. עיר גדולה.")
        for i, sent in enumerate(sents):
            punct_tokens = [t for t in sent.tokens if t.pos == "PUNCT"]
            assert (
                len(punct_tokens) == 1
            ), f"Sentence[{i}] must have exactly 1 PUNCT token. Got: {len(punct_tokens)}"
            assert (
                punct_tokens[0].text == "."
            ), f"Sentence[{i}] PUNCT token text must be '.'. Got: {punct_tokens[0].text!r}"
            assert (
                punct_tokens[0].morph == ""
            ), f"Sentence[{i}] PUNCT token morph must be ''. Got: {punct_tokens[0].morph!r}"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


@requires_stanza
class TestDeterminism:
    """Same input must produce identical structured output on two consecutive calls."""

    def test_determinism_sentence_and_token_structure(self, stanza_engine):
        """StanzaEngine.process() must be deterministic across calls.

        Identical input → identical list of (sentence.text, token.text, token.lemma,
        token.pos, token.morph) tuples on two independent calls.
        """

        def _struct(sents):
            return [(s.text, [(t.text, t.lemma, t.pos, t.morph) for t in s.tokens]) for s in sents]

        text = "הם כתבו ספרים גדולים"
        r1 = stanza_engine.process(text)
        r2 = stanza_engine.process(text)
        assert _struct(r1) == _struct(r2), (
            f"StanzaEngine is non-deterministic. " f"Run1: {_struct(r1)}\nRun2: {_struct(r2)}"
        )
