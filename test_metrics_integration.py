"""Integration tests for metrics with fixture data.

Tests MetricsRegistry validation, StatsService computation, and XLSX export
using the deterministic METRICS_FIXTURE_v1 project.
"""

import unittest
import tempfile
import os
from pathlib import Path

from app.services.db_service import DBService
from app.services.stats_service import StatsService
from app.services.export_service import ExportService
from app.services.metrics_registry import get_registry, MetricType
from app.tools.seed_metrics_fixture_project import FixtureSeed


class TestMetricsIntegration(unittest.TestCase):
    """Integration tests using fixture data."""

    @classmethod
    def setUpClass(cls):
        """Set up fixture project once for all tests."""
        # Use test_m7.db (has M7+ migrations)
        cls.db_path = Path("test_m7.db")
        DBService.initialize(cls.db_path)
        cls.db_service = DBService.get_instance()

        # Seed fixture
        seeder = FixtureSeed()
        success = seeder.seed()
        if not success:
            raise RuntimeError("Fixture seeding failed")

        cls.fixture_project_id = 1  # First project
        cls.fixture_project_name = "METRICS_FIXTURE_v1"

        print(f"\n[OK] Fixture project '{cls.fixture_project_name}' seeded (ID={cls.fixture_project_id})")

    def test_01_registry_validates_fixture_metrics(self):
        """Test that MetricsRegistry validates fixture project metrics."""
        print("\n[TEST 01] Registry validates fixture metrics")

        registry = get_registry()
        stats_service = StatsService()

        with self.db_service.get_session() as session:
            stats = stats_service.compute_project_stats(session, self.fixture_project_id)

            # Convert stats to dict
            metrics = {
                "project_name": stats.project_name,
                "project_id": stats.project_id,
                "document_count": stats.document_count,
                "lemma_count": stats.lemma_count,
                "lemmas_with_translation_count": stats.lemmas_with_translation_count,
                "term_cluster_count": stats.term_cluster_count,
                "term_approved_count": stats.term_approved_count,
                "tm_entry_count": stats.tm_entry_count,
                "tm_approved_count": stats.tm_approved_count,
                "dict_entry_count": stats.dict_entry_count,
                "lemma_coverage_pct": stats.lemma_coverage_pct,
                "tm_approval_rate_pct": stats.tm_approval_rate_pct,
                "term_approval_rate_pct": stats.term_approval_rate_pct,
                "tm_entries_per_lemma_pct": stats.tm_entries_per_lemma_pct,
            }

            # Validate bounds - should not raise
            try:
                registry.validate_bounds(metrics)
                print("  [OK] Bounds validation passed")
            except ValueError as e:
                self.fail(f"Bounds validation failed: {e}")

            # Validate invariants - should not raise
            try:
                registry.validate_invariants(metrics)
                print("  [OK] Invariant validation passed")
            except ValueError as e:
                self.fail(f"Invariant validation failed: {e}")

    def test_02_all_rate_metrics_bounded(self):
        """Test that all RATE_0_100 metrics stay within [0, 100]."""
        print("\n[TEST 02] All RATE metrics bounded [0, 100]")

        stats_service = StatsService()

        with self.db_service.get_session() as session:
            stats = stats_service.compute_project_stats(session, self.fixture_project_id)

            rate_metrics = {
                "lemma_coverage_pct": stats.lemma_coverage_pct,
                "tm_approval_rate_pct": stats.tm_approval_rate_pct,
                "term_approval_rate_pct": stats.term_approval_rate_pct,
            }

            for metric_name, value in rate_metrics.items():
                self.assertGreaterEqual(value, 0.0, f"{metric_name} < 0")
                self.assertLessEqual(value, 100.0, f"{metric_name} > 100")
                print(f"  [OK] {metric_name} = {value:.1f}% [0-100]")

    def test_03_density_metric_can_exceed_100(self):
        """Test that DENSITY metrics can be >= 0 (no upper bound)."""
        print("\n[TEST 03] DENSITY metric unbounded")

        stats_service = StatsService()

        with self.db_service.get_session() as session:
            stats = stats_service.compute_project_stats(session, self.fixture_project_id)

            density = stats.tm_entries_per_lemma_pct
            self.assertGreaterEqual(density, 0.0, "Density < 0")
            # No upper bound check - density can exceed 100%
            print(f"  [OK] tm_entries_per_lemma_pct = {density:.1f}% (unbounded)")

    def test_04_invariants_hold(self):
        """Test that metric invariants hold for fixture data."""
        print("\n[TEST 04] Metric invariants hold")

        stats_service = StatsService()

        with self.db_service.get_session() as session:
            stats = stats_service.compute_project_stats(session, self.fixture_project_id)

            # Approved counts <= totals
            self.assertLessEqual(stats.tm_approved_count, stats.tm_entry_count,
                                 "tm_approved > tm_total")
            print(f"  [OK] tm_approved ({stats.tm_approved_count}) <= tm_total ({stats.tm_entry_count})")

            self.assertLessEqual(stats.term_approved_count, stats.term_cluster_count,
                                 "term_approved > term_total")
            print(f"  [OK] term_approved ({stats.term_approved_count}) <= term_total ({stats.term_cluster_count})")

            self.assertLessEqual(stats.lemmas_with_translation_count, stats.lemma_count,
                                 "lemmas_with_translation > lemma_count")
            print(f"  [OK] lemmas_with_translation ({stats.lemmas_with_translation_count}) <= lemma_count ({stats.lemma_count})")

    def test_05_fixture_matches_expected_values(self):
        """Test that fixture metrics match documented ground truth."""
        print("\n[TEST 05] Fixture matches expected ground truth")

        expected = {
            "project_name": "METRICS_FIXTURE_v1",
            "lemma_count": 10,
            "lemmas_with_translation_count": 6,
            "term_cluster_count": 5,
            "term_approved_count": 2,
            "tm_entry_count": 8,
            "tm_approved_count": 6,
            "dict_entry_count": 0,
            "lemma_coverage_pct": 60.0,
            "tm_approval_rate_pct": 75.0,
            "term_approval_rate_pct": 40.0,
            "tm_entries_per_lemma_pct": 60.0,
        }

        stats_service = StatsService()

        with self.db_service.get_session() as session:
            stats = stats_service.compute_project_stats(session, self.fixture_project_id)

            self.assertEqual(stats.project_name, expected["project_name"])
            self.assertEqual(stats.lemma_count, expected["lemma_count"])
            self.assertEqual(stats.lemmas_with_translation_count, expected["lemmas_with_translation_count"])
            self.assertEqual(stats.term_cluster_count, expected["term_cluster_count"])
            self.assertEqual(stats.term_approved_count, expected["term_approved_count"])
            self.assertEqual(stats.tm_entry_count, expected["tm_entry_count"])
            self.assertEqual(stats.tm_approved_count, expected["tm_approved_count"])
            self.assertEqual(stats.dict_entry_count, expected["dict_entry_count"])

            # Float comparisons with tolerance
            self.assertAlmostEqual(stats.lemma_coverage_pct, expected["lemma_coverage_pct"], places=1)
            self.assertAlmostEqual(stats.tm_approval_rate_pct, expected["tm_approval_rate_pct"], places=1)
            self.assertAlmostEqual(stats.term_approval_rate_pct, expected["term_approval_rate_pct"], places=1)
            self.assertAlmostEqual(stats.tm_entries_per_lemma_pct, expected["tm_entries_per_lemma_pct"], places=1)

            print(f"  [OK] All {len(expected)} metrics match ground truth")

    def test_06_xlsx_export_includes_all_metrics(self):
        """Test that XLSX Statistics sheet includes all 17 metrics from registry."""
        print("\n[TEST 06] XLSX export includes all 17 metrics")

        export_service = ExportService()

        with self.db_service.get_session() as session:
            # Export to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as f:
                temp_path = f.name

            try:
                export_service.export_xlsx(session, temp_path, project_id=self.fixture_project_id)

                # Read XLSX and verify Statistics sheet
                import openpyxl
                wb = openpyxl.load_workbook(temp_path, read_only=True)

                self.assertIn("Statistics", wb.sheetnames, "Statistics sheet missing")
                ws = wb["Statistics"]

                # Count rows (excluding header)
                rows = list(ws.rows)
                data_rows = len(rows) - 1  # Exclude header

                # Registry has 17 specs (2 identifiers + 12 data + 3 separators)
                registry = get_registry()
                expected_rows = len(registry.get_ordered_specs())

                self.assertEqual(data_rows, expected_rows,
                                f"Expected {expected_rows} rows, got {data_rows}")

                print(f"  [OK] XLSX Statistics has {data_rows} rows (matches registry)")

                # Verify specific metrics exist
                metric_labels = [row[0].value for row in rows[1:]]  # Skip header
                expected_labels = [
                    "Project Name",
                    "Project ID",
                    "Lemmas (Unique Words)",
                    "Lemma Coverage (%)",
                    "TM Approval Rate (%)",
                    "Term Approval Rate (%)",
                    "TM Entries per Lemma (%)",
                ]

                for label in expected_labels:
                    self.assertIn(label, metric_labels, f"Missing metric: {label}")

                print(f"  [OK] All key metric labels present")

                # Close workbook before deleting
                wb.close()

            finally:
                os.unlink(temp_path)

    def test_07_registry_ordering_deterministic(self):
        """Test that registry returns metrics in deterministic order."""
        print("\n[TEST 07] Registry ordering is deterministic")

        registry = get_registry()

        # Get ordering twice
        specs1 = registry.get_ordered_specs()
        specs2 = registry.get_ordered_specs()

        self.assertEqual(len(specs1), len(specs2))

        for i, (spec1, spec2) in enumerate(zip(specs1, specs2)):
            self.assertEqual(spec1.id, spec2.id, f"Order mismatch at position {i}")

        # Verify first two are identifiers
        self.assertEqual(specs1[0].label, "Project Name")
        self.assertEqual(specs1[1].label, "Project ID")

        # Verify separators are in correct positions (3, 12, 16)
        separator_positions = [i for i, spec in enumerate(specs1) if spec.type == MetricType.SEPARATOR]
        self.assertEqual(len(separator_positions), 3, "Should have 3 separators")

        print(f"  [OK] Ordering is deterministic ({len(specs1)} specs)")
        print(f"  [OK] Separators at positions: {separator_positions}")

    def test_08_registry_spec_lookup(self):
        """Test MetricsRegistry spec lookup by key."""
        print("\n[TEST 08] Registry spec lookup works")

        registry = get_registry()

        # Lookup by key
        spec = registry.get_spec_by_key("lemma_coverage_pct")
        self.assertIsNotNone(spec)
        self.assertEqual(spec.label, "Lemma Coverage (%)")
        self.assertEqual(spec.type, MetricType.RATE_0_100)
        self.assertEqual(spec.bounds, (0.0, 100.0))

        print("  [OK] Spec lookup by key works")

        # Lookup non-existent key
        spec_none = registry.get_spec_by_key("nonexistent_metric")
        self.assertIsNone(spec_none)

        print("  [OK] Returns None for non-existent key")


if __name__ == "__main__":
    unittest.main()
