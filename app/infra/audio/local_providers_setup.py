"""Audio providers registration helpers."""

from __future__ import annotations

import logging

from app.infra.audio.providers import MockLocalAudioProvider, MockOnlineAudioProvider
from app.infra.audio.providers_registry import AudioProvidersRegistry

logger = logging.getLogger(__name__)


def register_default_audio_providers() -> int:
    """Register built-in audio providers idempotently."""
    registry = AudioProvidersRegistry()
    added = 0

    for provider_cls in (MockLocalAudioProvider, MockOnlineAudioProvider):
        provider = provider_cls()
        if registry.get(provider.provider_id):
            continue
        try:
            registry.register(provider)
            added += 1
        except ValueError:
            continue

    if added:
        logger.info("Registered %s default audio providers", added)
    return added
