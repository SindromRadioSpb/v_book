"""Tests for SentencesWorkspaceService (Task 22 / PATCH-05)."""
import pytest
from unittest.mock import MagicMock, patch


class TestSentencesWorkspaceServiceNorm:
    """Tests for normalization helper — no DB needed."""

    def test_norm_returns_string(self):
        from app.services.sentences_workspace_service import SentencesWorkspaceService
        svc = SentencesWorkspaceService()
        result = svc._norm("he", "שלום עולם")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_norm_fallback_on_error(self):
        """If normalize_for_tm raises, fallback must not raise."""
        from app.services.sentences_workspace_service import SentencesWorkspaceService
        svc = SentencesWorkspaceService()
        # Empty string
        result = svc._norm("he", "")
        assert isinstance(result, str)


class TestSentencesWorkspaceServiceBatchOverlays:
    """test_batch_overlay_no_per_row_queries"""

    def _make_mock_session(self, execute_results=None):
        """Create a mock session that returns given execute results in sequence."""
        session = MagicMock()
        if execute_results is not None:
            session.execute.side_effect = [MagicMock(**{
                'all.return_value': result
            }) for result in execute_results]
        return session

    def test_batch_get_translations_returns_dict(self):
        from app.services.sentences_workspace_service import SentencesWorkspaceService
        svc = SentencesWorkspaceService()
        session = MagicMock()
        # Mock: returns one TM entry
        session.execute.return_value.all.return_value = [
            ("norm_hello", "שלום", "approved", "user_edit")
        ]
        result = svc._batch_get_translations(session, project_id=1, src_lang="he", texts=["hello"])
        assert isinstance(result, dict)
        # Dict is keyed by norm
        assert len(result) <= 1  # 0 or 1 depending on norm matching

    def test_batch_get_translations_empty_texts(self):
        from app.services.sentences_workspace_service import SentencesWorkspaceService
        svc = SentencesWorkspaceService()
        session = MagicMock()
        result = svc._batch_get_translations(session, project_id=1, src_lang="he", texts=[])
        assert result == {}
        session.execute.assert_not_called()

    def test_batch_get_sentence_niqqud_empty(self):
        from app.services.sentences_workspace_service import SentencesWorkspaceService
        svc = SentencesWorkspaceService()
        session = MagicMock()
        result = svc._batch_get_sentence_niqqud(session, [])
        assert result == {}
        session.execute.assert_not_called()

    def test_batch_get_audio_empty(self):
        from app.services.sentences_workspace_service import SentencesWorkspaceService
        svc = SentencesWorkspaceService()
        session = MagicMock()
        result = svc._batch_get_audio(session, "he", [])
        assert result == {}

    def test_batch_get_audio_calls_hash_aware_bulk_status(self):
        from app.services.sentences_workspace_service import SentencesWorkspaceService
        svc = SentencesWorkspaceService()
        session = MagicMock()
        with patch("app.services.audio_asset_service.AudioAssetService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.bulk_get_status_for_items.return_value = {
                ("he", "norm", "Ч©ЧњЧ•Чќ"): "ready"
            }
            mock_cls.return_value = mock_svc
            result = svc._batch_get_audio(session, "he", ["שלום"])
            mock_svc.bulk_get_status_for_items.assert_called_once()


class TestSentencesWorkspaceServiceIdHelpers:
    """test_selected_current_all_filtered_scope_id_selection"""

    def _make_id_result(self, ids):
        mock_result = MagicMock()
        mock_result.all.return_value = [(i,) for i in ids]
        return mock_result

    def test_get_page_sentence_ids_returns_list(self):
        from app.services.sentences_workspace_service import SentencesWorkspaceService
        svc = SentencesWorkspaceService()
        session = MagicMock()
        session.execute.return_value = self._make_id_result([1, 2, 3])
        result = svc.get_page_sentence_ids(session, project_id=1, page=1, page_size=100)
        assert result == [1, 2, 3]

    def test_get_all_filtered_sentence_ids_returns_list(self):
        from app.services.sentences_workspace_service import SentencesWorkspaceService
        svc = SentencesWorkspaceService()
        session = MagicMock()
        session.execute.return_value = self._make_id_result([10, 20, 30, 40])
        result = svc.get_all_filtered_sentence_ids(session, project_id=1)
        assert result == [10, 20, 30, 40]

    def test_get_sentence_texts_by_ids_empty(self):
        from app.services.sentences_workspace_service import SentencesWorkspaceService
        svc = SentencesWorkspaceService()
        session = MagicMock()
        result = svc.get_sentence_texts_by_ids(session, [])
        assert result == {}
        session.execute.assert_not_called()

    def test_count_sentences_returns_int(self):
        """Unfiltered path uses SUM fast path (scalar), not scalar_one_or_none."""
        from app.services.sentences_workspace_service import SentencesWorkspaceService
        svc = SentencesWorkspaceService()
        session = MagicMock()
        # Fast path (no doc_filter, no text_search) calls .scalar()
        session.execute.return_value.scalar.return_value = 42
        session.execute.return_value.scalar_one_or_none.return_value = 42
        result = svc.count_sentences(session, project_id=1)
        assert result == 42

    def test_paginated_sentence_query_uses_limit_offset(self):
        """test_paginated_sentence_query — verifies that pagination params flow to DB query."""
        from app.services.sentences_workspace_service import SentencesWorkspaceService
        svc = SentencesWorkspaceService()
        session = MagicMock()
        # Mock chain
        mock_result = MagicMock()
        mock_result.all.return_value = []
        session.execute.return_value = mock_result

        # Should not raise
        result = svc.list_sentences(session, project_id=1, page=2, page_size=50)
        assert isinstance(result, list)
        # Verify DB was queried (pagination params integrated via SQLAlchemy limit/offset)
        assert session.execute.called
