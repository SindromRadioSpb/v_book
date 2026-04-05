"""Tests for LightBlueTTS local audio provider."""

from __future__ import annotations

import io
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.infra.audio.audio_provider_config import AudioProviderConfig
from app.infra.audio.base_provider import AudioErrorKind, AudioGenerationRequest
from app.infra.audio.local_providers_setup import register_default_audio_providers
from app.infra.audio.providers.lightblue_tts_local_provider import (
    LightBlueTTSLocalProvider,
    _adaptive_synth_params,
    _count_ipa_phonemes,
    _extract_g2p_word,
    _has_vowels,
    _is_single_word,
    _PHONEME_SHORT_THRESHOLD,
    _PHONEME_MID_THRESHOLD,
    _STEPS_SHORT,
    _STEPS_MID,
    _STEPS_DEFAULT,
    _CFG_SHORT,
    _CFG_MID,
    _CFG_DEFAULT,
    _MIN_PHONEME_THRESHOLD,
)
from app.infra.audio.providers._he_ipa import hebrew_to_ipa
from app.infra.audio.providers_registry import AudioProvidersRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeSettings:
    """Minimal settings stub."""

    def __init__(
        self, *, license_accepted: bool = True, enabled: bool = True, model_path: str = ""
    ):
        self._license = license_accepted
        self._enabled = enabled
        self._model_path = model_path

    def get_bool(self, key: str, default: bool = False) -> bool:
        if "license_accepted" in key:
            return self._license
        if key.endswith("/enabled"):
            return self._enabled
        return default

    def get_string(self, key: str, default: str = "") -> str:
        if "model_path" in key:
            return self._model_path
        return default

    def get_int(self, key: str, default: int = 0) -> int:
        return default

    def get_json(self, key: str, default=None):
        return default


class _FakeConfigManager:
    def __init__(self, *, enabled: bool = True, model_path: str | None = None) -> None:
        self._enabled = enabled
        self._model_path = model_path

    def load_config(self, provider_id: str) -> AudioProviderConfig:
        return AudioProviderConfig(
            provider_id=provider_id,
            enabled=self._enabled,
            model_path=self._model_path,
        )


def _make_provider(
    *,
    license_accepted: bool = True,
    enabled: bool = True,
    model_path: str | None = None,
) -> LightBlueTTSLocalProvider:
    p = LightBlueTTSLocalProvider(
        config_manager=_FakeConfigManager(enabled=enabled, model_path=model_path)
    )
    p._settings = _FakeSettings(license_accepted=license_accepted, enabled=enabled)
    p._model_cache.clear()
    return p


def _minimal_request(text: str = "שָׁלוֹם", speed: float = 1.0) -> AudioGenerationRequest:
    return AudioGenerationRequest(
        source_text=text,
        source_lang="he",
        source_norm=text,
        speed=speed,
    )


def _make_fake_wav(sample_rate: int = 22050, duration_frames: int = 2048) -> tuple[np.ndarray, int]:
    """Return a numpy float32 array and sample_rate as a fake synthesis result."""
    arr = np.zeros(duration_frames, dtype=np.float32)
    return arr, sample_rate


@pytest.fixture(autouse=True)
def _reset_registry():
    AudioProvidersRegistry.reset()
    yield
    AudioProvidersRegistry.reset()


# ---------------------------------------------------------------------------
# T1 — Registry / provider registration
# ---------------------------------------------------------------------------


def test_lightblue_tts_registers_correctly():
    register_default_audio_providers()
    registry = AudioProvidersRegistry()
    provider = registry.get("lightblue_tts")
    assert provider is not None
    assert provider.provider_id == "lightblue_tts"
    assert provider.is_local is True
    assert "lightblue_tts" in registry.list_provider_ids()


def test_lightblue_tts_not_in_default_chain_registration():
    """lightblue_tts must not appear in the auto-registered DEFAULT_CHAIN."""
    from app.services.audio_generation_service import AudioGenerationService

    assert "lightblue_tts" not in AudioGenerationService.DEFAULT_CHAIN


# ---------------------------------------------------------------------------
# T2 — License gate blocks synthesis
# ---------------------------------------------------------------------------


def test_generate_blocked_without_license_accepted():
    provider = _make_provider(license_accepted=False)
    result = provider.generate(_minimal_request())
    assert not result.is_success
    assert result.error_kind == AudioErrorKind.UNSUPPORTED
    assert "license" in (result.error_message or "").lower()


# ---------------------------------------------------------------------------
# T3 — Disabled provider path
# ---------------------------------------------------------------------------


def test_generate_blocked_when_disabled():
    provider = _make_provider(license_accepted=True, enabled=False)
    result = provider.generate(_minimal_request())
    assert not result.is_success
    assert result.error_kind == AudioErrorKind.UNSUPPORTED
    assert "disabled" in (result.error_message or "").lower()


# ---------------------------------------------------------------------------
# T4 — Missing dependency (lightblue_onnx)
# ---------------------------------------------------------------------------


def test_generate_fails_on_missing_lightblue_dep(tmp_path):
    (tmp_path / "vocoder.onnx").touch()
    (tmp_path / "voices").mkdir()
    (tmp_path / "voices" / "female1.json").write_text("{}")

    provider = _make_provider(model_path=str(tmp_path))

    import builtins

    real_import = builtins.__import__

    def _block_lightblue(name, *args, **kwargs):
        if name == "lightblue_onnx":
            raise ImportError("lightblue_onnx not installed (test block)")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_block_lightblue):
        result = provider.generate(_minimal_request())

    assert not result.is_success
    assert result.error_kind == AudioErrorKind.UNSUPPORTED
    assert "dependencies missing" in (result.error_message or "").lower()


# ---------------------------------------------------------------------------
# T5 — Missing model path
# ---------------------------------------------------------------------------


def test_generate_fails_on_missing_model_path(tmp_path):
    nonexistent = str(tmp_path / "does_not_exist")
    provider = _make_provider(model_path=nonexistent)
    result = provider.generate(_minimal_request())
    assert not result.is_success
    assert result.error_kind == AudioErrorKind.INVALID_REQUEST
    assert "not found" in (result.error_message or "").lower()


def test_generate_fails_on_missing_style_file(tmp_path):
    """Model dir exists but voices/female1.json is absent."""
    (tmp_path / "vocoder.onnx").touch()
    provider = _make_provider(model_path=str(tmp_path))
    result = provider.generate(_minimal_request())
    assert not result.is_success
    assert result.error_kind == AudioErrorKind.INVALID_REQUEST
    assert "style" in (result.error_message or "").lower()


# ---------------------------------------------------------------------------
# T6 — Happy path with mocked synthesis
# ---------------------------------------------------------------------------


def _build_style_json(tmp_path: Path) -> Path:
    """Create a minimal style JSON for testing."""
    import json

    voices_dir = tmp_path / "voices"
    voices_dir.mkdir(exist_ok=True)
    style = {"style_ttl": {"data": [[0.0] * 64], "shape": [1, 64]}}
    p = voices_dir / "female1.json"
    p.write_text(json.dumps(style))
    return p


def test_generate_returns_valid_wav(tmp_path):
    """Happy path: mock _synthesize to return fake WAV bytes."""
    _build_style_json(tmp_path)
    provider = _make_provider(model_path=str(tmp_path))

    fake_sr = 22050
    fake_audio, _ = _make_fake_wav(sample_rate=fake_sr)

    # Build expected WAV bytes inline (what _synthesize would return)
    import numpy as np  # noqa: PLC0415

    pcm = (np.clip(fake_audio, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fake_sr)
        w.writeframes(pcm.tobytes())
    fake_wav_bytes = buf.getvalue()

    with patch.object(provider, "_synthesize", return_value=(fake_wav_bytes, fake_sr)):
        result = provider.generate(_minimal_request())

    assert result.is_success, f"expected success, got: {result.error_message}"
    assert result.provider_id == "lightblue_tts"
    assert result.mime_type == "audio/wav"
    assert result.audio_bytes[:4] == b"RIFF"
    assert result.meta.get("sample_rate", 0) > 0

    buf2 = io.BytesIO(result.audio_bytes)
    with wave.open(buf2) as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == fake_sr


# ---------------------------------------------------------------------------
# T7 — Empty input guard
# ---------------------------------------------------------------------------


def test_generate_empty_text_returns_invalid_request():
    provider = _make_provider()
    result = provider.generate(_minimal_request(text=""))
    assert not result.is_success
    assert result.error_kind == AudioErrorKind.INVALID_REQUEST


def test_generate_whitespace_only_returns_invalid_request():
    provider = _make_provider()
    result = provider.generate(_minimal_request(text="   "))
    assert not result.is_success
    assert result.error_kind == AudioErrorKind.INVALID_REQUEST


# ---------------------------------------------------------------------------
# T8 — Speed parameter smoke (0.5x and 2.0x)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("speed", [0.5, 2.0])
def test_speed_parameter_does_not_crash(tmp_path, speed):
    """Speed values 0.5x and 2.0x must not crash the provider."""
    _build_style_json(tmp_path)
    provider = _make_provider(model_path=str(tmp_path), enabled=True)

    fake_wav = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x22\x56\x00\x00\x44\xac\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"

    with patch.object(provider, "_synthesize", return_value=(fake_wav, 22050)):
        result = provider.generate(_minimal_request(speed=speed))

    assert result.is_success, f"speed={speed}: {result.error_message}"


# ---------------------------------------------------------------------------
# T9 — Existing provider regression
# ---------------------------------------------------------------------------


def test_mock_local_audio_unaffected_after_lightblue_registration():
    register_default_audio_providers()
    registry = AudioProvidersRegistry()
    mock_provider = registry.get("mock_local_audio")
    assert mock_provider is not None
    req = AudioGenerationRequest(
        source_text="test",
        source_lang="he",
        source_norm="test",
    )
    result = mock_provider.generate(req)
    assert result.is_success, f"mock_local_audio regression: {result.error_message}"


def test_all_original_providers_still_registered():
    register_default_audio_providers()
    ids = set(AudioProvidersRegistry().list_provider_ids())
    for expected in (
        "google_cloud_tts",
        "azure_speech_tts",
        "mms_tts_local",
        "mock_local_audio",
        "mock_online_audio",
    ):
        assert expected in ids, f"Missing provider after lightblue registration: {expected}"


# ---------------------------------------------------------------------------
# T10 — Health check item
# ---------------------------------------------------------------------------


def test_health_check_returns_optional_when_disabled():
    from app.services.health_check_service import HealthCheckService

    svc = HealthCheckService.__new__(HealthCheckService)
    svc.settings = _FakeSettings(license_accepted=False, enabled=False)
    item = svc._check_lightblue_tts()
    assert item.check_id == "bootstrap:lightblue_tts"
    assert item.status == "optional"


def test_health_check_returns_warn_when_no_license():
    from app.services.health_check_service import HealthCheckService

    svc = HealthCheckService.__new__(HealthCheckService)
    svc.settings = _FakeSettings(license_accepted=False, enabled=True)
    item = svc._check_lightblue_tts()
    assert item.check_id == "bootstrap:lightblue_tts"
    assert item.status == "warn"
    assert "license" in item.message.lower()


def test_health_check_returns_error_on_missing_dep(monkeypatch):
    from app.services.health_check_service import HealthCheckService
    import builtins

    real_import = builtins.__import__

    def _block(name, *args, **kwargs):
        if name == "lightblue_onnx":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    svc = HealthCheckService.__new__(HealthCheckService)
    svc.settings = _FakeSettings(license_accepted=True, enabled=True)

    with monkeypatch.context() as m:
        m.setattr("builtins.__import__", _block)
        item = svc._check_lightblue_tts()

    assert item.status == "error"
    assert "lightblue_onnx" in item.message.lower()


def test_health_check_ok_with_models_present(tmp_path):
    """Full ok path: deps present, license accepted, model dir + style exist."""
    import json as _json
    import sys
    from unittest.mock import MagicMock
    from app.services.health_check_service import HealthCheckService

    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / "female1.json").write_text(_json.dumps({"style_ttl": {"data": [], "shape": []}}))

    svc = HealthCheckService.__new__(HealthCheckService)
    svc.settings = _FakeSettings(license_accepted=True, enabled=True, model_path=str(tmp_path))

    # Provide mock modules to avoid DLL load issues from prior import-block tests.
    fake_lbt = MagicMock()
    fake_phonikud = MagicMock()
    with patch.dict(sys.modules, {"lightblue_onnx": fake_lbt, "phonikud_onnx": fake_phonikud}):
        item = svc._check_lightblue_tts()

    assert item.check_id == "bootstrap:lightblue_tts"
    assert item.status == "ok"


# ---------------------------------------------------------------------------
# T11 — Config persistence
# ---------------------------------------------------------------------------


def test_config_loaded_with_model_path(tmp_path):
    mgr = _FakeConfigManager(enabled=True, model_path=str(tmp_path))
    cfg = mgr.load_config("lightblue_tts")
    assert cfg.enabled is True
    assert cfg.model_path == str(tmp_path)


def test_config_disabled_reflects_in_generate():
    provider = _make_provider(license_accepted=True, enabled=False)
    result = provider.generate(_minimal_request())
    assert not result.is_success
    assert result.error_kind == AudioErrorKind.UNSUPPORTED


# ---------------------------------------------------------------------------
# _he_ipa unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("שָׁלוֹם", "ʃalom"),
        ("תּוֹדָה", "todah"),
        ("אֲנִי", "ʔani"),
        ("מַיִם", "majim"),
        ("בַּיִת", "bajit"),
        ("יוֹם", "jom"),
        ("שָׁלוֹם, עוֹלָם!", "ʃalom, ʔolam!"),
        ("", ""),
    ],
)
def test_he_ipa_known_words(text, expected):
    assert hebrew_to_ipa(text) == expected


def test_he_ipa_no_niqqud_passthrough():
    """Without niqqud, consonants are returned with no vowels."""
    result = hebrew_to_ipa("שלום")
    assert result == "ʃlvm"


def test_he_ipa_returns_string():
    assert isinstance(hebrew_to_ipa("שָׁלוֹם"), str)


def test_he_ipa_empty_input():
    assert hebrew_to_ipa("") == ""


# ---------------------------------------------------------------------------
# T12 — _normalize_audio_loudness
# ---------------------------------------------------------------------------

_TARGET_RMS = 0.08
_TARGET_PEAK = 0.92


def _sine(
    sr: int = 44100, freq: float = 440.0, duration: float = 1.0, amp: float = 0.01
) -> np.ndarray:
    t = np.linspace(0, duration, int(sr * duration), endpoint=False, dtype=np.float32)
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _rms(arr: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(arr.astype(np.float64)))))


def test_normalize_rms_within_target_range():
    """After normalization a quiet signal RMS lands near target_rms."""
    result = LightBlueTTSLocalProvider._normalize_audio_loudness(_sine(amp=0.005))
    assert 0.05 <= _rms(result) <= 0.11


def test_normalize_peak_never_exceeds_target_peak():
    """Peak must not exceed target_peak regardless of input amplitude."""
    result = LightBlueTTSLocalProvider._normalize_audio_loudness(_sine(amp=0.005))
    assert float(np.max(np.abs(result))) <= _TARGET_PEAK + 1e-6


def test_normalize_empty_signal_returns_empty():
    empty = np.zeros(0, dtype=np.float32)
    result = LightBlueTTSLocalProvider._normalize_audio_loudness(empty)
    assert result.size == 0


def test_normalize_silent_signal_unchanged():
    silent = np.zeros(4096, dtype=np.float32)
    result = LightBlueTTSLocalProvider._normalize_audio_loudness(silent)
    assert np.allclose(result, 0.0)


def test_normalize_already_at_target_no_significant_amplification():
    """Signal already at target RMS must not be amplified (gain <= 1.05)."""
    # Sine amplitude for RMS == target_rms: amp = target_rms * sqrt(2)
    amp = _TARGET_RMS * np.sqrt(2)
    signal = _sine(amp=amp)
    result = LightBlueTTSLocalProvider._normalize_audio_loudness(signal)
    np.testing.assert_allclose(result, signal, rtol=0.02)


def test_normalize_no_clipping_on_typical_tts_output():
    """Moderate-amplitude signal must produce no hard-clipped samples."""
    signal = _sine(amp=0.2, duration=0.5)
    result = LightBlueTTSLocalProvider._normalize_audio_loudness(signal)
    clipped = np.sum(np.abs(result) >= _TARGET_PEAK)
    total = result.size
    # Allow at most 0.1% clipped samples (expect zero for a pure sine)
    assert clipped / total < 0.001


def test_normalize_cross_voice_loudness_within_tolerance():
    """Two quiet signals in the normalizable range converge to similar RMS.

    Signals with amp >= ~0.005 don't hit max_gain=24 and should both be pulled
    up to ≈ target_rms=0.08.  Very-quiet signals (amp < 0.004) hit max_gain and
    cannot reach target; they are NOT tested here — see test_normalize_rms_within.

    The function only amplifies (conservative gain): quiet signals are pulled up
    toward target_rms; loud signals (RMS already ≥ target) are left unchanged.
    """
    # Both in normalizable range → should converge to ~target_rms
    r_a = LightBlueTTSLocalProvider._normalize_audio_loudness(_sine(amp=0.01))
    r_b = LightBlueTTSLocalProvider._normalize_audio_loudness(_sine(amp=0.03))
    assert abs(_rms(r_a) - _rms(r_b)) < 0.015

    # A loud signal (RMS already above target) stays untouched (gain < 1.05)
    loud = _sine(amp=0.15)
    r_loud = LightBlueTTSLocalProvider._normalize_audio_loudness(loud)
    np.testing.assert_allclose(r_loud, loud, rtol=0.01)


# ---------------------------------------------------------------------------
# T13 — _apply_g2p fallback chain
# ---------------------------------------------------------------------------


def _make_fake_phonikud_onnx(result: str | None = "שָׁלוֹם") -> MagicMock:
    m = MagicMock()
    m.add_diacritics.return_value = result
    return m


def test_apply_g2p_uses_phonikud_onnx_when_pkg_missing(monkeypatch):
    """Without phonikud package, falls back to phonikud_onnx."""
    monkeypatch.delitem(__import__("sys").modules, "phonikud", raising=False)
    ph = _make_fake_phonikud_onnx("שָׁלוֹם")
    text, branch = LightBlueTTSLocalProvider._apply_g2p("שלום", ph)
    assert branch == "phonikud_onnx"
    assert text == "שָׁלוֹם"
    ph.add_diacritics.assert_called_once_with("שלום")


def test_apply_g2p_uses_phonikud_pkg_add_niqqud_when_available(monkeypatch):
    """phonikud.add_niqqud is preferred over phonikud_onnx when callable."""
    fake_pkg = MagicMock()
    fake_pkg.add_nikud = None  # not callable → skip
    fake_pkg.add_niqqud = MagicMock(return_value="שָׁלוֹם_pkg")
    monkeypatch.setitem(__import__("sys").modules, "phonikud", fake_pkg)
    ph = _make_fake_phonikud_onnx("שָׁלוֹם_onnx")
    text, branch = LightBlueTTSLocalProvider._apply_g2p("שלום", ph)
    assert branch == "phonikud.add_niqqud"
    assert text == "שָׁלוֹם_pkg"
    ph.add_diacritics.assert_not_called()


def test_apply_g2p_falls_through_on_pkg_exception(monkeypatch):
    """If phonikud pkg raises, silently falls through to phonikud_onnx."""
    fake_pkg = MagicMock()
    fake_pkg.add_nikud = MagicMock(side_effect=RuntimeError("boom"))
    fake_pkg.add_niqqud = MagicMock(side_effect=RuntimeError("boom"))
    fake_pkg.add_diacritics = MagicMock(side_effect=RuntimeError("boom"))
    monkeypatch.setitem(__import__("sys").modules, "phonikud", fake_pkg)
    ph = _make_fake_phonikud_onnx("שָׁלוֹם_onnx")
    text, branch = LightBlueTTSLocalProvider._apply_g2p("שלום", ph)
    assert branch == "phonikud_onnx"
    assert text == "שָׁלוֹם_onnx"


def test_apply_g2p_falls_back_to_raw_when_all_fail(monkeypatch):
    """Returns raw text and 'raw_text' branch when every G2P option fails."""
    monkeypatch.delitem(__import__("sys").modules, "phonikud", raising=False)
    ph = _make_fake_phonikud_onnx(None)  # add_diacritics returns None
    ph.add_diacritics.side_effect = RuntimeError("onnx broken")
    text, branch = LightBlueTTSLocalProvider._apply_g2p("שלום", ph)
    assert branch == "raw_text"
    assert text == "שלום"


def test_apply_g2p_returns_raw_when_onnx_returns_empty(monkeypatch):
    """Empty string from phonikud_onnx is treated as failure → raw_text."""
    monkeypatch.delitem(__import__("sys").modules, "phonikud", raising=False)
    ph = _make_fake_phonikud_onnx("")  # empty result
    text, branch = LightBlueTTSLocalProvider._apply_g2p("שלום", ph)
    assert branch == "raw_text"
    assert text == "שלום"


# ---------------------------------------------------------------------------
# T14 — Helper functions: _is_single_word
# ---------------------------------------------------------------------------


def test_is_single_word_true_for_single_token():
    assert _is_single_word("שלום") is True
    assert _is_single_word("מהירות") is True
    assert _is_single_word("כאשר") is True


def test_is_single_word_false_for_multi_word():
    assert _is_single_word("שלום עולם") is False
    assert _is_single_word("שתי מילים") is False


def test_is_single_word_false_for_empty():
    assert _is_single_word("") is False
    assert _is_single_word("   ") is False


# ---------------------------------------------------------------------------
# T15 — Helper functions: _adaptive_synth_params
# ---------------------------------------------------------------------------


def test_adaptive_synth_params_short_word():
    """Word with <= 5 Hebrew letters → SHORT params."""
    # כאשר = 4 letters → est = 6 < threshold 8 → SHORT
    steps, cfg = _adaptive_synth_params("כאשר")
    assert steps == _STEPS_SHORT
    assert cfg == _CFG_SHORT


def test_adaptive_synth_params_medium_word():
    """Word with ~6-10 Hebrew letters → MID params."""
    # מהירות = 6 letters → est = 9, between 8 and 16 → MID
    steps, cfg = _adaptive_synth_params("מהירות")
    assert steps == _STEPS_MID
    assert cfg == _CFG_MID


def test_adaptive_synth_params_long_sentence():
    """Long sentence with many letters → DEFAULT params."""
    sentence = "התהליך כולל חימום לטמפרטורה מבוקרת ולאחר מכן קירור מהיר"
    steps, cfg = _adaptive_synth_params(sentence)
    assert steps == _STEPS_DEFAULT
    assert cfg == _CFG_DEFAULT


def test_adaptive_synth_params_non_hebrew_text():
    """Non-Hebrew text (no Hebrew letters) → SHORT (est=1)."""
    steps, cfg = _adaptive_synth_params("hello")
    assert steps == _STEPS_SHORT  # est=1 < _PHONEME_SHORT_THRESHOLD


# ---------------------------------------------------------------------------
# T16 — Helper functions: _count_ipa_phonemes and _has_vowels
# ---------------------------------------------------------------------------


def test_count_ipa_phonemes_with_vowels():
    assert _count_ipa_phonemes("ʃalom") == 5
    assert _count_ipa_phonemes("mehirut") == 7


def test_count_ipa_phonemes_consonants_only():
    # Consonants only (no vowels) — still counts correctly
    assert _count_ipa_phonemes("ʃlm") == 3


def test_count_ipa_phonemes_empty():
    assert _count_ipa_phonemes("") == 0
    assert _count_ipa_phonemes("   ") == 0


def test_count_ipa_phonemes_with_punctuation():
    # Punctuation and spaces not counted
    assert _count_ipa_phonemes("ʃalom, ʔolam!") == 10


def test_has_vowels_true():
    assert _has_vowels("ʃalom") is True
    assert _has_vowels("mehirut") is True
    assert _has_vowels("a") is True


def test_has_vowels_false_consonants_only():
    assert _has_vowels("ʃlm") is False
    assert _has_vowels("kʃr") is False
    assert _has_vowels("tvbr") is False


# ---------------------------------------------------------------------------
# T17 — Helper functions: _extract_g2p_word
# ---------------------------------------------------------------------------


def test_extract_g2p_word_standard_case():
    """Standard format: prefix + space + niqqud_word + dot."""
    result = _extract_g2p_word("הַמִּילָה מְהִירוּת.", "מהירות")
    assert result == "מְהִירוּת"


def test_extract_g2p_word_no_trailing_dot():
    """No trailing dot — should still extract correctly."""
    result = _extract_g2p_word("הַמִּילָה כַּאֲשֶׁר", "כאשר")
    assert result == "כַּאֲשֶׁר"


def test_extract_g2p_word_fallback_when_no_space():
    """If no space in result, returns original word."""
    result = _extract_g2p_word("גוש", "גוש")
    # No space → fallback to original
    assert result == "גוש"


# ---------------------------------------------------------------------------
# T18 — Quality corpus: hebrew_to_ipa for problematic user-reported words
# ---------------------------------------------------------------------------
# These words are reported as producing bad TTS output.
# With niqqud added by G2P, hebrew_to_ipa should produce vowel-containing IPA.
# These tests use mocked niqqud (simulating what good phonikud output looks like).


_NIQQUD_CORPUS = [
    # (raw_word, expected_niqqud_form, expected_ipa_has_vowels, min_phoneme_count)
    # H1 group: user-reported problematic words (with correct niqqud)
    ("רבות", "רַבּוֹת", True, 4),  # ravot — "many" (feminine)
    ("מהירות", "מְהִירוּת", True, 6),  # mehirut — "speed"
    ("כאשר", "כַּאֲשֶׁר", True, 5),  # ka'asher — "when/as"
    # H2 group: user-confirmed working words
    ("עצוב", "עָצוּב", True, 4),  # atzuv — "sad"
    ("חיצוני", "חִיצוֹנִי", True, 5),  # khitsoni — "external"
    ("ינש", "יָנוּשׁ", True, 4),  # yanuish/yinsh
]


@pytest.mark.parametrize("raw,niqqud,expect_vowels,min_count", _NIQQUD_CORPUS)
def test_he_ipa_niqqud_quality(raw, niqqud, expect_vowels, min_count):
    """With proper niqqud, hebrew_to_ipa produces vowel-containing IPA."""
    ipa = hebrew_to_ipa(niqqud)
    assert (
        _has_vowels(ipa) == expect_vowels
    ), f"Expected has_vowels={expect_vowels} for niqqud={niqqud!r}, got IPA={ipa!r}"
    assert (
        _count_ipa_phonemes(ipa) >= min_count
    ), f"Expected >= {min_count} phonemes for niqqud={niqqud!r}, got {_count_ipa_phonemes(ipa)} (IPA={ipa!r})"


_RAW_CONSONANT_CORPUS = [
    # Without niqqud → consonant-only IPA (known degraded path)
    ("רבות", False),
    ("מהירות", False),
    ("כאשר", False),
]


@pytest.mark.parametrize("raw,expect_vowels", _RAW_CONSONANT_CORPUS)
def test_he_ipa_no_niqqud_consonant_only(raw, expect_vowels):
    """Without niqqud, hebrew_to_ipa produces consonant-only IPA (known issue)."""
    ipa = hebrew_to_ipa(raw)
    assert (
        _has_vowels(ipa) == expect_vowels
    ), f"Expected has_vowels={expect_vowels} for raw={raw!r}, got IPA={ipa!r}"


# ---------------------------------------------------------------------------
# T19 — Quality corpus: working sentences non-regression
# ---------------------------------------------------------------------------


_SENTENCE_CORPUS = [
    "סגסוגת זו מורכבת מברזל ופחמן",
    "התהליך כולל חימום לטמפרטורה מבוקרת ולאחר מכן קירור מהיר",
    "באחוזים מדויקים",
]


@pytest.mark.parametrize("sentence", _SENTENCE_CORPUS)
def test_sentence_adaptive_params_use_default_or_mid(sentence):
    """Sentences with many Hebrew letters use DEFAULT or MID diffusion params."""
    steps, _ = _adaptive_synth_params(sentence)
    # Sentences should NOT use SHORT (steps=48), which is reserved for very short inputs
    assert steps in (
        _STEPS_DEFAULT,
        _STEPS_MID,
    ), f"Sentence {sentence!r} should use default/mid params, got steps={steps}"


# ---------------------------------------------------------------------------
# T20 — Context-wrap integration in _synthesize_phonemes
# ---------------------------------------------------------------------------


def _make_fake_phonikud_onnx_quality(niqqud_result: str) -> MagicMock:
    ph = MagicMock()
    ph.add_diacritics = MagicMock(return_value=niqqud_result)
    return ph


def test_synthesize_phonemes_context_wrap_applied_for_single_word(monkeypatch, caplog):
    """Single word: context wrap is applied; G2P receives wrapped input."""
    import logging

    monkeypatch.delitem(__import__("sys").modules, "phonikud", raising=False)

    captured_g2p_inputs: list[str] = []

    def _fake_apply_g2p(text, ph):
        captured_g2p_inputs.append(text)
        # Simulate phonikud returning niqqud for wrapped input
        return f"הַמִּילָה מְהִירוּת.", "phonikud_onnx"

    monkeypatch.setattr(LightBlueTTSLocalProvider, "_apply_g2p", staticmethod(_fake_apply_g2p))

    fake_tts = MagicMock()
    fake_tts.create = MagicMock(return_value=_make_fake_wav())

    provider = _make_provider()
    with caplog.at_level(
        logging.INFO, logger="app.infra.audio.providers.lightblue_tts_local_provider"
    ):
        provider._synthesize_phonemes(
            text="מהירות",
            tts_model=fake_tts,
            phonikud_instance=MagicMock(),
            phonemize_fn=hebrew_to_ipa,
            phonemize_path="hebrew_to_ipa",
        )

    # Verify the wrapper was prepended to G2P input
    assert len(captured_g2p_inputs) == 1
    assert captured_g2p_inputs[0].startswith("המילה ")
    assert captured_g2p_inputs[0].endswith(".")


def test_synthesize_phonemes_no_wrap_for_multi_word(monkeypatch):
    """Multi-word input: context wrap is NOT applied."""
    monkeypatch.delitem(__import__("sys").modules, "phonikud", raising=False)

    captured_g2p_inputs: list[str] = []

    def _fake_apply_g2p(text, ph):
        captured_g2p_inputs.append(text)
        return text, "phonikud_onnx"

    monkeypatch.setattr(LightBlueTTSLocalProvider, "_apply_g2p", staticmethod(_fake_apply_g2p))

    fake_tts = MagicMock()
    fake_tts.create = MagicMock(return_value=_make_fake_wav())

    provider = _make_provider()
    provider._synthesize_phonemes(
        text="שתי מילים",
        tts_model=fake_tts,
        phonikud_instance=MagicMock(),
        phonemize_fn=hebrew_to_ipa,
        phonemize_path="hebrew_to_ipa",
    )

    assert captured_g2p_inputs[0] == "שתי מילים"  # no wrap


def test_synthesize_phonemes_short_phoneme_warning(monkeypatch, caplog):
    """Phoneme count below threshold triggers a WARNING."""
    import logging

    monkeypatch.delitem(__import__("sys").modules, "phonikud", raising=False)

    # Disable context-wrap so the single-letter text is not inflated by the wrapper,
    # which would otherwise produce a longer IPA string masking the short-phoneme warning.
    monkeypatch.setattr(
        "app.infra.audio.providers.lightblue_tts_local_provider._ENABLE_CONTEXT_WRAP",
        False,
    )

    def _fake_apply_g2p(text, ph):
        return "ב", "raw_text"  # return single consonant letter regardless of input

    monkeypatch.setattr(LightBlueTTSLocalProvider, "_apply_g2p", staticmethod(_fake_apply_g2p))

    fake_tts = MagicMock()
    fake_tts.create = MagicMock(return_value=_make_fake_wav())

    provider = _make_provider()
    with caplog.at_level(
        logging.WARNING, logger="app.infra.audio.providers.lightblue_tts_local_provider"
    ):
        provider._synthesize_phonemes(
            text="ב",  # single letter → 1 consonant phoneme
            tts_model=fake_tts,
            phonikud_instance=MagicMock(),
            phonemize_fn=hebrew_to_ipa,
            phonemize_path="hebrew_to_ipa",
        )

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("short phoneme sequence" in w for w in warnings)


def test_synthesize_phonemes_consonant_only_warning(monkeypatch, caplog):
    """Consonant-only IPA string triggers a WARNING."""
    import logging

    monkeypatch.delitem(__import__("sys").modules, "phonikud", raising=False)

    # Disable context-wrap so the 3-letter word is passed directly to G2P
    # without inflation, ensuring a consonant-only IPA is produced.
    monkeypatch.setattr(
        "app.infra.audio.providers.lightblue_tts_local_provider._ENABLE_CONTEXT_WRAP",
        False,
    )

    def _fake_apply_g2p(text, ph):
        return "גבר", "raw_text"  # return 3 consonants without niqqud

    monkeypatch.setattr(LightBlueTTSLocalProvider, "_apply_g2p", staticmethod(_fake_apply_g2p))

    fake_tts = MagicMock()
    fake_tts.create = MagicMock(return_value=_make_fake_wav())

    provider = _make_provider()
    # "גבר" without niqqud → hebrew_to_ipa gives consonants only (count < 6)
    with caplog.at_level(
        logging.WARNING, logger="app.infra.audio.providers.lightblue_tts_local_provider"
    ):
        provider._synthesize_phonemes(
            text="גבר",
            tts_model=fake_tts,
            phonikud_instance=MagicMock(),
            phonemize_fn=hebrew_to_ipa,
            phonemize_path="hebrew_to_ipa",
        )

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("consonant-only" in w for w in warnings)


def test_synthesize_phonemes_info_logging(monkeypatch, caplog):
    """INFO logs include niqqud text and phoneme string."""
    import logging

    monkeypatch.delitem(__import__("sys").modules, "phonikud", raising=False)

    def _fake_apply_g2p(text, ph):
        return "שָׁלוֹם", "phonikud_onnx"

    monkeypatch.setattr(LightBlueTTSLocalProvider, "_apply_g2p", staticmethod(_fake_apply_g2p))

    fake_tts = MagicMock()
    fake_tts.create = MagicMock(return_value=_make_fake_wav())

    provider = _make_provider()
    with caplog.at_level(
        logging.INFO, logger="app.infra.audio.providers.lightblue_tts_local_provider"
    ):
        provider._synthesize_phonemes(
            text="שלום",
            tts_model=fake_tts,
            phonikud_instance=MagicMock(),
            phonemize_fn=hebrew_to_ipa,
            phonemize_path="hebrew_to_ipa",
        )

    info_messages = [r.message for r in caplog.records if r.levelno == logging.INFO]
    # G2P info log
    assert any("G2P branch" in m for m in info_messages)
    # Phonemize info log
    assert any("phonemize_path" in m for m in info_messages)


# ---------------------------------------------------------------------------
# T21 — Audio metrics regression
# ---------------------------------------------------------------------------


def test_normalize_audio_loudness_rms_in_range():
    """Normalized audio RMS lands between 0.02 and 0.15."""
    audio = np.random.uniform(-0.1, 0.1, 44100).astype(np.float32)
    result = LightBlueTTSLocalProvider._normalize_audio_loudness(audio)
    rms = float(np.sqrt(np.mean(np.square(result, dtype=np.float64))))
    assert 0.02 <= rms <= 0.15, f"RMS out of range: {rms}"


def test_normalize_audio_loudness_peak_bounded():
    """Peak of normalized audio never exceeds target_peak."""
    audio = np.random.uniform(-0.05, 0.05, 44100).astype(np.float32)
    result = LightBlueTTSLocalProvider._normalize_audio_loudness(audio, target_peak=0.92)
    peak = float(np.max(np.abs(result)))
    assert peak <= 0.92 + 1e-6, f"Peak exceeded target: {peak}"


# ---------------------------------------------------------------------------
# T22 — Mater lectionis ו and mobile shva fixes in hebrew_to_ipa
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "niqqud, expected_ipa, label",
    [
        # Mater lectionis fix: ו after holam → silent (not /v/)
        ("חֹומֶר", "χomeʁ", "חומר holam-male vav silent"),
        ("כֹּול", "kol", "כול dagesh+holam+male vav silent"),
        # Mobile shva fix: shva before guttural → /e/
        ("לְאַחֵר", "leʔaχeʁ", "לאחר mobile shva before alef"),
        ("לְאֹורֶךְ", "leʔoʁeχ", "לאורך mobile shva before alef + mater lectionis"),
        # Regressions — fixes must NOT affect correctly handled forms
        ("הוֹסִיף", "hosif", "הוסיף vav+holam = /o/ unaffected"),
        ("מִבְנֶה", "mivneh", "מבנה shva before non-guttural stays silent"),
        ("שֶׁל", "ʃel", "של unchanged"),
        ("הוּא", "huʔ", "הוא shuruk unaffected"),
        ("עַל", "ʔal", "על unchanged"),
        ("רַב", "ʁav", "רב unchanged"),
    ],
)
def test_he_ipa_mater_lectionis_and_mobile_shva(niqqud, expected_ipa, label):
    """Mater lectionis ו and mobile shva produce correct IPA."""
    assert hebrew_to_ipa(niqqud) == expected_ipa, label


# ---------------------------------------------------------------------------
# T23 — Pipe-separator strip in _synthesize_phonemes
# ---------------------------------------------------------------------------


def test_synthesize_phonemes_pipe_stripped_from_niqqud(monkeypatch):
    """Phonikud pipe-separator '|' in G2P output is stripped before phonemization."""
    monkeypatch.delitem(__import__("sys").modules, "phonikud", raising=False)

    received_niqqud: list[str] = []

    def _tracking_phonemize(text: str) -> str:
        received_niqqud.append(text)
        return hebrew_to_ipa(text)

    def _fake_apply_g2p(text, ph):
        # Simulate phonikud returning pipe-separated result (e.g. prefix boundary)
        return "לְֽ|אַחֵר", "phonikud_onnx"

    monkeypatch.setattr(LightBlueTTSLocalProvider, "_apply_g2p", staticmethod(_fake_apply_g2p))

    fake_tts = MagicMock()
    fake_tts.create = MagicMock(return_value=_make_fake_wav())

    provider = _make_provider()
    monkeypatch.setattr(
        "app.infra.audio.providers.lightblue_tts_local_provider._ENABLE_CONTEXT_WRAP",
        False,
    )
    provider._synthesize_phonemes(
        text="לאחר",
        tts_model=fake_tts,
        phonikud_instance=MagicMock(),
        phonemize_fn=_tracking_phonemize,
        phonemize_path="hebrew_to_ipa",
    )

    assert received_niqqud, "phonemize_fn was never called"
    assert (
        "|" not in received_niqqud[0]
    ), f"Pipe was NOT stripped before phonemization: {received_niqqud[0]!r}"


# ---------------------------------------------------------------------------
# T24 — Terminal period appended to IPA before synthesis
# ---------------------------------------------------------------------------


def test_synthesize_phonemes_terminal_period_added(monkeypatch):
    """IPA string passed to tts_model.create() always ends with '.'."""
    monkeypatch.delitem(__import__("sys").modules, "phonikud", raising=False)

    received_by_create: list[str] = []

    def _fake_create(phonemes: str):
        received_by_create.append(phonemes)
        return _make_fake_wav()

    def _fake_apply_g2p(text, ph):
        return "שֶׁל", "phonikud_onnx"

    monkeypatch.setattr(LightBlueTTSLocalProvider, "_apply_g2p", staticmethod(_fake_apply_g2p))

    fake_tts = MagicMock()
    fake_tts.create = MagicMock(side_effect=_fake_create)

    provider = _make_provider()
    monkeypatch.setattr(
        "app.infra.audio.providers.lightblue_tts_local_provider._ENABLE_CONTEXT_WRAP",
        False,
    )
    provider._synthesize_phonemes(
        text="של",
        tts_model=fake_tts,
        phonikud_instance=MagicMock(),
        phonemize_fn=hebrew_to_ipa,
        phonemize_path="hebrew_to_ipa",
    )

    assert received_by_create, "tts_model.create was never called"
    sent = received_by_create[0]
    assert sent.endswith("."), f"IPA passed to create() does not end with '.': {sent!r}"


# ---------------------------------------------------------------------------
# T25–T27 — phonikud.py shim phonemize() — Variant 1 subprocess delegation
# ---------------------------------------------------------------------------

_IPA_VOWELS = set("aeiouˈ")


class TestShimPhonemize:
    """T25: shim.phonemize is present and delegates to site-packages phonikud."""

    def test_phonemize_callable_on_shim(self):
        """phonemize function is exposed by the phonikud shim module."""
        import phonikud  # noqa: PLC0415

        assert callable(
            getattr(phonikud, "phonemize", None)
        ), "phonikud.phonemize must be a callable after Variant 1"

    @pytest.mark.parametrize(
        "niqqud_text,expected_contains",
        [
            # niqqud input → phonemize should return IPA with at least one vowel
            ("\u05e9\u05b6\u05dc", "e"),  # שֶׁל  → ʃˈel
            ("\u05d7\u05d5\u05de\u05b6\u05e8", "e"),  # חוֹמֶר → χˈmeʁ
            ("\u05db\u05b8\u05d0\u05b2\u05e9\u05b6\u05c1\u05e8", "a"),  # כָּאֲשֶׁר
            ("\u05dc\u05b0\u05d0\u05d5\u05b9\u05e8\u05b6\u05da", "o"),  # לְאוֹרֶךְ
            ("\u05d4\u05d5\u05bc\u05e1\u05b4\u05d9\u05e3", "u"),  # הוּסִיף
            ("\u05de\u05b0\u05d4\u05b4\u05d9\u05e8\u05d5\u05bc\u05ea", "i"),  # מְהִירוּת
            ("\u05e2\u05b7\u05dc", "a"),  # עַל → ʔˈal
        ],
        ids=[
            "shel",
            "chomer",
            "kaasher",
            "leorech",
            "hosif",
            "mehirut",
            "al",
        ],
    )
    def test_phonemize_returns_ipa_with_vowel(self, niqqud_text: str, expected_contains: str):
        """phonemize(niqqud_text) returns IPA containing the expected vowel."""
        import phonikud  # noqa: PLC0415

        result = phonikud.phonemize(niqqud_text)
        assert isinstance(result, str), "phonemize must return str"
        assert len(result) > 0, f"phonemize returned empty string for {niqqud_text!r}"
        assert expected_contains in result, (
            f"Expected IPA to contain {expected_contains!r} for {niqqud_text!r}, " f"got {result!r}"
        )

    def test_phonemize_empty_input_returns_empty(self):
        """phonemize('') returns empty string without error."""
        import phonikud  # noqa: PLC0415

        assert phonikud.phonemize("") == ""
        assert phonikud.phonemize("   ") == ""


class TestLoadPhonemizerPicksShim:
    """T26: _load_phonemize() selects phonikud.phonemize when shim has it."""

    def test_load_phonemize_returns_shim_phonemize_path(self):
        """_load_phonemize() label is 'phonikud.phonemize' when shim exposes phonemize."""
        import phonikud  # ensures shim is in sys.modules  # noqa: PLC0415

        assert callable(
            getattr(phonikud, "phonemize", None)
        ), "Precondition: shim must have phonemize"

        _fn, path = LightBlueTTSLocalProvider._load_phonemize()
        assert path == "phonikud.phonemize", f"Expected 'phonikud.phonemize' path but got {path!r}"

    def test_load_phonemize_fn_returns_ipa_for_niqqud_input(self):
        """Function returned by _load_phonemize() produces non-empty IPA for שֶׁל."""
        import phonikud  # noqa: PLC0415 — ensure shim loaded

        fn, _path = LightBlueTTSLocalProvider._load_phonemize()
        result = fn("\u05e9\u05b6\u05dc")  # שֶׁל
        assert isinstance(result, str)
        assert len(result) > 0, f"IPA is empty for שֶׁל, got {result!r}"
        # shim.phonemize → subprocess → phonikud.phonemize: שֶׁל → ʃˈel
        assert "e" in result, f"Expected vowel 'e' in IPA for שֶׁל, got {result!r}"


class TestPhonemizerSubprocessIsolation:
    """T27: subprocess strips shim dir so installed phonikud is used."""

    def test_run_phonemize_subprocess_returns_list(self):
        """_run_phonemize_subprocess returns list of same length as input."""
        from phonikud import _run_phonemize_subprocess  # noqa: PLC0415

        inputs = [
            "\u05e9\u05b6\u05dc",  # שֶׁל
            "\u05d7\u05d5\u05de\u05b6\u05e8",  # חוֹמֶר
        ]
        outputs = _run_phonemize_subprocess(inputs)
        assert len(outputs) == len(inputs), f"Expected {len(inputs)} outputs, got {len(outputs)}"
        for i, (inp, out) in enumerate(zip(inputs, outputs)):
            assert isinstance(out, str), f"Output {i} is not str: {out!r}"
            assert len(out) > 0, f"Output {i} is empty for input {inp!r}"

    def test_run_phonemize_subprocess_empty_input(self):
        """_run_phonemize_subprocess([]) returns []."""
        from phonikud import _run_phonemize_subprocess  # noqa: PLC0415

        assert _run_phonemize_subprocess([]) == []

    def test_run_phonemize_subprocess_no_shim_in_path(self):
        """Subprocess does not import local shim (no ImportError from phonikud internals)."""
        import subprocess  # noqa: PLC0415
        import sys  # noqa: PLC0415
        from phonikud import _SHIM_DIR  # noqa: PLC0415

        # Run a probe that imports phonikud from a clean path and checks for lexicon.
        code = (
            "import json,sys,os\n"
            "shim_dir=sys.argv[1]\n"
            "norm=os.path.normcase\n"
            "sys.path=[p for p in sys.path if norm(os.path.abspath(p or '.'))!=norm(shim_dir)]\n"
            "from phonikud import lexicon\n"
            "sys.stdout.write(json.dumps({'ok': True}))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, _SHIM_DIR],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        assert (
            result.returncode == 0
        ), f"Subprocess failed (shim leaked?): {result.stderr or result.stdout}"
