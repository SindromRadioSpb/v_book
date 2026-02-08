"""Provider configuration manager for loading/saving provider configs.

Responsibilities:
- Load provider config from SettingsService (QSettings INI)
- Save provider config to SettingsService
- Load credentials from CredentialStore (secure)
- Provide defaults for backward compatibility with existing providers

Usage:
    from app.infra.translators.provider_config_manager import ProviderConfigManager
    from app.infra.settings import SettingsService
    from app.infra.security import CredentialStore
    from app.services.db_service import DBService

    settings = SettingsService.get_instance()
    with DBService.get_instance().get_session() as session:
        cred_store = CredentialStore(session)
        config_mgr = ProviderConfigManager(settings, cred_store)

        # Load config
        config = config_mgr.load_config("google_cloud_translate")

        # Check auth configured
        if config.auth.is_configured():
            api_key = config_mgr.get_credential(config.auth.api_key_credential_id)
"""

import logging
from typing import Optional

from app.infra.settings import SettingsService
from app.infra.security import CredentialStore

from .provider_config import (
    ProviderConfig,
    ProviderAuthConfig,
    ProviderAuthMode,
    ProviderLimitsConfig,
    ProviderRetryPolicy,
    ProviderUiMeta,
    # Settings key helpers
    get_auth_mode_key,
    get_api_key_credential_id_key,
    get_service_account_credential_id_key,
    get_service_account_path_key,
    get_max_chars_per_request_key,
    get_max_requests_per_minute_key,
    get_max_chars_per_day_key,
    get_max_chars_per_month_key,
    get_fail_closed_key,
    get_enabled_key,
    get_rate_limit_key,
)

logger = logging.getLogger(__name__)


class ProviderConfigManager:
    """Manager for loading/saving provider configurations."""

    def __init__(
        self,
        settings: SettingsService,
        cred_store: Optional[CredentialStore] = None,
    ):
        """Initialize config manager.

        Args:
            settings: SettingsService instance (QSettings)
            cred_store: Optional CredentialStore instance (for loading credentials)
        """
        self.settings = settings
        self.cred_store = cred_store

    def load_config(self, provider_id: str) -> ProviderConfig:
        """
        Load provider configuration from settings.

        Args:
            provider_id: Provider ID (e.g., "google_cloud_translate")

        Returns:
            ProviderConfig with values from settings or defaults
        """
        # Load auth config
        auth = self._load_auth_config(provider_id)

        # Load limits config
        limits = self._load_limits_config(provider_id)

        # Load retry policy (use defaults for now)
        retry = ProviderRetryPolicy()

        # Create config
        config = ProviderConfig(
            provider_id=provider_id,
            auth=auth,
            limits=limits,
            retry=retry,
        )

        return config

    def _load_auth_config(self, provider_id: str) -> ProviderAuthConfig:
        """Load authentication config from settings."""
        auth_mode_str = self.settings.get_string(
            get_auth_mode_key(provider_id),
            ProviderAuthMode.NONE.value,
        )

        # Parse auth mode
        try:
            auth_mode = ProviderAuthMode(auth_mode_str)
        except ValueError:
            logger.warning(
                f"Invalid auth mode '{auth_mode_str}' for provider '{provider_id}', "
                f"defaulting to NONE"
            )
            auth_mode = ProviderAuthMode.NONE

        # Load credential IDs
        api_key_cred_id = self.settings.get_string(
            get_api_key_credential_id_key(provider_id), ""
        )
        service_account_cred_id = self.settings.get_string(
            get_service_account_credential_id_key(provider_id), ""
        )
        service_account_path = self.settings.get_string(
            get_service_account_path_key(provider_id), ""
        )

        return ProviderAuthConfig(
            mode=auth_mode,
            api_key_credential_id=api_key_cred_id if api_key_cred_id else None,
            service_account_credential_id=(
                service_account_cred_id if service_account_cred_id else None
            ),
            service_account_path=service_account_path if service_account_path else None,
        )

    def _load_limits_config(self, provider_id: str) -> ProviderLimitsConfig:
        """Load limits config from settings."""
        # Check if using new keys or legacy rate_limit key
        max_requests_per_minute = self.settings.get_int(
            get_max_requests_per_minute_key(provider_id), 0
        )

        if max_requests_per_minute == 0:
            # Try legacy key for backward compatibility
            max_requests_per_minute = self.settings.get_int(
                get_rate_limit_key(provider_id), 60  # Default 60 req/min
            )

        return ProviderLimitsConfig(
            max_chars_per_request=self.settings.get_int(
                get_max_chars_per_request_key(provider_id), 10000
            ),
            max_requests_per_minute=max_requests_per_minute,
            max_chars_per_day=self._get_optional_int(
                get_max_chars_per_day_key(provider_id)
            ),
            max_chars_per_month=self._get_optional_int(
                get_max_chars_per_month_key(provider_id)
            ),
            fail_closed=self.settings.get_bool(get_fail_closed_key(provider_id), True),
        )

    def _get_optional_int(self, key: str) -> Optional[int]:
        """Get optional integer from settings (0 = None)."""
        value = self.settings.get_int(key, 0)
        return value if value > 0 else None

    def save_config(self, config: ProviderConfig) -> None:
        """
        Save provider configuration to settings.

        Args:
            config: ProviderConfig to save

        Note:
            Does NOT save credentials - use save_credential() for that
        """
        provider_id = config.provider_id

        # Save auth config (excluding credentials themselves)
        self.settings.set_value(get_auth_mode_key(provider_id), config.auth.mode.value)

        if config.auth.api_key_credential_id:
            self.settings.set_value(
                get_api_key_credential_id_key(provider_id),
                config.auth.api_key_credential_id,
            )

        if config.auth.service_account_credential_id:
            self.settings.set_value(
                get_service_account_credential_id_key(provider_id),
                config.auth.service_account_credential_id,
            )

        if config.auth.service_account_path:
            self.settings.set_value(
                get_service_account_path_key(provider_id),
                config.auth.service_account_path,
            )

        # Save limits config
        self.settings.set_value(
            get_max_chars_per_request_key(provider_id),
            config.limits.max_chars_per_request,
        )
        self.settings.set_value(
            get_max_requests_per_minute_key(provider_id),
            config.limits.max_requests_per_minute,
        )

        if config.limits.max_chars_per_day:
            self.settings.set_value(
                get_max_chars_per_day_key(provider_id),
                config.limits.max_chars_per_day,
            )

        if config.limits.max_chars_per_month:
            self.settings.set_value(
                get_max_chars_per_month_key(provider_id),
                config.limits.max_chars_per_month,
            )

        self.settings.set_value(
            get_fail_closed_key(provider_id),
            config.limits.fail_closed,
        )

        # Sync to disk
        self.settings.sync()

    def get_credential(self, credential_id: str) -> Optional[str]:
        """
        Get credential value from CredentialStore.

        Args:
            credential_id: Credential ID (e.g., "mt_provider:google_cloud_translate:api_key")

        Returns:
            Decrypted credential value or None if not found
        """
        # If cred_store provided, use it directly
        if self.cred_store:
            return self.cred_store.get_credential(credential_id)

        # Otherwise, create temporary session
        from app.services.db_service import DBService

        try:
            with DBService.get_instance().get_session() as session:
                temp_store = CredentialStore(session)
                return temp_store.get_credential(credential_id)
        except Exception as e:
            logger.warning(f"Failed to get credential {credential_id}: {e}")
            return None

    def set_credential(self, credential_id: str, value: str) -> None:
        """
        Save credential to CredentialStore.

        Args:
            credential_id: Credential ID
            value: Plaintext credential value (will be encrypted)
        """
        # If cred_store provided, use it directly
        if self.cred_store:
            self.cred_store.set_credential(credential_id, value)
            return

        # Otherwise, create temporary session
        from app.services.db_service import DBService

        with DBService.get_instance().get_session() as session:
            temp_store = CredentialStore(session)
            temp_store.set_credential(credential_id, value)

    def delete_credential(self, credential_id: str) -> bool:
        """
        Delete credential from CredentialStore.

        Args:
            credential_id: Credential ID

        Returns:
            True if deleted, False if not found
        """
        # If cred_store provided, use it directly
        if self.cred_store:
            return self.cred_store.delete_credential(credential_id)

        # Otherwise, create temporary session
        from app.services.db_service import DBService

        try:
            with DBService.get_instance().get_session() as session:
                temp_store = CredentialStore(session)
                return temp_store.delete_credential(credential_id)
        except Exception as e:
            logger.warning(f"Failed to delete credential {credential_id}: {e}")
            return False

    def is_enabled(self, provider_id: str) -> bool:
        """Check if provider is enabled in settings."""
        return self.settings.get_bool(get_enabled_key(provider_id), True)

    def set_enabled(self, provider_id: str, enabled: bool) -> None:
        """Enable or disable provider in settings."""
        self.settings.set_value(get_enabled_key(provider_id), enabled)
        self.settings.sync()
