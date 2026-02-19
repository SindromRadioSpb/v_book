"""Base provider contract for Audio generation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class AudioErrorKind(Enum):
    """Taxonomy of audio generation failures."""

    NETWORK = "network"
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    QUOTA = "quota"
    SERVER = "server"
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass
class AudioGenerationRequest:
    """Single source-text to audio request."""

    source_text: str
    source_lang: str
    source_norm: str
    voice_id: str = "default"
    speed: float = 1.0
    audio_format: str = "wav"
    trace_id: str = ""
    timeout_seconds: float = 15.0
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AudioGenerationResult:
    """Provider result with binary payload or structured error."""

    provider_id: str = ""
    audio_bytes: bytes = b""
    mime_type: str = "audio/wav"
    duration_ms: Optional[int] = None
    error_kind: Optional[AudioErrorKind] = None
    error_message: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.error_kind is None and bool(self.audio_bytes)


class BaseAudioProvider(ABC):
    """Abstract base class for audio providers."""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Stable provider identifier."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-friendly provider name."""

    @property
    def is_local(self) -> bool:
        """Whether provider is local/offline."""
        return False

    @abstractmethod
    def generate(self, request: AudioGenerationRequest) -> AudioGenerationResult:
        """Generate audio for source text. Must not raise."""
