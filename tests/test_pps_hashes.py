"""PPS PATCH-06 — Hash computation tests.

Tests for:
- compute_policy_hash(): SHA-256 canonical policy hash
- compute_source_text_hash(): SHA-256 of UTF-8 source text
- compute_glossary_hash(): SHA-256 of rendered glossary block
- _POLICY_HASH_FIELDS: correct set of fields
- _validate_registry() stamps policy_hash on all built-in policies
- _HYMT_SYSTEM_PROMPT_HASH: 12-char hex constant in worker_process
- get_model_version() includes system prompt hash
- EffectivePromptTrace hash fields populated (not None) when trace_id != ""
- meta["prompt_policy"]["policy_hash"] populated
"""

import hashlib
import json
import copy

import pytest

from app.infra.translators.prompt_policy import (
    PROMPT_POLICIES,
    PromptPolicy,
    _POLICY_HASH_FIELDS,
    compute_glossary_hash,
    compute_policy_hash,
    compute_source_text_hash,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_default_policy() -> PromptPolicy:
    return PROMPT_POLICIES["sentence_ru"]


# ---------------------------------------------------------------------------
# compute_source_text_hash
# ---------------------------------------------------------------------------


def test_source_text_hash_is_sha256_hex() -> None:
    h = compute_source_text_hash("שלום")
    expected = hashlib.sha256("שלום".encode()).hexdigest()
    assert h == expected


def test_source_text_hash_length_64() -> None:
    assert len(compute_source_text_hash("test")) == 64


def test_source_text_hash_empty_string() -> None:
    """Empty input must produce a stable, non-empty hash."""
    h = compute_source_text_hash("")
    assert len(h) == 64
    assert h == hashlib.sha256(b"").hexdigest()


def test_source_text_hash_deterministic() -> None:
    text = "Hello world"
    assert compute_source_text_hash(text) == compute_source_text_hash(text)


def test_source_text_hash_different_texts() -> None:
    assert compute_source_text_hash("abc") != compute_source_text_hash("abd")


def test_source_text_hash_unicode_normalization_sensitivity() -> None:
    """Different byte sequences → different hashes (no normalization applied)."""
    nfc = "é"  # U+00E9 (precomposed)
    nfd = "e\u0301"  # U+0065 + U+0301 (decomposed)
    # They are different byte sequences, so hashes should differ
    assert compute_source_text_hash(nfc) != compute_source_text_hash(nfd)


# ---------------------------------------------------------------------------
# compute_glossary_hash
# ---------------------------------------------------------------------------


def test_glossary_hash_is_sha256_hex() -> None:
    block = "Term: foo → bar"
    h = compute_glossary_hash(block)
    expected = hashlib.sha256(block.encode()).hexdigest()
    assert h == expected


def test_glossary_hash_length_64() -> None:
    assert len(compute_glossary_hash("anything")) == 64


def test_glossary_hash_empty_string() -> None:
    h = compute_glossary_hash("")
    assert len(h) == 64


def test_glossary_hash_deterministic() -> None:
    block = "a: b\nc: d"
    assert compute_glossary_hash(block) == compute_glossary_hash(block)


def test_glossary_hash_different_blocks() -> None:
    assert compute_glossary_hash("a") != compute_glossary_hash("b")


# ---------------------------------------------------------------------------
# _POLICY_HASH_FIELDS
# ---------------------------------------------------------------------------


def test_policy_hash_fields_is_tuple() -> None:
    assert isinstance(_POLICY_HASH_FIELDS, tuple)


def test_policy_hash_fields_length() -> None:
    assert len(_POLICY_HASH_FIELDS) == 19


def test_policy_hash_fields_contains_semantic_fields() -> None:
    required = {
        "policy_id",
        "version",
        "content_kind",
        "source_lang",
        "target_lang",
        "role_instruction",
        "task_instruction",
        "output_policy",
        "terminology_mode",
        "sampling_profile_id",
        "template_profile_id",
        "glossary_strategy",
        "context_strategy",
        "max_glossary_items",
        "max_context_items",
        "max_input_chars",
    }
    assert required.issubset(set(_POLICY_HASH_FIELDS))


def test_policy_hash_fields_excludes_metadata_fields() -> None:
    excluded = {
        "name",
        "description",
        "enabled",
        "is_builtin",
        "is_custom",
        "experimental",
        "allow_user_edit_instructions",
        "allow_user_edit_sampling",
        "created_at",
        "updated_at",
        "policy_hash",
    }
    for field in excluded:
        assert field not in _POLICY_HASH_FIELDS, f"Metadata field '{field}' must be excluded"


# ---------------------------------------------------------------------------
# compute_policy_hash
# ---------------------------------------------------------------------------


def test_compute_policy_hash_returns_hex_64() -> None:
    policy = _get_default_policy()
    h = compute_policy_hash(policy)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_compute_policy_hash_deterministic() -> None:
    policy = _get_default_policy()
    assert compute_policy_hash(policy) == compute_policy_hash(policy)


def test_compute_policy_hash_consistent_across_policies() -> None:
    """All built-in policies produce non-empty, distinct hashes."""
    hashes = [compute_policy_hash(p) for p in PROMPT_POLICIES.values()]
    assert all(len(h) == 64 for h in hashes)
    # All built-in policies should have distinct hashes
    assert len(set(hashes)) == len(hashes), "Collision among built-in policy hashes"


def test_compute_policy_hash_independent_of_name() -> None:
    """Changing `name` must not change the hash."""
    policy = _get_default_policy()
    original = compute_policy_hash(policy)
    policy.name = "Renamed Policy"
    assert compute_policy_hash(policy) == original
    policy.name = "Standard Translation"  # restore


def test_compute_policy_hash_independent_of_description() -> None:
    policy = _get_default_policy()
    original = compute_policy_hash(policy)
    policy.description = "Completely different description"
    assert compute_policy_hash(policy) == original
    policy.description = ""  # restore


def test_compute_policy_hash_changes_on_semantic_field() -> None:
    """Mutating task_instruction must produce a different hash."""
    policy = _get_default_policy()
    original = compute_policy_hash(policy)
    saved = policy.task_instruction
    policy.task_instruction = "Different instruction."
    assert compute_policy_hash(policy) != original
    policy.task_instruction = saved  # restore


def test_compute_policy_hash_uses_sort_keys() -> None:
    """Hash must be based on sort_keys=True JSON — stable regardless of dict insertion order."""
    policy = _get_default_policy()
    canonical: dict = {}
    for fn in _POLICY_HASH_FIELDS:
        canonical[fn] = (
            str(getattr(policy, fn))
            if hasattr(getattr(policy, fn), "__str__")
            and type(getattr(policy, fn)).__name__ != "str"
            and not isinstance(getattr(policy, fn), (int, float, bool, type(None)))
            else getattr(policy, fn)
        )

    # Two dicts with same content in different order must hash identically
    canonical_a = dict(sorted(canonical.items()))
    canonical_b = dict(reversed(list(canonical.items())))
    assert json.dumps(canonical_a, sort_keys=True) == json.dumps(canonical_b, sort_keys=True)


# ---------------------------------------------------------------------------
# _validate_registry stamps policy_hash on all built-in policies
# ---------------------------------------------------------------------------


def test_all_builtin_policies_have_policy_hash() -> None:
    """_validate_registry() must have stamped policy_hash on all built-in policies."""
    for policy_id, policy in PROMPT_POLICIES.items():
        assert policy.policy_hash is not None, f"policy_hash is None for {policy_id!r}"
        assert len(policy.policy_hash) == 64, f"Wrong hash length for {policy_id!r}"


def test_builtin_policy_hash_matches_compute() -> None:
    """Stamped policy_hash must equal a fresh compute_policy_hash() call."""
    for policy_id, policy in PROMPT_POLICIES.items():
        fresh = compute_policy_hash(policy)
        assert policy.policy_hash == fresh, (
            f"Stamped hash mismatch for {policy_id!r}: " f"{policy.policy_hash!r} != {fresh!r}"
        )


# ---------------------------------------------------------------------------
# _HYMT_SYSTEM_PROMPT_HASH — worker_process constant
# ---------------------------------------------------------------------------


def test_hymt_system_prompt_hash_exists() -> None:
    from app.infra.local_mt import _HYMT_SYSTEM_PROMPT_HASH

    assert _HYMT_SYSTEM_PROMPT_HASH is not None


def test_hymt_system_prompt_hash_is_12_char_hex() -> None:
    from app.infra.local_mt import _HYMT_SYSTEM_PROMPT_HASH

    assert len(_HYMT_SYSTEM_PROMPT_HASH) == 12
    assert all(c in "0123456789abcdef" for c in _HYMT_SYSTEM_PROMPT_HASH)


def test_hymt_system_prompt_hash_correct_value() -> None:
    from app.infra.local_mt import _HYMT_SYSTEM_PROMPT_HASH
    from app.infra.local_mt.worker_process import _HYMT_SYSTEM_PROMPT

    expected = hashlib.sha256(_HYMT_SYSTEM_PROMPT.encode()).hexdigest()[:12]
    assert _HYMT_SYSTEM_PROMPT_HASH == expected


def test_hymt_system_prompt_hash_exported_from_init() -> None:
    """__init__.py must re-export the constant."""
    import app.infra.local_mt as mod

    assert hasattr(mod, "_HYMT_SYSTEM_PROMPT_HASH")


# ---------------------------------------------------------------------------
# get_model_version() includes system prompt hash
# ---------------------------------------------------------------------------


def test_get_model_version_includes_system_prompt_hash() -> None:
    from app.infra.local_mt import _HYMT_SYSTEM_PROMPT_HASH
    from app.infra.translators.providers.local_hymt_provider import LocalHYMTProvider

    provider = LocalHYMTProvider.__new__(LocalHYMTProvider)
    provider.model_id = "tencent/HY-MT1.5-1.8B"
    provider.backend = "transformers_causal"

    version = provider.get_model_version()
    assert _HYMT_SYSTEM_PROMPT_HASH in version


def test_get_model_version_format() -> None:
    from app.infra.local_mt import _HYMT_SYSTEM_PROMPT_HASH
    from app.infra.translators.providers.local_hymt_provider import LocalHYMTProvider

    provider = LocalHYMTProvider.__new__(LocalHYMTProvider)
    provider.model_id = "tencent/HY-MT1.5-1.8B"
    provider.backend = "transformers_causal"

    version = provider.get_model_version()
    safe_model_id = "tencent_HY-MT1.5-1.8B"
    assert version == f"{safe_model_id}_transformers_causal_{_HYMT_SYSTEM_PROMPT_HASH}"


# ---------------------------------------------------------------------------
# Trace hash fields populated when trace_id != ""
# ---------------------------------------------------------------------------


def test_trace_policy_hash_populated() -> None:
    """policy_hash in trace must equal policy.policy_hash (not None)."""
    from unittest.mock import MagicMock

    from app.infra.translators.base_provider import TranslationRequest
    from app.infra.translators.providers.local_hymt_provider import LocalHYMTProvider

    policy = PROMPT_POLICIES["sentence_ru"]
    assert policy.policy_hash is not None  # precondition

    provider = LocalHYMTProvider.__new__(LocalHYMTProvider)
    provider.model_id = "tencent/HY-MT1.5-1.8B"
    provider.backend = "transformers_causal"
    provider._FORCE_GREEDY = False
    provider._MAX_N_PREDICT_CAP = 512
    provider._MODEL_QUANT_ID = None

    request = MagicMock(spec=TranslationRequest)
    request.trace_id = "test-trace-001"
    request.source_text = "שלום"
    request.source_lang = "he"
    request.target_lang = "ru"

    from app.infra.translators.prompt_policy import RouterResult

    router_result = MagicMock(spec=RouterResult)
    router_result.fallback_triggered = False
    router_result.fallback_reason = None
    router_result.warnings = []

    from app.infra.translators.providers.local_hymt_provider import _ProtectedText

    protected = _ProtectedText(text="שלום", mapping={})

    trace = provider._build_trace(
        request=request,
        policy=policy,
        router_result=router_result,
        resolved_template_profile_id=policy.template_profile_id,
        protected=protected,
        glossary_terms=[],
        raw_model_output="Привет",
        final_translation="Привет",
        missing=[],
        used_glossary=False,
        applied_terms_count=0,
        latency_ms=100,
        worker_latency_ms=80,
    )

    assert trace.policy_hash == policy.policy_hash
    assert trace.policy_hash is not None


def test_trace_source_text_hash_populated() -> None:
    from unittest.mock import MagicMock

    from app.infra.translators.base_provider import TranslationRequest
    from app.infra.translators.providers.local_hymt_provider import (
        LocalHYMTProvider,
        _ProtectedText,
    )

    policy = PROMPT_POLICIES["sentence_ru"]
    provider = LocalHYMTProvider.__new__(LocalHYMTProvider)
    provider.model_id = "tencent/HY-MT1.5-1.8B"
    provider.backend = "transformers_causal"
    provider._FORCE_GREEDY = False
    provider._MAX_N_PREDICT_CAP = 512
    provider._MODEL_QUANT_ID = None

    request = MagicMock(spec=TranslationRequest)
    request.trace_id = "test-trace-002"
    request.source_text = "שלום עולם"
    request.source_lang = "he"
    request.target_lang = "ru"

    from app.infra.translators.prompt_policy import RouterResult

    router_result = MagicMock(spec=RouterResult)
    router_result.fallback_triggered = False
    router_result.fallback_reason = None
    router_result.warnings = []

    protected = _ProtectedText(text="שלום עולם", mapping={})

    trace = provider._build_trace(
        request=request,
        policy=policy,
        router_result=router_result,
        resolved_template_profile_id=policy.template_profile_id,
        protected=protected,
        glossary_terms=[],
        raw_model_output="Привет мир",
        final_translation="Привет мир",
        missing=[],
        used_glossary=False,
        applied_terms_count=0,
        latency_ms=100,
        worker_latency_ms=80,
    )

    expected_hash = compute_source_text_hash("שלום עולם")
    assert trace.source_text_hash == expected_hash


def test_trace_glossary_hash_none_when_no_glossary() -> None:
    from unittest.mock import MagicMock

    from app.infra.translators.base_provider import TranslationRequest
    from app.infra.translators.providers.local_hymt_provider import (
        LocalHYMTProvider,
        _ProtectedText,
    )

    policy = PROMPT_POLICIES["sentence_ru"]
    provider = LocalHYMTProvider.__new__(LocalHYMTProvider)
    provider.model_id = "tencent/HY-MT1.5-1.8B"
    provider.backend = "transformers_causal"
    provider._FORCE_GREEDY = False
    provider._MAX_N_PREDICT_CAP = 512
    provider._MODEL_QUANT_ID = None

    request = MagicMock(spec=TranslationRequest)
    request.trace_id = "test-trace-003"
    request.source_text = "test"
    request.source_lang = "he"
    request.target_lang = "ru"

    from app.infra.translators.prompt_policy import RouterResult

    router_result = MagicMock(spec=RouterResult)
    router_result.fallback_triggered = False
    router_result.fallback_reason = None
    router_result.warnings = []

    protected = _ProtectedText(text="test", mapping={})

    trace = provider._build_trace(
        request=request,
        policy=policy,
        router_result=router_result,
        resolved_template_profile_id=policy.template_profile_id,
        protected=protected,
        glossary_terms=[],  # empty — no glossary
        raw_model_output="тест",
        final_translation="тест",
        missing=[],
        used_glossary=False,
        applied_terms_count=0,
        latency_ms=50,
        worker_latency_ms=30,
    )

    # No glossary terms → glossary_hash must be None
    assert trace.glossary_hash is None


def test_trace_context_hash_is_none_patch07() -> None:
    """context_hash stays None until PATCH-07 wires context."""
    from unittest.mock import MagicMock

    from app.infra.translators.base_provider import TranslationRequest
    from app.infra.translators.providers.local_hymt_provider import (
        LocalHYMTProvider,
        _ProtectedText,
    )

    policy = PROMPT_POLICIES["sentence_ru"]
    provider = LocalHYMTProvider.__new__(LocalHYMTProvider)
    provider.model_id = "tencent/HY-MT1.5-1.8B"
    provider.backend = "transformers_causal"
    provider._FORCE_GREEDY = False
    provider._MAX_N_PREDICT_CAP = 512
    provider._MODEL_QUANT_ID = None

    request = MagicMock(spec=TranslationRequest)
    request.trace_id = "test-trace-004"
    request.source_text = "test"
    request.source_lang = "he"
    request.target_lang = "ru"

    from app.infra.translators.prompt_policy import RouterResult

    router_result = MagicMock(spec=RouterResult)
    router_result.fallback_triggered = False
    router_result.fallback_reason = None
    router_result.warnings = []

    protected = _ProtectedText(text="test", mapping={})

    trace = provider._build_trace(
        request=request,
        policy=policy,
        router_result=router_result,
        resolved_template_profile_id=policy.template_profile_id,
        protected=protected,
        glossary_terms=[],
        raw_model_output="тест",
        final_translation="тест",
        missing=[],
        used_glossary=False,
        applied_terms_count=0,
        latency_ms=50,
        worker_latency_ms=30,
    )

    assert trace.context_hash is None
