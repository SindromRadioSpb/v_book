from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from app.infra.sa_models import (
    DictProject,
    Lemma,
    LemmaDocStat,
    LemmaProjectStat,
    Library,
    ProcessorRun,
    RunError,
    SourceCorpus,
    SourceDocument,
)
from app.services.db_service import DBService
from app.services.derived_artifact_governance_service import (
    DerivedArtifactGovernanceService,
)


def _reset_db_service() -> None:
    DBService.shutdown()
    DBService._instance = None
    DBService._db_manager = None
    DBService._ref_managers = {}


def _init_temp_db() -> Path:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    conn = sqlite3.connect(str(db_path))
    try:
        for migration_file in sorted(Path("app/infra/migrations").glob("*.sql")):
            conn.executescript(migration_file.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return db_path


def _seed_project(session) -> int:
    lib = Library(name="L")
    session.add(lib)
    session.flush()

    project = DictProject(
        library_id=lib.library_id,
        name="Governance Project",
        src_lang="he",
        tgt_lang="ru",
        is_general_corpus=1,
    )
    session.add(project)
    session.flush()

    corpus = SourceCorpus(project_id=project.project_id, name="Corpus")
    session.add(corpus)
    session.flush()

    docs = []
    for idx, sentence_count in enumerate((2, 1), start=1):
        doc = SourceDocument(
            corpus_id=corpus.corpus_id,
            file_path=f"/tmp/d{idx}.txt",
            file_name=f"d{idx}.txt",
            file_ext=".txt",
            file_size_bytes=10,
            sha256=f"sha-{idx}",
            status="processed",
            sentence_count=sentence_count,
            token_count=sentence_count * 3,
        )
        session.add(doc)
        session.flush()
        docs.append(doc)

    docs[0].snapshot_sentence_count = 2
    docs[0].snapshot_stats_state = "valid"
    docs[1].snapshot_sentence_count = 0
    docs[1].snapshot_stats_state = "unknown"

    lemma_a = Lemma(project_id=project.project_id, lemma_text="a", pos="NOUN")
    lemma_b = Lemma(project_id=project.project_id, lemma_text="b", pos="VERB")
    session.add_all([lemma_a, lemma_b])
    session.flush()

    session.add_all(
        [
            LemmaDocStat(project_id=project.project_id, doc_id=docs[0].doc_id, lemma_id=lemma_a.lemma_id, freq_abs=2),
            LemmaDocStat(project_id=project.project_id, doc_id=docs[0].doc_id, lemma_id=lemma_b.lemma_id, freq_abs=1),
            LemmaDocStat(project_id=project.project_id, doc_id=docs[1].doc_id, lemma_id=lemma_b.lemma_id, freq_abs=3),
            LemmaProjectStat(project_id=project.project_id, lemma_id=lemma_a.lemma_id, freq_abs=2, doc_freq=1),
            LemmaProjectStat(project_id=project.project_id, lemma_id=lemma_b.lemma_id, freq_abs=4, doc_freq=2),
        ]
    )

    ok_run = ProcessorRun(
        project_id=project.project_id,
        engine="fake",
        engine_version="1",
        docs_total=12000,
        docs_processed=12000,
        docs_failed=0,
        chunks_total=12,
        chunks_completed=12,
        status="ok",
        stage="completed",
        note=json.dumps(
            {
                "kind": "batch_nlp",
                "source": "snapshot_backfill_cli",
                "validation_scope": "bounded",
                "validated_doc_count": 12000,
            },
            sort_keys=True,
        ),
    )
    failed_run = ProcessorRun(
        project_id=project.project_id,
        engine="fake",
        engine_version="1",
        docs_total=1,
        docs_processed=0,
        docs_failed=1,
        chunks_total=1,
        chunks_completed=0,
        status="failed",
        stage="failed",
        note=json.dumps(
            {
                "kind": "batch_nlp",
                "source": "snapshot_backfill_cli",
                "validation_scope": "limited",
                "validated_doc_count": 0,
            },
            sort_keys=True,
        ),
    )
    session.add_all([ok_run, failed_run])
    session.flush()

    session.add(
        RunError(
            run_id=failed_run.run_id,
            doc_id=docs[1].doc_id,
            stage="processing",
            message="boom",
        )
    )
    session.commit()
    return int(project.project_id)


def test_derived_artifact_governance_service_reports_project_owned_growth() -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        with db.get_session() as session:
            project_id = _seed_project(session)

        service = DerivedArtifactGovernanceService()
        with db.get_read_session() as session:
            summary = service.get_project_summary(session, project_id)

        metrics = {metric.artifact_key: metric for metric in summary.artifacts}
        assert summary.project_name == "Governance Project"
        assert summary.total_docs == 2
        assert summary.processed_docs == 2
        assert "Observational only" in summary.observability_note
        assert "Snapshot volume reuses the existing readiness aggregate" in summary.storage_note

        assert metrics["lemma_doc_stat"].quantity_value == 3
        assert metrics["lemma_doc_stat"].quantity_basis == "exact count derived from lemma_project_stat.doc_freq"
        assert metrics["lemma_doc_stat"].status == "expected_large"
        assert metrics["lemma_doc_stat"].maintenance_mode == "reset_rebuild_only"
        assert "--reprocess-all" in str(metrics["lemma_doc_stat"].maintenance_cli_hint)
        assert "--dry-run" in str(metrics["lemma_doc_stat"].maintenance_cli_hint)
        assert "--preflight-only" in str(metrics["lemma_doc_stat"].maintenance_preflight_hint)
        assert "--backup-db-path" in str(metrics["lemma_doc_stat"].maintenance_preflight_hint)
        assert metrics["lemma_project_stat"].quantity_value == 2
        assert metrics["lemma_project_stat"].maintenance_mode == "reset_rebuild_only"
        assert "--reprocess-all" in str(metrics["lemma_project_stat"].maintenance_cli_hint)
        assert "--dry-run" in str(metrics["lemma_project_stat"].maintenance_cli_hint)
        assert "--preflight-only" in str(metrics["lemma_project_stat"].maintenance_preflight_hint)
        assert metrics["sentence_nlp_snapshot"].quantity_value == 2
        assert metrics["sentence_nlp_snapshot"].status == "stats_rebuild_required"
        assert metrics["sentence_nlp_snapshot"].maintenance_mode == "reset_rebuild_only"
        assert "Sentence coverage 66.67%" in metrics["sentence_nlp_snapshot"].summary
        assert any("unknown snapshot stats: 1" in line.lower() for line in metrics["sentence_nlp_snapshot"].detail_lines)
        assert "--reprocess-all" in str(metrics["sentence_nlp_snapshot"].maintenance_cli_hint)
        assert "--dry-run" in str(metrics["sentence_nlp_snapshot"].maintenance_cli_hint)
        assert "--preflight-only" in str(metrics["sentence_nlp_snapshot"].maintenance_preflight_hint)
        assert metrics["processor_run"].quantity_value == 2
        assert metrics["processor_run"].maintenance_mode == "retention_available"
        assert "prune_project_telemetry.py" in str(metrics["processor_run"].maintenance_cli_hint)
        assert "--preflight-only" in str(metrics["processor_run"].maintenance_preflight_hint)
        assert "--backup-db-path" in str(metrics["processor_run"].maintenance_preflight_hint)
        assert any("ok=1" in line and "failed=1" in line for line in metrics["processor_run"].detail_lines)
        assert metrics["run_error"].quantity_value == 1
        assert metrics["run_error"].maintenance_mode == "retention_with_parent_runs"
        assert any("processing=1" in line for line in metrics["run_error"].detail_lines)
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_derived_artifact_governance_service_omits_rebuild_cli_for_regular_projects() -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        with db.get_session() as session:
            project_id = _seed_project(session)
            project = session.get(DictProject, project_id)
            assert project is not None
            project.is_general_corpus = 0
            session.commit()

        service = DerivedArtifactGovernanceService()
        with db.get_read_session() as session:
            summary = service.get_project_summary(session, project_id)

        metrics = {metric.artifact_key: metric for metric in summary.artifacts}
        assert summary.is_reference_project is False
        assert metrics["lemma_doc_stat"].maintenance_cli_hint is None
        assert metrics["lemma_doc_stat"].maintenance_preflight_hint is None
        assert metrics["lemma_project_stat"].maintenance_cli_hint is None
        assert metrics["lemma_project_stat"].maintenance_preflight_hint is None
        assert metrics["sentence_nlp_snapshot"].maintenance_cli_hint is None
        assert metrics["sentence_nlp_snapshot"].maintenance_preflight_hint is None
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_derived_artifact_governance_service_uses_read_only_session_without_commit() -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        with db.get_session() as session:
            project_id = _seed_project(session)

        service = DerivedArtifactGovernanceService()
        with db.get_read_session() as session:
            session.commit = lambda: (_ for _ in ()).throw(AssertionError("commit should not be called"))
            summary = service.get_project_summary(session, project_id)

        assert summary.project_id == project_id
        assert len(summary.artifacts) == 5
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_derived_artifact_governance_service_avoids_cold_lemma_doc_stat_count() -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        with db.get_session() as session:
            project_id = _seed_project(session)

        service = DerivedArtifactGovernanceService()
        with db.get_read_session() as session:
            original_execute = session.execute
            seen_sql: list[str] = []

            def recording_execute(*args, **kwargs):
                if args:
                    seen_sql.append(str(args[0]))
                return original_execute(*args, **kwargs)

            session.execute = recording_execute  # type: ignore[assignment]
            summary = service.get_project_summary(session, project_id)

        assert summary.project_id == project_id
        assert all("FROM lemma_doc_stat WHERE project_id" not in sql for sql in seen_sql)
        assert any("SUM(doc_freq)" in sql and "FROM lemma_project_stat" in sql for sql in seen_sql)
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)
