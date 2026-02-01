"""Sentence splitting utilities."""
import re
import logging
from typing import List

logger = logging.getLogger(__name__)


class SentenceSplitter:
    """
    Sentence splitter for Hebrew text.

    Uses simple rule-based approach for splitting sentences.
    For production, consider using Stanza's sentence splitting.
    """

    # Sentence-ending punctuation
    SENTENCE_ENDERS = r'[.!?。！？]+'

    # Abbreviations that don't end sentences (Hebrew examples)
    ABBREVIATIONS = {
        'ד"ר',  # Doctor
        'פרופ',  # Professor
        'מר',  # Mr.
        'גב',  # Ms.
        'ת"א',  # Tel Aviv
        'י-ם',  # Jerusalem
        'בע"מ',  # Ltd.
        'ת.ד',  # P.O. Box
    }

    def __init__(self):
        # Compile regex for sentence splitting
        self.sentence_pattern = re.compile(
            f'({self.SENTENCE_ENDERS})'
            r'(?:\s+|$)',  # Followed by whitespace or end
            re.MULTILINE
        )

    def split(self, text: str) -> List[str]:
        """
        Split text into sentences.

        Args:
            text: Input text

        Returns:
            List of sentences (stripped, non-empty)
        """
        if not text or not text.strip():
            return []

        # Simple approach: split on sentence-ending punctuation
        sentences = []
        current = []

        # Split by lines first (preserves paragraph structure)
        lines = text.split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                # Empty line might end a sentence
                if current:
                    sentences.append(' '.join(current))
                    current = []
                continue

            # Split line by sentence enders
            parts = self.sentence_pattern.split(line)

            for i in range(0, len(parts), 2):
                text_part = parts[i].strip()
                if not text_part:
                    continue

                # Check if followed by punctuation
                punct = parts[i + 1].strip() if i + 1 < len(parts) else ''

                # Add to current sentence
                current.append(text_part)
                if punct:
                    current.append(punct)

                # If we have sentence-ending punctuation, finish sentence
                if punct and not self._is_abbreviation(' '.join(current)):
                    sentences.append(' '.join(current))
                    current = []

        # Add remaining text as last sentence
        if current:
            sentences.append(' '.join(current))

        # Filter and clean
        sentences = [s.strip() for s in sentences if s.strip()]

        logger.debug(f"Split text into {len(sentences)} sentences")
        return sentences

    def _is_abbreviation(self, text: str) -> bool:
        """Check if text ends with known abbreviation."""
        for abbr in self.ABBREVIATIONS:
            if text.strip().endswith(abbr):
                return True
        return False


def split_into_sentences(text: str) -> List[str]:
    """
    Convenience function to split text into sentences.

    Args:
        text: Input text

    Returns:
        List of sentences
    """
    splitter = SentenceSplitter()
    return splitter.split(text)
