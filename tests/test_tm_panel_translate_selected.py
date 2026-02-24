"""Tests for TM Panel batch translate entrypoint and write-mode behavior."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.normalization.normalizer import normalize_for_tm
from app.infra.sa_models import DictProject, Library, TMEntry
from app.services.batch_mt_translate_service import (
    BatchMTTranslateService,
    BatchTranslateItem,
    BatchTranslateOptions,
)
from app.services.translation_service import TranslationResult
from app.ui.translation_management_panel import TranslationManagementPanel


@pytest.fixture
def tm_engine():
    """SQLite test DB with minimal TM schema."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        Library.__table__.create(engine, checkfirst=True)
        DictProject.__table__.create(engine, checkfirst=True)
        TMEntry.__table__.create(engine, checkfirst=True)
        yield engine
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def tm_session(tm_engine):
    """Session with one project and TM entries used by tests."""
    with Session(tm_engine) as session:
        lib = Library(name="Test Library")
        session.add(lib)
        session.flush()
        project = DictProject(library_id=lib.library_id, name="P1")
        session.add(project)
        session.flush()

        entries = [
            TMEntry(
                project_id=project.project_id,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                src_text="alpha",
                src_norm="alpha",
                translation="",
                status="approved",
                origin="import",
                is_noise=0,
            ),
            TMEntry(
                project_id=project.project_id,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                src_text="beta",
                src_norm="beta",
                translation="EXISTING",
                status="rejected",
                origin="merge",
                is_noise=1,
            ),
            TMEntry(
                project_id=project.project_id,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                src_text="gamma",
                src_norm="gamma",
                translation="",
                status="draft",
                origin="mt_auto",
                is_noise=0,
            ),
        ]
        session.add_all(entries)
        session.commit()
        yield session


def _build_items(session: Session, tm_ids: list[int]) -> list[BatchTranslateItem]:
    """Build BatchTranslateItem list for tm_entry rows."""
    items: list[BatchTranslateItem] = []
    for tm_id in tm_ids:
        entry = session.get(TMEntry, tm_id)
        items.append(
            BatchTranslateItem(
                entity_type="tm_entry",
                entity_id=str(entry.tm_id),
                source_text=entry.src_text,
                src_lang=entry.src_lang,
                tgt_lang=entry.tgt_lang,
                current_translation=entry.translation,
                project_id=entry.project_id,
            )
        )
    return items


def _run_batch(monkeypatch, session: Session, tm_ids: list[int], write_mode: str):
    """Execute batch translation with deterministic fake MT output."""
    monkeypatch.setattr(
        "app.services.tm_global_service.TMGlobalService.upsert_and_link",
        lambda self, db_session, entry: None,
    )

    def fake_resolve(
        self,
        session,
        src_text,
        kind,
        src_lang,
        tgt_lang,
        project_id,
        use_mt,
        allow_draft,
    ):
        return TranslationResult(translation=f"MT::{src_text}", source="mt_auto", confidence=1.0)

    monkeypatch.setattr(
        "app.services.translation_service.TranslationService.resolve_translation",
        fake_resolve,
    )

    service = BatchMTTranslateService()
    result = service.execute_batch(
        session=session,
        items=_build_items(session, tm_ids),
        options=BatchTranslateOptions(provider_mode="chain", write_mode=write_mode, chunk_size=50),
    )
    return result


def test_translate_selected_fill_empty_only(monkeypatch, tm_session):
    """Fill-empty mode updates only rows with empty translations."""
    tm_ids = [entry.tm_id for entry in tm_session.query(TMEntry).order_by(TMEntry.tm_id.asc()).all()]
    _run_batch(monkeypatch, tm_session, tm_ids, "FILL_EMPTY")

    rows = tm_session.query(TMEntry).order_by(TMEntry.tm_id.asc()).all()
    assert rows[0].translation == "MT::alpha"
    assert rows[1].translation == "EXISTING"
    assert rows[2].translation == "MT::gamma"


def test_translate_selected_overwrite(monkeypatch, tm_session):
    """Overwrite mode updates every selected row."""
    tm_ids = [entry.tm_id for entry in tm_session.query(TMEntry).order_by(TMEntry.tm_id.asc()).all()]
    _run_batch(monkeypatch, tm_session, tm_ids, "OVERWRITE")

    rows = tm_session.query(TMEntry).order_by(TMEntry.tm_id.asc()).all()
    assert rows[0].translation == "MT::alpha"
    assert rows[1].translation == "MT::beta"
    assert rows[2].translation == "MT::gamma"


def test_translate_selected_skip_non_empty(monkeypatch, tm_session):
    """Skip-non-empty mode keeps non-empty translations intact."""
    tm_ids = [entry.tm_id for entry in tm_session.query(TMEntry).order_by(TMEntry.tm_id.asc()).all()]
    _run_batch(monkeypatch, tm_session, tm_ids, "SKIP_NON_EMPTY")

    rows = tm_session.query(TMEntry).order_by(TMEntry.tm_id.asc()).all()
    assert rows[0].translation == "MT::alpha"
    assert rows[1].translation == "EXISTING"
    assert rows[2].translation == "MT::gamma"


def test_translate_selected_preserves_status_origin_noise_fields(monkeypatch, tm_session):
    """tm_entry write path should not reset status/origin/is_noise."""
    target = tm_session.query(TMEntry).filter(TMEntry.src_text == "beta").one()
    tm_id = target.tm_id
    before = (target.status, target.origin, target.is_noise)

    _run_batch(monkeypatch, tm_session, [tm_id], "OVERWRITE")

    updated = tm_session.get(TMEntry, tm_id)
    assert updated.translation == "MT::beta"
    assert (updated.status, updated.origin, updated.is_noise) == before


def test_tm_panel_entrypoint_uses_selected_tm_ids(monkeypatch):
    """TM panel entrypoint should pass selected tm_id list into BatchTranslateWorker."""

    class DummySignal:
        def __init__(self):
            self._callbacks = []

        def connect(self, cb):
            self._callbacks.append(cb)

    class DummyProgressDialog:
        def __init__(self, parent=None, total=0):
            self.cancel_requested = DummySignal()
            self.pause_requested = DummySignal()
            self.resume_requested = DummySignal()

        def show(self):
            return None

        def update_progress(self, *_args):
            return None

        def set_completed(self):
            return None

        def update_counts(self, *_args):
            return None

        def add_recent_item(self, *_args):
            return None

        def set_stage(self, *_args):
            return None

        def accept(self):
            return None

        def reject(self):
            return None

    class DummyWorker:
        captured = None

        def __init__(self, items, options, tab_type):
            DummyWorker.captured = {
                "items": items,
                "options": options,
                "tab_type": tab_type,
            }
            self.progress = DummySignal()
            self.stats_updated = DummySignal()
            self.row_translated = DummySignal()
            self.stage_updated = DummySignal()
            self.finished = DummySignal()
            self.error = DummySignal()

        def start(self):
            return None

        def cancel(self):
            return None

        def pause(self):
            return None

        def resume(self):
            return None

        def isRunning(self):
            return False

        def deleteLater(self):
            return None

    class FakeIndex:
        def __init__(self, row):
            self._row = row

        def row(self):
            return self._row

    class FakeSelectionModel:
        def selectedRows(self, *_args):
            return [FakeIndex(2), FakeIndex(0)]

    class FakeTable:
        def __init__(self):
            self._selection_model = FakeSelectionModel()

        def selectionModel(self):
            return self._selection_model

    class FakeButton:
        def __init__(self):
            self.enabled = True

        def setEnabled(self, value):
            self.enabled = value

    class DummySessionCtx:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    class DummyDB:
        def get_session(self):
            return DummySessionCtx()

    fake_entries = {
        0: SimpleNamespace(
            tm_id=101,
            src_text="s1",
            src_lang="he",
            tgt_lang="ru",
            translation="",
            project_id=1,
        ),
        2: SimpleNamespace(
            tm_id=303,
            src_text="s3",
            src_lang="he",
            tgt_lang="ru",
            translation="x",
            project_id=2,
        ),
    }

    panel = TranslationManagementPanel.__new__(TranslationManagementPanel)
    panel.table_view = FakeTable()
    panel.model = SimpleNamespace(get_entry=lambda row: fake_entries.get(row))
    panel.batch_translate_btn = FakeButton()
    panel.project_id = None
    panel.batch_translate_worker = None
    panel.build_filters = lambda: {}
    panel.perform_search = lambda: None

    monkeypatch.setattr("app.ui.dialogs.show_batch_translate_dialog", lambda **kwargs: (True, "chain", "FILL_EMPTY", "current_page"))
    monkeypatch.setattr("app.ui.dialogs.batch_progress_dialog_v3.BatchProgressDialogV3", DummyProgressDialog)
    monkeypatch.setattr("app.ui.workers.BatchTranslateWorker", DummyWorker)
    monkeypatch.setattr("app.services.db_service.DBService.get_instance", lambda: DummyDB())
    monkeypatch.setattr(
        "app.services.translation_admin_service.TranslationAdminService.count_tm_ids_for_translation",
        lambda self, session, filters, write_mode: 2,
    )

    TranslationManagementPanel.on_batch_translate(panel)

    assert DummyWorker.captured is not None
    assert DummyWorker.captured["tab_type"] == "tm"
    assert DummyWorker.captured["options"].write_mode == "FILL_EMPTY"
    assert DummyWorker.captured["options"].chunk_size == 1
    assert [item.entity_id for item in DummyWorker.captured["items"]] == ["101", "303"]
    assert all(item.entity_type == "tm_entry" for item in DummyWorker.captured["items"])


def test_tm_panel_context_menu_includes_translate_selected(monkeypatch):
    """TM context menu should expose Translate Selected action for selected rows."""

    class DummySignal:
        def __init__(self):
            self._callbacks = []

        def connect(self, cb):
            self._callbacks.append(cb)

        def emit(self):
            for cb in self._callbacks:
                cb()

    class FakeAction:
        def __init__(self, text, parent):
            self.text = text
            self.parent = parent
            self.triggered = DummySignal()
            self.enabled = True

        def setEnabled(self, value):
            self.enabled = bool(value)

    class FakeMenu:
        last = None

        def __init__(self, parent):
            self.parent = parent
            self.actions = []
            self.separators = 0
            FakeMenu.last = self

        def addAction(self, action):
            self.actions.append(action)

        def addSeparator(self):
            self.separators += 1

        def exec(self, _pos):
            return None

    class FakeIndex:
        def __init__(self, row):
            self._row = row

        def row(self):
            return self._row

    class FakeSelectionModel:
        def selectedRows(self, *_args):
            return [FakeIndex(1), FakeIndex(4)]

    class FakeViewport:
        def mapToGlobal(self, pos):
            return pos

    class FakeTable:
        def __init__(self):
            self._selection_model = FakeSelectionModel()
            self._viewport = FakeViewport()

        def selectionModel(self):
            return self._selection_model

        def viewport(self):
            return self._viewport

    panel = TranslationManagementPanel.__new__(TranslationManagementPanel)
    panel.table_view = FakeTable()

    state = {
        "translate_called": 0,
        "generate_called": 0,
        "play_called": 0,
        "playlist_called": 0,
        "edit_pron_called": 0,
        "bootstrap_called": 0,
    }
    panel.on_batch_translate = lambda: state.__setitem__("translate_called", state["translate_called"] + 1)
    panel.on_generate_audio_selected = lambda: state.__setitem__("generate_called", state["generate_called"] + 1)
    panel.on_play_audio_selected = lambda: state.__setitem__("play_called", state["play_called"] + 1)
    panel.on_add_selected_to_playlist = lambda: state.__setitem__("playlist_called", state["playlist_called"] + 1)
    panel.on_edit_pronunciation_selected = lambda: state.__setitem__("edit_pron_called", state["edit_pron_called"] + 1)
    panel.on_pronunciation_bootstrap_selected = lambda: state.__setitem__("bootstrap_called", state["bootstrap_called"] + 1)
    panel.set_entries_noise_status_bulk = lambda _flag: None

    monkeypatch.setattr("app.ui.translation_management_panel.QMenu", FakeMenu)
    monkeypatch.setattr("app.ui.translation_management_panel.QAction", FakeAction)

    TranslationManagementPanel.on_context_menu(panel, pos=(0, 0))

    assert FakeMenu.last is not None
    assert len(FakeMenu.last.actions) >= 5
    assert FakeMenu.last.actions[0].text == "Translate Selected (2 rows)..."
    assert FakeMenu.last.actions[1].text == "Generate Audio Selected (2 rows)..."
    assert FakeMenu.last.actions[2].text == "Play Audio Selected (2 rows)"
    assert "Add Selected to Playlist (2 rows)..." in [a.text for a in FakeMenu.last.actions]
    assert "Mispronounced -> Add Pronunciation..." in [a.text for a in FakeMenu.last.actions]
    assert "Pronunciation Bootstrap Selected (2 rows)..." in [a.text for a in FakeMenu.last.actions]

    # Ensure wired callback invokes TM batch translate handler.
    FakeMenu.last.actions[0].triggered.emit()
    FakeMenu.last.actions[1].triggered.emit()
    FakeMenu.last.actions[2].triggered.emit()
    next(a for a in FakeMenu.last.actions if a.text == "Add Selected to Playlist (2 rows)...").triggered.emit()
    next(a for a in FakeMenu.last.actions if a.text == "Mispronounced -> Add Pronunciation...").triggered.emit()
    next(a for a in FakeMenu.last.actions if a.text == "Pronunciation Bootstrap Selected (2 rows)...").triggered.emit()
    assert state["translate_called"] == 1
    assert state["generate_called"] == 1
    assert state["play_called"] == 1
    assert state["playlist_called"] == 1
    assert state["edit_pron_called"] == 1
    assert state["bootstrap_called"] == 1


def test_selected_pronunciation_items_prefer_raw_src_norm():
    panel = TranslationManagementPanel.__new__(TranslationManagementPanel)
    panel._get_selected_tm_entries = lambda: [
        SimpleNamespace(
            tm_id=7,
            src_lang="he",
            src_text="legacy src",
            src_norm="legacy_wrong_norm",
            raw_src_norm="cluster_raw_norm",
            kind="term_cluster",
        )
    ]

    items = TranslationManagementPanel._get_selected_pronunciation_items(panel)

    assert len(items) == 1
    assert items[0]["src_norm"] == normalize_for_tm("he", "legacy src", "surface").norm


def test_tm_bootstrap_refreshes_search_on_success(monkeypatch):
    panel = TranslationManagementPanel.__new__(TranslationManagementPanel)
    panel._get_selected_pronunciation_items = lambda: [
        {"src_lang": "he", "src_text": "prefix_a", "src_norm": normalize_for_tm("he", "prefix_a", "surface").norm}
    ]
    state = {"search": 0}
    panel.perform_search = lambda: state.__setitem__("search", state["search"] + 1)

    monkeypatch.setattr(
        "app.ui.dialogs.pronunciation_bootstrap_dialog.show_pronunciation_bootstrap_dialog",
        lambda **kwargs: True,
    )

    TranslationManagementPanel.on_pronunciation_bootstrap_selected(panel)
    assert state["search"] == 1
