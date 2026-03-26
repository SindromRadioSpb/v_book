"""Oracle for noise classification validation (C08)."""

from __future__ import annotations

from app.services.entity_classifier import classify_phrase, classify_text

from tests.validation.oracles.base_oracle import OracleResult


def validate_classify_text(case: dict) -> OracleResult:
    """Compare classify_text() output against gold.

    Args:
        case: A dict from c08_noise_classification.json classify_text_cases[].
    """
    case_id = case["case_id"]
    input_text: str = case["input"]
    expected: dict = case["expected"]

    actual = classify_text(input_text)

    failures: list[str] = []

    if "entity_class" in expected and actual.entity_class != expected["entity_class"]:
        failures.append(
            f"entity_class: expected={expected['entity_class']}, actual={actual.entity_class}"
        )
    if "is_noise" in expected and actual.is_noise != expected["is_noise"]:
        failures.append(f"is_noise: expected={expected['is_noise']}, actual={actual.is_noise}")
    if "noise_reason" in expected:
        exp_reason = expected["noise_reason"]
        act_reason = actual.noise_reason
        if exp_reason is None and act_reason is not None:
            failures.append(f"noise_reason: expected=None, actual={act_reason}")
        elif exp_reason is not None and act_reason != exp_reason:
            failures.append(f"noise_reason: expected={exp_reason}, actual={act_reason}")

    return OracleResult(
        case_id=case_id,
        match=len(failures) == 0,
        expected=expected,
        actual={
            "entity_class": actual.entity_class,
            "is_noise": actual.is_noise,
            "noise_reason": actual.noise_reason,
        },
        missing=failures,
        notes=case.get("notes", ""),
    )


def validate_classify_phrase(case: dict) -> OracleResult:
    """Compare classify_phrase() output against gold.

    Args:
        case: A dict from c08_noise_classification.json classify_phrase_cases[].
    """
    case_id = case["case_id"]
    input_text: str = case["input"]
    expected: dict = case["expected"]

    actual = classify_phrase(input_text)

    failures: list[str] = []

    if "is_noise" in expected and actual.is_noise != expected["is_noise"]:
        failures.append(f"is_noise: expected={expected['is_noise']}, actual={actual.is_noise}")

    return OracleResult(
        case_id=case_id,
        match=len(failures) == 0,
        expected=expected,
        actual={"is_noise": actual.is_noise},
        missing=failures,
        notes=case.get("notes", ""),
    )
