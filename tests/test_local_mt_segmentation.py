"""Tests for text segmentation (PATCH-04).

Tests verify:
- Sentence boundary detection
- Separator preservation
- Length limit enforcement
- Short segment merging
- Reassembly correctness
"""
import pytest

from app.services.local_mt.segmentation import (
    segment_text,
    reassemble_text,
    TextSegment,
)


# ============================================================================
# Test 1: Basic segmentation
# ============================================================================


def test_segment_simple_sentences():
    """Segment simple sentences correctly."""
    text = "Hello world. This is a test. Another sentence."

    segments = segment_text(text)

    assert len(segments) == 3
    assert segments[0].text.strip() == "Hello world"
    assert segments[1].text.strip() == "This is a test"
    assert segments[2].text.strip() == "Another sentence"


def test_segment_preserves_separators():
    """Separators are preserved for reassembly."""
    text = "First sentence. Second sentence! Third sentence?"

    segments = segment_text(text)

    assert segments[0].separator == ". "
    assert segments[1].separator == "! "
    assert segments[2].separator == "?"


def test_segment_empty_text():
    """Empty text returns empty list."""
    segments = segment_text("")
    assert segments == []

    segments = segment_text("   ")
    assert segments == []


# ============================================================================
# Test 2: Different separators
# ============================================================================


def test_segment_question_marks():
    """Question marks are boundary markers."""
    text = "What is this? Another question? Final one?"

    segments = segment_text(text)

    assert len(segments) == 3
    assert "What is this" in segments[0].text
    assert "Another question" in segments[1].text
    assert "Final one" in segments[2].text


def test_segment_exclamation_marks():
    """Exclamation marks are boundary markers."""
    text = "Hello! How are you! Great!"

    segments = segment_text(text)

    # "Hello!" and "How are you!" are merged, then "Great!"
    assert len(segments) >= 2  # May merge short segments


def test_segment_ellipsis():
    """Ellipsis (…) is a boundary marker."""
    text = "Wait… What is this… Amazing…"

    segments = segment_text(text)

    # Ellipsis works as boundary
    assert len(segments) >= 2  # May merge short segments


def test_segment_newlines():
    """Newlines are boundary markers."""
    text = "First line\nSecond line\nThird line"

    segments = segment_text(text)

    assert len(segments) == 3
    assert "First line" in segments[0].text
    assert "Second line" in segments[1].text
    assert "Third line" in segments[2].text


# ============================================================================
# Test 3: Length limits
# ============================================================================


def test_segment_enforces_max_chars():
    """Long segments are split at max_chars limit."""
    # Create a very long sentence (1200 chars)
    long_text = "word " * 240  # 1200 characters

    segments = segment_text(long_text, max_chars=500)

    # Should be split into multiple segments
    assert len(segments) > 1
    for segment in segments:
        assert segment.char_count <= 500


def test_segment_respects_custom_limits():
    """Custom length limits are respected."""
    text = "This is a moderately long sentence that might need splitting."

    segments = segment_text(text, max_chars=30, max_tokens=10)

    # Should be split due to length limit
    for segment in segments:
        assert segment.char_count <= 30


# ============================================================================
# Test 4: Short segment merging
# ============================================================================


def test_segment_merges_short_segments():
    """Very short segments are merged with neighbors."""
    text = "A. B. C. D."

    segments = segment_text(text, min_chars=5)

    # Short segments should be merged
    assert len(segments) < 4


def test_segment_respects_min_chars():
    """Segments respect minimum character threshold."""
    text = "Short. Longer sentence here."

    segments = segment_text(text, min_chars=10)

    for segment in segments:
        # Either meets minimum or is the last segment
        assert segment.char_count >= 10 or segment.index == len(segments) - 1


# ============================================================================
# Test 5: Reassembly
# ============================================================================


def test_reassemble_simple():
    """Reassemble simple segments correctly."""
    text = "First sentence. Second sentence. Third sentence."

    segments = segment_text(text)
    translations = [seg.text for seg in segments]  # Identity translation

    result = reassemble_text(segments, translations)

    # Should match original (modulo whitespace normalization)
    assert "First sentence" in result
    assert "Second sentence" in result
    assert "Third sentence" in result


def test_reassemble_with_translations():
    """Reassemble with actual translations."""
    text = "Hello world this is long enough. Another sentence that is also long enough."

    segments = segment_text(text, min_chars=10)
    translations = ["Shalom olam ze maspik aroch", "Mishpat acher she gam hu aroch maspik"]  # Hebrew translations

    result = reassemble_text(segments, translations)

    assert "Shalom" in result
    assert "Mishpat" in result
    assert ". " in result  # Separator preserved


def test_reassemble_preserves_structure():
    """Reassembly preserves original structure."""
    text = "First line here\nSecond line here\nThird line here"

    segments = segment_text(text, min_chars=10)

    # Create translations matching actual segment count
    translations = [seg.text.replace("line", "línea") for seg in segments]

    result = reassemble_text(segments, translations)

    # Newlines should be preserved
    assert "línea" in result
    assert result.count('\n') >= 1  # At least one newline preserved


def test_reassemble_length_mismatch():
    """Reassemble raises error on length mismatch."""
    text = "First sentence is long enough. Second sentence is also long enough."

    segments = segment_text(text, min_chars=10)
    translations = ["Only one translation"]  # Wrong count (should be 2)

    with pytest.raises(ValueError, match="mismatch"):
        reassemble_text(segments, translations)


# ============================================================================
# Test 6: Edge cases
# ============================================================================


def test_segment_only_punctuation():
    """Text with only punctuation is handled."""
    text = "... !!! ???"

    segments = segment_text(text)

    # Should handle gracefully (may be empty or minimal segments)
    assert isinstance(segments, list)


def test_segment_mixed_boundaries():
    """Mixed boundary markers work correctly."""
    text = "First sentence here. Second sentence!\nThird sentence… Fourth sentence?"

    segments = segment_text(text, min_chars=10)

    assert len(segments) == 4


def test_segment_no_boundaries():
    """Text without boundaries is kept as single segment."""
    text = "This is a single long sentence without any boundaries"

    segments = segment_text(text)

    assert len(segments) == 1
    assert segments[0].text == text


# ============================================================================
# Test 7: Metadata
# ============================================================================


def test_segment_includes_metadata():
    """Segments include correct metadata."""
    text = "Short sentence. Longer sentence here."

    segments = segment_text(text)

    for i, segment in enumerate(segments):
        assert segment.index == i
        assert segment.char_count == len(segment.text)
        assert segment.estimated_tokens > 0


def test_segment_token_estimation():
    """Token estimation is reasonable."""
    text = "This is a test sentence."

    segments = segment_text(text)

    # Rough check: 1 token ≈ 4 chars, so 24 chars ≈ 6 tokens
    assert segments[0].estimated_tokens > 0
    assert segments[0].estimated_tokens < segments[0].char_count  # Should be less than char count


# ============================================================================
# Test 8: Hebrew text
# ============================================================================


def test_segment_hebrew_text():
    """Hebrew text segments correctly."""
    text = "שלום עולם זה משפט ראשון. זה טסט של טקסט עברי. עוד משפט נוסף כאן."

    segments = segment_text(text, min_chars=10)

    assert len(segments) == 3
    assert "שלום" in segments[0].text
    assert "טסט" in segments[1].text
    assert "עוד" in segments[2].text


# ============================================================================
# Test 9: Roundtrip test
# ============================================================================


def test_roundtrip_identity():
    """Roundtrip with identity translation preserves text."""
    text = "First sentence. Second sentence! Third sentence?"

    # Segment
    segments = segment_text(text)

    # Identity translation
    translations = [seg.text for seg in segments]

    # Reassemble
    result = reassemble_text(segments, translations)

    # Should be very close to original (may differ in whitespace)
    assert "First sentence" in result
    assert "Second sentence" in result
    assert "Third sentence" in result
    assert result.count('.') == 1
    assert result.count('!') == 1
    assert result.count('?') == 1
