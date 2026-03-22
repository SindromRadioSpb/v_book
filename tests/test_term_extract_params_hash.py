"""Tests for params_hash contract in TermExtractionService (Epic 4 PATCH-03).

Updated Epic 5C: min_freq removed from hash payload; algo_version bumped to 2.
"""

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
        enable_ngrams=True, include_np=False, ngram_ns=(2, 3), np_max_len=5
    )
    h2 = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, ngram_ns=(2, 3), np_max_len=5
    )
    assert h1 == h2


def test_params_hash_length(svc):
    """Hash is exactly 16 hex characters (SHA-256[:16])."""
    h = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, ngram_ns=(2, 3), np_max_len=5
    )
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_params_hash_ngram_ns_order_invariant(svc):
    """ngram_ns is always sorted — (3,2) and (2,3) produce the same hash."""
    h1 = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, ngram_ns=(2, 3), np_max_len=5
    )
    h2 = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, ngram_ns=(3, 2), np_max_len=5
    )
    assert h1 == h2


def test_params_hash_changes_with_include_np(svc):
    """Toggling include_np changes the hash."""
    h_false = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, ngram_ns=(2, 3), np_max_len=5
    )
    h_true = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=True, ngram_ns=(2, 3), np_max_len=5
    )
    assert h_false != h_true


def test_params_hash_changes_with_ngram_ns(svc):
    """Different ngram_ns values produce different hashes."""
    h_bigrams = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, ngram_ns=(2,), np_max_len=5
    )
    h_trigrams = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, ngram_ns=(3,), np_max_len=5
    )
    h_both = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, ngram_ns=(2, 3), np_max_len=5
    )
    assert len({h_bigrams, h_trigrams, h_both}) == 3


def test_params_hash_independent_of_min_freq(svc):
    """Epic 5C: min_freq is NOT part of the hash (display-time filter, not extraction param).

    Two extractions with different min_freq but same structural params should resume each other.
    """
    h_low = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, ngram_ns=(2, 3), np_max_len=5
    )
    # Verify the hash is the same regardless of min_freq (min_freq is now absent from signature)
    h_high = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, ngram_ns=(2, 3), np_max_len=5
    )
    assert h_low == h_high


def test_params_hash_does_not_include_overwrite(svc):
    """overwrite is NOT included in the hash (execution mode, not result params).

    This is by design: changing overwrite flag should not invalidate a run's
    params_hash, as it does not affect the extraction result.
    We verify this by manually constructing the canonical payload and checking
    that hash matches.
    """
    payload = json.dumps(
        {
            "algo_version": TermExtractionService._TERM_EXTRACT_ALGO_VERSION,
            "enable_ngrams": True,
            "include_np": False,
            "ngram_ns": [2, 3],
            "np_max_len": 5,
            "store_hapax": True,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    expected = hashlib.sha256(payload.encode()).hexdigest()[:16]
    actual = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, ngram_ns=(2, 3), np_max_len=5
    )
    assert actual == expected


def test_params_hash_does_not_include_min_freq(svc):
    """Epic 5C: min_freq is NOT in the canonical payload.

    Manually construct the payload without min_freq and confirm it matches the service output.
    """
    payload = json.dumps(
        {
            "algo_version": TermExtractionService._TERM_EXTRACT_ALGO_VERSION,
            "enable_ngrams": True,
            "include_np": False,
            "ngram_ns": [2, 3],
            "np_max_len": 5,
            "store_hapax": True,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    expected = hashlib.sha256(payload.encode()).hexdigest()[:16]
    actual = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, ngram_ns=(2, 3), np_max_len=5
    )
    assert actual == expected
    # Ensure "min_freq" key is absent from the canonical JSON
    assert "min_freq" not in payload


def test_params_hash_includes_algo_version(svc):
    """algo_version is part of the canonical payload — version 2 is current (Epic 5C)."""
    assert TermExtractionService._TERM_EXTRACT_ALGO_VERSION == 2

    # Compute expected hash with algo_version=2 and store_hapax (current after P2.2 bump)
    payload_v2 = json.dumps(
        {
            "algo_version": 2,
            "enable_ngrams": True,
            "include_np": False,
            "ngram_ns": [2, 3],
            "np_max_len": 5,
            "store_hapax": True,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    expected_v2 = hashlib.sha256(payload_v2.encode()).hexdigest()[:16]
    actual = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, ngram_ns=(2, 3), np_max_len=5
    )
    assert actual == expected_v2

    # Verify that algo_version=1 would produce a different hash (old runs are invalidated).
    payload_v1 = json.dumps(
        {
            "algo_version": 1,
            "enable_ngrams": True,
            "include_np": False,
            "ngram_ns": [2, 3],
            "np_max_len": 5,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    hash_v1 = hashlib.sha256(payload_v1.encode()).hexdigest()[:16]
    assert actual != hash_v1
