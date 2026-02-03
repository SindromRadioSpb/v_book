"""P2 Translation Management Table Model Tests.

Tests the TranslationManagementTableModel:
- Column structure
- Data display
- Inline editing
- Model behavior

Headless Qt tests (no GUI rendering).
"""

import unittest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

# Ensure single QApplication instance
app = QApplication.instance()
if app is None:
    app = QApplication([])


class TestTranslationManagementTableModel(unittest.TestCase):
    """Test TranslationManagementTableModel."""

    def setUp(self):
        """Create sample data."""
        from app.domain.dto import TMEntryDTO

        self.sample_entries = [
            TMEntryDTO(
                tm_id=1,
                project_id=1,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                src_text="בית",
                src_norm="בית",
                translation="дом",
                translation_norm=None,
                pos="NOUN",
                domain=None,
                notes=None,
                status="approved",
                confidence=None,
                origin="user_edit",
                source_ref="ui_test",
                created_at="2026-01-01T00:00:00",
                updated_at="2026-01-02T10:30:00",
                approved_at="2026-01-02T10:30:00",
                approved_by="test_user",
            ),
            TMEntryDTO(
                tm_id=2,
                project_id=None,  # Global
                kind="term_cluster",
                src_lang="he",
                tgt_lang="ru",
                src_text="בית הספר",
                src_norm="בית_הספר",
                translation="школа",
                translation_norm=None,
                pos=None,
                domain=None,
                notes="Test note",
                status="draft",
                confidence=0.8,
                origin="import",
                source_ref="dict_abc",
                created_at="2026-01-03T00:00:00",
                updated_at="2026-01-03T12:00:00",
                approved_at=None,
                approved_by=None,
            ),
        ]

    def test_column_count(self):
        """Test that model has expected number of columns."""
        from app.ui.models_qt import TranslationManagementTableModel

        model = TranslationManagementTableModel(self.sample_entries)

        # Expected: ID, Kind, Source, Translation, Status, Scope, Origin, Source Ref, Updated
        expected_columns = 9
        self.assertEqual(model.columnCount(), expected_columns)

    def test_row_count(self):
        """Test that model has correct row count."""
        from app.ui.models_qt import TranslationManagementTableModel

        model = TranslationManagementTableModel(self.sample_entries)
        self.assertEqual(model.rowCount(), 2)

        # Empty model
        empty_model = TranslationManagementTableModel([])
        self.assertEqual(empty_model.rowCount(), 0)

    def test_header_data(self):
        """Test column headers."""
        from app.ui.models_qt import TranslationManagementTableModel

        model = TranslationManagementTableModel(self.sample_entries)

        expected_headers = [
            "ID", "Kind", "Source", "Translation", "Status",
            "Scope", "Origin", "Source Ref", "Updated"
        ]

        for col, expected in enumerate(expected_headers):
            header = model.headerData(col, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
            self.assertEqual(header, expected, f"Column {col} header mismatch")

    def test_data_display_translation(self):
        """Test that translation data is displayed correctly."""
        from app.ui.models_qt import TranslationManagementTableModel

        model = TranslationManagementTableModel(self.sample_entries)

        # Row 0, column 3 (Translation)
        index = model.index(0, 3)
        translation = model.data(index, Qt.ItemDataRole.DisplayRole)
        self.assertEqual(translation, "дом")

        # Row 1, column 3 (Translation)
        index = model.index(1, 3)
        translation = model.data(index, Qt.ItemDataRole.DisplayRole)
        self.assertEqual(translation, "школа")

    def test_data_display_status(self):
        """Test that status data is displayed correctly."""
        from app.ui.models_qt import TranslationManagementTableModel

        model = TranslationManagementTableModel(self.sample_entries)

        # Row 0, column 4 (Status)
        index = model.index(0, 4)
        status = model.data(index, Qt.ItemDataRole.DisplayRole)
        self.assertEqual(status, "approved")

        # Row 1, column 4 (Status)
        index = model.index(1, 4)
        status = model.data(index, Qt.ItemDataRole.DisplayRole)
        self.assertEqual(status, "draft")

    def test_data_display_scope(self):
        """Test that scope data is displayed correctly."""
        from app.ui.models_qt import TranslationManagementTableModel

        model = TranslationManagementTableModel(self.sample_entries)

        # Row 0, column 5 (Scope) - project-scoped
        index = model.index(0, 5)
        scope = model.data(index, Qt.ItemDataRole.DisplayRole)
        self.assertEqual(scope, "Project 1")

        # Row 1, column 5 (Scope) - global
        index = model.index(1, 5)
        scope = model.data(index, Qt.ItemDataRole.DisplayRole)
        self.assertEqual(scope, "Global")

    def test_data_display_origin(self):
        """Test that origin data is displayed correctly."""
        from app.ui.models_qt import TranslationManagementTableModel

        model = TranslationManagementTableModel(self.sample_entries)

        # Row 0, column 6 (Origin)
        index = model.index(0, 6)
        origin = model.data(index, Qt.ItemDataRole.DisplayRole)
        self.assertEqual(origin, "user_edit")

        # Row 1, column 6 (Origin)
        index = model.index(1, 6)
        origin = model.data(index, Qt.ItemDataRole.DisplayRole)
        self.assertEqual(origin, "import")

    def test_data_display_source_ref(self):
        """Test that source_ref data is displayed correctly."""
        from app.ui.models_qt import TranslationManagementTableModel

        model = TranslationManagementTableModel(self.sample_entries)

        # Row 0, column 7 (Source Ref)
        index = model.index(0, 7)
        source_ref = model.data(index, Qt.ItemDataRole.DisplayRole)
        self.assertEqual(source_ref, "ui_test")

        # Row 1, column 7 (Source Ref)
        index = model.index(1, 7)
        source_ref = model.data(index, Qt.ItemDataRole.DisplayRole)
        self.assertEqual(source_ref, "dict_abc")

    def test_flags_translation_editable(self):
        """Test that Translation column is editable."""
        from app.ui.models_qt import TranslationManagementTableModel

        model = TranslationManagementTableModel(self.sample_entries)

        # Translation column (3) should be editable
        index = model.index(0, 3)
        flags = model.flags(index)
        self.assertTrue(flags & Qt.ItemFlag.ItemIsEditable)

        # Other columns should NOT be editable
        index_id = model.index(0, 0)
        flags_id = model.flags(index_id)
        self.assertFalse(flags_id & Qt.ItemFlag.ItemIsEditable)

    def test_setdata_updates_translation(self):
        """Test that setData updates translation in model."""
        from app.ui.models_qt import TranslationManagementTableModel

        model = TranslationManagementTableModel(self.sample_entries)

        # Edit translation for row 0
        index = model.index(0, 3)
        new_translation = "новый дом"

        # setData should return True and update the DTO
        result = model.setData(index, new_translation, Qt.ItemDataRole.EditRole)
        self.assertTrue(result)

        # Verify DTO updated
        entry = model.get_entry(0)
        self.assertEqual(entry.translation, new_translation)

    def test_setdata_emits_datachanged(self):
        """Test that setData emits dataChanged signal."""
        from app.ui.models_qt import TranslationManagementTableModel

        model = TranslationManagementTableModel(self.sample_entries)

        # Track dataChanged signal
        signal_received = []

        def on_data_changed(top_left, bottom_right, roles):
            signal_received.append((top_left.row(), top_left.column()))

        model.dataChanged.connect(on_data_changed)

        # Edit translation
        index = model.index(0, 3)
        model.setData(index, "новый перевод", Qt.ItemDataRole.EditRole)

        # Verify signal emitted
        self.assertEqual(len(signal_received), 1)
        self.assertEqual(signal_received[0], (0, 3))

    def test_update_entries_resets_model(self):
        """Test that update_entries resets the model correctly."""
        from app.ui.models_qt import TranslationManagementTableModel
        from app.domain.dto import TMEntryDTO

        model = TranslationManagementTableModel(self.sample_entries)
        self.assertEqual(model.rowCount(), 2)

        # Update with new entries
        new_entries = [
            TMEntryDTO(
                tm_id=3,
                project_id=1,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                src_text="test",
                src_norm="test",
                translation="тест",
                translation_norm=None,
                pos=None,
                domain=None,
                notes=None,
                status="approved",
                confidence=None,
                origin="user_edit",
                source_ref=None,
                created_at="2026-01-01",
                updated_at="2026-01-01",
                approved_at=None,
                approved_by=None,
            ),
        ]

        model.update_entries(new_entries, total_count=100)

        # Verify updated
        self.assertEqual(model.rowCount(), 1)
        self.assertEqual(model.total_count, 100)
        self.assertEqual(model.get_entry(0).tm_id, 3)


if __name__ == "__main__":
    unittest.main()
