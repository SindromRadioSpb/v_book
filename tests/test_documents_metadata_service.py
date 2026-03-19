"""Tests for DocumentService metadata CRUD and validation (Task 22 / PATCH-02/03)."""

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Validation helpers — no DB needed
# ---------------------------------------------------------------------------


class TestLinkUrlValidation:
    """test_link_validation_http_https_only"""

    def test_http_accepted(self):
        from app.services.document_service import validate_link_url

        result = validate_link_url("http://example.com/text")
        assert result == "http://example.com/text"

    def test_https_accepted(self):
        from app.services.document_service import validate_link_url

        result = validate_link_url("https://example.com/text?q=1")
        assert result == "https://example.com/text?q=1"

    def test_javascript_rejected(self):
        from app.services.document_service import validate_link_url

        with pytest.raises(ValueError, match="not allowed"):
            validate_link_url("javascript:alert(1)")

    def test_file_scheme_rejected(self):
        from app.services.document_service import validate_link_url

        with pytest.raises(ValueError, match="not allowed"):
            validate_link_url("file:///etc/passwd")

    def test_ftp_rejected(self):
        from app.services.document_service import validate_link_url

        with pytest.raises(ValueError, match="not allowed"):
            validate_link_url("ftp://files.example.com/doc.txt")

    def test_none_returns_none(self):
        from app.services.document_service import validate_link_url

        assert validate_link_url(None) is None

    def test_empty_string_returns_none(self):
        from app.services.document_service import validate_link_url

        assert validate_link_url("   ") is None

    def test_too_long_rejected(self):
        from app.services.document_service import validate_link_url

        long_url = "https://example.com/" + "a" * 2000
        with pytest.raises(ValueError, match="too long"):
            validate_link_url(long_url)

    def test_missing_host_rejected(self):
        from app.services.document_service import validate_link_url

        with pytest.raises(ValueError, match="no host"):
            validate_link_url("https://")


class TestTagValidation:
    def test_valid_tag(self):
        from app.services.document_service import validate_tag

        assert validate_tag("grammar") == "grammar"

    def test_whitespace_stripped(self):
        from app.services.document_service import validate_tag

        assert validate_tag("  vocab  ") == "vocab"

    def test_empty_returns_none(self):
        from app.services.document_service import validate_tag

        assert validate_tag("") is None
        assert validate_tag(None) is None

    def test_too_long_rejected(self):
        from app.services.document_service import validate_tag

        with pytest.raises(ValueError, match="too long"):
            validate_tag("x" * 201)

    def test_comma_separated_tags_are_canonicalized_and_deduped(self):
        from app.services.document_service import validate_tag

        assert validate_tag(" test_tag , tag 2, test_tag ") == "test_tag, tag 2"


class TestTagParsingHelpers:
    def test_split_tag_tokens_supports_explicit_separators(self):
        from app.services.document_service import split_tag_tokens

        assert split_tag_tokens("test_tag, tag 2;tag 3") == ["test_tag", "tag 2", "tag 3"]

    def test_split_tag_tokens_does_not_split_multi_word_tag_by_space(self):
        from app.services.document_service import split_tag_tokens

        assert split_tag_tokens("daily life") == ["daily life"]


class TestLevelValidation:
    def test_valid_levels(self):
        from app.services.document_service import validate_level

        for level in ("aleph", "bet", "gimel", "he"):
            assert validate_level(level) == level

    def test_invalid_level_rejected(self):
        from app.services.document_service import validate_level

        with pytest.raises(ValueError, match="not allowed"):
            validate_level("dalet")

    def test_none_returns_none(self):
        from app.services.document_service import validate_level

        assert validate_level(None) is None

    def test_empty_returns_none(self):
        from app.services.document_service import validate_level

        assert validate_level("") is None


# ---------------------------------------------------------------------------
# DocumentService — with mock session
# ---------------------------------------------------------------------------


class TestDocumentServiceListAndFilter:
    """test_search_by_title_and_metadata_filters"""

    def _make_mock_doc(self, **kwargs):
        doc = MagicMock()
        doc.doc_id = kwargs.get("doc_id", 1)
        doc.corpus_id = kwargs.get("corpus_id", 10)
        doc.file_name = kwargs.get("file_name", "test.txt")
        doc.file_path = kwargs.get("file_path", "/tmp/test.txt")
        doc.file_size_bytes = kwargs.get("file_size_bytes", 1024)
        doc.status = kwargs.get("status", "processed")
        doc.sentence_count = kwargs.get("sentence_count", 5)
        doc.token_count = kwargs.get("token_count", 50)
        doc.imported_at = kwargs.get("imported_at", "2026-01-01T00:00:00.000000Z")
        doc.processed_at = kwargs.get("processed_at", None)
        doc.tag = kwargs.get("tag", None)
        doc.link_url = kwargs.get("link_url", None)
        doc.level = kwargs.get("level", None)
        doc.topic = kwargs.get("topic", None)
        return doc

    def test_list_documents_returns_dtos(self):
        from app.services.document_service import DocumentService

        svc = DocumentService()
        mock_session = MagicMock()
        mock_doc = self._make_mock_doc(doc_id=42, file_name="shir.txt", level="aleph")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_doc]
        mock_session.execute.return_value = mock_result

        dtos = svc.list_documents(mock_session, corpus_id=10)
        assert len(dtos) == 1
        assert dtos[0].doc_id == 42
        assert dtos[0].file_name == "shir.txt"
        assert dtos[0].level == "aleph"

    def test_metadata_fields_validation_and_persistence(self):
        from app.services.document_service import DocumentService

        svc = DocumentService()
        mock_doc = self._make_mock_doc(doc_id=1)

        mock_session = MagicMock()
        mock_session.get.return_value = mock_doc
        mock_session.flush = MagicMock()

        dto = svc.update_metadata(
            mock_session,
            1,
            tag="grammar",
            link_url="https://example.com",
            level="bet",
            topic="daily life",
        )
        assert mock_doc.tag == "grammar"
        assert mock_doc.link_url == "https://example.com"
        assert mock_doc.level == "bet"
        assert mock_doc.topic == "daily life"
        mock_session.flush.assert_called_once()

    def test_update_metadata_invalid_link_raises(self):
        from app.services.document_service import DocumentService

        svc = DocumentService()
        mock_doc = self._make_mock_doc(doc_id=1)
        mock_session = MagicMock()
        mock_session.get.return_value = mock_doc

        with pytest.raises(ValueError, match="not allowed"):
            svc.update_metadata(mock_session, 1, link_url="javascript:evil()")

    def test_update_metadata_invalid_level_raises(self):
        from app.services.document_service import DocumentService

        svc = DocumentService()
        mock_doc = self._make_mock_doc(doc_id=1)
        mock_session = MagicMock()
        mock_session.get.return_value = mock_doc

        with pytest.raises(ValueError, match="not allowed"):
            svc.update_metadata(mock_session, 1, level="dalet")

    def test_update_metadata_not_found_raises(self):
        from app.services.document_service import DocumentService

        svc = DocumentService()
        mock_session = MagicMock()
        mock_session.get.return_value = None

        with pytest.raises(LookupError):
            svc.update_metadata(mock_session, 999, tag="test")

    def test_ellipsis_leaves_field_unchanged(self):
        """Passing ... (Ellipsis) must not change the field."""
        from app.services.document_service import DocumentService

        svc = DocumentService()
        mock_doc = self._make_mock_doc(doc_id=1, tag="original_tag")
        mock_session = MagicMock()
        mock_session.get.return_value = mock_doc
        mock_session.flush = MagicMock()

        # Only update topic, leave tag as ...
        svc.update_metadata(mock_session, 1, topic="new topic")
        assert mock_doc.tag == "original_tag"  # Unchanged
