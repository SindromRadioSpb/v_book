"""Deterministic WAV tone synthesis used by mock audio providers."""

from __future__ import annotations

import io
import math
import struct
import wave
from typing import Tuple


def synthesize_tone_wav(
    *,
    text: str,
    speed: float,
    sample_rate_hz: int = 16000,
) -> Tuple[bytes, int]:
    """Generate short deterministic mono WAV based on input text.

    This intentionally does not attempt real TTS. It is a safe stub that
    produces valid audio bytes for pipeline/testing.
    """
    clean_speed = max(0.5, min(2.0, float(speed or 1.0)))
    text_len = max(1, len((text or "").strip()))
    duration_sec = max(0.22, min(1.2, (0.14 + text_len * 0.014) / clean_speed))
    total_frames = int(sample_rate_hz * duration_sec)

    # Keep frequency deterministic but varied by content.
    checksum = sum(ord(ch) for ch in (text or ""))
    base_freq = 220 + (checksum % 180)

    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)  # 16-bit PCM
        wav.setframerate(sample_rate_hz)
        amplitude = 9000
        for i in range(total_frames):
            sample = amplitude * math.sin(2 * math.pi * base_freq * (i / sample_rate_hz))
            wav.writeframesraw(struct.pack("<h", int(sample)))
    return out.getvalue(), int(duration_sec * 1000)
