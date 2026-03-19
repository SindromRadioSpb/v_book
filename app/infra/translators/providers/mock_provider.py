"""Mock MT provider for testing (deterministic, no API calls)."""

import hashlib
import time

from ..base_provider import (
    BaseProvider,
    TranslationErrorKind,
    TranslationRequest,
    TranslationResult,
)


class MockProvider(BaseProvider):
    """
    Mock MT provider for testing.

    Behavior:
    - Returns deterministic "translations" (reversed source text + language markers)
    - Simulates latency (configurable)
    - Can simulate errors (configurable)
    - Supports glossary (marks used_glossary=True if glossary provided)
    """

    def __init__(
        self,
        simulate_latency_ms: int = 0,
        simulate_error: TranslationErrorKind | None = None,
        error_probability: float = 0.0,
    ):
        """
        Initialize mock provider.

        Args:
            simulate_latency_ms: Simulated latency in milliseconds (default: 0)
            simulate_error: Error kind to simulate (default: None = success)
            error_probability: Probability of error (0.0-1.0, default: 0.0)
        """
        self._simulate_latency_ms = simulate_latency_ms
        self._simulate_error = simulate_error
        self._error_probability = error_probability

    @property
    def provider_id(self) -> str:
        return "mock"

    @property
    def display_name(self) -> str:
        return "Mock Provider (Testing)"

    @property
    def supports_glossary(self) -> bool:
        return True

    @property
    def supports_batch(self) -> bool:
        return False

    def translate(self, request: TranslationRequest) -> TranslationResult:
        """
        Mock translation (deterministic).

        Strategy:
        - Reverse source text
        - Append language markers: [SRC→TGT]
        - If glossary provided: mark used_glossary=True

        Example:
            "hello world" (en→ru) → "dlrow olleh [EN→RU]"
        """
        start_time = time.time()

        # Simulate latency
        if self._simulate_latency_ms > 0:
            time.sleep(self._simulate_latency_ms / 1000.0)

        # Simulate error (if configured)
        if self._simulate_error:
            # Deterministic error: use hash of source text to decide
            text_hash = hashlib.md5(request.source_text.encode()).hexdigest()
            hash_value = int(text_hash[:8], 16) / 0xFFFFFFFF

            if hash_value < self._error_probability:
                latency_ms = int((time.time() - start_time) * 1000)
                return TranslationResult(
                    provider_id=self.provider_id,
                    error_kind=self._simulate_error,
                    error_message=f"Mock error: {self._simulate_error.value}",
                    latency_ms=latency_ms,
                )

        # Generate mock translation (deterministic)
        reversed_text = request.source_text[::-1]
        lang_marker = f"[{request.source_lang.upper()}→{request.target_lang.upper()}]"
        translated_text = f"{reversed_text} {lang_marker}"

        # Check if glossary was used
        used_glossary = request.glossary is not None

        latency_ms = int((time.time() - start_time) * 1000)

        return TranslationResult(
            translated_text=translated_text,
            provider_id=self.provider_id,
            used_glossary=used_glossary,
            cache_hit=False,
            latency_ms=latency_ms,
            meta={
                "mock_strategy": "reverse",
                "source_length": len(request.source_text),
            },
        )

    def get_model_version(self) -> str:
        return "mock-v1"

    def healthcheck(self) -> bool:
        return True
