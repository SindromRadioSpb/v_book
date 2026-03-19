"""Base NLP engine interface (M3)."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Token:
    """Token with linguistic annotations."""

    text: str
    lemma: str
    pos: str
    morph: str = ""


@dataclass
class Sentence:
    """Sentence with tokens."""

    text: str
    tokens: list[Token]


class NLPEngine(ABC):
    """Abstract base class for NLP engines."""

    @abstractmethod
    def get_name(self) -> str:
        """Return engine name."""
        pass

    @abstractmethod
    def get_version(self) -> str:
        """Return engine version."""
        pass

    @abstractmethod
    def process(self, text: str) -> list[Sentence]:
        """Process text and return sentences with tokens."""
        pass
