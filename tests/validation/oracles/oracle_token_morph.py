"""Oracle for tokenization and morphology validation (C02).

Calls StanzaEngine.process() and compares output against gold expected values.

Comparison strategy:
- sentence_count: exact integer match
- sentence_text: exact string match (optional; checks sent.text == expected)
- token_count: exact integer match per sentence
- text:  exact string match (surface form)
- pos:   exact string match (Universal POS tag, e.g. NOUN, VERB, DET)
- lemma: exact string match
- morph_contains: partial feature match — each listed feature string must appear
  as a substring of Token.morph. Intentionally loose for Stanza version robustness.
- morph: exact full string match — only checked if the gold case provides it.

Structural invariants (validate_token_invariants):
- All token.text are non-empty str
- All token.pos are non-empty str (never "" or "X" reserved only for truly unknown)
- All token.lemma are str (may equal text; never None — fallback applied by StanzaEngine)
- All token.morph are str (may be ""; never None — _format_feats normalises this)

Oracle note: this oracle calls the actual StanzaEngine which loads the Hebrew
Stanza model. It is NOT DB-free. Do NOT call from tests that lack the
stanza_engine fixture or the @requires_stanza marker.

See: tests/validation/conftest.py — stanza_engine fixture + requires_stanza mark.
See: docs/validation/STANZA_HE_PREP.md — setup guide for Stanza Hebrew model.
"""

from __future__ import annotations

from tests.validation.oracles.base_oracle import OracleResult


def validate_token_invariants(sentences: list, case_id: str = "") -> list[str]:
    """Check structural invariants on StanzaEngine output.

    Invariants that must hold for ALL inputs regardless of content:
    1. token.text is non-empty str
    2. token.pos is non-empty str (StanzaEngine falls back to "X", never "")
    3. token.lemma is str (StanzaEngine falls back to token.text if Stanza returns None)
    4. token.morph is str, never None (_format_feats normalises None → "")

    Args:
        sentences: list of Sentence objects from StanzaEngine.process()
        case_id:   optional label for error messages

    Returns:
        List of violation strings. Empty list means all invariants hold.
    """
    violations: list[str] = []
    label = f"[{case_id}] " if case_id else ""
    for s_idx, sent in enumerate(sentences):
        for t_idx, tok in enumerate(sent.tokens):
            loc = f"{label}sent[{s_idx}] tok[{t_idx}] text={tok.text!r}"
            if not isinstance(tok.text, str) or not tok.text:
                violations.append(f"{loc}: token.text must be non-empty str")
            if not isinstance(tok.pos, str) or not tok.pos:
                violations.append(f"{loc}: token.pos must be non-empty str, got {tok.pos!r}")
            if not isinstance(tok.lemma, str):
                violations.append(
                    f"{loc}: token.lemma must be str (not {type(tok.lemma).__name__})"
                )
            if not isinstance(tok.morph, str):
                violations.append(
                    f"{loc}: token.morph must be str, not None (got {type(tok.morph).__name__})"
                )
    return violations


def validate_token_morphology(case: dict, engine) -> OracleResult:
    """Validate token/POS/lemma/morph output for one C02 gold case.

    Args:
        case: One case dict from c02_token_morph.json. Must contain:
              - case_id: str
              - input_text: str
              - expected_sentences: list of {token_count, tokens: [{text, pos, lemma,
                morph_contains?, morph?}]}
        engine: Initialized StanzaEngine instance (from stanza_engine fixture).

    Returns:
        OracleResult with match=True iff all checks pass.
    """
    case_id: str = case["case_id"]
    input_text: str = case["input_text"]
    expected_sentences: list[dict] = case.get("expected_sentences", [])

    actual_sentences = engine.process(input_text)
    failures: list[str] = []

    # Sentence count
    if len(actual_sentences) != len(expected_sentences):
        failures.append(
            f"sentence count: expected={len(expected_sentences)}, actual={len(actual_sentences)}"
        )
        return OracleResult(
            case_id=case_id,
            match=False,
            expected=expected_sentences,
            actual=actual_sentences,
            missing=failures,
        )

    for s_idx, (exp_sent, act_sent) in enumerate(zip(expected_sentences, actual_sentences)):
        exp_tokens = exp_sent.get("tokens", [])
        act_tokens = act_sent.tokens

        # Sentence text (optional — only checked if provided in gold)
        if "sentence_text" in exp_sent and act_sent.text != exp_sent["sentence_text"]:
            failures.append(
                f"sentence[{s_idx}] text: expected={exp_sent['sentence_text']!r},"
                f" actual={act_sent.text!r}"
            )

        # Token count per sentence
        exp_count = exp_sent.get("token_count", len(exp_tokens))
        if len(act_tokens) != exp_count:
            failures.append(
                f"sentence[{s_idx}] token count: expected={exp_count}, actual={len(act_tokens)}"
            )
            continue  # can't compare individual tokens if count differs

        for t_idx, (exp_tok, act_tok) in enumerate(zip(exp_tokens, act_tokens)):
            prefix = f"sentence[{s_idx}] token[{t_idx}]"

            # Surface text
            if "text" in exp_tok and act_tok.text != exp_tok["text"]:
                failures.append(
                    f"{prefix} text: expected={exp_tok['text']!r}, actual={act_tok.text!r}"
                )

            # POS
            if "pos" in exp_tok and act_tok.pos != exp_tok["pos"]:
                failures.append(
                    f"{prefix} pos: expected={exp_tok['pos']!r}, actual={act_tok.pos!r}"
                )

            # Lemma
            if "lemma" in exp_tok and act_tok.lemma != exp_tok["lemma"]:
                failures.append(
                    f"{prefix} lemma: expected={exp_tok['lemma']!r}, actual={act_tok.lemma!r}"
                )

            # Morph partial match (feature-by-feature, model-version-robust)
            for feature in exp_tok.get("morph_contains", []):
                if feature not in act_tok.morph:
                    failures.append(
                        f"{prefix} morph missing feature={feature!r}"
                        f" (actual morph={act_tok.morph!r})"
                    )

            # Morph exact match (only if provided — stricter, Wave 6b+)
            if "morph" in exp_tok and act_tok.morph != exp_tok["morph"]:
                failures.append(
                    f"{prefix} morph exact: expected={exp_tok['morph']!r},"
                    f" actual={act_tok.morph!r}"
                )

    return OracleResult(
        case_id=case_id,
        match=len(failures) == 0,
        expected=expected_sentences,
        actual=[
            {
                "text": s.text,
                "tokens": [
                    {"text": t.text, "lemma": t.lemma, "pos": t.pos, "morph": t.morph}
                    for t in s.tokens
                ],
            }
            for s in actual_sentences
        ],
        missing=failures,
    )
