"""Tests for params_hash contract in TermExtractionService (Epic 4 PATCH-03)."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from app.services.db_service import DBService
from app.services.term_extraction_service import TermExtractionService


@pytest.fixture()
def svc(monkeypatch):
    monkeypatch.setattr(DBService, "_instance", SimpleNamespace())
    return TermExtractionService()


# ---------------------------------------------------------------------------
# Canonical hash contract
# ---------------------------------------------------------------------------


def test_params_hash_deterministic(svc):
    """Same params produce the same hash on repeated calls."""
    h1 = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, min_freq=2, ngram_ns=(2, 3), np_max_len=5
    )
    h2 = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, min_freq=2, ngram_ns=(2, 3), np_max_len=5
    )
    assert h1 == h2


def test_params_hash_length(svc):
    """Hash is exactly 16 hex characters (SHA-256[:16])."""
    h = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, min_freq=2, ngram_ns=(2, 3), np_max_len=5
    )
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_params_hash_ngram_ns_order_invariant(svc):
    """ngram_ns is always sorted — (3,2) and (2,3) produce the same hash."""
    h1 = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, min_freq=2, ngram_ns=(2, 3), np_max_len=5
    )
    h2 = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, min_freq=2, ngram_ns=(3, 2), np_max_len=5
    )
    assert h1 == h2


def test_params_hash_changes_with_include_np(svc):
    """Toggling include_np changes the hash."""
    h_false = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, min_freq=2, ngram_ns=(2, 3), np_max_len=5
    )
    h_true = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=True, min_freq=2, ngram_ns=(2, 3), np_max_len=5
    )
    assert h_false != h_true


def test_params_hash_changes_with_ngram_ns(svc):
    """Different ngram_ns values produce different hashes."""
    h_bigrams = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, min_freq=2, ngram_ns=(2,), np_max_len=5
    )
    h_trigrams = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, min_freq=2, ngram_ns=(3,), np_max_len=5
    )
    h_both = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, min_freq=2, ngram_ns=(2, 3), np_max_len=5
    )
    assert len({h_bigrams, h_trigrams, h_both}) == 3


def test_params_hash_changes_with_min_freq(svc):
    """Different min_freq produces different hash."""
    h2 = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, min_freq=2, ngram_ns=(2, 3), np_max_len=5
    )
    h5 = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, min_freq=5, ngram_ns=(2, 3), np_max_len=5
    )
    assert h2 != h5


def test_params_hash_does_not_include_overwrite(svc):
    """overwrite is NOT included in the hash (execution mode, not result params).

    This is by design: changing overwrite flag should not invalidate a run's
    params_hash, as it does not affect the extraction result.
    We verify this by manually constructing the canonical payload and checking
    that hash matches regardless of overwrite.
    """
    # Two calls that would differ only in overwrite produce the same payload structure.
    # We verify by re-implementing the canonical payload ourselves.
    payload = json.dumps(
        {
            "algo_version": TermExtractionService._TERM_EXTRACT_ALGO_VERSION,
            "enable_ngrams": True,
            "include_np": False,
            "min_freq": 2,
            "ngram_ns": [2, 3],
            "np_max_len": 5,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    expected = hashlib.sha256(payload.encode()).hexdigest()[:16]
    actual = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, min_freq=2, ngram_ns=(2, 3), np_max_len=5
    )
    assert actual == expected


def test_params_hash_includes_algo_version(svc):
    """algo_version is part of the canonical payload — changing it would change the hash."""
    # Compute expected hash with algo_version=1 (current)
    payload_v1 = json.dumps(
        {
            "algo_version": 1,
            "enable_ngrams": True,
            "include_np": False,
            "min_freq": 2,
            "ngram_ns": [2, 3],
            "np_max_len": 5,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    expected_v1 = hashlib.sha256(payload_v1.encode()).hexdigest()[:16]
    actual = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, min_freq=2, ngram_ns=(2, 3), np_max_len=5
    )
    assert actual == expected_v1

    # Verify that algo_version=2 would produce a different hash (future-proofing check).
    payload_v2 = json.dumps(
        {
            "algo_version": 2,
            "enable_ngrams": True,
            "include_np": False,
            "min_freq": 2,
            "ngram_ns": [2, 3],
            "np_max_len": 5,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    hash_v2 = hashlib.sha256(payload_v2.encode()).hexdigest()[:16]
    assert actual != hash_v2
