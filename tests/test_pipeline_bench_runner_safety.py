"""Safety/unit tests for scripts/benchmarks/bench_reference_pipeline.py."""

from __future__ import annotations

import importlib.util
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "benchmarks"
        / "bench_reference_pipeline.py"
    )
    spec = importlib.util.spec_from_file_location("bench_reference_pipeline", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runner_aborts_when_db_path_is_m_drive() -> None:
    mod = _load_module()
    rc = mod.run(
        [
            "extract_terms",
            "--db-path",
            r"M:\V_book\HDLE_Processing\hewiki_gpu_processing.db",
            "--copy-target",
            "--source-db",
            r"J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db",
        ]
    )
    assert rc == 1


def test_artifact_name_timestamp_is_deterministic(monkeypatch, tmp_path: Path) -> None:
    mod = _load_module()
    fixed = datetime(2026, 3, 6, 12, 34, 56, tzinfo=timezone.utc)
    monkeypatch.setattr(mod, "_utc_now", lambda: fixed)

    paths = mod.build_artifact_file_paths(tmp_path)
    assert paths["metrics_json"].name == "pipeline_bench_metrics_20260306_123456.json"
    assert paths["report_md"].name == "pipeline_bench_report_20260306_123456.md"
    assert paths["latest_log"].name == "pipeline_bench_latest.log"


def test_doc_slice_ordering_is_stable() -> None:
    mod = _load_module()
    sliced = mod.deterministic_slice_doc_ids([9, 1, 7, 1, 5, 3], 4)
    assert sliced == [1, 3, 5, 7]


def test_markdown_report_includes_timing_breakdown(tmp_path: Path) -> None:
    mod = _load_module()
    report = {
        "timestamp_utc": "2026-03-09T04:00:00+00:00",
        "scenario": "extract_terms",
        "overall_status": "pass",
        "config": {
            "doc_limit": 30,
            "tier": "smoke",
            "recommended_wall_budget_sec": 300,
            "pre_reset_sandbox": True,
            "post_cleanup_bench": True,
        },
        "db": {
            "base_sandbox_db": "base.db",
            "source_db": "source.db",
            "working_db": "working.db",
        },
        "bench": {
            "source_project_id": 1,
            "source_project_name": "Source",
            "bench_project_id": 2,
            "bench_project_name": "Bench",
            "selected_source_doc_ids": [1, 2, 3],
        },
        "stages": [
            {
                "name": "extract_terms",
                "status": "ok",
                "duration_sec": 12.5,
                "rows_processed": {"lemma": 10, "term": 5, "sentence": 3},
                "errors_count": 0,
            }
        ],
        "timings": {
            "base_copy_sec": 1.1,
            "working_copy_sec": 2.2,
            "db_initialize_sec": 0.3,
            "slice_clone_sec": 4.4,
            "pre_stage_overhead_sec": 8.0,
            "post_cleanup_bench_sec": 0.5,
            "overall_wall_sec": 21.1,
            "base_copy_reused": True,
            "working_db_reused": True,
        },
        "maintenance_cycle": {
            "actions": [
                {
                    "name": "pre_reset_sandbox",
                    "status": "ok",
                    "duration_sec": 1.1,
                    "details": {"base_copy_performed": True},
                },
                {
                    "name": "post_cleanup_bench",
                    "status": "ok",
                    "duration_sec": 0.5,
                    "details": {"deleted_count": 1},
                },
            ]
        },
        "artifacts": {
            "latest_log": "bench.log",
            "metrics_json": "bench.json",
            "report_md": "bench.md",
        },
    }
    md_path = tmp_path / "report.md"

    mod._write_markdown_report(report, md_path)
    text = md_path.read_text(encoding="utf-8")

    assert "## Timing Breakdown" in text
    assert "Pre-stage overhead total" in text
    assert "Stage wall total" in text
    assert "Overall wall total" in text
    assert "reused existing file" in text
    assert "reused sandbox file" in text
    assert "Tier: `smoke`" in text
    assert "Recommended wall budget: `300 s`" in text
    assert "Pre-reset sandbox: `enabled`" in text
    assert "Post-cleanup bench: `enabled`" in text
    assert "## Maintenance Cycle" in text
    assert "Post-cleanup bench: `0.500 s`" in text


def test_cleanup_sandbox_deletes_prefixed_projects(monkeypatch, tmp_path: Path) -> None:
    mod = _load_module()
    from app.infra.sa_models import DictProject, Library
    from app.services.project_service import ProjectService

    engine = create_engine(f"sqlite:///{tmp_path / 'cleanup_bench.db'}")
    Library.__table__.create(engine, checkfirst=True)
    DictProject.__table__.create(engine, checkfirst=True)

    calls: list[int] = []

    def _fake_delete_project(self, session, project_id):
        calls.append(int(project_id))
        session.execute(
            DictProject.__table__.delete().where(DictProject.project_id == int(project_id))
        )
        session.commit()
        return type(
            "DeleteReportStub",
            (),
            {"success": True, "error_message": ""},
        )()

    monkeypatch.setattr(ProjectService, "__init__", lambda self: None)
    monkeypatch.setattr(ProjectService, "delete_project", _fake_delete_project)

    with Session(engine) as session:
        lib = Library(name="lib")
        session.add(lib)
        session.flush()
        keep = DictProject(library_id=lib.library_id, name="KEEP_PROJECT", src_lang="he", tgt_lang="ru")
        bench_a = DictProject(library_id=lib.library_id, name="BENCH_A", src_lang="he", tgt_lang="ru")
        bench_b = DictProject(library_id=lib.library_id, name="BENCH_B", src_lang="he", tgt_lang="ru")
        session.add_all([keep, bench_a, bench_b])
        session.commit()
        bench_ids = [bench_a.project_id, bench_b.project_id]

        result = mod._run_cleanup_sandbox(
            session,
            cleanup_project_name=None,
            cleanup_prefix="BENCH_",
        )

        remaining = session.query(DictProject).order_by(DictProject.project_id.asc()).all()

    engine.dispose()

    assert calls == bench_ids
    assert result["details"]["deleted_count"] == 2
    assert [item["name"] for item in result["details"]["deleted_projects"]] == ["BENCH_A", "BENCH_B"]
    assert [project.name for project in remaining] == ["KEEP_PROJECT"]


def test_prepare_base_sandbox_replaces_db_and_removes_sidecars(tmp_path: Path) -> None:
    mod = _load_module()
    source_db = tmp_path / "source.db"
    target_db = tmp_path / "target.db"

    with sqlite3.connect(str(source_db)) as conn:
        conn.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO sample(value) VALUES ('source')")
        conn.commit()

    target_db.write_bytes(b"stale")
    for suffix in ("-wal", "-shm", "-journal"):
        (tmp_path / f"target.db{suffix}").write_bytes(b"stale-sidecar")

    copied = mod._prepare_base_sandbox(target_db, source_db, reuse_existing=False)

    with sqlite3.connect(str(target_db)) as conn:
        row = conn.execute("SELECT value FROM sample").fetchone()

    assert copied is True
    assert row == ("source",)
    for suffix in ("-wal", "-shm", "-journal"):
        assert not (tmp_path / f"target.db{suffix}").exists()


def test_validate_runtime_contract_rejects_cycle_flags_without_reuse_working_db(
    tmp_path: Path,
) -> None:
    mod = _load_module()
    source_db = tmp_path / "source.db"
    db_path = tmp_path / "sandbox.db"
    source_db.write_bytes(b"stub")
    db_path.write_bytes(b"stub")

    args = mod.build_parser().parse_args(
        [
            "extract_terms",
            "--db-path",
            str(db_path),
            "--copy-target",
            "--source-db",
            str(source_db),
            "--pre-reset-sandbox",
        ]
    )

    try:
        mod._validate_runtime_contract(args)
    except ValueError as exc:
        assert "--pre-reset-sandbox requires --reuse-working-db" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing --reuse-working-db")
