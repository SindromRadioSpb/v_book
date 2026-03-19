"""Tests for reference corpus service-level guards."""

import pytest
from pathlib import Path

from app.infra.sa_models import DictProject
from app.services.db_service import DBService
from app.services.project_service import ProjectService
from app.services.ingest_service import IngestService
from app.domain.exceptions import ReferenceCorpusReadonlyError


@pytest.fixture
def db_service(tmp_path):
    """Initialize test database."""
    db_path = tmp_path / "test.db"
    DBService.initialize(db_path)
    yield DBService.get_instance()
    DBService.shutdown()


@pytest.fixture
def project_service():
    """Create project service."""
    return ProjectService()


@pytest.fixture
def ingest_service():
    """Create ingest service."""
    return IngestService()


@pytest.fixture
def reference_project(db_service, project_service):
    """Create a reference corpus project."""
    with db_service.get_session() as session:
        project = project_service.create_project(
            session,
            name="Test Reference Corpus",
            description="Test reference",
            auto_assign_reference=False,
        )
        project_id = project.project_id

        # Mark as reference corpus
        project.is_general_corpus = 1
        session.commit()

        return project_id


def test_cannot_delete_reference_project(db_service, project_service, reference_project):
    """Test that reference corpus projects cannot be deleted."""
    with db_service.get_session() as session:
        with pytest.raises(ReferenceCorpusReadonlyError, match="Cannot delete reference corpus"):
            project_service.delete_project(session, reference_project)


def test_cannot_add_documents_to_reference_corpus(
    db_service, project_service, ingest_service, reference_project, tmp_path
):
    """Test that documents cannot be added to reference corpus."""
    # Create test file
    test_file = tmp_path / "test.txt"
    test_file.write_text("Test content", encoding="utf-8")

    with db_service.get_session() as session:
        # Get default corpus (always exists after create_project)
        corpus = project_service.get_default_corpus(session, reference_project)
        corpus_id = corpus.corpus_id

        with pytest.raises(
            ReferenceCorpusReadonlyError, match="Cannot add documents to reference corpus"
        ):
            ingest_service.import_document(session, corpus_id, test_file)


def test_cannot_delete_documents_from_reference_corpus(
    db_service, project_service, ingest_service, reference_project, tmp_path
):
    """Test that documents cannot be deleted from reference corpus."""
    # First, temporarily allow document import (by unmarking as reference)
    with db_service.get_session() as session:
        project = session.get(DictProject, reference_project)
        project.is_general_corpus = 0
        session.commit()

        # Import a document
        corpus = project_service.get_default_corpus(session, reference_project)
        corpus_id = corpus.corpus_id

        test_file = tmp_path / "test.txt"
        test_file.write_text("Test content", encoding="utf-8")

        doc = ingest_service.import_document(session, corpus_id, test_file)
        session.commit()

        # Re-mark as reference corpus
        project.is_general_corpus = 1
        session.commit()

        # Now try to delete - should fail
        with pytest.raises(
            ReferenceCorpusReadonlyError, match="Cannot delete documents from reference corpus"
        ):
            ingest_service.delete_document(session, doc.doc_id)


def test_can_modify_non_reference_project(db_service, project_service, ingest_service, tmp_path):
    """Test that regular (non-reference) projects can be modified normally."""
    with db_service.get_session() as session:
        # Create regular project (not reference)
        project = project_service.create_project(
            session,
            name="Regular Project",
            description="Not a reference",
            auto_assign_reference=False,
        )
        project_id = project.project_id

        corpus = project_service.get_default_corpus(session, project_id)
        corpus_id = corpus.corpus_id

        # Import document - should succeed
        test_file = tmp_path / "test.txt"
        test_file.write_text("Test content", encoding="utf-8")

        doc = ingest_service.import_document(session, corpus_id, test_file)
        assert doc is not None

        # Delete document - should succeed
        ingest_service.delete_document(session, doc.doc_id)

        # Delete project - should succeed
        project_service.delete_project(session, project_id)


def test_reference_corpus_marker_is_persisted(db_service, project_service, reference_project):
    """Test that is_general_corpus flag is properly persisted."""
    with db_service.get_session() as session:
        project = session.get(DictProject, reference_project)
        assert project.is_general_corpus == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
