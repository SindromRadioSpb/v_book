"""Mock NLP engine for diagnostic/demo and explicit fallback use."""

import logging
import re

from app.infra.nlp_engines.base import NLPEngine, Sentence, Token

logger = logging.getLogger(__name__)


class MockEngine(NLPEngine):
    """
    Mock NLP engine for diagnostic/demo and explicit fallback use.

    This is a simple rule-based engine that:
    - Tokenizes by whitespace
    - Uses basic Hebrew lemmatization rules
    - Assigns simple POS tags

    Use this only for testing, demo flows, or explicitly confirmed fallback.
    """

    def __init__(self):
        logger.info("Initializing MockEngine (rule-based, no ML)")
        self._simple_lemmatizer = SimpleHebrewLemmatizer()

    def get_name(self) -> str:
        return "mock"

    def get_version(self) -> str:
        return "1.0.0"

    def process(self, text: str) -> list[Sentence]:
        """
        Process text with simple rules.

        Args:
            text: Input text

        Returns:
            List of Sentence objects
        """
        if not text or not text.strip():
            return []

        sentences = []

        # Simple sentence splitting by punctuation
        sent_texts = re.split(r"([.!?]+\s+)", text)
        current = []

        for i in range(0, len(sent_texts), 2):
            part = sent_texts[i].strip()
            if part:
                current.append(part)
                if i + 1 < len(sent_texts):
                    current.append(sent_texts[i + 1].strip())

                sent_text = "".join(current).strip()
                if sent_text:
                    # Tokenize
                    tokens = self._tokenize(sent_text)
                    sentences.append(Sentence(text=sent_text, tokens=tokens))
                    current = []

        if current:
            sent_text = "".join(current).strip()
            if sent_text:
                tokens = self._tokenize(sent_text)
                sentences.append(Sentence(text=sent_text, tokens=tokens))

        logger.debug(f"Processed {len(sentences)} sentences (mock)")
        return sentences

    def _tokenize(self, text: str) -> list[Token]:
        """Simple whitespace tokenization."""
        tokens = []

        # Split by whitespace and punctuation
        words = re.findall(r"\S+", text)

        for word in words:
            # Remove trailing punctuation
            clean_word = re.sub(r"[.,!?;:]+$", "", word)
            if not clean_word:
                continue

            # Lemmatize
            lemma = self._simple_lemmatizer.lemmatize(clean_word)

            # Simple POS tagging
            pos = self._guess_pos(clean_word)

            tokens.append(
                Token(
                    text=clean_word,
                    lemma=lemma,
                    pos=pos,
                    morph="",
                )
            )

        return tokens

    def _guess_pos(self, word: str) -> str:
        """Very simple POS guessing."""
        # Hebrew verbs often start with certain letters
        if len(word) > 2:
            # Common Hebrew prefixes
            if word.startswith(("ה", "ו", "ב", "כ", "ל", "מ")):
                return "NOUN"
            return "VERB"
        return "X"


class SimpleHebrewLemmatizer:
    """Very simple rule-based Hebrew lemmatizer."""

    # Common Hebrew prefixes
    PREFIXES = ["ה", "ו", "ב", "כ", "ל", "מ", "ש"]

    # Common Hebrew suffixes
    SUFFIXES = ["ים", "ות", "ה", "י", "ך", "נו", "כם", "ן"]

    def lemmatize(self, word: str) -> str:
        """
        Simple lemmatization by removing common affixes.

        Note: This is NOT accurate! For real use, use Stanza.
        """
        if len(word) <= 2:
            return word

        result = word

        # Remove prefixes
        for prefix in self.PREFIXES:
            if result.startswith(prefix) and len(result) > 3:
                result = result[len(prefix) :]
                break

        # Remove suffixes
        for suffix in self.SUFFIXES:
            if result.endswith(suffix) and len(result) > len(suffix) + 1:
                result = result[: -len(suffix)]
                break

        return result if result else word


def create_mock_engine() -> MockEngine:
    """Factory for mock engine."""
    return MockEngine()
