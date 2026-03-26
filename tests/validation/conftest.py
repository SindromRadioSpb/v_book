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


def _stanza_he_model_available() -> bool:
    """Check if Stanza Hebrew model directory exists (cheap filesystem check, no pipeline load).

    Returns True only if:
    - stanza package is importable, AND
    - the he/ model directory exists under DEFAULT_MODEL_DIR.

    Does NOT verify that the pipeline can be loaded — use the stanza_engine fixture for that.
    Default model cache: C:\\Users\\<user>\\AppData\\Local\\StanfordNLP\\stanza\\Cache\\<version>\\resources
    Override with STANZA_HOME environment variable.
    """
    if not _stanza_available():
        return False
    try:
        import stanza.resources.common as src

        model_dir = Path(src.DEFAULT_MODEL_DIR) / "he"
        return model_dir.exists()
    except Exception:
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
    """Session-scoped Stanza engine fixture.

    Skip paths (in order):
    1. stanza package not importable → pytest.skip("stanza not installed")
    2. StanzaEngine init fails (model missing or corrupt) → pytest.skip(...)

    Pass path: returns initialized StanzaEngine(use_gpu=False).

    This is the authoritative gate for model availability.
    _stanza_he_model_available() is a cheap pre-check; this fixture is the real one.
    """
    if not _stanza_available():
        pytest.skip("stanza not installed")
    from app.infra.nlp_engines.stanza_engine import StanzaEngine

    try:
        engine = StanzaEngine(use_gpu=False)
        return engine
    except Exception as exc:
        pytest.skip(f"Stanza Hebrew model unavailable: {exc}")


# ---------------------------------------------------------------------------
# requires_stanza marker
# ---------------------------------------------------------------------------
# Evaluated at import time via _stanza_he_model_available() — cheap filesystem check.
# Skips when: stanza package is not installed, OR he/ model directory is absent.
# Does NOT skip when: package + model directory present but pipeline load fails —
# in that case the stanza_engine fixture handles it via pytest.skip().
#
# Usage:
#   @requires_stanza
#   def test_something(stanza_engine): ...
#
# Run only stanza tests:
#   pytest tests/validation/ -m requires_stanza
#
# Run without stanza tests:
#   pytest tests/validation/ -m "not requires_stanza"
# ---------------------------------------------------------------------------
requires_stanza = pytest.mark.skipif(
    not _stanza_he_model_available(),
    reason="stanza not installed or Hebrew 'he' model directory not found",
)
