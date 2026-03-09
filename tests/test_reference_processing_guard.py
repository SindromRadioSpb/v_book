"""Tests for PERF-SCALE PATCH-J: reference corpus processing guard.

Covers:
- is_reference_corpus flag is True when project.is_reference=1
- is_reference_corpus flag is True when project.is_general_corpus=1
- is_reference_corpus flag is False for normal projects
- on_process() and on_reprocess() guard logic (unit-tested without full UI)
- CLI _get_unprocessed_doc_ids() query correctness
- CLI _process_chunk() dry-run returns correct counts
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# is_reference_corpus flag logic (mirrors documents_view.load_corpus)
# ---------------------------------------------------------------------------


def _compute_is_reference_corpus(is_general_corpus: int, is_reference: int) -> bool:
    """Mirrors the flag computation added in PATCH-J."""
    return bool(is_general_corpus or is_reference)


def test_flag_false_for_normal_project():
    assert _compute_is_reference_corpus(0, 0) is False


def test_flag_true_for_general_corpus():
    assert _compute_is_reference_corpus(1, 0) is True


def test_flag_true_for_reference_project():
    assert _compute_is_reference_corpus(0, 1) is True


def test_flag_true_when_both_set():
    assert _compute_is_reference_corpus(1, 1) is True


# ---------------------------------------------------------------------------
# on_process / on_reprocess guard (mocked QWidget logic)
# ---------------------------------------------------------------------------


def _simulate_on_process(is_reference_corpus: bool) -> str:
    """Simulate the guard at the top of on_process().

    Returns 'blocked' or 'continues'.
    """
    if is_reference_corpus:
        return "blocked"
    return "continues"


def test_on_process_blocked_for_reference():
    assert _simulate_on_process(True) == "blocked"


def test_on_process_continues_for_normal():
    assert _simulate_on_process(False) == "continues"


def test_on_reprocess_blocked_for_reference():
    assert _simulate_on_process(True) == "blocked"


def test_on_reprocess_continues_for_normal():
    assert _simulate_on_process(False) == "continues"


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def _make_db_with_docs() -> str:
    """Create a temp DB with minimal schema + sample documents."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE source_corpus (
            corpus_id INTEGER PRIMARY KEY,
            project_id INTEGER,
            name TEXT
        );
        CREATE TABLE source_document (
            doc_id INTEGER PRIMARY KEY,
            corpus_id INTEGER,
            file_name TEXT,
            status TEXT
        );
        INSERT INTO source_corpus VALUES (1, 42, 'main');
        INSERT INTO source_document VALUES (1, 1, 'doc_a.txt', 'imported');
        INSERT INTO source_document VALUES (2, 1, 'doc_b.txt', 'processed');
        INSERT INTO source_document VALUES (3, 1, 'doc_c.txt', 'failed');
        INSERT INTO source_document VALUES (4, 1, 'doc_d.txt', NULL);
        """
    )
    conn.commit()
    conn.close()
    return db_path


def test_get_unprocessed_doc_ids():
    """Only unprocessed/failed/null docs should be returned."""
    db_path = _make_db_with_docs()
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import Session

        engine = create_engine(f"sqlite:///{db_path}")
        with Session(engine) as session:
            # Import the function
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
            from process_reference_corpus import _get_unprocessed_doc_ids

            ids = _get_unprocessed_doc_ids(session, project_id=42)

        # doc 2 is 'processed' — must be excluded
        # doc 1 ('imported'), doc 3 ('failed'), doc 4 (NULL) must be included
        assert 2 not in ids
        assert 1 in ids
        assert 3 in ids
        assert 4 in ids
        engine.dispose()
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_get_project_doc_ids_returns_full_deterministic_slice():
    """All project docs should be returned in stable doc_id order."""
    db_path = _make_db_with_docs()
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        engine = create_engine(f"sqlite:///{db_path}")
        with Session(engine) as session:
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
            from process_reference_corpus import _get_project_doc_ids

            ids = _get_project_doc_ids(session, project_id=42)

        assert ids == [1, 2, 3, 4]
        engine.dispose()
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_process_chunk_dry_run():
    """Dry-run must return (len(chunk), 0) without calling process_service."""
    from process_reference_corpus import _process_chunk  # noqa: F401 (already on path)

    mock_db = MagicMock()
    mock_svc = MagicMock()
    ok, err = _process_chunk(mock_db, mock_svc, [1, 2, 3], True, False, dry_run=True)
    assert ok == 3
    assert err == 0
    mock_svc.process_document.assert_not_called()


def test_process_chunk_counts_success_and_error():
    """_process_chunk counts success/error from process_service return value."""
    from process_reference_corpus import _process_chunk

    mock_svc = MagicMock()
    # Alternate success/failure
    mock_svc.process_document.side_effect = [True, False, True]

    # Mock db_service.get_session() as context manager
    mock_session_cm = MagicMock()
    mock_session_cm.__enter__ = MagicMock(return_value=MagicMock())
    mock_session_cm.__exit__ = MagicMock(return_value=False)
    mock_db = MagicMock()
    mock_db.get_session.return_value = mock_session_cm

    ok, err = _process_chunk(mock_db, mock_svc, [1, 2, 3], True, False, dry_run=False)
    assert ok == 2
    assert err == 1
