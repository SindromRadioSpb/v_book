"""V01v2 — Sentence splitting borderline cases and known-limitation contracts (C01v2).

Extends C01 with:
  - Hebrew abbreviation: 'פרופ.' — abbreviation detection fix verified
  - Decimal number: '2.1' — period inside number must not split (regex by design)
  - Latin abbreviation: 'Inc.' — KNOWN LIMITATION: splits (not in ABBREVIATIONS set)
  - Ellipsis: '...' — KNOWN LIMITATION: splits (treated as sentence boundary)
  - Parenthetical punct: '("שלום!")' — must NOT split (punct not followed by whitespace)
  - Empty string '' — must return []
  - Long paragraph: 10 sentences — all correctly split

Abbreviation fix note (C01v2_01):
  Bug: _is_abbreviation(" ".join(current)) was called after punct was appended,
  so 'פרופ .' was checked against 'פרופ' — failed. Fix: check text_part directly.

Known limitations are documented as contracts (not failures). They pin the actual
behavior so regressions from these known states are detectable.

No Stanza required — pure rule-based splitter.
"""

from __future__ import annotations

import pytest

from app.domain.sentence_splitter import SentenceSplitter
from tests.validation.oracles.oracle_sentence import validate_sentence_splitting


@pytest.fixture
def cases(gold_data):
    return gold_data("c01v2_sentence_splitting")["cases"]


# ---------------------------------------------------------------------------
# Borderline cases — bulk + individual pins
# ---------------------------------------------------------------------------


class TestBorderlineSentenceSplitting:
    def test_all_borderline_cases_pass(self, cases):
        """All C01v2 gold cases must match actual splitter output."""
        failures = []
        for case in cases:
            result = validate_sentence_splitting(case)
            if not result.match:
                failures.append(
                    {
                        "case_id": result.case_id,
                        "expected": result.expected,
                        "actual": result.actual,
                        "missing": result.missing,
                        "extra": result.extra,
                    }
                )
        assert not failures, f"Sentence splitting borderline failures:\n{failures}"

    def test_hebrew_abbreviation_not_split(self, cases):
        """C01v2_01: 'פרופ.' — Hebrew abbreviation must not cause a split."""
        c = next(c for c in cases if c["case_id"] == "C01v2_01")
        result = validate_sentence_splitting(c)
        assert result.actual == [
            "פרופ . כהן ביקר את המוסד ."
        ], f"Expected 1 sentence, got: {result.actual}"

    def test_decimal_not_split(self, cases):
        """C01v2_02: '2.1' — decimal period must not split (no whitespace follows)."""
        c = next(c for c in cases if c["case_id"] == "C01v2_02")
        result = validate_sentence_splitting(c)
        assert len(result.actual) == 1, (
            f"Decimal '2.1' must not cause a split — got {len(result.actual)} sentences: "
            f"{result.actual}"
        )

    def test_latin_abbreviation_splits_known_limitation(self, cases):
        """C01v2_03: 'Inc.' splits — KNOWN LIMITATION, Latin abbreviations not supported.

        Documents actual behavior. If the splitter is enhanced to handle Latin
        abbreviations, this test must be updated to reflect the new contract.
        """
        c = next(c for c in cases if c["case_id"] == "C01v2_03")
        result = validate_sentence_splitting(c)
        assert result.actual == [
            "Google Inc .",
            "הוא חברה .",
        ], (
            "Known limitation: Latin abbreviation 'Inc.' causes a split. "
            f"Actual: {result.actual}"
        )

    def test_ellipsis_splits_known_limitation(self, cases):
        """C01v2_04: '...' splits — KNOWN LIMITATION, ellipsis treated as sentence boundary.

        Documents actual behavior. If an ellipsis exception is added to the splitter,
        this test must be updated to reflect the new contract.
        """
        c = next(c for c in cases if c["case_id"] == "C01v2_04")
        result = validate_sentence_splitting(c)
        assert result.actual == [
            "הוא חיכה ...",
            "ואז הלך .",
        ], (
            "Known limitation: '...' followed by space causes a split. " f"Actual: {result.actual}"
        )

    def test_parenthetical_exclamation_not_split(self, cases):
        """C01v2_05: '!' inside parens must NOT split (not followed by whitespace)."""
        c = next(c for c in cases if c["case_id"] == "C01v2_05")
        result = validate_sentence_splitting(c)
        assert len(result.actual) == 1, (
            f"'!' inside parens must not split — got {len(result.actual)} sentences: "
            f"{result.actual}"
        )

    def test_empty_string_returns_empty_list(self, cases):
        """C01v2_06: empty string '' must return []."""
        c = next(c for c in cases if c["case_id"] == "C01v2_06")
        result = validate_sentence_splitting(c)
        assert result.actual == [], f"Empty string must produce [], got: {result.actual}"

    def test_long_paragraph_count(self, cases):
        """C01v2_07: 10-sentence paragraph must produce exactly 10 sentences."""
        c = next(c for c in cases if c["case_id"] == "C01v2_07")
        result = validate_sentence_splitting(c)
        assert len(result.actual) == 10, (
            f"Long paragraph must produce 10 sentences, got {len(result.actual)}: "
            f"{result.actual}"
        )
        assert (
            result.match
        ), f"Long paragraph sentences do not match gold: {result.missing=} {result.extra=}"


# ---------------------------------------------------------------------------
# Abbreviation fix contract
# ---------------------------------------------------------------------------


class TestAbbreviationFixContract:
    def test_abbreviation_check_uses_word_before_punct(self):
        """_is_abbreviation() must be called with the word, not word+space+punct.

        Pre-fix: _is_abbreviation('פרופ .') was called — 'פרופ .' does NOT end with
        'פרופ', so the abbreviation went undetected and a split was produced.
        Post-fix: _is_abbreviation('פרופ') is called — correctly returns True.

        This test pins the fix contract so it cannot silently regress.
        """
        splitter = SentenceSplitter()
        result = splitter.split("פרופ. כהן ביקר.")
        assert len(result) == 1, (
            f"'פרופ.' must not split — abbreviation check bug would produce 2 sentences. "
            f"Got: {result}"
        )

    def test_dr_abbreviation_not_split(self):
        """'ד\"ר' (Doctor) abbreviation must not cause a split."""
        splitter = SentenceSplitter()
        result = splitter.split('ד"ר. כהן בדק את המטופל.')
        assert (
            len(result) == 1
        ), f"'ד\"ר.' must not split — 'ד\"ר' is in ABBREVIATIONS set. Got: {result}"

    def test_non_abbreviation_still_splits(self):
        """A word that is NOT an abbreviation must still split on terminal period.

        Regression guard: the fix must not suppress splits for normal words.
        """
        splitter = SentenceSplitter()
        result = splitter.split("ירושלים היא עיר. תל אביב היא עיר.")
        assert (
            len(result) == 2
        ), f"Normal sentences must still split on '.'. Got {len(result)}: {result}"
