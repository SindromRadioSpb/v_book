"""Provider registry for managing MT providers."""

import logging
from typing import Optional

from .base_provider import BaseProvider

logger = logging.getLogger(__name__)


class ProvidersRegistry:
    """Registry for MT providers (singleton)."""

    _instance: Optional["ProvidersRegistry"] = None
    _providers: dict[str, BaseProvider] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._providers = {}
        return cls._instance

    @classmethod
    def reset(cls):
        """Reset singleton instance (for tests)."""
        cls._instance = None
        cls._providers = {}

    def register(self, provider: BaseProvider) -> None:
        """
        Register a provider.

        Args:
            provider: Provider instance to register

        Raises:
            ValueError: If provider_id already registered
        """
        provider_id = provider.provider_id

        if provider_id in self._providers:
            raise ValueError(f"Provider '{provider_id}' already registered")

        self._providers[provider_id] = provider
        logger.info(f"Registered MT provider: {provider_id} ({provider.display_name})")

    def get(self, provider_id: str) -> BaseProvider | None:
        """
        Get provider by ID.

        Args:
            provider_id: Provider ID (e.g., 'deepl', 'google')

        Returns:
            Provider instance or None if not found
        """
        return self._providers.get(provider_id)

    def list_providers(self) -> list[BaseProvider]:
        """
        List all registered providers.

        Returns:
            List of provider instances
        """
        return list(self._providers.values())

    def list_provider_ids(self) -> list[str]:
        """
        List all registered provider IDs.

        Returns:
            List of provider IDs (sorted alphabetically)
        """
        return sorted(self._providers.keys())

    def unregister(self, provider_id: str) -> bool:
        """
        Unregister a provider.

        Args:
            provider_id: Provider ID to unregister

        Returns:
            True if provider was unregistered, False if not found
        """
        if provider_id in self._providers:
            del self._providers[provider_id]
            logger.info(f"Unregistered MT provider: {provider_id}")
            return True
        return False

    def __len__(self) -> int:
        """Get number of registered providers."""
        return len(self._providers)
