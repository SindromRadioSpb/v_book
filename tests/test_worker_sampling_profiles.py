"""Tests for PATCH-04: _resolve_gen_kwargs + _WORKER_SAMPLING_PROFILES.

Verifies:
- _WORKER_SAMPLING_PROFILES contains exactly the 3 expected profiles
- Values in _WORKER_SAMPLING_PROFILES match SAMPLING_PROFILES in prompt_policy
- _resolve_gen_kwargs produces correct gen_kwargs for each scenario
- force_greedy=True always yields do_sample=False (with WARNING for temp > 0)
- temperature=0.0 in profile yields do_sample=False (no hardware constraint)
- Unknown sampling_profile_id falls back to hy_mt_precise_sentence (with WARNING)
- max_n_predict_cap is applied correctly
- stop_ids are threaded through
- WorkerRequest has sampling_profile_id field with empty-string default
- WorkerRequest is still constructible without sampling_profile_id (backwards compat)
- _translate_transformers_causal accepts sampling_profile_id parameter

No torch import. All tests are pure-Python source-level inspection + unit tests.
"""

import inspect
import logging

import pytest

from app.infra.local_mt.worker_process import (
    WorkerRequest,
    _WORKER_DEFAULT_SAMPLING_PROFILE_ID,
    _WORKER_SAMPLING_PROFILES,
    _resolve_gen_kwargs,
    _translate_transformers_causal,
)
from app.infra.translators.prompt_policy import SAMPLING_PROFILES


# ============================================================================
# _WORKER_SAMPLING_PROFILES — structure
# ============================================================================


def test_worker_sampling_profiles_has_three_entries() -> None:
    assert len(_WORKER_SAMPLING_PROFILES) == 3


def test_worker_sampling_profiles_has_precise_sentence() -> None:
    assert "hy_mt_precise_sentence" in _WORKER_SAMPLING_PROFILES


def test_worker_sampling_profiles_has_precise_short() -> None:
    assert "hy_mt_precise_short" in _WORKER_SAMPLING_PROFILES


def test_worker_sampling_profiles_has_precise_formatted() -> None:
    assert "hy_mt_precise_formatted" in _WORKER_SAMPLING_PROFILES


def test_worker_sampling_profiles_all_have_required_keys() -> None:
    required = {"temperature", "top_k", "top_p", "repetition_penalty", "n_predict"}
    for pid, profile in _WORKER_SAMPLING_PROFILES.items():
        assert required.issubset(profile.keys()), f"profile {pid!r} missing keys"


# ============================================================================
# Value parity with prompt_policy.SAMPLING_PROFILES
# ============================================================================


def test_precise_sentence_temperature_matches_policy() -> None:
    assert _WORKER_SAMPLING_PROFILES["hy_mt_precise_sentence"]["temperature"] == pytest.approx(
        SAMPLING_PROFILES["hy_mt_precise_sentence"].temperature
    )


def test_precise_sentence_top_k_matches_policy() -> None:
    assert (
        _WORKER_SAMPLING_PROFILES["hy_mt_precise_sentence"]["top_k"]
        == SAMPLING_PROFILES["hy_mt_precise_sentence"].top_k
    )


def test_precise_sentence_top_p_matches_policy() -> None:
    assert _WORKER_SAMPLING_PROFILES["hy_mt_precise_sentence"]["top_p"] == pytest.approx(
        SAMPLING_PROFILES["hy_mt_precise_sentence"].top_p
    )


def test_precise_sentence_repetition_penalty_matches_policy() -> None:
    assert _WORKER_SAMPLING_PROFILES["hy_mt_precise_sentence"][
        "repetition_penalty"
    ] == pytest.approx(SAMPLING_PROFILES["hy_mt_precise_sentence"].repetition_penalty)


def test_precise_sentence_n_predict_matches_policy() -> None:
    assert (
        _WORKER_SAMPLING_PROFILES["hy_mt_precise_sentence"]["n_predict"]
        == SAMPLING_PROFILES["hy_mt_precise_sentence"].n_predict
    )


def test_precise_short_temperature_is_zero() -> None:
    assert _WORKER_SAMPLING_PROFILES["hy_mt_precise_short"]["temperature"] == 0.0


def test_precise_short_n_predict_matches_policy() -> None:
    assert (
        _WORKER_SAMPLING_PROFILES["hy_mt_precise_short"]["n_predict"]
        == SAMPLING_PROFILES["hy_mt_precise_short"].n_predict
    )


def test_precise_formatted_temperature_matches_policy() -> None:
    assert _WORKER_SAMPLING_PROFILES["hy_mt_precise_formatted"]["temperature"] == pytest.approx(
        SAMPLING_PROFILES["hy_mt_precise_formatted"].temperature
    )


def test_precise_formatted_top_k_matches_policy() -> None:
    assert (
        _WORKER_SAMPLING_PROFILES["hy_mt_precise_formatted"]["top_k"]
        == SAMPLING_PROFILES["hy_mt_precise_formatted"].top_k
    )


# ============================================================================
# _resolve_gen_kwargs — 1.8B path (force_greedy=False)
# ============================================================================


def test_resolve_sentence_produces_do_sample_true() -> None:
    kwargs = _resolve_gen_kwargs("hy_mt_precise_sentence", False, 512, [])
    assert kwargs["do_sample"] is True


def test_resolve_sentence_produces_correct_max_new_tokens() -> None:
    kwargs = _resolve_gen_kwargs("hy_mt_precise_sentence", False, 512, [])
    assert kwargs["max_new_tokens"] == 512


def test_resolve_sentence_produces_correct_temperature() -> None:
    kwargs = _resolve_gen_kwargs("hy_mt_precise_sentence", False, 512, [])
    assert kwargs["temperature"] == pytest.approx(0.7)


def test_resolve_sentence_produces_correct_top_k() -> None:
    kwargs = _resolve_gen_kwargs("hy_mt_precise_sentence", False, 512, [])
    assert kwargs["top_k"] == 20


def test_resolve_sentence_produces_correct_top_p() -> None:
    kwargs = _resolve_gen_kwargs("hy_mt_precise_sentence", False, 512, [])
    assert kwargs["top_p"] == pytest.approx(0.6)


def test_resolve_sentence_produces_correct_repetition_penalty() -> None:
    kwargs = _resolve_gen_kwargs("hy_mt_precise_sentence", False, 512, [])
    assert kwargs["repetition_penalty"] == pytest.approx(1.05)


def test_resolve_sentence_stop_ids_threaded_through() -> None:
    stop_ids = [42, 99]
    kwargs = _resolve_gen_kwargs("hy_mt_precise_sentence", False, 512, stop_ids)
    assert kwargs["eos_token_id"] == stop_ids


def test_resolve_sentence_empty_stop_ids_yields_none() -> None:
    kwargs = _resolve_gen_kwargs("hy_mt_precise_sentence", False, 512, [])
    assert kwargs["eos_token_id"] is None


# ============================================================================
# _resolve_gen_kwargs — hy_mt_precise_short (greedy by intent)
# ============================================================================


def test_resolve_short_greedy_by_intent() -> None:
    """temperature=0.0 in profile → do_sample=False without hardware constraint."""
    kwargs = _resolve_gen_kwargs("hy_mt_precise_short", False, 512, [])
    assert kwargs["do_sample"] is False


def test_resolve_short_n_predict_respected() -> None:
    kwargs = _resolve_gen_kwargs("hy_mt_precise_short", False, 512, [])
    assert kwargs["max_new_tokens"] == 32


def test_resolve_short_no_sampling_keys() -> None:
    """Greedy kwargs must not contain top_k/top_p/temperature."""
    kwargs = _resolve_gen_kwargs("hy_mt_precise_short", False, 512, [])
    for key in ("top_k", "top_p", "temperature", "repetition_penalty"):
        assert key not in kwargs, f"unexpected key {key!r} in greedy kwargs"


# ============================================================================
# _resolve_gen_kwargs — 7B-GPTQ path (force_greedy=True)
# ============================================================================


def test_resolve_gptq_force_greedy_yields_do_sample_false() -> None:
    kwargs = _resolve_gen_kwargs("hy_mt_precise_sentence", True, 128, [])
    assert kwargs["do_sample"] is False


def test_resolve_gptq_n_predict_capped_to_128() -> None:
    """max_n_predict_cap=128 beats profile's n_predict=512."""
    kwargs = _resolve_gen_kwargs("hy_mt_precise_sentence", True, 128, [])
    assert kwargs["max_new_tokens"] == 128


def test_resolve_gptq_no_sampling_keys() -> None:
    kwargs = _resolve_gen_kwargs("hy_mt_precise_sentence", True, 128, [42])
    for key in ("top_k", "top_p", "temperature", "repetition_penalty"):
        assert key not in kwargs, f"unexpected key {key!r} in greedy kwargs"


def test_resolve_gptq_stop_ids_present() -> None:
    stop_ids = [127960]
    kwargs = _resolve_gen_kwargs("hy_mt_precise_sentence", True, 128, stop_ids)
    assert kwargs["eos_token_id"] == stop_ids


# ============================================================================
# _resolve_gen_kwargs — max_n_predict_cap enforcement
# ============================================================================


def test_cap_reduces_n_predict() -> None:
    kwargs = _resolve_gen_kwargs("hy_mt_precise_sentence", False, 100, [])
    assert kwargs["max_new_tokens"] == 100


def test_cap_none_does_not_reduce() -> None:
    kwargs = _resolve_gen_kwargs("hy_mt_precise_sentence", False, None, [])
    assert kwargs["max_new_tokens"] == 512


def test_cap_larger_than_profile_does_not_increase() -> None:
    """Cap is only an upper bound — cannot exceed profile n_predict."""
    kwargs = _resolve_gen_kwargs("hy_mt_precise_short", False, 512, [])
    # profile n_predict=32 < cap=512 → stays at 32
    assert kwargs["max_new_tokens"] == 32


# ============================================================================
# _resolve_gen_kwargs — unknown profile fallback
# ============================================================================


def test_unknown_profile_falls_back_silently(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        kwargs = _resolve_gen_kwargs("nonexistent_profile_xyz", False, 512, [])
    assert kwargs["do_sample"] is True  # sentence profile default
    assert any("nonexistent_profile_xyz" in r.message for r in caplog.records)


def test_empty_profile_id_uses_default_no_warning(caplog) -> None:
    """Empty string must not emit WARNING — it's the normal 'no explicit profile' path."""
    with caplog.at_level(logging.WARNING):
        kwargs = _resolve_gen_kwargs("", False, 512, [])
    # No warning emitted
    assert not any(r.levelno >= logging.WARNING for r in caplog.records)
    # Still produces valid kwargs
    assert "max_new_tokens" in kwargs


def test_force_greedy_with_nonzero_temp_emits_warning(caplog) -> None:
    """force_greedy=True on a profile with temperature>0 must emit WARNING."""
    with caplog.at_level(logging.WARNING):
        _resolve_gen_kwargs("hy_mt_precise_sentence", True, 128, [])
    assert any("force_greedy" in r.message or "overrides" in r.message for r in caplog.records)


# ============================================================================
# WorkerRequest — backwards compatibility
# ============================================================================


def test_worker_request_without_sampling_profile_id() -> None:
    """Constructing WorkerRequest without sampling_profile_id must still work."""
    req = WorkerRequest(text="שלום", source_lang="he", target_lang="ru")
    assert req.sampling_profile_id == ""


def test_worker_request_with_sampling_profile_id() -> None:
    req = WorkerRequest(
        text="שלום",
        source_lang="he",
        target_lang="ru",
        sampling_profile_id="hy_mt_precise_sentence",
    )
    assert req.sampling_profile_id == "hy_mt_precise_sentence"


def test_worker_request_default_is_empty_string() -> None:
    req = WorkerRequest(text="x", source_lang="he", target_lang="ru")
    assert req.sampling_profile_id == ""


# ============================================================================
# _translate_transformers_causal — signature inspection (no torch)
# ============================================================================


def test_translate_causal_accepts_sampling_profile_id_param() -> None:
    sig = inspect.signature(_translate_transformers_causal)
    assert "sampling_profile_id" in sig.parameters


def test_translate_causal_sampling_profile_id_has_default() -> None:
    sig = inspect.signature(_translate_transformers_causal)
    param = sig.parameters["sampling_profile_id"]
    assert param.default == ""


# ============================================================================
# Default profile ID constant
# ============================================================================


def test_default_profile_id_is_precise_sentence() -> None:
    assert _WORKER_DEFAULT_SAMPLING_PROFILE_ID == "hy_mt_precise_sentence"


def test_default_profile_id_exists_in_profiles() -> None:
    assert _WORKER_DEFAULT_SAMPLING_PROFILE_ID in _WORKER_SAMPLING_PROFILES
