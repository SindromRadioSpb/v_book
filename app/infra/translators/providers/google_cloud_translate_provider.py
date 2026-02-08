"""Google Cloud Translation API v3 (Advanced) provider.

Official Google Cloud provider with:
- Service Account JSON authentication (API key NOT supported in v3)
- Budget guards (chars/requests per minute/day/month)
- 429 retry with exponential backoff
- 403 error classification (permission/billing/quota)
- Secure credential loading from CredentialStore
- Usage tracking for fail-closed enforcement

Pricing (2026):
- Free tier: 500,000 characters/month (permanent)
- Paid: $20 per 1 million characters

Requirements:
- google-cloud-translate>=3.15.0
- google-auth>=2.28.0
- Service account JSON with roles/cloudtranslate.user

Architecture:
- Config loaded via ProviderConfigManager
- Credentials decrypted via CredentialStore
- Usage tracked in mt_usage table (PATCH-05)
"""

import json
import logging
import time
import random
from typing import Optional, Dict, Any

from google.cloud import translate_v3
from google.oauth2 import service_account
from google.api_core import exceptions as google_exceptions

from ..base_provider import (
    BaseProvider,
    TranslationRequest,
    TranslationResult,
    TranslationErrorKind,
)
from ..provider_config import ProviderAuthMode
from ..provider_config_manager import ProviderConfigManager
from app.infra.settings import SettingsService
from app.infra.security import CredentialStore
from app.services.mt_usage_tracker import MTUsageTracker

logger = logging.getLogger(__name__)


class GoogleCloudTranslateProvider(BaseProvider):
    """
    Google Cloud Translation API v3 (Advanced) provider.

    Features:
    - Official Google Cloud API (guaranteed SLA)
    - Service Account JSON authentication
    - Budget guards (fail-closed on limit exceeded)
    - 429 retry with exponential backoff + jitter
    - 403 classification (permission/billing/quota)

    Limitations:
    - API key auth NOT supported (v3 requires OAuth/SA)
    - Glossaries require separate setup (not implemented yet)
    - Requires Google Cloud project + billing enabled
    """

    def __init__(
        self,
        config_manager: Optional[ProviderConfigManager] = None,
        cred_store: Optional[CredentialStore] = None,
    ):
        """Initialize provider.

        Args:
            config_manager: Optional config manager (auto-created if None)
            cred_store: Optional credential store (auto-created if None)

        Note:
            In production, config_manager and cred_store should be provided.
            Auto-creation is for convenience in simple use cases.
            Usage tracking creates a new DB session when needed (if DBService available).
        """
        self._config_manager = config_manager
        self._cred_store = cred_store
        self._client: Optional[translate_v3.TranslationServiceClient] = None
        self._project_id: Optional[str] = None

    @property
    def provider_id(self) -> str:
        return "google_cloud_translate"

    @property
    def display_name(self) -> str:
        return "Google Cloud Translate (Official v3)"

    @property
    def supports_glossary(self) -> bool:
        return False  # TODO: Implement glossary support

    @property
    def supports_batch(self) -> bool:
        return False  # One-by-one translation for now

    def _get_config_manager(self) -> ProviderConfigManager:
        """Get or create config manager."""
        if self._config_manager is None:
            settings = SettingsService.get_instance()
            # Note: CredentialStore will be None, caller must provide if needed
            self._config_manager = ProviderConfigManager(settings)
        return self._config_manager

    def _initialize_client(self) -> None:
        """
        Initialize Google Cloud Translation client from config.

        Loads service account JSON from CredentialStore and creates client.

        Raises:
            TranslationResult with error if initialization fails
        """
        if self._client is not None:
            return  # Already initialized

        config_mgr = self._get_config_manager()
        config = config_mgr.load_config(self.provider_id)

        # Check auth mode
        if config.auth.mode == ProviderAuthMode.API_KEY:
            # API key NOT supported in v3
            error_msg = (
                "Google Cloud Translation API v3 requires Service Account JSON. "
                "API keys are only supported in v2 (Basic). "
                "Please configure Service Account credentials in MT Provider Settings."
            )
            logger.error(f"[{self.provider_id}] {error_msg}")
            raise ValueError(error_msg)

        if config.auth.mode == ProviderAuthMode.NONE:
            error_msg = (
                f"Authentication not configured for '{self.provider_id}'. "
                f"Please configure Service Account JSON in MT Provider Settings."
            )
            logger.error(f"[{self.provider_id}] {error_msg}")
            raise ValueError(error_msg)

        # Load service account JSON from CredentialStore
        if config.auth.service_account_credential_id:
            # Load from encrypted DB
            sa_json_str = config_mgr.get_credential(
                config.auth.service_account_credential_id
            )
            if not sa_json_str:
                error_msg = (
                    f"Service Account JSON not found in credential store "
                    f"(ID: {config.auth.service_account_credential_id}). "
                    f"Please configure credentials in MT Provider Settings."
                )
                logger.error(f"[{self.provider_id}] {error_msg}")
                raise ValueError(error_msg)

            try:
                sa_info = json.loads(sa_json_str)
            except json.JSONDecodeError as e:
                error_msg = f"Invalid Service Account JSON: {e}"
                logger.error(f"[{self.provider_id}] {error_msg}")
                raise ValueError(error_msg)

        elif config.auth.service_account_path:
            # Load from file
            try:
                with open(config.auth.service_account_path, 'r') as f:
                    sa_info = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError) as e:
                error_msg = (
                    f"Failed to load Service Account JSON from "
                    f"{config.auth.service_account_path}: {e}"
                )
                logger.error(f"[{self.provider_id}] {error_msg}")
                raise ValueError(error_msg)
        else:
            error_msg = "Service Account not configured (no credential ID or path)"
            logger.error(f"[{self.provider_id}] {error_msg}")
            raise ValueError(error_msg)

        # Extract project ID from SA JSON
        self._project_id = sa_info.get("project_id")
        if not self._project_id:
            error_msg = "Service Account JSON missing 'project_id' field"
            logger.error(f"[{self.provider_id}] {error_msg}")
            raise ValueError(error_msg)

        # Create credentials
        try:
            credentials = service_account.Credentials.from_service_account_info(sa_info)
        except Exception as e:
            error_msg = f"Failed to create credentials from Service Account JSON: {e}"
            logger.error(f"[{self.provider_id}] {error_msg}")
            raise ValueError(error_msg)

        # Create client
        try:
            self._client = translate_v3.TranslationServiceClient(credentials=credentials)
            logger.info(
                f"[{self.provider_id}] Client initialized (project: {self._project_id})"
            )
        except Exception as e:
            error_msg = f"Failed to create Translation API client: {e}"
            logger.error(f"[{self.provider_id}] {error_msg}")
            raise ValueError(error_msg)

    def translate(self, request: TranslationRequest) -> TranslationResult:
        """
        Translate text using Google Cloud Translation API v3.

        Flow:
        1. Initialize client (lazy, once)
        2. Check budget guards (if configured)
        3. Call API with retry on 429
        4. Classify errors (403 → permission/billing/quota)
        5. Return result (NO secrets in logs, NO full text)

        Args:
            request: Translation request

        Returns:
            TranslationResult with translation or error

        Note:
            MUST NOT raise exceptions - return TranslationResult with error_kind
        """
        start_time = time.time()
        trace_id = request.trace_id or f"gct-{int(time.time() * 1000)}"

        # Empty text check
        if not request.source_text or not request.source_text.strip():
            return TranslationResult(
                translated_text="",
                provider_id=self.provider_id,
                latency_ms=int((time.time() - start_time) * 1000),
            )

        # Initialize client (may raise ValueError on config error)
        try:
            self._initialize_client()
        except ValueError as e:
            return TranslationResult(
                provider_id=self.provider_id,
                error_kind=TranslationErrorKind.AUTH,
                error_message=str(e),
                latency_ms=int((time.time() - start_time) * 1000),
            )

        # Load config for limits and retry policy
        config_mgr = self._get_config_manager()
        config = config_mgr.load_config(self.provider_id)

        # Check budget guards (per-request limit)
        char_count = len(request.source_text)
        if char_count > config.limits.max_chars_per_request:
            error_msg = (
                f"Text too long: {char_count} chars "
                f"(max {config.limits.max_chars_per_request} chars per request)"
            )
            logger.warning(f"[{self.provider_id}] [{trace_id}] {error_msg}")
            return TranslationResult(
                provider_id=self.provider_id,
                error_kind=TranslationErrorKind.INVALID_REQUEST,
                error_message=error_msg,
                latency_ms=int((time.time() - start_time) * 1000),
            )

        # Check usage tracking (chars per day/month, requests per minute)
        if config.limits.has_budget_guards():
            try:
                from app.services.db_service import DBService

                with DBService.get_instance().get_session() as session:
                    tracker = MTUsageTracker(session)
                    allowed, error_msg = tracker.can_spend(
                        self.provider_id, char_count, config.limits
                    )
                    if not allowed:
                        logger.warning(
                            f"[{self.provider_id}] [{trace_id}] Budget limit exceeded: {error_msg}"
                        )
                        return TranslationResult(
                            provider_id=self.provider_id,
                            error_kind=TranslationErrorKind.RATE_LIMIT,
                            error_message=error_msg,
                            latency_ms=int((time.time() - start_time) * 1000),
                        )
            except Exception as e:
                logger.warning(
                    f"[{self.provider_id}] [{trace_id}] Failed to check usage tracking: {e}. "
                    f"Proceeding with translation (usage tracking bypassed)."
                )

        # Translate with retry
        result = self._translate_with_retry(request, config, trace_id, start_time)

        return result

    def _translate_with_retry(
        self,
        request: TranslationRequest,
        config,
        trace_id: str,
        start_time: float,
    ) -> TranslationResult:
        """
        Translate with exponential backoff retry on 429.

        Args:
            request: Translation request
            config: Provider config (limits, retry policy)
            trace_id: Trace ID for logging
            start_time: Start time for latency calculation

        Returns:
            TranslationResult
        """
        retry_policy = config.retry
        attempt = 0

        while attempt <= retry_policy.max_retries:
            try:
                # Build API request
                parent = f"projects/{self._project_id}/locations/global"
                api_request = {
                    "parent": parent,
                    "contents": [request.source_text],
                    "source_language_code": request.source_lang,
                    "target_language_code": request.target_lang,
                    "mime_type": "text/plain",
                }

                # Call API
                logger.debug(
                    f"[{self.provider_id}] [{trace_id}] API call "
                    f"(attempt {attempt + 1}/{retry_policy.max_retries + 1}, "
                    f"chars: {len(request.source_text)})"
                )

                response = self._client.translate_text(request=api_request)

                # Extract translation
                if response.translations:
                    translated_text = response.translations[0].translated_text
                else:
                    translated_text = ""

                latency_ms = int((time.time() - start_time) * 1000)

                logger.info(
                    f"[{self.provider_id}] [{trace_id}] Success "
                    f"(chars: {len(request.source_text)}, latency: {latency_ms}ms)"
                )

                # Record usage (if DBService available)
                try:
                    from app.services.db_service import DBService

                    with DBService.get_instance().get_session() as session:
                        tracker = MTUsageTracker(session)
                        tracker.record_spend(
                            self.provider_id,
                            char_count=len(request.source_text),
                            request_count=1,
                        )
                except Exception as e:
                    # Don't fail translation if usage tracking fails
                    logger.error(
                        f"[{self.provider_id}] [{trace_id}] "
                        f"Failed to record usage: {e}"
                    )

                return TranslationResult(
                    translated_text=translated_text,
                    provider_id=self.provider_id,
                    latency_ms=latency_ms,
                    meta={
                        "detected_language": (
                            response.translations[0].detected_language_code
                            if response.translations
                            else None
                        ),
                        "attempt": attempt + 1,
                    },
                )

            except google_exceptions.TooManyRequests as e:
                # 429 - Rate limit exceeded
                latency_ms = int((time.time() - start_time) * 1000)

                if not retry_policy.should_retry(429, attempt):
                    logger.error(
                        f"[{self.provider_id}] [{trace_id}] Rate limit exceeded "
                        f"(max retries reached: {attempt})"
                    )
                    return TranslationResult(
                        provider_id=self.provider_id,
                        error_kind=TranslationErrorKind.RATE_LIMIT,
                        error_message=f"Rate limit exceeded (429): {e}",
                        latency_ms=latency_ms,
                    )

                # Calculate backoff
                backoff_ms = self._calculate_backoff(
                    attempt,
                    retry_policy.base_backoff_ms,
                    retry_policy.max_backoff_ms,
                    retry_policy.use_jitter,
                )

                logger.warning(
                    f"[{self.provider_id}] [{trace_id}] Rate limit (429), "
                    f"retry in {backoff_ms}ms (attempt {attempt + 1})"
                )

                time.sleep(backoff_ms / 1000.0)
                attempt += 1
                continue

            except google_exceptions.PermissionDenied as e:
                # 403 - Permission denied
                latency_ms = int((time.time() - start_time) * 1000)
                error_msg = self._classify_403_error(str(e))
                logger.error(f"[{self.provider_id}] [{trace_id}] {error_msg}")
                return TranslationResult(
                    provider_id=self.provider_id,
                    error_kind=TranslationErrorKind.AUTH,
                    error_message=error_msg,
                    latency_ms=latency_ms,
                )

            except google_exceptions.ResourceExhausted as e:
                # Quota exceeded (could be 403 or 429 depending on quota type)
                latency_ms = int((time.time() - start_time) * 1000)
                logger.error(
                    f"[{self.provider_id}] [{trace_id}] Quota exceeded: {e}"
                )
                return TranslationResult(
                    provider_id=self.provider_id,
                    error_kind=TranslationErrorKind.QUOTA,
                    error_message=f"Quota exceeded: {e}",
                    latency_ms=latency_ms,
                )

            except google_exceptions.InvalidArgument as e:
                # 400 - Invalid request (bad language code, etc.)
                latency_ms = int((time.time() - start_time) * 1000)
                logger.error(
                    f"[{self.provider_id}] [{trace_id}] Invalid request: {e}"
                )
                return TranslationResult(
                    provider_id=self.provider_id,
                    error_kind=TranslationErrorKind.INVALID_REQUEST,
                    error_message=f"Invalid request: {e}",
                    latency_ms=latency_ms,
                )

            except Exception as e:
                # Catch-all for unexpected errors
                latency_ms = int((time.time() - start_time) * 1000)
                logger.error(
                    f"[{self.provider_id}] [{trace_id}] Unexpected error: {e}",
                    exc_info=True,
                )
                return TranslationResult(
                    provider_id=self.provider_id,
                    error_kind=TranslationErrorKind.UNKNOWN,
                    error_message=f"Unexpected error: {e}",
                    latency_ms=latency_ms,
                )

        # Should not reach here, but just in case
        latency_ms = int((time.time() - start_time) * 1000)
        return TranslationResult(
            provider_id=self.provider_id,
            error_kind=TranslationErrorKind.UNKNOWN,
            error_message="Retry loop exited unexpectedly",
            latency_ms=latency_ms,
        )

    def _calculate_backoff(
        self,
        attempt: int,
        base_ms: int,
        max_ms: int,
        use_jitter: bool,
    ) -> int:
        """Calculate exponential backoff with optional jitter."""
        backoff = min(base_ms * (2 ** attempt), max_ms)
        if use_jitter:
            # Add +/- 25% jitter
            jitter = random.uniform(0.75, 1.25)
            backoff = int(backoff * jitter)
        return backoff

    def _classify_403_error(self, error_message: str) -> str:
        """
        Classify 403 error into specific categories.

        Returns user-friendly error message with actionable guidance.
        """
        error_lower = error_message.lower()

        if "permission" in error_lower or "denied" in error_lower:
            return (
                "Permission denied: Service account lacks required permissions. "
                "Ensure it has 'roles/cloudtranslate.user' role in IAM settings."
            )
        elif "billing" in error_lower:
            return (
                "Billing not enabled: Please enable billing for your Google Cloud project. "
                "Visit: https://console.cloud.google.com/billing"
            )
        elif "quota" in error_lower or "limit" in error_lower:
            return (
                "Quota exceeded: Monthly or daily quota limit reached. "
                "Check quota usage in Google Cloud Console or upgrade your plan."
            )
        elif "api" in error_lower and ("disabled" in error_lower or "not enabled" in error_lower):
            return (
                "Translation API not enabled: Enable Cloud Translation API in your project. "
                "Visit: https://console.cloud.google.com/apis/library/translate.googleapis.com"
            )
        else:
            return f"Authorization error (403): {error_message}"

    def get_model_version(self) -> str:
        """Get model version (v3 Advanced uses NMT models)."""
        return "google-cloud-translate-v3-nmt"

    def healthcheck(self) -> bool:
        """
        Check if provider is healthy (can initialize + has valid credentials).

        Returns:
            True if provider can be initialized, False otherwise
        """
        try:
            self._initialize_client()
            return self._client is not None
        except Exception as e:
            logger.warning(f"[{self.provider_id}] Healthcheck failed: {e}")
            return False
