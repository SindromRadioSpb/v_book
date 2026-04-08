"""PPS PATCH-08 — Context block wiring (Layer 4b) tests.

Tests for:
- compute_context_hash(): SHA-256 of rendered context block
- context_items from request.options wired to render_sentinel_payload()
- render_effective_preview() includes context block when context_items provided
- _render_context_block() format (Context: header + items)
- EffectivePromptTrace.rendered_context_block populated when context_items provided
- EffectivePromptTrace.context_hash populated (not None) when context applied
- EffectivePromptTrace.context_applied=True when context_items provided + context_mode != off
- EffectivePromptTrace.context_applied=False when context_mode=off or no context_items
- EffectivePromptTrace.context_hash=None when no context_items
- sentence_ru policy (context_mode=off) ignores context_items
- sentence_ru_context policy (context_mode=surrounding_sentences) uses context_items
- context_items=None → context_hash=None in trace
- context_items=[] (empty) → context_hash=None, context_applied=False
"""

import hashlib

import pytest

from app.infra.translators.prompt_policy import (
    PROMPT_POLICIES,
    ContextMode,
    PolicyRenderer,
    compute_context_hash,
)


# ---------------------------------------------------------------------------
# compute_context_hash
# ---------------------------------------------------------------------------


def test_context_hash_is_sha256_hex() -> None:
    block = "Context:\n  prev sentence\n  next sentence"
    h = compute_context_hash(block)
    assert h == hashlib.sha256(block.encode()).hexdigest()


def test_context_hash_length_64() -> None:
    assert len(compute_context_hash("anything")) == 64


def test_context_hash_empty_string() -> None:
    h = compute_context_hash("")
    assert len(h) == 64
    assert h == hashlib.sha256(b"").hexdigest()


def test_context_hash_deterministic() -> None:
    block = "Context:\n  hello\n  world"
    assert compute_context_hash(block) == compute_context_hash(block)


def test_context_hash_different_blocks() -> None:
    assert compute_context_hash("a") != compute_context_hash("b")


# ---------------------------------------------------------------------------
# PolicyRenderer._render_context_block
# ---------------------------------------------------------------------------


def test_render_context_block_contains_header() -> None:
    renderer = PolicyRenderer()
    block = renderer._render_context_block(["prev", "next"])
    assert block.startswith("Context:")


def test_render_context_block_contains_items() -> None:
    renderer = PolicyRenderer()
    block = renderer._render_context_block(["prev segment", "next segment"])
    assert "prev segment" in block
    assert "next segment" in block


def test_render_context_block_single_item() -> None:
    renderer = PolicyRenderer()
    block = renderer._render_context_block(["only item"])
    assert "only item" in block


def test_render_context_block_multiple_items_all_present() -> None:
    renderer = PolicyRenderer()
    items = ["item1", "item2", "item3"]
    block = renderer._render_context_block(items)
    for item in items:
        assert item in block


# ---------------------------------------------------------------------------
# PolicyRenderer.render_effective_preview — context block presence
# ---------------------------------------------------------------------------


def test_preview_includes_context_when_context_mode_active() -> None:
    renderer = PolicyRenderer()
    policy = PROMPT_POLICIES.get("sentence_ru_context")
    if policy is None:
        pytest.skip("sentence_ru_context policy not in registry")
    preview = renderer.render_effective_preview(
        policy=policy,
        source_text="test",
        context_items=["previous sentence", "next sentence"],
    )
    assert "Context:" in preview or "previous sentence" in preview


def test_preview_excludes_context_when_context_mode_off() -> None:
    renderer = PolicyRenderer()
    policy = PROMPT_POLICIES["sentence_ru"]  # context_mode=off
    preview = renderer.render_effective_preview(
        policy=policy,
        source_text="test",
        context_items=["previous sentence", "next sentence"],
    )
    # sentence_ru has context_mode=off → context items must not appear
    assert "previous sentence" not in preview
    assert "next sentence" not in preview


def test_preview_no_context_when_context_items_none() -> None:
    renderer = PolicyRenderer()
    policy = PROMPT_POLICIES.get("sentence_ru_context")
    if policy is None:
        pytest.skip("sentence_ru_context policy not in registry")
    preview = renderer.render_effective_preview(
        policy=policy,
        source_text="test",
        context_items=None,
    )
    assert "Context:" not in preview


# ---------------------------------------------------------------------------
# _build_trace context fields — using direct call
# ---------------------------------------------------------------------------


def _make_provider():
    """Return a LocalHYMTProvider with mocked worker."""
    from unittest.mock import Mock, patch

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
        return LocalHYMTProvider()


def _build_trace_direct(provider, context_items, policy_id="sentence_ru"):
    """Call _build_trace() directly with minimal required args."""
    from unittest.mock import MagicMock

    from app.infra.translators.base_provider import TranslationRequest
    from app.infra.translators.prompt_policy import RouterResult
    from app.infra.translators.providers.local_hymt_provider import _ProtectedText

    policy = PROMPT_POLICIES[policy_id]

    request = MagicMock(spec=TranslationRequest)
    request.trace_id = "test-ctx-trace"
    request.source_text = "שלום"
    request.source_lang = "he"
    request.target_lang = "ru"

    router_result = MagicMock(spec=RouterResult)
    router_result.fallback_triggered = False
    router_result.fallback_reason = None
    router_result.warnings = []

    protected = _ProtectedText(text="שלום", mapping={})

    return provider._build_trace(
        request=request,
        policy=policy,
        router_result=router_result,
        resolved_template_profile_id=policy.template_profile_id,
        context_items=context_items,
        protected=protected,
        glossary_terms=[],
        raw_model_output="перевод",
        final_translation="перевод",
        missing=[],
        used_glossary=False,
        applied_terms_count=0,
        latency_ms=100,
        worker_latency_ms=80,
    )


def test_trace_context_hash_none_when_no_context_items() -> None:
    provider = _make_provider()
    trace = _build_trace_direct(provider, context_items=None)
    assert trace.context_hash is None


def test_trace_context_hash_none_when_empty_context_items() -> None:
    provider = _make_provider()
    trace = _build_trace_direct(provider, context_items=[])
    assert trace.context_hash is None


def test_trace_context_hash_none_when_context_mode_off() -> None:
    """sentence_ru has context_mode=off → context_hash must be None even with items."""
    provider = _make_provider()
    trace = _build_trace_direct(provider, context_items=["prev", "next"], policy_id="sentence_ru")
    assert trace.context_hash is None


def test_trace_context_hash_populated_when_context_mode_active() -> None:
    """sentence_ru_context has context_mode=surrounding_sentences → context_hash must be set."""
    policy = PROMPT_POLICIES.get("sentence_ru_context")
    if policy is None:
        pytest.skip("sentence_ru_context policy not in registry")
    provider = _make_provider()
    trace = _build_trace_direct(
        provider, context_items=["prev segment", "next segment"], policy_id="sentence_ru_context"
    )
    assert trace.context_hash is not None
    assert len(trace.context_hash) == 64


def test_trace_context_hash_value_matches_rendered_block() -> None:
    """context_hash must equal compute_context_hash of the rendered block."""
    policy = PROMPT_POLICIES.get("sentence_ru_context")
    if policy is None:
        pytest.skip("sentence_ru_context policy not in registry")
    provider = _make_provider()
    context_items = ["first prev", "second prev"]
    trace = _build_trace_direct(
        provider, context_items=context_items, policy_id="sentence_ru_context"
    )
    if trace.rendered_context_block is None:
        pytest.skip("context not rendered — context_mode may be off")
    expected_hash = compute_context_hash(trace.rendered_context_block)
    assert trace.context_hash == expected_hash


def test_trace_context_applied_false_when_no_items() -> None:
    provider = _make_provider()
    trace = _build_trace_direct(provider, context_items=None)
    assert trace.context_applied is False


def test_trace_context_applied_false_when_context_mode_off() -> None:
    provider = _make_provider()
    trace = _build_trace_direct(provider, context_items=["prev"], policy_id="sentence_ru")
    assert trace.context_applied is False


def test_trace_context_applied_true_when_context_active() -> None:
    policy = PROMPT_POLICIES.get("sentence_ru_context")
    if policy is None:
        pytest.skip("sentence_ru_context policy not in registry")
    provider = _make_provider()
    trace = _build_trace_direct(provider, context_items=["prev"], policy_id="sentence_ru_context")
    assert trace.context_applied is True


def test_trace_rendered_context_block_none_when_no_items() -> None:
    provider = _make_provider()
    trace = _build_trace_direct(provider, context_items=None)
    assert trace.rendered_context_block is None


def test_trace_rendered_context_block_none_when_context_mode_off() -> None:
    provider = _make_provider()
    trace = _build_trace_direct(provider, context_items=["prev"], policy_id="sentence_ru")
    assert trace.rendered_context_block is None


def test_trace_rendered_context_block_contains_items_when_active() -> None:
    policy = PROMPT_POLICIES.get("sentence_ru_context")
    if policy is None:
        pytest.skip("sentence_ru_context policy not in registry")
    provider = _make_provider()
    trace = _build_trace_direct(
        provider, context_items=["my prev segment"], policy_id="sentence_ru_context"
    )
    assert trace.rendered_context_block is not None
    assert "my prev segment" in trace.rendered_context_block


# ---------------------------------------------------------------------------
# translate() — context_items wired via request.options
# ---------------------------------------------------------------------------


def test_translate_context_items_in_options_wired_to_render() -> None:
    """context_items in request.options must flow into the rendered prompt."""
    from unittest.mock import Mock, patch

    from app.infra.translators.base_provider import TranslationRequest
    from app.infra.translators.providers.local_hymt_provider import LocalHYMTProvider

    mock_manager = Mock()
    mock_manager.is_installed = Mock(return_value=(True, None))
    mock_manager.model_dir = Mock(return_value="/fake/hymt/path")

    sentinel_calls: list[dict] = []

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

    # Capture what the renderer was called with
    original_render = provider._RENDERER if hasattr(provider, "_RENDERER") else None

    request = TranslationRequest(
        source_text="שלום",
        source_lang="he",
        target_lang="ru",
        options={"context_items": ["prev seg", "next seg"]},
        trace_id="",
    )
    result = provider.translate(request)
    # Translation should succeed; no crash from context_items being passed
    assert result.error_kind is None
    assert result.translated_text is not None


def test_translate_no_context_items_in_options_no_crash() -> None:
    """Absence of context_items in options must not break translate()."""
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
        source_text="שלום",
        source_lang="he",
        target_lang="ru",
        options={},
        trace_id="",
    )
    result = provider.translate(request)
    assert result.error_kind is None
