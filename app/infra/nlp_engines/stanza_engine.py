"""Stanza Hebrew NLP engine."""

import logging

from app.infra.nlp_engines.base import NLPEngine, Sentence, Token

logger = logging.getLogger(__name__)


class StanzaEngine(NLPEngine):
    """
    Stanza-based NLP engine for Hebrew.

    Provides:
    - Sentence segmentation
    - Tokenization
    - Lemmatization
    - POS tagging
    - Morphological features
    """

    def __init__(self, use_gpu: bool = False):
        """
        Initialize Stanza pipeline.

        Args:
            use_gpu: Whether to use GPU acceleration (requires CUDA)

        Raises:
            ImportError: If stanza is not installed
            RuntimeError: If Hebrew model is not downloaded
        """
        logger.info("Initializing StanzaEngine...")

        try:
            import stanza
        except ImportError:
            raise ImportError(
                "Stanza is not installed. Install with: pip install stanza\n"
                "Then download Hebrew model: python -c \"import stanza; stanza.download('he')\""
            )

        self.stanza = stanza

        try:
            # Initialize pipeline
            # processors: tokenize, pos, lemma
            self._pipeline = stanza.Pipeline(
                lang="he",
                processors="tokenize,pos,lemma",
                use_gpu=use_gpu,
                verbose=False,
                download_method=None,  # Don't auto-download
            )
            logger.info("Stanza Hebrew pipeline initialized successfully")
        except Exception as e:
            error_msg = (
                f"Failed to initialize Stanza pipeline: {e}\n"
                "Make sure Hebrew model is downloaded:\n"
                "  python -c \"import stanza; stanza.download('he')\""
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def get_name(self) -> str:
        """Return engine name."""
        return "stanza"

    def get_version(self) -> str:
        """Return engine version."""
        try:
            return self.stanza.__version__
        except Exception:
            return "unknown"

    def process(self, text: str) -> list[Sentence]:
        """
        Process text with Stanza.

        Args:
            text: Input text (can contain multiple sentences)

        Returns:
            List of Sentence objects with tokens

        Raises:
            RuntimeError: If processing fails
        """
        if not text or not text.strip():
            return []

        try:
            # Process with Stanza
            doc = self._pipeline(text)

            sentences = []

            for sent in doc.sentences:
                # Extract tokens
                tokens = []
                for word in sent.words:
                    token = Token(
                        text=word.text,
                        lemma=word.lemma if word.lemma else word.text,
                        pos=word.upos if word.upos else "X",  # Universal POS tag
                        morph=self._format_feats(word.feats) if word.feats else "",
                    )
                    tokens.append(token)

                # Create sentence
                sentence = Sentence(
                    text=sent.text,
                    tokens=tokens,
                )
                sentences.append(sentence)

            logger.debug(
                f"Processed {len(sentences)} sentences, {sum(len(s.tokens) for s in sentences)} tokens"
            )
            return sentences

        except Exception as e:
            logger.exception(f"Stanza processing failed: {e}")
            raise RuntimeError(f"NLP processing failed: {e}")

    def _format_feats(self, feats: str | None) -> str:
        """
        Format morphological features.

        Args:
            feats: Features string from Stanza (e.g., "Gender=Masc|Number=Sing")

        Returns:
            Formatted features string
        """
        if not feats:
            return ""
        # Keep as-is for now (already in key=value format)
        return feats


def create_stanza_engine(use_gpu: bool = False) -> StanzaEngine:
    """
    Factory function to create Stanza engine.

    Args:
        use_gpu: Whether to use GPU

    Returns:
        StanzaEngine instance

    Raises:
        ImportError: If stanza not available
        RuntimeError: If model not downloaded
    """
    return StanzaEngine(use_gpu=use_gpu)
