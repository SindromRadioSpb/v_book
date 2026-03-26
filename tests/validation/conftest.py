"""Shared fixtures for NLP pipeline validation tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

GOLD_DIR = Path(__file__).parent / "gold"


def _stanza_available() -> bool:
    try:
        import stanza  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.fixture
def gold_data():
    """Loader fixture: gold_data('c04_ngram_extraction') → parsed JSON dict."""

    def _load(corpus_id: str) -> dict:
        path = GOLD_DIR / f"{corpus_id}.json"
        if not path.exists():
            pytest.skip(f"Gold corpus not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    return _load


@pytest.fixture(scope="session")
def stanza_engine():
    """Session-scoped Stanza engine fixture. Skips if Stanza not installed."""
    if not _stanza_available():
        pytest.skip("stanza not installed")
    from app.infra.nlp_engines.stanza_engine import StanzaEngine

    try:
        engine = StanzaEngine(use_gpu=False)
        return engine
    except Exception as exc:
        pytest.skip(f"Stanza Hebrew model unavailable: {exc}")


requires_stanza = pytest.mark.skipif(
    not _stanza_available(),
    reason="stanza not installed or Hebrew model missing",
)
