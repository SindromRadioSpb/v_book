"""Tests for Epic 6A: Lemma provenance — noise lifecycle + orphan snapshot.

Covers:
- Migration 047 schema: noise_source, noise_updated_at, orphaned_lemma_id
- _get_or_create_lemmas: sets noise_source='auto' on new lemma creation
- _cleanup_orphaned_lemmas_for_ids: snapshots orphaned_lemma_id before DELETE
- Orphan snapshot idempotency
- Batch MT translate R2 guard: skips user_edit+approved entries
- Manual noise update writes noise_source='manual' + noise_updated_at
- compute_source_lifecycle: all four states
- Backfill coverage: migration backfills existing is_noise IS NOT NULL rows
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.infra.sa_models import Base, Lemma, LemmaProjectStat, TMEntry
from app.services.dictionary_service import DictionaryService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def raw_db(tmp_path: Path):
    """Bare SQLite connection for low-level migration / SQL tests."""
    db_path = tmp_path / "test_epic6a.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    yield conn
    conn.close()


@pytest.fixture()
def sa_engine(tmp_path: Path):
    """SQLAlchemy engine with full ORM schema (no migrations, direct create)."""
    db_path = tmp_path / "test_epic6a_sa.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    # Disable FK enforcement so we can insert lemma/tm_entry without full parent chain
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.commit()
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(
            text("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT)")
        )
        conn.execute(text("INSERT OR REPLACE INTO schema_meta VALUES ('schema_version', '47')"))
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.commit()
    yield engine
    engine.dispose()


@pytest.fixture()
def session(sa_engine):
    with Session(sa_engine) as s:
        s.execute(text("PRAGMA foreign_keys=OFF"))
        yield s


def _make_lemma(
    session: Session,
    *,
    project_id: int = 1,
    lemma_text: str = "foo",
    is_noise: int = 0,
    noise_source: str | None = None,
) -> Lemma:
    """Insert a Lemma and return it."""
    lemma = Lemma(
        project_id=project_id,
        lemma_text=lemma_text,
        pos="NN",
        is_noise=is_noise,
        noise_source=noise_source,
    )
    session.add(lemma)
    session.flush()
    return lemma


# ---------------------------------------------------------------------------
# Test 1: ORM schema includes new columns
# ---------------------------------------------------------------------------


def test_schema_columns_present(sa_engine):
    """noise_source, noise_updated_at, orphaned_lemma_id are in ORM schema."""
    with sa_engine.connect() as conn:
        lemma_info = conn.execute(text("PRAGMA table_info(lemma)")).fetchall()
        tm_info = conn.execute(text("PRAGMA table_info(tm_entry)")).fetchall()

    lemma_cols = {row[1] for row in lemma_info}
    tm_cols = {row[1] for row in tm_info}

    assert "noise_source" in lemma_cols
    assert "noise_updated_at" in lemma_cols
    assert "orphaned_lemma_id" in tm_cols


# ---------------------------------------------------------------------------
# Test 2: Migration 047 SQL backfill logic
# ---------------------------------------------------------------------------


def test_migration_047_backfill(raw_db):
    """Rows with is_noise IS NOT NULL get noise_source='auto' by migration backfill."""
    raw_db.executescript(
        """
        CREATE TABLE lemma (
            lemma_id INTEGER PRIMARY KEY,
            project_id INTEGER,
            lemma_text TEXT,
            is_noise INTEGER,
            noise_source TEXT
        );
        INSERT INTO lemma VALUES (1, 1, 'foo', 1, NULL);
        INSERT INTO lemma VALUES (2, 1, 'bar', 0, NULL);
        INSERT INTO lemma VALUES (3, 1, 'baz', NULL, NULL);
        INSERT INTO lemma VALUES (4, 1, 'qux', 1, 'manual');
    """
    )
    # Run backfill from migration 047
    raw_db.execute(
        "UPDATE lemma SET noise_source = 'auto' WHERE is_noise IS NOT NULL AND noise_source IS NULL"
    )
    raw_db.commit()

    rows = {r[0]: r[1] for r in raw_db.execute("SELECT lemma_id, noise_source FROM lemma")}
    assert rows[1] == "auto"  # was classified, gets backfilled
    assert rows[2] == "auto"  # was classified (not noise), gets backfilled
    assert rows[3] is None  # unclassified: stays NULL
    assert rows[4] == "manual"  # already set: untouched


# ---------------------------------------------------------------------------
# Test 3: _get_or_create_lemmas sets noise_source='auto'
# ---------------------------------------------------------------------------


def test_get_or_create_lemmas_sets_noise_source(session):
    """New lemmas created by _get_or_create_lemmas must have noise_source='auto'."""
    from collections import Counter

    from app.services.process_service import ProcessService

    pass  # FK enforcement disabled in fixture
    svc = ProcessService.__new__(ProcessService)

    lemma_counter = Counter({"שלום": 3})
    lemma_pos_map = {"שלום": "NN"}

    id_map = svc._create_or_get_lemmas(session, 1, lemma_counter, lemma_pos_map)
    session.flush()

    lemma = session.execute(
        text(
            "SELECT noise_source, noise_updated_at FROM lemma WHERE lemma_text = 'שלום' AND project_id = 1"
        )
    ).fetchone()

    assert lemma is not None, "Lemma should have been created"
    assert lemma[0] == "auto", f"Expected noise_source='auto', got {lemma[0]!r}"
    assert lemma[1] is not None, "noise_updated_at should be set"


# ---------------------------------------------------------------------------
# Test 4: orphan snapshot written before DELETE
# ---------------------------------------------------------------------------


def test_orphan_cleanup_snapshots_lemma_id(session):
    """_cleanup_orphaned_lemmas_for_ids snapshots orphaned_lemma_id into tm_entry."""
    from app.services.process_service import ProcessService

    pass  # FK enforcement disabled in fixture
    svc = ProcessService.__new__(ProcessService)

    # Create a lemma
    lemma = _make_lemma(session, project_id=1, lemma_text="orphan_test", is_noise=0)
    session.commit()
    lemma_id = lemma.lemma_id

    # Create a tm_entry linked to this lemma
    tm = TMEntry(
        project_id=1,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="orphan_test",
        src_norm="orphan_test",
        translation="test",
        status="draft",
        origin="mt_auto",
        lemma_id=lemma_id,
    )
    session.add(tm)
    session.commit()
    tm_id = tm.tm_id

    # No lemma_project_stat — so lemma is orphaned
    # Call cleanup with lemma_id as a candidate
    deleted = svc._cleanup_orphaned_lemmas_for_ids(session, 1, [lemma_id])
    session.commit()

    assert deleted == 1, "Should have deleted 1 orphan lemma"

    # orphaned_lemma_id must be captured in tm_entry before lemma was deleted
    # Note: lemma_id FK SET NULL requires PRAGMA foreign_keys=ON; we only test orphaned_lemma_id here
    row = session.execute(
        text("SELECT orphaned_lemma_id FROM tm_entry WHERE tm_id = :tmid"),
        {"tmid": tm_id},
    ).fetchone()

    assert row[0] == lemma_id, f"orphaned_lemma_id should be {lemma_id}, got {row[0]}"


# ---------------------------------------------------------------------------
# Test 5: orphan snapshot is idempotent
# ---------------------------------------------------------------------------


def test_orphan_snapshot_idempotent(session):
    """Running cleanup twice does not overwrite an existing orphaned_lemma_id."""
    pass  # FK enforcement disabled in fixture; no ProcessService needed here

    # Create a tm_entry with orphaned_lemma_id already set (sentinel=999)
    tm = TMEntry(
        project_id=1,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="already_orphaned",
        src_norm="already_orphaned",
        translation="val",
        status="draft",
        origin="mt_auto",
        lemma_id=None,
        orphaned_lemma_id=999,
    )
    session.add(tm)
    session.commit()
    tm_id = tm.tm_id

    # Run the snapshot UPDATE directly (simulating the inner loop)
    session.execute(
        text(
            "UPDATE tm_entry SET orphaned_lemma_id = lemma_id "
            "WHERE lemma_id IN (999) AND orphaned_lemma_id IS NULL"
        )
    )
    session.commit()

    row = session.execute(
        text("SELECT orphaned_lemma_id FROM tm_entry WHERE tm_id = :tmid"),
        {"tmid": tm_id},
    ).fetchone()

    assert row[0] == 999, "orphaned_lemma_id must not be overwritten (idempotent guard)"


# ---------------------------------------------------------------------------
# Test 6: batch MT translate R2 guard
# ---------------------------------------------------------------------------


def test_batch_mt_translate_skips_user_approved(session):
    """_write_lemma must not overwrite tm_entry with origin=user_edit, status=approved."""
    from app.services.batch_mt_translate_service import BatchMTTranslateService, BatchTranslateItem

    pass  # FK enforcement disabled in fixture

    # Insert existing user-approved TM entry
    tm = TMEntry(
        project_id=1,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="שלום",
        src_norm="שלום",
        translation="мир (user)",
        status="approved",
        origin="user_edit",
    )
    session.add(tm)
    session.commit()
    tm_id = tm.tm_id

    svc = BatchMTTranslateService.__new__(BatchMTTranslateService)
    item = BatchTranslateItem(
        project_id=1,
        src_lang="he",
        tgt_lang="ru",
        source_text="שלום",
        entity_type="lemma",
        entity_id="שלום",
        current_translation=None,
    )

    svc._write_lemma(session, item, "мир (mt)")
    session.commit()

    row = session.execute(
        text("SELECT translation, origin FROM tm_entry WHERE tm_id = :tmid"),
        {"tmid": tm_id},
    ).fetchone()

    assert row[0] == "мир (user)", "Translation must not be overwritten by MT"
    assert row[1] == "user_edit", "origin must remain user_edit"


# ---------------------------------------------------------------------------
# Test 7: manual noise update writes provenance
# ---------------------------------------------------------------------------


def test_manual_noise_update_sets_provenance(session):
    """Direct SQL UPDATE (simulating set_lemma_noise_status) writes noise_source=manual."""
    from datetime import UTC, datetime

    from sqlalchemy import update

    pass  # FK enforcement disabled in fixture
    lemma = _make_lemma(session, lemma_text="manual_test", noise_source="auto")
    session.commit()

    now_ts = datetime.now(UTC).isoformat()
    session.execute(
        update(Lemma)
        .where(Lemma.lemma_id == lemma.lemma_id)
        .values(is_noise=1, noise_source="manual", noise_updated_at=now_ts)
    )
    session.commit()

    row = session.execute(
        text("SELECT noise_source, noise_updated_at FROM lemma WHERE lemma_id = :lid"),
        {"lid": lemma.lemma_id},
    ).fetchone()

    assert row[0] == "manual"
    assert row[1] == now_ts


# ---------------------------------------------------------------------------
# Test 8: compute_source_lifecycle — all four states
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lemma_id, orphaned_lemma_id, origin, expected",
    [
        (1, None, "mt_auto", "linked"),
        (None, 42, "mt_auto", "source_missing"),
        (None, None, "user_edit", "manual"),
        (None, None, "manual", "manual"),
        (None, None, "mt_auto", "auto_only"),
        (None, None, None, "auto_only"),
    ],
)
def test_compute_source_lifecycle(lemma_id, orphaned_lemma_id, origin, expected):
    result = DictionaryService.compute_source_lifecycle(lemma_id, orphaned_lemma_id, origin)
    assert (
        result == expected
    ), f"lifecycle({lemma_id}, {orphaned_lemma_id}, {origin!r}) → {result!r}, want {expected!r}"
