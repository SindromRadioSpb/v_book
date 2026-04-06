"""Tests for local providers setup (PATCH-08).

Tests verify:
- Provider registration with installed models
- Skipping providers with missing models
- Provider availability checking
- Unregistration and cleanup
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from app.infra.translators.providers_registry import ProvidersRegistry
from app.infra.translators.local_providers_setup import (
    initialize_local_providers,
    check_local_providers_available,
    unregister_local_providers,
    is_local_provider_available,
    get_installed_local_providers,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def registry():
    """Create clean registry for each test."""
    ProvidersRegistry.reset()
    return ProvidersRegistry()


@pytest.fixture
def mock_model_manager():
    """Create mock ModelResourceManager."""
    manager = Mock()
    manager.is_installed = Mock(return_value=(True, None))
    manager.model_dir = Mock(return_value="/fake/model/path")
    return manager


@pytest.fixture
def mock_worker():
    """Create mock worker."""
    worker = Mock()
    worker.ping = Mock(return_value=True)
    worker.shutdown = Mock()
    return worker


# ============================================================================
# Test 1: Initialize Providers - Success
# ============================================================================


def test_initialize_local_providers_success(registry, mock_model_manager, mock_worker):
    """Initialize providers when models are installed."""
    with patch(
        "app.infra.translators.local_providers_setup.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.start_worker",
            return_value=mock_worker,
        ):
            with patch(
                "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
                return_value=mock_model_manager,
            ):
                with patch(
                    "app.infra.translators.providers.local_hymt_provider.start_worker",
                    return_value=mock_worker,
                ):
                    with patch(
                        "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
                        return_value=mock_model_manager,
                    ):
                        count = initialize_local_providers()

                        # Should register local_nllb + local_hymt providers
                        assert count == 2
                        assert len(registry) == 2
                        assert registry.get("local_nllb") is not None
                        assert registry.get("local_hymt") is not None


def test_initialize_local_providers_with_db_session(registry, mock_model_manager, mock_worker):
    """Initialize providers with database session for glossary support."""
    mock_session = Mock()

    with patch(
        "app.infra.translators.local_providers_setup.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.start_worker",
            return_value=mock_worker,
        ):
            with patch(
                "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
                return_value=mock_model_manager,
            ):
                with patch(
                    "app.infra.translators.providers.local_hymt_provider.start_worker",
                    return_value=mock_worker,
                ):
                    with patch(
                        "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
                        return_value=mock_model_manager,
                    ):
                        count = initialize_local_providers(db_session=mock_session, project_id=100)

                        assert count == 2

                        provider = registry.get("local_nllb")
                        assert provider is not None
                        assert provider.db_session == mock_session
                        assert provider.project_id == 100

                        hymt_provider = registry.get("local_hymt")
                        assert hymt_provider is not None
                        assert hymt_provider.db_session == mock_session
                        assert hymt_provider.project_id == 100


# ============================================================================
# Test 2: Initialize Providers - Model Not Installed
# ============================================================================


def test_initialize_local_providers_model_not_installed(registry, mock_model_manager):
    """Skip providers when models are not installed."""
    # Model not installed
    mock_model_manager.is_installed = Mock(return_value=(False, "Model not found"))

    with patch(
        "app.infra.translators.local_providers_setup.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        count = initialize_local_providers()

        # Should skip provider
        assert count == 0
        assert len(registry) == 0


def test_initialize_local_providers_force_register_fails(registry, mock_model_manager):
    """Force register raises error if model not installed."""
    # Model not installed in setup check
    mock_model_manager.is_installed = Mock(return_value=(False, "Model not found"))

    with patch(
        "app.infra.translators.local_providers_setup.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        # Also mock the provider's internal model manager to fail
        with patch(
            "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
            return_value=mock_model_manager,
        ):
            with pytest.raises(RuntimeError, match="Model not installed"):
                initialize_local_providers(force_register=True)


# ============================================================================
# Test 3: Check Provider Availability
# ============================================================================


def test_check_local_providers_available_installed(mock_model_manager):
    """Check providers with installed models."""
    mock_model_manager.is_installed = Mock(return_value=(True, None))

    with patch(
        "app.infra.translators.local_providers_setup.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        status = check_local_providers_available()

        assert "local_nllb" in status
        assert status["local_nllb"]["available"] is True
        assert status["local_nllb"]["model_id"] == "facebook/nllb-200-distilled-1.3B"
        assert status["local_nllb"]["backend"] == "ctranslate2"
        assert status["local_nllb"]["reason"] is None


def test_check_local_providers_available_not_installed(mock_model_manager):
    """Check providers with missing models."""
    mock_model_manager.is_installed = Mock(return_value=(False, "Model files not found"))

    with patch(
        "app.infra.translators.local_providers_setup.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        status = check_local_providers_available()

        assert "local_nllb" in status
        assert status["local_nllb"]["available"] is False
        assert status["local_nllb"]["reason"] == "Model files not found"


# ============================================================================
# Test 4: Unregister Providers
# ============================================================================


def test_unregister_local_providers(registry, mock_model_manager, mock_worker):
    """Unregister local providers."""
    # First register providers
    with patch(
        "app.infra.translators.local_providers_setup.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.start_worker",
            return_value=mock_worker,
        ):
            with patch(
                "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
                return_value=mock_model_manager,
            ):
                with patch(
                    "app.infra.translators.providers.local_hymt_provider.start_worker",
                    return_value=mock_worker,
                ):
                    with patch(
                        "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
                        return_value=mock_model_manager,
                    ):
                        initialize_local_providers()

                        assert len(registry) == 2

                        # Unregister
                        count = unregister_local_providers()

                        assert count == 2
                        assert len(registry) == 0

                        # Shutdown should be called for each provider
                        assert mock_worker.shutdown.call_count == 2


def test_unregister_local_providers_when_none_registered(registry):
    """Unregister when no providers registered."""
    count = unregister_local_providers()
    assert count == 0


# ============================================================================
# Test 5: Convenience Functions
# ============================================================================


def test_is_local_provider_available(mock_model_manager):
    """Check if specific provider is available."""
    mock_model_manager.is_installed = Mock(return_value=(True, None))

    with patch(
        "app.infra.translators.local_providers_setup.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        assert is_local_provider_available("local_nllb") is True


def test_is_local_provider_available_not_installed(mock_model_manager):
    """Check provider availability when model not installed."""
    mock_model_manager.is_installed = Mock(return_value=(False, "Not found"))

    with patch(
        "app.infra.translators.local_providers_setup.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        assert is_local_provider_available("local_nllb") is False


def test_is_local_provider_available_unknown_provider(mock_model_manager):
    """Check unknown provider returns False."""
    with patch(
        "app.infra.translators.local_providers_setup.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        assert is_local_provider_available("unknown_provider") is False


def test_get_installed_local_providers(mock_model_manager):
    """Get list of installed local providers."""
    mock_model_manager.is_installed = Mock(return_value=(True, None))

    with patch(
        "app.infra.translators.local_providers_setup.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        installed = get_installed_local_providers()

        assert isinstance(installed, list)
        assert "local_nllb" in installed


def test_get_installed_local_providers_none_installed(mock_model_manager):
    """Get empty list when no providers installed."""
    mock_model_manager.is_installed = Mock(return_value=(False, "Not found"))

    with patch(
        "app.infra.translators.local_providers_setup.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        installed = get_installed_local_providers()

        assert installed == []


# ============================================================================
# Test 6: Multiple Registrations
# ============================================================================


def test_initialize_local_providers_duplicate_registration(
    registry, mock_model_manager, mock_worker
):
    """Duplicate registration is handled gracefully without force_register."""
    with patch(
        "app.infra.translators.local_providers_setup.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.start_worker",
            return_value=mock_worker,
        ):
            with patch(
                "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
                return_value=mock_model_manager,
            ):
                with patch(
                    "app.infra.translators.providers.local_hymt_provider.start_worker",
                    return_value=mock_worker,
                ):
                    with patch(
                        "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
                        return_value=mock_model_manager,
                    ):
                        # First registration
                        count1 = initialize_local_providers()
                        assert count1 == 2

                        # Second registration should log error but not raise (without force_register)
                        count2 = initialize_local_providers()
                        assert count2 == 0  # No new providers registered
                        assert len(registry) == 2  # Still only two providers


def test_initialize_local_providers_duplicate_registration_force(
    registry, mock_model_manager, mock_worker
):
    """Duplicate registration raises error with force_register=True."""
    with patch(
        "app.infra.translators.local_providers_setup.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.start_worker",
            return_value=mock_worker,
        ):
            with patch(
                "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
                return_value=mock_model_manager,
            ):
                with patch(
                    "app.infra.translators.providers.local_hymt_provider.start_worker",
                    return_value=mock_worker,
                ):
                    with patch(
                        "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
                        return_value=mock_model_manager,
                    ):
                        # First registration
                        count1 = initialize_local_providers()
                        assert count1 == 2

                        # Second registration with force_register should raise
                        with pytest.raises(ValueError, match="already registered"):
                            initialize_local_providers(force_register=True)


# ============================================================================
# Test 7: Provider Initialization Failure
# ============================================================================


def test_initialize_local_providers_init_failure(registry, mock_model_manager):
    """Handle provider initialization failure gracefully."""
    # Model is installed, but provider init fails
    mock_model_manager.is_installed = Mock(return_value=(True, None))

    with patch(
        "app.infra.translators.local_providers_setup.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.LocalNLLBProvider.__init__",
            side_effect=RuntimeError("Init failed"),
        ):
            with patch(
                "app.infra.translators.providers.local_hymt_provider.LocalHYMTProvider.__init__",
                side_effect=RuntimeError("Init failed"),
            ):
                # Should not raise, just log error
                count = initialize_local_providers()

                assert count == 0
                assert len(registry) == 0


def test_initialize_local_providers_init_failure_force_register(registry, mock_model_manager):
    """Force register raises error on init failure."""
    mock_model_manager.is_installed = Mock(return_value=(True, None))

    with patch(
        "app.infra.translators.local_providers_setup.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.LocalNLLBProvider.__init__",
            side_effect=RuntimeError("Init failed"),
        ):
            with pytest.raises(RuntimeError, match="Init failed"):
                initialize_local_providers(force_register=True)


# ============================================================================
# Test 8: 7B GPTQ provider — disabled by default, visible in availability check
# ============================================================================


def test_7b_gptq_not_registered_by_default(registry, mock_model_manager, mock_worker):
    """7B provider must NOT be registered by default (enabled_by_default=False)."""
    with patch(
        "app.infra.translators.local_providers_setup.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.start_worker",
            return_value=mock_worker,
        ):
            with patch(
                "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
                return_value=mock_model_manager,
            ):
                with patch(
                    "app.infra.translators.providers.local_hymt_provider.start_worker",
                    return_value=mock_worker,
                ):
                    with patch(
                        "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
                        return_value=mock_model_manager,
                    ):
                        count = initialize_local_providers()

                        # Only nllb + hymt-1.8B registered; 7B is disabled by default
                        assert count == 2
                        assert registry.get("local_hymt_7b_gptq") is None


def test_7b_gptq_present_in_availability_check(mock_model_manager):
    """7B provider must appear in check_local_providers_available() result."""
    mock_model_manager.is_installed = Mock(return_value=(True, None))

    with patch(
        "app.infra.translators.local_providers_setup.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        status = check_local_providers_available()

        assert "local_hymt_7b_gptq" in status
        assert status["local_hymt_7b_gptq"]["model_id"] == "tencent/HY-MT1.5-7B-GPTQ-Int4"
        assert status["local_hymt_7b_gptq"]["backend"] == "transformers_causal"


def test_7b_gptq_registered_with_force_register(registry, mock_model_manager, mock_worker):
    """7B provider IS registered when force_register=True."""
    with patch(
        "app.infra.translators.local_providers_setup.ModelResourceManager",
        return_value=mock_model_manager,
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.start_worker",
            return_value=mock_worker,
        ):
            with patch(
                "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
                return_value=mock_model_manager,
            ):
                with patch(
                    "app.infra.translators.providers.local_hymt_provider.start_worker",
                    return_value=mock_worker,
                ):
                    with patch(
                        "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
                        return_value=mock_model_manager,
                    ):
                        count = initialize_local_providers(force_register=True)

                        # All 3 providers registered with force_register
                        assert count == 3
                        assert registry.get("local_hymt_7b_gptq") is not None
