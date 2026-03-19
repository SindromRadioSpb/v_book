"""Deterministic audio cache-key helpers.

Separates provider-agnostic spoken payload identity from provider/request-
specific synthesis identity.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from app.services.pronunciation_quality_service import PronunciationQualityService
from app.services.pronunciation_service import PronunciationService


class AudioCacheKeyService:
    """Build stable hashes for current speech content and exact TTS requests."""

    SPEECH_HASH_VERSION = "audio-speech-v1"
    INPUT_HASH_VERSION = "audio-input-v1"
    SANITIZER_VERSION = "tts-sanitize-v1"

    def __init__(self) -> None:
        self.pronunciation_service = PronunciationService()

    def prepare_pronunciation_payload(
        self,
        session: Session,
        *,
        src_lang: str,
        source_text: str,
        source_norm: str,
    ) -> dict[str, object]:
        try:
            applied = self.pronunciation_service.apply_to_text(
                session=session,
                src_lang=src_lang,
                source_text=source_text,
                source_norm=source_norm,
            )
        except Exception:
            return {
                "text": source_text,
                "token_text": source_text,
                "ssml": "",
                "mode": "none",
                "is_valid": True,
                "qc_flag": None,
            }
        return {
            "text": applied.text or source_text,
            "token_text": applied.token_text or source_text,
            "ssml": applied.ssml or "",
            "mode": applied.mode or "none",
            "is_valid": bool(getattr(applied, "is_valid", True)),
            "qc_flag": getattr(applied, "qc_flag", None),
        }

    def build_speech_hash(
        self,
        *,
        src_lang: str,
        source_text: str,
        source_norm: str,
        pronunciation_payload: dict[str, object],
    ) -> str:
        canonical = {
            "v": self.SPEECH_HASH_VERSION,
            "sanitizer": self.SANITIZER_VERSION,
            "lang": (src_lang or "").strip(),
            "source_norm": (source_norm or "").strip(),
            "source_text": PronunciationQualityService.sanitize_tts_text(source_text),
            "text": PronunciationQualityService.sanitize_tts_text(
                str(pronunciation_payload.get("text") or "")
            ),
            "token_text": PronunciationQualityService.sanitize_tts_text(
                str(pronunciation_payload.get("token_text") or "")
            ),
            "ssml": str(pronunciation_payload.get("ssml") or "").strip(),
            "mode": str(pronunciation_payload.get("mode") or "none"),
            "is_valid": bool(pronunciation_payload.get("is_valid", True)),
            "qc_flag": str(pronunciation_payload.get("qc_flag") or ""),
        }
        return self._sha256_json(canonical)

    def build_input_hash(
        self,
        *,
        speech_hash: str,
        provider_id: str,
        voice_id: str,
        speed: float,
        audio_format: str,
        sample_rate_hz: int,
        provider_model_version: str | None = None,
    ) -> str:
        canonical = {
            "v": self.INPUT_HASH_VERSION,
            "speech_hash": (speech_hash or "").strip(),
            "provider_id": (provider_id or "").strip(),
            "voice_id": (voice_id or "").strip(),
            "speed": f"{float(speed):.4f}",
            "audio_format": (audio_format or "").strip().lower(),
            "sample_rate_hz": int(sample_rate_hz or 0),
            "provider_model_version": (provider_model_version or "").strip(),
        }
        return self._sha256_json(canonical)

    @staticmethod
    def _sha256_json(payload: dict[str, object]) -> str:
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
