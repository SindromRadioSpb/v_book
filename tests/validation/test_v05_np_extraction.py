"""V05 — NP chunk extraction validation (C05).

Tests extract_np_chunks_from_sentence() against gold expected chunks.
No Stanza required — uses pre-tokenized inputs.
"""

from __future__ import annotations

import pytest

from tests.validation.oracles.oracle_np import validate_np_extraction


@pytest.fixture
def cases(gold_data):
    return gold_data("c05_np_extraction")["cases"]


class TestNPExtraction:
    def test_all_cases_pass(self, cases):
        failures = []
        for case in cases:
            # Skip C05_07 subset-match case from all-pass check, handle separately
            if case.get("expected_chunks_contain"):
                continue
            result = validate_np_extraction(case)
            if not result.match:
                failures.append(
                    {
                        "case_id": result.case_id,
                        "expected": result.expected,
                        "actual": result.actual,
                        "missing": result.missing,
                    }
                )
        assert not failures, f"NP extraction failures:\n{failures}"

    @pytest.mark.parametrize("case_idx", range(7))
    def test_individual_case(self, cases, case_idx):
        if case_idx >= len(cases):
            pytest.skip(f"Case index {case_idx} out of range")
        case = cases[case_idx]
        result = validate_np_extraction(case)
        assert result.match, (
            f"Case {result.case_id}: "
            f"expected={result.expected}, actual={result.actual}, missing={result.missing}"
        )

    def test_stop_pos_breaks_segment(self, cases):
        """C05_03: VERB in the middle must break the NP segment."""
        c = next(c for c in cases if c["case_id"] == "C05_03")
        result = validate_np_extraction(c)
        assert result.match, f"STOP_POS test failed: {result.missing}"

    def test_empty_when_all_stop_pos(self, cases):
        """C05_06: All STOP_POS tokens → zero chunks."""
        c = next(c for c in cases if c["case_id"] == "C05_06")
        result = validate_np_extraction(c)
        assert result.actual == 0, f"Expected 0 chunks, got {result.actual}"

    def test_max_len_respected(self, cases):
        """C05_05: max_len=2 must exclude all spans longer than 2."""
        from app.domain.term_extraction.np_extractor import extract_np_chunks_from_sentence

        c = next(c for c in cases if c["case_id"] == "C05_05")
        tokens = c["input"]["tokens"]
        actual = extract_np_chunks_from_sentence(tokens, min_len=2, max_len=2)
        for chunk in actual:
            length = chunk.get("length", len(chunk.get("token_indices", [])))
            assert length <= 2, f"Chunk exceeds max_len=2: {chunk}"

    def test_determinism(self):
        """Same token list must produce same chunks on two calls."""
        from app.domain.term_extraction.np_extractor import extract_np_chunks_from_sentence

        tokens = [
            {"text": "ילד", "lemma": "ילד", "pos": "NOUN"},
            {"text": "גדול", "lemma": "גדול", "pos": "ADJ"},
            {"text": "חכם", "lemma": "חכם", "pos": "NOUN"},
        ]
        run1 = extract_np_chunks_from_sentence(tokens)
        run2 = extract_np_chunks_from_sentence(tokens)
        assert run1 == run2, "NP extraction is non-deterministic"
