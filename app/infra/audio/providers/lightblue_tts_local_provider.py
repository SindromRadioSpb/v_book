"""Optional local LightBlueTTS Hebrew provider (experimental, license-gated)."""

from __future__ import annotations

import io
import logging
import wave
from pathlib import Path
from threading import Lock
from typing import Any

from app.infra.audio.audio_provider_config_manager import AudioProviderConfigManager
from app.infra.audio.base_provider import (
    AudioErrorKind,
    AudioGenerationRequest,
    AudioGenerationResult,
    BaseAudioProvider,
)
from app.infra.settings import SettingsService

logger = logging.getLogger(__name__)

# Default voice style file inside the model directory.
_DEFAULT_VOICE = "female1.json"

# Max speed ratio supported without audible artefacts.
_SPEED_MIN = 0.5
_SPEED_MAX = 2.0

# Context wrapping improves phonikud accuracy on isolated single words.
# Set to False to disable (e.g., for debugging or performance testing).
_ENABLE_CONTEXT_WRAP: bool = True
_CONTEXT_WRAP_PREFIX: str = "המילה "  # Hebrew: "the word " — provides article/context signal
_CONTEXT_WRAP_SUFFIX: str = "."

# Minimum IPA phoneme count for stable synthesis; a WARNING is logged below this.
_MIN_PHONEME_THRESHOLD: int = 5

# Adaptive diffusion parameters by estimated phoneme count.
# Short Hebrew words (< 8 est. phonemes) benefit from more diffusion steps.
_PHONEME_SHORT_THRESHOLD: int = 8
_PHONEME_MID_THRESHOLD: int = 16
_STEPS_SHORT: int = 48
_STEPS_MID: int = 40
_STEPS_DEFAULT: int = 32
_CFG_SHORT: float = 4.5
_CFG_MID: float = 3.5
_CFG_DEFAULT: float = 3.0


class LightBlueTTSLocalProvider(BaseAudioProvider):
    """Experimental local Hebrew TTS provider based on LightBlueTTS (ONNX, CPU).

    Status: EXPERIMENTAL — model weights license (notmax123/LightBlue) has not
    been verified for commercial use.  The provider is disabled by default and
    requires explicit license gate acceptance before activation.

    Model directory layout expected at config.model_path (or default discovery
    path %LOCALAPPDATA%\\HDLE\\models\\lightblue_tts\\):
        backbone_keys.onnx / backbone.onnx
        vocoder.onnx
        text_encoder.onnx
        length_pred.onnx          (optional)
        length_pred_style.onnx    (optional)
        reference_encoder.onnx   (optional)
        stats.npz
        uncond.npz
        voices/female1.json       (default style)
        voices/male1.json         (alternative style)
    """

    LICENSE_GATE_KEY = "audio/providers/lightblue_tts/license_accepted"

    # (model_dir, style_path, speed, steps, cfg_scale) -> (LightBlueTTS, Phonikud)
    _cache_lock: Lock = Lock()
    _synth_lock: Lock = Lock()
    _model_cache: dict[tuple[str, str, float, int, float], Any] = {}

    def __init__(self, config_manager: AudioProviderConfigManager | None = None) -> None:
        self._config_manager = config_manager or AudioProviderConfigManager()
        self._settings = SettingsService.get_instance()

    @property
    def provider_id(self) -> str:
        return "lightblue_tts"

    @property
    def display_name(self) -> str:
        return "LightBlueTTS Hebrew (Local, Experimental)"

    @property
    def is_local(self) -> bool:
        return True

    def generate(self, request: AudioGenerationRequest) -> AudioGenerationResult:
        """Synthesize Hebrew audio via LightBlueTTS ONNX pipeline."""
        source_text = (request.source_text or "").strip()
        if not source_text:
            return AudioGenerationResult(
                provider_id=self.provider_id,
                error_kind=AudioErrorKind.INVALID_REQUEST,
                error_message="Source text is empty.",
            )

        if not self._settings.get_bool(self.LICENSE_GATE_KEY, False):
            return AudioGenerationResult(
                provider_id=self.provider_id,
                error_kind=AudioErrorKind.UNSUPPORTED,
                error_message=(
                    "lightblue_tts is disabled: license gate not accepted. "
                    "Open Tools → Translation → Audio Provider Settings to enable."
                ),
            )

        config = self._config_manager.load_config(self.provider_id)
        if not config.enabled:
            return AudioGenerationResult(
                provider_id=self.provider_id,
                error_kind=AudioErrorKind.UNSUPPORTED,
                error_message="lightblue_tts provider is disabled.",
            )

        speed = max(_SPEED_MIN, min(_SPEED_MAX, float(request.speed or 1.0)))

        try:
            audio_bytes, sample_rate = self._synthesize(
                text=source_text,
                model_path=config.model_path,
                speed=speed,
            )
            return AudioGenerationResult(
                provider_id=self.provider_id,
                audio_bytes=audio_bytes,
                mime_type="audio/wav",
                meta={
                    "sample_rate": sample_rate,
                    "model_dir": config.model_path or self._default_model_dir(),
                },
            )
        except ImportError as exc:
            logger.warning("lightblue_tts dependencies missing: %s", exc)
            return AudioGenerationResult(
                provider_id=self.provider_id,
                error_kind=AudioErrorKind.UNSUPPORTED,
                error_message=f"LightBlueTTS dependencies missing: {exc}",
            )
        except FileNotFoundError as exc:
            logger.warning("lightblue_tts model not found: %s", exc)
            return AudioGenerationResult(
                provider_id=self.provider_id,
                error_kind=AudioErrorKind.INVALID_REQUEST,
                error_message=str(exc),
            )
        except Exception as exc:
            logger.error("lightblue_tts synthesis failed: %s", exc, exc_info=True)
            return AudioGenerationResult(
                provider_id=self.provider_id,
                error_kind=AudioErrorKind.UNKNOWN,
                error_message=str(exc),
            )

    # ------------------------------------------------------------------
    # Internal synthesis pipeline
    # ------------------------------------------------------------------

    def _synthesize(
        self,
        *,
        text: str,
        model_path: str | None,
        speed: float,
    ) -> tuple[bytes, int]:
        """Full pipeline: text → niqqud → IPA phonemes → WAV bytes.

        Raises:
            ImportError: required dependency not installed.
            FileNotFoundError: model directory or style file missing.
        """
        # Validate paths first — before any heavy imports — so missing-model
        # tests never trigger onnxruntime initialisation in the same process.
        model_dir = Path(model_path or self._default_model_dir())
        if not model_dir.exists():
            raise FileNotFoundError(
                f"LightBlueTTS model directory not found: {model_dir}. "
                "Place model files at this path or configure a custom path in "
                "Audio Provider Settings."
            )

        style_path = self._resolve_style_path(model_dir)
        if not style_path.exists():
            raise FileNotFoundError(
                f"LightBlueTTS voice style file not found: {style_path}. "
                "The model directory must contain a voices/ subdirectory with "
                "at least female1.json."
            )

        # Lazy imports — failures become ImportError, never crash the app.
        try:
            from lightblue_onnx import LightBlueTTS  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(f"lightblue_onnx not installed: {exc}") from exc

        try:
            from phonikud_onnx import Phonikud  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(f"phonikud_onnx not installed: {exc}") from exc

        phonemize_fn, phonemize_path = self._load_phonemize()

        # Adaptive diffusion params: short words need more steps to converge.
        steps, cfg_scale = _adaptive_synth_params(text)
        cache_key = (str(model_dir), str(style_path), speed, steps, cfg_scale)

        with self._cache_lock:
            tts = self._model_cache.get(cache_key)
            if tts is None:
                phonikud_model_path = self._resolve_phonikud_model()
                phonikud_instance = Phonikud(phonikud_model_path)
                tts = (
                    LightBlueTTS(
                        onnx_dir=str(model_dir),
                        style_json=str(style_path),
                        steps=steps,
                        cfg_scale=cfg_scale,
                        speed=speed,
                        seed=42,
                        use_gpu=False,
                        chunk_len=150,
                        silence_sec=0.15,
                        fade_duration=0.02,
                    ),
                    phonikud_instance,
                )
                self._model_cache[cache_key] = tts
            tts_model, phonikud_instance = tts

        with self._synth_lock:
            audio_arr, sample_rate = self._synthesize_phonemes(
                text=text,
                tts_model=tts_model,
                phonikud_instance=phonikud_instance,
                phonemize_fn=phonemize_fn,
                phonemize_path=phonemize_path,
            )

        import numpy as np  # noqa: PLC0415

        arr = np.asarray(audio_arr, dtype=np.float32)

        # Short inputs (lemmas, terms) lose their attack/release edges because
        # the model generates minimal silence and fade_duration clips the ends.
        # Pad with 120 ms of silence before and after to preserve the full word.
        pad_samples = int(sample_rate * 0.12)
        silence = np.zeros(pad_samples, dtype=np.float32)
        arr = np.concatenate([silence, arr, silence])

        arr = self._normalize_audio_loudness(arr)

        pcm = (arr * 32767.0).astype(np.int16)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm.tobytes())
        return buf.getvalue(), sample_rate

    def _synthesize_phonemes(
        self,
        *,
        text: str,
        tts_model: Any,
        phonikud_instance: Any,
        phonemize_fn: Any,
        phonemize_path: str,
    ) -> tuple[Any, int]:
        """G2P → phonemize → synthesize. Must be called within _synth_lock.

        Returns:
            (audio_array, sample_rate) from LightBlueTTS.create().
        """
        # Context-wrap single words to improve phonikud accuracy (PATCH-01).
        # Isolated words lack grammatical context; wrapping provides an article signal.
        was_wrapped = _ENABLE_CONTEXT_WRAP and _is_single_word(text)
        g2p_input = (
            _CONTEXT_WRAP_PREFIX + text.strip() + _CONTEXT_WRAP_SUFFIX if was_wrapped else text
        )

        niqqud_raw, g2p_branch = self._apply_g2p(g2p_input, phonikud_instance)

        # Strip context wrapper from G2P result to recover only the target word.
        if was_wrapped and g2p_branch != "raw_text":
            niqqud_text = _extract_g2p_word(niqqud_raw, text)
        else:
            niqqud_text = niqqud_raw

        # Strip phonikud pipe-separators ('|') — phonikud uses '|' as a prefix/compound
        # word boundary marker; it is not a Hebrew character and must be removed before
        # IPA conversion so that pre-scan of diacritics (e.g. mobile shva detection)
        # works correctly across the boundary.
        niqqud_text = niqqud_text.replace("|", "")

        if g2p_branch == "raw_text":
            logger.warning(
                "lightblue_tts: all G2P branches failed — synthesizing raw text (len=%d)",
                len(text),
            )
        else:
            logger.info(
                "lightblue_tts: G2P branch=%s wrapped=%s niqqud=%r",
                g2p_branch,
                was_wrapped,
                niqqud_text,
            )

        phonemes = phonemize_fn(niqqud_text)
        phoneme_count = _count_ipa_phonemes(phonemes)

        logger.info(
            "lightblue_tts: phonemize_path=%s phonemes=%r count=%d",
            phonemize_path,
            phonemes,
            phoneme_count,
        )

        if phoneme_count < _MIN_PHONEME_THRESHOLD:
            logger.warning(
                "lightblue_tts: short phoneme sequence (count=%d < threshold=%d) text=%r",
                phoneme_count,
                _MIN_PHONEME_THRESHOLD,
                text,
            )

        if not _has_vowels(phonemes) and phoneme_count < 6:
            logger.warning(
                "lightblue_tts: consonant-only IPA detected (no vowels, count=%d) "
                "— quality may be degraded for text=%r",
                phoneme_count,
                text,
            )

        # Append a terminal period so the model treats the sequence as a complete
        # utterance.  Without it, the flow-matching diffusion tends to echo or
        # repeat the final phoneme on short inputs (e.g. 2–4 phoneme words).
        phonemes_for_synth = phonemes.rstrip(" ") + (
            "" if phonemes.rstrip().endswith((".", "!", "?")) else "."
        )

        audio_arr, sample_rate = tts_model.create(phonemes_for_synth)
        return audio_arr, sample_rate

    @staticmethod
    def _apply_g2p(text: str, phonikud_onnx_instance: Any) -> tuple[str, str]:
        """Add Hebrew diacritics (niqqud) via a best-effort fallback chain.

        Chain:
          1. phonikud.add_nikud / add_niqqud / add_diacritics  (any installed version)
          2. phonikud_onnx.Phonikud.add_diacritics              (ONNX runtime)
          3. original text                                       (raw fallback)

        Returns:
            (niqqud_text, branch_name) — branch_name identifies which path succeeded.
        """
        import sys  # noqa: PLC0415

        # 1. Try the phonikud package (any version) — attribute discovery covers
        #    older API names (add_nikud, add_niqqud) and newer (add_diacritics).
        pkg = sys.modules.get("phonikud")
        if pkg is not None:
            for attr in ("add_nikud", "add_niqqud", "add_diacritics"):
                fn = getattr(pkg, attr, None)
                if not callable(fn):
                    continue
                try:
                    result = fn(text)
                    if result:
                        return result, f"phonikud.{attr}"
                except Exception as exc:
                    logger.debug("lightblue_tts G2P: phonikud.%s failed: %s", attr, exc)

        # 2. phonikud_onnx — reliable ONNX-based diacritizer.
        try:
            result = phonikud_onnx_instance.add_diacritics(text)
            if result:
                return result, "phonikud_onnx"
        except Exception as exc:
            logger.warning("lightblue_tts G2P: phonikud_onnx.add_diacritics failed: %s", exc)

        # 3. Raw text — synthesize without diacritics (degraded quality, no crash).
        return text, "raw_text"

    @staticmethod
    def _normalize_audio_loudness(
        audio: Any,
        *,
        target_rms: float = 0.08,
        target_peak: float = 0.92,
        max_gain: float = 24.0,
    ) -> Any:
        """Normalize waveform loudness via RMS + peak gain (from Kadima reference)."""
        import numpy as np  # noqa: PLC0415

        waveform = np.asarray(audio, dtype=np.float32).copy()
        if waveform.size == 0:
            return waveform
        peak = float(np.max(np.abs(waveform)))
        rms = float(np.sqrt(np.mean(np.square(waveform, dtype=np.float64))))
        if peak <= 1e-7 or rms <= 1e-7:
            return waveform
        gain_from_rms = target_rms / rms
        gain_from_peak = target_peak / peak
        gain = min(gain_from_rms, gain_from_peak, max_gain)
        if gain <= 1.05:
            return waveform
        waveform *= gain
        return np.clip(waveform, -target_peak, target_peak)

    @staticmethod
    def _load_phonemize() -> tuple[Any, str]:
        """Load phonikud.phonemize from site-packages, bypassing local shim.

        Returns:
            (callable, source_label) — the phonemize function and a diagnostic
            label identifying which code path was selected.
        """
        import importlib.util  # noqa: PLC0415
        import site  # noqa: PLC0415
        import sys  # noqa: PLC0415

        # phonikud.py at project root shadows the installed package.
        # Load from site-packages directly when the shim is active.
        pkg_mod = sys.modules.get("phonikud")
        if pkg_mod is not None and callable(getattr(pkg_mod, "phonemize", None)):
            return pkg_mod.phonemize, "phonikud.phonemize"

        for sp in site.getsitepackages():
            init = Path(sp) / "phonikud" / "__init__.py"
            if not init.exists():
                continue
            spec = importlib.util.spec_from_file_location(
                "phonikud",
                str(init),
                submodule_search_locations=[str(init.parent)],
            )
            if spec is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            sys.modules["phonikud"] = mod
            try:
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
            except Exception:
                del sys.modules["phonikud"]
                continue
            fn = getattr(mod, "phonemize", None)
            if callable(fn):
                return fn, "phonikud.phonemize(site)"
            del sys.modules["phonikud"]

        # Fallback: use our rule-based IPA converter
        from app.infra.audio.providers._he_ipa import hebrew_to_ipa  # noqa: PLC0415

        return hebrew_to_ipa, "hebrew_to_ipa"

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _default_model_dir() -> str:
        """Resolve default model directory from HDLE data root."""
        import os  # noqa: PLC0415

        local_app_data = os.getenv("LOCALAPPDATA", "")
        if local_app_data:
            return str(Path(local_app_data) / "HDLE" / "models" / "lightblue_tts")
        try:
            from app.infra.resource_paths import ResourcePaths  # noqa: PLC0415

            return str(ResourcePaths.resolve_data_root() / "models" / "lightblue_tts")
        except Exception:
            return ""

    @staticmethod
    def _resolve_style_path(model_dir: Path) -> Path:
        """Return the default voice style JSON path."""
        return model_dir / "voices" / _DEFAULT_VOICE

    @staticmethod
    def _resolve_phonikud_model() -> str:
        """Resolve phonikud ONNX model path via standard discovery chain."""
        import os  # noqa: PLC0415

        # 1. Environment variable (set by app bootstrap)
        env_path = (os.getenv("PHONIKUD_MODEL_PATH") or "").strip()
        if env_path and Path(env_path).exists():
            return env_path

        # 2. QSettings (may not be reachable if called early)
        try:
            from app.infra.settings import SettingsService  # noqa: PLC0415

            settings_path = SettingsService.get_instance().get_string(
                "pronunciation/phonikud/model_path", ""
            )
            if settings_path and Path(settings_path).exists():
                return settings_path
        except Exception:
            pass

        # 3. Default HDLE data root
        local_app_data = os.getenv("LOCALAPPDATA", "")
        if local_app_data:
            candidates = sorted(
                (Path(local_app_data) / "HDLE" / "models" / "phonikud").glob("*.onnx"),
                key=lambda p: (0 if "int8" in p.name else 1, p.name),
            )
            if candidates:
                return str(candidates[0])

        # 4. Bundled resources
        try:
            from app.infra.resource_paths import ResourcePaths  # noqa: PLC0415

            bundled = ResourcePaths.resolve_data_root().parent / "resources" / "models" / "phonikud"
            candidates = sorted(
                bundled.glob("*.onnx"),
                key=lambda p: (0 if "int8" in p.name else 1, p.name),
            )
            if candidates:
                return str(candidates[0])
        except Exception:
            pass

        raise FileNotFoundError(
            "Phonikud ONNX model not found. Set PHONIKUD_MODEL_PATH or configure "
            "the model path in Resources Manager."
        )


# ---------------------------------------------------------------------------
# Module-level helpers — no class dependencies
# ---------------------------------------------------------------------------


def _adaptive_synth_params(text: str) -> tuple[int, float]:
    """Return (steps, cfg_scale) tuned for the estimated phoneme count.

    Estimates phoneme count from Hebrew letter count (each Hebrew consonant
    ~1.5 phonemes on average including likely vowels). Short words get more
    diffusion steps to avoid under-convergence artefacts.
    """
    he_count = sum(1 for c in text if "\u05d0" <= c <= "\u05ea")
    est = max(1, int(he_count * 1.5))
    if est < _PHONEME_SHORT_THRESHOLD:
        return _STEPS_SHORT, _CFG_SHORT
    if est < _PHONEME_MID_THRESHOLD:
        return _STEPS_MID, _CFG_MID
    return _STEPS_DEFAULT, _CFG_DEFAULT


def _is_single_word(text: str) -> bool:
    """Return True if text contains no whitespace (single token)."""
    stripped = text.strip()
    return bool(stripped) and " " not in stripped


def _extract_g2p_word(wrapped_niqqud: str, original_word: str) -> str:
    """Extract the target niqqud word from context-wrapped G2P output.

    Expected format after G2P: "<niqqud_prefix> <niqqud_word>[punct]"
    The prefix token ("הַמִּילָה") is dropped; trailing punctuation stripped.
    """
    parts = wrapped_niqqud.split(" ", 1)
    if len(parts) == 2:
        extracted = parts[1].rstrip(_CONTEXT_WRAP_SUFFIX + " ")
        if extracted:
            return extracted
    # Fallback: strip suffix then take last space-separated token.
    stripped = wrapped_niqqud.rstrip(_CONTEXT_WRAP_SUFFIX + " ")
    if " " in stripped:
        candidate = stripped.rsplit(" ", 1)[1]
        if candidate:
            return candidate
    logger.debug(
        "lightblue_tts: context-wrap extraction fell through, using original=%r",
        original_word,
    )
    return original_word


def _count_ipa_phonemes(phonemes: str) -> int:
    """Count non-whitespace, non-punctuation characters in an IPA string."""
    _PUNCT = frozenset(" .,!?-\t\n\r")
    return sum(1 for c in phonemes if c not in _PUNCT)


def _has_vowels(ipa: str) -> bool:
    """Return True if the IPA string contains at least one vowel character."""
    return any(c in "aeiouæøœɪʊɐəɑɔɛ" for c in ipa)
