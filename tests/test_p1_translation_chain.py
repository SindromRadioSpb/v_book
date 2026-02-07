"""Offline tests for MT provider chain with fallback logic (PATCH-P1-T03).

These tests verify:
- Provider chain orchestration
- Fallback policy by TranslationErrorKind
- Structured logging
- Settings-driven configuration
- Deterministic behavior (no real API calls)
"""
import logging
import pytest
from unittest.mock import MagicMock

from app.services.translation_service import TranslationService
from app.infra.translators.base_provider import TranslationErrorKind
from app.infra.translators.providers.mock_provider import MockProvider
from app.infra.translators.providers_registry import ProvidersRegistry


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def registry():
    """Create clean registry for each test."""
    ProvidersRegistry.reset()
    return ProvidersRegistry()


@pytest.fixture
def mock_settings(monkeypatch):
    """Mock SettingsService for deterministic tests."""
    mock_instance = MagicMock()

    # Default settings
    settings_data = {
        "mt/providers/enabled": True,
        "mt/providers/chain": [],
        "mt/providers/allow_fallback_default": True,
    }

    def get_bool(key, default=False):
        return settings_data.get(key, default)

    def get_json(key, default=None):
        return settings_data.get(key, default)

    mock_instance.get_bool = get_bool
    mock_instance.get_json = get_json

    # Monkeypatch SettingsService.get_instance to return mock
    from app.infra import settings
    monkeypatch.setattr(settings.SettingsService, "get_instance", lambda: mock_instance)

    # Return settings_data so tests can modify it
    return settings_data


@pytest.fixture
def db_session():
    """Mock database session (not used in chain tests, but required by API)."""
    return MagicMock()


@pytest.fixture
def translation_service():
    """Create TranslationService instance."""
    return TranslationService()


# ============================================================================
# Test 1: NETWORK fail → fallback success
# ============================================================================


def test_chain_network_fail_then_success(
    registry, mock_settings, db_session, translation_service, caplog
):
    """Primary provider fails with NETWORK error, secondary succeeds."""
    # Setup: Register two providers
    provider_fail = MockProvider(simulate_error=TranslationErrorKind.NETWORK)
    provider_success = MockProvider()  # No error

    # Register with custom IDs
    class FailProvider(MockProvider):
        @property
        def provider_id(self):
            return "mock_fail_network"

        @property
        def display_name(self):
            return "Mock Fail Network"

        def __init__(self):
            super().__init__(
                simulate_error=TranslationErrorKind.NETWORK,
                error_probability=1.0  # Always fail
            )

    class SuccessProvider(MockProvider):
        @property
        def provider_id(self):
            return "mock_success"

        @property
        def display_name(self):
            return "Mock Success"

    registry.register(FailProvider())
    registry.register(SuccessProvider())

    # Configure chain
    mock_settings["mt/providers/chain"] = ["mock_fail_network", "mock_success"]
    mock_settings["mt/providers/enabled"] = True

    # Execute
    with caplog.at_level(logging.INFO):
        result = translation_service._translate_via_provider_chain(
            session=db_session,
            src_text="שלום",
            src_lang="he",
            tgt_lang="ru",
            allow_fallback=True,
        )

    # Verify: Result is from secondary provider
    assert result.translation is not None
    assert result.source == "mt"
    assert result.provider == "mock_success"
    assert "םולש [HE→RU]" in result.translation  # Reversed Hebrew + marker

    # Verify: Logs show 2 attempts
    logs = caplog.text
    assert "mock_fail_network" in logs
    assert "mock_success" in logs
    assert "CONTINUE_FALLBACK" in logs
    assert "STOP_SUCCESS" in logs
    assert "translation_completed" in logs


# ============================================================================
# Test 2: AUTH fail → CONFIG_ISSUE logged + fallback
# ============================================================================


def test_chain_auth_fail_then_success_logs_config_issue(
    registry, mock_settings, db_session, translation_service, caplog
):
    """AUTH error logged as CONFIG_ISSUE, but fallback still occurs."""

    class AuthFailProvider(MockProvider):
        @property
        def provider_id(self):
            return "mock_auth_fail"

        @property
        def display_name(self):
            return "Mock Auth Fail"

        def __init__(self):
            super().__init__(
                simulate_error=TranslationErrorKind.AUTH,
                error_probability=1.0
            )

    class SuccessProvider(MockProvider):
        @property
        def provider_id(self):
            return "mock_success"

        @property
        def display_name(self):
            return "Mock Success"

    registry.register(AuthFailProvider())
    registry.register(SuccessProvider())

    mock_settings["mt/providers/chain"] = ["mock_auth_fail", "mock_success"]
    mock_settings["mt/providers/enabled"] = True

    # Execute
    with caplog.at_level(logging.INFO):  # Capture all logs (including ERROR)
        result = translation_service._translate_via_provider_chain(
            session=db_session,
            src_text="test",
            src_lang="en",
            tgt_lang="ru",
            allow_fallback=True,
        )

    # Verify: Success from fallback
    assert result.translation is not None
    assert result.source == "mt"
    assert result.provider == "mock_success"

    # Verify: AUTH error logged at ERROR level with CONFIG_ISSUE marker
    logs = caplog.text
    assert "mock_auth_fail" in logs
    assert "error=auth" in logs.lower() or "error=AUTH" in logs
    assert "[CONFIG_ISSUE]" in logs  # Special marker for config errors
    assert "CONTINUE_FALLBACK" in logs
    assert "translation_completed" in logs


# ============================================================================
# Test 3: allow_fallback=False → stop after first
# ============================================================================


def test_chain_no_fallback_stops_after_first(
    registry, mock_settings, db_session, translation_service, caplog
):
    """When allow_fallback=False, chain stops after first failure."""

    class NetworkFailProvider(MockProvider):
        @property
        def provider_id(self):
            return "mock_network_fail"

        def __init__(self):
            super().__init__(
                simulate_error=TranslationErrorKind.NETWORK,
                error_probability=1.0
            )

    class SuccessProvider(MockProvider):
        @property
        def provider_id(self):
            return "mock_success"

    registry.register(NetworkFailProvider())
    registry.register(SuccessProvider())

    mock_settings["mt/providers/chain"] = ["mock_network_fail", "mock_success"]
    mock_settings["mt/providers/enabled"] = True

    # Execute with allow_fallback=False
    with caplog.at_level(logging.INFO):
        result = translation_service._translate_via_provider_chain(
            session=db_session,
            src_text="test",
            src_lang="en",
            tgt_lang="ru",
            allow_fallback=False,  # ← KEY: No fallback
        )

    # Verify: Failed result (not from second provider)
    assert result.translation is None
    assert result.source == "none"
    assert result.notes is not None  # Error message

    # Verify: Only 1 attempt logged
    logs = caplog.text
    assert "mock_network_fail" in logs
    assert "mock_success" not in logs  # Second provider NOT tried
    assert "STOP_FAIL" in logs
    assert "ALLOW_FALLBACK_FALSE" in logs
    assert "translation_failed" in logs


# ============================================================================
# Test 4: Empty chain → UNSUPPORTED graceful error
# ============================================================================


def test_chain_empty_returns_graceful_error(
    registry, mock_settings, db_session, translation_service, caplog
):
    """Empty provider chain returns UNSUPPORTED error without crashing."""

    # Empty chain
    mock_settings["mt/providers/chain"] = []
    mock_settings["mt/providers/enabled"] = True

    # Execute
    with caplog.at_level(logging.INFO):
        result = translation_service._translate_via_provider_chain(
            session=db_session,
            src_text="test",
            src_lang="en",
            tgt_lang="ru",
        )

    # Verify: Graceful error
    assert result.translation is None
    assert result.source == "none"
    assert "No MT providers configured" in result.notes or "empty" in result.notes.lower()

    # Verify: No crash, no attempts logged
    logs = caplog.text
    assert "provider_attempt" not in logs  # No attempts
    assert "translation_failed" not in logs  # Not a failure, just unconfigured


# ============================================================================
# Test 5: Missing provider ID → continue chain
# ============================================================================


def test_chain_missing_provider_continues(
    registry, mock_settings, db_session, translation_service, caplog
):
    """Chain with missing provider ID skips and continues to next."""

    class SuccessProvider(MockProvider):
        @property
        def provider_id(self):
            return "mock_success"

    # Only register one provider
    registry.register(SuccessProvider())

    # Chain includes non-existent provider
    mock_settings["mt/providers/chain"] = [
        "nonexistent_provider",  # ← Not registered
        "mock_success",  # ← Registered
    ]
    mock_settings["mt/providers/enabled"] = True

    # Execute
    with caplog.at_level(logging.INFO):
        result = translation_service._translate_via_provider_chain(
            session=db_session,
            src_text="test",
            src_lang="en",
            tgt_lang="ru",
        )

    # Verify: Success from second provider
    assert result.translation is not None
    assert result.source == "mt"
    assert result.provider == "mock_success"

    # Verify: First provider logged as SKIP_MISSING
    logs = caplog.text
    assert "nonexistent_provider" in logs
    assert "SKIP_MISSING" in logs
    assert "PROVIDER_NOT_REGISTERED" in logs
    assert "mock_success" in logs
    assert "STOP_SUCCESS" in logs


# ============================================================================
# Test 6: MT disabled → graceful error
# ============================================================================


def test_chain_mt_disabled_returns_graceful_error(
    registry, mock_settings, db_session, translation_service
):
    """When MT disabled via settings, returns graceful error."""

    class SuccessProvider(MockProvider):
        @property
        def provider_id(self):
            return "mock_success"

    registry.register(SuccessProvider())

    # MT disabled
    mock_settings["mt/providers/enabled"] = False
    mock_settings["mt/providers/chain"] = ["mock_success"]

    # Execute
    result = translation_service._translate_via_provider_chain(
        session=db_session,
        src_text="test",
        src_lang="en",
        tgt_lang="ru",
    )

    # Verify: Graceful error
    assert result.translation is None
    assert result.source == "none"
    assert "MT providers disabled" in result.notes or "disabled" in result.notes.lower()


# ============================================================================
# Test 7: All providers fail → NO_MORE_PROVIDERS
# ============================================================================


def test_chain_all_providers_fail_returns_last_error(
    registry, mock_settings, db_session, translation_service, caplog
):
    """All providers fail → returns last error with NO_MORE_PROVIDERS reason."""

    class Fail1Provider(MockProvider):
        @property
        def provider_id(self):
            return "fail1"

        def __init__(self):
            super().__init__(
                simulate_error=TranslationErrorKind.NETWORK,
                error_probability=1.0
            )

    class Fail2Provider(MockProvider):
        @property
        def provider_id(self):
            return "fail2"

        def __init__(self):
            super().__init__(
                simulate_error=TranslationErrorKind.SERVER,
                error_probability=1.0
            )

    registry.register(Fail1Provider())
    registry.register(Fail2Provider())

    mock_settings["mt/providers/chain"] = ["fail1", "fail2"]
    mock_settings["mt/providers/enabled"] = True

    # Execute
    with caplog.at_level(logging.INFO):
        result = translation_service._translate_via_provider_chain(
            session=db_session,
            src_text="test",
            src_lang="en",
            tgt_lang="ru",
        )

    # Verify: Failed result
    assert result.translation is None
    assert result.source == "none"

    # Verify: Logs show all attempts + final failure
    logs = caplog.text
    assert "fail1" in logs
    assert "fail2" in logs
    assert "CONTINUE_FALLBACK" in logs
    assert "translation_failed" in logs
    assert "NO_MORE_PROVIDERS" in logs
