"""Oracle for lemma aggregation validation (C03).

Tests the invariant that Freq and Docs are computed correctly across documents
without requiring a database — simulates the aggregation logic in Python.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from tests.validation.oracles.base_oracle import OracleResult


def simulate_aggregation(documents: list[dict]) -> list[dict]:
    """Simulate lemma aggregation from multi-doc token lists.

    Args:
        documents: List of {doc_id, tokens: [{lemma, pos}]} dicts.

    Returns:
        List of {lemma, freq, docs} aggregates.
    """
    freq_counter: Counter = Counter()
    doc_sets: dict[str, set] = defaultdict(set)

    for doc in documents:
        doc_id = doc["doc_id"]
        for token in doc["tokens"]:
            lemma = token["lemma"]
            freq_counter[lemma] += 1
            doc_sets[lemma].add(doc_id)

    return [
        {"lemma": lemma, "freq": freq, "docs": len(doc_sets[lemma])}
        for lemma, freq in freq_counter.items()
    ]


def validate_lemma_aggregation(case: dict) -> OracleResult:
    """Validate simulated aggregation against gold expected values.

    Args:
        case: Top-level dict from c03_lemma_aggregation.json or a scenario
              dict from c03v2_lemma_aggregation.json. Must contain:
              - documents: list of {doc_id, tokens} dicts
              - expected_aggregates: list of {lemma, freq, docs} dicts
              - corpus_id (optional): used as case_id in OracleResult
              - invariants (optional): list of invariant dicts
    """
    corpus_id: str = case.get("corpus_id", "C03")
    documents = case["documents"]
    expected_agg = {row["lemma"]: row for row in case["expected_aggregates"]}

    actual_list = simulate_aggregation(documents)
    actual_agg = {row["lemma"]: row for row in actual_list}

    failures: list[str] = []

    # Check aggregate count matches (catches extra unexpected lemmas)
    if len(actual_list) != len(expected_agg):
        failures.append(
            f"aggregate count: expected={len(expected_agg)}, actual={len(actual_list)}. "
            f"Extra: {sorted(set(actual_agg) - set(expected_agg))}. "
            f"Missing: {sorted(set(expected_agg) - set(actual_agg))}"
        )

    # Check each expected lemma
    for lemma, exp_row in expected_agg.items():
        if lemma not in actual_agg:
            failures.append(f"lemma '{lemma}' missing from actual")
            continue
        act_row = actual_agg[lemma]
        if act_row["freq"] != exp_row["freq"]:
            failures.append(
                f"lemma '{lemma}' freq: expected={exp_row['freq']}, actual={act_row['freq']}"
            )
        if act_row["docs"] != exp_row["docs"]:
            failures.append(
                f"lemma '{lemma}' docs: expected={exp_row['docs']}, actual={act_row['docs']}"
            )

    # Check invariants
    for row in actual_list:
        if row["docs"] > row["freq"]:
            failures.append(
                f"INVARIANT VIOLATED: lemma '{row['lemma']}' docs({row['docs']}) > freq({row['freq']})"
            )

    # Check total_token_count invariant
    if "invariants" in case:
        for inv in case["invariants"]:
            if inv["name"] == "total_tokens_match":
                expected_total = inv["total_token_count"]
                actual_total = sum(r["freq"] for r in actual_list)
                if actual_total != expected_total:
                    failures.append(
                        f"total_tokens_match: expected={expected_total}, actual={actual_total}"
                    )

    return OracleResult(
        case_id=corpus_id,
        match=len(failures) == 0,
        expected=expected_agg,
        actual=actual_agg,
        missing=failures,
    )
