"""Association measures for term extraction (M5, M5.2).

Implements:
- PMI (Pointwise Mutual Information)
- T-score
- LLR (Log-Likelihood Ratio)
- Dice coefficient
"""
import math
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def compute_pmi(c_xy: int, c_x: int, c_y: int, n: int) -> Optional[float]:
    """
    Compute Pointwise Mutual Information (PMI) for bigram.

    PMI(x,y) = log2( P(x,y) / (P(x) * P(y)) )
             = log2( (c_xy * N) / (c_x * c_y) )

    Args:
        c_xy: Count of bigram (x,y)
        c_x: Count of first word x
        c_y: Count of second word y
        n: Total token count in corpus

    Returns:
        PMI score (higher = stronger association), or None if invalid

    Note:
        - Positive PMI indicates co-occurrence above chance
        - Negative PMI indicates independence or avoidance
        - PMI is biased towards rare events
    """
    if c_xy <= 0 or c_x <= 0 or c_y <= 0 or n <= 0:
        return None

    try:
        pmi = math.log2((c_xy * n) / (c_x * c_y))
        return pmi
    except (ValueError, ZeroDivisionError):
        return None


def compute_tscore(c_xy: int, c_x: int, c_y: int, n: int) -> Optional[float]:
    """
    Compute T-score for bigram.

    T-score = (P(x,y) - P(x)*P(y)) / sqrt(P(x,y) / N)
            ≈ (c_xy - c_x*c_y/N) / sqrt(c_xy / N)

    Args:
        c_xy: Count of bigram (x,y)
        c_x: Count of first word x
        c_y: Count of second word y
        n: Total token count in corpus

    Returns:
        T-score (higher = stronger association), or None if invalid

    Note:
        - T-score is more stable than PMI for frequent terms
        - Less biased towards rare events
    """
    if c_xy <= 0 or n <= 0:
        return None

    try:
        expected = (c_x * c_y) / n if n > 0 else 0
        observed = c_xy
        variance = observed / n if n > 0 else 0

        if variance <= 0:
            return None

        tscore = (observed - expected) / math.sqrt(variance)
        return tscore
    except (ValueError, ZeroDivisionError):
        return None


def compute_llr(c_xy: int, c_x: int, c_y: int, n: int) -> Optional[float]:
    """
    Compute Log-Likelihood Ratio (LLR) for bigram.

    LLR tests the hypothesis that x and y are independent.
    Uses contingency table:
        | x    | ¬x   | total
    ----+------+------+------
    y   | c_xy | c_y_nx | c_y
    ¬y  | c_x_ny | c_nx_ny | c_ny
    ----+------+------+------
    tot | c_x  | c_nx | n

    LLR = 2 * sum( O_ij * log(O_ij / E_ij) )

    Args:
        c_xy: Count of bigram (x,y)
        c_x: Count of word x
        c_y: Count of word y
        n: Total token count

    Returns:
        LLR score (higher = stronger association), or None if invalid

    Note:
        - LLR is robust for sparse data
        - Can be used with chi-square distribution for significance testing
        - Threshold: LLR > 10.83 is significant at p < 0.001
    """
    if n <= 0 or c_x <= 0 or c_y <= 0:
        return None

    # Contingency table
    o11 = c_xy
    o12 = c_y - c_xy
    o21 = c_x - c_xy
    o22 = n - c_x - c_y + c_xy

    # Expected values
    e11 = (c_x * c_y) / n
    e12 = (c_x * (n - c_y)) / n
    e21 = ((n - c_x) * c_y) / n
    e22 = ((n - c_x) * (n - c_y)) / n

    def safe_log_ratio(o: int, e: float) -> float:
        if o <= 0 or e <= 0:
            return 0.0
        return o * math.log(o / e)

    try:
        llr = 2 * (
            safe_log_ratio(o11, e11) +
            safe_log_ratio(o12, e12) +
            safe_log_ratio(o21, e21) +
            safe_log_ratio(o22, e22)
        )
        return llr
    except (ValueError, ZeroDivisionError):
        return None


def compute_dice(c_xy: int, c_x: int, c_y: int) -> Optional[float]:
    """
    Compute Dice coefficient for bigram.

    Dice = 2 * c_xy / (c_x + c_y)

    Args:
        c_xy: Count of bigram (x,y)
        c_x: Count of word x
        c_y: Count of word y

    Returns:
        Dice coefficient [0, 1] (higher = stronger association), or None if invalid

    Note:
        - Dice is normalized (0 to 1)
        - Dice = 1 means x and y always occur together
        - Dice = 0 means x and y never co-occur
    """
    if c_x <= 0 or c_y <= 0:
        return None

    try:
        dice = (2 * c_xy) / (c_x + c_y)
        return dice
    except ZeroDivisionError:
        return None


def compute_all_measures(c_xy: int, c_x: int, c_y: int, n: int) -> dict:
    """
    Compute all association measures for a bigram.

    Args:
        c_xy: Bigram count
        c_x: First word count
        c_y: Second word count
        n: Total tokens

    Returns:
        Dict with keys: pmi, tscore, llr, dice (values can be None)
    """
    return {
        'pmi': compute_pmi(c_xy, c_x, c_y, n),
        'tscore': compute_tscore(c_xy, c_x, c_y, n),
        'llr': compute_llr(c_xy, c_x, c_y, n),
        'dice': compute_dice(c_xy, c_x, c_y),
    }


def compute_trigram_llr_approx(
    c_xyz: int,
    c_xy: int,
    c_yz: int,
    c_x: int,
    c_y: int,
    c_z: int,
    n: int
) -> Optional[float]:
    """
    Approximate LLR for trigram using pairwise minimum.

    Since exact trigram LLR requires 8-dimensional contingency table,
    we approximate using the minimum of pairwise LLRs:
        LLR(x,y,z) ≈ min(LLR(x,y), LLR(y,z))

    This gives a conservative estimate of association strength.

    Args:
        c_xyz: Trigram count
        c_xy: Count of bigram (x,y)
        c_yz: Count of bigram (y,z)
        c_x, c_y, c_z: Individual word counts
        n: Total tokens

    Returns:
        Approximate LLR score
    """
    llr_xy = compute_llr(c_xy, c_x, c_y, n)
    llr_yz = compute_llr(c_yz, c_y, c_z, n)

    if llr_xy is None or llr_yz is None:
        return None

    return min(llr_xy, llr_yz)
