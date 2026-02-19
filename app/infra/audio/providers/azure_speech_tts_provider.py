"""Azure Speech Neural TTS provider."""

from __future__ import annotations

import html
import logging
import time
import urllib.error
import urllib.request
from typing import Tuple

from app.infra.audio.audio_provider_config import AudioProviderAuthMode
from app.infra.audio.audio_provider_config_manager import AudioProviderConfigManager
from app.infra.audio.base_provider import (
    AudioErrorKind,
    AudioGenerationRequest,
    AudioGenerationResult,
    BaseAudioProvider,
)

logger = logging.getLogger(__name__)


class AzureSpeechTTSProvider(BaseAudioProvider):
    """Professional online TTS provider via Azure Speech REST API."""

    def __init__(self, config_manager: AudioProviderConfigManager | None = None):
        self._config_manager = config_manager or AudioProviderConfigManager()

    @property
    def provider_id(self) -> str:
        return "azure_speech_tts"

    @property
    def display_name(self) -> str:
        return "Azure Speech TTS"

    def generate(self, request: AudioGenerationRequest) -> AudioGenerationResult:
        source_text = (request.source_text or "").strip()
        if not source_text:
            return AudioGenerationResult(
                provider_id=self.provider_id,
                error_kind=AudioErrorKind.INVALID_REQUEST,
                error_message="Source text is empty",
            )

        cfg = self._config_manager.load_config(self.provider_id)
        if not cfg.enabled:
            return AudioGenerationResult(
                provider_id=self.provider_id,
                error_kind=AudioErrorKind.UNSUPPORTED,
                error_message="Provider is disabled",
            )
        if cfg.auth_mode != AudioProviderAuthMode.API_KEY:
            return AudioGenerationResult(
                provider_id=self.provider_id,
                error_kind=AudioErrorKind.AUTH,
                error_message="azure_speech_tts requires api_key auth mode",
            )

        api_key = self._config_manager.get_credential(cfg.api_key_credential_id)
        region = (cfg.region or "").strip()
        if not api_key or not region:
            return AudioGenerationResult(
                provider_id=self.provider_id,
                error_kind=AudioErrorKind.AUTH,
                error_message="Azure TTS requires region and API key credentials",
            )

        language_code = self._language_code(request.source_lang)
        voice_name = request.voice_id if request.voice_id and request.voice_id != "default" else (cfg.default_voice or "")
        if not voice_name:
            voice_name = "he-IL-HilaNeural"
        output_format, mime_type = self._output_format((request.audio_format or cfg.audio_format or "wav").lower())

        ssml = (request.options or {}).get("ssml")
        if not isinstance(ssml, str) or not ssml.strip():
            ssml = self._build_ssml(
                text=source_text,
                language_code=language_code,
                voice_name=voice_name,
                speed=request.speed,
            )

        endpoint = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
        payload = ssml.encode("utf-8")
        headers = {
            "Ocp-Apim-Subscription-Key": api_key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": output_format,
            "User-Agent": "HDLE-Premium/AudioPipeline",
        }
        req = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")

        attempts = max(1, int(cfg.retry_max_attempts))
        backoff_ms = max(100, int(cfg.retry_backoff_base_ms))
        for attempt in range(1, attempts + 1):
            try:
                with urllib.request.urlopen(req, timeout=cfg.timeout_seconds) as response:
                    audio_bytes = response.read()
                    if not audio_bytes:
                        return AudioGenerationResult(
                            provider_id=self.provider_id,
                            error_kind=AudioErrorKind.SERVER,
                            error_message="Azure TTS returned empty payload",
                        )
                    return AudioGenerationResult(
                        provider_id=self.provider_id,
                        audio_bytes=audio_bytes,
                        mime_type=mime_type,
                        meta={"region": region, "voice": voice_name, "format": output_format},
                    )
            except urllib.error.HTTPError as http_err:
                err_kind, err_msg = self._classify_http_error(http_err)
                if attempt < attempts and err_kind in {AudioErrorKind.NETWORK, AudioErrorKind.RATE_LIMIT, AudioErrorKind.SERVER}:
                    time.sleep((backoff_ms * (2 ** (attempt - 1))) / 1000.0)
                    continue
                return AudioGenerationResult(
                    provider_id=self.provider_id,
                    error_kind=err_kind,
                    error_message=err_msg,
                )
            except urllib.error.URLError as url_err:
                if attempt < attempts:
                    time.sleep((backoff_ms * (2 ** (attempt - 1))) / 1000.0)
                    continue
                return AudioGenerationResult(
                    provider_id=self.provider_id,
                    error_kind=AudioErrorKind.NETWORK,
                    error_message=str(url_err.reason),
                )
            except Exception as exc:
                return AudioGenerationResult(
                    provider_id=self.provider_id,
                    error_kind=AudioErrorKind.UNKNOWN,
                    error_message=str(exc),
                )

        return AudioGenerationResult(
            provider_id=self.provider_id,
            error_kind=AudioErrorKind.UNKNOWN,
            error_message="Azure TTS failed after retries",
        )

    @staticmethod
    def _language_code(raw_lang: str) -> str:
        lang = (raw_lang or "").strip().lower()
        if lang in {"he", "he-il"}:
            return "he-IL"
        if lang in {"en", "en-us"}:
            return "en-US"
        if "-" not in lang and len(lang) == 2:
            return f"{lang.lower()}-{lang.upper()}"
        return raw_lang or "he-IL"

    @staticmethod
    def _output_format(fmt: str) -> Tuple[str, str]:
        if fmt in {"mp3", "mpeg"}:
            return "audio-24khz-48kbitrate-mono-mp3", "audio/mpeg"
        if fmt in {"ogg", "opus"}:
            return "ogg-24khz-16bit-mono-opus", "audio/ogg"
        return "riff-24khz-16bit-mono-pcm", "audio/wav"

    @staticmethod
    def _build_ssml(text: str, language_code: str, voice_name: str, speed: float) -> str:
        speed_ratio = max(0.5, min(2.0, speed))
        speed_percent = int(round((speed_ratio - 1.0) * 100))
        prosody_rate = f"{speed_percent:+d}%"
        escaped = html.escape(text, quote=False)
        return (
            f"<speak version='1.0' xml:lang='{language_code}'>"
            f"<voice name='{voice_name}'>"
            f"<prosody rate='{prosody_rate}'>{escaped}</prosody>"
            f"</voice>"
            f"</speak>"
        )

    @staticmethod
    def _classify_http_error(error: urllib.error.HTTPError) -> Tuple[AudioErrorKind, str]:
        code = int(error.code)
        body = ""
        try:
            body = error.read().decode("utf-8", errors="ignore")
        except Exception:
            body = str(error)
        short = body[:400] if body else str(error)
        if code in (401, 403):
            return AudioErrorKind.AUTH, short
        if code == 429:
            return AudioErrorKind.RATE_LIMIT, short
        if 500 <= code <= 599:
            return AudioErrorKind.SERVER, short
        if code in (400, 404):
            return AudioErrorKind.INVALID_REQUEST, short
        return AudioErrorKind.UNKNOWN, short
