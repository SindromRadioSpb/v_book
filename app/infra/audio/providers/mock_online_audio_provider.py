"""Online-style mock audio provider (simulated cloud behavior)."""

from __future__ import annotations

import time

from app.infra.audio.base_provider import (
    AudioErrorKind,
    AudioGenerationRequest,
    AudioGenerationResult,
    BaseAudioProvider,
)

from ._tone import synthesize_tone_wav


class MockOnlineAudioProvider(BaseAudioProvider):
    """Simulates an online provider with small network-like latency."""

    @property
    def provider_id(self) -> str:
        return "mock_online_audio"

    @property
    def display_name(self) -> str:
        return "Mock Online Audio (Cloud-style)"

    @property
    def is_local(self) -> bool:
        return False

    def generate(self, request: AudioGenerationRequest) -> AudioGenerationResult:
        try:
            text = (request.source_text or "").strip()
            if not text:
                return AudioGenerationResult(
                    provider_id=self.provider_id,
                    error_kind=AudioErrorKind.INVALID_REQUEST,
                    error_message="Source text is empty",
                )

            # Simulated provider RTT.
            time.sleep(0.06)
            payload, duration_ms = synthesize_tone_wav(text=text, speed=request.speed)
            return AudioGenerationResult(
                provider_id=self.provider_id,
                audio_bytes=payload,
                duration_ms=duration_ms,
                mime_type="audio/wav",
                meta={"stub": True, "mode": "online"},
            )
        except Exception as exc:
            return AudioGenerationResult(
                provider_id=self.provider_id,
                error_kind=AudioErrorKind.UNKNOWN,
                error_message=str(exc),
            )
