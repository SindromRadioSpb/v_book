"""Microsoft Translator MT provider.

Microsoft Translator (Azure Cognitive Services Translator) is an enterprise-grade
neural machine translation service.

Configuration (QSettings keys):
- mt/microsoft/enabled: bool (default False)
- mt/microsoft/api_key: str (required, subscription key from Azure portal)
- mt/microsoft/region: str (required, Azure region e.g., "eastus", "westeurope")
- mt/microsoft/endpoint: str (default "https://api.cognitive.microsofttranslator.com")
- mt/microsoft/timeout_seconds: float (default 10.0)

Glossary Support: Yes (via Custom Translator or inline dictionary)
  - Custom Translator requires separate training workflow
  - Inline dictionary can be passed in request (supports term mapping on-the-fly)
  - For this implementation: Inline dictionary in PATCH-P1-T05
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from app.infra.translators.base_provider import (
    BaseProvider,
    TranslationErrorKind,
    TranslationRequest,
    TranslationResult,
)

logger = logging.getLogger(__name__)


class MicrosoftTranslatorProvider(BaseProvider):
    """Microsoft Translator API adapter."""

    def __init__(
        self,
        api_key: str | None = None,
        region: str | None = None,
        endpoint: str = "https://api.cognitive.microsofttranslator.com",
        timeout_seconds: float = 10.0,
    ):
        """Initialize Microsoft Translator provider.

        Args:
            api_key: Azure subscription key (required)
            region: Azure region (required, e.g., "eastus", "westeurope")
            endpoint: Microsoft Translator endpoint URL
            timeout_seconds: Request timeout in seconds
        """
        self._api_key = api_key
        self._region = region
        self._endpoint = endpoint.rstrip("/")
        self._timeout_seconds = timeout_seconds

    @property
    def provider_id(self) -> str:
        return "microsoft"

    @property
    def display_name(self) -> str:
        return "Microsoft Translator"

    @property
    def supports_glossary(self) -> bool:
        return True  # Supports inline dictionary (dynamic dictionary)

    @property
    def supports_batch(self) -> bool:
        return True  # Supports multiple text entries

    def get_model_version(self) -> str:
        """Microsoft does not expose model versions publicly."""
        return "microsoft-2024"  # Placeholder version identifier

    def translate(self, request: TranslationRequest) -> TranslationResult:
        """Translate text using Microsoft Translator API.

        Args:
            request: Translation request

        Returns:
            TranslationResult with translated text or error
        """
        start_ms = int(time.time() * 1000)

        # Check API key and region
        if not self._api_key:
            return TranslationResult(
                translated_text="",
                provider_id=self.provider_id,
                used_glossary=False,
                cache_hit=False,
                latency_ms=0,
                error_kind=TranslationErrorKind.AUTH,
                error_message="Microsoft Translator API key not configured. Please set mt/microsoft/api_key in settings.",
                meta={},
            )

        if not self._region:
            return TranslationResult(
                translated_text="",
                provider_id=self.provider_id,
                used_glossary=False,
                cache_hit=False,
                latency_ms=0,
                error_kind=TranslationErrorKind.INVALID_REQUEST,
                error_message="Microsoft Translator region not configured. Please set mt/microsoft/region in settings.",
                meta={},
            )

        # Build request payload
        # Microsoft expects array of {"text": "..."} objects
        payload = [{"text": request.source_text}]

        # TODO PATCH-P1-T05: Add inline dictionary when glossary is provided
        # if request.glossary:
        #     # Add dynamic dictionary to first text object
        #     payload[0]["dictionary"] = [...glossary entries...]

        # Build query parameters
        params = {
            "api-version": "3.0",
            "from": self._map_lang_code(request.source_lang),
            "to": self._map_lang_code(request.target_lang),
        }

        url = f"{self._endpoint}/translate?{urllib.parse.urlencode(params)}"

        # Encode payload
        data = json.dumps(payload).encode("utf-8")

        # Build request headers
        headers = {
            "Ocp-Apim-Subscription-Key": self._api_key,
            "Ocp-Apim-Subscription-Region": self._region,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-ClientTraceId": str(uuid.uuid4()),  # For request tracing
        }

        timeout = request.timeout_seconds or self._timeout_seconds

        try:
            req = urllib.request.Request(
                url,
                data=data,
                headers=headers,
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=timeout) as response:
                response_data = json.loads(response.read().decode("utf-8"))

                # Microsoft returns [{"translations": [{"text": "...", "to": "..."}], ...}]
                if not response_data or not response_data[0].get("translations"):
                    return TranslationResult(
                        translated_text="",
                        provider_id=self.provider_id,
                        used_glossary=False,
                        cache_hit=False,
                        latency_ms=int(time.time() * 1000) - start_ms,
                        error_kind=TranslationErrorKind.SERVER,
                        error_message="Microsoft Translator returned empty translations array",
                        meta={},
                    )

                translations = response_data[0]["translations"]
                translated_text = translations[0].get("text", "")

                latency_ms = int(time.time() * 1000) - start_ms

                return TranslationResult(
                    translated_text=translated_text,
                    provider_id=self.provider_id,
                    used_glossary=False,  # TODO PATCH-P1-T05: Check if dictionary was used
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
                    error_message=f"Authentication failed (HTTP {e.code}). Check API key and region.",
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
            logger.exception(f"Microsoft Translator unexpected error: {e}")
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
        """Map internal lang codes to Microsoft Translator codes.

        Microsoft uses BCP-47 language tags (similar to ISO 639-1).

        Args:
            lang: Internal language code (e.g., "he", "en", "ru")

        Returns:
            Microsoft Translator language code
        """
        # For now, pass through (assuming internal codes match BCP-47)
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
