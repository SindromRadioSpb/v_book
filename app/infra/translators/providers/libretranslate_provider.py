"""LibreTranslate MT provider.

LibreTranslate is an open-source machine translation service that can be
self-hosted or accessed via libre.translate.com.

Configuration (QSettings keys):
- mt/libretranslate/enabled: bool (default False)
- mt/libretranslate/api_url: str (default "https://libretranslate.com/translate")
- mt/libretranslate/api_key: str (optional, required for libre.translate.com)
- mt/libretranslate/timeout_seconds: float (default 10.0)

Glossary Support: No (LibreTranslate does not support glossaries natively)
"""
import json
import logging
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional

from app.infra.translators.base_provider import (
    BaseProvider,
    TranslationRequest,
    TranslationResult,
    TranslationErrorKind,
)

logger = logging.getLogger(__name__)


class LibreTranslateProvider(BaseProvider):
    """LibreTranslate API adapter."""

    def __init__(
        self,
        api_url: str = "https://libretranslate.com/translate",
        api_key: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ):
        """Initialize LibreTranslate provider.

        Args:
            api_url: LibreTranslate API endpoint URL
            api_key: API key (required for libre.translate.com, optional for self-hosted)
            timeout_seconds: Request timeout in seconds
        """
        self._api_url = api_url
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    @property
    def provider_id(self) -> str:
        return "libretranslate"

    @property
    def display_name(self) -> str:
        return "LibreTranslate"

    @property
    def supports_glossary(self) -> bool:
        return False

    @property
    def supports_batch(self) -> bool:
        return False

    def get_model_version(self) -> str:
        """LibreTranslate uses Argos Translate models, version varies by deployment."""
        return "argos-1.9"  # Placeholder, actual version depends on deployment

    def translate(self, request: TranslationRequest) -> TranslationResult:
        """Translate text using LibreTranslate API.

        Args:
            request: Translation request

        Returns:
            TranslationResult with translated text or error
        """
        start_ms = int(time.time() * 1000)

        # Build request payload
        payload = {
            "q": request.source_text,
            "source": self._map_lang_code(request.source_lang),
            "target": self._map_lang_code(request.target_lang),
            "format": "text",
        }

        # Add API key if configured
        if self._api_key:
            payload["api_key"] = self._api_key

        # Encode payload
        data = json.dumps(payload).encode("utf-8")

        # Build request
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        timeout = request.timeout_seconds or self._timeout_seconds

        try:
            req = urllib.request.Request(
                self._api_url,
                data=data,
                headers=headers,
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=timeout) as response:
                response_data = json.loads(response.read().decode("utf-8"))

                translated_text = response_data.get("translatedText", "")

                latency_ms = int(time.time() * 1000) - start_ms

                return TranslationResult(
                    translated_text=translated_text,
                    provider_id=self.provider_id,
                    used_glossary=False,  # LibreTranslate does not support glossary
                    cache_hit=False,
                    latency_ms=latency_ms,
                    error_kind=None,
                    error_message=None,
                    meta={
                        "source_lang": request.source_lang,
                        "target_lang": request.target_lang,
                    },
                )

        except urllib.error.HTTPError as e:
            latency_ms = int(time.time() * 1000) - start_ms
            error_body = e.read().decode("utf-8", errors="replace")

            if e.code == 401 or e.code == 403:
                return TranslationResult(
                    translated_text="",
                    provider_id=self.provider_id,
                    used_glossary=False,
                    cache_hit=False,
                    latency_ms=latency_ms,
                    error_kind=TranslationErrorKind.AUTH,
                    error_message=f"Authentication failed (HTTP {e.code}). Check API key configuration.",
                    meta={"http_code": e.code, "error_body": error_body[:200]},
                )
            elif e.code == 429:
                return TranslationResult(
                    translated_text="",
                    provider_id=self.provider_id,
                    used_glossary=False,
                    cache_hit=False,
                    latency_ms=latency_ms,
                    error_kind=TranslationErrorKind.RATE_LIMIT,
                    error_message=f"Rate limit exceeded (HTTP {e.code})",
                    meta={"http_code": e.code},
                )
            elif e.code == 400:
                return TranslationResult(
                    translated_text="",
                    provider_id=self.provider_id,
                    used_glossary=False,
                    cache_hit=False,
                    latency_ms=latency_ms,
                    error_kind=TranslationErrorKind.INVALID_REQUEST,
                    error_message=f"Invalid request (HTTP {e.code}): {error_body[:100]}",
                    meta={"http_code": e.code, "error_body": error_body[:200]},
                )
            else:
                return TranslationResult(
                    translated_text="",
                    provider_id=self.provider_id,
                    used_glossary=False,
                    cache_hit=False,
                    latency_ms=latency_ms,
                    error_kind=TranslationErrorKind.SERVER,
                    error_message=f"Server error (HTTP {e.code})",
                    meta={"http_code": e.code, "error_body": error_body[:200]},
                )

        except urllib.error.URLError as e:
            latency_ms = int(time.time() * 1000) - start_ms
            return TranslationResult(
                translated_text="",
                provider_id=self.provider_id,
                used_glossary=False,
                cache_hit=False,
                latency_ms=latency_ms,
                error_kind=TranslationErrorKind.NETWORK,
                error_message=f"Network error: {str(e.reason)[:100]}",
                meta={},
            )

        except Exception as e:
            latency_ms = int(time.time() * 1000) - start_ms
            logger.exception(f"LibreTranslate unexpected error: {e}")
            return TranslationResult(
                translated_text="",
                provider_id=self.provider_id,
                used_glossary=False,
                cache_hit=False,
                latency_ms=latency_ms,
                error_kind=TranslationErrorKind.UNKNOWN,
                error_message=f"Unexpected error: {str(e)[:100]}",
                meta={},
            )

    def _map_lang_code(self, lang: str) -> str:
        """Map internal lang codes to LibreTranslate codes.

        LibreTranslate uses ISO 639-1 codes (2-letter).

        Args:
            lang: Internal language code (e.g., "he", "en", "ru")

        Returns:
            LibreTranslate language code
        """
        # For now, pass through (assuming internal codes are ISO 639-1)
        # Add mappings here if internal codes differ
        mapping = {
            "he": "he",
            "en": "en",
            "ru": "ru",
            "ar": "ar",
            "es": "es",
            "fr": "fr",
            "de": "de",
        }
        return mapping.get(lang.lower(), lang.lower())
