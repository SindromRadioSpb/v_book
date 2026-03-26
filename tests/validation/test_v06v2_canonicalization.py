"""V06v2 — Canonicalization edge cases: prefix matrix, multi-token nikud,
mixed Hebrew/Latin, geresh, and collision contracts (C06v2).

Extends C06 with:
  - Prefix כ: strips correctly (3-char guard verified for כ)
  - Prefix ש: strips when ≥4 chars (3-char guard verified for ש)
  - Multi-token nikud: all tokens stripped before tokenizing
  - Mixed Hebrew/Latin: Latin preserved, lowercased
  - Geresh ׳ (U+05F3): converted to ASCII ' by normalize_quotes, then stripped
  - Collision: 'מות' and 'כמות' produce identical canonical 'מות' (known limitation)

No implementation changes — all gaps were gold/test coverage gaps.
No Stanza required.
"""

from __future__ import annotations

import pytest

from app.domain.term_extraction.canonicalizer import HEBREW_PREFIXES, canonicalize_hebrew_term
from tests.validation.oracles.oracle_canonicalization import validate_canonicalization


@pytest.fixture
def cases(gold_data):
    return gold_data("c06v2_canonicalization")["canonicalize_cases"]


# ---------------------------------------------------------------------------
# Prefix matrix — כ and ש
# ---------------------------------------------------------------------------


class TestPrefixMatrix:
    def test_all_prefix_cases_pass(self, cases):
        """All C06v2 prefix matrix cases must match gold."""
        prefix_ids = {"C06v2_01", "C06v2_02", "C06v2_03", "C06v2_04"}
        failures = []
        for case in cases:
            if case["case_id"] not in prefix_ids:
                continue
            result = validate_canonicalization(case)
            if not result.match:
                failures.append(
                    {
                        "case_id": result.case_id,
                        "expected": result.expected,
                        "actual": result.actual,
                    }
                )
        assert not failures, f"Prefix matrix failures:\n{failures}"

    def test_prefix_kaf_strips_at_four_chars(self, cases):
        """C06v2_01: 'כחוק' — prefix כ strips when len-1 ≥ 3 → 'חוק'."""
        c = next(c for c in cases if c["case_id"] == "C06v2_01")
        result = validate_canonicalization(c)
        assert result.actual == "חוק", (
            f"'כחוק' must produce 'חוק' — כ in HEBREW_PREFIXES, len-1=3 ≥ 3. "
            f"Got: '{result.actual}'"
        )

    def test_prefix_kaf_guard_prevents_short_result(self, cases):
        """C06v2_02: 'כלי' — prefix כ NOT stripped (would leave 'לי' = 2 chars < 3)."""
        c = next(c for c in cases if c["case_id"] == "C06v2_02")
        result = validate_canonicalization(c)
        assert (
            result.actual == "כלי"
        ), f"'כלי' must remain 'כלי' — 3-char guard prevents stripping. Got: '{result.actual}'"

    def test_prefix_shin_guard_prevents_short_result(self, cases):
        """C06v2_03: 'שכר' — prefix ש NOT stripped (would leave 'כר' = 2 chars < 3)."""
        c = next(c for c in cases if c["case_id"] == "C06v2_03")
        result = validate_canonicalization(c)
        assert (
            result.actual == "שכר"
        ), f"'שכר' must remain 'שכר' — 3-char guard prevents stripping. Got: '{result.actual}'"

    def test_prefix_shin_strips_known_limitation(self, cases):
        """C06v2_04: 'שמחה' → 'מחה' — KNOWN LIMITATION: ש stripped despite being root letter.

        Same defect class as C06_06 (מדינה→דינה). The canonicalizer cannot distinguish
        prefix letters from root-initial letters. This test pins the actual behavior
        so any change is explicit rather than silent.
        """
        c = next(c for c in cases if c["case_id"] == "C06v2_04")
        result = validate_canonicalization(c)
        assert result.actual == "מחה", (
            f"Known limitation: 'שמחה' (happiness) → 'מחה' due to ש stripping. "
            f"Got: '{result.actual}'"
        )

    def test_prefix_matrix_contains_kaf_and_shin(self):
        """HEBREW_PREFIXES must contain both כ and ש.

        This pins the prefix set contract. If כ or ש are removed from HEBREW_PREFIXES,
        C06v2_01 and C06v2_04 (strip cases) would silently start failing the gold.
        """
        assert "כ" in HEBREW_PREFIXES, "HEBREW_PREFIXES must contain כ"
        assert "ש" in HEBREW_PREFIXES, "HEBREW_PREFIXES must contain ש"


# ---------------------------------------------------------------------------
# Multi-token nikud
# ---------------------------------------------------------------------------


class TestMultiTokenNikud:
    def test_all_tokens_nikud_stripped(self, cases):
        """C06v2_05: both tokens in 'בֵּית סֵפֶר' must have nikud stripped → 'בית_ספר'.

        C06_06 (Wave 1) only tested single-token nikud. This case proves that
        strip_nikud() operates on the full text before tokenizing, stripping nikud
        from all tokens simultaneously.
        """
        c = next(c for c in cases if c["case_id"] == "C06v2_05")
        result = validate_canonicalization(c)
        assert result.actual == "בית_ספר", (
            f"Multi-token nikud must all be stripped. "
            f"'בֵּית סֵפֶר' → 'בית_ספר'. Got: '{result.actual}'"
        )


# ---------------------------------------------------------------------------
# Mixed Hebrew/Latin
# ---------------------------------------------------------------------------


class TestMixedHebrewLatin:
    def test_latin_preserved_and_lowercased(self, cases):
        """C06v2_06: 'קוד Python' → 'קוד_python' — Latin preserved, lowercased.

        The cleanup regex [^\\u0590-\\u05FF0-9a-zA-Z_\\s] keeps Latin letters.
        The .lower() step lowercases the full canonical including Latin.
        By design — enables clustering mixed-language terms.
        """
        c = next(c for c in cases if c["case_id"] == "C06v2_06")
        result = validate_canonicalization(c)
        assert (
            result.actual == "קוד_python"
        ), f"'קוד Python' must → 'קוד_python' (Latin lowercased). Got: '{result.actual}'"

    def test_latin_direct(self):
        """Inline: verify Latin is lowercased independently of gold fixture."""
        assert canonicalize_hebrew_term("ניתוח SQL", None) == "ניתוח_sql"
        assert canonicalize_hebrew_term("מסד נתונים NoSQL", None) == "מסד_נתונים_nosql"


# ---------------------------------------------------------------------------
# Geresh handling
# ---------------------------------------------------------------------------


class TestGereshHandling:
    def test_geresh_stripped_via_normalize_quotes(self, cases):
        """C06v2_07: 'צה׳ל' → 'צהל' — geresh ׳ (U+05F3) stripped same way as gershayim.

        Pipeline: normalize_quotes() converts U+05F3 → ASCII ' (U+0027),
        then cleanup regex removes ' (not in [Hebrew/digit/Latin/_/space]).
        Same mechanism as C06_07 (gershayim ״ → \" → stripped).
        """
        c = next(c for c in cases if c["case_id"] == "C06v2_07")
        result = validate_canonicalization(c)
        assert (
            result.actual == "צהל"
        ), f"'צה׳ל' must → 'צהל' — geresh stripped. Got: '{result.actual}'"

    def test_geresh_and_gershayim_both_stripped(self):
        """Geresh ׳ and gershayim ״ both produce stripped output (no quote chars in canonical).

        This verifies the symmetry between the two Hebrew quotation marks.
        """
        # gershayim: ד״ר alone (no space, no lemma) → "דר"
        result_gershayim = canonicalize_hebrew_term("ד\u05f4ר", None)
        # geresh: same word with geresh → same canonical
        result_geresh = canonicalize_hebrew_term("ד\u05f3ר", None)
        assert result_gershayim == result_geresh == "דר", (
            f"Both ד״ר (gershayim) and ד׳ר (geresh) must produce 'דר'. "
            f"Got: gershayim='{result_gershayim}', geresh='{result_geresh}'"
        )


# ---------------------------------------------------------------------------
# Collision behavior
# ---------------------------------------------------------------------------


class TestCollisionBehavior:
    def test_collision_a_canonical(self, cases):
        """C06v2_08: 'מות' → 'מות' — מ NOT stripped (3-char guard)."""
        c = next(c for c in cases if c["case_id"] == "C06v2_08")
        result = validate_canonicalization(c)
        assert result.actual == "מות", f"'מות' must stay 'מות'. Got: '{result.actual}'"

    def test_collision_b_produces_same_canonical(self, cases):
        """C06v2_09: 'כמות' → 'מות' — KNOWN LIMITATION: collides with C06v2_08.

        'כמות' (quantity) and 'מות' (death) are unrelated words that produce the same
        canonical key. This is an extension of the מדינה→דינה limitation to the
        collision domain: prefix stripping can merge unrelated terms into one cluster.
        """
        c = next(c for c in cases if c["case_id"] == "C06v2_09")
        result = validate_canonicalization(c)
        assert (
            result.actual == "מות"
        ), f"Known limitation: 'כמות' must → 'מות' (כ strips). Got: '{result.actual}'"

    def test_collision_invariant_same_key(self):
        """'מות' and 'כמות' must produce identical canonical keys.

        This pins the collision as an explicit contract. If the canonicalizer is
        changed to distinguish these, this test will fail — prompting a gold update
        and conscious decision rather than a silent behavior change.
        """
        key_death = canonicalize_hebrew_term("מות", None)
        key_quantity = canonicalize_hebrew_term("כמות", None)
        assert key_death == key_quantity == "מות", (
            f"Collision contract: both must produce 'מות'. "
            f"Got: מות→'{key_death}', כמות→'{key_quantity}'"
        )


# ---------------------------------------------------------------------------
# Full bulk pass + determinism
# ---------------------------------------------------------------------------


class TestAllC06v2Cases:
    def test_all_c06v2_cases_pass(self, cases):
        """All 9 C06v2 gold cases must pass."""
        failures = []
        for case in cases:
            result = validate_canonicalization(case)
            if not result.match:
                failures.append(
                    {
                        "case_id": result.case_id,
                        "expected": result.expected,
                        "actual": result.actual,
                    }
                )
        assert not failures, f"C06v2 canonicalization failures:\n{failures}"

    def test_determinism_on_new_cases(self, cases):
        """All C06v2 cases must be deterministic (same input → same output)."""
        for case in cases:
            r1 = canonicalize_hebrew_term(case["surface_text"], case.get("lemma_phrase"))
            r2 = canonicalize_hebrew_term(case["surface_text"], case.get("lemma_phrase"))
            assert r1 == r2, f"Non-deterministic canonicalization for '{case['surface_text']}'"
