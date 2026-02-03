"""P2 UI Smoke Tests - Verify panels can be instantiated.

Quick smoke tests to ensure:
- TranslationManagementPanel imports and instantiates
- CoveragePanel imports and instantiates
- No import errors or missing dependencies
"""

import unittest
import tempfile
import sqlite3
import os
from pathlib import Path
from PyQt6.QtWidgets import QApplication

# Ensure single QApplication instance
app = QApplication.instance()
if app is None:
    app = QApplication([])


class TestP2UISmoke(unittest.TestCase):
    """Smoke tests for P2 UI panels."""

    @classmethod
    def setUpClass(cls):
        """Create test database with M7 schema."""
        cls.test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        cls.test_db.close()

        # Apply schema
        from app.services.db_service import DBService
        DBService.initialize(cls.test_db.name)

        # Apply M7 + P2 migrations
        migration_m7 = Path("schema/004_m7_translation_memory.sql").read_text(encoding='utf-8')
        migration_m7_revert = Path("schema/005_m7_add_revert_origin.sql").read_text(encoding='utf-8')
        migration_p2 = Path("schema/006_p2_add_revert_origin.sql").read_text(encoding='utf-8')
        con = sqlite3.connect(cls.test_db.name)
        con.executescript(migration_m7)
        con.executescript(migration_m7_revert)
        con.executescript(migration_p2)
        con.close()

        cls.db_service = DBService.get_instance()

        # Create test project
        with cls.db_service.get_session() as session:
            from app.infra.sa_models import Library, DictProject

            library = Library(library_id=1, name="Test Library")
            session.add(library)

            project = DictProject(
                project_id=1,
                library_id=1,
                name="Test Project",
                src_lang="he",
                tgt_lang="ru",
            )
            session.add(project)
            session.commit()

    @classmethod
    def tearDownClass(cls):
        """Clean up test database."""
        from app.services.db_service import DBService
        DBService.shutdown()
        os.unlink(cls.test_db.name)

    def test_import_translation_management_panel(self):
        """Test that TranslationManagementPanel can be imported."""
        from app.ui.translation_management_panel import TranslationManagementPanel
        self.assertIsNotNone(TranslationManagementPanel)

    def test_import_coverage_panel(self):
        """Test that CoveragePanel can be imported."""
        from app.ui.coverage_panel import CoveragePanel
        self.assertIsNotNone(CoveragePanel)

    def test_instantiate_translation_management_panel(self):
        """Test that TranslationManagementPanel can be instantiated."""
        from app.ui.translation_management_panel import TranslationManagementPanel

        # Global TM (no project context)
        panel = TranslationManagementPanel(project_id=None)
        self.assertIsNotNone(panel)
        panel.deleteLater()

        # Project TM
        panel2 = TranslationManagementPanel(project_id=1)
        self.assertIsNotNone(panel2)
        panel2.deleteLater()

    def test_instantiate_coverage_panel(self):
        """Test that CoveragePanel can be instantiated."""
        from app.ui.coverage_panel import CoveragePanel

        panel = CoveragePanel(project_id=1)
        self.assertIsNotNone(panel)
        panel.deleteLater()

    def test_translation_management_panel_has_required_attributes(self):
        """Test that TranslationManagementPanel has required attributes."""
        from app.ui.translation_management_panel import TranslationManagementPanel

        panel = TranslationManagementPanel(project_id=None)

        # Check for required widgets
        self.assertIsNotNone(panel.table_view)
        self.assertIsNotNone(panel.model)
        self.assertIsNotNone(panel.search_edit)
        self.assertIsNotNone(panel.kind_combo)
        self.assertIsNotNone(panel.status_combo)
        self.assertIsNotNone(panel.scope_combo)
        self.assertIsNotNone(panel.origin_combo)

        panel.deleteLater()

    def test_coverage_panel_has_required_attributes(self):
        """Test that CoveragePanel has required attributes."""
        from app.ui.coverage_panel import CoveragePanel

        panel = CoveragePanel(project_id=1)

        # Check for required widgets
        self.assertIsNotNone(panel.lemma_pct_label)
        self.assertIsNotNone(panel.cluster_pct_label)
        self.assertIsNotNone(panel.lemmas_table)
        self.assertIsNotNone(panel.clusters_table)
        self.assertIsNotNone(panel.include_draft_check)

        panel.deleteLater()


if __name__ == "__main__":
    unittest.main()
