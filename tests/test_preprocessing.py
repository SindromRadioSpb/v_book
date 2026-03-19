"""Test preprocessing (M3)."""

import pytest
from app.domain.preprocessing import preprocess_text
from app.domain.hebrew_utils import strip_nikud, is_hebrew_text


def test_strip_nikud():
    """Test nikud removal."""
    # Hebrew with nikud
    text_with_nikud = "שָׁלוֹם"
    expected = "שלום"
    assert strip_nikud(text_with_nikud) == expected


def test_is_hebrew_text():
    """Test Hebrew text detection."""
    assert is_hebrew_text("שלום") is True
    assert is_hebrew_text("Hello") is False
    assert is_hebrew_text("שלום World") is True


def test_preprocess_text():
    """Test full preprocessing pipeline."""
    text = "שָׁלוֹם  עוֹלָם"
    result = preprocess_text(text)
    # Should strip nikud and normalize whitespace
    assert "שלום עולם" in result or result == "שלום עולם"
