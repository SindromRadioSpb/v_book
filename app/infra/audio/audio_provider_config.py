"""Configuration schema helpers for audio providers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


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
    api_key_credential_id: Optional[str] = None
    service_account_credential_id: Optional[str] = None
    service_account_path: Optional[str] = None
    region: Optional[str] = None
    default_voice: Optional[str] = None
    audio_format: str = "wav"
    sample_rate_hz: int = 24000
    timeout_seconds: float = 15.0
    retry_max_attempts: int = 2
    retry_backoff_base_ms: int = 500
    model_path: Optional[str] = None

    @property
    def supports_ssml(self) -> bool:
        return self.provider_id in {"google_cloud_tts", "azure_speech_tts"}


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


def get_api_key_credential_id(provider_id: str) -> str:
    return f"audio_provider:{provider_id}:api_key"


def get_service_account_credential_id(provider_id: str) -> str:
    return f"audio_provider:{provider_id}:service_account_json"
