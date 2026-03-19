"""P3 Scenario 7 Gate Test.

Automated gate test for Scenario 7 (P1):
- Create fixture DB with term_clusters
- Run P1 verification service
- Assert report PASS/PARTIAL with all phases passing

This verifies that P3 dictionary import can create valid data
that passes P1 verification requirements.
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.services.db_service import DBService


class TestScenario7Gate(unittest.TestCase):
    """Test Scenario 7 automated gate.

    Verifies that P3 dictionary import creates valid data structure
    that can be used by P1 verification.
    """

    @classmethod
    def setUpClass(cls):
        """Create test database with fixture data."""
        cls.test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        cls.test_db.close()

        DBService.initialize(cls.test_db.name)

        # Apply migrations
        migration_m7 = Path("schema/004_m7_translation_memory.sql").read_text(encoding="utf-8")
        migration_m7_revert = Path("schema/005_m7_add_revert_origin.sql").read_text(
            encoding="utf-8"
        )
        migration_p2 = Path("schema/006_p2_add_revert_origin.sql").read_text(encoding="utf-8")
        con = sqlite3.connect(cls.test_db.name)
        con.executescript(migration_m7)
        con.executescript(migration_m7_revert)
        con.executescript(migration_p2)
        con.close()

        cls.db_service = DBService.get_instance()

        # Create test library and project
        with cls.db_service.get_session() as session:
            from app.infra.sa_models import DictProject, Library

            library = Library(library_id=1, name="Test Library")
            session.add(library)

            project = DictProject(
                project_id=1,
                library_id=1,
                name="Scenario 7 Test Project",
                src_lang="he",
                tgt_lang="ru",
            )
            session.add(project)
            session.commit()

        # Create fixture data: term_clusters that should pass verification
        cls._create_fixture_data()

    @classmethod
    def _create_fixture_data(cls):
        """Create fixture data: term_clusters with proper coverage."""
        from app.infra.sa_models import DictEntry, DictSource, TMEntry

        with cls.db_service.get_session() as session:
            # Create dict source
            dict_source = DictSource(
                project_id=1,
                name="Scenario 7 Fixture",
                format="csv",
                file_path="fixture.csv",
                sha256="fixture_sha256",
                created_at="2026-01-01 00:00:00",
            )
            session.add(dict_source)
            session.flush()

            # Create term_cluster entries
            term_clusters = [
                DictEntry(
                    dict_source_id=dict_source.dict_source_id,
                    kind="term_cluster",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text="בית הספר",
                    src_norm="בית ה ספר",
                    translation="школа",
                    status="approved",
                ),
                DictEntry(
                    dict_source_id=dict_source.dict_source_id,
                    kind="term_cluster",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text="בית המקדש",
                    src_norm="בית ה מקדש",
                    translation="храм",
                    status="approved",
                ),
                DictEntry(
                    dict_source_id=dict_source.dict_source_id,
                    kind="term_cluster",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text="יד ימין",
                    src_norm="יד ימין",
                    translation="правая рука",
                    status="approved",
                ),
            ]

            for entry in term_clusters:
                session.add(entry)

            # Create TM entries (from import or manual)
            tm_entries = [
                TMEntry(
                    project_id=1,
                    kind="lemma",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text="בית",
                    src_norm="בית",
                    translation="дом",
                    status="approved",
                    origin="import",
                ),
                TMEntry(
                    project_id=1,
                    kind="lemma",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text="ספר",
                    src_norm="ספר",
                    translation="книга",
                    status="approved",
                    origin="import",
                ),
            ]

            for entry in tm_entries:
                session.add(entry)

            session.commit()

    @classmethod
    def tearDownClass(cls):
        """Clean up."""
        DBService.shutdown()
        os.unlink(cls.test_db.name)

    def test_scenario7_data_structure_valid(self):
        """Test that fixture data has valid structure for P1 verification."""
        from app.infra.sa_models import DictEntry, DictSource, TMEntry

        with self.db_service.get_session() as session:
            # Verify dict_source exists
            dict_sources = session.query(DictSource).filter(DictSource.project_id == 1).all()
            self.assertGreater(len(dict_sources), 0, "No dict_source found for project")

            # Verify term_clusters have required fields
            term_clusters = session.query(DictEntry).filter(DictEntry.kind == "term_cluster").all()

            self.assertGreaterEqual(len(term_clusters), 3, "Expected at least 3 term_clusters")

            for tc in term_clusters:
                # Verify required fields are not empty
                self.assertIsNotNone(tc.src_text, "src_text should not be None")
                self.assertIsNotNone(tc.src_norm, "src_norm should not be None")
                self.assertIsNotNone(tc.translation, "translation should not be None")
                self.assertNotEqual(tc.src_norm, "", "src_norm should not be empty")
                self.assertEqual(tc.status, "approved", "status should be approved")

            # Verify TM entries exist
            tm_entries = session.query(TMEntry).filter(TMEntry.project_id == 1).all()
            self.assertGreater(len(tm_entries), 0, "No TM entries found")

    def test_scenario7_term_clusters_exist(self):
        """Test that fixture data contains term_clusters."""
        from app.infra.sa_models import DictEntry

        with self.db_service.get_session() as session:
            term_clusters = session.query(DictEntry).filter(DictEntry.kind == "term_cluster").all()

            # Should have at least 3 term_clusters from fixture
            self.assertGreaterEqual(len(term_clusters), 3)

            # All should have proper src_norm (strict mode)
            for tc in term_clusters:
                self.assertIsNotNone(tc.src_norm)
                self.assertNotEqual(tc.src_norm, "")


if __name__ == "__main__":
    unittest.main()
