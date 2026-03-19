"""Unit tests for provider configuration schema and manager.

Tests:
- ProviderAuthConfig dataclass
- ProviderLimitsConfig dataclass
- ProviderRetryPolicy dataclass
- ProviderConfigManager load/save
- Backward compatibility with existing providers
"""

import pytest
from app.infra.translators.provider_config import (
    ProviderConfig,
    ProviderAuthConfig,
    ProviderAuthMode,
    ProviderLimitsConfig,
    ProviderRetryPolicy,
    ProviderUiMeta,
    get_api_key_credential_id,
    get_service_account_credential_id,
)
from app.infra.translators.provider_config_manager import ProviderConfigManager
from app.infra.settings import SettingsService
from app.infra.security import CredentialStore


class TestProviderAuthConfig:
    """Test ProviderAuthConfig dataclass."""

    def test_default_none_mode(self):
        """Test default auth mode is NONE."""
        auth = ProviderAuthConfig()
        assert auth.mode == ProviderAuthMode.NONE
        assert auth.is_configured()

    def test_api_key_configured(self):
        """Test API key mode is configured when credential ID set."""
        auth = ProviderAuthConfig(
            mode=ProviderAuthMode.API_KEY,
            api_key_credential_id="mt_provider:test:api_key",
        )
        assert auth.is_configured()

    def test_api_key_not_configured(self):
        """Test API key mode NOT configured without credential ID."""
        auth = ProviderAuthConfig(mode=ProviderAuthMode.API_KEY)
        assert not auth.is_configured()

    def test_service_account_configured_via_credential_id(self):
        """Test SA mode configured via credential ID."""
        auth = ProviderAuthConfig(
            mode=ProviderAuthMode.SERVICE_ACCOUNT_JSON,
            service_account_credential_id="mt_provider:test:service_account_json",
        )
        assert auth.is_configured()

    def test_service_account_configured_via_path(self):
        """Test SA mode configured via file path."""
        auth = ProviderAuthConfig(
            mode=ProviderAuthMode.SERVICE_ACCOUNT_JSON,
            service_account_path="/path/to/service-account.json",
        )
        assert auth.is_configured()

    def test_service_account_not_configured(self):
        """Test SA mode NOT configured without credential ID or path."""
        auth = ProviderAuthConfig(mode=ProviderAuthMode.SERVICE_ACCOUNT_JSON)
        assert not auth.is_configured()


class TestProviderLimitsConfig:
    """Test ProviderLimitsConfig dataclass."""

    def test_defaults(self):
        """Test default limits."""
        limits = ProviderLimitsConfig()
        assert limits.max_chars_per_request == 10000
        assert limits.max_requests_per_minute == 60
        assert limits.fail_closed is True
        assert not limits.has_budget_guards()  # No day/month limits

    def test_budget_guards_detected(self):
        """Test budget guards detection."""
        limits = ProviderLimitsConfig(max_chars_per_month=500000)
        assert limits.has_budget_guards()

        limits = ProviderLimitsConfig(max_chars_per_day=100000)
        assert limits.has_budget_guards()

        limits = ProviderLimitsConfig(max_requests_per_day=1000)
        assert limits.has_budget_guards()


class TestProviderRetryPolicy:
    """Test ProviderRetryPolicy dataclass."""

    def test_defaults(self):
        """Test default retry policy."""
        retry = ProviderRetryPolicy()
        assert retry.max_retries == 3
        assert retry.base_backoff_ms == 1000
        assert retry.max_backoff_ms == 10000
        assert 429 in retry.retry_on_status
        assert 503 in retry.retry_on_status

    def test_should_retry_429(self):
        """Test should retry on 429 (rate limit)."""
        retry = ProviderRetryPolicy(max_retries=3)
        assert retry.should_retry(429, attempt=0)
        assert retry.should_retry(429, attempt=1)
        assert retry.should_retry(429, attempt=2)
        assert not retry.should_retry(429, attempt=3)  # Max retries reached

    def test_should_not_retry_403(self):
        """Test should NOT retry on 403 (permission denied) by default."""
        retry = ProviderRetryPolicy()
        assert not retry.should_retry(403, attempt=0)

    def test_custom_retry_statuses(self):
        """Test custom retry status codes."""
        retry = ProviderRetryPolicy(retry_on_status=[429, 503, 500])
        assert retry.should_retry(500, attempt=0)
        assert not retry.should_retry(502, attempt=0)


class TestProviderConfigManager:
    """Test ProviderConfigManager load/save."""

    @pytest.fixture
    def settings(self):
        """Create test SettingsService (in-memory)."""
        from PyQt6.QtCore import QSettings

        settings = SettingsService()
        settings._settings = QSettings(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            "HDLE_Test",
            "ProviderConfigTest",
        )
        yield settings
        # Cleanup
        settings._settings.clear()

    @pytest.fixture
    def config_manager(self, settings):
        """Create ProviderConfigManager with test settings."""
        return ProviderConfigManager(settings)

    def test_load_default_config(self, config_manager):
        """Test loading config with defaults (no settings saved)."""
        config = config_manager.load_config("test_provider")

        assert config.provider_id == "test_provider"
        assert config.auth.mode == ProviderAuthMode.NONE
        assert config.limits.max_chars_per_request == 10000
        assert config.limits.max_requests_per_minute == 60
        assert config.retry.max_retries == 3

    def test_save_and_load_config(self, config_manager):
        """Test saving and loading config roundtrip."""
        # Create config
        config = ProviderConfig(
            provider_id="test_provider",
            auth=ProviderAuthConfig(
                mode=ProviderAuthMode.API_KEY,
                api_key_credential_id="mt_provider:test_provider:api_key",
            ),
            limits=ProviderLimitsConfig(
                max_chars_per_request=5000,
                max_requests_per_minute=30,
                max_chars_per_month=100000,
                fail_closed=False,
            ),
        )

        # Save
        config_manager.save_config(config)

        # Load
        loaded = config_manager.load_config("test_provider")

        # Verify
        assert loaded.provider_id == "test_provider"
        assert loaded.auth.mode == ProviderAuthMode.API_KEY
        assert loaded.auth.api_key_credential_id == "mt_provider:test_provider:api_key"
        assert loaded.limits.max_chars_per_request == 5000
        assert loaded.limits.max_requests_per_minute == 30
        assert loaded.limits.max_chars_per_month == 100000
        assert loaded.limits.fail_closed is False

    def test_backward_compatibility_legacy_rate_limit(self, config_manager):
        """Test backward compatibility with legacy 'rate_limit' key."""
        # Simulate old settings (only rate_limit key, no max_requests_per_minute)
        from app.infra.translators.provider_config import get_rate_limit_key

        config_manager.settings.set_value(get_rate_limit_key("legacy_provider"), 120)

        # Load config
        config = config_manager.load_config("legacy_provider")

        # Should use legacy rate_limit value
        assert config.limits.max_requests_per_minute == 120

    def test_enabled_status(self, config_manager):
        """Test is_enabled and set_enabled."""
        # Default enabled
        assert config_manager.is_enabled("new_provider")

        # Disable
        config_manager.set_enabled("new_provider", False)
        assert not config_manager.is_enabled("new_provider")

        # Enable
        config_manager.set_enabled("new_provider", True)
        assert config_manager.is_enabled("new_provider")


class TestCredentialHelpers:
    """Test credential ID helper functions."""

    def test_api_key_credential_id(self):
        """Test API key credential ID format."""
        cred_id = get_api_key_credential_id("google_cloud_translate")
        assert cred_id == "mt_provider:google_cloud_translate:api_key"

    def test_service_account_credential_id(self):
        """Test service account credential ID format."""
        cred_id = get_service_account_credential_id("google_cloud_translate")
        assert cred_id == "mt_provider:google_cloud_translate:service_account_json"


class TestProviderUiMeta:
    """Test ProviderUiMeta dataclass."""

    def test_defaults(self):
        """Test UI metadata defaults."""
        ui_meta = ProviderUiMeta(display_name="Test Provider")
        assert ui_meta.display_name == "Test Provider"
        assert ui_meta.supports_force is True
        assert ui_meta.supports_chain is True
        assert ui_meta.supports_auth is False
        assert ui_meta.default_enabled is True
        assert ui_meta.default_rate_limit == 60
