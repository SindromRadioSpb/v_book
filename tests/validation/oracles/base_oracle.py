"""Base oracle interface for NLP pipeline validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OracleResult:
    """Standardised result returned by every oracle validate_*() call."""

    case_id: str
    match: bool
    expected: Any = None
    actual: Any = None
    missing: list = field(default_factory=list)
    extra: list = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "match": self.match,
            "expected": self.expected,
            "actual": self.actual,
            "missing": self.missing,
            "extra": self.extra,
            "notes": self.notes,
        }
