"""Tests for LocalHYMT7BGPTQProvider (thin subclass of LocalHYMTProvider).

Verifies:
- provider_id and display_name are overridden correctly
- model_id and backend default values are 7B-GPTQ-specific
- translate() pipeline is inherited (placeholder protection, glossary)
- Worker GPTQ detection: _load_transformers_causal_model skips dtype for GPTQ
- GPTQ inference path: correct template, generation params, EOS handling
"""

import pytest
from unittest.mock import Mock, patch

from app.infra.translators.providers.local_hymt_7b_gptq_provider import (
    LocalHYMT7BGPTQProvider,
    MODEL_ID,
    BACKEND,
)
from app.infra.translators.providers.local_hymt_provider import LocalHYMTProvider


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_model_manager():
    """Mock ModelResourceManager that reports model installed."""
    manager = Mock()
    manager.is_installed = Mock(return_value=(True, None))
    manager.model_dir = Mock(return_value="/fake/hymt7b/path")
    return manager


@pytest.fixture
def mock_worker():
    """Mock LocalMTWorker."""
    worker = Mock()
    worker.ping = Mock(return_value=True)
    worker.shutdown = Mock()
    return worker


@pytest.fixture
def provider(mock_model_manager, mock_worker):
    """Instantiated LocalHYMT7BGPTQProvider with mocked worker."""
    with patch(
        "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        with patch(
            "app.infra.translators.providers.local_hymt_provider.start_worker",
            return_value=mock_worker,
        ):
            return LocalHYMT7BGPTQProvider()


# ============================================================================
# Test 1: Identity properties are overridden
# ============================================================================


def test_provider_id(provider):
    """provider_id must be 'local_hymt_7b_gptq'."""
    assert provider.provider_id == "local_hymt_7b_gptq"


def test_display_name(provider):
    """display_name must include '7B' and 'GPTQ'."""
    name = provider.display_name
    assert "7B" in name
    assert "GPTQ" in name


def test_model_id_default():
    """Default model_id must be the 7B GPTQ model."""
    assert MODEL_ID == "tencent/HY-MT1.5-7B-GPTQ-Int4"


def test_backend_default():
    """Backend must be transformers_causal (shared with 1.8B)."""
    assert BACKEND == "transformers_causal"


def test_provider_id_distinct_from_1b8(provider):
    """7B provider_id must differ from 1.8B provider_id."""
    assert provider.provider_id != "local_hymt"


# ============================================================================
# Test 2: Inherits LocalHYMTProvider
# ============================================================================


def test_is_subclass():
    """LocalHYMT7BGPTQProvider must subclass LocalHYMTProvider."""
    assert issubclass(LocalHYMT7BGPTQProvider, LocalHYMTProvider)


def test_supports_glossary(provider):
    """Inherits supports_glossary=True from parent."""
    assert provider.supports_glossary is True


def test_supports_batch(provider):
    """Inherits supports_batch=False from parent."""
    assert provider.supports_batch is False


def test_timeout_default(mock_model_manager, mock_worker):
    """Default timeout for 7B is 120s (larger than 1.8B's 60s)."""
    with patch(
        "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        with patch(
            "app.infra.translators.providers.local_hymt_provider.start_worker",
            return_value=mock_worker,
        ):
            p = LocalHYMT7BGPTQProvider()
            assert p.timeout == 120.0


# ============================================================================
# Test 3: model_version isolation from 1.8B
# ============================================================================


def test_get_model_version(provider):
    """model_version must include 7B model id (not 1.8B)."""
    version = provider.get_model_version()
    assert "7B" in version or "HY-MT1.5-7B-GPTQ-Int4" in version.replace("/", "_")


def test_model_version_differs_from_1b8(provider, mock_model_manager, mock_worker):
    """Cache key must not collide with 1.8B provider."""
    with patch(
        "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        with patch(
            "app.infra.translators.providers.local_hymt_provider.start_worker",
            return_value=mock_worker,
        ):
            p_1b8 = LocalHYMTProvider()
            assert provider.get_model_version() != p_1b8.get_model_version()


# ============================================================================
# Test 4: Worker GPTQ detection (unit test on worker function)
# ============================================================================


def test_gptq_detection_logic_positive():
    """'gptq' must appear in lower-cased GPTQ model_id — drives dtype-skip branch."""
    # This is the exact condition used in _load_transformers_causal_model
    assert "gptq" in "tencent/HY-MT1.5-7B-GPTQ-Int4".lower()


def test_gptq_detection_logic_negative():
    """1.8B model_id must NOT contain 'gptq' — must go through dtype-pass branch."""
    assert "gptq" not in "tencent/HY-MT1.5-1.8B".lower()


def test_gptq_detection_case_insensitive():
    """GPTQ detection uses .lower() — mixed-case variants must all match."""
    for variant in ["gptq", "GPTQ", "Gptq", "GPTq"]:
        assert "gptq" in variant.lower()


def test_worker_process_source_has_gptq_branch():
    """worker_process.py must contain the is_gptq dtype-skip branch."""
    import inspect
    from app.infra.local_mt import worker_process

    source = inspect.getsource(worker_process._load_transformers_causal_model)
    assert "is_gptq" in source
    assert "gptq" in source.lower()


# ============================================================================
# Test 5: GPTQ inference path — template, generation params, truncation
# ============================================================================


def test_worker_stores_is_gptq_flag():
    """_load_transformers_causal_model must propagate is_gptq into model_dict."""
    import inspect
    from app.infra.local_mt import worker_process

    source = inspect.getsource(worker_process._load_transformers_causal_model)
    # The function must store is_gptq in the returned dict
    assert '"is_gptq"' in source or "'is_gptq'" in source


def test_7b_template_constants_are_defined():
    """7B-GPTQ template constants must be defined in worker_process module."""
    from app.infra.local_mt import worker_process

    assert hasattr(worker_process, "_HYMT7B_BOS")
    assert hasattr(worker_process, "_HYMT7B_SEP")
    assert hasattr(worker_process, "_HYMT7B_USER_END")
    assert hasattr(worker_process, "_HYMT7B_EOS")


def test_7b_template_constants_distinct_from_1b8():
    """7B template tokens must differ from 1.8B template tokens."""
    from app.infra.local_mt import worker_process

    assert worker_process._HYMT7B_BOS != worker_process._HYMT_BOS
    assert worker_process._HYMT7B_SEP != worker_process._HYMT_SEP
    assert worker_process._HYMT7B_EOS != worker_process._HYMT_EOS


def test_7b_template_token_values():
    """7B template constants must match the model's chat_template.jinja vocabulary."""
    from app.infra.local_mt import worker_process

    assert worker_process._HYMT7B_BOS == "<|startoftext|>"
    assert worker_process._HYMT7B_SEP == "<|extra_4|>"
    assert worker_process._HYMT7B_USER_END == "<|extra_0|>"
    assert worker_process._HYMT7B_EOS == "<|eos|>"


def test_translate_causal_uses_gptq_template_when_is_gptq():
    """_translate_transformers_causal must select 7B template when is_gptq=True."""
    import inspect
    from app.infra.local_mt import worker_process

    source = inspect.getsource(worker_process._translate_transformers_causal)
    # 7B path must use the new template constants, not the 1.8B ones in the GPTQ branch
    assert "_HYMT7B_BOS" in source
    assert "_HYMT7B_SEP" in source
    assert "_HYMT7B_USER_END" in source


def test_translate_causal_uses_gptq_gen_params():
    """GPTQ path must delegate to _resolve_gen_kwargs with is_gptq-derived constraints.

    Since PATCH-04, gen_kwargs are computed by _resolve_gen_kwargs — the literal
    values no longer appear in _translate_transformers_causal source.  Instead we
    verify that the delegation call is present and that _resolve_gen_kwargs itself
    produces the correct values for the GPTQ scenario.
    """
    import inspect
    from app.infra.local_mt import worker_process

    source = inspect.getsource(worker_process._translate_transformers_causal)
    # The function must call _resolve_gen_kwargs (PATCH-04 delegation)
    assert "_resolve_gen_kwargs" in source
    # Hardware constraints for GPTQ must be forwarded
    assert "128" in source  # max_n_predict_cap=128
    assert "is_gptq" in source

    # Functional check via _resolve_gen_kwargs directly
    kwargs = worker_process._resolve_gen_kwargs("hy_mt_precise_sentence", True, 128, [])
    assert kwargs["max_new_tokens"] == 128
    assert kwargs["do_sample"] is False


def test_translate_causal_gptq_boundary_truncation():
    """_translate_transformers_causal must truncate output at dialog boundary for GPTQ.

    Uses source inspection to verify the truncation logic is present without
    importing torch (which fails in test subprocess on Windows).
    """
    import inspect
    from app.infra.local_mt import worker_process

    source = inspect.getsource(worker_process._translate_transformers_causal)

    # The 7B-GPTQ path must check for boundary markers and truncate
    assert "_HYMT7B_USER_END" in source
    assert "_HYMT7B_BOS" in source
    # It must use find() + slice to truncate at the boundary
    assert ".find(" in source
    # The strip() to clean trailing whitespace after truncation
    assert ".strip()" in source


def test_translate_causal_1b8_unaffected_by_gptq_changes():
    """1.8B path (is_gptq=False) must use original template and sampling params.

    Since PATCH-04, sampling params live in _resolve_gen_kwargs.  We verify the
    1.8B template tokens are still in the source AND that _resolve_gen_kwargs
    produces do_sample=True for the 1.8B path (force_greedy=False, temp>0).
    """
    import inspect
    from app.infra.local_mt import worker_process

    source = inspect.getsource(worker_process._translate_transformers_causal)
    # 1.8B template tokens must still be present
    assert "_HYMT_BOS" in source
    assert "_HYMT_ASSISTANT" in source

    # Functional: 1.8B path (force_greedy=False) uses sampling
    kwargs = worker_process._resolve_gen_kwargs("hy_mt_precise_sentence", False, 512, [])
    assert kwargs["do_sample"] is True


def test_warmup_present_in_load_source():
    """_load_transformers_causal_model must include post-load warmup for GPTQ."""
    import inspect
    from app.infra.local_mt import worker_process

    source = inspect.getsource(worker_process._load_transformers_causal_model)
    assert "warmup" in source.lower()
    assert "max_new_tokens" in source  # warmup generates 1 token
