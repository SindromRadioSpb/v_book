"""Config manager for audio providers (settings + secure credentials)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from app.infra.security import CredentialStore
from app.infra.settings import SettingsService
from app.services.db_service import DBService

from .audio_provider_config import (
    AudioProviderAuthMode,
    AudioProviderConfig,
    get_api_key_credential_id,
    get_api_key_credential_id_key,
    get_auth_mode_key,
    get_default_voice_key,
    get_enabled_key,
    get_format_key,
    get_region_key,
    get_model_path_key,
    get_retry_attempts_key,
    get_retry_backoff_key,
    get_sample_rate_key,
    get_service_account_credential_id,
    get_service_account_credential_id_key,
    get_service_account_path_key,
    get_timeout_key,
)

logger = logging.getLogger(__name__)


class AudioProviderConfigManager:
    """Load/save audio provider configuration and credentials."""

    def __init__(
        self,
        settings: Optional[SettingsService] = None,
        cred_store: Optional[CredentialStore] = None,
    ):
        self.settings = settings or SettingsService.get_instance()
        self.cred_store = cred_store

    def load_config(self, provider_id: str) -> AudioProviderConfig:
        """Resolve provider config with conservative defaults."""
        defaults = self._defaults(provider_id)

        auth_mode_raw = self.settings.get_string(
            get_auth_mode_key(provider_id),
            defaults.auth_mode.value,
        )
        try:
            auth_mode = AudioProviderAuthMode(auth_mode_raw)
        except Exception:
            auth_mode = defaults.auth_mode

        api_key_cred_id = self.settings.get_string(
            get_api_key_credential_id_key(provider_id),
            defaults.api_key_credential_id or "",
        ).strip() or None

        service_account_cred_id = self.settings.get_string(
            get_service_account_credential_id_key(provider_id),
            defaults.service_account_credential_id or "",
        ).strip() or None

        service_account_path = self.settings.get_string(
            get_service_account_path_key(provider_id),
            defaults.service_account_path or "",
        ).strip() or None

        return AudioProviderConfig(
            provider_id=provider_id,
            enabled=self.settings.get_bool(get_enabled_key(provider_id), defaults.enabled),
            auth_mode=auth_mode,
            api_key_credential_id=api_key_cred_id,
            service_account_credential_id=service_account_cred_id,
            service_account_path=service_account_path,
            region=self.settings.get_string(get_region_key(provider_id), defaults.region or "").strip() or None,
            default_voice=self.settings.get_string(
                get_default_voice_key(provider_id), defaults.default_voice or ""
            ).strip()
            or None,
            audio_format=self.settings.get_string(get_format_key(provider_id), defaults.audio_format).strip()
            or defaults.audio_format,
            sample_rate_hz=max(8000, self.settings.get_int(get_sample_rate_key(provider_id), defaults.sample_rate_hz)),
            timeout_seconds=max(
                3.0,
                float(self.settings.get_string(get_timeout_key(provider_id), str(defaults.timeout_seconds)) or 15.0),
            ),
            retry_max_attempts=max(
                1,
                self.settings.get_int(get_retry_attempts_key(provider_id), defaults.retry_max_attempts),
            ),
            retry_backoff_base_ms=max(
                100,
                self.settings.get_int(get_retry_backoff_key(provider_id), defaults.retry_backoff_base_ms),
            ),
            model_path=self.settings.get_string(get_model_path_key(provider_id), defaults.model_path or "").strip()
            or None,
        )

    def get_credential(self, credential_id: Optional[str]) -> Optional[str]:
        """Load decrypted credential value from CredentialStore."""
        if not credential_id:
            return None
        if self.cred_store:
            return self.cred_store.get_credential(credential_id)
        try:
            with DBService.get_instance().get_session() as session:
                temp_store = CredentialStore(session)
                return temp_store.get_credential(credential_id)
        except Exception as exc:
            logger.warning("Failed to read credential %s: %s", credential_id, exc)
            return None

    def get_service_account_info(self, config: AudioProviderConfig) -> Optional[dict]:
        """Resolve service-account JSON from credential store or file path."""
        if config.service_account_credential_id:
            raw = self.get_credential(config.service_account_credential_id)
            if not raw:
                return None
            try:
                return json.loads(raw)
            except Exception:
                return None

        if config.service_account_path:
            try:
                return json.loads(Path(config.service_account_path).read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    @staticmethod
    def _defaults(provider_id: str) -> AudioProviderConfig:
        if provider_id == "google_cloud_tts":
            return AudioProviderConfig(
                provider_id=provider_id,
                enabled=True,
                auth_mode=AudioProviderAuthMode.SERVICE_ACCOUNT_JSON,
                service_account_credential_id=get_service_account_credential_id(provider_id),
                default_voice="he-IL-Neural2-B",
                audio_format="wav",
                sample_rate_hz=24000,
                timeout_seconds=18.0,
                retry_max_attempts=2,
                retry_backoff_base_ms=400,
            )
        if provider_id == "azure_speech_tts":
            return AudioProviderConfig(
                provider_id=provider_id,
                enabled=True,
                auth_mode=AudioProviderAuthMode.API_KEY,
                api_key_credential_id=get_api_key_credential_id(provider_id),
                region="eastus",
                default_voice="he-IL-HilaNeural",
                audio_format="wav",
                sample_rate_hz=24000,
                timeout_seconds=18.0,
                retry_max_attempts=2,
                retry_backoff_base_ms=400,
            )
        if provider_id == "mms_tts_local":
            return AudioProviderConfig(
                provider_id=provider_id,
                enabled=False,
                auth_mode=AudioProviderAuthMode.NONE,
                default_voice="mms-he",
                audio_format="wav",
                sample_rate_hz=16000,
                timeout_seconds=45.0,
                retry_max_attempts=1,
                retry_backoff_base_ms=200,
            )
        return AudioProviderConfig(provider_id=provider_id)
