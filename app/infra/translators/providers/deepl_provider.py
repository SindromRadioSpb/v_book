"""DeepL MT provider.

DeepL is a premium neural machine translation service with high quality output.

Configuration (QSettings keys):
- mt/deepl/enabled: bool (default False)
- mt/deepl/api_key: str (required)
- mt/deepl/api_url: str (default "https://api-free.deepl.com/v2" or "https://api.deepl.com/v2")
- mt/deepl/timeout_seconds: float (default 10.0)
- mt/deepl/formality: str (default "default", options: "default", "more", "less", "prefer_more", "prefer_less")

Glossary Support: Yes (via DeepL glossary API)
  - Glossary must be uploaded to DeepL first via separate API call
  - Requires glossary_id to be passed in request
  - For this implementation: NOT YET INTEGRATED (TODO in PATCH-P1-T05)
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


class DeepLProvider(BaseProvider):
    """DeepL API adapter."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: str = "https://api-free.deepl.com/v2",
        timeout_seconds: float = 10.0,
        formality: str = "default",
    ):
        """Initialize DeepL provider.

        Args:
            api_key: DeepL API key (required)
            api_url: DeepL API base URL (use api-free.deepl.com for Free plan,
                     api.deepl.com for Pro plan)
            timeout_seconds: Request timeout in seconds
            formality: Formality level (default, more, less, prefer_more, prefer_less)
        """
        self._api_key = api_key
        self._api_url = api_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._formality = formality

    @property
    def provider_id(self) -> str:
        return "deepl"

    @property
    def display_name(self) -> str:
        return "DeepL"

    @property
    def supports_glossary(self) -> bool:
        return True  # DeepL supports glossaries via glossary_id

    @property
    def supports_batch(self) -> bool:
        return True  # DeepL supports multiple text entries

    def get_model_version(self) -> str:
        """DeepL does not expose model versions publicly."""
        return "deepl-2024"  # Placeholder version identifier

    def translate(self, request: TranslationRequest) -> TranslationResult:
        """Translate text using DeepL API.

        Args:
            request: Translation request

        Returns:
            TranslationResult with translated text or error
        """
        start_ms = int(time.time() * 1000)

        # Check API key
        if not self._api_key:
            return TranslationResult(
                translated_text="",
                provider_id=self.provider_id,
                used_glossary=False,
                cache_hit=False,
                latency_ms=0,
                error_kind=TranslationErrorKind.AUTH,
                error_message="DeepL API key not configured. Please set mt/deepl/api_key in settings.",
                meta={},
            )

        # Build request payload
        payload = {
            "text": [request.source_text],
            "source_lang": self._map_lang_code(request.source_lang, is_source=True),
            "target_lang": self._map_lang_code(request.target_lang, is_source=False),
        }

        # Add formality if not default
        if self._formality != "default":
            payload["formality"] = self._formality

        # TODO PATCH-P1-T05: Add glossary_id when glossary is provided
        # if request.glossary:
        #     payload["glossary_id"] = <resolved_glossary_id>

        # Encode as form data (DeepL uses application/x-www-form-urlencoded)
        data = urllib.parse.urlencode(payload, doseq=True).encode("utf-8")

        # Build request
        headers = {
            "Authorization": f"DeepL-Auth-Key {self._api_key}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        timeout = request.timeout_seconds or self._timeout_seconds

        try:
            url = f"{self._api_url}/translate"
            req = urllib.request.Request(
                url,
                data=data,
                headers=headers,
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=timeout) as response:
                response_data = json.loads(response.read().decode("utf-8"))

                # DeepL returns {"translations": [{"text": "...", "detected_source_language": "..."}]}
                translations = response_data.get("translations", [])
                if not translations:
                    return TranslationResult(
                        translated_text="",
                        provider_id=self.provider_id,
                        used_glossary=False,
                        cache_hit=False,
                        latency_ms=int(time.time() * 1000) - start_ms,
                        error_kind=TranslationErrorKind.SERVER,
                        error_message="DeepL returned empty translations array",
                        meta={},
                    )

                translated_text = translations[0].get("text", "")
                detected_source = translations[0].get("detected_source_language", "")

                latency_ms = int(time.time() * 1000) - start_ms

                return TranslationResult(
                    translated_text=translated_text,
                    provider_id=self.provider_id,
                    used_glossary=False,  # TODO PATCH-P1-T05: Check if glossary was used
                    cache_hit=False,
                    latency_ms=latency_ms,
                    error_kind=None,
                    error_message=None,
                    meta={
                        "source_lang": request.source_lang,
                        "target_lang": request.target_lang,
                        "detected_source_language": detected_source,
                    },
                )

        except urllib.error.HTTPError as e:
            latency_ms = int(time.time() * 1000) - start_ms
            error_body = e.read().decode("utf-8", errors="replace")

            if e.code == 403:
                return TranslationResult(
                    translated_text="",
                    provider_id=self.provider_id,
                    used_glossary=False,
                    cache_hit=False,
                    latency_ms=latency_ms,
                    error_kind=TranslationErrorKind.AUTH,
                    error_message=f"Authentication failed (HTTP {e.code}). Check DeepL API key.",
                    meta={"http_code": e.code, "error_body": error_body[:200]},
                )
            elif e.code == 456:
                # DeepL quota exceeded
                return TranslationResult(
                    translated_text="",
                    provider_id=self.provider_id,
                    used_glossary=False,
                    cache_hit=False,
                    latency_ms=latency_ms,
                    error_kind=TranslationErrorKind.QUOTA,
                    error_message=f"DeepL quota exceeded (HTTP {e.code})",
                    meta={"http_code": e.code},
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
            logger.exception(f"DeepL unexpected error: {e}")
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

    def _map_lang_code(self, lang: str, is_source: bool) -> str:
        """Map internal lang codes to DeepL codes.

        DeepL uses specific codes with variants (e.g., EN-US, EN-GB).
        Source languages use 2-letter codes, target languages may use variants.

        Args:
            lang: Internal language code (e.g., "he", "en", "ru")
            is_source: True if source language, False if target

        Returns:
            DeepL language code
        """
        lang_upper = lang.upper()

        # Source language mapping (2-letter codes)
        if is_source:
            mapping = {
                "HE": "HE",  # Hebrew (added 2023)
                "EN": "EN",
                "RU": "RU",
                "AR": "AR",
                "ES": "ES",
                "FR": "FR",
                "DE": "DE",
            }
            return mapping.get(lang_upper, lang_upper)

        # Target language mapping (may include variants)
        # For simplicity, use generic codes unless user specifies variant
        mapping = {
            "HE": "HE",
            "EN": "EN-US",  # Default to US English
            "RU": "RU",
            "AR": "AR",
            "ES": "ES",
            "FR": "FR",
            "DE": "DE",
        }
        return mapping.get(lang_upper, lang_upper)
