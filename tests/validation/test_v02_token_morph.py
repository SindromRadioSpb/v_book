"""V02 — Tokenization and morphology via StanzaEngine (C02).

Wave 6a: Infrastructure smoke tests only.
These tests verify that:
  - The Stanza Hebrew pipeline can be loaded and returns correct output structure
  - Three calibrated smoke cases pass (interjection, DET prefix detachment, NOUN+ADJ)
  - The skip mechanism is correctly wired (Stanza unavailable → all tests skip)

What these tests do NOT validate:
  - Morphology contract across word classes (Wave 6b)
  - Lemma paradigms (plural, verb conjugations) (Wave 6b)
  - Multi-sentence segmentation alignment (Wave 6b)
  - Full feature coverage or version-independent morph strings (Wave 6b)

All tests are decorated with @requires_stanza and/or use the stanza_engine fixture.
Skip behaviour:
  - stanza package not installed → all tests skip (requires_stanza marker)
  - he/ model directory absent → all tests skip (requires_stanza marker)
  - StanzaEngine init fails → tests using stanza_engine fixture skip

PowerShell commands:
  # Run C02 tests only (requires stanza + he model):
  .venv\\Scripts\\python.exe -m pytest tests/validation/test_v02_token_morph.py -v
  # Run only stanza-tagged tests across all validation:
  .venv\\Scripts\\python.exe -m pytest tests/validation/ -v -m requires_stanza
  # Run non-stanza validation (unchanged baseline):
  .venv\\Scripts\\python.exe -m pytest tests/validation/ -v -k "not v02 and not stanza"

See: docs/validation/STANZA_HE_PREP.md — setup guide for Stanza Hebrew model.
See: docs/validation/audits/C02_AUDIT.md — audit doc (Wave 6a infra prep).
"""

from __future__ import annotations

import pytest

from tests.validation.conftest import _stanza_he_model_available, requires_stanza
from tests.validation.oracles.oracle_token_morph import validate_token_morphology


# ---------------------------------------------------------------------------
# Infra availability tests
# (Always run — they ARE the preflight. If stanza not installed, they skip via
#  the requires_stanza decorator, not fail. That keeps the non-stanza baseline clean.)
# ---------------------------------------------------------------------------


@requires_stanza
class TestStanzaInfraSmoke:
    """Infrastructure and output-contract checks. No morphology gold needed."""

    def test_stanza_package_importable(self):
        """stanza package must be importable. Fails → install stanza>=1.7.0."""
        import stanza

        assert stanza.__version__, "stanza.__version__ must be non-empty"

    def test_stanza_he_model_directory_exists(self):
        """Hebrew model directory must exist on disk (cheap check, no pipeline load).

        If this fails: run the model download command — see docs/validation/STANZA_HE_PREP.md.
        """
        assert _stanza_he_model_available(), (
            "Stanza Hebrew model directory not found. "
            "Run: .venv\\Scripts\\python.exe -c \"import stanza; stanza.download('he')\""
        )

    def test_engine_initializes(self, stanza_engine):
        """StanzaEngine must initialize and report name/version.

        Uses stanza_engine fixture — skips if pipeline load fails.
        """
        assert stanza_engine is not None
        assert stanza_engine.get_name() == "stanza"
        assert stanza_engine.get_version(), "engine version must be non-empty"

    def test_empty_text_returns_empty_list(self, stanza_engine):
        """StanzaEngine.process('') must return []. By design: no text → no sentences."""
        assert stanza_engine.process("") == []
        assert stanza_engine.process("   ") == []

    def test_process_returns_list_of_sentence_objects(self, stanza_engine):
        """Non-empty text must return list[Sentence] with at least one sentence."""
        from app.infra.nlp_engines.base import Sentence

        result = stanza_engine.process("hello world")
        assert isinstance(result, list), "process() must return a list"
        assert len(result) > 0, "non-empty text must produce at least one sentence"
        assert isinstance(result[0], Sentence), "list elements must be Sentence instances"

    def test_token_has_required_fields_text_lemma_pos_morph(self, stanza_engine):
        """Every Token must have text, lemma, pos (str) and morph (str, not None).

        Confirms StanzaEngine normalises None feats → empty string.
        """
        from app.infra.nlp_engines.base import Token

        result = stanza_engine.process("hello world")
        assert len(result) > 0 and len(result[0].tokens) > 0
        tok = result[0].tokens[0]
        assert isinstance(tok, Token)
        assert isinstance(tok.text, str) and tok.text != ""
        assert isinstance(tok.lemma, str)  # may equal text; must not be None
        assert isinstance(tok.pos, str) and tok.pos != ""
        assert isinstance(tok.morph, str)  # empty string allowed; None is not


# ---------------------------------------------------------------------------
# Calibrated smoke tests against gold (Wave 6a)
# ---------------------------------------------------------------------------


@requires_stanza
class TestC02SmokeCases:
    """Three calibrated cases from c02_token_morph.json (Wave 6a).

    These prove the infra is wired end-to-end but do NOT constitute a morphology
    contract validation. See TODO_wave_6b in the gold file for what's still missing.
    """

    def test_c02_smoke_01_interjection(self, stanza_engine, gold_data):
        """C02_SMOKE_01: שלום → 1 token, pos=INTJ, morph='' (no features).

        Minimum valid single-word case.
        """
        case = next(
            c for c in gold_data("c02_token_morph")["cases"] if c["case_id"] == "C02_SMOKE_01"
        )
        result = validate_token_morphology(case, stanza_engine)
        assert result.match, f"C02_SMOKE_01 failed: {result.missing}"

    def test_c02_smoke_02_det_prefix_detachment(self, stanza_engine, gold_data):
        """C02_SMOKE_02: הכלב רץ → 3 tokens (ה DET + כלב NOUN + רץ VERB).

        Pins the Hebrew DET prefix detachment contract: surface 'הכלב' → 2 tokens.
        Token count=3, not 2. Critical for downstream NP extractor (C05).
        """
        case = next(
            c for c in gold_data("c02_token_morph")["cases"] if c["case_id"] == "C02_SMOKE_02"
        )
        result = validate_token_morphology(case, stanza_engine)
        assert result.match, f"C02_SMOKE_02 failed: {result.missing}"

    def test_c02_smoke_03_noun_adj(self, stanza_engine, gold_data):
        """C02_SMOKE_03: ספר גדול → 2 tokens (ספר NOUN + גדול ADJ).

        Confirms NOUN+ADJ POS assignment — pattern central to NP extraction.
        """
        case = next(
            c for c in gold_data("c02_token_morph")["cases"] if c["case_id"] == "C02_SMOKE_03"
        )
        result = validate_token_morphology(case, stanza_engine)
        assert result.match, f"C02_SMOKE_03 failed: {result.missing}"

    def test_he_det_prefix_token_count_is_three_not_two(self, stanza_engine):
        """Inline pin: 'הכלב רץ' must produce 3 tokens, not 2.

        Explicit guard against a future Stanza version that might merge the prefix back.
        This is a contract boundary between C02 (tokenization) and C05 (NP extraction).
        """
        sents = stanza_engine.process("הכלב רץ")
        assert len(sents) == 1
        assert len(sents[0].tokens) == 3, (
            f"Expected 3 tokens (ה + כלב + רץ), got {len(sents[0].tokens)}: "
            f"{[t.text for t in sents[0].tokens]}"
        )
        assert (
            sents[0].tokens[0].pos == "DET"
        ), f"First token must be DET (detached article ה), got pos={sents[0].tokens[0].pos!r}"
