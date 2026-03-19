"""Registry for audio providers."""

from __future__ import annotations

import logging

from .base_provider import BaseAudioProvider

logger = logging.getLogger(__name__)


class AudioProvidersRegistry:
    """Singleton registry for audio providers."""

    _instance: AudioProvidersRegistry | None = None
    _providers: dict[str, BaseAudioProvider] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._providers = {}
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton instance (tests)."""
        cls._instance = None
        cls._providers = {}

    def register(self, provider: BaseAudioProvider) -> None:
        """Register provider by unique ID."""
        provider_id = provider.provider_id
        if provider_id in self._providers:
            raise ValueError(f"Audio provider '{provider_id}' already registered")
        self._providers[provider_id] = provider
        logger.info("Registered audio provider: %s (%s)", provider_id, provider.display_name)

    def get(self, provider_id: str) -> BaseAudioProvider | None:
        """Get provider by ID."""
        return self._providers.get(provider_id)

    def list_provider_ids(self) -> list[str]:
        """Return sorted provider IDs."""
        return sorted(self._providers.keys())

    def list_providers(self) -> list[BaseAudioProvider]:
        """Return provider instances."""
        return [self._providers[k] for k in self.list_provider_ids()]
