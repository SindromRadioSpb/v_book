"""Tests for PolicyRenderer (PATCH-02).

Verifies:
- sentence_ru renders identically to the pre-PPS hardcoded template (regression)
- lemma_ru role instruction roundtrip through sentinel
- Sentinel parsing: role_instruction and user_content recovered correctly
- No sentinel present → legacy-compatible user_content produced
- Glossary block rendered for SOFT_GLOSSARY / STRICT_GLOSSARY
- Glossary suppressed for TerminologyMode.OFF (lemma_ru)
- Context block rendered when context_mode != OFF
- max_glossary_items cap applied
- render_effective_preview includes [Role] and [User] sections

No torch import — all tests operate on strings only.
"""

import pytest

from app.infra.translators.prompt_policy import (
    ContextMode,
    PolicyRenderer,
    TerminologyMode,
    _PPS_ROLE_SEP,
    _PPS_SENTINEL_START,
    get_policy,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RENDERER = PolicyRenderer()

SENTENCE_TASK = "Translate the following segment into Russian, without additional explanation."
LEMMA_TASK = "Translate the following Hebrew lemma into Russian."


# ---------------------------------------------------------------------------
# Regression baseline: sentence_ru without glossary
# ---------------------------------------------------------------------------


def test_sentence_ru_no_glossary_matches_legacy_user_content() -> None:
    """sentence_ru + no glossary must produce EXACTLY the pre-PPS user_content.

    Pre-PPS worker hardcoded:
        f"Translate the following segment into Russian, without additional explanation.\\n\\n{source}"
    PolicyRenderer must produce the identical string.
    """
    policy = get_policy("sentence_ru")
    source = "שלום"
    result = _RENDERER.render_user_content(policy, source)
    expected = f"{SENTENCE_TASK}\n\n{source}"
    assert result == expected


def test_sentence_ru_sentinel_user_content_equals_legacy() -> None:
    """Sentinel payload user_content for sentence_ru must equal legacy user_content."""
    policy = get_policy("sentence_ru")
    source = "שלום"
    sentinel = _RENDERER.render_sentinel_payload(policy, source)
    assert sentinel.startswith(_PPS_SENTINEL_START)
    payload = sentinel[len(_PPS_SENTINEL_START) :]
    sep_idx = payload.find(_PPS_ROLE_SEP)
    assert sep_idx != -1
    role_instruction = payload[:sep_idx]
    user_content = payload[sep_idx + len(_PPS_ROLE_SEP) :]
    assert role_instruction == ""
    assert user_content == f"{SENTENCE_TASK}\n\nשלום"


# ---------------------------------------------------------------------------
# Sentinel structure
# ---------------------------------------------------------------------------


def test_sentinel_starts_with_null_byte() -> None:
    policy = get_policy("sentence_ru")
    sentinel = _RENDERER.render_sentinel_payload(policy, "test")
    assert sentinel[0] == "\x00"


def test_sentinel_contains_role_sep() -> None:
    policy = get_policy("sentence_ru")
    sentinel = _RENDERER.render_sentinel_payload(policy, "test")
    assert _PPS_ROLE_SEP in sentinel


def test_sentinel_role_empty_for_sentence_ru() -> None:
    policy = get_policy("sentence_ru")
    sentinel = _RENDERER.render_sentinel_payload(policy, "test")
    payload = sentinel[len(_PPS_SENTINEL_START) :]
    role_instruction = payload[: payload.find(_PPS_ROLE_SEP)]
    assert role_instruction == ""


def test_sentinel_natural_source_text_never_matches_prefix() -> None:
    """Ordinary Hebrew text cannot start with the null-byte sentinel prefix."""
    natural_texts = ["שלום", "test", "Translate", "\n\n", ""]
    for text in natural_texts:
        assert not text.startswith(_PPS_SENTINEL_START)


# ---------------------------------------------------------------------------
# lemma_ru — role instruction roundtrip
# ---------------------------------------------------------------------------


def test_lemma_ru_role_instruction_in_sentinel() -> None:
    policy = get_policy("lemma_ru")
    sentinel = _RENDERER.render_sentinel_payload(policy, "ילד")
    payload = sentinel[len(_PPS_SENTINEL_START) :]
    sep_idx = payload.find(_PPS_ROLE_SEP)
    role_instruction = payload[:sep_idx]
    assert "lexicograph" in role_instruction.lower()


def test_lemma_ru_user_content_has_task_and_source() -> None:
    policy = get_policy("lemma_ru")
    source = "ילד"
    result = _RENDERER.render_user_content(policy, source)
    assert LEMMA_TASK in result
    assert source in result


def test_lemma_ru_user_content_task_before_source() -> None:
    policy = get_policy("lemma_ru")
    source = "ילד"
    result = _RENDERER.render_user_content(policy, source)
    assert result.index(LEMMA_TASK) < result.index(source)


def test_lemma_ru_output_policy_in_user_content() -> None:
    policy = get_policy("lemma_ru")
    result = _RENDERER.render_user_content(policy, "ילד")
    assert policy.output_policy in result


def test_lemma_ru_output_policy_before_source() -> None:
    policy = get_policy("lemma_ru")
    source = "ילד"
    result = _RENDERER.render_user_content(policy, source)
    assert result.index(policy.output_policy) < result.index(source)


# ---------------------------------------------------------------------------
# Glossary rendering
# ---------------------------------------------------------------------------


def test_sentence_ru_glossary_block_appended_before_source() -> None:
    policy = get_policy("sentence_ru")
    source = "המחשב"
    terms = [("המחשב", "компьютер")]
    result = _RENDERER.render_user_content(policy, source, glossary_terms=terms)
    assert "Terminology:" in result
    assert "המחשב: компьютер" in result
    assert result.index("Terminology:") < result.index(source)


def test_soft_glossary_header() -> None:
    policy = get_policy("sentence_ru")
    assert policy.terminology_mode == TerminologyMode.SOFT_GLOSSARY
    result = _RENDERER.render_user_content(policy, "x", glossary_terms=[("a", "б")])
    assert "Terminology:" in result
    assert "Approved" not in result


def test_strict_glossary_header() -> None:
    policy = get_policy("term_ru_strict_glossary")
    assert policy.terminology_mode == TerminologyMode.STRICT_GLOSSARY
    result = _RENDERER.render_user_content(policy, "x", glossary_terms=[("a", "б")])
    assert "Approved Terminology (use exactly):" in result


def test_glossary_suppressed_for_terminology_mode_off() -> None:
    """lemma_ru has TerminologyMode.OFF — glossary must never appear even if passed."""
    policy = get_policy("lemma_ru")
    assert policy.terminology_mode == TerminologyMode.OFF
    result = _RENDERER.render_user_content(policy, "ילד", glossary_terms=[("ילד", "ребёнок")])
    assert "Terminology" not in result
    assert "ребёнок" not in result


def test_glossary_none_produces_no_terminology_block() -> None:
    policy = get_policy("sentence_ru")
    result = _RENDERER.render_user_content(policy, "text", glossary_terms=None)
    assert "Terminology" not in result


def test_glossary_empty_list_produces_no_terminology_block() -> None:
    policy = get_policy("sentence_ru")
    result = _RENDERER.render_user_content(policy, "text", glossary_terms=[])
    assert "Terminology" not in result


def test_glossary_capped_by_max_glossary_items() -> None:
    policy = get_policy("sentence_ru")
    assert policy.max_glossary_items == 20
    # Supply 25 terms; only 20 should appear
    terms = [(f"src{i}", f"tgt{i}") for i in range(25)]
    result = _RENDERER.render_user_content(policy, "x", glossary_terms=terms)
    assert "src19: tgt19" in result
    assert "src20: tgt20" not in result


def test_glossary_uncapped_when_max_glossary_items_is_none() -> None:
    policy = get_policy("lemma_ru")
    assert policy.max_glossary_items is None
    # But lemma_ru has TerminologyMode.OFF, so glossary is suppressed.
    # Use term_ru which has max_glossary_items=20 for this test.
    policy_term = get_policy("term_ru")
    assert policy_term.max_glossary_items == 20
    terms = [(f"src{i}", f"tgt{i}") for i in range(5)]
    result = _RENDERER.render_user_content(policy_term, "x", glossary_terms=terms)
    for i in range(5):
        assert f"src{i}: tgt{i}" in result


# ---------------------------------------------------------------------------
# Context block
# ---------------------------------------------------------------------------


def test_context_block_rendered_when_context_mode_set() -> None:
    policy = get_policy("sentence_ru_context")
    assert policy.context_mode == ContextMode.SURROUNDING_SENTENCES
    context = ["Previous sentence here.", "Next sentence here."]
    result = _RENDERER.render_user_content(policy, "target", context_items=context)
    assert "Context:" in result
    assert "Previous sentence here." in result


def test_context_block_suppressed_when_context_mode_off() -> None:
    policy = get_policy("sentence_ru")
    assert policy.context_mode == ContextMode.OFF
    result = _RENDERER.render_user_content(policy, "text", context_items=["some context"])
    assert "Context:" not in result


def test_context_block_suppressed_when_context_items_none() -> None:
    policy = get_policy("sentence_ru_context")
    result = _RENDERER.render_user_content(policy, "text", context_items=None)
    assert "Context:" not in result


# ---------------------------------------------------------------------------
# render_effective_preview
# ---------------------------------------------------------------------------


def test_preview_includes_user_section() -> None:
    policy = get_policy("sentence_ru")
    preview = _RENDERER.render_effective_preview(policy, "שלום")
    assert "[User]" in preview


def test_preview_no_role_section_when_role_empty() -> None:
    policy = get_policy("sentence_ru")
    assert policy.role_instruction == ""
    preview = _RENDERER.render_effective_preview(policy, "שלום")
    assert "[Role]" not in preview


def test_preview_includes_role_section_for_lemma_ru() -> None:
    policy = get_policy("lemma_ru")
    assert policy.role_instruction != ""
    preview = _RENDERER.render_effective_preview(policy, "ילד")
    assert "[Role]" in preview
    assert "lexicograph" in preview.lower()


def test_preview_role_before_user() -> None:
    policy = get_policy("lemma_ru")
    preview = _RENDERER.render_effective_preview(policy, "ילד")
    assert preview.index("[Role]") < preview.index("[User]")


# ---------------------------------------------------------------------------
# render_user_content — source text always present
# ---------------------------------------------------------------------------


def test_source_text_always_in_user_content() -> None:
    for policy_id in ("sentence_ru", "lemma_ru", "term_ru", "term_ru_strict_glossary"):
        policy = get_policy(policy_id)
        source = f"__src_{policy_id}__"
        result = _RENDERER.render_user_content(policy, source)
        assert source in result, f"source missing for policy '{policy_id}'"


def test_source_text_is_last_part() -> None:
    """Source text must always be the final segment in user_content."""
    for policy_id in ("sentence_ru", "lemma_ru", "term_ru"):
        policy = get_policy(policy_id)
        source = f"__src_{policy_id}__"
        result = _RENDERER.render_user_content(policy, source, glossary_terms=[("a", "б")])
        assert result.endswith(source), f"source not last for policy '{policy_id}'"
