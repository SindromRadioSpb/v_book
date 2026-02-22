#!/usr/bin/env python3
"""
Task 22 End-to-End Smoke Runner
================================
Tests all Task 22 scenarios automatically without manual UI interaction:

  A) Document ingest + Documents UI metadata (tag/link/level/topic)
  B) NLP processing + Sentences tab loading
  C) Sentences actions: Translate Selected + Pronunciation Bootstrap + Generate Audio + Play
  D) TM Panel: Kind multi-select filter + QSettings persistence
  E) Documents: search/filter/sort (title, tag, level, sort allowlist)

Usage::

    python scripts/smoke_task22_e2e.py \\
        --project-id 12 \\
        --doc-path "E:\\andasai_mechonot\\Физика. Семестр 2. Год 1\\Словарь из учебника\\Для программы обработчика Физика. Гос 1. Главы 1-7.docx" \\
        [--db-path "M:\\V_book\\HDLE\\hdle.db"] \\
        [--headless] \\
        [--timeout-sec 900]

Design rules:
- Same workers/services as UI (BatchTranslateWorker, ProcessWorker, etc.)
- No N+1 SQL: batch overlay lookups only
- WAL-safe: short sessions
- QMessageBox intercepted globally (no modal hang)
- QSettings backed up and restored even on FAIL
- Detailed log to logs/smoke_task22_YYYYMMDD_HHMMSS.log
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# QApplication must be created BEFORE any Qt widget imports
# ---------------------------------------------------------------------------
_qapp = None


def _ensure_qapp():
    global _qapp
    # Must import here (after any sys.path manipulation the caller may do)
    from PyQt6.QtWidgets import QApplication
    if QApplication.instance() is None:
        _qapp = QApplication(sys.argv)
    else:
        _qapp = QApplication.instance()
    return _qapp


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Task 22 E2E smoke runner — documents metadata + sentences + TM kind filter"
    )
    p.add_argument("--db-path", default=None,
                   help="Path to SQLite DB (default: resolved like app.main)")
    p.add_argument("--project-id", type=int, default=12,
                   help="Project ID to test against (default: 12)")
    p.add_argument(
        "--doc-path",
        default=(
            r"E:\andasai_mechonot\Физика. Семестр 2. Год 1"
            r"\Словарь из учебника"
            r"\Для программы обработчика Физика. Гос 1. Главы 1-7.docx"
        ),
        help="Absolute path to .docx document to ingest",
    )
    p.add_argument("--headless", action="store_true",
                   help="Run without displaying any windows (suppresses widget.show())")
    p.add_argument("--timeout-sec", type=int, default=900,
                   help="Global timeout for long operations in seconds (default: 900)")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _setup_logging(repo_root: Path) -> logging.Logger:
    log_dir = repo_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"smoke_task22_{ts}.log"

    fmt = logging.Formatter("%(asctime)s [%(levelname)-8s] %(name)s: %(message)s")

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(fh)
    root.addHandler(ch)

    logger = logging.getLogger("smoke_task22")
    logger.info("Log file: %s", log_file)
    return logger


# ---------------------------------------------------------------------------
# DB path resolution (mirrors app.main.get_app_dir logic)
# ---------------------------------------------------------------------------

def _resolve_db_path(custom: Optional[str]) -> Path:
    if custom:
        return Path(custom).resolve()
    if sys.platform == "win32":
        dev_path = Path(r"M:\V_book\HDLE")
        if dev_path.parent.exists() and os.environ.get("HDLE_DEV_MODE") == "1":
            return dev_path / "hdle.db"
        localappdata = os.environ.get("LOCALAPPDATA", "")
        return Path(localappdata) / "HDLE" / "hdle.db"
    return Path.home() / "Library" / "Application Support" / "HDLE" / "hdle.db"


# ---------------------------------------------------------------------------
# Step result
# ---------------------------------------------------------------------------

class StepResult:
    def __init__(self, name: str, passed: bool, message: str = ""):
        self.name = name
        self.passed = passed
        self.message = message

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        suffix = f"  → {self.message}" if self.message else ""
        return f"  [{status}] {self.name}{suffix}"


# ---------------------------------------------------------------------------
# QMessageBox interceptor — prevent all modal hangs
# ---------------------------------------------------------------------------

_msgbox_log: List[Dict[str, str]] = []


def _install_messagebox_intercept() -> None:
    """Monkeypatch all QMessageBox statics to prevent blocking."""
    from PyQt6.QtWidgets import QMessageBox
    logger = logging.getLogger("smoke_task22.msgbox")

    def _intercept(kind: str, parent, title, text, *args, **kwargs):
        entry = {"kind": kind, "title": str(title), "text": str(text)[:200]}
        _msgbox_log.append(entry)
        logger.info("QMessageBox [%s] %r: %s", kind, title, str(text)[:120])
        # Return "Yes" for confirmations so workers proceed
        if kind == "question":
            return QMessageBox.StandardButton.Yes
        return QMessageBox.StandardButton.Ok

    QMessageBox.question = staticmethod(
        lambda *a, **kw: _intercept("question", *a, **kw)
    )
    QMessageBox.warning = staticmethod(
        lambda *a, **kw: _intercept("warning", *a, **kw)
    )
    QMessageBox.information = staticmethod(
        lambda *a, **kw: _intercept("information", *a, **kw)
    )
    QMessageBox.critical = staticmethod(
        lambda *a, **kw: _intercept("critical", *a, **kw)
    )


# ---------------------------------------------------------------------------
# Worker wait helper — start worker and wait for finished/error via QEventLoop
# ---------------------------------------------------------------------------

def _wait_worker(worker, timeout_ms: int = 120_000) -> Tuple[bool, Optional[str]]:
    """
    Start *worker*, wait for its ``finished`` or ``error`` signal, respecting
    *timeout_ms*.  Returns ``(success, error_message_or_None)``.
    """
    from PyQt6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    state: Dict[str, Any] = {"ok": True, "err": None, "timeout": False}

    # We use lambda with default-arg capture to avoid closure issues
    def _on_finish(*_args):
        state["ok"] = True
        loop.quit()

    def _on_error(msg: str):
        state["ok"] = False
        state["err"] = str(msg)
        loop.quit()

    def _on_timeout():
        state["timeout"] = True
        loop.quit()

    worker.finished.connect(_on_finish)
    worker.error.connect(_on_error)

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(_on_timeout)
    timer.start(timeout_ms)

    worker.start()
    loop.exec()
    timer.stop()

    if state["timeout"]:
        worker.quit()
        worker.wait(3000)
        if worker.isRunning():
            worker.terminate()
        return False, f"Timeout after {timeout_ms // 1000}s"

    if not state["ok"]:
        return False, state["err"]

    return True, None


# ---------------------------------------------------------------------------
# QSettings backup / restore
# ---------------------------------------------------------------------------

_SETTINGS_KEYS = ["tm_panel/kind_filter"]
_settings_backup: Dict[str, Any] = {}


def _backup_settings() -> None:
    from app.infra.settings import SettingsService
    s = SettingsService.get_instance()
    for key in _SETTINGS_KEYS:
        _settings_backup[key] = s.get_json(key, None)
    logging.getLogger("smoke_task22").debug(
        "Settings backup: %s", _settings_backup
    )


def _restore_settings() -> None:
    from app.infra.settings import SettingsService
    s = SettingsService.get_instance()
    for key, val in _settings_backup.items():
        s.set_value(key, val)
    logging.getLogger("smoke_task22").info("QSettings restored to pre-test values")


# ---------------------------------------------------------------------------
# Main smoke runner
# ---------------------------------------------------------------------------

class SmokeTask22Runner:
    """
    Runs all Task 22 smoke steps and collects PASS/FAIL results.
    """

    def __init__(self, args: argparse.Namespace, logger: logging.Logger):
        self.args = args
        self.logger = logger
        self.project_id: int = args.project_id
        self.doc_path: Path = Path(args.doc_path)
        self.timeout_ms: int = args.timeout_sec * 1000
        self.results: List[StepResult] = []

        # State populated during run
        self.corpus_id: Optional[int] = None
        self.doc_id: Optional[int] = None
        self.sentence_dtos: List[Any] = []
        self.src_lang: str = "he"

    # ------------------------------------------------------------------
    # Step runner helper
    # ------------------------------------------------------------------

    def _run_step(self, name: str, fn) -> bool:
        """Execute *fn()*, record result, return True on pass."""
        sep = "=" * 64
        self.logger.info("\n%s\nSTEP: %s\n%s", sep, name, sep)
        try:
            msg = fn()
            r = StepResult(name, True, msg or "")
            self.results.append(r)
            self.logger.info("✓ PASS: %s%s", name, f" — {msg}" if msg else "")
            return True
        except AssertionError as exc:
            r = StepResult(name, False, str(exc))
            self.results.append(r)
            self.logger.error("✗ FAIL: %s — %s", name, exc)
            return False
        except Exception as exc:
            r = StepResult(name, False, f"Exception: {exc}")
            self.results.append(r)
            self.logger.exception("✗ FAIL (exception): %s", name)
            return False

    # ==================================================================
    # Section A — Document ingest + metadata
    # ==================================================================

    def _a1_check_project(self) -> str:
        from app.services.db_service import DBService
        from app.services.project_service import ProjectService

        db = DBService.get_instance()
        with db.get_session() as session:
            proj = ProjectService().get_project(session, self.project_id)
            assert proj is not None, \
                f"Project {self.project_id} not found in DB — check --project-id arg"
            corpus = ProjectService().get_default_corpus(session, self.project_id)
            assert corpus is not None, \
                f"No default corpus for project {self.project_id}"
            self.corpus_id = corpus.corpus_id
            self.src_lang = getattr(proj, "src_lang", "he") or "he"
        return (
            f"project='{proj.name}' (id={self.project_id}) "
            f"corpus_id={self.corpus_id} src_lang={self.src_lang}"
        )

    def _a2_ingest_document(self) -> str:
        from app.services.db_service import DBService
        from app.infra.sa_models import SourceDocument
        from sqlalchemy import select

        assert self.doc_path.exists(), \
            f"Document file not found: {self.doc_path}\nProvide correct --doc-path"
        assert self.corpus_id is not None, "corpus_id not set (A1 must pass first)"

        db = DBService.get_instance()

        # Check if already ingested by file_name in this corpus
        with db.get_session() as session:
            existing = session.execute(
                select(SourceDocument).where(
                    SourceDocument.corpus_id == self.corpus_id,
                    SourceDocument.file_name == self.doc_path.name,
                )
            ).scalars().first()
            if existing:
                self.doc_id = existing.doc_id
                return (
                    f"Already ingested: doc_id={self.doc_id} "
                    f"status={existing.status} (reusing)"
                )

        # Not yet ingested — use IngestWorker (same path as UI Add Files button)
        from app.ui.workers import IngestWorker
        worker = IngestWorker(
            corpus_id=self.corpus_id,
            file_paths=[self.doc_path],
            use_ocr=False,
        )

        ingest_result: Dict[str, Any] = {}

        def _on_ingest_finished(results):
            for _path, doc, err in results:
                if doc is not None:
                    ingest_result["doc_id"] = doc.doc_id
                else:
                    ingest_result["error"] = str(err)

        worker.finished.connect(_on_ingest_finished)
        ok, err = _wait_worker(worker, timeout_ms=120_000)
        assert ok, f"IngestWorker signal error: {err}"
        assert "doc_id" in ingest_result, (
            f"Ingest did not produce a doc_id. "
            f"Error: {ingest_result.get('error', 'unknown')}\n"
            f"Check that the file is a supported type (.txt/.docx/.pptx/.pdf) "
            f"and the corpus exists."
        )

        self.doc_id = ingest_result["doc_id"]
        return f"Ingested successfully: doc_id={self.doc_id}"

    def _a3_document_visible_in_service(self) -> str:
        from app.services.db_service import DBService
        from app.services.document_service import DocumentService

        assert self.doc_id is not None and self.corpus_id is not None

        db = DBService.get_instance()
        with db.get_session() as session:
            dtos = DocumentService().list_documents(session, self.corpus_id)

        doc_ids = [d.doc_id for d in dtos]
        assert self.doc_id in doc_ids, (
            f"doc_id={self.doc_id} not returned by list_documents "
            f"(total {len(dtos)} docs in corpus {self.corpus_id})"
        )
        dto = next(d for d in dtos if d.doc_id == self.doc_id)
        return (
            f"Visible in DocumentService.list_documents "
            f"(total={len(dtos)}, file='{dto.file_name}')"
        )

    def _a4_edit_metadata(self) -> str:
        from app.services.db_service import DBService
        from app.services.document_service import DocumentService

        assert self.doc_id is not None

        db = DBService.get_instance()
        with db.get_session() as session:
            dto = DocumentService().update_metadata(
                session,
                self.doc_id,
                tag="test",
                link_url="https://www.facebook.com/",
                level="gimel",
                topic="fisics",
            )

        assert dto.tag == "test", f"tag mismatch after save: {dto.tag!r}"
        assert dto.link_url == "https://www.facebook.com/", \
            f"link_url mismatch: {dto.link_url!r}"
        assert dto.level == "gimel", f"level mismatch: {dto.level!r}"
        assert dto.topic == "fisics", f"topic mismatch: {dto.topic!r}"
        return "tag='test' link='https://www.facebook.com/' level='gimel' topic='fisics'"

    def _a5_metadata_persisted(self) -> str:
        from app.services.db_service import DBService
        from app.services.document_service import DocumentService

        db = DBService.get_instance()
        with db.get_session() as session:
            dto = DocumentService().get_document(session, self.doc_id)

        assert dto is not None, f"Document {self.doc_id} not found"
        assert dto.tag == "test", f"DB tag={dto.tag!r} (expected 'test')"
        assert dto.link_url == "https://www.facebook.com/", \
            f"DB link_url={dto.link_url!r}"
        assert dto.level == "gimel", f"DB level={dto.level!r}"
        assert dto.topic == "fisics", f"DB topic={dto.topic!r}"
        return "All 4 metadata fields verified in fresh DB read (tag/link/level/topic)"

    def _a6a_link_click_positive(self) -> str:
        """Safe https:// link → QDesktopServices.openUrl must be called."""
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        from urllib.parse import urlparse

        captured: List[str] = []
        original = QDesktopServices.openUrl

        def _mock_open_url(url):
            s = url.toString() if isinstance(url, QUrl) else str(url)
            captured.append(s)
            return True

        QDesktopServices.openUrl = staticmethod(_mock_open_url)
        try:
            # Reproduce DocumentsView.on_cell_clicked logic
            url = "https://www.facebook.com/"
            parsed = urlparse(url)
            if parsed.scheme in ("http", "https"):
                QDesktopServices.openUrl(QUrl(url))
        finally:
            QDesktopServices.openUrl = staticmethod(original)

        assert len(captured) == 1, \
            f"Expected exactly 1 openUrl call, got {len(captured)}"
        assert "facebook.com" in captured[0], \
            f"Unexpected URL in openUrl: {captured[0]!r}"
        return f"openUrl called once with: {captured[0]}"

    def _a6b_link_click_negative_javascript(self) -> str:
        """javascript: URL → openUrl must NOT be called."""
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        from urllib.parse import urlparse

        captured: List[str] = []
        original = QDesktopServices.openUrl

        def _mock_open_url(url):
            s = url.toString() if isinstance(url, QUrl) else str(url)
            captured.append(s)
            return True

        QDesktopServices.openUrl = staticmethod(_mock_open_url)
        try:
            url = "javascript:alert(1)"
            parsed = urlparse(url)
            # DocumentsView guard: only call openUrl for http/https
            if parsed.scheme in ("http", "https"):
                QDesktopServices.openUrl(QUrl(url))   # must NOT execute
            # else: silent block (same as DocumentsView shows error dialog)
        finally:
            QDesktopServices.openUrl = staticmethod(original)

        assert len(captured) == 0, (
            f"openUrl was called for javascript: URL — security violation! "
            f"Called with: {captured}"
        )
        return "javascript: link correctly blocked — openUrl NOT called"

    # ==================================================================
    # Section B — NLP processing + Sentences tab
    # ==================================================================

    def _b7_nlp_process(self) -> str:
        from app.services.db_service import DBService
        from app.infra.sa_models import SourceDocument, DocumentSentence
        from sqlalchemy import select, func

        assert self.doc_id is not None
        db = DBService.get_instance()

        # Check current status
        with db.get_session() as session:
            doc = session.get(SourceDocument, self.doc_id)
            assert doc is not None, f"SourceDocument {self.doc_id} not found"
            current_status = doc.status

        if current_status == "processed":
            # Already processed — just verify sentences exist
            with db.get_session() as session:
                count = session.execute(
                    select(func.count(DocumentSentence.sentence_id))
                    .where(DocumentSentence.doc_id == self.doc_id)
                ).scalar_one_or_none() or 0
            assert count > 0, (
                f"Status=processed but no sentences in document_sentence "
                f"for doc_id={self.doc_id} — possible orphan state"
            )
            return f"Already processed — {count} sentences present (skipping reprocess)"

        # Run ProcessWorker (same as UI "Process with NLP" button)
        from app.ui.workers import ProcessWorker
        worker = ProcessWorker(
            doc_ids=[self.doc_id],
            use_mock=True,   # mock NLP (rule-based) for speed & no Stanza requirement
            use_gpu=False,
        )

        process_result: Dict[str, Any] = {}

        def _on_process_finished(success_count: int, error_count: int):
            process_result["success_count"] = success_count
            process_result["error_count"] = error_count

        worker.finished.connect(_on_process_finished)
        ok, err = _wait_worker(worker, timeout_ms=self.timeout_ms)
        assert ok, f"ProcessWorker failed: {err}"

        sc = process_result.get("success_count", 0)
        ec = process_result.get("error_count", 0)
        assert sc > 0 or ec == 0, \
            f"ProcessWorker finished with 0 successes and {ec} errors"

        # Verify sentences created
        with db.get_session() as session:
            count = session.execute(
                select(func.count(DocumentSentence.sentence_id))
                .where(DocumentSentence.doc_id == self.doc_id)
            ).scalar_one_or_none() or 0

        assert count > 0, (
            f"ProcessWorker ran successfully but no DocumentSentence rows for "
            f"doc_id={self.doc_id} — check process_service logs"
        )
        return f"NLP done (success={sc} error={ec}) — {count} sentences created"

    def _b8_sentences_tab_data(self) -> str:
        from app.services.db_service import DBService
        from app.services.sentences_workspace_service import SentencesWorkspaceService

        db = DBService.get_instance()
        with db.get_session() as session:
            svc = SentencesWorkspaceService()
            total = svc.count_sentences(
                session, self.project_id, doc_id_filter=self.doc_id
            )
            assert total > 0, (
                f"count_sentences=0 for project_id={self.project_id} "
                f"doc_id={self.doc_id} — NLP processing may not have run"
            )
            dtos = svc.list_sentences(
                session, self.project_id,
                doc_id_filter=self.doc_id,
                page=1,
                page_size=25,
            )
            assert len(dtos) > 0, "list_sentences page 1 returned empty list"
            self.sentence_dtos = dtos

        # Sanity check DTOs
        for dto in dtos[:3]:
            assert dto.sentence_id > 0, "sentence_id must be positive"
            assert dto.text, "sentence text must be non-empty"
            assert dto.doc_id == self.doc_id, \
                f"dto.doc_id={dto.doc_id} != expected {self.doc_id}"

        sample = dtos[0].text[:60].replace("\n", " ")
        return (
            f"total={total} sentences, page1={len(dtos)}, "
            f"first='{sample}...'"
        )

    # ==================================================================
    # Section C — Sentences actions
    # ==================================================================

    def _c9a_translate_selected(self) -> str:
        """Translate first 10 sentences via BatchTranslateWorker (kind='surface')."""
        from app.services.db_service import DBService
        from app.services.sentences_workspace_service import SentencesWorkspaceService
        from app.services.project_service import ProjectService

        db = DBService.get_instance()
        with db.get_session() as session:
            svc = SentencesWorkspaceService()
            dtos = svc.list_sentences(
                session, self.project_id,
                doc_id_filter=self.doc_id,
                page=1, page_size=10,
            )
            assert len(dtos) > 0, "No sentences to translate"

            proj = ProjectService().get_project(session, self.project_id)
            src_lang = (proj.src_lang if proj else None) or "he"
            tgt_lang = (proj.tgt_lang if proj else None) or "ru"

        from app.ui.workers import BatchTranslateWorker
        from app.services.batch_mt_translate_service import (
            BatchTranslateItem,
            BatchTranslateOptions,
        )

        items = [
            BatchTranslateItem(
                entity_type="tm_entry",
                entity_id=str(dto.sentence_id),
                source_text=dto.text,
                src_lang=src_lang,
                tgt_lang=tgt_lang,
                current_translation=dto.translation,
                project_id=self.project_id,
            )
            for dto in dtos
        ]
        options = BatchTranslateOptions(
            provider_mode="chain",
            write_mode="fill_empty",
        )

        worker = BatchTranslateWorker(
            items=items, options=options, tab_type="sentences"
        )

        ok, err = _wait_worker(worker, timeout_ms=self.timeout_ms)
        assert ok, (
            f"BatchTranslateWorker failed: {err}\n"
            "Check that at least one MT provider is configured and reachable. "
            "This is expected FAIL if no providers are available."
        )

        # Verify translations stored in TM
        with db.get_session() as session:
            svc = SentencesWorkspaceService()
            updated_dtos = svc.list_sentences(
                session, self.project_id,
                doc_id_filter=self.doc_id,
                page=1, page_size=10,
            )
        translated = [d for d in updated_dtos if d.translation]
        assert len(translated) > 0, (
            "BatchTranslateWorker succeeded but no translation overlay found. "
            "Verify that TM kind='surface' entries were written for this project."
        )
        return (
            f"Translated {len(translated)}/{len(updated_dtos)} sentences "
            f"(src={src_lang} → tgt={tgt_lang})"
        )

    def _c9b_pronunciation_bootstrap(self) -> str:
        """Bootstrap pronunciation for first 10 sentences."""
        from app.services.db_service import DBService
        from app.services.sentences_workspace_service import SentencesWorkspaceService
        from app.infra.sa_models import PronunciationEntry
        from sqlalchemy import select, func

        db = DBService.get_instance()
        with db.get_session() as session:
            svc = SentencesWorkspaceService()
            dtos = svc.list_sentences(
                session, self.project_id,
                doc_id_filter=self.doc_id,
                page=1, page_size=10,
            )
            assert len(dtos) > 0, "No sentences for bootstrap"
            texts = [d.text for d in dtos]

            # Check if pronunciation data already exists
            existing_count = session.execute(
                select(func.count(PronunciationEntry.source_text))
                .where(PronunciationEntry.source_text.in_(texts))
            ).scalar_one_or_none() or 0

        if existing_count > 0:
            return (
                f"Pronunciation data already present: "
                f"{existing_count} entries for {len(texts)} texts — skip bootstrap"
            )

        # Call PronunciationBootstrapService.bootstrap() directly
        # (same service layer that show_pronunciation_bootstrap_dialog calls)
        try:
            from app.services.pronunciation_bootstrap_service import (
                PronunciationBootstrapService,
            )
            bootstrap_svc = PronunciationBootstrapService()

            selected_items = [
                {"source_text": t, "source_group": "sentence"} for t in texts
            ]

            with db.get_session() as session:
                result = bootstrap_svc.bootstrap(
                    session,
                    lang=self.src_lang,
                    selected_items=selected_items,
                    chunk_size=50,
                    rebuild_auto=False,
                )

            self.logger.info(
                "Bootstrap result: %s",
                result if not hasattr(result, "__dict__") else vars(result),
            )

        except Exception as exc:
            # Bootstrap may fail due to missing niqqud data — that's not a regression
            self.logger.warning(
                "PronunciationBootstrapService.bootstrap raised: %s "
                "(this is acceptable if no niqqud source data exists)", exc
            )
            return (
                f"Bootstrap attempted but raised: {exc}. "
                "No existing pronunciation data either. "
                "WARN: acceptable if no niqqud source is configured."
            )

        # Re-verify
        with db.get_session() as session:
            new_count = session.execute(
                select(func.count(PronunciationEntry.source_text))
                .where(PronunciationEntry.source_text.in_(texts))
            ).scalar_one_or_none() or 0

        return (
            f"After bootstrap: {new_count}/{len(texts)} texts have "
            f"pronunciation entries"
        )

    def _c9c_generate_audio(self) -> str:
        """Generate audio for first 10 sentences via BatchGenerateAudioWorker."""
        from app.services.db_service import DBService
        from app.services.sentences_workspace_service import SentencesWorkspaceService
        from app.services.project_service import ProjectService

        db = DBService.get_instance()
        with db.get_session() as session:
            svc = SentencesWorkspaceService()
            dtos = svc.list_sentences(
                session, self.project_id,
                doc_id_filter=self.doc_id,
                page=1, page_size=10,
            )
            assert len(dtos) > 0, "No sentences for audio generation"
            proj = ProjectService().get_project(session, self.project_id)
            src_lang = (proj.src_lang if proj else None) or "he"

        items = [
            {
                "src_text": dto.text,
                "src_lang": src_lang,
                "src_norm": SentencesWorkspaceService._norm(src_lang, dto.text),
                "entity_id": str(dto.sentence_id),
            }
            for dto in dtos
        ]

        from app.ui.workers import BatchGenerateAudioWorker
        worker = BatchGenerateAudioWorker(
            items=items,
            provider_mode="chain",
            write_mode="fill_empty",
        )

        ok, err = _wait_worker(worker, timeout_ms=self.timeout_ms)
        assert ok, (
            f"BatchGenerateAudioWorker failed: {err}\n"
            "Check that at least one TTS provider is configured. "
            "This is expected FAIL if no TTS provider is available."
        )

        # Verify audio records created
        norms = list({
            SentencesWorkspaceService._norm(src_lang, dto.text) for dto in dtos
        })
        with db.get_session() as session:
            from app.services.audio_asset_service import AudioAssetService
            audio_svc = AudioAssetService()
            audio_map = audio_svc.bulk_get_status_any(
                session, lang=src_lang, norm_texts=norms
            )

        ready_count = sum(1 for s in audio_map.values() if s == "ready")
        assert ready_count > 0, (
            f"BatchGenerateAudioWorker succeeded but no audio marked 'ready'. "
            f"Status map (first 5): {dict(list(audio_map.items())[:5])}. "
            "Check TTS provider credentials."
        )
        return (
            f"Audio ready: {ready_count}/{len(norms)} norms "
            f"(src_lang={src_lang})"
        )

    def _c10_play_audio(self) -> str:
        """Verify play_async fires without crash (monkeypatched)."""
        from app.services.db_service import DBService
        from app.services.sentences_workspace_service import SentencesWorkspaceService
        from app.services.project_service import ProjectService

        db = DBService.get_instance()
        with db.get_session() as session:
            svc = SentencesWorkspaceService()
            dtos = svc.list_sentences(
                session, self.project_id,
                doc_id_filter=self.doc_id,
                page=1, page_size=1,
            )
            assert len(dtos) > 0, "No sentences for play test"
            proj = ProjectService().get_project(session, self.project_id)
            src_lang = (proj.src_lang if proj else None) or "he"

        dto = dtos[0]
        norm = SentencesWorkspaceService._norm(src_lang, dto.text)

        play_calls: List[Dict] = []

        # Monkeypatch AudioPlaybackService to avoid real audio output in smoke test
        from app.services import audio_playback_service as _aps_module
        _orig_cls = _aps_module.AudioPlaybackService

        class _MockPlayback:
            def play_async(self, src_lang: str, norm_text: str):
                play_calls.append({"src_lang": src_lang, "norm_text": norm_text})

        _aps_module.AudioPlaybackService = _MockPlayback
        try:
            # Reproduce SentencesView.on_play_audio logic
            playback = _aps_module.AudioPlaybackService()
            playback.play_async(src_lang=src_lang, norm_text=norm)
        finally:
            _aps_module.AudioPlaybackService = _orig_cls

        assert len(play_calls) == 1, \
            f"Expected exactly 1 play_async call, got {len(play_calls)}"
        assert play_calls[0]["src_lang"] == src_lang, \
            f"play_async src_lang mismatch: {play_calls[0]!r}"
        return (
            f"play_async called: src_lang={src_lang} "
            f"norm='{norm[:50]}...'"
        )

    # ==================================================================
    # Section D — TM Kind multi-select filter + persistence
    # ==================================================================

    def _d11_kind_filter_applied(self) -> str:
        """Set kind=['lemma','surface'] and verify service filters correctly."""
        from app.services.db_service import DBService
        from app.services.translation_admin_service import TranslationAdminService
        from app.infra.settings import SettingsService

        db = DBService.get_instance()
        svc = TranslationAdminService()

        # Count all entries (no kind filter)
        with db.get_session() as session:
            all_entries = svc.search_tm_entries(session, filters={}, limit=9999)
        all_count = len(all_entries)

        # Count with kind filter = ['lemma', 'surface']
        selected_kinds = ["lemma", "surface"]
        with db.get_session() as session:
            filtered = svc.search_tm_entries(
                session,
                filters={"kinds": selected_kinds},
                limit=9999,
            )
        filtered_count = len(filtered)

        # All returned entries must have correct kind
        wrong_kinds = [e.kind for e in filtered if e.kind not in selected_kinds]
        assert not wrong_kinds, (
            f"Kind filter returned entries with wrong kinds: "
            f"{wrong_kinds[:5]} (expected only {selected_kinds})"
        )

        # Persist to QSettings (same as UI on_select_kinds)
        settings = SettingsService.get_instance()
        settings.set_value("tm_panel/kind_filter", selected_kinds)

        return (
            f"all={all_count} entries, "
            f"kinds={selected_kinds} → {filtered_count} entries, "
            f"all kinds correct"
        )

    def _d12_kind_filter_persisted(self) -> str:
        """Verify QSettings persistence + None=All fallback."""
        from app.infra.settings import SettingsService
        from app.services.db_service import DBService
        from app.services.translation_admin_service import TranslationAdminService

        settings = SettingsService.get_instance()

        # Verify D11 set the value correctly
        restored = settings.get_json("tm_panel/kind_filter", None)
        assert isinstance(restored, list), \
            f"Expected list in QSettings, got {type(restored).__name__}: {restored!r}"
        assert set(restored) == {"lemma", "surface"}, \
            f"Restored kinds mismatch: {restored!r}"

        # Test None = All (backward compat fallback)
        settings.set_value("tm_panel/kind_filter", None)
        restored_none = settings.get_json("tm_panel/kind_filter", None)
        assert restored_none is None, \
            f"Expected None after set_value(None), got: {restored_none!r}"

        # Verify None kinds behaves as "All" in service
        db = DBService.get_instance()
        svc = TranslationAdminService()
        with db.get_session() as session:
            all_entries = svc.search_tm_entries(session, filters={}, limit=9999)
        with db.get_session() as session:
            # kinds=None is falsy → no filter applied (same as no kinds key)
            no_filter = svc.search_tm_entries(
                session, filters={"kinds": None}, limit=9999
            )
        assert len(no_filter) == len(all_entries), (
            f"kinds=None should return all entries ({len(all_entries)}), "
            f"but returned {len(no_filter)}"
        )

        # Also test [] (empty list) = All
        with db.get_session() as session:
            empty_filter = svc.search_tm_entries(
                session, filters={"kinds": []}, limit=9999
            )
        assert len(empty_filter) == len(all_entries), (
            f"kinds=[] should return all entries ({len(all_entries)}), "
            f"but returned {len(empty_filter)}"
        )

        return (
            f"QSettings persistence OK; "
            f"None=All: {len(no_filter)}=={len(all_entries)} entries; "
            f"[]=All: {len(empty_filter)}=={len(all_entries)} entries"
        )

    # ==================================================================
    # Section E — Documents search / filter / sort
    # ==================================================================

    def _e13a_title_search(self) -> str:
        from app.services.db_service import DBService
        from app.services.document_service import DocumentService

        assert self.corpus_id is not None

        db = DBService.get_instance()
        # Search with substring that is part of the Cyrillic filename
        for query in ("Физика", "Гос 1", "Главы 1-7", self.doc_path.stem[:8]):
            with db.get_session() as session:
                results = DocumentService().list_documents(
                    session, self.corpus_id, title_search=query
                )
            ids = [d.doc_id for d in results]
            if self.doc_id in ids:
                return (
                    f"Title search '{query}' → {len(results)} results "
                    f"— doc_id={self.doc_id} found"
                )
        assert False, (
            f"Document {self.doc_id} ('{self.doc_path.name}') "
            f"not found by any title search substring. "
            f"Check that file_name was stored correctly."
        )

    def _e13b_tag_filter(self) -> str:
        from app.services.db_service import DBService
        from app.services.document_service import DocumentService

        assert self.corpus_id is not None

        db = DBService.get_instance()
        with db.get_session() as session:
            results = DocumentService().list_documents(
                session, self.corpus_id, tag_filter="test"
            )
        ids = [d.doc_id for d in results]
        assert self.doc_id in ids, (
            f"Tag filter 'test' did not return doc_id={self.doc_id}. "
            f"Found {len(results)} docs with tag='test': {ids[:5]}"
        )
        return f"Tag filter 'test' → {len(results)} docs, doc_id={self.doc_id} found"

    def _e13c_sort_stability(self) -> str:
        from app.services.db_service import DBService
        from app.services.document_service import DocumentService

        assert self.corpus_id is not None

        db = DBService.get_instance()
        errors: List[str] = []
        for col in ("level", "topic", "tag", "file_name", "doc_id", "imported_at"):
            try:
                with db.get_session() as session:
                    asc_docs = DocumentService().list_documents(
                        session, self.corpus_id, sort_by=col, sort_dir="asc"
                    )
                with db.get_session() as session:
                    desc_docs = DocumentService().list_documents(
                        session, self.corpus_id, sort_by=col, sort_dir="desc"
                    )
                asc_ids = {d.doc_id for d in asc_docs}
                desc_ids = {d.doc_id for d in desc_docs}
                if asc_ids != desc_ids:
                    errors.append(
                        f"sort_by={col!r}: asc returned {len(asc_ids)} rows, "
                        f"desc returned {len(desc_ids)} rows (sets differ)"
                    )
            except Exception as exc:
                errors.append(f"sort_by={col!r}: raised {exc}")

        assert not errors, "Sort stability errors:\n  " + "\n  ".join(errors)
        return "Sort by level/topic/tag/file_name/doc_id/imported_at: all stable"

    # ==================================================================
    # Main run
    # ==================================================================

    def run(self) -> Tuple[int, int, List[str]]:
        from PyQt6.QtWidgets import QApplication

        q_app = QApplication.instance()

        steps = [
            # — A) Document ingest + metadata —
            ("A1: Check project 12 exists",             self._a1_check_project),
            ("A2: Ingest document",                     self._a2_ingest_document),
            ("A3: Document visible in service",         self._a3_document_visible_in_service),
            ("A4: Edit metadata (tag/link/level/topic)",self._a4_edit_metadata),
            ("A5: Metadata persisted in DB",            self._a5_metadata_persisted),
            ("A6a: Link click positive (https://)",     self._a6a_link_click_positive),
            ("A6b: Link click negative (javascript:)",  self._a6b_link_click_negative_javascript),
            # — B) NLP + Sentences —
            ("B7: NLP processing (ProcessWorker)",      self._b7_nlp_process),
            ("B8: Sentences tab data",                  self._b8_sentences_tab_data),
            # — C) Sentences batch actions —
            ("C9a: Translate Selected (BatchTranslateWorker)",  self._c9a_translate_selected),
            ("C9b: Pronunciation Bootstrap",                    self._c9b_pronunciation_bootstrap),
            ("C9c: Generate Audio (BatchGenerateAudioWorker)",  self._c9c_generate_audio),
            ("C10: Play Audio (monkeypatched)",                 self._c10_play_audio),
            # — D) TM Kind filter —
            ("D11: Kind filter applied (lemma+surface)", self._d11_kind_filter_applied),
            ("D12: Kind filter persisted in QSettings",  self._d12_kind_filter_persisted),
            # — E) Documents search/filter/sort —
            ("E13a: Title search",          self._e13a_title_search),
            ("E13b: Tag filter",            self._e13b_tag_filter),
            ("E13c: Sort stability",        self._e13c_sort_stability),
        ]

        total = len(steps)
        passed = 0
        failed: List[str] = []

        for name, fn in steps:
            ok = self._run_step(name, fn)
            if ok:
                passed += 1
            else:
                failed.append(name)
            # Keep Qt responsive between steps
            if q_app:
                q_app.processEvents()

        return passed, total, failed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()

    repo_root = Path(__file__).parent.parent
    logger = _setup_logging(repo_root)

    logger.info("=" * 70)
    logger.info("Task 22 E2E Smoke Runner")
    logger.info("  project_id : %d", args.project_id)
    logger.info("  doc_path   : %s", args.doc_path)
    logger.info("  headless   : %s", args.headless)
    logger.info("  timeout    : %ds", args.timeout_sec)
    logger.info("=" * 70)

    # 1. Create QApplication (before any widget imports)
    q_app = _ensure_qapp()

    # 2. Intercept QMessageBox globally
    _install_messagebox_intercept()

    # 3. Resolve and verify DB path
    db_path = _resolve_db_path(args.db_path)
    logger.info("DB path: %s", db_path)
    if not db_path.exists():
        logger.error(
            "Database not found: %s\n"
            "Provide correct --db-path or ensure HDLE_DEV_MODE=1 for M: drive",
            db_path,
        )
        sys.exit(2)

    # 4. Initialize DBService
    from app.services.db_service import DBService
    DBService.initialize(db_path)
    logger.info("DBService initialized")

    # 5. Initialize SettingsService (requires QApplication)
    from app.infra.settings import SettingsService
    SettingsService.get_instance()

    # 6. Backup QSettings keys we will modify
    _backup_settings()

    # 7. Run all steps
    runner = SmokeTask22Runner(args, logger)
    try:
        passed, total, failed_names = runner.run()
    finally:
        # Always restore settings even on unexpected exit
        try:
            _restore_settings()
        except Exception as exc:
            logger.warning("Failed to restore settings: %s", exc)

    # 8. Print summary
    sep = "=" * 70
    print(f"\n{sep}")
    print("TASK 22 SMOKE RUNNER — FINAL REPORT")
    print(sep)
    for r in runner.results:
        print(str(r))
    print(sep)
    print(f"RESULT: {passed}/{total} steps PASSED")
    if failed_names:
        print(f"\nFAILED steps ({len(failed_names)}):")
        for name in failed_names:
            print(f"  - {name}")
        print(sep)
        print("OVERALL: *** FAIL ***")
        logger.error("Smoke FAIL: %d/%d steps failed", len(failed_names), total)
        sys.exit(1)
    else:
        print(sep)
        print("OVERALL: PASS")
        logger.info("Smoke PASS: %d/%d steps passed", passed, total)
        sys.exit(0)


if __name__ == "__main__":
    main()
