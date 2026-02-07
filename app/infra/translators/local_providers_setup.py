"""Local MT providers setup and registration.

This module handles initialization and registration of local MT providers.
Providers are only registered if their models are installed.

Usage:
    from app.infra.translators.local_providers_setup import initialize_local_providers

    # At app startup:
    initialize_local_providers(db_session, project_id)
"""
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.infra.translators.providers_registry import ProvidersRegistry
from app.infra.translators.providers.local_nllb_provider import LocalNLLBProvider
from app.services.local_models import ModelResourceManager

logger = logging.getLogger(__name__)


# ============================================================================
# Provider Configuration
# ============================================================================

LOCAL_PROVIDERS_CONFIG = [
    {
        "provider_class": LocalNLLBProvider,
        "model_id": "facebook/nllb-200-distilled-1.3B",
        "backend": "ctranslate2",
        "enabled_by_default": True,
    },
    # Add more local providers here in the future:
    # {
    #     "provider_class": LocalSeamlessProvider,
    #     "model_id": "facebook/seamless-m4t-v2-large",
    #     "backend": "transformers",
    #     "enabled_by_default": False,
    # },
]


# ============================================================================
# Initialization Functions
# ============================================================================


def initialize_local_providers(
    db_session: Optional[Session] = None,
    project_id: Optional[int] = None,
    force_register: bool = False,
) -> int:
    """
    Initialize and register local MT providers.

    This function:
    1. Checks if each provider's model is installed
    2. Initializes provider if model is available
    3. Registers provider in ProvidersRegistry

    Args:
        db_session: Optional database session for glossary postprocessing
        project_id: Optional project ID for TM scope
        force_register: If True, attempt to register even if model not installed
                       (will raise error if model missing)

    Returns:
        Number of providers successfully registered
    """
    registry = ProvidersRegistry()
    model_manager = ModelResourceManager()

    registered_count = 0

    for config in LOCAL_PROVIDERS_CONFIG:
        provider_class = config["provider_class"]
        model_id = config["model_id"]
        backend = config["backend"]
        enabled = config.get("enabled_by_default", True)

        if not enabled and not force_register:
            logger.debug(f"Skipping {provider_class.__name__} (disabled by default)")
            continue

        # Check if model is installed
        is_installed, reason = model_manager.is_installed(model_id, backend)

        if not is_installed:
            if force_register:
                logger.warning(
                    f"Model not installed for {provider_class.__name__}: {reason}. "
                    f"Attempting to register anyway (will fail if used)."
                )
            else:
                logger.info(
                    f"Skipping {provider_class.__name__}: model not installed ({reason})"
                )
                continue

        # Initialize provider
        try:
            provider = provider_class(
                model_id=model_id,
                backend=backend,
                db_session=db_session,
                project_id=project_id,
            )

            # Register provider
            try:
                registry.register(provider)
                registered_count += 1

                logger.info(
                    f"Registered local provider: {provider.provider_id} "
                    f"({provider.display_name})"
                )
            except ValueError as e:
                # Duplicate registration
                logger.error(f"Failed to register {provider_class.__name__}: {e}")
                if force_register:
                    raise
                # Otherwise continue (provider already registered)

        except Exception as e:
            logger.error(f"Failed to initialize {provider_class.__name__}: {e}")
            if force_register:
                raise

    return registered_count


def check_local_providers_available() -> dict:
    """
    Check which local providers have models installed.

    Returns:
        Dict mapping provider_id → availability status:
        {
            "local_nllb": {
                "available": True,
                "model_id": "facebook/nllb-200-distilled-1.3B",
                "reason": None or "Model not installed"
            }
        }
    """
    model_manager = ModelResourceManager()
    status = {}

    for config in LOCAL_PROVIDERS_CONFIG:
        provider_class = config["provider_class"]
        model_id = config["model_id"]
        backend = config["backend"]

        # Get provider_id (create temporary instance)
        try:
            # Get provider_id without full initialization
            provider_id = provider_class.provider_id.fget(None)  # Call property getter
        except:
            # Fallback: use class name
            provider_id = provider_class.__name__.lower().replace("provider", "")

        # Check model availability
        is_installed, reason = model_manager.is_installed(model_id, backend)

        status[provider_id] = {
            "available": is_installed,
            "model_id": model_id,
            "backend": backend,
            "reason": None if is_installed else reason,
        }

    return status


def unregister_local_providers() -> int:
    """
    Unregister all local MT providers.

    Useful for cleanup or testing.

    Returns:
        Number of providers unregistered
    """
    registry = ProvidersRegistry()
    unregistered_count = 0

    for config in LOCAL_PROVIDERS_CONFIG:
        provider_class = config["provider_class"]

        # Get provider_id
        try:
            provider_id = provider_class.provider_id.fget(None)
        except:
            provider_id = provider_class.__name__.lower().replace("provider", "")

        # Check if registered
        provider = registry.get(provider_id)
        if provider:
            # Shutdown provider if it has shutdown method
            if hasattr(provider, 'shutdown'):
                try:
                    provider.shutdown()
                except Exception as e:
                    logger.warning(f"Error shutting down {provider_id}: {e}")

            # Unregister
            if registry.unregister(provider_id):
                unregistered_count += 1
                logger.info(f"Unregistered local provider: {provider_id}")

    return unregistered_count


# ============================================================================
# Convenience Functions
# ============================================================================


def is_local_provider_available(provider_id: str) -> bool:
    """
    Check if a local provider is available (model installed).

    Args:
        provider_id: Provider ID (e.g., "local_nllb")

    Returns:
        True if provider's model is installed
    """
    status = check_local_providers_available()
    return status.get(provider_id, {}).get("available", False)


def get_installed_local_providers() -> list:
    """
    Get list of installed local provider IDs.

    Returns:
        List of provider IDs that have models installed
    """
    status = check_local_providers_available()
    return [
        provider_id
        for provider_id, info in status.items()
        if info["available"]
    ]
