"""Provider configuration schema for MT providers.

Unified configuration classes for authentication, limits, retry policy, and UI metadata.
All providers can use these dataclasses for consistent configuration and UI rendering.

Architecture:
- ProviderAuthConfig: Authentication mode and credential references
- ProviderLimitsConfig: Budget guards (chars/requests per minute/day/month)
- ProviderRetryPolicy: Retry behavior on failures (429, 503, etc.)
- ProviderUiMeta: UI display metadata (name, capabilities)

Backward Compatibility:
- Existing providers (google_translate, deepl, etc.) default to auth_mode="none"
- Limits optional (providers can use defaults)
- Settings stored in SettingsService (QSettings, INI format)
- Credentials stored in CredentialStore (OS keyring + encrypted DB)
"""

from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum


class ProviderAuthMode(Enum):
    """Authentication mode for MT provider."""

    NONE = "none"  # No authentication required (e.g., local NLLB, free scraping)
    API_KEY = "api_key"  # API key authentication
    SERVICE_ACCOUNT_JSON = "service_account_json"  # Google Cloud service account JSON


@dataclass
class ProviderAuthConfig:
    """
    Authentication configuration for a provider.

    Credential Storage:
    - API keys/JSON stored in CredentialStore (OS keyring + encrypted DB)
    - Credential IDs format: "mt_provider:<provider_id>:api_key" or ":service_account_json"
    - Never store plaintext credentials in QSettings or logs

    Example (Google Cloud Translate v3):
        auth = ProviderAuthConfig(
            mode=ProviderAuthMode.SERVICE_ACCOUNT_JSON,
            service_account_credential_id="mt_provider:google_cloud_translate:service_account_json",
        )
    """

    mode: ProviderAuthMode = ProviderAuthMode.NONE

    # Credential IDs (references to CredentialStore)
    api_key_credential_id: Optional[str] = None
    service_account_credential_id: Optional[str] = None

    # Optional: Path to service account JSON file (alternative to storing in CredentialStore)
    # Use this if user prefers file-based SA JSON instead of DB storage
    service_account_path: Optional[str] = None

    def is_configured(self) -> bool:
        """Check if authentication is properly configured."""
        if self.mode == ProviderAuthMode.NONE:
            return True
        elif self.mode == ProviderAuthMode.API_KEY:
            return self.api_key_credential_id is not None
        elif self.mode == ProviderAuthMode.SERVICE_ACCOUNT_JSON:
            return (
                self.service_account_credential_id is not None
                or self.service_account_path is not None
            )
        return False


@dataclass
class ProviderLimitsConfig:
    """
    Budget guards and rate limits for a provider.

    Purpose:
    - Prevent cost overruns for paid APIs
    - Respect free tier quotas
    - Avoid rate limiting (429 errors)

    Enforcement:
    - Before each translation: check len(text) vs limits
    - Query mt_usage table for current counters (minute/day/month buckets)
    - If exceeded: fail-closed (return error, do NOT translate)
    - After success: increment counters atomically

    Example (Google Cloud Translate - stay in free tier):
        limits = ProviderLimitsConfig(
            max_chars_per_request=10000,  # API limit
            max_chars_per_month=500000,   # Free tier: 500k chars/month
            fail_closed=True,              # Strict enforcement
        )
    """

    # Per-request limits
    max_chars_per_request: int = 10000  # Safe default for most APIs

    # Rate limits (requests)
    max_requests_per_minute: int = 60  # Conservative default
    max_requests_per_hour: Optional[int] = None  # Optional
    max_requests_per_day: Optional[int] = None  # Optional

    # Rate limits (characters)
    max_chars_per_minute: Optional[int] = None  # Optional
    max_chars_per_hour: Optional[int] = None  # Optional
    max_chars_per_day: Optional[int] = None  # Optional
    max_chars_per_month: Optional[int] = None  # For free tier enforcement

    # Behavior on limit exceeded
    fail_closed: bool = True  # If True, reject translation when limit exceeded
    # If False, attempt translation anyway (may hit 429/403)

    def has_budget_guards(self) -> bool:
        """Check if any budget guards are configured."""
        return (
            self.max_chars_per_day is not None
            or self.max_chars_per_month is not None
            or self.max_requests_per_day is not None
        )


@dataclass
class ProviderRetryPolicy:
    """
    Retry policy for transient failures (429, 503, network errors).

    Strategy:
    - Exponential backoff with jitter to avoid thundering herd
    - Respect Retry-After header if present (429 responses)
    - Fail fast for permanent errors (403 permission, 401 auth, 400 bad request)

    Example (Google Cloud Translate):
        retry = ProviderRetryPolicy(
            max_retries=3,
            base_backoff_ms=1000,  # 1s, 2s, 4s
            max_backoff_ms=10000,
            retry_on_status=[429, 503],  # Rate limit + service unavailable
        )
    """

    max_retries: int = 3  # Total attempts = 1 + max_retries (default: 4 attempts)

    # Backoff parameters (exponential: base * 2^attempt)
    base_backoff_ms: int = 1000  # 1 second
    max_backoff_ms: int = 10000  # 10 seconds cap

    # Which HTTP status codes to retry
    retry_on_status: List[int] = field(
        default_factory=lambda: [429, 503]  # Rate limit, service unavailable
    )

    # Add jitter to prevent thundering herd
    use_jitter: bool = True

    def should_retry(self, status_code: int, attempt: int) -> bool:
        """Check if request should be retried based on status and attempt count."""
        if attempt >= self.max_retries:
            return False
        return status_code in self.retry_on_status


@dataclass
class ProviderUiMeta:
    """
    UI display metadata for a provider.

    Used for dynamic UI rendering (provider lists, settings dialogs, etc.).

    Example:
        ui_meta = ProviderUiMeta(
            display_name="Google Cloud Translate (Official v3)",
            description="Official Google Cloud Translation API with guaranteed SLA",
            supports_auth=True,
            supports_limits=True,
            supports_force=True,
            supports_chain=True,
            default_enabled=False,  # Requires credentials
        )
    """

    display_name: str  # Human-readable name
    description: str = ""  # Optional description for tooltips

    # Capabilities
    supports_auth: bool = False  # Shows auth UI section
    supports_limits: bool = False  # Shows limits UI section
    supports_retry: bool = True  # Shows retry policy UI section
    supports_glossary: bool = False  # Provider supports glossaries

    # UI visibility
    supports_force: bool = True  # Can be used in force provider mode
    supports_chain: bool = True  # Can be used in provider chain

    # Defaults
    default_enabled: bool = True  # Enabled by default in new installations
    default_rate_limit: int = 60  # Default requests per minute


@dataclass
class ProviderConfig:
    """
    Complete configuration for a provider (convenience wrapper).

    Aggregates auth, limits, retry, and UI metadata into a single config object.

    Example (Google Cloud Translate):
        config = ProviderConfig(
            provider_id="google_cloud_translate",
            auth=ProviderAuthConfig(
                mode=ProviderAuthMode.SERVICE_ACCOUNT_JSON,
                service_account_credential_id="mt_provider:google_cloud_translate:service_account_json",
            ),
            limits=ProviderLimitsConfig(
                max_chars_per_month=500000,  # Free tier
                fail_closed=True,
            ),
            retry=ProviderRetryPolicy(max_retries=3),
            ui_meta=ProviderUiMeta(
                display_name="Google Cloud Translate (Official v3)",
                supports_auth=True,
                supports_limits=True,
                default_enabled=False,
            ),
        )
    """

    provider_id: str  # Unique provider ID (lowercase, alphanumeric + underscore)

    auth: ProviderAuthConfig = field(default_factory=ProviderAuthConfig)
    limits: ProviderLimitsConfig = field(default_factory=ProviderLimitsConfig)
    retry: ProviderRetryPolicy = field(default_factory=ProviderRetryPolicy)
    ui_meta: Optional[ProviderUiMeta] = None


# =============================================================================
# Settings Keys (for SettingsService / QSettings)
# =============================================================================

def get_auth_mode_key(provider_id: str) -> str:
    """Get QSettings key for auth mode."""
    return f"mt/providers/{provider_id}/auth_mode"


def get_api_key_credential_id_key(provider_id: str) -> str:
    """Get QSettings key for API key credential ID."""
    return f"mt/providers/{provider_id}/api_key_credential_id"


def get_service_account_credential_id_key(provider_id: str) -> str:
    """Get QSettings key for service account credential ID."""
    return f"mt/providers/{provider_id}/service_account_credential_id"


def get_service_account_path_key(provider_id: str) -> str:
    """Get QSettings key for service account file path."""
    return f"mt/providers/{provider_id}/service_account_path"


def get_max_chars_per_request_key(provider_id: str) -> str:
    """Get QSettings key for max chars per request."""
    return f"mt/providers/{provider_id}/max_chars_per_request"


def get_max_requests_per_minute_key(provider_id: str) -> str:
    """Get QSettings key for max requests per minute."""
    return f"mt/providers/{provider_id}/max_requests_per_minute"


def get_max_chars_per_day_key(provider_id: str) -> str:
    """Get QSettings key for max chars per day."""
    return f"mt/providers/{provider_id}/max_chars_per_day"


def get_max_chars_per_month_key(provider_id: str) -> str:
    """Get QSettings key for max chars per month."""
    return f"mt/providers/{provider_id}/max_chars_per_month"


def get_fail_closed_key(provider_id: str) -> str:
    """Get QSettings key for fail-closed behavior."""
    return f"mt/providers/{provider_id}/fail_closed"


def get_enabled_key(provider_id: str) -> str:
    """Get QSettings key for enabled status."""
    return f"mt/providers/{provider_id}/enabled"


def get_rate_limit_key(provider_id: str) -> str:
    """Get QSettings key for rate limit (legacy, for backward compatibility)."""
    return f"mt/providers/{provider_id}/rate_limit"


# =============================================================================
# Credential ID Helpers
# =============================================================================

def get_api_key_credential_id(provider_id: str) -> str:
    """Get credential ID for API key in CredentialStore."""
    return f"mt_provider:{provider_id}:api_key"


def get_service_account_credential_id(provider_id: str) -> str:
    """Get credential ID for service account JSON in CredentialStore."""
    return f"mt_provider:{provider_id}:service_account_json"
