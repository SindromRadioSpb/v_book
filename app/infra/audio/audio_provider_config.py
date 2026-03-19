"""Configuration schema helpers for audio providers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.services.audio_usage_tracker import AudioBudgetLimits


class AudioProviderAuthMode(Enum):
    """Authentication mode for audio providers."""

    NONE = "none"
    API_KEY = "api_key"
    SERVICE_ACCOUNT_JSON = "service_account_json"


@dataclass
class AudioProviderConfig:
    """Resolved provider config from settings."""

    provider_id: str
    enabled: bool = True
    auth_mode: AudioProviderAuthMode = AudioProviderAuthMode.NONE
    api_key_credential_id: str | None = None
    service_account_credential_id: str | None = None
    service_account_path: str | None = None
    region: str | None = None
    default_voice: str | None = None
    speech_rate: float = 1.0
    audio_format: str = "wav"
    sample_rate_hz: int = 24000
    timeout_seconds: float = 15.0
    retry_max_attempts: int = 2
    retry_backoff_base_ms: int = 500
    model_path: str | None = None
    max_chars_per_request: int = 10000
    max_requests_per_minute: int = 60
    max_chars_per_day: int | None = None
    max_chars_per_month: int | None = None
    max_requests_per_day: int | None = None
    fail_closed: bool = True

    @property
    def supports_ssml(self) -> bool:
        return self.provider_id in {"google_cloud_tts", "azure_speech_tts"}

    def has_budget_guards(self) -> bool:
        return (
            self.max_chars_per_day is not None
            or self.max_chars_per_month is not None
            or self.max_requests_per_day is not None
            or self.max_requests_per_minute is not None
        )

    def to_budget_limits(self) -> AudioBudgetLimits:
        return AudioBudgetLimits(
            max_chars_per_request=int(self.max_chars_per_request),
            max_requests_per_minute=int(self.max_requests_per_minute),
            max_chars_per_day=self.max_chars_per_day,
            max_chars_per_month=self.max_chars_per_month,
            max_requests_per_day=self.max_requests_per_day,
            fail_closed=bool(self.fail_closed),
        )


def get_enabled_key(provider_id: str) -> str:
    return f"audio/providers/{provider_id}/enabled"


def get_auth_mode_key(provider_id: str) -> str:
    return f"audio/providers/{provider_id}/auth_mode"


def get_api_key_credential_id_key(provider_id: str) -> str:
    return f"audio/providers/{provider_id}/api_key_credential_id"


def get_service_account_credential_id_key(provider_id: str) -> str:
    return f"audio/providers/{provider_id}/service_account_credential_id"


def get_service_account_path_key(provider_id: str) -> str:
    return f"audio/providers/{provider_id}/service_account_path"


def get_region_key(provider_id: str) -> str:
    return f"audio/providers/{provider_id}/region"


def get_default_voice_key(provider_id: str) -> str:
    return f"audio/providers/{provider_id}/default_voice"


def get_speech_rate_key(provider_id: str) -> str:
    return f"audio/providers/{provider_id}/speech_rate"


def get_format_key(provider_id: str) -> str:
    return f"audio/providers/{provider_id}/format"


def get_sample_rate_key(provider_id: str) -> str:
    return f"audio/providers/{provider_id}/sample_rate_hz"


def get_timeout_key(provider_id: str) -> str:
    return f"audio/providers/{provider_id}/timeout_seconds"


def get_retry_attempts_key(provider_id: str) -> str:
    return f"audio/providers/{provider_id}/retry_max_attempts"


def get_retry_backoff_key(provider_id: str) -> str:
    return f"audio/providers/{provider_id}/retry_backoff_base_ms"


def get_model_path_key(provider_id: str) -> str:
    return f"audio/providers/{provider_id}/model_path"


def get_max_chars_per_request_key(provider_id: str) -> str:
    return f"audio/providers/{provider_id}/max_chars_per_request"


def get_max_requests_per_minute_key(provider_id: str) -> str:
    return f"audio/providers/{provider_id}/max_requests_per_minute"


def get_max_chars_per_day_key(provider_id: str) -> str:
    return f"audio/providers/{provider_id}/max_chars_per_day"


def get_max_chars_per_month_key(provider_id: str) -> str:
    return f"audio/providers/{provider_id}/max_chars_per_month"


def get_max_requests_per_day_key(provider_id: str) -> str:
    return f"audio/providers/{provider_id}/max_requests_per_day"


def get_fail_closed_key(provider_id: str) -> str:
    return f"audio/providers/{provider_id}/fail_closed"


def get_api_key_credential_id(provider_id: str) -> str:
    return f"audio_provider:{provider_id}:api_key"


def get_service_account_credential_id(provider_id: str) -> str:
    return f"audio_provider:{provider_id}:service_account_json"
