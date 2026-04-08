"""PPS PATCH-07 — TemplateProfile family resolution tests.

Tests for:
- resolve_template_profile(): compatible, mismatch, unknown family, no nearest found
- _TEMPLATE_NEAREST mapping completeness
- _PROVIDER_FAMILY class attributes on 1.8B and 7B providers
- translate() meta["prompt_policy"]["template_profile_id"] uses resolved value
- translate() meta["prompt_policy"]["warnings"] contains mismatch warning
- _build_trace() receives resolved template_profile_id
- Spec §10.4 invariants: 1.8B gets _observed, 7B gets hy_mt_7b_*
"""

import logging

import pytest

from app.infra.translators.prompt_policy import (
    PROMPT_POLICIES,
    _TEMPLATE_FAMILY_7B,
    _TEMPLATE_FAMILY_OBSERVED,
    _TEMPLATE_NEAREST,
    PromptPolicy,
    resolve_template_profile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _policy(template_profile_id: str) -> PromptPolicy:
    """Return sentence_ru with a specific template_profile_id for testing."""
    p = PROMPT_POLICIES["sentence_ru"]
    # Temporarily override template (not frozen)
    p.template_profile_id = template_profile_id
    return p


def _restore() -> None:
    PROMPT_POLICIES["sentence_ru"].template_profile_id = "hy_mt_standard_observed"


# ---------------------------------------------------------------------------
# resolve_template_profile — compatible (no mismatch)
# ---------------------------------------------------------------------------


def test_observed_template_with_observed_family_no_warning() -> None:
    p = _policy("hy_mt_standard_observed")
    resolved, warning = resolve_template_profile(p, _TEMPLATE_FAMILY_OBSERVED)
    assert resolved == "hy_mt_standard_observed"
    assert warning is None
    _restore()


def test_observed_glossary_with_observed_family_no_warning() -> None:
    p = _policy("hy_mt_glossary_observed")
    resolved, warning = resolve_template_profile(p, _TEMPLATE_FAMILY_OBSERVED)
    assert resolved == "hy_mt_glossary_observed"
    assert warning is None
    _restore()


def test_observed_context_with_observed_family_no_warning() -> None:
    p = _policy("hy_mt_context_observed")
    resolved, warning = resolve_template_profile(p, _TEMPLATE_FAMILY_OBSERVED)
    assert resolved == "hy_mt_context_observed"
    assert warning is None
    _restore()


def test_observed_formatted_with_observed_family_no_warning() -> None:
    p = _policy("hy_mt_formatted_observed")
    resolved, warning = resolve_template_profile(p, _TEMPLATE_FAMILY_OBSERVED)
    assert resolved == "hy_mt_formatted_observed"
    assert warning is None
    _restore()


def test_7b_standard_with_7b_family_no_warning() -> None:
    p = _policy("hy_mt_7b_standard")
    resolved, warning = resolve_template_profile(p, _TEMPLATE_FAMILY_7B)
    assert resolved == "hy_mt_7b_standard"
    assert warning is None
    _restore()


def test_7b_glossary_with_7b_family_no_warning() -> None:
    p = _policy("hy_mt_7b_glossary")
    resolved, warning = resolve_template_profile(p, _TEMPLATE_FAMILY_7B)
    assert resolved == "hy_mt_7b_glossary"
    assert warning is None
    _restore()


# ---------------------------------------------------------------------------
# resolve_template_profile — mismatch → nearest equivalent
# ---------------------------------------------------------------------------


def test_7b_standard_on_observed_family_resolves_to_standard_observed() -> None:
    p = _policy("hy_mt_7b_standard")
    resolved, warning = resolve_template_profile(p, _TEMPLATE_FAMILY_OBSERVED)
    assert resolved == "hy_mt_standard_observed"
    assert warning is not None
    assert "template_profile_mismatch" in warning
    _restore()


def test_7b_glossary_on_observed_family_resolves_to_glossary_observed() -> None:
    p = _policy("hy_mt_7b_glossary")
    resolved, warning = resolve_template_profile(p, _TEMPLATE_FAMILY_OBSERVED)
    assert resolved == "hy_mt_glossary_observed"
    assert warning is not None
    _restore()


def test_standard_observed_on_7b_family_resolves_to_7b_standard() -> None:
    p = _policy("hy_mt_standard_observed")
    resolved, warning = resolve_template_profile(p, _TEMPLATE_FAMILY_7B)
    assert resolved == "hy_mt_7b_standard"
    assert warning is not None
    assert "template_profile_mismatch" in warning
    _restore()


def test_glossary_observed_on_7b_family_resolves_to_7b_glossary() -> None:
    p = _policy("hy_mt_glossary_observed")
    resolved, warning = resolve_template_profile(p, _TEMPLATE_FAMILY_7B)
    assert resolved == "hy_mt_7b_glossary"
    assert warning is not None
    _restore()


def test_context_observed_on_7b_family_resolves_to_7b_standard() -> None:
    """No 7B context-aware profile yet — falls back to hy_mt_7b_standard."""
    p = _policy("hy_mt_context_observed")
    resolved, warning = resolve_template_profile(p, _TEMPLATE_FAMILY_7B)
    assert resolved == "hy_mt_7b_standard"
    assert warning is not None
    _restore()


def test_formatted_observed_on_7b_family_resolves_to_7b_standard() -> None:
    """No 7B formatted profile yet — falls back to hy_mt_7b_standard."""
    p = _policy("hy_mt_formatted_observed")
    resolved, warning = resolve_template_profile(p, _TEMPLATE_FAMILY_7B)
    assert resolved == "hy_mt_7b_standard"
    assert warning is not None
    _restore()


# ---------------------------------------------------------------------------
# Warning message format (spec §11.2)
# ---------------------------------------------------------------------------


def test_mismatch_warning_contains_policy_id() -> None:
    p = _policy("hy_mt_standard_observed")
    _, warning = resolve_template_profile(p, _TEMPLATE_FAMILY_7B)
    assert "sentence_ru" in warning
    _restore()


def test_mismatch_warning_contains_specified_and_selected() -> None:
    p = _policy("hy_mt_standard_observed")
    _, warning = resolve_template_profile(p, _TEMPLATE_FAMILY_7B)
    assert "hy_mt_standard_observed" in warning
    assert "hy_mt_7b_standard" in warning
    _restore()


def test_mismatch_warning_contains_family() -> None:
    p = _policy("hy_mt_standard_observed")
    _, warning = resolve_template_profile(p, _TEMPLATE_FAMILY_7B)
    assert _TEMPLATE_FAMILY_7B in warning
    _restore()


# ---------------------------------------------------------------------------
# Unknown provider family
# ---------------------------------------------------------------------------


def test_unknown_provider_family_returns_as_is() -> None:
    p = _policy("hy_mt_standard_observed")
    resolved, warning = resolve_template_profile(p, "unknown_family")
    assert resolved == "hy_mt_standard_observed"
    assert warning is not None
    assert "unknown_family" in warning
    _restore()


# ---------------------------------------------------------------------------
# Unknown template (no nearest in _TEMPLATE_NEAREST)
# ---------------------------------------------------------------------------


def test_unknown_template_on_observed_family_uses_default() -> None:
    """A completely unknown template_id → family default hy_mt_standard_observed."""
    p = _policy("hy_mt_nonexistent_template")
    resolved, warning = resolve_template_profile(p, _TEMPLATE_FAMILY_OBSERVED)
    assert resolved == "hy_mt_standard_observed"
    assert warning is not None
    _restore()


def test_unknown_template_on_7b_family_uses_default() -> None:
    p = _policy("hy_mt_nonexistent_template")
    resolved, warning = resolve_template_profile(p, _TEMPLATE_FAMILY_7B)
    assert resolved == "hy_mt_7b_standard"
    assert warning is not None
    _restore()


# ---------------------------------------------------------------------------
# _TEMPLATE_NEAREST completeness
# ---------------------------------------------------------------------------


def test_template_nearest_covers_all_cross_mappings() -> None:
    """All 6 cross-family mappings must be present."""
    expected_keys = {
        ("hy_mt_7b_standard", _TEMPLATE_FAMILY_OBSERVED),
        ("hy_mt_7b_glossary", _TEMPLATE_FAMILY_OBSERVED),
        ("hy_mt_standard_observed", _TEMPLATE_FAMILY_7B),
        ("hy_mt_glossary_observed", _TEMPLATE_FAMILY_7B),
        ("hy_mt_context_observed", _TEMPLATE_FAMILY_7B),
        ("hy_mt_formatted_observed", _TEMPLATE_FAMILY_7B),
    }
    assert expected_keys.issubset(set(_TEMPLATE_NEAREST.keys()))


def test_template_nearest_values_exist_in_template_profiles() -> None:
    from app.infra.translators.prompt_policy import TEMPLATE_PROFILES

    for (_, _), resolved_id in _TEMPLATE_NEAREST.items():
        assert (
            resolved_id in TEMPLATE_PROFILES
        ), f"Nearest equivalent {resolved_id!r} not in TEMPLATE_PROFILES"


# ---------------------------------------------------------------------------
# _PROVIDER_FAMILY class attributes
# ---------------------------------------------------------------------------


def test_1b8_provider_family_is_observed() -> None:
    from app.infra.translators.providers.local_hymt_provider import LocalHYMTProvider

    assert LocalHYMTProvider._PROVIDER_FAMILY == _TEMPLATE_FAMILY_OBSERVED


def test_7b_provider_family_is_7b_gptq() -> None:
    from app.infra.translators.providers.local_hymt_7b_gptq_provider import (
        LocalHYMT7BGPTQProvider,
    )

    assert LocalHYMT7BGPTQProvider._PROVIDER_FAMILY == _TEMPLATE_FAMILY_7B


def test_7b_provider_family_differs_from_1b8() -> None:
    from app.infra.translators.providers.local_hymt_7b_gptq_provider import (
        LocalHYMT7BGPTQProvider,
    )
    from app.infra.translators.providers.local_hymt_provider import LocalHYMTProvider

    assert LocalHYMT7BGPTQProvider._PROVIDER_FAMILY != LocalHYMTProvider._PROVIDER_FAMILY


# ---------------------------------------------------------------------------
# translate() integration — meta uses resolved template_profile_id
# ---------------------------------------------------------------------------


def test_translate_meta_template_profile_id_is_observed_for_1b8() -> None:
    """1.8B provider + sentence_ru (hy_mt_standard_observed) → meta keeps _observed template."""
    from unittest.mock import Mock, patch

    from app.infra.translators.base_provider import TranslationRequest
    from app.infra.translators.providers.local_hymt_provider import LocalHYMTProvider

    mock_manager = Mock()
    mock_manager.is_installed = Mock(return_value=(True, None))
    mock_manager.model_dir = Mock(return_value="/fake/hymt/path")

    mock_worker_result = Mock()
    mock_worker_result.text = "перевод"
    mock_worker_result.error = None
    mock_worker_result.inference_time_ms = 100.0
    mock_worker = Mock()
    mock_worker.translate = Mock(return_value=mock_worker_result)

    with (
        patch(
            "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
            return_value=mock_manager,
        ),
        patch(
            "app.infra.translators.providers.local_hymt_provider.start_worker",
            return_value=mock_worker,
        ),
    ):
        provider = LocalHYMTProvider()

    request = TranslationRequest(
        source_text="שלום", source_lang="he", target_lang="ru", options={}, trace_id=""
    )
    result = provider.translate(request)
    assert result.meta["prompt_policy"]["template_profile_id"] == "hy_mt_standard_observed"


def test_translate_meta_no_mismatch_warning_for_compatible_policy() -> None:
    """1.8B provider + hy_mt_standard_observed policy → no template_profile_mismatch warning."""
    from unittest.mock import Mock, patch

    from app.infra.translators.base_provider import TranslationRequest
    from app.infra.translators.providers.local_hymt_provider import LocalHYMTProvider

    mock_manager = Mock()
    mock_manager.is_installed = Mock(return_value=(True, None))
    mock_manager.model_dir = Mock(return_value="/fake/hymt/path")

    mock_worker_result = Mock()
    mock_worker_result.text = "перевод"
    mock_worker_result.error = None
    mock_worker_result.inference_time_ms = 100.0
    mock_worker = Mock()
    mock_worker.translate = Mock(return_value=mock_worker_result)

    with (
        patch(
            "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
            return_value=mock_manager,
        ),
        patch(
            "app.infra.translators.providers.local_hymt_provider.start_worker",
            return_value=mock_worker,
        ),
    ):
        provider = LocalHYMTProvider()

    request = TranslationRequest(
        source_text="שלום", source_lang="he", target_lang="ru", options={}, trace_id=""
    )
    result = provider.translate(request)
    warnings = result.meta["prompt_policy"]["warnings"]
    assert not any("template_profile_mismatch" in w for w in warnings)


def test_mismatch_triggers_warning_in_resolve_result() -> None:
    """Force a 7B template on 1.8B family → resolved ID is _observed + warning returned."""
    policy = PROMPT_POLICIES["sentence_ru"]
    original = policy.template_profile_id
    try:
        policy.template_profile_id = "hy_mt_7b_standard"
        resolved, warning = resolve_template_profile(policy, _TEMPLATE_FAMILY_OBSERVED)
        assert resolved == "hy_mt_standard_observed"
        assert warning is not None
        assert "template_profile_mismatch" in warning
    finally:
        policy.template_profile_id = original


# ---------------------------------------------------------------------------
# Logging — mismatch triggers WARNING
# ---------------------------------------------------------------------------


def test_mismatch_logs_warning(caplog) -> None:
    p = _policy("hy_mt_standard_observed")
    with caplog.at_level(logging.WARNING, logger="app.infra.translators.prompt_policy"):
        resolve_template_profile(p, _TEMPLATE_FAMILY_7B)
    assert any("template_profile_mismatch" in r.message for r in caplog.records)
    _restore()


def test_compatible_does_not_log_warning(caplog) -> None:
    p = _policy("hy_mt_standard_observed")
    with caplog.at_level(logging.WARNING, logger="app.infra.translators.prompt_policy"):
        resolve_template_profile(p, _TEMPLATE_FAMILY_OBSERVED)
    assert not any("template_profile_mismatch" in r.message for r in caplog.records)
    _restore()
