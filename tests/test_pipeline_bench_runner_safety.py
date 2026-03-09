"""Safety/unit tests for scripts/benchmarks/bench_reference_pipeline.py."""

from __future__ import annotations

import importlib.util
import sqlite3
import shutil
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
            "reuse_bench_slice": True,
            "prepared_source_db": "fixture.db",
            "pre_reset_sandbox": True,
            "post_cleanup_bench": False,
        },
        "db": {
            "base_sandbox_db": "base.db",
            "source_db": "source.db",
            "prepared_source_db": "fixture.db",
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
                    "name": "reuse_bench_slice",
                    "status": "prepared",
                    "duration_sec": 4.4,
                    "details": {"doc_limit": 30},
                },
                {
                    "name": "pre_reset_sandbox",
                    "status": "ok",
                    "duration_sec": 1.1,
                    "details": {"base_copy_performed": True},
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
    assert "Prepared Source DB: `fixture.db`" in text
    assert "Prepared source fixture: `enabled`" in text
    assert "Pre-reset sandbox: `enabled`" in text
    assert "Reuse bench slice: `enabled`" in text
    assert "## Maintenance Cycle" in text
    assert "reuse_bench_slice: status=`prepared`" in text


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


def test_validate_runtime_contract_rejects_reuse_bench_slice_with_post_cleanup(
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
            "--reuse-working-db",
            "--reuse-bench-slice",
            "--prepared-source-db",
            str(source_db),
            "--post-cleanup-bench",
            "--bench-project-name",
            "BENCH_FIXTURE",
        ]
    )

    try:
        mod._validate_runtime_contract(args)
    except ValueError as exc:
        assert "--reuse-bench-slice cannot be combined with --post-cleanup-bench" in str(exc)
    else:
        raise AssertionError("Expected ValueError for incompatible bench-slice flags")


def test_parse_bench_slice_description_roundtrip() -> None:
    mod = _load_module()
    description = mod._build_bench_slice_description(1, 6000)
    assert mod._parse_bench_slice_description(description) == {
        "source_project_id": 1,
        "doc_limit": 6000,
    }


def test_validate_runtime_contract_requires_prepared_source_for_reuse_bench_slice(
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
            "--reuse-working-db",
            "--reuse-bench-slice",
            "--bench-project-name",
            "BENCH_FIXTURE",
        ]
    )

    try:
        mod._validate_runtime_contract(args)
    except ValueError as exc:
        assert "--reuse-bench-slice requires --prepared-source-db" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing prepared source db")


def test_validate_runtime_contract_requires_existing_fixture_for_verify(
    tmp_path: Path,
) -> None:
    mod = _load_module()
    source_db = tmp_path / "source.db"
    source_db.write_bytes(b"stub")
    missing_fixture = tmp_path / "fixture.db"

    args = mod.build_parser().parse_args(
        [
            "verify_bench_fixture",
            "--db-path",
            str(missing_fixture),
            "--copy-target",
            "--source-db",
            str(source_db),
            "--bench-project-name",
            "BENCH_FIXTURE",
        ]
    )

    try:
        mod._validate_runtime_contract(args)
    except FileNotFoundError as exc:
        assert "--db-path not found for fixture verify" in str(exc)
    else:
        raise AssertionError("Expected FileNotFoundError for missing verify fixture DB")


def test_resolve_bench_slice_reuses_matching_project(tmp_path: Path) -> None:
    mod = _load_module()
    from app.infra.sa_models import (
        DictProject,
        DocumentSentence,
        DocumentText,
        Lemma,
        LemmaDocStat,
        Library,
        SourceCorpus,
        SourceDocument,
    )

    engine = create_engine(f"sqlite:///{tmp_path / 'reuse_slice.db'}")
    Library.__table__.create(engine, checkfirst=True)
    DictProject.__table__.create(engine, checkfirst=True)
    SourceCorpus.__table__.create(engine, checkfirst=True)
    SourceDocument.__table__.create(engine, checkfirst=True)
    DocumentText.__table__.create(engine, checkfirst=True)
    DocumentSentence.__table__.create(engine, checkfirst=True)
    Lemma.__table__.create(engine, checkfirst=True)
    LemmaDocStat.__table__.create(engine, checkfirst=True)

    with Session(engine) as session:
        lib = Library(name="lib")
        session.add(lib)
        session.flush()
        source = DictProject(library_id=lib.library_id, name="Source", src_lang="he", tgt_lang="ru")
        bench = DictProject(
            library_id=lib.library_id,
            name="BENCH_FIXTURE",
            description=mod._build_bench_slice_description(1, 2),
            src_lang="he",
            tgt_lang="ru",
        )
        session.add_all([source, bench])
        session.flush()
        source_corpus = SourceCorpus(project_id=source.project_id, name="source")
        bench_corpus = SourceCorpus(project_id=bench.project_id, name="bench")
        session.add_all([source_corpus, bench_corpus])
        session.flush()
        src_doc_1 = SourceDocument(
            corpus_id=source_corpus.corpus_id,
            file_path="a.txt",
            file_name="a.txt",
            file_ext=".txt",
            file_size_bytes=1,
            sha256="a",
            status="processed",
            sentence_count=1,
            token_count=1,
        )
        src_doc_2 = SourceDocument(
            corpus_id=source_corpus.corpus_id,
            file_path="b.txt",
            file_name="b.txt",
            file_ext=".txt",
            file_size_bytes=1,
            sha256="b",
            status="processed",
            sentence_count=1,
            token_count=1,
        )
        bench_doc_1 = SourceDocument(
            corpus_id=bench_corpus.corpus_id,
            file_path="ba.txt",
            file_name="ba.txt",
            file_ext=".txt",
            file_size_bytes=1,
            sha256="ba",
            status="processed",
            sentence_count=1,
            token_count=1,
        )
        bench_doc_2 = SourceDocument(
            corpus_id=bench_corpus.corpus_id,
            file_path="bb.txt",
            file_name="bb.txt",
            file_ext=".txt",
            file_size_bytes=1,
            sha256="bb",
            status="processed",
            sentence_count=1,
            token_count=1,
        )
        session.add_all([src_doc_1, src_doc_2, bench_doc_1, bench_doc_2])
        session.flush()
        session.add_all(
            [
                DocumentSentence(doc_id=bench_doc_1.doc_id, sent_index=0, text="one"),
                DocumentSentence(doc_id=bench_doc_2.doc_id, sent_index=0, text="two"),
            ]
        )
        selected_source_doc_ids = [src_doc_1.doc_id, src_doc_2.doc_id]
        session.commit()

        result, reused = mod._resolve_bench_slice(
            session,
            source_project_id=source.project_id,
            bench_project_name="BENCH_FIXTURE",
            doc_limit=2,
            reuse_existing_slice=True,
        )

    engine.dispose()

    assert reused is True
    assert result["bench_project_name"] == "BENCH_FIXTURE"
    assert result["copied_counts"]["documents"] == 2
    assert result["selected_source_doc_ids"] == selected_source_doc_ids


def _insert_schema_meta(path: Path, schema_version: int) -> None:
    with sqlite3.connect(str(path)) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_meta(key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)",
            (str(schema_version),),
        )
        conn.commit()


def test_run_verify_bench_fixture_accepts_matching_fixture(tmp_path: Path) -> None:
    mod = _load_module()
    from app.infra.sa_models import (
        DictProject,
        DocumentSentence,
        DocumentText,
        Lemma,
        LemmaDocStat,
        Library,
        SourceCorpus,
        SourceDocument,
    )

    source_path = tmp_path / "source_fixture.db"
    fixture_path = tmp_path / "prepared_fixture.db"
    source_engine = create_engine(f"sqlite:///{source_path}")
    Library.__table__.create(source_engine, checkfirst=True)
    DictProject.__table__.create(source_engine, checkfirst=True)
    SourceCorpus.__table__.create(source_engine, checkfirst=True)
    SourceDocument.__table__.create(source_engine, checkfirst=True)
    DocumentText.__table__.create(source_engine, checkfirst=True)
    DocumentSentence.__table__.create(source_engine, checkfirst=True)
    Lemma.__table__.create(source_engine, checkfirst=True)
    LemmaDocStat.__table__.create(source_engine, checkfirst=True)

    with Session(source_engine) as session:
        lib = Library(name="lib")
        session.add(lib)
        session.flush()
        source = DictProject(library_id=lib.library_id, name="Source", src_lang="he", tgt_lang="ru")
        session.add(source)
        session.flush()
        source_corpus = SourceCorpus(project_id=source.project_id, name="source")
        session.add(source_corpus)
        session.flush()
        for name in ("a.txt", "b.txt"):
            session.add(
                SourceDocument(
                    corpus_id=source_corpus.corpus_id,
                    file_path=name,
                    file_name=name,
                    file_ext=".txt",
                    file_size_bytes=1,
                    sha256=name,
                    status="processed",
                    sentence_count=1,
                    token_count=1,
                )
            )
        session.commit()
        source_project_id = int(source.project_id)
    source_engine.dispose()
    _insert_schema_meta(source_path, 36)
    shutil.copyfile(source_path, fixture_path)

    fixture_engine = create_engine(f"sqlite:///{fixture_path}")
    with Session(fixture_engine) as session:
        source = session.get(DictProject, source_project_id)
        assert source is not None
        source_corpus = session.query(SourceCorpus).filter_by(project_id=source_project_id).one()
        source_docs = (
            session.query(SourceDocument)
            .filter_by(corpus_id=source_corpus.corpus_id)
            .order_by(SourceDocument.doc_id.asc())
            .all()
        )
        bench = DictProject(
            library_id=source.library_id,
            name="BENCH_FIXTURE",
            description=mod._build_bench_slice_description(source_project_id, 2),
            src_lang="he",
            tgt_lang="ru",
        )
        session.add(bench)
        session.flush()
        bench_corpus = SourceCorpus(project_id=bench.project_id, name="bench")
        session.add(bench_corpus)
        session.flush()
        bench_docs = []
        for index, source_doc in enumerate(source_docs, 1):
            bench_doc = SourceDocument(
                corpus_id=bench_corpus.corpus_id,
                file_path=f"bench_{index}.txt",
                file_name=f"bench_{index}.txt",
                file_ext=".txt",
                file_size_bytes=1,
                sha256=f"bench_{index}",
                status="processed",
                sentence_count=1,
                token_count=1,
            )
            session.add(bench_doc)
            bench_docs.append(bench_doc)
        session.flush()
        for index, bench_doc in enumerate(bench_docs, 1):
            session.add(DocumentText(doc_id=bench_doc.doc_id, raw_text=f"doc {index}"))
            session.add(DocumentSentence(doc_id=bench_doc.doc_id, sent_index=0, text=f"sent {index}"))
        lemma = Lemma(project_id=bench.project_id, lemma_text="lemma", pos="NOUN")
        session.add(lemma)
        session.flush()
        session.add(
            LemmaDocStat(
                project_id=bench.project_id,
                doc_id=bench_docs[0].doc_id,
                lemma_id=lemma.lemma_id,
                freq_abs=1,
                sample_sentence_id=None,
            )
        )
        session.commit()
    fixture_engine.dispose()
    _insert_schema_meta(fixture_path, 36)

    fixture_engine = create_engine(f"sqlite:///{fixture_path}")
    with Session(fixture_engine) as session:
        result = mod._run_verify_bench_fixture(
            session,
            fixture_db=fixture_path,
            source_db=source_path,
            source_project_id=source_project_id,
            bench_project_name="BENCH_FIXTURE",
            doc_limit=2,
        )
    fixture_engine.dispose()

    assert result["name"] == "verify_bench_fixture"
    assert result["details"]["checks"]["schema_version_match"] is True
    assert result["details"]["checks"]["source_doc_ids_match"] is True
    assert result["details"]["bench"]["bench_project_name"] == "BENCH_FIXTURE"
    assert result["rows_processed"]["sentence"] == 2


def test_run_verify_bench_fixture_rejects_schema_mismatch(tmp_path: Path) -> None:
    mod = _load_module()
    from app.infra.sa_models import DictProject, Library, SourceCorpus, SourceDocument

    source_path = tmp_path / "source_schema.db"
    fixture_path = tmp_path / "fixture_schema.db"

    for path in (source_path, fixture_path):
        engine = create_engine(f"sqlite:///{path}")
        Library.__table__.create(engine, checkfirst=True)
        DictProject.__table__.create(engine, checkfirst=True)
        SourceCorpus.__table__.create(engine, checkfirst=True)
        SourceDocument.__table__.create(engine, checkfirst=True)
        with Session(engine) as session:
            lib = Library(name="lib")
            session.add(lib)
            session.flush()
            source = DictProject(library_id=lib.library_id, name="Source", src_lang="he", tgt_lang="ru")
            session.add(source)
            session.flush()
            source_corpus = SourceCorpus(project_id=source.project_id, name="source")
            session.add(source_corpus)
            session.flush()
            session.add(
                SourceDocument(
                    corpus_id=source_corpus.corpus_id,
                    file_path="a.txt",
                    file_name="a.txt",
                    file_ext=".txt",
                    file_size_bytes=1,
                    sha256="a",
                    status="processed",
                    sentence_count=1,
                    token_count=1,
                )
            )
            session.commit()
            source_project_id = int(source.project_id)
        engine.dispose()

    _insert_schema_meta(source_path, 36)
    _insert_schema_meta(fixture_path, 35)

    engine = create_engine(f"sqlite:///{fixture_path}")
    with Session(engine) as session:
        try:
            mod._run_verify_bench_fixture(
                session,
                fixture_db=fixture_path,
                source_db=source_path,
                source_project_id=source_project_id,
                bench_project_name="BENCH_FIXTURE",
                doc_limit=1,
            )
        except RuntimeError as exc:
            assert "schema version mismatch" in str(exc)
        else:
            raise AssertionError("Expected RuntimeError for schema mismatch")
    engine.dispose()
