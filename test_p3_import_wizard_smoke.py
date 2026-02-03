"""P3 Import Wizard Smoke Test.

Headless smoke test for ImportWizard:
- Instantiate ImportWizard in headless environment
- Verify all components initialized
- No runtime errors
"""

import unittest
import tempfile
import sqlite3
import os
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from app.services.db_service import DBService


class TestImportWizardSmoke(unittest.TestCase):
    """Headless smoke test for ImportWizard."""

    @classmethod
    def setUpClass(cls):
        """Create test database and QApplication."""
        # Create test DB
        cls.test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        cls.test_db.close()

        DBService.initialize(cls.test_db.name)

        # Apply M7 migrations
        migration_m7 = Path("schema/004_m7_translation_memory.sql").read_text(encoding='utf-8')
        con = sqlite3.connect(cls.test_db.name)
        con.executescript(migration_m7)
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

        # Create QApplication for headless testing
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    @classmethod
    def tearDownClass(cls):
        """Clean up."""
        DBService.shutdown()
        os.unlink(cls.test_db.name)

    def test_instantiate_import_wizard(self):
        """Test that ImportWizard can be instantiated without errors."""
        from app.ui.import_wizard import ImportWizard

        # Instantiate wizard (headless)
        wizard = ImportWizard()

        # Verify components exist
        self.assertIsNotNone(wizard.file_path_edit)
        self.assertIsNotNone(wizard.scope_global_radio)
        self.assertIsNotNone(wizard.scope_project_radio)
        self.assertIsNotNone(wizard.project_combo)
        self.assertIsNotNone(wizard.kind_combo)
        self.assertIsNotNone(wizard.conflict_combo)
        self.assertIsNotNone(wizard.normalize_combo)
        self.assertIsNotNone(wizard.run_btn)
        self.assertIsNotNone(wizard.cancel_btn)
        self.assertIsNotNone(wizard.progress_bar)
        self.assertIsNotNone(wizard.log_output)

        # Verify initial state
        self.assertTrue(wizard.scope_global_radio.isChecked())
        self.assertFalse(wizard.scope_project_radio.isChecked())
        self.assertFalse(wizard.project_combo.isEnabled())
        self.assertTrue(wizard.run_btn.isEnabled())
        self.assertFalse(wizard.cancel_btn.isEnabled())

        # Verify combos have items
        self.assertGreater(wizard.kind_combo.count(), 0)
        self.assertGreater(wizard.conflict_combo.count(), 0)
        self.assertGreater(wizard.normalize_combo.count(), 0)

        # Clean up
        wizard.close()
        wizard.deleteLater()

    def test_wizard_scope_toggle(self):
        """Test that scope radio buttons toggle project combo."""
        from app.ui.import_wizard import ImportWizard

        wizard = ImportWizard()

        # Initially global selected, project combo disabled
        self.assertTrue(wizard.scope_global_radio.isChecked())
        self.assertFalse(wizard.project_combo.isEnabled())

        # Switch to project scope
        wizard.scope_project_radio.setChecked(True)
        self.assertTrue(wizard.project_combo.isEnabled())

        # Switch back to global
        wizard.scope_global_radio.setChecked(True)
        self.assertFalse(wizard.project_combo.isEnabled())

        # Clean up
        wizard.close()
        wizard.deleteLater()

if __name__ == "__main__":
    unittest.main()
