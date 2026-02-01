"""Statistical scoring functions for MWE (M5)."""
import math
import logging

logger = logging.getLogger(__name__)


def calculate_pmi(
    ngram_freq: int,
    component_freqs: list[int],
    total_tokens: int,
) -> float:
    """
    Calculate Pointwise Mutual Information for an n-gram.

    PMI(w1, w2) = log2(P(w1,w2) / (P(w1) * P(w2)))
    """
    if ngram_freq == 0 or total_tokens == 0:
        return 0.0

    p_ngram = ngram_freq / total_tokens
    p_components = 1.0
    for freq in component_freqs:
        if freq == 0:
            return 0.0
        p_components *= freq / total_tokens

    if p_components == 0:
        return 0.0

    pmi = math.log2(p_ngram / p_components)
    return pmi


def calculate_tscore(
    ngram_freq: int,
    component_freqs: list[int],
    total_tokens: int,
) -> float:
    """
    Calculate T-score for an n-gram.

    T-score = (P(w1,w2) - P(w1)*P(w2)) / sqrt(P(w1,w2))
    """
    if ngram_freq == 0 or total_tokens == 0:
        return 0.0

    p_ngram = ngram_freq / total_tokens
    p_components = 1.0
    for freq in component_freqs:
        if freq == 0:
            return 0.0
        p_components *= freq / total_tokens

    numerator = p_ngram - p_components
    denominator = math.sqrt(p_ngram / total_tokens)

    if denominator == 0:
        return 0.0

    tscore = numerator / denominator
    return tscore
