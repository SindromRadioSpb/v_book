"""Stanza Hebrew NLP engine."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

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


class SubprocessStanzaEngine(NLPEngine):
    """Stanza engine hosted in a clean subprocess.

    Used as a production fallback when the main Qt process cannot import or
    initialize Torch/Stanza safely.
    """

    _STARTUP_TIMEOUT_SECONDS = 60

    def __init__(self, use_gpu: bool = False):
        self._process: subprocess.Popen[str] | None = None
        self._name = "stanza"
        self._version = "unknown"
        self._use_gpu = bool(use_gpu)
        self._start_worker()

    def get_name(self) -> str:
        return self._name

    def get_version(self) -> str:
        return self._version

    def process(self, text: str) -> list[Sentence]:
        if not text or not text.strip():
            return []

        process = self._require_process()
        assert process.stdin is not None
        assert process.stdout is not None

        process.stdin.write(
            json.dumps({"command": "process", "text": text}, ensure_ascii=False) + "\n"
        )
        process.stdin.flush()

        response_line = process.stdout.readline()
        if not response_line:
            stderr = self._read_stderr()
            raise RuntimeError(stderr or "Stanza subprocess exited unexpectedly")

        payload = json.loads(response_line)
        if not payload.get("ok"):
            raise RuntimeError(payload.get("error", "Unknown Stanza subprocess error"))

        return [
            Sentence(
                text=sentence["text"],
                tokens=[
                    Token(
                        text=token["text"],
                        lemma=token["lemma"],
                        pos=token["pos"],
                        morph=token["morph"],
                    )
                    for token in sentence["tokens"]
                ],
            )
            for sentence in payload["sentences"]
        ]

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.poll() is not None:
            return

        try:
            if process.stdin is not None:
                process.stdin.write(json.dumps({"command": "shutdown"}) + "\n")
                process.stdin.flush()
        except Exception:
            pass

        try:
            process.wait(timeout=2)
        except Exception:
            process.terminate()
            try:
                process.wait(timeout=5)
            except Exception:
                process.kill()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _start_worker(self) -> None:
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["HDLE_STANZA_WORKER_MODE"] = "gpu" if self._use_gpu else "cpu"

        process = subprocess.Popen(
            [sys.executable, "-u", "-m", "app.infra.nlp_engines.stanza_subprocess_worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=Path(__file__).resolve().parents[3],
            env=env,
        )

        assert process.stdout is not None
        startup_line = process.stdout.readline().strip()
        if not startup_line:
            stderr = ""
            if process.stderr is not None:
                stderr = process.stderr.read().strip()
            process.terminate()
            raise RuntimeError(stderr or "Stanza subprocess worker returned an empty handshake")

        payload = json.loads(startup_line)
        if not payload.get("ok"):
            process.terminate()
            raise RuntimeError(payload.get("error", "Stanza subprocess worker failed to start"))

        self._process = process
        self._name = str(payload.get("name") or "stanza")
        self._version = str(payload.get("version") or "unknown")

    def _require_process(self) -> subprocess.Popen[str]:
        if self._process is None or self._process.poll() is not None:
            raise RuntimeError(self._read_stderr() or "Stanza subprocess is not running")
        return self._process

    def _read_stderr(self) -> str:
        process = self._process
        if process is None or process.stderr is None:
            return ""
        try:
            return process.stderr.read().strip()
        except Exception:
            return ""


def _should_try_subprocess_fallback(exc: Exception) -> bool:
    if isinstance(exc, OSError):
        return True
    message = str(exc or "").lower()
    return any(
        marker in message
        for marker in (
            "c10.dll",
            "dll",
            "winerror 1114",
            "failed to initialize stanza pipeline",
        )
    )


def create_stanza_engine(use_gpu: bool = False) -> NLPEngine:
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
    try:
        return StanzaEngine(use_gpu=use_gpu)
    except Exception as exc:
        if not _should_try_subprocess_fallback(exc):
            raise
        logger.warning(
            "Stanza in-process init failed; trying subprocess fallback: %s",
            exc,
        )
        try:
            return SubprocessStanzaEngine(use_gpu=use_gpu)
        except Exception as sub_exc:
            raise RuntimeError(
                "Stanza failed in-process and subprocess fallback also failed.\n\n"
                f"In-process error: {exc}\n\n"
                f"Subprocess error: {sub_exc}"
            ) from sub_exc
