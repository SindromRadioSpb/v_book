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
import random
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from google.api_core import exceptions as google_exceptions
from google.cloud import translate_v3
from google.oauth2 import service_account
from sqlalchemy.exc import OperationalError

from app.infra.security import CredentialStore
from app.infra.settings import SettingsService
from app.services.mt_usage_tracker import MTUsageTracker

from ..base_provider import (
    BaseProvider,
    TranslationErrorKind,
    TranslationRequest,
    TranslationResult,
)
from ..provider_config import ProviderAuthMode
from ..provider_config_manager import ProviderConfigManager

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

    # Deferred usage queue for "database is locked" windows.
    # Key: (provider_id, minute_key, day_key, month_key) -> [char_count, request_count]
    _usage_pending: dict[tuple[str, str, str, str], list[int]] = defaultdict(lambda: [0, 0])
    _usage_pending_lock = threading.Lock()
    _usage_suspend_until: float = 0.0
    _usage_queue_loaded: bool = False
    _usage_queue_path: Path | None = None
    _usage_locked_events: int = 0
    _usage_locked_chars: int = 0
    _usage_locked_requests: int = 0
    _usage_last_warning_at: float = 0.0
    _USAGE_WARNING_INTERVAL_SEC = 15.0
    _MAX_PENDING_USAGE_BUCKETS = 2000

    def __init__(
        self,
        config_manager: ProviderConfigManager | None = None,
        cred_store: CredentialStore | None = None,
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
        self._client: translate_v3.TranslationServiceClient | None = None
        self._project_id: str | None = None

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
            sa_json_str = config_mgr.get_credential(config.auth.service_account_credential_id)
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
                with open(config.auth.service_account_path) as f:
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
            logger.info(f"[{self.provider_id}] Client initialized (project: {self._project_id})")
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

                # Record usage (non-fatal; deferred on lock contention)
                self._record_usage_with_fallback(
                    trace_id=trace_id,
                    char_count=len(request.source_text),
                    request_count=1,
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
                logger.error(f"[{self.provider_id}] [{trace_id}] Quota exceeded: {e}")
                return TranslationResult(
                    provider_id=self.provider_id,
                    error_kind=TranslationErrorKind.QUOTA,
                    error_message=f"Quota exceeded: {e}",
                    latency_ms=latency_ms,
                )

            except google_exceptions.InvalidArgument as e:
                # 400 - Invalid request (bad language code, etc.)
                latency_ms = int((time.time() - start_time) * 1000)
                logger.error(f"[{self.provider_id}] [{trace_id}] Invalid request: {e}")
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

    def _usage_keys_from_dt(self, dt_utc: datetime) -> tuple[str, str, str]:
        """Build minute/day/month keys from UTC datetime."""
        return (
            dt_utc.strftime("%Y-%m-%dT%H:%M"),
            dt_utc.strftime("%Y-%m-%d"),
            dt_utc.strftime("%Y-%m"),
        )

    @classmethod
    def _get_usage_queue_path(cls) -> Path | None:
        """Get persistent queue path near the active SQLite DB."""
        if cls._usage_queue_path is not None:
            return cls._usage_queue_path

        try:
            from app.services.db_service import DBService

            db_path = DBService.get_instance().db_manager.db_path
            cls._usage_queue_path = db_path.with_suffix(".mt_usage_pending.json")
            return cls._usage_queue_path
        except Exception:
            return None

    @classmethod
    def _persist_usage_queue_locked(cls) -> None:
        """Persist deferred usage queue atomically. Lock must be held."""
        queue_path = cls._get_usage_queue_path()
        if not queue_path:
            return

        if not cls._usage_pending:
            try:
                if queue_path.exists():
                    queue_path.unlink()
            except Exception as e:
                logger.debug(f"[google_cloud_translate] Failed to cleanup usage queue file: {e}")
            return

        payload = {
            "version": 1,
            "items": [
                {
                    "provider_id": provider_id,
                    "minute_key": minute_key,
                    "day_key": day_key,
                    "month_key": month_key,
                    "char_count": delta[0],
                    "request_count": delta[1],
                }
                for (provider_id, minute_key, day_key, month_key), delta in sorted(
                    cls._usage_pending.items()
                )
            ],
        }

        temp_path = queue_path.with_suffix(queue_path.suffix + ".tmp")
        try:
            queue_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(json.dumps(payload), encoding="utf-8")
            temp_path.replace(queue_path)
        except Exception as e:
            logger.warning(f"[google_cloud_translate] Failed to persist usage queue: {e}")
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass

    @classmethod
    def _load_usage_queue_once(cls) -> None:
        """Load deferred usage queue from disk one time per process."""
        with cls._usage_pending_lock:
            if cls._usage_queue_loaded:
                return
            cls._usage_queue_loaded = True

        queue_path = cls._get_usage_queue_path()
        if not queue_path or not queue_path.exists():
            return

        try:
            payload = json.loads(queue_path.read_text(encoding="utf-8"))
            items = payload.get("items", [])
        except Exception as e:
            logger.warning(f"[google_cloud_translate] Failed to load usage queue file: {e}")
            return

        loaded = 0
        with cls._usage_pending_lock:
            for item in items:
                try:
                    key = (
                        str(item["provider_id"]),
                        str(item["minute_key"]),
                        str(item["day_key"]),
                        str(item["month_key"]),
                    )
                    chars = int(item["char_count"])
                    requests = int(item["request_count"])
                    if chars <= 0 or requests <= 0:
                        continue
                    current = cls._usage_pending[key]
                    current[0] += chars
                    current[1] += requests
                    loaded += 1
                except Exception:
                    continue

        if loaded:
            logger.info(
                f"[google_cloud_translate] Loaded {loaded} deferred usage buckets from disk"
            )

    def _consume_usage_lock_warning_locked(
        self,
        force: bool = False,
    ) -> tuple[int, int, int, int] | None:
        """Return aggregated lock warning payload and reset counters. Lock must be held."""
        cls = type(self)

        if cls._usage_locked_events <= 0:
            return None

        now_ts = time.time()
        if not force and cls._usage_last_warning_at > 0:
            if now_ts - cls._usage_last_warning_at < cls._USAGE_WARNING_INTERVAL_SEC:
                return None

        payload = (
            cls._usage_locked_events,
            cls._usage_locked_chars,
            cls._usage_locked_requests,
            len(cls._usage_pending),
        )
        cls._usage_locked_events = 0
        cls._usage_locked_chars = 0
        cls._usage_locked_requests = 0
        cls._usage_last_warning_at = now_ts
        return payload

    def _emit_usage_lock_warning_if_due(self, trace_id: str, force: bool = False) -> None:
        """Emit aggregated warning for deferred usage queueing events."""
        payload = None
        with self._usage_pending_lock:
            payload = self._consume_usage_lock_warning_locked(force=force)

        if payload:
            events, chars, requests, pending_buckets = payload
            logger.warning(
                f"[{self.provider_id}] [{trace_id}] Usage DB locked; queued {events} events "
                f"({chars} chars, {requests} req), pending buckets={pending_buckets}"
            )

    def _queue_usage_delta(
        self,
        provider_id: str,
        occurred_at_utc: datetime,
        char_count: int,
        request_count: int,
        trace_id: str = "usage-lock",
    ) -> None:
        """Queue usage delta for deferred flush when DB lock clears."""
        cls = type(self)
        minute_key, day_key, month_key = self._usage_keys_from_dt(occurred_at_utc)
        usage_key = (provider_id, minute_key, day_key, month_key)

        with cls._usage_pending_lock:
            if (
                usage_key not in cls._usage_pending
                and len(cls._usage_pending) >= cls._MAX_PENDING_USAGE_BUCKETS
            ):
                logger.warning(
                    f"[{self.provider_id}] Usage queue full ({cls._MAX_PENDING_USAGE_BUCKETS} buckets), "
                    f"dropping deferred usage bucket {usage_key[1]}"
                )
                return

            current = cls._usage_pending[usage_key]
            current[0] += char_count
            current[1] += request_count
            cls._usage_queue_loaded = True
            cls._usage_locked_events += 1
            cls._usage_locked_chars += char_count
            cls._usage_locked_requests += request_count

            cls._persist_usage_queue_locked()

        # Emit outside lock (throttled aggregate warning).
        self._emit_usage_lock_warning_if_due(trace_id=trace_id, force=False)

    def _flush_pending_usage(self, trace_id: str, force: bool = False) -> None:
        """Flush deferred usage deltas best-effort."""
        cls = type(self)
        self._load_usage_queue_once()

        now_ts = time.time()
        if not force and now_ts < cls._usage_suspend_until:
            return

        with cls._usage_pending_lock:
            if not cls._usage_pending:
                return
            pending_items = [
                (key, (delta[0], delta[1])) for key, delta in cls._usage_pending.items()
            ]

        try:
            from app.services.db_service import DBService

            with DBService.get_instance().get_session() as session:
                tracker = MTUsageTracker(session)
                for (provider_id, minute_key, day_key, month_key), (
                    chars,
                    requests,
                ) in pending_items:
                    tracker.record_spend_for_keys(
                        provider_id=provider_id,
                        minute_key=minute_key,
                        day_key=day_key,
                        month_key=month_key,
                        char_count=chars,
                        request_count=requests,
                        commit=False,
                    )
                session.commit()

            # Remove only flushed deltas. Newer concurrent queue entries stay intact.
            with cls._usage_pending_lock:
                for key, delta in pending_items:
                    current = cls._usage_pending.get(key)
                    if not current:
                        continue
                    current[0] -= delta[0]
                    current[1] -= delta[1]
                    if current[0] <= 0 and current[1] <= 0:
                        cls._usage_pending.pop(key, None)
                cls._persist_usage_queue_locked()
        except OperationalError as e:
            if "database is locked" in str(e).lower():
                # Avoid repeated blocking attempts inside same lock window.
                cls._usage_suspend_until = time.time() + 1.0
                logger.debug(
                    f"[{self.provider_id}] [{trace_id}] Deferred usage flush blocked (database locked), will retry"
                )
                return
            raise
        except Exception as e:
            logger.warning(f"[{self.provider_id}] [{trace_id}] Deferred usage flush failed: {e}")

    @classmethod
    def flush_deferred_usage_now(cls, trace_id: str = "batch-end") -> None:
        """Force flush deferred usage queue (used at batch completion)."""
        cls._load_usage_queue_once()
        cls._usage_suspend_until = 0.0

        provider = cls()
        provider._flush_pending_usage(trace_id=trace_id, force=True)
        provider._emit_usage_lock_warning_if_due(trace_id=trace_id, force=True)

    def _record_usage_with_fallback(
        self, trace_id: str, char_count: int, request_count: int
    ) -> None:
        """Record usage immediately; queue deltas when DB is locked."""
        cls = type(self)
        self._load_usage_queue_once()

        occurred_at = datetime.utcnow()
        self._flush_pending_usage(trace_id)

        try:
            from app.services.db_service import DBService

            with DBService.get_instance().get_session() as session:
                tracker = MTUsageTracker(session)
                tracker.record_spend(
                    self.provider_id,
                    char_count=char_count,
                    request_count=request_count,
                    timestamp_utc=occurred_at,
                )
        except OperationalError as e:
            if "database is locked" in str(e).lower():
                self._queue_usage_delta(
                    self.provider_id,
                    occurred_at,
                    char_count,
                    request_count,
                    trace_id=trace_id,
                )
                cls._usage_suspend_until = time.time() + 1.0
                return
            logger.error(f"[{self.provider_id}] [{trace_id}] Failed to record usage: {e}")
        except Exception as e:
            # Non-lock failures are logged but don't fail translation.
            logger.error(f"[{self.provider_id}] [{trace_id}] Failed to record usage: {e}")

    def _calculate_backoff(
        self,
        attempt: int,
        base_ms: int,
        max_ms: int,
        use_jitter: bool,
    ) -> int:
        """Calculate exponential backoff with optional jitter."""
        backoff = min(base_ms * (2**attempt), max_ms)
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
