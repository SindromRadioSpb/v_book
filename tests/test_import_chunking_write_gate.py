"""Unit tests for chunked import write-gate behavior."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
from pathlib import Path

import pytest

from app.services.project_exchange.import_engine import (
    ImportCancelledError,
    ProjectImportEngine,
)


def _build_minimal_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE lemma (
            lemma_id INTEGER PRIMARY KEY,
            project_id INTEGER,
            lemma_text TEXT,
            pos TEXT
        )
        """
    )
    conn.commit()
    return conn


def _make_engine_without_dbservice() -> ProjectImportEngine:
    engine = object.__new__(ProjectImportEngine)
    engine.db_service = None
    engine._lemma_batch_size = 2000
    engine._lemma_gate_batch_cap = 1500
    engine._gate_trace_path = None
    engine._gate_trace_lock = threading.Lock()
    return engine


def test_import_table_in_gate_batches_acquires_gate_multiple_times() -> None:
    engine = _make_engine_without_dbservice()

    with tempfile.TemporaryDirectory() as tmpdir:
        host_path = Path(tmpdir) / "host.db"
        payload_path = Path(tmpdir) / "payload.db"
        host_conn = _build_minimal_conn(host_path)
        payload_conn = _build_minimal_conn(payload_path)

        try:
            payload_conn.executemany(
                "INSERT INTO lemma (lemma_id, project_id, lemma_text, pos) VALUES (?, 1, ?, 'NOUN')",
                [(i, f"lemma_{i}") for i in range(1, 13)],
            )
            payload_conn.commit()

            calls: list[tuple[str, int | None, int | None]] = []

            def fake_run_serialized_write_tx(
                _host_conn,
                *,
                operation: str,
                action,
                batch_idx=None,
                rows_in_batch=None,
            ) -> None:
                calls.append((operation, batch_idx, rows_in_batch))
                action()

            engine._run_serialized_write_tx = fake_run_serialized_write_tx  # type: ignore[method-assign]
            engine._cooperative_yield_if_needed = lambda **_kwargs: None  # type: ignore[method-assign]

            imported = engine._import_table_in_gate_batches(
                host_conn,
                payload_conn,
                "lemma",
                offsets={"lemma": 0, "dict_project": 0},
                override_name=None,
                warnings=[],
                tm_global_id_map=None,
                cancel_check=None,
                batch_size=5,
            )

            assert imported == 12
            lemma_calls = [entry for entry in calls if entry[0] == "import.table.lemma"]
            assert len(lemma_calls) == 3
            assert [entry[1] for entry in lemma_calls] == [0, 1, 2]
            assert [entry[2] for entry in lemma_calls] == [5, 5, 2]

            host_count = host_conn.execute("SELECT COUNT(*) FROM lemma").fetchone()[0]
            assert host_count == 12
        finally:
            host_conn.close()
            payload_conn.close()


def test_import_table_in_gate_batches_checks_cancel_between_batches() -> None:
    engine = _make_engine_without_dbservice()

    with tempfile.TemporaryDirectory() as tmpdir:
        host_path = Path(tmpdir) / "host.db"
        payload_path = Path(tmpdir) / "payload.db"
        host_conn = _build_minimal_conn(host_path)
        payload_conn = _build_minimal_conn(payload_path)

        try:
            payload_conn.executemany(
                "INSERT INTO lemma (lemma_id, project_id, lemma_text, pos) VALUES (?, 1, ?, 'NOUN')",
                [(i, f"lemma_{i}") for i in range(1, 21)],
            )
            payload_conn.commit()

            cancel_state = {"value": False}
            lemma_batches = {"count": 0}

            def fake_run_serialized_write_tx(
                _host_conn,
                *,
                operation: str,
                action,
                batch_idx=None,
                rows_in_batch=None,
            ) -> None:
                action()
                if operation == "import.table.lemma":
                    lemma_batches["count"] += 1
                    if lemma_batches["count"] == 1:
                        cancel_state["value"] = True

            engine._run_serialized_write_tx = fake_run_serialized_write_tx  # type: ignore[method-assign]
            engine._cooperative_yield_if_needed = lambda **_kwargs: None  # type: ignore[method-assign]

            with pytest.raises(ImportCancelledError):
                engine._import_table_in_gate_batches(
                    host_conn,
                    payload_conn,
                    "lemma",
                    offsets={"lemma": 0, "dict_project": 0},
                    override_name=None,
                    warnings=[],
                    tm_global_id_map=None,
                    cancel_check=lambda: bool(cancel_state["value"]),
                    batch_size=5,
                )

            assert lemma_batches["count"] == 1
            host_count = host_conn.execute("SELECT COUNT(*) FROM lemma").fetchone()[0]
            assert host_count == 5
        finally:
            host_conn.close()
            payload_conn.close()


def test_import_table_in_gate_batches_respects_lemma_gate_batch_cap() -> None:
    engine = _make_engine_without_dbservice()
    engine._lemma_gate_batch_cap = 4

    with tempfile.TemporaryDirectory() as tmpdir:
        host_path = Path(tmpdir) / "host.db"
        payload_path = Path(tmpdir) / "payload.db"
        host_conn = _build_minimal_conn(host_path)
        payload_conn = _build_minimal_conn(payload_path)

        try:
            payload_conn.executemany(
                "INSERT INTO lemma (lemma_id, project_id, lemma_text, pos) VALUES (?, 1, ?, 'NOUN')",
                [(i, f"lemma_{i}") for i in range(1, 11)],
            )
            payload_conn.commit()

            batch_sizes: list[int] = []

            def fake_run_serialized_write_tx(
                _host_conn,
                *,
                operation: str,
                action,
                batch_idx=None,
                rows_in_batch=None,
            ) -> None:
                if operation == "import.table.lemma":
                    batch_sizes.append(int(rows_in_batch or 0))
                action()

            engine._run_serialized_write_tx = fake_run_serialized_write_tx  # type: ignore[method-assign]
            engine._cooperative_yield_if_needed = lambda **_kwargs: None  # type: ignore[method-assign]

            imported = engine._import_table_in_gate_batches(
                host_conn,
                payload_conn,
                "lemma",
                offsets={"lemma": 0, "dict_project": 0},
                override_name=None,
                warnings=[],
                tm_global_id_map=None,
                cancel_check=None,
                batch_size=6,
            )

            assert imported == 10
            assert batch_sizes == [4, 4, 2]
        finally:
            host_conn.close()
            payload_conn.close()


def test_import_table_in_gate_batches_aligns_lemma_read_chunks_to_cap_boundaries() -> None:
    engine = _make_engine_without_dbservice()
    engine._lemma_gate_batch_cap = 1500

    with tempfile.TemporaryDirectory() as tmpdir:
        host_path = Path(tmpdir) / "host.db"
        payload_path = Path(tmpdir) / "payload.db"
        host_conn = _build_minimal_conn(host_path)
        payload_conn = _build_minimal_conn(payload_path)

        try:
            payload_conn.executemany(
                "INSERT INTO lemma (lemma_id, project_id, lemma_text, pos) VALUES (?, 1, ?, 'NOUN')",
                [(i, f"lemma_{i}") for i in range(1, 3501)],
            )
            payload_conn.commit()

            batch_sizes: list[int] = []

            def fake_run_serialized_write_tx(
                _host_conn,
                *,
                operation: str,
                action,
                batch_idx=None,
                rows_in_batch=None,
            ) -> None:
                if operation == "import.table.lemma":
                    batch_sizes.append(int(rows_in_batch or 0))
                action()

            engine._run_serialized_write_tx = fake_run_serialized_write_tx  # type: ignore[method-assign]
            engine._cooperative_yield_if_needed = lambda **_kwargs: None  # type: ignore[method-assign]

            imported = engine._import_table_in_gate_batches(
                host_conn,
                payload_conn,
                "lemma",
                offsets={"lemma": 0, "dict_project": 0},
                override_name=None,
                warnings=[],
                tm_global_id_map=None,
                cancel_check=None,
                batch_size=2000,
            )

            assert imported == 3500
            assert batch_sizes == [1500, 1500, 500]
            assert max(batch_sizes) == 1500
            assert all(size == 1500 for size in batch_sizes[:-1])

            host_ids = [row[0] for row in host_conn.execute("SELECT lemma_id FROM lemma ORDER BY lemma_id")]
            assert host_ids == list(range(1, 3501))
        finally:
            host_conn.close()
            payload_conn.close()
