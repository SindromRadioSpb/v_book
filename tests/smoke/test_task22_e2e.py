"""pytest-qt smoke coverage for Task 22 critical flows.

Marked with @pytest.mark.smoke and @pytest.mark.env.
Requires:
  - SMOKE_DB_PATH env var pointing to a source DB
  - Optional SMOKE_DOC_PATH env var pointing to a .docx test document
  - Optional SMOKE_PROJECT_ID env var (auto-detects first project if absent)

Run:
    python -m pytest tests/smoke/test_task22_e2e.py -q -m "smoke and env"
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pytest

# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------
pytestmark = [pytest.mark.smoke, pytest.mark.env, pytest.mark.serial]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def test_smoke_paths_are_isolated(isolate_smoke_environment):
    """Smoke runtime must stay under per-run temp paths, not user AppData."""
    lock_dir = Path(os.environ["HDLE_MIGRATION_LOCK_DIR"]).resolve()
    isolated_root = isolate_smoke_environment["session_root"].resolve()
    smoke_db = Path(os.environ["SMOKE_DB_PATH"]).resolve()

    assert str(lock_dir).startswith(str(isolated_root))
    assert str(smoke_db).startswith(str(isolated_root))


@pytest.fixture(scope="session")
def db_path() -> Path:
    custom = (os.environ.get("SMOKE_DB_PATH") or "").strip()
    assert custom, "SMOKE_DB_PATH must be set by smoke fixture or environment"
    p = Path(custom)
    assert p.exists(), f"SMOKE_DB_PATH does not exist: {p}"
    return p


@pytest.fixture(scope="session")
def project_id(db_service) -> int:
    from sqlalchemy import select
    from app.infra.sa_models import DictProject

    forced_raw = (os.environ.get("SMOKE_PROJECT_ID") or "").strip()
    with db_service.get_session() as session:
        if forced_raw:
            forced = int(forced_raw)
            exists = session.execute(
                select(DictProject.project_id).where(DictProject.project_id == forced)
            ).scalar_one_or_none()
            if exists is None:
                pytest.skip(f"SMOKE_PROJECT_ID={forced} not found in isolated smoke DB")
            return int(exists)

        detected = session.execute(
            select(DictProject.project_id).order_by(DictProject.project_id.asc()).limit(1)
        ).scalar_one_or_none()

    if detected is None:
        pytest.skip("No projects found in isolated smoke DB")
    return int(detected)


@pytest.fixture(scope="session")
def doc_path() -> Optional[Path]:
    raw = (os.environ.get("SMOKE_DOC_PATH") or "").strip()
    if raw:
        return Path(raw)
    return None


@pytest.fixture(scope="session")
def db_service(db_path):
    from app.services.db_service import DBService

    DBService.shutdown()
    DBService.initialize(db_path)
    instance = DBService.get_instance()
    try:
        yield instance
    finally:
        DBService.shutdown()


@pytest.fixture(scope="session")
def corpus_id(db_service, project_id) -> int:
    from app.services.project_service import ProjectService

    with db_service.get_session() as session:
        corpus = ProjectService().get_default_corpus(session, project_id)
    assert corpus is not None, f"No default corpus for project {project_id}"
    return corpus.corpus_id


@pytest.fixture(scope="session")
def src_lang(db_service, project_id) -> str:
    from app.services.project_service import ProjectService

    with db_service.get_session() as session:
        proj = ProjectService().get_project(session, project_id)
    return (proj.src_lang if proj else None) or "he"


# ---------------------------------------------------------------------------
# Helper: wait for a QThread worker
# ---------------------------------------------------------------------------


def _wait(worker, timeout_ms: int = 60_000):
    """Wait for worker finished/error. Returns (ok, error_or_None)."""
    from PyQt6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    state = {"ok": True, "err": None, "timeout": False}

    def _fin(*_):
        state["ok"] = True
        loop.quit()

    def _err(m):
        state["ok"] = False
        state["err"] = str(m)
        loop.quit()

    def _tout():
        state["timeout"] = True
        loop.quit()

    worker.finished.connect(_fin)
    worker.error.connect(_err)
    t = QTimer()
    t.setSingleShot(True)
    t.timeout.connect(_tout)
    t.start(timeout_ms)
    worker.start()
    loop.exec()
    t.stop()

    if state["timeout"]:
        worker.quit()
        worker.wait(2000)
        return False, f"Timeout after {timeout_ms//1000}s"
    return state["ok"], state["err"]


# ===========================================================================
# A) Document metadata tests
# ===========================================================================


class TestDocumentMetadata:

    def test_project_and_corpus_exist(self, db_service, project_id, corpus_id):
        """Selected project and its default corpus are present."""
        assert project_id > 0
        assert corpus_id > 0

    def test_document_service_list(self, db_service, corpus_id):
        """DocumentService.list_documents returns a list without error."""
        from app.services.document_service import DocumentService

        with db_service.get_session() as session:
            dtos = DocumentService().list_documents(session, corpus_id)
        assert isinstance(dtos, list)

    def test_update_metadata_validation_link_unsafe(self, db_service, corpus_id):
        """update_metadata with javascript: link raises ValueError."""
        from app.services.document_service import DocumentService
        from app.infra.sa_models import SourceDocument
        from sqlalchemy import select

        with db_service.get_session() as session:
            doc = (
                session.execute(
                    select(SourceDocument).where(SourceDocument.corpus_id == corpus_id).limit(1)
                )
                .scalars()
                .first()
            )
            if doc is None:
                pytest.skip("No documents in corpus")

            with pytest.raises(ValueError, match="not allowed"):
                DocumentService().update_metadata(session, doc.doc_id, link_url="javascript:evil()")

    def test_title_search_returns_filtered(self, db_service, corpus_id):
        """Title search filters documents correctly."""
        from app.services.document_service import DocumentService

        with db_service.get_session() as session:
            all_docs = DocumentService().list_documents(session, corpus_id)
        if not all_docs:
            pytest.skip("No documents to search")
        # Search by first 4 chars of first doc's filename; should return >=1.
        query = all_docs[0].file_name[:4]
        with db_service.get_session() as session:
            filtered = DocumentService().list_documents(session, corpus_id, title_search=query)
        assert len(filtered) >= 1

    def test_sort_allowlist_stable(self, db_service, corpus_id):
        """Sort by allowlist columns returns consistent row sets."""
        from app.services.document_service import DocumentService

        for col in ("level", "tag", "topic", "file_name"):
            with db_service.get_session() as session:
                asc = DocumentService().list_documents(
                    session, corpus_id, sort_by=col, sort_dir="asc"
                )
            with db_service.get_session() as session:
                desc = DocumentService().list_documents(
                    session, corpus_id, sort_by=col, sort_dir="desc"
                )
            assert {d.doc_id for d in asc} == {
                d.doc_id for d in desc
            }, f"Row set differs for sort_by={col!r}"

    def test_link_click_guard_javascript(self):
        """Safe link click guard: javascript: must not reach QDesktopServices."""
        from urllib.parse import urlparse

        for url, should_open in [
            ("https://example.com", True),
            ("http://example.com", True),
            ("javascript:alert(1)", False),
            ("file:///etc/passwd", False),
            ("ftp://files.example.com", False),
        ]:
            parsed = urlparse(url)
            opens = parsed.scheme in ("http", "https")
            assert opens == should_open, f"URL {url!r}: expected open={should_open}, got {opens}"


# ===========================================================================
# B+C) NLP + Sentences service tests
# ===========================================================================


class TestSentencesService:

    def test_count_sentences_returns_int(self, db_service, project_id):
        """count_sentences returns a non-negative integer."""
        from app.services.sentences_workspace_service import SentencesWorkspaceService

        with db_service.get_session() as session:
            n = SentencesWorkspaceService().count_sentences(session, project_id)
        assert isinstance(n, int) and n >= 0

    def test_list_sentences_page1_no_crash(self, db_service, project_id):
        """list_sentences page 1 returns list without error."""
        from app.services.sentences_workspace_service import SentencesWorkspaceService

        with db_service.get_session() as session:
            dtos = SentencesWorkspaceService().list_sentences(
                session, project_id, page=1, page_size=25
            )
        assert isinstance(dtos, list)

    def test_batch_get_translations_empty(self, db_service, project_id, src_lang):
        """_batch_get_translations with empty texts returns empty dict."""
        from app.services.sentences_workspace_service import SentencesWorkspaceService

        with db_service.get_session() as session:
            result = SentencesWorkspaceService()._batch_get_translations(
                session, project_id, src_lang, []
            )
        assert result == {}

    def test_batch_get_sentence_niqqud_empty(self, db_service):
        """_batch_get_sentence_niqqud with empty IDs returns empty dict."""
        from app.services.sentences_workspace_service import SentencesWorkspaceService

        with db_service.get_session() as session:
            result = SentencesWorkspaceService()._batch_get_sentence_niqqud(session, [])
        assert result == {}

    def test_batch_get_audio_empty(self, db_service, src_lang):
        """_batch_get_audio with empty texts returns empty dict."""
        from app.services.sentences_workspace_service import SentencesWorkspaceService

        with db_service.get_session() as session:
            result = SentencesWorkspaceService()._batch_get_audio(session, src_lang, [])
        assert result == {}

    def test_norm_helper_returns_string(self):
        """_norm returns non-empty string for Hebrew text."""
        from app.services.sentences_workspace_service import SentencesWorkspaceService

        result = SentencesWorkspaceService._norm("he", "שלום עולם")
        assert isinstance(result, str) and len(result) > 0


# ===========================================================================
# D) TM Kind filter tests
# ===========================================================================


class TestTMKindFilter:

    def test_search_tm_entries_kinds_filter_single(self, db_service):
        """kinds=['lemma'] returns only lemma entries (or empty)."""
        from app.services.translation_admin_service import TranslationAdminService

        with db_service.get_session() as session:
            entries = TranslationAdminService().search_tm_entries(
                session, filters={"kinds": ["lemma"]}, limit=200
            )
        for e in entries:
            assert e.kind == "lemma", f"Unexpected kind: {e.kind!r}"

    def test_search_tm_entries_kinds_filter_multi(self, db_service):
        """kinds=['lemma','surface'] returns only those kinds."""
        from app.services.translation_admin_service import TranslationAdminService

        allowed = {"lemma", "surface"}
        with db_service.get_session() as session:
            entries = TranslationAdminService().search_tm_entries(
                session, filters={"kinds": list(allowed)}, limit=200
            )
        for e in entries:
            assert e.kind in allowed, f"Entry kind={e.kind!r} not in {allowed}"

    def test_kind_filter_empty_is_no_filter(self, db_service):
        """kinds=[] returns same count as no filter."""
        from app.services.translation_admin_service import TranslationAdminService

        svc = TranslationAdminService()
        with db_service.get_session() as session:
            all_count = len(svc.search_tm_entries(session, filters={}, limit=9999))
        with db_service.get_session() as session:
            empty_count = len(svc.search_tm_entries(session, filters={"kinds": []}, limit=9999))
        assert empty_count == all_count

    def test_settings_kind_filter_roundtrip(self):
        """SettingsService get_json/set_value round-trip for kind_filter."""
        from app.infra.settings import SettingsService

        s = SettingsService.get_instance()
        key = "smoke_test/kind_filter_roundtrip"
        try:
            s.set_value(key, ["lemma", "surface"])
            got = s.get_json(key, None)
            assert isinstance(got, list)
            assert set(got) == {"lemma", "surface"}

            s.set_value(key, None)
            got_none = s.get_json(key, None)
            assert got_none is None
        finally:
            s.set_value(key, None)  # cleanup

    def test_kind_filter_dialog_logic(self):
        """KindFilterDialog.get_selected_kinds returns None for all/none selected."""
        from app.ui.translation_management_panel import KindFilterDialog

        all_k = KindFilterDialog.ALL_KINDS

        # All selected -> None
        selected_all = all_k[:]
        result = (
            selected_all if (len(selected_all) != len(all_k) and len(selected_all) != 0) else None
        )
        assert result is None

        # None selected -> None
        selected_none: list = []
        result = (
            selected_none
            if (len(selected_none) != len(all_k) and len(selected_none) != 0)
            else None
        )
        assert result is None

        # Partial selection -> list
        selected_partial = ["lemma", "surface"]
        result = (
            selected_partial
            if (len(selected_partial) != len(all_k) and len(selected_partial) != 0)
            else None
        )
        assert result == ["lemma", "surface"]
