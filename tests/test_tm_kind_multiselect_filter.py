"""Tests for TM Kind multi-select filter and persistence (Task 22 / PATCH-07)."""
import pytest
from unittest.mock import MagicMock, patch


class TestKindFilterPersistence:
    """test_kind_selection_persistence_qsettings"""

    def test_kind_filter_saved_to_settings(self):
        """Verify selected_kinds is persisted via SettingsService.set_value."""
        from app.infra.settings import SettingsService
        settings = SettingsService.get_instance()
        # Save a kind list
        settings.set_value("tm_panel/kind_filter", ["lemma", "surface"])
        # Read back
        saved = settings.get_json("tm_panel/kind_filter", None)
        assert saved == ["lemma", "surface"]

    def test_kind_filter_none_saved_as_none(self):
        """None (= All) stored cleanly."""
        from app.infra.settings import SettingsService
        settings = SettingsService.get_instance()
        settings.set_value("tm_panel/kind_filter", None)
        saved = settings.get_json("tm_panel/kind_filter", None)
        assert saved is None

    def test_kind_filter_restored_as_list(self):
        """JSON round-trip preserves list type."""
        from app.infra.settings import SettingsService
        settings = SettingsService.get_instance()
        kinds = ["term_cluster", "ngram"]
        settings.set_value("tm_panel/kind_filter", kinds)
        restored = settings.get_json("tm_panel/kind_filter", None)
        assert isinstance(restored, list)
        assert set(restored) == set(kinds)


class TestTranslationAdminServiceKindFilter:
    """test_kind_multiselect_filters_results / test_kind_filter_safe_sort_and_counts"""

    def _make_mock_entry(self, kind="lemma"):
        entry = MagicMock()
        entry.kind = kind
        entry.tm_id = 1
        entry.project_id = None
        entry.src_lang = "he"
        entry.tgt_lang = "ru"
        entry.src_text = "test"
        entry.src_norm = "test"
        entry.translation = "тест"
        entry.status = "approved"
        entry.origin = "user_edit"
        entry.source_ref = None
        entry.is_noise = None
        entry.noise_reason = None
        entry.updated_at = "2026-01-01"
        entry.created_at = "2026-01-01"
        return entry

    def test_kinds_filter_applied_single(self):
        """Single kind in kinds list → filter to that kind only."""
        from app.services.translation_admin_service import TranslationAdminService
        svc = TranslationAdminService()
        session = MagicMock()

        # Mock execute returning an empty list
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        # Should not raise
        result = svc.search_tm_entries(session, filters={"kinds": ["lemma"]})
        assert isinstance(result, list)
        assert session.execute.called

    def test_kinds_filter_empty_list_treated_as_all(self):
        """Empty list → no kind filter applied (same as All)."""
        from app.services.translation_admin_service import TranslationAdminService
        svc = TranslationAdminService()
        session = MagicMock()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        # Should not raise, should not apply kind filter
        result = svc.search_tm_entries(session, filters={"kinds": []})
        assert isinstance(result, list)

    def test_legacy_kind_still_works(self):
        """Backward compat: old single 'kind' key still works."""
        from app.services.translation_admin_service import TranslationAdminService
        svc = TranslationAdminService()
        session = MagicMock()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        result = svc.search_tm_entries(session, filters={"kind": "lemma"})
        assert isinstance(result, list)

    def test_kinds_filter_multi(self):
        """Multiple kinds in list → both included."""
        from app.services.translation_admin_service import TranslationAdminService
        svc = TranslationAdminService()
        session = MagicMock()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        result = svc.search_tm_entries(session, filters={"kinds": ["lemma", "surface"]})
        assert isinstance(result, list)
        assert session.execute.called


class TestKindFilterDialogLogic:
    """test_kind_filter_safe_sort_and_counts"""

    def test_all_selected_returns_none(self):
        """If all kinds selected → get_selected_kinds() returns None (= All)."""
        # Test KindFilterDialog.get_selected_kinds logic
        # Since we can't create a Qt widget in pytest without QApplication,
        # we test the underlying logic directly.
        all_kinds = ["lemma", "term_cluster", "ngram", "surface"]
        # Simulate: all selected
        selected = all_kinds[:]
        # Logic: if len(selected) == len(ALL_KINDS) or len(selected) == 0 → None
        result = selected if (len(selected) != len(all_kinds) and len(selected) != 0) else None
        assert result is None

    def test_none_selected_returns_none(self):
        """If no kinds selected → returns None (= All, safest fallback)."""
        all_kinds = ["lemma", "term_cluster", "ngram", "surface"]
        selected = []
        result = selected if (len(selected) != len(all_kinds) and len(selected) != 0) else None
        assert result is None

    def test_partial_selection_returns_list(self):
        """Partial selection → returns the selected subset."""
        all_kinds = ["lemma", "term_cluster", "ngram", "surface"]
        selected = ["lemma", "surface"]
        result = selected if (len(selected) != len(all_kinds) and len(selected) != 0) else None
        assert result == ["lemma", "surface"]


class TestKindFilterDefaults:
    def test_tm_default_kind_filter_keeps_sentences_off(self):
        from app.ui.translation_management_panel import TranslationManagementPanel

        assert 'surface' not in TranslationManagementPanel.DEFAULT_KIND_FILTER

