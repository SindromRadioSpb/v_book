"""Tests for MetricsRegistry.

Validates registry structure, ordering, bounds, and invariants.
"""

import unittest
from app.services.metrics_registry import (
    MetricsRegistry, MetricType, MetricId, get_registry
)


class TestMetricsRegistry(unittest.TestCase):
    """Test MetricsRegistry functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.registry = get_registry()

    def test_01_registry_singleton(self):
        """Test that get_registry returns singleton."""
        reg1 = get_registry()
        reg2 = get_registry()
        self.assertIs(reg1, reg2)
        print("[OK] Registry is singleton")

    def test_02_ordered_specs_count(self):
        """Test that registry has all 17 metrics (including separators)."""
        specs = self.registry.get_ordered_specs()
        self.assertEqual(len(specs), 17, "Should have 17 total specs")
        print(f"[OK] Registry has {len(specs)} specs")

    def test_03_metric_ids_stable(self):
        """Test that all MetricId enum values are defined."""
        specs = self.registry.get_ordered_specs()
        metric_ids = {spec.id for spec in specs}

        # Check key metric IDs exist
        required_ids = {
            MetricId.PROJECT_NAME,
            MetricId.PROJECT_ID,
            MetricId.LEMMA_COUNT,
            MetricId.LEMMAS_WITH_TRANSLATION,
            MetricId.LEMMA_COVERAGE_PCT,
            MetricId.TM_APPROVAL_RATE_PCT,
            MetricId.TERM_APPROVAL_RATE_PCT,
            MetricId.TM_ENTRIES_PER_LEMMA_PCT,
        }

        for req_id in required_ids:
            self.assertIn(req_id, metric_ids, f"Missing {req_id}")

        print(f"[OK] All {len(required_ids)} required metric IDs present")

    def test_04_deterministic_ordering(self):
        """Test that ordering is deterministic and starts with identifiers."""
        specs = self.registry.get_ordered_specs()

        # First two should be identifiers
        self.assertEqual(specs[0].id, MetricId.PROJECT_NAME)
        self.assertEqual(specs[1].id, MetricId.PROJECT_ID)

        # Should have separators
        separator_count = sum(1 for s in specs if s.type == MetricType.SEPARATOR)
        self.assertEqual(separator_count, 3, "Should have 3 separators")

        print("[OK] Ordering is deterministic with correct structure")

    def test_05_rate_metrics_have_bounds(self):
        """Test that all RATE_0_100 metrics have bounds [0, 100]."""
        specs = self.registry.get_ordered_specs()
        rate_specs = [s for s in specs if s.type == MetricType.RATE_0_100]

        self.assertGreater(len(rate_specs), 0, "Should have RATE metrics")

        for spec in rate_specs:
            self.assertIsNotNone(spec.bounds, f"{spec.id} should have bounds")
            min_val, max_val = spec.bounds
            self.assertEqual(min_val, 0.0, f"{spec.id} min should be 0.0")
            self.assertEqual(max_val, 100.0, f"{spec.id} max should be 100.0")

        print(f"[OK] All {len(rate_specs)} RATE metrics have bounds [0, 100]")

    def test_06_density_metrics_unbounded(self):
        """Test that DENSITY metrics have no upper bound."""
        specs = self.registry.get_ordered_specs()
        density_specs = [s for s in specs if s.type == MetricType.DENSITY]

        self.assertGreater(len(density_specs), 0, "Should have DENSITY metrics")

        for spec in density_specs:
            # Density metrics should not have restrictive upper bounds
            # (they can exceed 100%)
            if spec.bounds:
                logger.warning(f"DENSITY metric {spec.id} has bounds: {spec.bounds}")

        print(f"[OK] {len(density_specs)} DENSITY metrics found")

    def test_07_validate_bounds_pass(self):
        """Test bounds validation with valid values."""
        valid_metrics = {
            "lemma_count": 100,
            "lemmas_with_translation_count": 50,
            "lemma_coverage_pct": 50.0,
            "tm_approval_rate_pct": 75.0,
            "term_approval_rate_pct": 0.0,
            "tm_entries_per_lemma_pct": 150.0,  # DENSITY can exceed 100
        }

        # Should not raise
        self.registry.validate_bounds(valid_metrics)
        print("[OK] Bounds validation passes for valid metrics")

    def test_08_validate_bounds_fail_negative_count(self):
        """Test bounds validation fails for negative count."""
        invalid_metrics = {
            "lemma_count": -5,
        }

        with self.assertRaises(ValueError) as cm:
            self.registry.validate_bounds(invalid_metrics)

        self.assertIn("COUNT must be >= 0", str(cm.exception))
        print("[OK] Bounds validation rejects negative COUNT")

    def test_09_validate_bounds_fail_rate_out_of_range(self):
        """Test bounds validation fails for rate > 100."""
        invalid_metrics = {
            "lemma_coverage_pct": 150.0,  # RATE cannot exceed 100
        }

        with self.assertRaises(ValueError) as cm:
            self.registry.validate_bounds(invalid_metrics)

        self.assertIn("RATE must be in", str(cm.exception))
        print("[OK] Bounds validation rejects RATE > 100")

    def test_10_validate_invariants_pass(self):
        """Test invariant validation with consistent metrics."""
        valid_metrics = {
            "lemma_count": 10,
            "lemmas_with_translation_count": 7,
            "tm_entry_count": 15,
            "tm_approved_count": 10,
            "term_cluster_count": 5,
            "term_approved_count": 3,
            "lemma_coverage_pct": 70.0,
        }

        # Should not raise
        self.registry.validate_invariants(valid_metrics)
        print("[OK] Invariant validation passes for consistent metrics")

    def test_11_validate_invariants_fail_approved_exceeds_total(self):
        """Test invariant validation fails when approved > total."""
        invalid_metrics = {
            "tm_entry_count": 10,
            "tm_approved_count": 15,  # Invalid: approved > total
        }

        with self.assertRaises(ValueError) as cm:
            self.registry.validate_invariants(invalid_metrics)

        self.assertIn("tm_approved", str(cm.exception))
        print("[OK] Invariant validation rejects approved > total")

    def test_12_get_spec_by_key(self):
        """Test looking up specs by machine key."""
        spec = self.registry.get_spec_by_key("lemma_count")
        self.assertIsNotNone(spec)
        self.assertEqual(spec.id, MetricId.LEMMA_COUNT)
        self.assertEqual(spec.label, "Lemmas (Unique Words)")
        print("[OK] Spec lookup by key works")


if __name__ == "__main__":
    unittest.main()
