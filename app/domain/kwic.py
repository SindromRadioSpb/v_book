"""KWIC (Key Word In Context) formatting (M6)."""
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


def format_kwic(
    sentence: str,
    match: str,
    context_chars: int = 50,
) -> Tuple[str, str, str]:
    """
    Format a sentence as KWIC (left, match, right).

    Args:
        sentence: Full sentence text
        match: The matched keyword/phrase
        context_chars: Number of characters for left/right context

    Returns:
        Tuple of (left_context, match, right_context)
    """
    match_pos = sentence.find(match)
    if match_pos == -1:
        # Match not found, return full sentence as left context
        return (sentence, "", "")

    left_start = max(0, match_pos - context_chars)
    right_end = min(len(sentence), match_pos + len(match) + context_chars)

    left_context = sentence[left_start:match_pos]
    right_context = sentence[match_pos + len(match) : right_end]

    # Add ellipsis if truncated
    if left_start > 0:
        left_context = "..." + left_context
    if right_end < len(sentence):
        right_context = right_context + "..."

    return (left_context.strip(), match, right_context.strip())
