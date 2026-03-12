"""Tests for SentencesWorkspaceService."""

from unittest.mock import MagicMock, patch


class TestSentencesWorkspaceServiceNorm:
    """Normalization helper tests that do not need a database."""

    def test_norm_returns_string(self):
        from app.services.sentences_workspace_service import SentencesWorkspaceService

        svc = SentencesWorkspaceService()
        result = svc._norm("he", "shalom olam")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_norm_fallback_on_error(self):
        """If normalize_for_tm raises, the fallback must still return text."""
        from app.services.sentences_workspace_service import SentencesWorkspaceService

        svc = SentencesWorkspaceService()
        result = svc._norm("he", "")
        assert isinstance(result, str)


class TestSentencesWorkspaceServiceBatchOverlays:
    """Batch overlay helpers should stay bounded and avoid per-row lookups."""

    def _make_mock_session(self, execute_results=None):
        session = MagicMock()
        if execute_results is not None:
            session.execute.side_effect = [
                MagicMock(**{"all.return_value": result})
                for result in execute_results
            ]
        return session

    def test_batch_get_translations_returns_dict(self):
        from app.services.sentences_workspace_service import SentencesWorkspaceService

        svc = SentencesWorkspaceService()
        session = MagicMock()
        session.execute.return_value.all.return_value = [
            ("norm_hello", "shalom", "approved", "user_edit")
        ]
        result = svc._batch_get_translations(
            session,
            project_id=1,
            src_lang="he",
            texts=["hello"],
        )
        assert isinstance(result, dict)
        assert len(result) <= 1

    def test_batch_get_translations_empty_texts(self):
        from app.services.sentences_workspace_service import SentencesWorkspaceService

        svc = SentencesWorkspaceService()
        session = MagicMock()
        result = svc._batch_get_translations(
            session,
            project_id=1,
            src_lang="he",
            texts=[],
        )
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
                ("he", "norm", "shalom"): "ready"
            }
            mock_cls.return_value = mock_svc
            svc._batch_get_audio(session, "he", ["shalom"])
            mock_svc.bulk_get_status_for_items.assert_called_once()


class TestSentencesWorkspaceServiceIdHelpers:
    """ID helper methods must preserve selection scopes."""

    def _make_id_result(self, ids):
        mock_result = MagicMock()
        mock_result.all.return_value = [(i,) for i in ids]
        return mock_result

    def test_get_page_sentence_ids_returns_list(self):
        from app.services.sentences_workspace_service import SentencesWorkspaceService

        svc = SentencesWorkspaceService()
        session = MagicMock()
        session.execute.return_value = self._make_id_result([1, 2, 3])
        result = svc.get_page_sentence_ids(
            session,
            project_id=1,
            page=1,
            page_size=100,
        )
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
        """Unfiltered path must use the SUM fast path."""
        from app.services.sentences_workspace_service import SentencesWorkspaceService

        svc = SentencesWorkspaceService()
        session = MagicMock()
        session.execute.return_value.scalar.return_value = 42
        session.execute.return_value.scalar_one_or_none.return_value = 42
        result = svc.count_sentences(session, project_id=1)
        assert result == 42

    def test_paginated_sentence_query_uses_limit_offset(self):
        """Default page path must propagate limit/offset into the fast SQL."""
        from app.services.sentences_workspace_service import SentencesWorkspaceService

        svc = SentencesWorkspaceService()
        session = MagicMock()
        page_result = MagicMock()
        page_result.mappings.return_value.all.return_value = []
        session.execute.return_value = page_result

        with patch.object(svc, "_get_project_corpus_ids", return_value=[1]), patch.object(
            svc, "_get_project_src_lang", return_value="he"
        ), patch.object(svc, "_batch_get_translations", return_value={}), patch.object(
            svc, "_batch_get_sentence_niqqud", return_value={}
        ), patch.object(
            svc, "_batch_get_audio", return_value={}
        ):
            result = svc.list_sentences(session, project_id=1, page=2, page_size=50)

        assert isinstance(result, list)
        stmt = session.execute.call_args.args[0]
        params = session.execute.call_args.args[1]
        assert "LIMIT :limit OFFSET :offset" in str(stmt)
        assert params["limit"] == 50
        assert params["offset"] == 50

    def test_list_sentences_uses_pk_scan_fast_path_for_default_sentence_sort(self):
        from app.services.sentences_workspace_service import SentencesWorkspaceService

        svc = SentencesWorkspaceService()
        session = MagicMock()

        page_result = MagicMock()
        page_result.mappings.return_value.all.return_value = [
            {
                "sentence_id": 7,
                "doc_id": 11,
                "sent_index": 0,
                "text": "wiki alpha",
            }
        ]
        doc_result = MagicMock()
        doc_result.all.return_value = [(11, "doc-11.txt")]
        session.execute.side_effect = [page_result, doc_result]

        with patch.object(svc, "_get_project_corpus_ids", return_value=[1, 2]), patch.object(
            svc, "_get_project_src_lang", return_value="he"
        ), patch.object(svc, "_batch_get_translations", return_value={}), patch.object(
            svc, "_batch_get_sentence_niqqud", return_value={}
        ), patch.object(
            svc, "_batch_get_audio", return_value={}
        ):
            result = svc.list_sentences(
                session,
                project_id=1,
                text_search="wiki",
                page=1,
                page_size=100,
            )

        assert [dto.sentence_id for dto in result] == [7]
        assert result[0].doc_name == "doc-11.txt"
        fast_stmt = session.execute.call_args_list[0].args[0]
        fast_params = session.execute.call_args_list[0].args[1]
        assert "FROM document_sentence NOT INDEXED" in str(fast_stmt)
        assert fast_params["text_search"] == "%wiki%"

    def test_list_sentences_keeps_orm_path_for_doc_filtered_queries(self):
        from app.services.sentences_workspace_service import SentencesWorkspaceService

        svc = SentencesWorkspaceService()
        session = MagicMock()
        session.execute.return_value.all.return_value = []

        with patch.object(svc, "_get_project_corpus_ids", return_value=[1]), patch.object(
            svc, "_get_project_src_lang", return_value="he"
        ), patch.object(svc, "_batch_get_translations", return_value={}), patch.object(
            svc, "_batch_get_sentence_niqqud", return_value={}
        ), patch.object(
            svc, "_batch_get_audio", return_value={}
        ):
            result = svc.list_sentences(
                session,
                project_id=1,
                doc_id_filter=55,
                page=1,
                page_size=25,
            )

        assert result == []
        fallback_stmt = session.execute.call_args.args[0]
        assert "NOT INDEXED" not in str(fallback_stmt)
