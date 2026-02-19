"""Local/offline mock audio provider."""

from __future__ import annotations

from app.infra.audio.base_provider import (
    AudioErrorKind,
    AudioGenerationRequest,
    AudioGenerationResult,
    BaseAudioProvider,
)

from ._tone import synthesize_tone_wav


class MockLocalAudioProvider(BaseAudioProvider):
    """Deterministic local audio stub for source-only pipeline."""

    @property
    def provider_id(self) -> str:
        return "mock_local_audio"

    @property
    def display_name(self) -> str:
        return "Mock Local Audio (Offline)"

    @property
    def is_local(self) -> bool:
        return True

    def generate(self, request: AudioGenerationRequest) -> AudioGenerationResult:
        try:
            text = (request.source_text or "").strip()
            if not text:
                return AudioGenerationResult(
                    provider_id=self.provider_id,
                    error_kind=AudioErrorKind.INVALID_REQUEST,
                    error_message="Source text is empty",
                )
            payload, duration_ms = synthesize_tone_wav(text=text, speed=request.speed)
            return AudioGenerationResult(
                provider_id=self.provider_id,
                audio_bytes=payload,
                duration_ms=duration_ms,
                mime_type="audio/wav",
                meta={"stub": True, "mode": "local"},
            )
        except Exception as exc:
            return AudioGenerationResult(
                provider_id=self.provider_id,
                error_kind=AudioErrorKind.UNKNOWN,
                error_message=str(exc),
            )
