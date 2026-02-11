"""Entity classification for lemmas and term clusters.

Classifies text strings into entity types (WORD_HE, WORD_LATIN, NUMBER, MATH_EXPR, etc.)
and determines noise status with explainable reason codes.

Pure Python implementation (no external dependencies beyond stdlib).
Performance target: < 1ms per classification.
"""

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class EntityClass(str, Enum):
    """Entity classification types."""

    WORD_HE = "WORD_HE"  # Pure Hebrew letters
    WORD_LATIN = "WORD_LATIN"  # Pure Latin letters
    MIXED_ALPHA_NUM = "MIXED_ALPHA_NUM"  # Letters + digits mixed
    NUMBER = "NUMBER"  # Pure numeric
    QUANTITY_UNIT = "QUANTITY_UNIT"  # Number + unit word
    MATH_EXPR = "MATH_EXPR"  # Math operators/Greek/superscripts
    SYMBOL = "SYMBOL"  # Symbol characters
    PUNCT = "PUNCT"  # Punctuation only
    OTHER = "OTHER"  # Unclassified


class NoiseReason(str, Enum):
    """Noise reason codes (why something is classified as noise)."""

    NOISE_PUNCT_ONLY = "NOISE_PUNCT_ONLY"
    NOISE_SYMBOL_ONLY = "NOISE_SYMBOL_ONLY"
    NOISE_NUMERIC_ONLY = "NOISE_NUMERIC_ONLY"
    NOISE_MATH_EXPR = "NOISE_MATH_EXPR"
    NOISE_MIXED_GARBAGE = "NOISE_MIXED_GARBAGE"
    NOISE_TOO_SHORT = "NOISE_TOO_SHORT"
    NOISE_RATIO_NON_LETTER_HIGH = "NOISE_RATIO_NON_LETTER_HIGH"
    NOISE_LEADING_TRAILING_PUNCT_HEAVY = "NOISE_LEADING_TRAILING_PUNCT_HEAVY"


@dataclass(frozen=True)
class ClassificationResult:
    """Result of text classification."""

    entity_class: str  # EntityClass value
    is_noise: bool
    noise_reason: Optional[str]  # NoiseReason value or None
    norm_text: str  # Normalized text


# Unicode ranges
HEBREW_RANGE = (0x0590, 0x05FF)  # Hebrew block (includes geresh, gershayim, maqaf)
GREEK_RANGE = (0x0370, 0x03FF)  # Greek and Coptic

# Hebrew-specific markers (part of Hebrew words, not punctuation)
HEBREW_GERESH = "\u05F3"  # '
HEBREW_GERSHAYIM = "\u05F4"  # "
HEBREW_MAQAF = "\u05BE"  # -

# Math/symbol characters
MATH_OPERATORS = set("+-*/=<>≤≥±∓×÷∑∫∂∇Δ∆√∞≈≠")
SUPERSCRIPT_CHARS = set("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
SUBSCRIPT_CHARS = set("₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")
SPECIAL_SYMBOLS = set("°·•†‡§¶©®™€£¥")


def normalize_text(raw: str) -> str:
    """Normalize text for classification.

    - NFKC Unicode normalization
    - Unify dashes (em-dash, en-dash, minus → ASCII hyphen)
    - Unify quotes (curly quotes → ASCII quotes)
    - Strip leading/trailing whitespace
    - Collapse multiple whitespace to single space

    Args:
        raw: Raw text string

    Returns:
        Normalized text
    """
    if not raw:
        return ""

    # NFKC normalization (compatibility decomposition + canonical composition)
    text = unicodedata.normalize("NFKC", raw)

    # Unify dashes
    text = text.replace("\u2014", "-")  # em dash
    text = text.replace("\u2013", "-")  # en dash
    text = text.replace("\u2212", "-")  # minus sign
    text = text.replace("\u2010", "-")  # hyphen
    text = text.replace("\u2011", "-")  # non-breaking hyphen

    # Unify quotes
    text = text.replace("\u2018", "'")  # left single quote
    text = text.replace("\u2019", "'")  # right single quote
    text = text.replace("\u201C", '"')  # left double quote
    text = text.replace("\u201D", '"')  # right double quote

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)

    # Strip
    text = text.strip()

    return text


def _is_hebrew_char(char: str) -> bool:
    """Check if character is Hebrew (0590-05FF)."""
    if not char:
        return False
    code = ord(char)
    return HEBREW_RANGE[0] <= code <= HEBREW_RANGE[1]


def _is_greek_char(char: str) -> bool:
    """Check if character is Greek (0370-03FF)."""
    if not char:
        return False
    code = ord(char)
    return GREEK_RANGE[0] <= code <= GREEK_RANGE[1]


def _compute_char_ratios(text: str) -> dict:
    """Compute character-class ratios for classification.

    Returns:
        Dict with keys: he_ratio, latin_ratio, digit_ratio, punct_ratio, symbol_ratio, total
    """
    if not text:
        return {
            "he_ratio": 0.0,
            "latin_ratio": 0.0,
            "digit_ratio": 0.0,
            "punct_ratio": 0.0,
            "symbol_ratio": 0.0,
            "total": 0,
        }

    total = len(text)
    he_count = sum(1 for c in text if _is_hebrew_char(c))
    latin_count = sum(1 for c in text if c.isascii() and c.isalpha())
    digit_count = sum(1 for c in text if c.isdigit())

    # Punctuation: unicode category starts with 'P'
    punct_count = sum(1 for c in text if unicodedata.category(c).startswith("P"))

    # Symbols: math operators, Greek letters, special symbols, super/subscripts
    symbol_count = sum(
        1
        for c in text
        if (
            c in MATH_OPERATORS
            or c in SUPERSCRIPT_CHARS
            or c in SUBSCRIPT_CHARS
            or c in SPECIAL_SYMBOLS
            or _is_greek_char(c)
        )
    )

    return {
        "he_ratio": he_count / total,
        "latin_ratio": latin_count / total,
        "digit_ratio": digit_count / total,
        "punct_ratio": punct_count / total,
        "symbol_ratio": symbol_count / total,
        "total": total,
    }


def _is_pure_punctuation(text: str, ratios: dict) -> bool:
    """Check if text is only punctuation."""
    return ratios["punct_ratio"] >= 0.99


def _is_pure_number(text: str, ratios: dict) -> bool:
    """Check if text is a pure number (int, decimal, fraction)."""
    if ratios["digit_ratio"] < 0.5:
        return False

    # Remove digits, decimal separators, fraction slash, minus/plus
    stripped = re.sub(r"[0-9.,/\-+]", "", text)
    # If nothing left (or only whitespace), it's a number
    return len(stripped.strip()) == 0


def _is_math_expr(text: str, ratios: dict) -> bool:
    """Check if text contains math expression patterns."""
    # Greek letters - but single Greek letter is SYMBOL, not MATH_EXPR
    if any(_is_greek_char(c) for c in text):
        if len(text) == 1:
            return False  # Single Greek letter -> SYMBOL
        return True

    # Math operators (not just single minus/plus which could be number)
    if any(c in MATH_OPERATORS for c in text if c not in "+-"):
        return True

    # Superscripts or subscripts
    if any(c in SUPERSCRIPT_CHARS or c in SUBSCRIPT_CHARS for c in text):
        return True

    # Degree symbol, multiplication dot, caret, underscore (subscript notation)
    # But exclude underscore if text starts with digit (e.g., "0.5_m" is MIXED_ALPHA_NUM, not MATH_EXPR)
    if any(c in "°·^" for c in text):
        return True

    if "_" in text and not text[0].isdigit():
        return True

    return False


def _is_single_symbol(text: str, ratios: dict) -> bool:
    """Check if text is a single symbol character (len <= 2)."""
    if len(text) > 2:
        return False

    # High symbol ratio and not a letter/digit
    if ratios["symbol_ratio"] > 0.5:
        return True

    # Single special character (including dash, which may come from en dash normalization)
    if len(text) == 1 and (text in SPECIAL_SYMBOLS or text == "-"):
        return True

    return False


def _is_quantity_unit(text: str, ratios: dict) -> bool:
    """Check if text is number + unit word pattern."""
    # Pattern: starts with number, ends with Hebrew/Latin word
    # Examples: "1.2kg", "10kN", "0.6 מטר"

    # Must have both digits and letters
    if ratios["digit_ratio"] < 0.1 or (ratios["he_ratio"] + ratios["latin_ratio"]) < 0.1:
        return False

    # Try to match pattern: optional sign, digits, optional decimal, optional space, letters
    match = re.match(r"^[+-]?\d+\.?\d*\s*[a-zA-Z\u0590-\u05FF]+$", text)
    return match is not None


def _is_pure_hebrew(text: str, ratios: dict) -> bool:
    """Check if text is pure Hebrew (including geresh, gershayim, maqaf)."""
    if ratios["he_ratio"] < 0.85:
        return False

    # Allow Hebrew letters + Hebrew-specific markers
    allowed = set(text)
    for c in allowed:
        if not (_is_hebrew_char(c) or c in " \t" or c == HEBREW_GERESH or c == HEBREW_GERSHAYIM or c == HEBREW_MAQAF):
            # Check if it's actually a Hebrew letter
            if _is_hebrew_char(c):
                continue
            return False

    return True


def _is_pure_latin(text: str, ratios: dict) -> bool:
    """Check if text is pure Latin letters."""
    if ratios["latin_ratio"] < 0.9:
        return False

    # All characters should be Latin letters or whitespace
    return all(c.isascii() and (c.isalpha() or c.isspace()) for c in text)


def _is_mixed_alpha_num(text: str, ratios: dict) -> bool:
    """Check if text is mixed letters + digits (not cleanly separated)."""
    # Both letters and digits present
    has_letters = (ratios["he_ratio"] + ratios["latin_ratio"]) >= 0.1
    has_digits = ratios["digit_ratio"] >= 0.1

    return has_letters and has_digits


def _leading_trailing_punct_heavy(text: str) -> bool:
    """Check if text starts or ends with 2+ punctuation chars."""
    if len(text) < 2:
        return False

    # Count leading punct
    leading_punct = 0
    for c in text:
        if unicodedata.category(c).startswith("P"):
            leading_punct += 1
        else:
            break

    # Count trailing punct
    trailing_punct = 0
    for c in reversed(text):
        if unicodedata.category(c).startswith("P"):
            trailing_punct += 1
        else:
            break

    return leading_punct >= 2 or trailing_punct >= 2


def classify_text(raw: str) -> ClassificationResult:
    """Classify a single lemma string.

    Args:
        raw: Raw lemma text

    Returns:
        ClassificationResult with entity_class, is_noise, noise_reason, norm_text
    """
    norm = normalize_text(raw)

    # Empty -> PUNCT
    if not norm:
        return ClassificationResult(
            entity_class=EntityClass.PUNCT,
            is_noise=True,
            noise_reason=NoiseReason.NOISE_PUNCT_ONLY,
            norm_text=norm,
        )

    # Compute character ratios
    ratios = _compute_char_ratios(norm)

    # Decision tree
    entity_class = None

    # 1. Single symbol (check before pure punctuation to catch single dashes)
    if _is_single_symbol(norm, ratios):
        entity_class = EntityClass.SYMBOL

    # 2. Pure punctuation
    elif _is_pure_punctuation(norm, ratios):
        entity_class = EntityClass.PUNCT

    # 3. Pure number
    elif _is_pure_number(norm, ratios):
        entity_class = EntityClass.NUMBER

    # 4. Math expression (Greek, operators, super/subscripts)
    elif _is_math_expr(norm, ratios):
        entity_class = EntityClass.MATH_EXPR

    # 5. Quantity + unit
    elif _is_quantity_unit(norm, ratios):
        entity_class = EntityClass.QUANTITY_UNIT

    # 6. Pure Hebrew
    elif _is_pure_hebrew(norm, ratios):
        entity_class = EntityClass.WORD_HE

    # 7. Pure Latin
    elif _is_pure_latin(norm, ratios):
        entity_class = EntityClass.WORD_LATIN

    # 8. Mixed alpha-num
    elif _is_mixed_alpha_num(norm, ratios):
        entity_class = EntityClass.MIXED_ALPHA_NUM

    # 9. Other
    else:
        entity_class = EntityClass.OTHER

    # Apply noise mapping
    is_noise = False
    noise_reason = None

    if entity_class == EntityClass.PUNCT:
        is_noise = True
        noise_reason = NoiseReason.NOISE_PUNCT_ONLY
    elif entity_class == EntityClass.SYMBOL:
        is_noise = True
        noise_reason = NoiseReason.NOISE_SYMBOL_ONLY
    elif entity_class in (EntityClass.NUMBER, EntityClass.QUANTITY_UNIT):
        is_noise = True
        noise_reason = NoiseReason.NOISE_NUMERIC_ONLY
    elif entity_class == EntityClass.MATH_EXPR:
        is_noise = True
        noise_reason = NoiseReason.NOISE_MATH_EXPR
    elif entity_class in (EntityClass.MIXED_ALPHA_NUM, EntityClass.OTHER):
        is_noise = True
        noise_reason = NoiseReason.NOISE_MIXED_GARBAGE

    # Additional heuristics
    if len(norm.strip()) <= 1 and entity_class not in (EntityClass.WORD_HE, EntityClass.WORD_LATIN):
        noise_reason = NoiseReason.NOISE_TOO_SHORT
        is_noise = True

    if _leading_trailing_punct_heavy(norm):
        noise_reason = NoiseReason.NOISE_LEADING_TRAILING_PUNCT_HEAVY
        is_noise = True

    # Ratio check: high non-letter content
    non_letter_ratio = ratios["punct_ratio"] + ratios["symbol_ratio"] + ratios["digit_ratio"]
    if len(norm) > 2 and non_letter_ratio > 0.6:
        noise_reason = NoiseReason.NOISE_RATIO_NON_LETTER_HIGH
        is_noise = True

    return ClassificationResult(
        entity_class=entity_class,
        is_noise=is_noise,
        noise_reason=noise_reason,
        norm_text=norm,
    )


def classify_phrase(raw: str) -> ClassificationResult:
    """Classify a multi-token phrase (term_cluster representative_he).

    Args:
        raw: Raw phrase text

    Returns:
        ClassificationResult for the phrase as a whole
    """
    norm = normalize_text(raw)

    if not norm:
        return ClassificationResult(
            entity_class=EntityClass.PUNCT,
            is_noise=True,
            noise_reason=NoiseReason.NOISE_PUNCT_ONLY,
            norm_text=norm,
        )

    # Split on whitespace
    tokens = norm.split()

    if len(tokens) == 1:
        # Single token -> classify as text
        return classify_text(raw)

    # Classify each token
    token_results = [classify_text(tok) for tok in tokens]

    # Count noise tokens
    noise_count = sum(1 for res in token_results if res.is_noise)

    # Special case: First token is NUMBER, rest are WORD_HE -> QUANTITY_UNIT phrase
    if (
        len(token_results) >= 2
        and token_results[0].entity_class == EntityClass.NUMBER
        and all(res.entity_class == EntityClass.WORD_HE for res in token_results[1:])
    ):
        return ClassificationResult(
            entity_class=EntityClass.QUANTITY_UNIT,
            is_noise=True,
            noise_reason=NoiseReason.NOISE_NUMERIC_ONLY,
            norm_text=norm,
        )

    # Aggregate: if majority tokens are noise -> phrase is noise
    if noise_count / len(tokens) >= 0.5:
        # Find dominant noise reason
        noise_reasons = [res.noise_reason for res in token_results if res.is_noise and res.noise_reason]
        if noise_reasons:
            # Most frequent reason
            dominant_reason = max(set(noise_reasons), key=noise_reasons.count)
        else:
            dominant_reason = NoiseReason.NOISE_MIXED_GARBAGE

        # Dominant entity class
        entity_classes = [res.entity_class for res in token_results]
        dominant_class = max(set(entity_classes), key=entity_classes.count)

        return ClassificationResult(
            entity_class=dominant_class,
            is_noise=True,
            noise_reason=dominant_reason,
            norm_text=norm,
        )

    # Non-noise phrase: use first token's class (or dominant)
    entity_classes = [res.entity_class for res in token_results]
    dominant_class = max(set(entity_classes), key=entity_classes.count)

    return ClassificationResult(
        entity_class=dominant_class,
        is_noise=False,
        noise_reason=None,
        norm_text=norm,
    )
