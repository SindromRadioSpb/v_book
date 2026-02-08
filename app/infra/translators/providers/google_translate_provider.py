"""Google Translate MT provider using deep-translator.

Free, no API key required, but rate-limited.
"""

import time
import logging
from typing import Optional

from deep_translator import GoogleTranslator

from ..base_provider import (
    BaseProvider,
    TranslationRequest,
    TranslationResult,
    TranslationErrorKind,
)

logger = logging.getLogger(__name__)


# Language code mapping: ISO 639-1 → Google Translate codes
ISO_TO_GOOGLE = {
    "he": "iw",  # Hebrew: ISO uses 'he', Google uses 'iw'
    "iw": "iw",
    "en": "en",
    "ru": "ru",
    "ar": "ar",
    "es": "es",
    "fr": "fr",
    "de": "de",
    "it": "it",
    "pt": "pt",
    "zh": "zh-CN",
    "zh-CN": "zh-CN",
    "zh-TW": "zh-TW",
    "ja": "ja",
    "ko": "ko",
    "tr": "tr",
    "pl": "pl",
    "nl": "nl",
    "sv": "sv",
    "no": "no",
    "da": "da",
    "fi": "fi",
    "el": "el",
    "cs": "cs",
    "ro": "ro",
    "hu": "hu",
    "uk": "uk",
    "vi": "vi",
    "th": "th",
    "id": "id",
    "hi": "hi",
    "bn": "bn",
    "fa": "fa",
}


class GoogleTranslateProvider(BaseProvider):
    """
    Google Translate provider using deep-translator.

    Features:
    - Free (no API key required)
    - Supports 100+ languages
    - Rate-limited (use with caution for batch operations)
    - No glossary support (Google Translate API doesn't support custom glossaries in free tier)
    """

    def __init__(self):
        """Initialize Google Translate provider."""
        pass

    @property
    def provider_id(self) -> str:
        return "google_translate"

    @property
    def display_name(self) -> str:
        return "Google Translate (Free)"

    @property
    def supports_glossary(self) -> bool:
        return False  # Free tier doesn't support glossaries

    @property
    def supports_batch(self) -> bool:
        return False  # Rate-limited, better to use one-by-one

    def translate(self, request: TranslationRequest) -> TranslationResult:
        """
        Translate text using Google Translate.

        Args:
            request: Translation request

        Returns:
            Translation result
        """
        start_time = time.time()

        try:
            # Map language codes
            source_lang = ISO_TO_GOOGLE.get(request.source_lang, request.source_lang)
            target_lang = ISO_TO_GOOGLE.get(request.target_lang, request.target_lang)

            # Empty text check
            if not request.source_text or not request.source_text.strip():
                latency_ms = int((time.time() - start_time) * 1000)
                return TranslationResult(
                    translated_text="",
                    provider_id=self.provider_id,
                    used_glossary=False,
                    cache_hit=False,
                    latency_ms=latency_ms,
                )

            # Translate using deep-translator
            translator = GoogleTranslator(source=source_lang, target=target_lang)
            translated_text = translator.translate(request.source_text)

            latency_ms = int((time.time() - start_time) * 1000)

            return TranslationResult(
                translated_text=translated_text,
                provider_id=self.provider_id,
                used_glossary=False,
                cache_hit=False,
                latency_ms=latency_ms,
                meta={
                    "source_lang_mapped": source_lang,
                    "target_lang_mapped": target_lang,
                },
            )

        except Exception as e:
            logger.error(f"Google Translate error: {e}")
            latency_ms = int((time.time() - start_time) * 1000)

            # Classify error
            error_str = str(e).lower()
            if "rate limit" in error_str or "429" in error_str:
                error_kind = TranslationErrorKind.RATE_LIMIT
            elif "timeout" in error_str:
                error_kind = TranslationErrorKind.TIMEOUT
            elif "network" in error_str or "connection" in error_str:
                error_kind = TranslationErrorKind.NETWORK
            else:
                error_kind = TranslationErrorKind.UNKNOWN

            return TranslationResult(
                provider_id=self.provider_id,
                error_kind=error_kind,
                error_message=str(e),
                latency_ms=latency_ms,
            )

    def get_model_version(self) -> str:
        """Get model version (Google Translate doesn't expose this)."""
        return "google-translate-free"

    def healthcheck(self) -> bool:
        """Check if Google Translate is accessible."""
        try:
            translator = GoogleTranslator(source="en", target="es")
            result = translator.translate("hello")
            return result is not None and len(result) > 0
        except Exception as e:
            logger.warning(f"Google Translate healthcheck failed: {e}")
            return False
