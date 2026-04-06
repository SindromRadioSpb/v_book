"""Local MT providers setup and registration.

This module handles initialization and registration of local MT providers.
Providers are only registered if their models are installed.

Usage:
    from app.infra.translators.local_providers_setup import initialize_local_providers

    # At app startup:
    initialize_local_providers(db_session, project_id)
"""

import logging
import threading

from sqlalchemy.orm import Session

from app.infra.settings import SettingsService
from app.infra.translators.provider_config_manager import ProviderConfigManager
from app.infra.translators.providers.google_cloud_translate_provider import (
    GoogleCloudTranslateProvider,
)
from app.infra.translators.providers.google_translate_provider import GoogleTranslateProvider
from app.infra.translators.providers.local_hymt_provider import LocalHYMTProvider
from app.infra.translators.providers.local_nllb_provider import LocalNLLBProvider
from app.infra.translators.providers_registry import ProvidersRegistry
from app.services.local_models import ModelResourceManager

logger = logging.getLogger(__name__)

# Global lock for provider initialization to prevent concurrent worker starts
_provider_init_lock = threading.Lock()
_initializing_providers = set()  # Track which providers are currently being initialized


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
    {
        "provider_class": LocalHYMTProvider,
        "model_id": "tencent/HY-MT1.5-1.8B",
        "backend": "transformers_causal",
        "enabled_by_default": True,
    },
]


# ============================================================================
# Initialization Functions
# ============================================================================


def initialize_local_providers(
    db_session: Session | None = None,
    project_id: int | None = None,
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
                logger.info(f"Skipping {provider_class.__name__}: model not installed ({reason})")
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
        except Exception:
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
        except Exception:
            provider_id = provider_class.__name__.lower().replace("provider", "")

        # Check if registered
        provider = registry.get(provider_id)
        if provider:
            # Shutdown provider if it has shutdown method
            if hasattr(provider, "shutdown"):
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
    return [provider_id for provider_id, info in status.items() if info["available"]]


def register_google_translate() -> bool:
    """
    Register Google Translate provider (always available, no model needed).

    Returns:
        True if registered successfully, False otherwise
    """
    registry = ProvidersRegistry()

    # Check if already registered
    if registry.get("google_translate"):
        logger.debug("Google Translate already registered")
        return True

    try:
        provider = GoogleTranslateProvider()
        registry.register(provider)
        logger.info("Registered Google Translate provider")
        return True
    except Exception as e:
        logger.error(f"Failed to register Google Translate: {e}")
        return False


def register_google_cloud_translate() -> bool:
    """
    Register Google Cloud Translate provider (Official API v3).

    Requires Service Account JSON to be configured in settings.
    Provider is registered even if auth not configured, but will return errors
    when used until credentials are set up.

    Provider creates DB sessions as needed for usage tracking (budget guards).

    Returns:
        True if registered successfully, False otherwise

    Note:
        Provider enabled status is controlled by settings. If disabled in UI,
        it won't be used even if registered here.
    """
    registry = ProvidersRegistry()

    # Check if already registered
    if registry.get("google_cloud_translate"):
        logger.debug("Google Cloud Translate already registered")
        return True

    try:
        # Initialize config manager
        settings_service = SettingsService.get_instance()
        config_manager = ProviderConfigManager(settings_service)

        # Create provider (creates DB sessions as needed for usage tracking)
        provider = GoogleCloudTranslateProvider(
            config_manager=config_manager,
        )

        registry.register(provider)
        logger.info("Registered Google Cloud Translate provider")
        return True

    except Exception as e:
        logger.error(f"Failed to register Google Cloud Translate: {e}")
        return False


def initialize_provider_lazy(
    provider_id: str,
    db_session: Session | None = None,
    project_id: int | None = None,
) -> bool:
    """
    Lazily initialize a single local provider if not already registered.

    This function checks if the provider is already registered, and if not,
    attempts to initialize it (if the model is installed).

    Args:
        provider_id: Provider ID (e.g., "local_nllb")
        db_session: Optional database session for glossary postprocessing
        project_id: Optional project ID for TM scope

    Returns:
        True if provider is now available (was registered or already existed)
        False if provider could not be initialized

    Note:
        This function is thread-safe and can be called multiple times.
        Subsequent calls for the same provider_id are no-ops if already registered.
        Uses a lock to prevent concurrent initialization of the same provider.
    """
    registry = ProvidersRegistry()

    # Quick check without lock (fast path)
    if registry.get(provider_id):
        return True

    # Use lock to prevent concurrent initialization
    with _provider_init_lock:
        # Double-check after acquiring lock (another thread may have initialized it)
        if registry.get(provider_id):
            return True

        # Check if another thread is currently initializing this provider
        if provider_id in _initializing_providers:
            logger.info(
                f"Provider {provider_id} is being initialized by another thread, waiting..."
            )
            # Release lock and wait a bit, then retry
            import time

            time.sleep(1)
            return initialize_provider_lazy(provider_id, db_session, project_id)

        # Mark as initializing
        _initializing_providers.add(provider_id)

    try:
        # Find provider config
        provider_config = None
        for config in LOCAL_PROVIDERS_CONFIG:
            provider_class = config["provider_class"]
            # Get provider_id from class
            try:
                config_provider_id = provider_class.provider_id.fget(None)
            except Exception:
                config_provider_id = provider_class.__name__.lower().replace("provider", "")

            if config_provider_id == provider_id:
                provider_config = config
                break

        if not provider_config:
            logger.warning(f"Unknown local provider: {provider_id}")
            return False

        # Check if model is installed
        model_manager = ModelResourceManager()
        model_id = provider_config["model_id"]
        backend = provider_config["backend"]

        is_installed, reason = model_manager.is_installed(model_id, backend)
        if not is_installed:
            logger.info(f"Cannot initialize {provider_id}: {reason}")
            return False

        # Initialize provider
        provider_class = provider_config["provider_class"]
        logger.info(
            f"Starting initialization of {provider_id} (this may take 10-30s for model loading)..."
        )
        provider = provider_class(
            model_id=model_id,
            backend=backend,
            db_session=db_session,
            project_id=project_id,
        )

        # Register provider
        try:
            registry.register(provider)
            logger.info(f"Lazily registered local provider: {provider_id}")
            return True
        except ValueError as e:
            # Already registered (race condition)
            logger.debug(f"Provider {provider_id} already registered: {e}")
            return True

    except Exception as e:
        logger.error(f"Failed to lazily initialize {provider_id}: {e}")
        return False

    finally:
        # Always remove from initializing set
        with _provider_init_lock:
            _initializing_providers.discard(provider_id)
