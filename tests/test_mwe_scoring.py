"""Test MWE scoring (M5)."""

import pytest
from app.domain.scoring import calculate_pmi, calculate_tscore


def test_calculate_pmi():
    """Test PMI calculation."""
    # Simple example: bigram "בית ספר"
    ngram_freq = 10
    component_freqs = [50, 20]  # "בית" appears 50 times, "ספר" 20 times
    total_tokens = 1000

    pmi = calculate_pmi(ngram_freq, component_freqs, total_tokens)
    assert pmi > 0  # Should be positive for a collocation


def test_calculate_tscore():
    """Test T-score calculation."""
    ngram_freq = 10
    component_freqs = [50, 20]
    total_tokens = 1000

    tscore = calculate_tscore(ngram_freq, component_freqs, total_tokens)
    assert tscore != 0  # Should be non-zero
