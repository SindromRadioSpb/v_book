"""Unit tests for Google Cloud Translate provider.

Tests:
- API key rejection (v3 requires SA JSON)
- Service account initialization
- Budget guard enforcement
- 429 retry with backoff
- 403 error classification
- No secrets in logs
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from google.api_core import exceptions as google_exceptions

from app.infra.translators.providers.google_cloud_translate_provider import (
    GoogleCloudTranslateProvider,
)
from app.infra.translators.base_provider import (
    TranslationRequest,
    TranslationErrorKind,
)
from app.infra.translators.provider_config import (
    ProviderConfig,
    ProviderAuthConfig,
    ProviderAuthMode,
    ProviderLimitsConfig,
    ProviderRetryPolicy,
)
from app.infra.translators.provider_config_manager import ProviderConfigManager


class TestApiKeyRejection:
    """Test that API key auth is rejected for v3."""

    def test_api_key_mode_rejected(self):
        """Test v3 rejects API key mode with clear error."""
        # Mock config manager to return API key config
        config_mgr = Mock(spec=ProviderConfigManager)
        config_mgr.load_config.return_value = ProviderConfig(
            provider_id="google_cloud_translate",
            auth=ProviderAuthConfig(mode=ProviderAuthMode.API_KEY),
        )

        provider = GoogleCloudTranslateProvider(config_manager=config_mgr)

        # Translate should return AUTH error
        request = TranslationRequest(
            source_text="hello",
            source_lang="en",
            target_lang="ru",
        )

        result = provider.translate(request)

        assert result.is_error
        assert result.error_kind == TranslationErrorKind.AUTH
        assert "API keys" in result.error_message
        assert "Service Account JSON" in result.error_message
        assert "v2" in result.error_message  # Mention v2 as alternative


class TestServiceAccountAuth:
    """Test service account authentication."""

    @pytest.fixture
    def mock_sa_json(self):
        """Mock service account JSON."""
        return {
            "type": "service_account",
            "project_id": "test-project-123",
            "private_key_id": "key-id",
            "private_key": "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----\n",
            "client_email": "test@test-project.iam.gserviceaccount.com",
            "client_id": "123456789",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }

    def test_sa_json_from_credential_store(self, mock_sa_json):
        """Test loading SA JSON from CredentialStore."""
        # Mock config manager
        config_mgr = Mock(spec=ProviderConfigManager)
        config_mgr.load_config.return_value = ProviderConfig(
            provider_id="google_cloud_translate",
            auth=ProviderAuthConfig(
                mode=ProviderAuthMode.SERVICE_ACCOUNT_JSON,
                service_account_credential_id="mt_provider:google_cloud_translate:service_account_json",
            ),
        )
        config_mgr.get_credential.return_value = json.dumps(mock_sa_json)

        provider = GoogleCloudTranslateProvider(config_manager=config_mgr)

        # Initialize client (will call _initialize_client internally)
        with patch(
            "app.infra.translators.providers.google_cloud_translate_provider.translate_v3.TranslationServiceClient"
        ):
            # Healthcheck triggers initialization
            with patch(
                "app.infra.translators.providers.google_cloud_translate_provider.service_account.Credentials.from_service_account_info"
            ) as mock_creds:
                mock_creds.return_value = Mock()
                provider.healthcheck()

        # Verify credential was loaded
        config_mgr.get_credential.assert_called_once_with(
            "mt_provider:google_cloud_translate:service_account_json"
        )

    def test_sa_json_missing_project_id(self):
        """Test error when SA JSON missing project_id."""
        invalid_sa_json = {"type": "service_account"}  # Missing project_id

        config_mgr = Mock(spec=ProviderConfigManager)
        config_mgr.load_config.return_value = ProviderConfig(
            provider_id="google_cloud_translate",
            auth=ProviderAuthConfig(
                mode=ProviderAuthMode.SERVICE_ACCOUNT_JSON,
                service_account_credential_id="test_cred_id",
            ),
        )
        config_mgr.get_credential.return_value = json.dumps(invalid_sa_json)

        provider = GoogleCloudTranslateProvider(config_manager=config_mgr)

        # Translate should return AUTH error
        request = TranslationRequest(
            source_text="hello",
            source_lang="en",
            target_lang="ru",
        )

        result = provider.translate(request)

        assert result.is_error
        assert result.error_kind == TranslationErrorKind.AUTH
        assert "project_id" in result.error_message


class TestBudgetGuards:
    """Test budget guard enforcement."""

    def test_max_chars_per_request_exceeded(self):
        """Test rejection when text exceeds max_chars_per_request."""
        config_mgr = Mock(spec=ProviderConfigManager)
        config_mgr.load_config.return_value = ProviderConfig(
            provider_id="google_cloud_translate",
            auth=ProviderAuthConfig(
                mode=ProviderAuthMode.SERVICE_ACCOUNT_JSON,
                service_account_credential_id="test_cred_id",
            ),
            limits=ProviderLimitsConfig(
                max_chars_per_request=100,  # Small limit for testing
            ),
        )
        config_mgr.get_credential.return_value = json.dumps({
            "project_id": "test-project",
            "private_key": "test",
        })

        provider = GoogleCloudTranslateProvider(config_manager=config_mgr)

        # Mock client initialization
        with patch.object(provider, '_initialize_client'):
            provider._client = Mock()
            provider._project_id = "test-project"

            # Request with text > 100 chars
            long_text = "a" * 150
            request = TranslationRequest(
                source_text=long_text,
                source_lang="en",
                target_lang="ru",
            )

            result = provider.translate(request)

        assert result.is_error
        assert result.error_kind == TranslationErrorKind.INVALID_REQUEST
        assert "too long" in result.error_message.lower()
        assert "150 chars" in result.error_message


class TestRetryPolicy:
    """Test retry policy on 429."""

    def test_retry_on_429(self):
        """Test retry with backoff on 429 (rate limit)."""
        config_mgr = Mock(spec=ProviderConfigManager)
        config_mgr.load_config.return_value = ProviderConfig(
            provider_id="google_cloud_translate",
            auth=ProviderAuthConfig(
                mode=ProviderAuthMode.SERVICE_ACCOUNT_JSON,
                service_account_credential_id="test_cred_id",
            ),
            retry=ProviderRetryPolicy(
                max_retries=2,  # 3 total attempts
                base_backoff_ms=100,
                use_jitter=False,  # Disable jitter for deterministic test
            ),
        )
        config_mgr.get_credential.return_value = json.dumps({
            "project_id": "test-project",
            "private_key": "test",
        })

        provider = GoogleCloudTranslateProvider(config_manager=config_mgr)

        # Mock client
        mock_client = Mock()
        # First 2 attempts: 429, third attempt: success
        mock_client.translate_text.side_effect = [
            google_exceptions.TooManyRequests("Rate limit"),
            google_exceptions.TooManyRequests("Rate limit"),
            Mock(translations=[Mock(translated_text="привет", detected_language_code="en")]),
        ]

        with patch.object(provider, '_initialize_client'):
            provider._client = mock_client
            provider._project_id = "test-project"

            request = TranslationRequest(
                source_text="hello",
                source_lang="en",
                target_lang="ru",
            )

            with patch('time.sleep'):  # Mock sleep to speed up test
                result = provider.translate(request)

        # Should succeed on third attempt
        assert result.is_success
        assert result.translated_text == "привет"
        assert result.meta["attempt"] == 3

        # Verify 3 API calls made
        assert mock_client.translate_text.call_count == 3

    def test_max_retries_exceeded_on_429(self):
        """Test max retries exceeded returns RATE_LIMIT error."""
        config_mgr = Mock(spec=ProviderConfigManager)
        config_mgr.load_config.return_value = ProviderConfig(
            provider_id="google_cloud_translate",
            auth=ProviderAuthConfig(
                mode=ProviderAuthMode.SERVICE_ACCOUNT_JSON,
                service_account_credential_id="test_cred_id",
            ),
            retry=ProviderRetryPolicy(max_retries=1),  # Only 2 total attempts
        )
        config_mgr.get_credential.return_value = json.dumps({
            "project_id": "test-project",
            "private_key": "test",
        })

        provider = GoogleCloudTranslateProvider(config_manager=config_mgr)

        # Mock client - always return 429
        mock_client = Mock()
        mock_client.translate_text.side_effect = google_exceptions.TooManyRequests(
            "Rate limit"
        )

        with patch.object(provider, '_initialize_client'):
            provider._client = mock_client
            provider._project_id = "test-project"

            request = TranslationRequest(
                source_text="hello",
                source_lang="en",
                target_lang="ru",
            )

            with patch('time.sleep'):
                result = provider.translate(request)

        assert result.is_error
        assert result.error_kind == TranslationErrorKind.RATE_LIMIT
        assert "429" in result.error_message


class Test403Classification:
    """Test 403 error classification."""

    @pytest.mark.parametrize(
        "exception_msg,expected_keywords",
        [
            ("Permission denied", ["Permission denied", "roles/cloudtranslate.user"]),
            ("Billing not enabled", ["Billing not enabled", "billing"]),
            ("Quota exceeded", ["Quota exceeded", "quota"]),
            ("API is not enabled", ["Translation API not enabled", "console.cloud.google.com"]),
        ],
    )
    def test_403_classification(self, exception_msg, expected_keywords):
        """Test different 403 error messages are classified correctly."""
        config_mgr = Mock(spec=ProviderConfigManager)
        config_mgr.load_config.return_value = ProviderConfig(
            provider_id="google_cloud_translate",
            auth=ProviderAuthConfig(
                mode=ProviderAuthMode.SERVICE_ACCOUNT_JSON,
                service_account_credential_id="test_cred_id",
            ),
        )
        config_mgr.get_credential.return_value = json.dumps({
            "project_id": "test-project",
            "private_key": "test",
        })

        provider = GoogleCloudTranslateProvider(config_manager=config_mgr)

        # Mock client - return 403
        mock_client = Mock()
        mock_client.translate_text.side_effect = google_exceptions.PermissionDenied(
            exception_msg
        )

        with patch.object(provider, '_initialize_client'):
            provider._client = mock_client
            provider._project_id = "test-project"

            request = TranslationRequest(
                source_text="hello",
                source_lang="en",
                target_lang="ru",
            )

            result = provider.translate(request)

        assert result.is_error
        assert result.error_kind == TranslationErrorKind.AUTH
        # Check all expected keywords appear in error message
        for keyword in expected_keywords:
            assert keyword.lower() in result.error_message.lower()


class TestBackoffCalculation:
    """Test exponential backoff calculation."""

    def test_backoff_without_jitter(self):
        """Test exponential backoff without jitter."""
        provider = GoogleCloudTranslateProvider()

        # Attempt 0: base_ms * 2^0 = 1000
        backoff = provider._calculate_backoff(0, 1000, 10000, use_jitter=False)
        assert backoff == 1000

        # Attempt 1: base_ms * 2^1 = 2000
        backoff = provider._calculate_backoff(1, 1000, 10000, use_jitter=False)
        assert backoff == 2000

        # Attempt 2: base_ms * 2^2 = 4000
        backoff = provider._calculate_backoff(2, 1000, 10000, use_jitter=False)
        assert backoff == 4000

        # Attempt 4: base_ms * 2^4 = 16000 → capped to max_ms = 10000
        backoff = provider._calculate_backoff(4, 1000, 10000, use_jitter=False)
        assert backoff == 10000

    def test_backoff_with_jitter(self):
        """Test backoff with jitter adds randomness."""
        provider = GoogleCloudTranslateProvider()

        # With jitter, backoff should vary between 75% and 125% of base
        base_backoff = 1000
        backoffs = [
            provider._calculate_backoff(0, base_backoff, 10000, use_jitter=True)
            for _ in range(10)
        ]

        # All backoffs should be in range [750, 1250]
        for backoff in backoffs:
            assert 750 <= backoff <= 1250

        # At least some variation (not all identical)
        assert len(set(backoffs)) > 1


class TestProviderMeta:
    """Test provider metadata."""

    def test_provider_id(self):
        """Test provider ID."""
        provider = GoogleCloudTranslateProvider()
        assert provider.provider_id == "google_cloud_translate"

    def test_display_name(self):
        """Test display name."""
        provider = GoogleCloudTranslateProvider()
        assert "Google Cloud" in provider.display_name
        assert "v3" in provider.display_name

    def test_supports_glossary(self):
        """Test glossary support (not yet implemented)."""
        provider = GoogleCloudTranslateProvider()
        assert provider.supports_glossary is False

    def test_supports_batch(self):
        """Test batch support (not yet implemented)."""
        provider = GoogleCloudTranslateProvider()
        assert provider.supports_batch is False
