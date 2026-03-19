"""Metrics Registry - Single Source of Truth for Project Metrics.

Provides type-safe, validated access to all project statistics metrics.
Runtime enforcement of bounds, invariants, and deterministic ordering.

See docs/METRICS_CATALOG.md for comprehensive metric definitions.
"""

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

logger = logging.getLogger(__name__)


class MetricType(Enum):
    """Metric value types with specific validation rules."""

    TEXT = auto()  # String identifier
    COUNT = auto()  # Integer >= 0
    RATE_0_100 = auto()  # Float in [0.0, 100.0]
    DENSITY = auto()  # Float >= 0.0, unbounded (can exceed 100%)
    SEPARATOR = auto()  # Blank row for formatting


class MetricId(Enum):
    """Stable metric identifiers matching METRICS_CATALOG.md."""

    # Identifiers
    PROJECT_NAME = "M001"
    PROJECT_ID = "M002"

    # Counts
    DOCUMENT_COUNT = "M010"
    LEMMA_COUNT = "M011"
    LEMMAS_WITH_TRANSLATION = "M012"
    TERM_CLUSTER_COUNT = "M013"
    TERM_APPROVED_COUNT = "M014"
    TM_ENTRY_COUNT = "M015"
    TM_APPROVED_COUNT = "M016"
    DICT_ENTRY_COUNT = "M017"

    # Coverage/Rate metrics
    LEMMA_COVERAGE_PCT = "M020"
    TM_APPROVAL_RATE_PCT = "M021"
    TERM_APPROVAL_RATE_PCT = "M022"

    # Density metrics
    TM_ENTRIES_PER_LEMMA_PCT = "M030"

    # Separators (formatting)
    SEP_1 = "SEP1"
    SEP_2 = "SEP2"
    SEP_3 = "SEP3"


@dataclass(frozen=True)
class MetricSpec:
    """Specification for a single metric.

    Immutable specification that defines how a metric is computed,
    validated, and rendered.
    """

    id: MetricId
    key: str  # Machine key (e.g., "lemma_count")
    label: str  # Display label for UI/XLSX
    type: MetricType
    bounds: tuple[float, float] | None = None  # (min, max) for validation
    doc: str = ""  # Short definition

    def validate_value(self, value: Any) -> None:
        """Validate value against metric type and bounds.

        Raises:
            ValueError: If value violates type or bounds constraints
        """
        if self.type == MetricType.TEXT:
            if not isinstance(value, str):
                raise ValueError(f"{self.id}: Expected str, got {type(value)}")

        elif self.type == MetricType.COUNT:
            if not isinstance(value, int):
                raise ValueError(f"{self.id}: Expected int, got {type(value)}")
            if value < 0:
                raise ValueError(f"{self.id}: COUNT must be >= 0, got {value}")

        elif self.type == MetricType.RATE_0_100:
            if not isinstance(value, (int, float)):
                raise ValueError(f"{self.id}: Expected numeric, got {type(value)}")
            value = float(value)
            if self.bounds:
                min_val, max_val = self.bounds
                if not (min_val <= value <= max_val):
                    raise ValueError(
                        f"{self.id}: RATE must be in [{min_val}, {max_val}], got {value}"
                    )
            # Default bounds for RATE_0_100
            if not (0.0 <= value <= 100.0):
                raise ValueError(f"{self.id}: RATE must be in [0, 100], got {value}")

        elif self.type == MetricType.DENSITY:
            if not isinstance(value, (int, float)):
                raise ValueError(f"{self.id}: Expected numeric, got {type(value)}")
            value = float(value)
            if value < 0.0:
                raise ValueError(f"{self.id}: DENSITY must be >= 0, got {value}")

        elif self.type == MetricType.SEPARATOR:
            # Separators can be empty string or None
            pass


class MetricsRegistry:
    """Registry of all project metrics with deterministic ordering.

    Single source of truth for metric definitions, ordering, and validation.
    Enforces catalog consistency at runtime.
    """

    # Deterministic ordering (XLSX Statistics order)
    _ORDERED_SPECS = [
        # Identifiers
        MetricSpec(
            MetricId.PROJECT_NAME,
            "project_name",
            "Project Name",
            MetricType.TEXT,
            doc="Project name from dict_project table",
        ),
        MetricSpec(
            MetricId.PROJECT_ID,
            "project_id",
            "Project ID",
            MetricType.COUNT,
            doc="Project ID (primary key)",
        ),
        # Separator
        MetricSpec(MetricId.SEP_1, "", "", MetricType.SEPARATOR),
        # Counts
        MetricSpec(
            MetricId.DOCUMENT_COUNT,
            "document_count",
            "Documents",
            MetricType.COUNT,
            doc="Count of source documents in project corpora",
        ),
        MetricSpec(
            MetricId.LEMMA_COUNT,
            "lemma_count",
            "Lemmas (Unique Words)",
            MetricType.COUNT,
            doc="Count of distinct lemmas",
        ),
        MetricSpec(
            MetricId.LEMMAS_WITH_TRANSLATION,
            "lemmas_with_translation_count",
            "Lemmas with Translation",
            MetricType.COUNT,
            doc="Count of lemmas with >=1 approved TM entry",
        ),
        MetricSpec(
            MetricId.TERM_CLUSTER_COUNT,
            "term_cluster_count",
            "Term Clusters",
            MetricType.COUNT,
            doc="Count of term clusters (all statuses)",
        ),
        MetricSpec(
            MetricId.TERM_APPROVED_COUNT,
            "term_approved_count",
            "Terms Approved",
            MetricType.COUNT,
            doc="Count of approved term clusters",
        ),
        MetricSpec(
            MetricId.TM_ENTRY_COUNT,
            "tm_entry_count",
            "TM Entries",
            MetricType.COUNT,
            doc="Count of TM entries (all statuses)",
        ),
        MetricSpec(
            MetricId.TM_APPROVED_COUNT,
            "tm_approved_count",
            "TM Approved",
            MetricType.COUNT,
            doc="Count of approved TM entries",
        ),
        MetricSpec(
            MetricId.DICT_ENTRY_COUNT,
            "dict_entry_count",
            "Dictionary Entries",
            MetricType.COUNT,
            doc="Count of static dictionary entries",
        ),
        # Separator
        MetricSpec(MetricId.SEP_2, "", "", MetricType.SEPARATOR),
        # Coverage/Rate metrics
        MetricSpec(
            MetricId.LEMMA_COVERAGE_PCT,
            "lemma_coverage_pct",
            "Lemma Coverage (%)",
            MetricType.RATE_0_100,
            bounds=(0.0, 100.0),
            doc="Percentage of lemmas with >=1 approved translation",
        ),
        MetricSpec(
            MetricId.TM_APPROVAL_RATE_PCT,
            "tm_approval_rate_pct",
            "TM Approval Rate (%)",
            MetricType.RATE_0_100,
            bounds=(0.0, 100.0),
            doc="Percentage of TM entries that are approved",
        ),
        MetricSpec(
            MetricId.TERM_APPROVAL_RATE_PCT,
            "term_approval_rate_pct",
            "Term Approval Rate (%)",
            MetricType.RATE_0_100,
            bounds=(0.0, 100.0),
            doc="Percentage of term clusters that are approved",
        ),
        # Separator
        MetricSpec(MetricId.SEP_3, "", "", MetricType.SEPARATOR),
        # Density metrics
        MetricSpec(
            MetricId.TM_ENTRIES_PER_LEMMA_PCT,
            "tm_entries_per_lemma_pct",
            "TM Entries per Lemma (%)",
            MetricType.DENSITY,
            doc="Average approved TM entries per lemma (can exceed 100%)",
        ),
    ]

    def __init__(self):
        """Initialize registry with spec lookup maps."""
        self._specs_by_id = {spec.id: spec for spec in self._ORDERED_SPECS}
        self._specs_by_key = {spec.key: spec for spec in self._ORDERED_SPECS if spec.key}

    def get_ordered_specs(self) -> list[MetricSpec]:
        """Get all metric specs in deterministic XLSX order."""
        return list(self._ORDERED_SPECS)

    def get_spec(self, metric_id: MetricId) -> MetricSpec:
        """Get spec by metric ID."""
        return self._specs_by_id[metric_id]

    def get_spec_by_key(self, key: str) -> MetricSpec | None:
        """Get spec by machine key."""
        return self._specs_by_key.get(key)

    def validate_bounds(self, metrics: dict[str, Any]) -> None:
        """Validate all metric values against their specs.

        Args:
            metrics: Dict mapping metric keys to values

        Raises:
            ValueError: If any metric violates its bounds or type
        """
        for key, value in metrics.items():
            if key == "":  # Skip separators
                continue
            spec = self.get_spec_by_key(key)
            if spec:
                spec.validate_value(value)

    def validate_invariants(self, metrics: dict[str, Any]) -> None:
        """Validate metric invariants (consistency rules).

        Args:
            metrics: Dict mapping metric keys to values

        Raises:
            ValueError: If invariants are violated
        """
        # Extract values safely
        lemma_count = metrics.get("lemma_count", 0)
        lemmas_with_translation = metrics.get("lemmas_with_translation_count", 0)
        tm_entry_count = metrics.get("tm_entry_count", 0)
        tm_approved_count = metrics.get("tm_approved_count", 0)
        term_cluster_count = metrics.get("term_cluster_count", 0)
        term_approved_count = metrics.get("term_approved_count", 0)

        # Approved counts never exceed totals
        if tm_approved_count > tm_entry_count:
            raise ValueError(
                f"Invariant violated: tm_approved ({tm_approved_count}) > "
                f"tm_total ({tm_entry_count})"
            )

        if term_approved_count > term_cluster_count:
            raise ValueError(
                f"Invariant violated: term_approved ({term_approved_count}) > "
                f"term_total ({term_cluster_count})"
            )

        if lemmas_with_translation > lemma_count:
            raise ValueError(
                f"Invariant violated: lemmas_with_translation ({lemmas_with_translation}) > "
                f"lemma_count ({lemma_count})"
            )

        # If no approved TM, no coverage
        lemma_coverage_pct = metrics.get("lemma_coverage_pct", 0.0)
        if tm_approved_count == 0 and lemmas_with_translation > 0:
            raise ValueError(
                f"Invariant violated: tm_approved=0 but lemmas_with_translation={lemmas_with_translation}"
            )

        # If all lemmas covered, coverage should be 100%
        if lemma_count > 0 and lemmas_with_translation == lemma_count:
            if abs(lemma_coverage_pct - 100.0) > 0.1:  # tolerance for float
                logger.warning(f"All lemmas covered but coverage={lemma_coverage_pct:.1f}% != 100%")


# Global singleton instance
_registry = None


def get_registry() -> MetricsRegistry:
    """Get global MetricsRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = MetricsRegistry()
    return _registry
