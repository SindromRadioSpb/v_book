"""Optional local Meta MMS-TTS Hebrew provider (license-gated)."""

from __future__ import annotations

import io
import logging
import wave
from pathlib import Path
from threading import Lock

from app.infra.audio.audio_provider_config_manager import AudioProviderConfigManager
from app.infra.audio.base_provider import (
    AudioErrorKind,
    AudioGenerationRequest,
    AudioGenerationResult,
    BaseAudioProvider,
)
from app.infra.settings import SettingsService

logger = logging.getLogger(__name__)


class MMSTTSLocalProvider(BaseAudioProvider):
    """Local/offline MMS provider with explicit license-gate."""

    DEFAULT_MODEL_ID = "facebook/mms-tts-heb"
    LICENSE_GATE_KEY = "audio/providers/mms_tts_local/license_accepted"

    _cache_lock = Lock()
    _synth_lock = Lock()
    _model_cache = {}

    def __init__(self, config_manager: AudioProviderConfigManager | None = None):
        self._config_manager = config_manager or AudioProviderConfigManager()
        self._settings = SettingsService.get_instance()

    @property
    def provider_id(self) -> str:
        return "mms_tts_local"

    @property
    def display_name(self) -> str:
        return "Meta MMS-TTS Hebrew (Local)"

    @property
    def is_local(self) -> bool:
        return True

    def generate(self, request: AudioGenerationRequest) -> AudioGenerationResult:
        source_text = (request.source_text or "").strip()
        if not source_text:
            return AudioGenerationResult(
                provider_id=self.provider_id,
                error_kind=AudioErrorKind.INVALID_REQUEST,
                error_message="Source text is empty",
            )

        if not self._settings.get_bool(self.LICENSE_GATE_KEY, False):
            return AudioGenerationResult(
                provider_id=self.provider_id,
                error_kind=AudioErrorKind.UNSUPPORTED,
                error_message=(
                    "mms_tts_local is disabled until license gate is accepted "
                    "(Tools -> Translation -> Audio Provider Settings or force dialog)."
                ),
            )

        config = self._config_manager.load_config(self.provider_id)
        if not config.enabled:
            return AudioGenerationResult(
                provider_id=self.provider_id,
                error_kind=AudioErrorKind.UNSUPPORTED,
                error_message="mms_tts_local provider is disabled",
            )

        try:
            audio_bytes, sample_rate = self._synthesize(
                text=source_text,
                model_path=config.model_path,
                speed=request.speed,
            )
            return AudioGenerationResult(
                provider_id=self.provider_id,
                audio_bytes=audio_bytes,
                mime_type="audio/wav",
                meta={"sample_rate": sample_rate, "model_path": config.model_path or self.DEFAULT_MODEL_ID},
            )
        except ImportError as exc:
            return AudioGenerationResult(
                provider_id=self.provider_id,
                error_kind=AudioErrorKind.UNSUPPORTED,
                error_message=f"Local MMS dependencies missing: {exc}",
            )
        except FileNotFoundError as exc:
            return AudioGenerationResult(
                provider_id=self.provider_id,
                error_kind=AudioErrorKind.INVALID_REQUEST,
                error_message=str(exc),
            )
        except Exception as exc:
            logger.error("mms_tts_local synthesis failed: %s", exc, exc_info=True)
            return AudioGenerationResult(
                provider_id=self.provider_id,
                error_kind=AudioErrorKind.UNKNOWN,
                error_message=str(exc),
            )

    def _synthesize(self, *, text: str, model_path: str | None, speed: float) -> tuple[bytes, int]:
        import numpy as np
        import torch
        from transformers import AutoTokenizer, VitsModel

        model_ref = model_path or self.DEFAULT_MODEL_ID
        if model_path and not Path(model_path).exists():
            raise FileNotFoundError(f"MMS model path not found: {model_path}")

        with self._cache_lock:
            cached = self._model_cache.get(model_ref)
            if cached is None:
                tokenizer = AutoTokenizer.from_pretrained(model_ref)
                model = VitsModel.from_pretrained(model_ref)
                model.eval()
                sample_rate = int(getattr(model.config, "sampling_rate", 16000))
                cached = (tokenizer, model, sample_rate)
                self._model_cache[model_ref] = cached
            tokenizer, model, sample_rate = cached

        with self._synth_lock:
            inputs = tokenizer(text, return_tensors="pt")
            with torch.no_grad():
                waveform = model(**inputs).waveform

        arr = waveform[0].cpu().numpy()
        arr = np.asarray(arr, dtype=np.float32)
        speed = max(0.5, min(2.0, float(speed or 1.0)))
        if speed != 1.0 and len(arr) > 1:
            x_old = np.linspace(0.0, 1.0, num=len(arr), endpoint=True)
            new_len = max(1, int(round(len(arr) / speed)))
            x_new = np.linspace(0.0, 1.0, num=new_len, endpoint=True)
            arr = np.interp(x_new, x_old, arr).astype(np.float32)

        arr = np.clip(arr, -1.0, 1.0)
        pcm = (arr * 32767.0).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm.tobytes())
        return buf.getvalue(), sample_rate
