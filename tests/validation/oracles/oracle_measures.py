"""Oracle for association measure validation (C07)."""

from __future__ import annotations

import math

from app.domain.term_extraction.association_measures import (
    compute_dice,
    compute_llr,
    compute_pmi,
    compute_tscore,
)

from tests.validation.oracles.base_oracle import OracleResult

DEFAULT_TOLERANCE = 0.01


def _approx_eq(a: float | None, b: float | None, tol: float) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return math.isclose(a, b, abs_tol=tol)


def validate_association_measures(case: dict) -> OracleResult:
    """Compare compute_pmi/dice/llr/tscore outputs against hand-calculated gold.

    Args:
        case: A dict from c07_association_measures.json cases[].
    """
    case_id = case["case_id"]
    inp = case["inputs"]
    expected = case["expected"]
    tol = case.get("tolerance_override", DEFAULT_TOLERANCE)

    c_xy, c_x, c_y, n = inp["c_xy"], inp["c_x"], inp["c_y"], inp["n"]

    actual_pmi = compute_pmi(c_xy, c_x, c_y, n)
    actual_dice = compute_dice(c_xy, c_x, c_y)
    actual_llr = compute_llr(c_xy, c_x, c_y, n)
    actual_tscore = compute_tscore(c_xy, c_x, c_y, n)

    failures: list[str] = []

    for measure_name, actual_val, compute_fn_name in [
        ("pmi", actual_pmi, "compute_pmi"),
        ("dice", actual_dice, "compute_dice"),
        ("llr", actual_llr, "compute_llr"),
        ("tscore", actual_tscore, "compute_tscore"),
    ]:
        if measure_name not in expected:
            continue
        exp_val = expected[measure_name]
        if not _approx_eq(actual_val, exp_val, tol):
            failures.append(f"{measure_name}: expected={exp_val}, actual={actual_val} (tol={tol})")

    match = len(failures) == 0

    return OracleResult(
        case_id=case_id,
        match=match,
        expected={k: v for k, v in expected.items() if k != "notes"},
        actual={
            "pmi": actual_pmi,
            "dice": actual_dice,
            "llr": actual_llr,
            "tscore": actual_tscore,
        },
        missing=failures,
        notes=case.get("notes", "") + " | " + "; ".join(failures),
    )
