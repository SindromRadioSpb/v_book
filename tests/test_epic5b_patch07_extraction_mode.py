"""Epic 5B PATCH-07: extraction_mode parameter wiring.

Tests:
1. Worker accepts extraction_mode kwarg (overwrite)
2. Worker accepts extraction_mode kwarg (merge)
3. Worker accepts extraction_mode kwarg (replace_layer)
4. Worker defaults extraction_mode to "overwrite"
5. Service accepts extraction_mode=overwrite and runs chunked path
6. Service accepts extraction_mode=merge and runs legacy path
7. Service extraction_mode=replace_layer raises NotImplementedError
8. Service backward-compat: overwrite=False maps to merge
"""

import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.infra.sa_models import Base, DictProject, Library
from app.services.term_extraction_service import TermExtractionService


# ---------------------------------------------------------------------------
# Worker parameter tests (no QApplication needed — just inspect __init__)
# ---------------------------------------------------------------------------


def test_worker_accepts_overwrite_mode():
    from app.ui.workers import ProjectTermExtractionWorker

    w = ProjectTermExtractionWorker(project_id=1, extraction_mode="overwrite")
    assert w.extraction_mode == "overwrite"


def test_worker_accepts_merge_mode():
    from app.ui.workers import ProjectTermExtractionWorker

    w = ProjectTermExtractionWorker(project_id=1, extraction_mode="merge")
    assert w.extraction_mode == "merge"


def test_worker_accepts_replace_layer_mode():
    from app.ui.workers import ProjectTermExtractionWorker

    w = ProjectTermExtractionWorker(project_id=1, extraction_mode="replace_layer")
    assert w.extraction_mode == "replace_layer"


def test_worker_defaults_to_overwrite():
    from app.ui.workers import ProjectTermExtractionWorker

    w = ProjectTermExtractionWorker(project_id=1)
    assert w.extraction_mode == "overwrite"


# ---------------------------------------------------------------------------
# Service dispatch tests
# ---------------------------------------------------------------------------


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def set_pragma(conn, _record):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine)
    sess = Session_()

    lib = Library(library_id=1, name="Lib")
    sess.add(lib)
    sess.flush()
    proj = DictProject(project_id=1, library_id=1, name="P1", src_lang="he", tgt_lang="ru")
    sess.add(proj)
    sess.commit()

    yield sess
    sess.close()
    engine.dispose()


def test_service_overwrite_mode_calls_chunked(session):
    """extraction_mode='overwrite' dispatches to chunked path."""
    svc = TermExtractionService.__new__(TermExtractionService)
    chunked_mock = MagicMock(return_value=MagicMock())

    with patch.object(svc, "_extract_terms_for_project_chunked", chunked_mock):
        svc.extract_terms_for_project(
            session,
            1,
            extraction_mode="overwrite",
        )

    chunked_mock.assert_called_once()
    call_kwargs = chunked_mock.call_args[1]
    assert call_kwargs.get("overwrite") is True


def test_service_merge_mode_calls_legacy(session):
    """extraction_mode='merge' dispatches to legacy path (non-destructive)."""
    svc = TermExtractionService.__new__(TermExtractionService)
    legacy_mock = MagicMock(return_value=MagicMock())

    with patch.object(svc, "_extract_terms_for_project_legacy", legacy_mock):
        svc.extract_terms_for_project(
            session,
            1,
            extraction_mode="merge",
        )

    legacy_mock.assert_called_once()
    call_kwargs = legacy_mock.call_args[1]
    assert call_kwargs.get("overwrite") is False


def test_service_replace_layer_raises(session):
    """extraction_mode='replace_layer' raises NotImplementedError until PATCH-09."""
    svc = TermExtractionService.__new__(TermExtractionService)

    with pytest.raises(NotImplementedError, match="PATCH-09"):
        svc.extract_terms_for_project(
            session,
            1,
            extraction_mode="replace_layer",
        )


def test_service_backward_compat_overwrite_false_maps_to_merge(session):
    """overwrite=False with default extraction_mode='overwrite' → merge path."""
    svc = TermExtractionService.__new__(TermExtractionService)
    legacy_mock = MagicMock(return_value=MagicMock())

    with patch.object(svc, "_extract_terms_for_project_legacy", legacy_mock):
        svc.extract_terms_for_project(
            session,
            1,
            overwrite=False,
            # extraction_mode defaults to "overwrite", backward-compat maps it to "merge"
        )

    legacy_mock.assert_called_once()
    call_kwargs = legacy_mock.call_args[1]
    assert call_kwargs.get("overwrite") is False
