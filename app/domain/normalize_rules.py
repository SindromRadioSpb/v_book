"""Normalization rules (M3)."""
import logging

logger = logging.getLogger(__name__)


class NormalizationRules:
    """Manages text normalization rules (to be implemented in M3)."""

    def __init__(self):
        self.rules = {}
        logger.info("NormalizationRules initialized (placeholder)")

    def apply(self, text: str) -> str:
        """Apply normalization rules to text."""
        return text
