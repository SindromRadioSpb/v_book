"""Tests for PPS PATCH-05: EffectivePromptTrace + Debug UI.

Verifies:
- EffectivePromptTrace dataclass shape (all required fields per spec §4.9)
- build_applied_sampling() for 1.8B / 7B / greedy-intent / cap paths
- Trace is None when trace_id="" (production default)
- Trace is populated when trace_id is set
- meta["prompt_policy"]["trace"] wiring is correct
- Rendered semantic layers match policy and glossary inputs
- applied_sampling reflects effective resolved runtime values
- placeholder_tokens_restored ≤ len(placeholder_tokens_protected)
- fallback flags propagate into trace
- latency and worker_latency are ints
- PromptAuditPanel history cap = 100, FIFO eviction, add/clear
- Colour-coded HTML rendering is testable without heavy UI runtime
- PATCH-03 and PATCH-04 regression tests remain green

No torch import. All provider tests use mocked worker + model manager.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from app.infra.translators.base_provider import TranslationRequest, TranslationResult
from app.infra.translators.prompt_policy import (
    ContentKind,
    EffectivePromptTrace,
    PromptPolicy,
    TerminologyMode,
    TranslationRouter,
    build_applied_sampling,
    get_policy,
    get_sampling_profile,
)
from app.infra.translators.providers.local_hymt_provider import LocalHYMTProvider


# ============================================================================
# Helpers
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
    result = Mock()
    result.text = "перевод"
    result.error = None
    result.inference_time_ms = 88.5
    worker.translate = Mock(return_value=result)
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


def _req(
    source_text: str = "שלום",
    trace_id: str = "",
    options: dict | None = None,
) -> TranslationRequest:
    return TranslationRequest(
        source_text=source_text,
        source_lang="he",
        target_lang="ru",
        options=options or {},
        trace_id=trace_id,
    )


# ============================================================================
# EffectivePromptTrace — dataclass shape
# ============================================================================


def test_trace_dataclass_exists() -> None:
    assert EffectivePromptTrace is not None


def test_trace_is_dataclass() -> None:
    assert dataclasses.is_dataclass(EffectivePromptTrace)


def test_trace_has_all_required_fields() -> None:
    required = {
        "trace_id",
        "policy_id",
        "policy_version",
        "policy_hash",
        "template_profile_id",
        "sampling_profile_id",
        "content_kind",
        "source_lang",
        "target_lang",
        "model_id",
        "model_quant_id",
        "provider_id",
        "source_text",
        "source_text_hash",
        "source_length_chars",
        "rendered_role_instruction",
        "rendered_task_instruction",
        "rendered_output_policy",
        "rendered_glossary_block",
        "rendered_context_block",
        "rendered_formatting_note",
        "rendered_user_payload",
        "effective_prompt_preview",
        "glossary_hash",
        "context_hash",
        "applied_sampling",
        "placeholder_tokens_protected",
        "placeholder_tokens_restored",
        "raw_model_output",
        "translated_text",
        "output_length_chars",
        "output_tokens_generated",
        "latency_ms",
        "worker_latency_ms",
        "glossary_applied",
        "context_applied",
        "fallback_triggered",
        "fallback_reason",
        "created_at",
    }
    actual = {f.name for f in dataclasses.fields(EffectivePromptTrace)}
    assert required.issubset(actual), f"missing fields: {required - actual}"


def test_trace_nullable_patch06_fields_accepted() -> None:
    """Fields deferred to PATCH-06 must accept None."""
    policy = get_policy("sentence_ru")
    t = EffectivePromptTrace(
        trace_id="test-001",
        policy_id=policy.policy_id,
        policy_version=policy.version,
        policy_hash=None,
        template_profile_id=policy.template_profile_id,
        sampling_profile_id=policy.sampling_profile_id,
        content_kind=policy.content_kind,
        source_lang="he",
        target_lang="ru",
        model_id="tencent/HY-MT1.5-1.8B",
        model_quant_id=None,
        provider_id="local_hymt",
        source_text="שלום",
        source_text_hash=None,
        source_length_chars=4,
        rendered_role_instruction="",
        rendered_task_instruction=policy.task_instruction,
        rendered_output_policy="",
        rendered_glossary_block=None,
        rendered_context_block=None,
        rendered_formatting_note=None,
        rendered_user_payload="שלום",
        effective_prompt_preview="[Role]\n\n[User]\nשלום",
        glossary_hash=None,
        context_hash=None,
        applied_sampling={"max_new_tokens": 512, "do_sample": True},
        placeholder_tokens_protected=[],
        placeholder_tokens_restored=0,
        raw_model_output="привет",
        translated_text="привет",
        output_length_chars=6,
        output_tokens_generated=None,
        latency_ms=150,
        worker_latency_ms=88,
        glossary_applied=False,
        context_applied=False,
        fallback_triggered=False,
        fallback_reason=None,
    )
    assert t.policy_hash is None
    assert t.source_text_hash is None
    assert t.glossary_hash is None
    assert t.context_hash is None
    assert t.output_tokens_generated is None
    assert t.model_quant_id is None


# ============================================================================
# build_applied_sampling
# ============================================================================


def test_build_applied_sampling_1b8_sentence_do_sample_true() -> None:
    policy = get_policy("sentence_ru")
    result = build_applied_sampling(policy, force_greedy=False, max_n_predict_cap=512)
    assert result["do_sample"] is True


def test_build_applied_sampling_1b8_sentence_max_new_tokens() -> None:
    policy = get_policy("sentence_ru")
    result = build_applied_sampling(policy, force_greedy=False, max_n_predict_cap=512)
    assert result["max_new_tokens"] == 512


def test_build_applied_sampling_1b8_sentence_temperature() -> None:
    policy = get_policy("sentence_ru")
    sp = get_sampling_profile(policy.sampling_profile_id)
    result = build_applied_sampling(policy, force_greedy=False, max_n_predict_cap=512)
    assert result["temperature"] == pytest.approx(sp.temperature)


def test_build_applied_sampling_1b8_sentence_top_k() -> None:
    policy = get_policy("sentence_ru")
    sp = get_sampling_profile(policy.sampling_profile_id)
    result = build_applied_sampling(policy, force_greedy=False, max_n_predict_cap=512)
    assert result["top_k"] == sp.top_k


def test_build_applied_sampling_1b8_sentence_top_p() -> None:
    policy = get_policy("sentence_ru")
    sp = get_sampling_profile(policy.sampling_profile_id)
    result = build_applied_sampling(policy, force_greedy=False, max_n_predict_cap=512)
    assert result["top_p"] == pytest.approx(sp.top_p)


def test_build_applied_sampling_1b8_sentence_repetition_penalty() -> None:
    policy = get_policy("sentence_ru")
    sp = get_sampling_profile(policy.sampling_profile_id)
    result = build_applied_sampling(policy, force_greedy=False, max_n_predict_cap=512)
    assert result["repetition_penalty"] == pytest.approx(sp.repetition_penalty)


def test_build_applied_sampling_no_eos_token_id() -> None:
    """eos_token_id is worker-owned and must NOT appear in build_applied_sampling."""
    policy = get_policy("sentence_ru")
    result = build_applied_sampling(policy, force_greedy=False, max_n_predict_cap=512)
    assert "eos_token_id" not in result


def test_build_applied_sampling_gptq_force_greedy() -> None:
    policy = get_policy("sentence_ru")
    result = build_applied_sampling(policy, force_greedy=True, max_n_predict_cap=128)
    assert result["do_sample"] is False


def test_build_applied_sampling_gptq_cap_applied() -> None:
    policy = get_policy("sentence_ru")
    result = build_applied_sampling(policy, force_greedy=True, max_n_predict_cap=128)
    assert result["max_new_tokens"] == 128


def test_build_applied_sampling_gptq_no_sampling_keys() -> None:
    policy = get_policy("sentence_ru")
    result = build_applied_sampling(policy, force_greedy=True, max_n_predict_cap=128)
    for key in ("top_k", "top_p", "temperature", "repetition_penalty"):
        assert key not in result, f"unexpected key {key!r} in greedy result"


def test_build_applied_sampling_lemma_greedy_by_intent() -> None:
    """lemma_ru uses hy_mt_precise_short (temperature=0.0) — greedy by intent."""
    policy = get_policy("lemma_ru")
    result = build_applied_sampling(policy, force_greedy=False, max_n_predict_cap=512)
    assert result["do_sample"] is False


def test_build_applied_sampling_lemma_n_predict() -> None:
    policy = get_policy("lemma_ru")
    sp = get_sampling_profile(policy.sampling_profile_id)
    result = build_applied_sampling(policy, force_greedy=False, max_n_predict_cap=512)
    assert result["max_new_tokens"] == sp.n_predict


def test_build_applied_sampling_cap_none_no_effect() -> None:
    policy = get_policy("sentence_ru")
    sp = get_sampling_profile(policy.sampling_profile_id)
    result = build_applied_sampling(policy, force_greedy=False, max_n_predict_cap=None)
    assert result["max_new_tokens"] == sp.n_predict


def test_build_applied_sampling_small_cap_overrides() -> None:
    policy = get_policy("sentence_ru")
    result = build_applied_sampling(policy, force_greedy=False, max_n_predict_cap=64)
    assert result["max_new_tokens"] == 64


# ============================================================================
# Provider trace — None when no trace_id
# ============================================================================


def test_trace_none_when_no_trace_id(provider) -> None:
    result = provider.translate(_req(trace_id=""))
    assert result.meta["prompt_policy"]["trace"] is None


def test_trace_none_for_default_request(provider) -> None:
    result = provider.translate(_req())
    assert result.meta["prompt_policy"]["trace"] is None


# ============================================================================
# Provider trace — populated when trace_id is set
# ============================================================================


def test_trace_not_none_when_trace_id_set(provider) -> None:
    result = provider.translate(_req(trace_id="seg-001"))
    assert result.meta["prompt_policy"]["trace"] is not None


def test_trace_is_effective_prompt_trace_instance(provider) -> None:
    result = provider.translate(_req(trace_id="seg-001"))
    assert isinstance(result.meta["prompt_policy"]["trace"], EffectivePromptTrace)


def test_trace_wired_in_meta_prompt_policy(provider) -> None:
    result = provider.translate(_req(trace_id="seg-001"))
    assert "trace" in result.meta["prompt_policy"]


def test_trace_policy_id_matches(provider) -> None:
    result = provider.translate(_req(trace_id="seg-001"))
    trace = result.meta["prompt_policy"]["trace"]
    assert trace.policy_id == result.meta["prompt_policy"]["policy_id"]


def test_trace_trace_id_matches_request(provider) -> None:
    result = provider.translate(_req(trace_id="seg-abc-123"))
    assert result.meta["prompt_policy"]["trace"].trace_id == "seg-abc-123"


def test_trace_source_text_present(provider) -> None:
    result = provider.translate(_req(source_text="שלום", trace_id="t1"))
    assert result.meta["prompt_policy"]["trace"].source_text == "שלום"


def test_trace_source_length_chars(provider) -> None:
    text = "שלום"
    result = provider.translate(_req(source_text=text, trace_id="t1"))
    assert result.meta["prompt_policy"]["trace"].source_length_chars == len(text)


def test_trace_rendered_task_instruction_nonempty(provider) -> None:
    result = provider.translate(_req(trace_id="t1"))
    trace = result.meta["prompt_policy"]["trace"]
    assert isinstance(trace.rendered_task_instruction, str)
    assert len(trace.rendered_task_instruction) > 0


def test_trace_rendered_role_instruction_is_str(provider) -> None:
    result = provider.translate(_req(trace_id="t1"))
    trace = result.meta["prompt_policy"]["trace"]
    assert isinstance(trace.rendered_role_instruction, str)


def test_trace_rendered_glossary_block_none_without_db(provider) -> None:
    """No db_session → no glossary fetch → rendered_glossary_block is None."""
    result = provider.translate(_req(trace_id="t1"))
    assert result.meta["prompt_policy"]["trace"].rendered_glossary_block is None


def test_trace_rendered_context_block_none_patch05(provider) -> None:
    """Context not wired until PATCH-07 — must be None."""
    result = provider.translate(_req(trace_id="t1"))
    assert result.meta["prompt_policy"]["trace"].rendered_context_block is None


def test_trace_effective_prompt_preview_nonempty(provider) -> None:
    result = provider.translate(_req(trace_id="t1"))
    assert len(result.meta["prompt_policy"]["trace"].effective_prompt_preview) > 0


def test_trace_applied_sampling_has_max_new_tokens(provider) -> None:
    result = provider.translate(_req(trace_id="t1"))
    trace = result.meta["prompt_policy"]["trace"]
    assert "max_new_tokens" in trace.applied_sampling


def test_trace_applied_sampling_no_eos_token_id(provider) -> None:
    result = provider.translate(_req(trace_id="t1"))
    trace = result.meta["prompt_policy"]["trace"]
    assert "eos_token_id" not in trace.applied_sampling


def test_trace_applied_sampling_1b8_do_sample_true(provider) -> None:
    """Default sentence_ru on 1.8B → do_sample=True."""
    result = provider.translate(_req(trace_id="t1"))
    assert result.meta["prompt_policy"]["trace"].applied_sampling["do_sample"] is True


def test_trace_placeholder_tokens_protected_is_list(provider) -> None:
    result = provider.translate(_req(trace_id="t1"))
    assert isinstance(result.meta["prompt_policy"]["trace"].placeholder_tokens_protected, list)


def test_trace_placeholder_tokens_restored_lte_protected(provider) -> None:
    result = provider.translate(_req(trace_id="t1"))
    trace = result.meta["prompt_policy"]["trace"]
    assert trace.placeholder_tokens_restored <= len(trace.placeholder_tokens_protected)


def test_trace_raw_model_output_is_worker_text(provider, mock_worker) -> None:
    result = provider.translate(_req(trace_id="t1"))
    trace = result.meta["prompt_policy"]["trace"]
    assert trace.raw_model_output == mock_worker.translate.return_value.text


def test_trace_translated_text_is_final(provider) -> None:
    result = provider.translate(_req(trace_id="t1"))
    trace = result.meta["prompt_policy"]["trace"]
    assert trace.translated_text == result.translated_text


def test_trace_output_length_chars(provider) -> None:
    result = provider.translate(_req(trace_id="t1"))
    trace = result.meta["prompt_policy"]["trace"]
    assert trace.output_length_chars == len(result.translated_text)


def test_trace_latency_ms_is_int(provider) -> None:
    result = provider.translate(_req(trace_id="t1"))
    assert isinstance(result.meta["prompt_policy"]["trace"].latency_ms, int)


def test_trace_worker_latency_ms_is_int(provider) -> None:
    result = provider.translate(_req(trace_id="t1"))
    assert isinstance(result.meta["prompt_policy"]["trace"].worker_latency_ms, int)


def test_trace_fallback_triggered_false_for_default(provider) -> None:
    result = provider.translate(_req(trace_id="t1"))
    trace = result.meta["prompt_policy"]["trace"]
    assert trace.fallback_triggered is False


def test_trace_fallback_triggered_true_for_unknown_policy(provider) -> None:
    result = provider.translate(
        _req(trace_id="t1", options={"prompt_policy_id": "nonexistent_xyz"})
    )
    trace = result.meta["prompt_policy"]["trace"]
    assert trace.fallback_triggered is True
    assert trace.fallback_reason is not None


def test_trace_policy_hash_populated_patch06(provider) -> None:
    """PATCH-06: policy_hash is now populated from compute_policy_hash()."""
    result = provider.translate(_req(trace_id="t1"))
    trace = result.meta["prompt_policy"]["trace"]
    assert trace.policy_hash is not None
    assert len(trace.policy_hash) == 64


def test_trace_source_text_hash_populated_patch06(provider) -> None:
    """PATCH-06: source_text_hash is now populated from compute_source_text_hash()."""
    result = provider.translate(_req(trace_id="t1"))
    trace = result.meta["prompt_policy"]["trace"]
    assert trace.source_text_hash is not None
    assert len(trace.source_text_hash) == 64


def test_trace_glossary_hash_none_patch05(provider) -> None:
    result = provider.translate(_req(trace_id="t1"))
    assert result.meta["prompt_policy"]["trace"].glossary_hash is None


def test_trace_context_hash_none_patch05(provider) -> None:
    result = provider.translate(_req(trace_id="t1"))
    assert result.meta["prompt_policy"]["trace"].context_hash is None


def test_trace_output_tokens_generated_none_patch05(provider) -> None:
    result = provider.translate(_req(trace_id="t1"))
    assert result.meta["prompt_policy"]["trace"].output_tokens_generated is None


def test_trace_created_at_is_datetime(provider) -> None:
    result = provider.translate(_req(trace_id="t1"))
    assert isinstance(result.meta["prompt_policy"]["trace"].created_at, datetime)


def test_trace_provider_id_present(provider) -> None:
    result = provider.translate(_req(trace_id="t1"))
    assert result.meta["prompt_policy"]["trace"].provider_id == "local_hymt"


def test_trace_sampling_profile_id_matches_policy(provider) -> None:
    policy = get_policy("sentence_ru")
    result = provider.translate(_req(trace_id="t1"))
    assert result.meta["prompt_policy"]["trace"].sampling_profile_id == policy.sampling_profile_id


# ============================================================================
# 7B provider — hardware constraint overrides
# ============================================================================


def test_7b_force_greedy_attribute() -> None:
    from app.infra.translators.providers.local_hymt_7b_gptq_provider import (
        LocalHYMT7BGPTQProvider,
    )

    assert LocalHYMT7BGPTQProvider._FORCE_GREEDY is True


def test_7b_max_n_predict_cap_attribute() -> None:
    from app.infra.translators.providers.local_hymt_7b_gptq_provider import (
        LocalHYMT7BGPTQProvider,
    )

    assert LocalHYMT7BGPTQProvider._MAX_N_PREDICT_CAP == 128


def test_7b_model_quant_id_attribute() -> None:
    from app.infra.translators.providers.local_hymt_7b_gptq_provider import (
        LocalHYMT7BGPTQProvider,
    )

    assert LocalHYMT7BGPTQProvider._MODEL_QUANT_ID == "gptq-int4"


def test_7b_trace_applied_sampling_greedy(mock_model_manager, mock_worker) -> None:
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

    result = p7b.translate(_req(trace_id="seg-7b-01"))
    trace = result.meta["prompt_policy"]["trace"]
    assert trace is not None
    assert trace.applied_sampling["do_sample"] is False
    assert trace.applied_sampling["max_new_tokens"] == 128


def test_7b_trace_model_quant_id(mock_model_manager, mock_worker) -> None:
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

    result = p7b.translate(_req(trace_id="seg-7b-01"))
    assert result.meta["prompt_policy"]["trace"].model_quant_id == "gptq-int4"


# ============================================================================
# PromptAuditPanel — history cap + FIFO + API
# ============================================================================


@pytest.fixture(autouse=True)
def clear_audit_history():
    """Ensure PromptAuditPanel history is empty before each test."""
    from app.ui.prompt_audit_dialog import PromptAuditPanel

    PromptAuditPanel.clear_history()
    yield
    PromptAuditPanel.clear_history()


def _fake_trace(trace_id: str = "t") -> EffectivePromptTrace:
    """Build a minimal EffectivePromptTrace for history tests."""
    policy = get_policy("sentence_ru")
    return EffectivePromptTrace(
        trace_id=trace_id,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        policy_hash=None,
        template_profile_id=policy.template_profile_id,
        sampling_profile_id=policy.sampling_profile_id,
        content_kind=policy.content_kind,
        source_lang="he",
        target_lang="ru",
        model_id="tencent/HY-MT1.5-1.8B",
        model_quant_id=None,
        provider_id="local_hymt",
        source_text="שלום",
        source_text_hash=None,
        source_length_chars=4,
        rendered_role_instruction="",
        rendered_task_instruction=policy.task_instruction,
        rendered_output_policy="",
        rendered_glossary_block=None,
        rendered_context_block=None,
        rendered_formatting_note=None,
        rendered_user_payload="שלום",
        effective_prompt_preview="[User]\nשלום",
        glossary_hash=None,
        context_hash=None,
        applied_sampling={"max_new_tokens": 512, "do_sample": True},
        placeholder_tokens_protected=[],
        placeholder_tokens_restored=0,
        raw_model_output="привет",
        translated_text="привет",
        output_length_chars=6,
        output_tokens_generated=None,
        latency_ms=100,
        worker_latency_ms=88,
        glossary_applied=False,
        context_applied=False,
        fallback_triggered=False,
        fallback_reason=None,
    )


def test_audit_history_initially_empty() -> None:
    from app.ui.prompt_audit_dialog import PromptAuditPanel

    assert PromptAuditPanel.get_history() == []


def test_audit_add_trace_single() -> None:
    from app.ui.prompt_audit_dialog import PromptAuditPanel

    PromptAuditPanel.add_trace(_fake_trace("a"))
    assert len(PromptAuditPanel.get_history()) == 1


def test_audit_add_trace_multiple() -> None:
    from app.ui.prompt_audit_dialog import PromptAuditPanel

    for i in range(5):
        PromptAuditPanel.add_trace(_fake_trace(f"t{i}"))
    assert len(PromptAuditPanel.get_history()) == 5


def test_audit_history_cap_at_100() -> None:
    from app.ui.prompt_audit_dialog import PromptAuditPanel

    for i in range(150):
        PromptAuditPanel.add_trace(_fake_trace(f"t{i}"))
    assert len(PromptAuditPanel.get_history()) == 100


def test_audit_history_fifo_eviction() -> None:
    """When history overflows, the OLDEST entry is evicted."""
    from app.ui.prompt_audit_dialog import PromptAuditPanel

    # Fill exactly 100
    for i in range(100):
        PromptAuditPanel.add_trace(_fake_trace(f"t{i}"))
    # Add one more — t0 should be evicted
    PromptAuditPanel.add_trace(_fake_trace("t100"))
    history = PromptAuditPanel.get_history()
    ids = [t.trace_id for t in history]
    assert "t0" not in ids
    assert "t100" in ids


def test_audit_clear_history() -> None:
    from app.ui.prompt_audit_dialog import PromptAuditPanel

    for i in range(10):
        PromptAuditPanel.add_trace(_fake_trace(f"t{i}"))
    PromptAuditPanel.clear_history()
    assert PromptAuditPanel.get_history() == []


def test_audit_get_history_returns_list() -> None:
    from app.ui.prompt_audit_dialog import PromptAuditPanel

    PromptAuditPanel.add_trace(_fake_trace("x"))
    assert isinstance(PromptAuditPanel.get_history(), list)


def test_audit_dialog_add_trace_delegates() -> None:
    from app.ui.prompt_audit_dialog import PromptAuditDialog, PromptAuditPanel

    PromptAuditDialog.add_trace(_fake_trace("d1"))
    assert len(PromptAuditPanel.get_history()) == 1


def test_audit_dialog_clear_history_delegates() -> None:
    from app.ui.prompt_audit_dialog import PromptAuditDialog, PromptAuditPanel

    PromptAuditPanel.add_trace(_fake_trace("x"))
    PromptAuditDialog.clear_history()
    assert PromptAuditPanel.get_history() == []


# ============================================================================
# Colour-coded HTML rendering — testable without UI runtime
# ============================================================================


def test_build_layers_html_returns_string() -> None:
    from app.ui.prompt_audit_dialog import _build_layers_html

    trace = _fake_trace("h1")
    result = _build_layers_html(trace)
    assert isinstance(result, str)
    assert len(result) > 0


def test_build_layers_html_contains_layer_labels() -> None:
    from app.ui.prompt_audit_dialog import _build_layers_html

    trace = _fake_trace("h1")
    html = _build_layers_html(trace)
    assert "Layer 1" in html
    assert "Layer 2" in html
    assert "Layer 5" in html


def test_build_layers_html_has_colour_for_task() -> None:
    from app.ui.prompt_audit_dialog import _build_layers_html, _LAYER_COLOURS

    trace = _fake_trace("h1")
    html = _build_layers_html(trace)
    assert _LAYER_COLOURS["task"] in html


def test_build_meta_html_returns_string() -> None:
    from app.ui.prompt_audit_dialog import _build_meta_html

    trace = _fake_trace("m1")
    result = _build_meta_html(trace)
    assert isinstance(result, str)
    assert "policy_id" in result


def test_build_meta_html_contains_applied_sampling() -> None:
    from app.ui.prompt_audit_dialog import _build_meta_html

    trace = _fake_trace("m1")
    result = _build_meta_html(trace)
    assert "applied_sampling" in result


def test_build_output_html_contains_raw_and_final() -> None:
    from app.ui.prompt_audit_dialog import _build_output_html

    trace = _fake_trace("o1")
    result = _build_output_html(trace)
    assert "Raw Model Output" in result
    assert "Final Translation" in result
    assert "Source Text" in result


def test_build_output_html_escapes_html_chars() -> None:
    from app.ui.prompt_audit_dialog import _build_output_html
    from app.infra.translators.prompt_policy import EffectivePromptTrace, get_policy

    policy = get_policy("sentence_ru")
    t = _fake_trace("xss")
    object.__setattr__(t, "source_text", "<script>alert('xss')</script>")
    result = _build_output_html(t)
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


# ============================================================================
# PATCH-03 / PATCH-04 regression — meta["prompt_policy"] contract unchanged
# ============================================================================


def test_patch03_meta_fields_still_present(provider) -> None:
    """PATCH-03 meta contract must survive PATCH-05 additions."""
    result = provider.translate(_req())
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
    assert required.issubset(pp.keys()), f"missing keys: {required - pp.keys()}"


def test_patch04_sampling_profile_in_meta(provider) -> None:
    """PATCH-04: sampling_profile_id present in meta."""
    result = provider.translate(_req())
    assert "sampling_profile_id" in result.meta["prompt_policy"]


# ---------------------------------------------------------------------------
# PATCH-11: EffectivePromptTrace.to_dict()
# ---------------------------------------------------------------------------


_EXPECTED_DICT_KEYS = {
    "trace_id",
    "policy_id",
    "policy_version",
    "policy_hash",
    "template_profile_id",
    "sampling_profile_id",
    "content_kind",
    "source_lang",
    "target_lang",
    "model_id",
    "model_quant_id",
    "provider_id",
    "source_text",
    "source_text_hash",
    "source_length_chars",
    "rendered_role_instruction",
    "rendered_task_instruction",
    "rendered_output_policy",
    "rendered_glossary_block",
    "rendered_context_block",
    "rendered_formatting_note",
    "rendered_user_payload",
    "effective_prompt_preview",
    "glossary_hash",
    "context_hash",
    "applied_sampling",
    "placeholder_tokens_protected",
    "placeholder_tokens_restored",
    "raw_model_output",
    "translated_text",
    "output_length_chars",
    "output_tokens_generated",
    "latency_ms",
    "worker_latency_ms",
    "glossary_applied",
    "context_applied",
    "fallback_triggered",
    "fallback_reason",
    "created_at",
}


def test_patch11_to_dict_all_keys_present(provider) -> None:
    """to_dict() must include all expected keys."""
    result = provider.translate(_req(trace_id="patch11-test"))
    trace = result.meta["prompt_policy"]["trace"]
    assert trace is not None, "trace must be populated when trace_id is set"
    d = trace.to_dict()
    assert set(d.keys()) == _EXPECTED_DICT_KEYS


def test_patch11_to_dict_created_at_is_iso_string(provider) -> None:
    """created_at must be serialised to an ISO 8601 string."""
    result = provider.translate(_req(trace_id="patch11-test"))
    trace = result.meta["prompt_policy"]["trace"]
    d = trace.to_dict()
    assert isinstance(d["created_at"], str)
    # Must parse back to datetime without error
    from datetime import datetime

    datetime.fromisoformat(d["created_at"])


def test_patch11_to_dict_content_kind_is_str(provider) -> None:
    """content_kind must be a plain str (not an enum instance)."""
    result = provider.translate(_req(trace_id="patch11-test"))
    trace = result.meta["prompt_policy"]["trace"]
    d = trace.to_dict()
    assert isinstance(d["content_kind"], str)


def test_patch11_to_dict_is_json_serialisable(provider) -> None:
    """json.dumps(trace.to_dict()) must not raise."""
    import json

    result = provider.translate(_req(trace_id="patch11-test"))
    trace = result.meta["prompt_policy"]["trace"]
    serialised = json.dumps(trace.to_dict(), ensure_ascii=False)
    assert isinstance(serialised, str) and len(serialised) > 0


def test_patch11_to_dict_nullable_none_preserved(provider) -> None:
    """Nullable fields that are None must appear as None (not absent) in to_dict()."""
    result = provider.translate(_req(trace_id="patch11-test"))
    trace = result.meta["prompt_policy"]["trace"]
    d = trace.to_dict()
    # context_hash and rendered_context_block are None when no context_items provided
    assert "rendered_context_block" in d
    assert "context_hash" in d
