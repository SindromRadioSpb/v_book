"""Tests for PATCH-03: TranslationRouter + LocalHYMTProvider PPS integration.

Verifies:
- TranslationRouter resolution order: explicit → content_kind → fallback
- Experimental guard at router level
- LocalHYMTProvider.translate() returns meta["prompt_policy"] on success
- meta["prompt_policy"] required fields present and consistent
- terminology_mode=off yields injected_term_count=0, applied_term_count=0
- Backwards compatible: no options → sentence_ru (default path, fallback_triggered=False)
- Top-level meta fields preserved for backwards compat

No torch import. All provider tests use mocked worker + model manager.
"""

from unittest.mock import Mock, MagicMock, patch

import pytest

from app.infra.translators.base_provider import TranslationRequest, TranslationResult
from app.infra.translators.prompt_policy import (
    DEFAULT_POLICY_ID,
    ContentKind,
    RouterResult,
    TerminologyMode,
    TranslationRouter,
    get_policy,
)
from app.infra.translators.providers.local_hymt_provider import LocalHYMTProvider


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_model_manager():
    manager = Mock()
    manager.is_installed = Mock(return_value=(True, None))
    manager.model_dir = Mock(return_value="/fake/hymt/path")
    return manager


@pytest.fixture
def mock_worker():
    worker = Mock()
    worker.ping = Mock(return_value=True)
    worker.shutdown = Mock()
    worker_result = Mock()
    worker_result.text = "перевод"
    worker_result.error = None
    worker_result.inference_time_ms = 100.0
    worker.translate = Mock(return_value=worker_result)
    return worker


@pytest.fixture
def provider(mock_model_manager, mock_worker):
    with patch(
        "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        with patch(
            "app.infra.translators.providers.local_hymt_provider.start_worker",
            return_value=mock_worker,
        ):
            return LocalHYMTProvider()


def _make_request(
    source_text: str = "שלום",
    source_lang: str = "he",
    target_lang: str = "ru",
    options: dict | None = None,
    trace_id: str = "",
) -> TranslationRequest:
    return TranslationRequest(
        source_text=source_text,
        source_lang=source_lang,
        target_lang=target_lang,
        options=options or {},
        trace_id=trace_id,
    )


# ============================================================================
# TranslationRouter — unit tests (no torch, no worker)
# ============================================================================


_ROUTER = TranslationRouter()


def test_router_no_options_returns_default_policy() -> None:
    result = _ROUTER.route({})
    assert result.policy.policy_id == DEFAULT_POLICY_ID


def test_router_no_options_source_is_fallback() -> None:
    result = _ROUTER.route({})
    assert result.source == "fallback"


def test_router_no_options_fallback_triggered_false() -> None:
    """Global default is not an error — fallback_triggered must be False."""
    result = _ROUTER.route({})
    assert result.fallback_triggered is False


def test_router_explicit_policy_id_resolves() -> None:
    result = _ROUTER.route({"prompt_policy_id": "lemma_ru"})
    assert result.policy.policy_id == "lemma_ru"
    assert result.source == "explicit"
    assert result.fallback_triggered is False


def test_router_explicit_overrides_content_kind() -> None:
    """When both keys present, explicit prompt_policy_id wins."""
    result = _ROUTER.route({"prompt_policy_id": "lemma_ru", "content_kind": "sentence"})
    assert result.policy.policy_id == "lemma_ru"
    assert result.source == "explicit"


def test_router_content_kind_lemma() -> None:
    result = _ROUTER.route({"content_kind": "lemma"})
    assert result.policy.policy_id == "lemma_ru"
    assert result.source == "content_kind"


def test_router_content_kind_term() -> None:
    result = _ROUTER.route({"content_kind": "term"})
    assert result.policy.policy_id == "term_ru"
    assert result.source == "content_kind"


def test_router_content_kind_sentence() -> None:
    result = _ROUTER.route({"content_kind": "sentence"})
    assert result.policy.policy_id == "sentence_ru"
    assert result.source == "content_kind"


def test_router_content_kind_sentence_formatted() -> None:
    result = _ROUTER.route({"content_kind": "sentence_formatted"})
    assert result.policy.policy_id == "sentence_ru_formatted"
    assert result.source == "content_kind"


def test_router_content_kind_ui_string() -> None:
    """ui_string maps to lemma_ru (short greedy output)."""
    result = _ROUTER.route({"content_kind": "ui_string"})
    assert result.policy.policy_id == "lemma_ru"


def test_router_content_kind_batch_mixed() -> None:
    result = _ROUTER.route({"content_kind": "batch_mixed"})
    assert result.policy.policy_id == "sentence_ru"


def test_router_unknown_policy_id_falls_back() -> None:
    result = _ROUTER.route({"prompt_policy_id": "nonexistent_xyz"})
    assert result.policy.policy_id == DEFAULT_POLICY_ID
    assert result.fallback_triggered is True
    assert result.fallback_reason is not None
    assert "nonexistent_xyz" in result.fallback_reason


def test_router_unknown_policy_id_adds_warning() -> None:
    result = _ROUTER.route({"prompt_policy_id": "nonexistent_xyz"})
    assert any("nonexistent_xyz" in w for w in result.warnings)


def test_router_unknown_content_kind_falls_back() -> None:
    result = _ROUTER.route({"content_kind": "invalid_kind_xyz"})
    assert result.policy.policy_id == DEFAULT_POLICY_ID


def test_router_experimental_blocked_by_default() -> None:
    """sentence_ru_context is experimental; blocked when allow_experimental=False."""
    result = _ROUTER.route(
        {"prompt_policy_id": "sentence_ru_context"},
        allow_experimental=False,
    )
    assert result.policy.policy_id == DEFAULT_POLICY_ID
    assert result.fallback_triggered is True
    assert result.fallback_reason is not None
    assert (
        "experimental" in result.fallback_reason.lower()
        or "sentence_ru_context" in result.fallback_reason
    )


def test_router_experimental_allowed_with_flag() -> None:
    result = _ROUTER.route(
        {"prompt_policy_id": "sentence_ru_context"},
        allow_experimental=True,
    )
    assert result.policy.policy_id == "sentence_ru_context"
    assert result.fallback_triggered is False


def test_router_experimental_content_kind_also_blocked() -> None:
    """sentence_ru_context reachable via content_kind; guard still fires."""
    result = _ROUTER.route({"content_kind": "sentence_with_context"}, allow_experimental=False)
    assert result.policy.policy_id == DEFAULT_POLICY_ID
    assert result.fallback_triggered is True


def test_router_result_is_router_result_instance() -> None:
    result = _ROUTER.route({})
    assert isinstance(result, RouterResult)


def test_router_warnings_empty_for_clean_resolution() -> None:
    result = _ROUTER.route({"prompt_policy_id": "lemma_ru"})
    assert result.warnings == []


def test_router_all_non_experimental_policies_resolve_cleanly() -> None:
    """All 5 non-experimental policies must resolve without fallback."""
    non_experimental_ids = [
        "sentence_ru",
        "sentence_ru_formatted",
        "lemma_ru",
        "term_ru",
        "term_ru_strict_glossary",
    ]
    for pid in non_experimental_ids:
        result = _ROUTER.route({"prompt_policy_id": pid})
        assert result.policy.policy_id == pid, f"policy {pid} did not resolve"
        assert not result.fallback_triggered, f"unexpected fallback for {pid}"


# ============================================================================
# LocalHYMTProvider — translate() meta integration tests
# ============================================================================


def test_translate_success_result_has_prompt_policy_key(provider) -> None:
    result = provider.translate(_make_request())
    assert result.translated_text is not None
    assert "prompt_policy" in result.meta


def test_translate_prompt_policy_has_all_required_fields(provider) -> None:
    result = provider.translate(_make_request())
    pp = result.meta["prompt_policy"]
    required = {
        "policy_id",
        "policy_hash",
        "sampling_profile_id",
        "template_profile_id",
        "content_kind",
        "terminology_mode",
        "injected_term_count",
        "applied_term_count",
        "placeholder_count",
        "missing_placeholders",
        "fallback_triggered",
        "fallback_reason",
        "warnings",
        "trace",
    }
    assert required.issubset(pp.keys()), f"missing fields: {required - pp.keys()}"


def test_translate_default_path_policy_id_is_sentence_ru(provider) -> None:
    """No options → sentence_ru is the default."""
    result = provider.translate(_make_request())
    assert result.meta["prompt_policy"]["policy_id"] == "sentence_ru"


def test_translate_explicit_policy_id_honoured(provider) -> None:
    result = provider.translate(_make_request(options={"prompt_policy_id": "lemma_ru"}))
    assert result.meta["prompt_policy"]["policy_id"] == "lemma_ru"


def test_translate_content_kind_routing(provider) -> None:
    result = provider.translate(_make_request(options={"content_kind": "term"}))
    assert result.meta["prompt_policy"]["policy_id"] == "term_ru"


def test_translate_fallback_triggered_false_for_default(provider) -> None:
    """Normal default path must not set fallback_triggered."""
    result = provider.translate(_make_request())
    assert result.meta["prompt_policy"]["fallback_triggered"] is False


def test_translate_fallback_triggered_true_for_unknown_policy(provider) -> None:
    result = provider.translate(_make_request(options={"prompt_policy_id": "nonexistent_xyz"}))
    assert result.meta["prompt_policy"]["fallback_triggered"] is True
    assert result.meta["prompt_policy"]["fallback_reason"] is not None


def test_translate_top_level_meta_fields_preserved(provider) -> None:
    """Backwards compat: existing top-level meta fields must still be present."""
    result = provider.translate(_make_request())
    for key in (
        "applied_terms_count",
        "placeholder_count",
        "missing_placeholders",
        "model_id",
        "backend",
    ):
        assert key in result.meta, f"top-level meta key '{key}' missing"


def test_translate_placeholder_count_consistent(provider) -> None:
    """meta['placeholder_count'] == meta['prompt_policy']['placeholder_count']."""
    result = provider.translate(_make_request(source_text="שלום"))
    assert result.meta["placeholder_count"] == result.meta["prompt_policy"]["placeholder_count"]


def test_translate_applied_terms_count_consistent(provider) -> None:
    """meta['applied_terms_count'] == meta['prompt_policy']['applied_term_count']."""
    result = provider.translate(_make_request())
    assert result.meta["applied_terms_count"] == result.meta["prompt_policy"]["applied_term_count"]


def test_translate_terminology_mode_off_zero_injected(provider) -> None:
    """lemma_ru has terminology_mode=OFF: injected_term_count must be 0."""
    result = provider.translate(_make_request(options={"prompt_policy_id": "lemma_ru"}))
    assert result.meta["prompt_policy"]["injected_term_count"] == 0


def test_translate_terminology_mode_off_zero_applied(provider) -> None:
    """lemma_ru has terminology_mode=OFF: applied_term_count must be 0."""
    result = provider.translate(_make_request(options={"prompt_policy_id": "lemma_ru"}))
    assert result.meta["prompt_policy"]["applied_term_count"] == 0


def test_translate_trace_field_is_none(provider) -> None:
    """trace must be None (PATCH-05 scope)."""
    result = provider.translate(_make_request())
    assert result.meta["prompt_policy"]["trace"] is None


def test_translate_policy_hash_is_none(provider) -> None:
    """policy_hash must be None (PATCH-06 scope)."""
    result = provider.translate(_make_request())
    assert result.meta["prompt_policy"]["policy_hash"] is None


def test_translate_sampling_profile_id_matches_policy(provider) -> None:
    result = provider.translate(_make_request())
    policy = get_policy("sentence_ru")
    assert result.meta["prompt_policy"]["sampling_profile_id"] == policy.sampling_profile_id


def test_translate_template_profile_id_matches_policy(provider) -> None:
    result = provider.translate(_make_request())
    policy = get_policy("sentence_ru")
    assert result.meta["prompt_policy"]["template_profile_id"] == policy.template_profile_id


def test_translate_experimental_blocked_without_trace_id(provider) -> None:
    """sentence_ru_context is experimental — blocked when no trace_id."""
    result = provider.translate(
        _make_request(options={"prompt_policy_id": "sentence_ru_context"}, trace_id="")
    )
    # Must fall back to sentence_ru
    assert result.meta["prompt_policy"]["policy_id"] == "sentence_ru"
    assert result.meta["prompt_policy"]["fallback_triggered"] is True


def test_translate_experimental_allowed_with_trace_id(provider) -> None:
    """sentence_ru_context is experimental — allowed when trace_id set."""
    result = provider.translate(
        _make_request(options={"prompt_policy_id": "sentence_ru_context"}, trace_id="seg-001")
    )
    assert result.meta["prompt_policy"]["policy_id"] == "sentence_ru_context"
    assert result.meta["prompt_policy"]["fallback_triggered"] is False


def test_translate_missing_placeholders_consistent(provider) -> None:
    """missing_placeholders must match between top-level and prompt_policy."""
    result = provider.translate(_make_request(source_text="שלום"))
    assert (
        result.meta["missing_placeholders"] == result.meta["prompt_policy"]["missing_placeholders"]
    )


def test_translate_warnings_is_list(provider) -> None:
    result = provider.translate(_make_request())
    assert isinstance(result.meta["prompt_policy"]["warnings"], list)


def test_translate_content_kind_str_in_meta(provider) -> None:
    result = provider.translate(_make_request())
    ck = result.meta["prompt_policy"]["content_kind"]
    assert isinstance(ck, str)
    assert ck == str(ContentKind.SENTENCE)


def test_translate_terminology_mode_str_in_meta(provider) -> None:
    result = provider.translate(_make_request())
    tm = result.meta["prompt_policy"]["terminology_mode"]
    assert isinstance(tm, str)
    assert tm == str(TerminologyMode.SOFT_GLOSSARY)


# ============================================================================
# 7B provider inherits all changes
# ============================================================================


def test_7b_provider_inherits_prompt_policy_meta(mock_model_manager, mock_worker) -> None:
    """LocalHYMT7BGPTQProvider must inherit meta['prompt_policy'] from parent."""
    from app.infra.translators.providers.local_hymt_7b_gptq_provider import (
        LocalHYMT7BGPTQProvider,
    )

    with patch(
        "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        with patch(
            "app.infra.translators.providers.local_hymt_provider.start_worker",
            return_value=mock_worker,
        ):
            p7b = LocalHYMT7BGPTQProvider()

    result = p7b.translate(_make_request())
    assert "prompt_policy" in result.meta
    assert result.meta["prompt_policy"]["policy_id"] == "sentence_ru"


def test_7b_provider_id_in_result(mock_model_manager, mock_worker) -> None:
    from app.infra.translators.providers.local_hymt_7b_gptq_provider import (
        LocalHYMT7BGPTQProvider,
    )

    with patch(
        "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        with patch(
            "app.infra.translators.providers.local_hymt_provider.start_worker",
            return_value=mock_worker,
        ):
            p7b = LocalHYMT7BGPTQProvider()

    result = p7b.translate(_make_request())
    assert result.provider_id == "local_hymt_7b_gptq"
