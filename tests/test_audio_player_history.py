from __future__ import annotations
import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import QModelIndex, Qt
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infra.sa_models import Base
from app.services.audio_queue_service import AudioItemSpec, AudioQueueService
from app.ui.widgets.audio_player_panel import AudioQueueTableModel


# -- QApp fixture ---------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication(sys.argv)


# -- Model fixtures -------------------------------------------------------


@pytest.fixture
def model(qapp):
    return AudioQueueTableModel()


@pytest.fixture
def tmp_wav(tmp_path):
    p = tmp_path / "test.wav"
    p.write_bytes(b"RIFF")
    return p


# -- 1. empty model -------------------------------------------------------


def test_model_empty(model):
    assert model.rowCount() == 0
    assert model.columnCount() == 7


# -- 2. load rows ---------------------------------------------------------


def test_model_load_tracks(model, tmp_wav):
    rows = [{"label": "hello", "path": str(tmp_wav), "context": {}}]
    model.load(rows, 0)
    assert model.rowCount() == 1


# -- 3. current row shows play marker ------------------------------------


def test_model_current_row_marker(model, tmp_wav):
    rows = [
        {"label": "A", "path": str(tmp_wav), "context": {}},
        {"label": "B", "path": str(tmp_wav), "context": {}},
        {"label": "C", "path": str(tmp_wav), "context": {}},
    ]
    model.load(rows, 1)
    idx = model.index(1, 0)
    data = model.data(idx, Qt.ItemDataRole.DisplayRole)
    # The play arrow character
    assert data == chr(0x25B6)


# -- 4. non-current row shows 1-based row number -------------------------


def test_model_non_current_row_number(model, tmp_wav):
    rows = [
        {"label": "A", "path": str(tmp_wav), "context": {}},
        {"label": "B", "path": str(tmp_wav), "context": {}},
    ]
    model.load(rows, 1)
    # Row 0 is not current (current=1) -> displays "1"
    idx = model.index(0, 0)
    data = model.data(idx, Qt.ItemDataRole.DisplayRole)
    assert data == "1"


# -- 5. Hebrew label column -----------------------------------------------


def test_model_hebrew_column(model, tmp_wav):
    rows = [{"label": "shalom", "path": str(tmp_wav), "context": {}}]
    model.load(rows, -1)
    idx = model.index(0, 1)
    data = model.data(idx, Qt.ItemDataRole.DisplayRole)
    assert data == "shalom"


# -- 6. status: ready vs missing ------------------------------------------


def test_model_status_ready(model, tmp_wav):
    rows = [{"label": "X", "path": str(tmp_wav), "context": {}}]
    model.load(rows, -1)
    status = model.data(model.index(0, 5), Qt.ItemDataRole.DisplayRole)
    assert status == "ready"


def test_model_status_missing(model):
    rows = [{"label": "X", "path": "/nonexistent_audio_file.wav", "context": {}}]
    model.load(rows, -1)
    status = model.data(model.index(0, 5), Qt.ItemDataRole.DisplayRole)
    assert status == "missing"


# -- 7. header data -------------------------------------------------------


def test_model_header_data(model):
    header = model.headerData(1, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
    assert header == "Hebrew"


# -- 8. column count is 7 -------------------------------------------------


def test_model_column_count(model):
    assert model.columnCount() == 7


# -- History via AudioQueueService ----------------------------------------


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def svc():
    return AudioQueueService()


def _specs(n):
    return [AudioItemSpec(kind="sentence", source_id=i + 1) for i in range(n)]


# -- 9. history survives queue clear (append-only) ------------------------


def test_history_append_only(session, svc):
    ids = svc.add_to_queue(session, _specs(3))
    session.commit()
    for item_id in ids:
        svc.mark_played(session, item_id)
        session.commit()
    # Now clear the queue
    svc.clear_queue(session)
    session.commit()
    # History still has 3 entries
    history = svc.get_history(session)
    assert len(history) == 3


# -- 10. history limit ----------------------------------------------------


def test_history_limit(session, svc):
    ids = svc.add_to_queue(session, _specs(5))
    session.commit()
    for item_id in ids:
        svc.mark_played(session, item_id)
        session.commit()
    history = svc.get_history(session, limit=2)
    assert len(history) == 2
    # The 2 returned should be the 2 most recent (highest played_at)
    all_history = svc.get_history(session, limit=100)
    assert history[0].history_id == all_history[0].history_id
    assert history[1].history_id == all_history[1].history_id
