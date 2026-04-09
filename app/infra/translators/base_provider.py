"""Base provider contract for Machine Translation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TranslationErrorKind(Enum):
    """Taxonomy of translation errors for fallback logic."""

    NETWORK = "network"  # Connection failed, timeout
    AUTH = "auth"  # Invalid API key, unauthorized
    RATE_LIMIT = "rate_limit"  # Rate limit exceeded (429)
    QUOTA = "quota"  # Quota exceeded (402, 403)
    SERVER = "server"  # Server error (500, 502, 503, 504)
    INVALID_REQUEST = "invalid_request"  # Bad request (400)
    UNSUPPORTED = "unsupported"  # Feature not supported (e.g., language pair)
    UNKNOWN = "unknown"  # Catch-all for unexpected errors


@dataclass
class TranslationRequest:
    """Request to translate a single segment."""

    source_text: str
    source_lang: str  # ISO 639-1 (e.g., "he", "en", "ru")
    target_lang: str  # ISO 639-1 (e.g., "ru", "en", "he")

    # Optional fields
    glossary: Any | None = None  # Provider-specific glossary payload
    glossary_hash: str = ""  # SHA256 hex of canonical glossary (for cache key)
    options: dict[str, Any] = field(default_factory=dict)  # Provider-specific options
    trace_id: str = ""  # For logging and debugging
    allow_fallback: bool = True
    timeout_seconds: float = 10.0


@dataclass
class TranslationResult:
    """Result of translation request with provenance."""

    translated_text: str = ""
    provider_id: str = ""  # e.g., "deepl", "google", "mock"
    used_glossary: bool = False
    cache_hit: bool = False
    latency_ms: int = 0

    # Error fields (mutually exclusive with successful translation)
    error_kind: TranslationErrorKind | None = None
    error_message: str | None = None

    # Metadata (provider-specific)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        """Check if translation succeeded."""
        return self.error_kind is None and bool(self.translated_text)

    @property
    def is_error(self) -> bool:
        """Check if translation failed."""
        return self.error_kind is not None


class BaseProvider(ABC):
    """Abstract base class for MT providers."""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """
        Unique provider ID (lowercase, alphanumeric + underscore).

        Examples: 'deepl', 'google', 'libretranslate', 'mock'
        """
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """
        Human-readable provider name.

        Examples: 'DeepL Pro', 'Google Translate', 'LibreTranslate'
        """
        pass

    @property
    @abstractmethod
    def supports_glossary(self) -> bool:
        """Whether this provider supports glossary payloads."""
        pass

    @property
    def supports_batch(self) -> bool:
        """Whether this provider supports batch translation (default: False)."""
        return False

    def translate_batch(self, requests: list[TranslationRequest]) -> list[TranslationResult]:
        """Optional batch translation API.

        Default implementation preserves existing behaviour by delegating to
        ``translate()`` one request at a time.
        """
        return [self.translate(request) for request in requests]

    @abstractmethod
    def translate(self, request: TranslationRequest) -> TranslationResult:
        """
        Translate a single segment.

        CRITICAL: MUST NOT raise exceptions.
        Return TranslationResult with error_kind on failure.

        Args:
            request: TranslationRequest with source text and parameters

        Returns:
            TranslationResult with translated text or error
        """
        pass

    def get_model_version(self) -> str:
        """
        Get model version for cache key.

        Returns:
            Model version string (default: 'v1')
        """
        return "v1"

    def healthcheck(self) -> bool:
        """
        Optional health check.

        Returns:
            True if provider is healthy (default: True)
        """
        return True
