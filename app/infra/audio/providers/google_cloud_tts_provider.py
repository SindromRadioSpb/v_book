"""Google Cloud Text-to-Speech provider."""

from __future__ import annotations

import base64
import json
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


class GoogleCloudTTSProvider(BaseAudioProvider):
    """Professional online TTS provider via Google Cloud Text-to-Speech REST API."""

    def __init__(self, config_manager: AudioProviderConfigManager | None = None):
        self._config_manager = config_manager or AudioProviderConfigManager()

    @property
    def provider_id(self) -> str:
        return "google_cloud_tts"

    @property
    def display_name(self) -> str:
        return "Google Cloud TTS"

    def generate(self, request: AudioGenerationRequest) -> AudioGenerationResult:
        trace_id = request.trace_id or f"gtts-{int(time.time() * 1000)}"
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
        if cfg.auth_mode != AudioProviderAuthMode.SERVICE_ACCOUNT_JSON:
            return AudioGenerationResult(
                provider_id=self.provider_id,
                error_kind=AudioErrorKind.AUTH,
                error_message="google_cloud_tts requires service account auth mode",
            )

        try:
            token, project_id = self._resolve_access_token_and_project(cfg)
        except Exception as exc:
            logger.warning("[%s] auth init failed: %s", trace_id, exc)
            return AudioGenerationResult(
                provider_id=self.provider_id,
                error_kind=AudioErrorKind.AUTH,
                error_message=str(exc),
            )

        language_code = self._language_code(request.source_lang)
        voice_name = request.voice_id if request.voice_id and request.voice_id != "default" else (cfg.default_voice or "")
        encoding = self._audio_encoding((request.audio_format or cfg.audio_format or "wav").lower())
        speaking_rate = max(0.5, min(2.0, request.speed))

        ssml = (request.options or {}).get("ssml")
        if isinstance(ssml, str) and ssml.strip():
            input_payload = {"ssml": ssml}
        else:
            input_payload = {"text": source_text}

        body = {
            "input": input_payload,
            "voice": {
                "languageCode": language_code,
            },
            "audioConfig": {
                "audioEncoding": encoding,
                "speakingRate": speaking_rate,
                "sampleRateHertz": int(cfg.sample_rate_hz),
            },
        }
        if voice_name:
            body["voice"]["name"] = voice_name

        endpoint = "https://texttospeech.googleapis.com/v1/text:synthesize"
        payload = json.dumps(body).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
            "x-goog-user-project": project_id,
        }
        req = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")

        attempts = max(1, int(cfg.retry_max_attempts))
        backoff_ms = max(100, int(cfg.retry_backoff_base_ms))
        for attempt in range(1, attempts + 1):
            try:
                with urllib.request.urlopen(req, timeout=cfg.timeout_seconds) as response:
                    raw = response.read()
                    data = json.loads(raw.decode("utf-8"))
                    audio_content = str(data.get("audioContent") or "")
                    if not audio_content:
                        return AudioGenerationResult(
                            provider_id=self.provider_id,
                            error_kind=AudioErrorKind.SERVER,
                            error_message="Google TTS response missing audioContent",
                        )
                    audio_bytes = base64.b64decode(audio_content)
                    return AudioGenerationResult(
                        provider_id=self.provider_id,
                        audio_bytes=audio_bytes,
                        mime_type=self._mime_type(encoding),
                        meta={"project_id": project_id, "encoding": encoding},
                    )
            except urllib.error.HTTPError as http_err:
                err_kind, err_message = self._classify_http_error(http_err)
                if attempt < attempts and err_kind in {AudioErrorKind.NETWORK, AudioErrorKind.RATE_LIMIT, AudioErrorKind.SERVER}:
                    time.sleep((backoff_ms * (2 ** (attempt - 1))) / 1000.0)
                    continue
                return AudioGenerationResult(
                    provider_id=self.provider_id,
                    error_kind=err_kind,
                    error_message=err_message,
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
            error_message="Google TTS failed after retries",
        )

    def _resolve_access_token_and_project(self, cfg) -> Tuple[str, str]:
        sa_info = self._config_manager.get_service_account_info(cfg)
        if not sa_info:
            raise ValueError("Service account JSON is not configured")

        project_id = str(sa_info.get("project_id") or "").strip()
        if not project_id:
            raise ValueError("Service account JSON missing project_id")

        from google.auth.transport.requests import Request as GoogleAuthRequest
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        credentials.refresh(GoogleAuthRequest())
        token = str(credentials.token or "").strip()
        if not token:
            raise ValueError("Failed to obtain Google OAuth access token")
        return token, project_id

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
    def _audio_encoding(fmt: str) -> str:
        if fmt in {"mp3", "mpeg"}:
            return "MP3"
        if fmt in {"ogg", "opus"}:
            return "OGG_OPUS"
        return "LINEAR16"

    @staticmethod
    def _mime_type(encoding: str) -> str:
        if encoding == "MP3":
            return "audio/mpeg"
        if encoding == "OGG_OPUS":
            return "audio/ogg"
        return "audio/wav"

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
