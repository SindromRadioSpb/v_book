"""Stanza Hebrew NLP engine (M3)."""
import logging
from typing import List

from app.infra.nlp_engines.base import NLPEngine, Sentence, Token

logger = logging.getLogger(__name__)


class StanzaEngine(NLPEngine):
    """Stanza-based NLP engine for Hebrew (to be implemented in M3)."""

    def __init__(self):
        logger.warning("StanzaEngine not fully implemented yet")
        self._pipeline = None

    def get_name(self) -> str:
        return "stanza"

    def get_version(self) -> str:
        return "1.7.0"

    def process(self, text: str) -> List[Sentence]:
        """Process text (placeholder)."""
        logger.warning("StanzaEngine.process() not implemented yet")
        return []
