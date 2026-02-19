"""Registry for audio providers."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .base_provider import BaseAudioProvider

logger = logging.getLogger(__name__)


class AudioProvidersRegistry:
    """Singleton registry for audio providers."""

    _instance: Optional["AudioProvidersRegistry"] = None
    _providers: Dict[str, BaseAudioProvider] = {}

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

    def get(self, provider_id: str) -> Optional[BaseAudioProvider]:
        """Get provider by ID."""
        return self._providers.get(provider_id)

    def list_provider_ids(self) -> List[str]:
        """Return sorted provider IDs."""
        return sorted(self._providers.keys())

    def list_providers(self) -> List[BaseAudioProvider]:
        """Return provider instances."""
        return [self._providers[k] for k in self.list_provider_ids()]
