"""M7 Normalization module for Translation Memory.

Provides deterministic text normalization for TM lookup with strict
compatibility to M5's canonical_key to avoid desync.
"""

from .normalizer import NormalizedText, normalize_for_tm, normalize_text

__all__ = ["NormalizedText", "normalize_text", "normalize_for_tm"]
