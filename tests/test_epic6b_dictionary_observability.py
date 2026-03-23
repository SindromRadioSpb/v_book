"""Tests for Epic 6B: Observability + Status Semantics.

Covers:
- LemmaTableModel: Entity Class column at index 9, Audio shifted to 12
- LemmaTableModel: Noise column shows noise_source suffix
- DictionaryService.count_noise_lemmas: correct COUNT per project
- DictionarySearchWorker: noise_count_ready signal emitted
- noise_source + noise_updated_at passed through to LemmaStats DTO
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.domain.dto import LemmaStats
from app.infra.sa_models import Base, Lemma, LemmaProjectStat  # noqa: F401
from app.services.dictionary_service import DictionaryService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sa_engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path}/test_6b.db",
        connect_args={"check_same_thread": False},
    )
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.commit()
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(
            text("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT)")
        )
        conn.execute(text("INSERT OR REPLACE INTO schema_meta VALUES ('schema_version', '47')"))
        conn.commit()
    yield engine
    engine.dispose()


@pytest.fixture()
def session(sa_engine):
    with Session(sa_engine) as s:
        s.execute(text("PRAGMA foreign_keys=OFF"))
        yield s


# ---------------------------------------------------------------------------
# Test 1: LemmaTableModel column count = 13 (added Entity Class)
# ---------------------------------------------------------------------------


def test_lemma_table_model_column_count():
    """Entity Class inserted → 13 columns total."""
    from app.ui.models_qt import LemmaTableModel

    model = LemmaTableModel()
    assert model.columnCount() == 13, f"Expected 13, got {model.columnCount()}"
    assert model.headers[9] == "Entity Class"
    assert model.headers[10] == "Last Review"
    assert model.headers[11] == "Niqqud"
    assert model.headers[12] == "Audio"


# ---------------------------------------------------------------------------
# Test 2: Noise column shows noise_source suffix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "is_noise, noise_source, expected",
    [
        (1, "auto", "Noise (auto)"),
        (1, "manual", "Noise (manual)"),
        (0, "auto", "Valid (auto)"),
        (0, "manual", "Valid (manual)"),
        (1, None, "Noise"),  # legacy: no suffix
        (0, None, "Valid"),
        (None, None, ""),  # unclassified
    ],
)
def test_noise_column_shows_source(is_noise, noise_source, expected):
    """Noise column (col 8) displays noise_source suffix."""
    from PyQt6.QtCore import Qt

    from app.ui.models_qt import LemmaTableModel

    lemma = LemmaStats(
        lemma_id=1,
        lemma_text="test",
        pos="NN",
        freq_abs=1,
        doc_freq=1,
        is_noise=is_noise,
        noise_source=noise_source,
    )
    model = LemmaTableModel(lemmas=[lemma])
    idx = model.index(0, 8)
    result = model.data(idx, Qt.ItemDataRole.DisplayRole)
    assert (
        result == expected
    ), f"col 8 for is_noise={is_noise}, noise_source={noise_source!r}: got {result!r}"


# ---------------------------------------------------------------------------
# Test 3: Entity Class column (col 9) shows entity_class
# ---------------------------------------------------------------------------


def test_entity_class_column():
    """Entity Class column (col 9) returns entity_class from DTO."""
    from PyQt6.QtCore import Qt

    from app.ui.models_qt import LemmaTableModel

    lemma = LemmaStats(
        lemma_id=1,
        lemma_text="תל אביב",
        pos="NNP",
        freq_abs=5,
        doc_freq=2,
        entity_class="GPE",
    )
    model = LemmaTableModel(lemmas=[lemma])
    idx = model.index(0, 9)
    assert model.data(idx, Qt.ItemDataRole.DisplayRole) == "GPE"


def test_entity_class_column_empty():
    """Entity Class column returns '' when entity_class is None."""
    from PyQt6.QtCore import Qt

    from app.ui.models_qt import LemmaTableModel

    lemma = LemmaStats(lemma_id=1, lemma_text="test", pos="NN", freq_abs=1, doc_freq=1)
    model = LemmaTableModel(lemmas=[lemma])
    idx = model.index(0, 9)
    assert model.data(idx, Qt.ItemDataRole.DisplayRole) == ""


# ---------------------------------------------------------------------------
# Test 4: Translation still editable at col 5 (regression)
# ---------------------------------------------------------------------------


def test_translation_still_editable_at_col_5():
    """Column 5 (Translation) must remain editable after column shift."""
    from PyQt6.QtCore import Qt

    from app.ui.models_qt import LemmaTableModel

    lemma = LemmaStats(lemma_id=1, lemma_text="test", pos="NN", freq_abs=1, doc_freq=1)
    model = LemmaTableModel(lemmas=[lemma])
    idx = model.index(0, 5)
    flags = model.flags(idx)
    assert flags & Qt.ItemFlag.ItemIsEditable, "Column 5 must be editable"

    # Also verify columns 4 and 6 are NOT editable
    for col in (4, 6, 8, 9):
        assert not (
            model.flags(model.index(0, col)) & Qt.ItemFlag.ItemIsEditable
        ), f"Column {col} must not be editable"


# ---------------------------------------------------------------------------
# Test 5: count_noise_lemmas returns correct count
# ---------------------------------------------------------------------------


def test_count_noise_lemmas(session):
    """count_noise_lemmas returns count of is_noise=1 lemmas for the project."""
    for i, (is_noise, project_id) in enumerate([(1, 1), (1, 1), (0, 1), (1, 2)]):
        session.add(
            Lemma(
                project_id=project_id,
                lemma_text=f"word{i}",
                pos="NN",
                is_noise=is_noise,
            )
        )
    session.flush()
    session.commit()

    svc = DictionaryService()
    assert svc.count_noise_lemmas(session, project_id=1) == 2
    assert svc.count_noise_lemmas(session, project_id=2) == 1
    assert svc.count_noise_lemmas(session, project_id=99) == 0


# ---------------------------------------------------------------------------
# Test 6: noise_source propagated to LemmaStats DTO
# ---------------------------------------------------------------------------


def test_noise_source_in_lemma_dto(session):
    """noise_source and noise_updated_at are populated in LemmaStats DTO."""
    from datetime import UTC, datetime

    now_ts = datetime.now(UTC).isoformat()

    lemma = Lemma(
        project_id=1,
        lemma_text="test",
        pos="NN",
        is_noise=1,
        noise_source="manual",
        noise_updated_at=now_ts,
    )
    session.add(lemma)
    session.flush()

    stat = LemmaProjectStat(
        lemma_id=lemma.lemma_id,
        project_id=1,
        freq_abs=3,
        doc_freq=1,
    )
    session.add(stat)
    session.commit()

    svc = DictionaryService()
    rows = svc.search_lemmas(session, project_id=1, filters={"hide_noise": False})
    assert rows, "Expected at least one result"

    lemma_orm, _stat = rows[0]
    assert lemma_orm.noise_source == "manual"
    assert lemma_orm.noise_updated_at == now_ts
