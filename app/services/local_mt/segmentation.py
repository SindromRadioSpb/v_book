"""Text segmentation for local MT.

Splits long texts into sentence-level segments for better translation quality.
NLLB models degrade on long inputs (>512 tokens), so we segment before translation.

Algorithm:
1. Split text by sentence boundaries (. ! ? ... \\n)
2. Preserve separators for reassembly
3. Enforce max segment length (characters and tokens)
4. Return segments + separators for reconstruction

Example:
    Input: "Hello world! This is a test. Another sentence?"
    Segments: ["Hello world!", "This is a test.", "Another sentence?"]
    Separators: ["", "", ""]
    Reassembly: segments[0] + separators[0] + segments[1] + ...
"""
import re
from dataclasses import dataclass
from typing import List, Tuple


# ============================================================================
# Constants
# ============================================================================

# Sentence boundary patterns (in priority order)
SENTENCE_BOUNDARIES = [
    r'[.!?…]+',  # Multiple punctuation marks
    r'\n+',      # Newlines
]

# Maximum segment lengths (safety limits for NLLB)
MAX_CHARS_PER_SEGMENT = 1000  # Character limit
MAX_TOKENS_PER_SEGMENT = 512  # Approximate token limit (rough estimate: 1 token ≈ 4 chars)

# Minimum segment length (avoid splitting very short segments)
MIN_CHARS_PER_SEGMENT = 10


# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class TextSegment:
    """Text segment with metadata."""

    text: str
    separator: str
    index: int
    char_count: int
    estimated_tokens: int


# ============================================================================
# Segmentation Functions
# ============================================================================


def segment_text(
    text: str,
    max_chars: int = MAX_CHARS_PER_SEGMENT,
    max_tokens: int = MAX_TOKENS_PER_SEGMENT,
    min_chars: int = MIN_CHARS_PER_SEGMENT,
) -> List[TextSegment]:
    """
    Segment text into sentence-level chunks.

    Args:
        text: Input text to segment
        max_chars: Maximum characters per segment
        max_tokens: Maximum estimated tokens per segment
        min_chars: Minimum characters per segment (avoid tiny splits)

    Returns:
        List of TextSegment objects with text and separators
    """
    if not text or not text.strip():
        return []

    # Normalize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # Split by sentence boundaries
    segments = _split_by_boundaries(text)

    # Enforce length limits
    segments = _enforce_length_limits(segments, max_chars, max_tokens)

    # Merge very short segments
    segments = _merge_short_segments(segments, min_chars)

    # Create TextSegment objects
    result = []
    for i, (segment_text, separator) in enumerate(segments):
        result.append(TextSegment(
            text=segment_text,
            separator=separator,
            index=i,
            char_count=len(segment_text),
            estimated_tokens=_estimate_token_count(segment_text),
        ))

    return result


def reassemble_text(segments: List[TextSegment], translations: List[str]) -> str:
    """
    Reassemble translated segments with original separators.

    Args:
        segments: Original segments with separators
        translations: Translated text for each segment

    Returns:
        Reassembled text

    Raises:
        ValueError: If lengths don't match
    """
    if len(segments) != len(translations):
        raise ValueError(
            f"Segment count mismatch: {len(segments)} segments, {len(translations)} translations"
        )

    if not segments:
        return ""

    # Reassemble with separators
    result = []
    for segment, translation in zip(segments, translations):
        result.append(translation)
        result.append(segment.separator)

    return ''.join(result)


# ============================================================================
# Helper Functions
# ============================================================================


def _split_by_boundaries(text: str) -> List[Tuple[str, str]]:
    """
    Split text by sentence boundaries, preserving separators.

    Args:
        text: Input text

    Returns:
        List of (segment, separator) tuples
    """
    # Pattern that captures sentence boundaries + optional trailing whitespace
    # This ensures we preserve both punctuation and spacing
    pattern = r'([.!?…]+\s*|\n+)'

    # Split while preserving separators
    parts = re.split(pattern, text)

    # Group into (text, separator) pairs
    segments = []
    i = 0
    while i < len(parts):
        segment_text = parts[i] if i < len(parts) else ''

        # Get separator (next part if it exists)
        separator = ''
        if i + 1 < len(parts):
            next_part = parts[i + 1]
            # Check if next part is a separator (matches boundary pattern)
            if next_part and re.match(r'^([.!?…]+\s*|\n+)$', next_part):
                separator = next_part
                i += 2  # Skip both segment and separator
            else:
                i += 1
        else:
            i += 1

        # Only add non-empty segments
        if segment_text and segment_text.strip():
            segments.append((segment_text.strip(), separator))

    return segments


def _enforce_length_limits(
    segments: List[Tuple[str, str]],
    max_chars: int,
    max_tokens: int,
) -> List[Tuple[str, str]]:
    """
    Split segments that exceed length limits.

    Args:
        segments: List of (text, separator) tuples
        max_chars: Maximum characters per segment
        max_tokens: Maximum estimated tokens per segment

    Returns:
        List of (text, separator) tuples with enforced limits
    """
    result = []

    for segment_text, separator in segments:
        # Check if segment exceeds limits
        char_count = len(segment_text)
        token_count = _estimate_token_count(segment_text)

        if char_count <= max_chars and token_count <= max_tokens:
            # Segment is fine
            result.append((segment_text, separator))
        else:
            # Split long segment by whitespace
            words = segment_text.split()
            current_chunk = []
            current_chars = 0

            for word in words:
                word_chars = len(word) + 1  # +1 for space

                if current_chars + word_chars > max_chars:
                    # Flush current chunk
                    if current_chunk:
                        chunk_text = ' '.join(current_chunk)
                        result.append((chunk_text, ''))
                        current_chunk = [word]
                        current_chars = len(word)
                else:
                    current_chunk.append(word)
                    current_chars += word_chars

            # Add remaining chunk with original separator
            if current_chunk:
                chunk_text = ' '.join(current_chunk)
                result.append((chunk_text, separator))

    return result


def _merge_short_segments(
    segments: List[Tuple[str, str]],
    min_chars: int,
) -> List[Tuple[str, str]]:
    """
    Merge very short segments with neighbors.

    Args:
        segments: List of (text, separator) tuples
        min_chars: Minimum characters per segment

    Returns:
        List of (text, separator) tuples with merged short segments
    """
    if not segments:
        return []

    result = []
    i = 0

    while i < len(segments):
        segment_text, separator = segments[i]

        # Check if segment is too short
        if len(segment_text) < min_chars and i + 1 < len(segments):
            # Merge with next segment
            next_text, next_sep = segments[i + 1]
            merged_text = segment_text + separator + next_text
            result.append((merged_text, next_sep))
            i += 2
        else:
            result.append((segment_text, separator))
            i += 1

    return result


def _estimate_token_count(text: str) -> int:
    """
    Estimate token count for text.

    Uses rough approximation: 1 token ≈ 4 characters for most languages.
    This is conservative (actual token count may be lower).

    Args:
        text: Input text

    Returns:
        Estimated token count
    """
    # Rough estimate: 1 token ≈ 4 characters
    # This is conservative for most languages (actual ratio varies)
    return len(text) // 4
