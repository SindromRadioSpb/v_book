"""Benchmark guard tests for healthy target DB requirements."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from scripts import benchmark_import_concurrent_save as bench_mod


def _make_args(db_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        db_path=str(db_path),
        use_repaired_db=None,
        copy_target=False,
        allow_fallback=False,
        seed_docs=10,
        seed_lemmas=10,
        save_cadence_ms=100,
        max_save_attempts=10,
        lemma_batch_size=2000,
        quick_check_timeout_sec=1.0,
    )


def test_benchmark_main_fails_without_allow_fallback_on_malformed_target(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    target_db = tmp_path / "target.db"
    sqlite3.connect(str(target_db)).close()

    malformed_error = "malformed database schema (sentence_fts) - table sentence_fts already exists"
    monkeypatch.setattr(
        bench_mod, "_validate_sqlite_readable", lambda _path: (False, malformed_error)
    )
    monkeypatch.setattr(bench_mod, "parse_args", lambda: _make_args(target_db))

    exit_code = bench_mod.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err.strip()
    payload = json.loads(captured.err)
    assert payload["status"] == "FAILED"
    assert "repair_fts_schema.py" in payload["error"]
    assert payload["allow_fallback"] is False
