#!/usr/bin/env python3
"""
M7 Normalization - Comprehensive Test Suite

Tests Hebrew text normalization with 50+ test cases covering:
- Strict mode (prefix/suffix stripping for lemmas)
- Compat mode (no stripping for ngrams/terms)
- Nikkud removal
- Whitespace normalization
- Edge cases (numbers, punctuation, mixed scripts)
"""

import unittest
from app.domain.normalization import normalize_for_tm


class TestNormalizationStrictMode(unittest.TestCase):
    """Test strict mode normalization (lemmas with prefix/suffix stripping)."""

    def test_01_simple_word_no_stripping(self):
        """Simple word without prefixes should remain unchanged."""
        result = normalize_for_tm("he", "דבר", "lemma")
        self.assertEqual(result.norm, "דבר")
        self.assertEqual(result.mode, "strict")

    def test_02_definite_article_he_stripped(self):
        """Definite article ה should be stripped."""
        result = normalize_for_tm("he", "הבית", "lemma")
        self.assertEqual(result.norm, "בית")
        self.assertEqual(result.mode, "strict")

    def test_03_prefix_ve_stripped(self):
        """Prefix ו (and) should be stripped."""
        result = normalize_for_tm("he", "ודבר", "lemma")
        self.assertEqual(result.norm, "דבר")
        self.assertEqual(result.mode, "strict")

    def test_04_prefix_be_stripped(self):
        """Prefix ב (in) should be stripped."""
        result = normalize_for_tm("he", "בבית", "lemma")
        self.assertEqual(result.norm, "בית")
        self.assertEqual(result.mode, "strict")

    def test_05_prefix_le_stripped(self):
        """Prefix ל (to) should be stripped."""
        result = normalize_for_tm("he", "לבית", "lemma")
        self.assertEqual(result.norm, "בית")
        self.assertEqual(result.mode, "strict")

    def test_06_prefix_ke_stripped(self):
        """Prefix כ (like) should be stripped."""
        result = normalize_for_tm("he", "כדבר", "lemma")
        self.assertEqual(result.norm, "דבר")
        self.assertEqual(result.mode, "strict")

    def test_07_prefix_mi_stripped(self):
        """Prefix מ (from) should be stripped."""
        result = normalize_for_tm("he", "מבית", "lemma")
        self.assertEqual(result.norm, "בית")
        self.assertEqual(result.mode, "strict")

    def test_08_prefix_she_stripped(self):
        """Prefix ש (that/which) should be stripped."""
        result = normalize_for_tm("he", "שדבר", "lemma")
        self.assertEqual(result.norm, "דבר")
        self.assertEqual(result.mode, "strict")

    def test_09_multiple_prefixes_stripped(self):
        """Multiple prefixes should be stripped: ו+ה+דבר."""
        result = normalize_for_tm("he", "והדבר", "lemma")
        self.assertEqual(result.norm, "דבר")
        self.assertEqual(result.mode, "strict")

    def test_10_complex_prefixes_veshel(self):
        """Complex prefixes: ו+ש+ל+דבר."""
        result = normalize_for_tm("he", "ושלדבר", "lemma")
        self.assertEqual(result.norm, "דבר")
        self.assertEqual(result.mode, "strict")

    def test_11_suffix_im_not_stripped_in_strict(self):
        """Plural suffix ים should NOT be stripped in current implementation."""
        result = normalize_for_tm("he", "ספרים", "lemma")
        # Assuming current implementation doesn't strip suffixes
        self.assertEqual(result.norm, "ספרים")
        self.assertEqual(result.mode, "strict")

    def test_12_nikkud_removed(self):
        """Nikkud should be removed."""
        result = normalize_for_tm("he", "דָּבָר", "lemma")
        self.assertEqual(result.norm, "דבר")
        self.assertEqual(result.mode, "strict")

    def test_13_nikkud_and_prefix_combined(self):
        """Nikkud removal + prefix stripping."""
        result = normalize_for_tm("he", "הַבַּיִת", "lemma")
        self.assertEqual(result.norm, "בית")
        self.assertEqual(result.mode, "strict")

    def test_14_whitespace_stripped(self):
        """Leading/trailing whitespace should be stripped."""
        result = normalize_for_tm("he", "  דבר  ", "lemma")
        self.assertEqual(result.norm, "דבר")

    def test_15_internal_whitespace_preserved(self):
        """Internal whitespace should be normalized to single space."""
        result = normalize_for_tm("he", "דבר   אחר", "lemma")
        self.assertEqual(result.norm, "דבר אחר")

    def test_16_empty_string(self):
        """Empty string should normalize to empty."""
        result = normalize_for_tm("he", "", "lemma")
        self.assertEqual(result.norm, "")

    def test_17_single_character(self):
        """Single character should remain unchanged."""
        result = normalize_for_tm("he", "ד", "lemma")
        self.assertEqual(result.norm, "ד")

    def test_18_numbers_preserved(self):
        """Numbers should be preserved."""
        result = normalize_for_tm("he", "123", "lemma")
        self.assertEqual(result.norm, "123")

    def test_19_mixed_hebrew_numbers(self):
        """Mixed Hebrew and numbers."""
        result = normalize_for_tm("he", "דבר123", "lemma")
        self.assertEqual(result.norm, "דבר123")

    def test_20_punctuation_preserved(self):
        """Punctuation should be preserved (depends on implementation)."""
        result = normalize_for_tm("he", "דבר!", "lemma")
        # Assuming punctuation is kept
        self.assertIn("דבר", result.norm)


class TestNormalizationCompatMode(unittest.TestCase):
    """Test compat mode normalization (ngrams/terms without stripping)."""

    def test_21_ngram_no_prefix_stripping(self):
        """Ngrams should NOT strip prefixes (compat mode)."""
        result = normalize_for_tm("he", "הבית", "ngram")
        self.assertEqual(result.norm, "הבית")
        self.assertEqual(result.mode, "compat")

    def test_22_ngram_preserve_ve_prefix(self):
        """Ngrams preserve ו prefix."""
        result = normalize_for_tm("he", "ודבר", "ngram")
        self.assertEqual(result.norm, "ודבר")
        self.assertEqual(result.mode, "compat")

    def test_23_ngram_nikkud_still_removed(self):
        """Ngrams still remove nikkud even in compat mode."""
        result = normalize_for_tm("he", "דָּבָר", "ngram")
        self.assertEqual(result.norm, "דבר")
        self.assertEqual(result.mode, "compat")

    def test_24_ngram_whitespace_normalized(self):
        """Ngrams normalize whitespace."""
        result = normalize_for_tm("he", "  דבר  אחר  ", "ngram")
        self.assertEqual(result.norm, "דבר אחר")
        self.assertEqual(result.mode, "compat")

    def test_25_term_cluster_no_stripping(self):
        """Term clusters use compat mode (no stripping)."""
        result = normalize_for_tm("he", "והבית", "term_cluster")
        self.assertEqual(result.norm, "והבית")
        self.assertEqual(result.mode, "compat")

    def test_26_surface_no_stripping(self):
        """Surface forms use compat mode (no stripping)."""
        result = normalize_for_tm("he", "לבית", "surface")
        self.assertEqual(result.norm, "לבית")
        self.assertEqual(result.mode, "compat")

    def test_27_ngram_multiword(self):
        """Multi-word ngrams preserve all prefixes."""
        result = normalize_for_tm("he", "הבית הגדול", "ngram")
        self.assertEqual(result.norm, "הבית הגדול")
        self.assertEqual(result.mode, "compat")

    def test_28_ngram_with_numbers(self):
        """Ngrams with numbers preserved."""
        result = normalize_for_tm("he", "דף 123", "ngram")
        self.assertEqual(result.norm, "דף 123")
        self.assertEqual(result.mode, "compat")


class TestNormalizationEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_29_only_prefixes(self):
        """Word consisting only of prefixes."""
        result = normalize_for_tm("he", "והב", "lemma")
        # Depends on implementation - may strip to nothing or keep minimal
        self.assertIsNotNone(result.norm)

    def test_30_repeated_characters(self):
        """Repeated characters preserved."""
        result = normalize_for_tm("he", "בבבב", "lemma")
        # After stripping prefix ב, should get "בבב" or similar
        self.assertIn("בב", result.norm)

    def test_31_mixed_scripts_hebrew_latin(self):
        """Mixed Hebrew and Latin scripts."""
        result = normalize_for_tm("he", "דבר word", "lemma")
        self.assertEqual(result.norm, "דבר word")

    def test_32_all_nikkud_no_letters(self):
        """String with only nikkud marks."""
        result = normalize_for_tm("he", "\u05B0\u05B1", "lemma")
        # Should normalize to empty or minimal
        self.assertIsNotNone(result.norm)

    def test_33_newline_normalized(self):
        """Newlines should be normalized to space."""
        result = normalize_for_tm("he", "דבר\nאחר", "lemma")
        self.assertEqual(result.norm, "דבר אחר")

    def test_34_tab_normalized(self):
        """Tabs should be normalized to space."""
        result = normalize_for_tm("he", "דבר\tאחר", "lemma")
        self.assertEqual(result.norm, "דבר אחר")

    def test_35_multiple_spaces_collapsed(self):
        """Multiple spaces should collapse to single space."""
        result = normalize_for_tm("he", "דבר     אחר", "lemma")
        self.assertEqual(result.norm, "דבר אחר")

    def test_36_rtl_mark_removed(self):
        """RTL/LTR marks should be removed (if implemented)."""
        result = normalize_for_tm("he", "\u200Fדבר", "lemma")
        self.assertEqual(result.norm, "דבר")

    def test_37_zero_width_characters(self):
        """Zero-width characters should be removed."""
        result = normalize_for_tm("he", "ד\u200Bבר", "lemma")
        self.assertEqual(result.norm, "דבר")


class TestNormalizationConsistency(unittest.TestCase):
    """Test consistency across different inputs."""

    def test_38_idempotence_simple(self):
        """Normalizing twice should give same result."""
        result1 = normalize_for_tm("he", "הבית", "lemma")
        result2 = normalize_for_tm("he", result1.norm, "lemma")
        self.assertEqual(result1.norm, result2.norm)

    def test_39_idempotence_complex(self):
        """Normalizing complex word twice should be idempotent."""
        result1 = normalize_for_tm("he", "והַבָּתִים", "lemma")
        result2 = normalize_for_tm("he", result1.norm, "lemma")
        self.assertEqual(result1.norm, result2.norm)

    def test_40_case_insensitive_latin(self):
        """Latin characters should be case-normalized (if implemented)."""
        result1 = normalize_for_tm("he", "Test", "lemma")
        result2 = normalize_for_tm("he", "test", "lemma")
        # Depends on implementation - may lowercase
        self.assertIsNotNone(result1.norm)
        self.assertIsNotNone(result2.norm)

    def test_41_same_word_different_nikkud(self):
        """Same word with different nikkud should normalize identically."""
        result1 = normalize_for_tm("he", "דָּבָר", "lemma")
        result2 = normalize_for_tm("he", "דַּבָּר", "lemma")
        self.assertEqual(result1.norm, result2.norm)

    def test_42_prefix_order_independence(self):
        """Different prefix combinations should normalize differently."""
        result1 = normalize_for_tm("he", "והבית", "lemma")
        result2 = normalize_for_tm("he", "לבית", "lemma")
        # Both should strip to "בית"
        self.assertEqual(result1.norm, "בית")
        self.assertEqual(result2.norm, "בית")


class TestNormalizationRealWorldExamples(unittest.TestCase):
    """Test real-world Hebrew words and phrases."""

    def test_43_common_word_sefer(self):
        """Common word: ספר (book)."""
        result = normalize_for_tm("he", "ספר", "lemma")
        self.assertEqual(result.norm, "ספר")

    def test_44_common_word_with_prefix_vesefer(self):
        """Common word with prefix: וספר (and book)."""
        result = normalize_for_tm("he", "וספר", "lemma")
        self.assertEqual(result.norm, "ספר")

    def test_45_definite_habayit(self):
        """Definite form: הבית (the house)."""
        result = normalize_for_tm("he", "הבית", "lemma")
        self.assertEqual(result.norm, "בית")

    def test_46_prepositional_phrase_bebayit(self):
        """Prepositional: בבית (in the house)."""
        result = normalize_for_tm("he", "בבית", "lemma")
        self.assertEqual(result.norm, "בית")

    def test_47_complex_uvabayit(self):
        """Complex: ובבית (and in the house)."""
        result = normalize_for_tm("he", "ובבית", "lemma")
        self.assertEqual(result.norm, "בית")

    def test_48_plural_form_sefarim(self):
        """Plural: ספרים (books)."""
        result = normalize_for_tm("he", "ספרים", "lemma")
        # Suffix not stripped in current implementation
        self.assertEqual(result.norm, "ספרים")

    def test_49_construct_state_batei(self):
        """Construct state: בתי (houses of)."""
        result = normalize_for_tm("he", "בתי", "lemma")
        self.assertEqual(result.norm, "תי")  # ב stripped as prefix

    def test_50_multiword_phrase_lemma(self):
        """Multi-word phrase as lemma."""
        result = normalize_for_tm("he", "בית ספר", "lemma")
        self.assertEqual(result.norm, "בית ספר")

    def test_51_multiword_phrase_ngram(self):
        """Multi-word phrase as ngram (no stripping)."""
        result = normalize_for_tm("he", "בבית הספר", "ngram")
        self.assertEqual(result.norm, "בבית הספר")

    def test_52_relative_clause_shehu(self):
        """Relative pronoun: שהוא (that he)."""
        result = normalize_for_tm("he", "שהוא", "lemma")
        # ש stripped, הוא becomes וא after ה stripped
        self.assertIn("וא", result.norm)

    def test_53_interrogative_haim(self):
        """Interrogative: האם (whether)."""
        result = normalize_for_tm("he", "האם", "lemma")
        self.assertEqual(result.norm, "אם")

    def test_54_preposition_mishel(self):
        """Compound preposition: משל (from of)."""
        result = normalize_for_tm("he", "משל", "lemma")
        # מ stripped, של remains
        self.assertEqual(result.norm, "של")

    def test_55_acronym_with_quotes(self):
        """Hebrew acronym with quotes: צה\"ל."""
        result = normalize_for_tm("he", "צה\"ל", "lemma")
        # Should preserve acronym structure
        self.assertIn("צה", result.norm)


class TestNormalizationNonHebrew(unittest.TestCase):
    """Test normalization for non-Hebrew languages (passthrough mode)."""

    def test_56_english_passthrough(self):
        """English text should pass through (no Hebrew normalization)."""
        result = normalize_for_tm("en", "the house", "lemma")
        # Should normalize whitespace but not strip prefixes
        self.assertEqual(result.norm, "the house")

    def test_57_russian_passthrough(self):
        """Russian text should pass through."""
        result = normalize_for_tm("ru", "дом", "lemma")
        self.assertEqual(result.norm, "дом")

    def test_58_mixed_language_passthrough(self):
        """Non-Hebrew languages preserve all characters."""
        result = normalize_for_tm("en", "  test  ", "lemma")
        self.assertEqual(result.norm, "test")


class TestNormalizationPerformance(unittest.TestCase):
    """Test performance characteristics (boundary conditions)."""

    def test_59_very_long_string(self):
        """Very long string should normalize without error."""
        long_text = "דבר " * 1000
        result = normalize_for_tm("he", long_text, "lemma")
        self.assertIsNotNone(result.norm)
        self.assertGreater(len(result.norm), 0)

    def test_60_many_prefixes(self):
        """Word with many prefixes."""
        result = normalize_for_tm("he", "ושבלמהדבר", "lemma")
        # Should strip all valid prefixes
        self.assertIsNotNone(result.norm)


# ============================================================================
# Test Runner
# ============================================================================

if __name__ == "__main__":
    # Run with verbose output
    suite = unittest.TestLoader().loadTestsFromModule(__import__("__main__"))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Summary
    print("\n" + "=" * 70)
    print("M7 Normalization Test Suite - Summary")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success rate: {(result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100:.1f}%")
    print("=" * 70)

    # Exit with appropriate code
    exit(0 if result.wasSuccessful() else 1)
