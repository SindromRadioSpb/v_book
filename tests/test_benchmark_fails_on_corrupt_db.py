"""Benchmark fail-fast behavior on detected DB corruption."""

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


def test_benchmark_main_fails_fast_when_corruption_probe_fails(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    target_db = tmp_path / "target.db"
    sqlite3.connect(str(target_db)).close()

    monkeypatch.setattr(bench_mod, "parse_args", lambda: _make_args(target_db))
    monkeypatch.setattr(bench_mod, "_validate_sqlite_readable", lambda _path: (True, None))
    monkeypatch.setattr(
        bench_mod,
        "_probe_target_db_corruption",
        lambda _path, quick_check_timeout_sec=10.0: {
            "ok": False,
            "quick_check_rows": ["database disk image is malformed"],
            "quick_check_error": "database disk image is malformed",
            "tm_entry_probe_ok": False,
            "tm_entry_probe_error": "database disk image is malformed",
        },
    )

    exit_code = bench_mod.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    payload = json.loads(captured.err)
    assert payload["status"] == "FAILED"
    assert "repair_db_corruption.py" in payload["error"]
