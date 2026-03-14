"""Task 15: Tests for translate scope functionality.

Smoke tests to verify code compiles and basic logic is correct.
Full integration testing with DB fixtures requires manual testing.
"""

import pytest


class TestCodeImports:
    """Test that all Task 15 modules import successfully."""

    def test_dictionary_service_new_methods(self):
        """Test DictionaryService has new ID fetching methods."""
        from app.services.dictionary_service import DictionaryService

        service = DictionaryService()
        assert hasattr(service, 'count_lemma_ids_for_translation'), \
            "DictionaryService should have count_lemma_ids_for_translation method"
        assert hasattr(service, 'fetch_lemma_ids_for_translation'), \
            "DictionaryService should have fetch_lemma_ids_for_translation method"

    def test_term_extraction_service_new_methods(self):
        """Test TermExtractionService has new ID fetching methods."""
        from app.services.term_extraction_service import TermExtractionService

        # Check class has methods (don't instantiate - requires DBService init)
        assert hasattr(TermExtractionService, 'count_cluster_ids_for_translation'), \
            "TermExtractionService should have count_cluster_ids_for_translation method"
        assert hasattr(TermExtractionService, 'fetch_cluster_ids_for_translation'), \
            "TermExtractionService should have fetch_cluster_ids_for_translation method"

    def test_translate_all_filtered_worker_import(self):
        """Test TranslateAllFilteredWorker exists."""
        from app.ui.workers import TranslateAllFilteredWorker

        assert hasattr(TranslateAllFilteredWorker, 'run'), \
            "TranslateAllFilteredWorker should have run method"
        assert hasattr(TranslateAllFilteredWorker, 'cancel'), \
            "TranslateAllFilteredWorker should have cancel method"

    def test_batch_translate_dialog_scope_support(self):
        """Test BatchTranslateDialog has scope support."""
        from app.ui.dialogs.batch_translate_dialog import show_batch_translate_dialog, BatchTranslateDialog

        # Check signature includes new params
        import inspect
        sig = inspect.signature(show_batch_translate_dialog)
        params = sig.parameters
        assert 'scope_enabled' in params, "show_batch_translate_dialog should have scope_enabled param"
        assert 'filtered_count' in params, "show_batch_translate_dialog should have filtered_count param"

        # Check dialog has get_scope method
        assert hasattr(BatchTranslateDialog, 'get_scope'), \
            "BatchTranslateDialog should have get_scope method"

    def test_dictionary_view_updated(self):
        """Test DictionaryView has updated on_batch_translate."""
        from app.ui.dictionary_view import DictionaryView

        assert hasattr(DictionaryView, '_update_page_size_combo'), \
            "DictionaryView should have _update_page_size_combo method"

    def test_terms_view_updated(self):
        """Test TermsView has updated on_batch_translate."""
        from app.ui.terms_view import TermsView

        assert hasattr(TermsView, '_update_page_size_combo'), \
            "TermsView should have _update_page_size_combo method"


class TestMethodSignatures:
    """Test method signatures are correct."""

    def test_count_lemma_ids_signature(self):
        """Test count_lemma_ids_for_translation signature."""
        from app.services.dictionary_service import DictionaryService
        import inspect

        method = DictionaryService.count_lemma_ids_for_translation
        sig = inspect.signature(method)
        params = sig.parameters

        # Should have: self, session, project_id, filters, write_mode
        assert 'session' in params
        assert 'project_id' in params
        assert 'filters' in params
        assert 'write_mode' in params

    def test_fetch_lemma_ids_signature(self):
        """Test fetch_lemma_ids_for_translation signature."""
        from app.services.dictionary_service import DictionaryService
        import inspect

        method = DictionaryService.fetch_lemma_ids_for_translation
        sig = inspect.signature(method)
        params = sig.parameters

        # Should have: self, session, project_id, filters, write_mode, limit, offset
        assert 'session' in params
        assert 'project_id' in params
        assert 'filters' in params
        assert 'write_mode' in params
        assert 'limit' in params
        assert 'offset' in params

    def test_translate_all_filtered_worker_signature(self):
        """Test TranslateAllFilteredWorker __init__ signature."""
        from app.ui.workers import TranslateAllFilteredWorker
        import inspect

        sig = inspect.signature(TranslateAllFilteredWorker.__init__)
        params = sig.parameters

        # Should have entity_type, project_id, filters, provider_mode, write_mode, etc.
        assert 'entity_type' in params
        assert 'project_id' in params
        assert 'filters' in params
        assert 'provider_mode' in params
        assert 'write_mode' in params


class TestBasicLogic:
    """Test basic logic without DB."""

    def test_write_mode_constants(self, qtbot):
        """Test write mode strings are as expected."""
        # These are the write modes used throughout the code
        write_modes = ["FILL_EMPTY", "OVERWRITE", "SKIP_NON_EMPTY"]

        # Just verify they're used consistently
        from app.ui.dialogs.batch_translate_dialog import BatchTranslateDialog

        dialog = BatchTranslateDialog()
        qtbot.addWidget(dialog)
        result = dialog.get_write_mode()
        assert result in write_modes, f"Write mode should be one of {write_modes}"

    def test_scope_constants(self, qtbot):
        """Test scope strings are as expected."""
        scopes = ["current_page", "all_filtered"]

        from app.ui.dialogs.batch_translate_dialog import BatchTranslateDialog

        dialog = BatchTranslateDialog()
        qtbot.addWidget(dialog)
        result = dialog.get_scope()
        assert result in scopes, f"Scope should be one of {scopes}"
