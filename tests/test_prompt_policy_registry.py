"""Tests for prompt_policy.py (PATCH-01: domain model + registry).

Verifies:
- All 6 production profiles loadable at import time (no I/O)
- All 3 sampling profiles loadable
- All 6 template profiles loadable
- sentence_ru is the default and matches current production gen_kwargs exactly
- TerminologyMode values are correctly assigned (V3 canonical enum)
- SamplingProfile.validate() passes for all built-in profiles
- Registry cross-references are consistent (no unknown profile IDs)
- Registry guards: unknown lookups raise KeyError
"""

import pytest

from app.infra.translators.prompt_policy import (
    DEFAULT_POLICY_ID,
    PROMPT_POLICIES,
    SAMPLING_PROFILES,
    TEMPLATE_PROFILES,
    ContentKind,
    ContextMode,
    FormattingMode,
    PlaceholderMode,
    TerminologyMode,
    get_policy,
    get_sampling_profile,
    get_template_profile,
    list_profiles,
)


# ============================================================================
# Registry completeness
# ============================================================================


def test_all_six_policies_present() -> None:
    expected = {
        "sentence_ru",
        "sentence_ru_context",
        "sentence_ru_formatted",
        "lemma_ru",
        "term_ru",
        "term_ru_strict_glossary",
    }
    assert expected == set(PROMPT_POLICIES.keys())


def test_three_sampling_profiles_present() -> None:
    expected = {
        "hy_mt_precise_sentence",
        "hy_mt_precise_short",
        "hy_mt_precise_formatted",
    }
    assert expected == set(SAMPLING_PROFILES.keys())


def test_six_template_profiles_present() -> None:
    expected = {
        "hy_mt_standard_observed",
        "hy_mt_glossary_observed",
        "hy_mt_context_observed",
        "hy_mt_formatted_observed",
        "hy_mt_7b_standard",
        "hy_mt_7b_glossary",
    }
    assert expected == set(TEMPLATE_PROFILES.keys())


def test_default_policy_id_is_sentence_ru() -> None:
    assert DEFAULT_POLICY_ID == "sentence_ru"
    assert DEFAULT_POLICY_ID in PROMPT_POLICIES


# ============================================================================
# sentence_ru — regression baseline
# ============================================================================


def test_sentence_ru_content_kind() -> None:
    assert get_policy("sentence_ru").content_kind == ContentKind.SENTENCE


def test_sentence_ru_terminology_mode_soft_glossary() -> None:
    """sentence_ru uses soft_glossary — V3 canonical for old BOTH."""
    assert get_policy("sentence_ru").terminology_mode == TerminologyMode.SOFT_GLOSSARY


def test_sentence_ru_sampling_profile() -> None:
    assert get_policy("sentence_ru").sampling_profile_id == "hy_mt_precise_sentence"


def test_sentence_ru_template_profile() -> None:
    assert get_policy("sentence_ru").template_profile_id == "hy_mt_standard_observed"


def test_sentence_ru_not_experimental() -> None:
    assert not get_policy("sentence_ru").experimental


def test_sentence_ru_task_instruction_mentions_russian() -> None:
    assert "Russian" in get_policy("sentence_ru").task_instruction


def test_sentence_ru_no_role_instruction() -> None:
    assert get_policy("sentence_ru").role_instruction == ""


def test_sentence_ru_no_output_policy() -> None:
    assert get_policy("sentence_ru").output_policy == ""


def test_sentence_ru_is_builtin() -> None:
    p = get_policy("sentence_ru")
    assert p.is_builtin
    assert not p.is_custom


def test_sentence_ru_context_mode_off() -> None:
    assert get_policy("sentence_ru").context_mode == ContextMode.OFF


def test_sentence_ru_max_glossary_items() -> None:
    assert get_policy("sentence_ru").max_glossary_items == 20


# ============================================================================
# lemma_ru
# ============================================================================


def test_lemma_ru_terminology_mode_off() -> None:
    """lemma_ru disables glossary — lemma output is itself the canonical term."""
    assert get_policy("lemma_ru").terminology_mode == TerminologyMode.OFF


def test_lemma_ru_sampling_profile() -> None:
    assert get_policy("lemma_ru").sampling_profile_id == "hy_mt_precise_short"


def test_lemma_ru_content_kind() -> None:
    assert get_policy("lemma_ru").content_kind == ContentKind.LEMMA


def test_lemma_ru_plain_text_formatting() -> None:
    assert get_policy("lemma_ru").formatting_mode == FormattingMode.PLAIN_TEXT


def test_lemma_ru_has_role_instruction() -> None:
    role = get_policy("lemma_ru").role_instruction
    assert "lexicograph" in role.lower()


def test_lemma_ru_has_output_policy() -> None:
    assert get_policy("lemma_ru").output_policy != ""


def test_lemma_ru_glossary_items_none() -> None:
    assert get_policy("lemma_ru").max_glossary_items is None


# ============================================================================
# term_ru vs term_ru_strict_glossary
# ============================================================================


def test_term_ru_terminology_mode() -> None:
    assert get_policy("term_ru").terminology_mode == TerminologyMode.SOFT_GLOSSARY


def test_term_strict_terminology_mode() -> None:
    assert get_policy("term_ru_strict_glossary").terminology_mode == TerminologyMode.STRICT_GLOSSARY


def test_term_strict_differs_from_term_ru() -> None:
    assert (
        get_policy("term_ru_strict_glossary").terminology_mode
        != get_policy("term_ru").terminology_mode
    )


def test_term_strict_sampling_profile() -> None:
    assert get_policy("term_ru_strict_glossary").sampling_profile_id == "hy_mt_precise_short"


def test_both_term_profiles_same_content_kind() -> None:
    assert get_policy("term_ru").content_kind == ContentKind.TERM
    assert get_policy("term_ru_strict_glossary").content_kind == ContentKind.TERM


# ============================================================================
# sentence_ru_formatted
# ============================================================================


def test_sentence_formatted_sampling_profile() -> None:
    assert get_policy("sentence_ru_formatted").sampling_profile_id == "hy_mt_precise_formatted"


def test_sentence_formatted_template_has_placeholder_note() -> None:
    p = get_policy("sentence_ru_formatted")
    tmpl = get_template_profile(p.template_profile_id)
    assert tmpl.use_placeholder_note is True


def test_sentence_formatted_not_experimental() -> None:
    assert not get_policy("sentence_ru_formatted").experimental


# ============================================================================
# Experimental profiles
# ============================================================================


def test_sentence_ru_context_is_experimental() -> None:
    assert get_policy("sentence_ru_context").experimental


def test_sentence_ru_context_has_context_mode() -> None:
    assert get_policy("sentence_ru_context").context_mode == ContextMode.SURROUNDING_SENTENCES


def test_list_profiles_excludes_experimental_by_default() -> None:
    profiles = list_profiles()
    ids = [p.policy_id for p in profiles]
    assert "sentence_ru_context" not in ids


def test_list_profiles_includes_all_with_flag() -> None:
    profiles = list_profiles(include_experimental=True)
    ids = [p.policy_id for p in profiles]
    assert "sentence_ru_context" in ids
    assert len(ids) == 6


def test_list_profiles_non_experimental_count() -> None:
    assert len(list_profiles()) == 5


def test_list_profiles_sorted_by_policy_id() -> None:
    ids = [p.policy_id for p in list_profiles(include_experimental=True)]
    assert ids == sorted(ids)


# ============================================================================
# SamplingProfile validation
# ============================================================================


def test_all_sampling_profiles_valid() -> None:
    for profile in SAMPLING_PROFILES.values():
        errors = profile.validate()
        assert errors == [], f"Profile '{profile.sampling_profile_id}' failed validation: {errors}"


def test_precise_sentence_matches_production_gen_kwargs() -> None:
    """hy_mt_precise_sentence must match current hard-coded gen_kwargs for 1.8B.

    These values are the regression baseline.  Any change here invalidates the
    MT cache for all existing sentence_ru translations.
    """
    p = get_sampling_profile("hy_mt_precise_sentence")
    assert p.temperature == 0.7
    assert p.top_k == 20
    assert p.top_p == 0.6
    assert p.repetition_penalty == 1.05
    assert p.n_predict == 512


def test_precise_short_greedy_by_temperature() -> None:
    """hy_mt_precise_short uses temperature=0.0 (greedy by intent, not hardware constraint)."""
    p = get_sampling_profile("hy_mt_precise_short")
    assert p.temperature == 0.0
    assert p.n_predict == 32


def test_precise_formatted_lower_temperature_than_sentence() -> None:
    formatted = get_sampling_profile("hy_mt_precise_formatted")
    sentence = get_sampling_profile("hy_mt_precise_sentence")
    assert formatted.temperature < sentence.temperature


def test_precise_formatted_higher_repetition_penalty() -> None:
    formatted = get_sampling_profile("hy_mt_precise_formatted")
    sentence = get_sampling_profile("hy_mt_precise_sentence")
    assert formatted.repetition_penalty > sentence.repetition_penalty


def test_sampling_validate_rejects_negative_temperature() -> None:
    from app.infra.translators.prompt_policy import SamplingProfile

    bad = SamplingProfile(
        sampling_profile_id="bad_temp",
        name="Bad",
        description="",
        temperature=-0.1,
    )
    errors = bad.validate()
    assert any("temperature" in e for e in errors)


def test_sampling_validate_rejects_invalid_top_p() -> None:
    from app.infra.translators.prompt_policy import SamplingProfile

    bad = SamplingProfile(
        sampling_profile_id="bad_top_p",
        name="Bad",
        description="",
        top_p=1.5,
    )
    errors = bad.validate()
    assert any("top_p" in e for e in errors)


def test_sampling_validate_rejects_invalid_mirostat() -> None:
    from app.infra.translators.prompt_policy import SamplingProfile

    bad = SamplingProfile(
        sampling_profile_id="bad_mirostat",
        name="Bad",
        description="",
        mirostat_mode=5,
    )
    errors = bad.validate()
    assert any("mirostat" in e for e in errors)


# ============================================================================
# TemplateProfile
# ============================================================================


def test_formatted_template_has_placeholder_note() -> None:
    t = get_template_profile("hy_mt_formatted_observed")
    assert t.use_placeholder_note is True


def test_context_template_has_context_block() -> None:
    t = get_template_profile("hy_mt_context_observed")
    assert t.use_context_block is True


def test_glossary_templates_have_glossary_block() -> None:
    for tid in ("hy_mt_glossary_observed", "hy_mt_7b_glossary"):
        t = get_template_profile(tid)
        assert t.use_glossary_block is True, f"{tid} must have use_glossary_block"


def test_7b_templates_force_greedy() -> None:
    for tid in ("hy_mt_7b_standard", "hy_mt_7b_glossary"):
        t = get_template_profile(tid)
        assert t.force_greedy is True, f"{tid} must force greedy"
        assert t.max_n_predict_cap == 128, f"{tid} cap must be 128"


def test_1b8_templates_not_force_greedy() -> None:
    for tid in (
        "hy_mt_standard_observed",
        "hy_mt_glossary_observed",
        "hy_mt_context_observed",
        "hy_mt_formatted_observed",
    ):
        t = get_template_profile(tid)
        assert not t.force_greedy, f"{tid} must not force greedy"
        assert t.max_n_predict_cap == 512, f"{tid} cap must be 512"


def test_7b_cap_less_than_1b8_cap() -> None:
    assert (
        get_template_profile("hy_mt_7b_standard").max_n_predict_cap
        < get_template_profile("hy_mt_standard_observed").max_n_predict_cap
    )


# ============================================================================
# Cross-references (all policies point to existing profiles)
# ============================================================================


def test_all_policies_reference_valid_sampling_profile() -> None:
    for policy in PROMPT_POLICIES.values():
        assert policy.sampling_profile_id in SAMPLING_PROFILES, (
            f"Policy '{policy.policy_id}' references unknown sampling "
            f"'{policy.sampling_profile_id}'"
        )


def test_all_policies_reference_valid_template_profile() -> None:
    for policy in PROMPT_POLICIES.values():
        assert policy.template_profile_id in TEMPLATE_PROFILES, (
            f"Policy '{policy.policy_id}' references unknown template "
            f"'{policy.template_profile_id}'"
        )


def test_placeholder_mode_never_absent() -> None:
    """Every built-in policy must have a valid placeholder mode (no OFF)."""
    valid = {
        PlaceholderMode.PROTECT_KNOWN_PLACEHOLDERS,
        PlaceholderMode.STRICT_PROTECT_ALL_TOKENS,
        PlaceholderMode.RESTORE_AFTER_GENERATION,
    }
    for policy in PROMPT_POLICIES.values():
        assert policy.placeholder_mode in valid, (
            f"Policy '{policy.policy_id}' has unexpected placeholder_mode "
            f"'{policy.placeholder_mode}'"
        )


# ============================================================================
# Registry lookup guards
# ============================================================================


def test_get_policy_unknown_raises_key_error() -> None:
    with pytest.raises(KeyError):
        get_policy("nonexistent_policy_xyz")


def test_get_sampling_profile_unknown_raises_key_error() -> None:
    with pytest.raises(KeyError):
        get_sampling_profile("nonexistent_sampling_xyz")


def test_get_template_profile_unknown_raises_key_error() -> None:
    with pytest.raises(KeyError):
        get_template_profile("nonexistent_template_xyz")
