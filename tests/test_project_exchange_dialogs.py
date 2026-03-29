"""UI contract tests for project exchange dialogs."""

from __future__ import annotations

from app.services.project_exchange.dto import (
    ExportArtifactInfo,
    ExportReport,
    ExportStageRecord,
    ImportArtifactInfo,
    ImportPreflightReport,
    ImportReport,
    ImportStageRecord,
    ImportVerificationInfo,
    ManifestInfo,
)
from app.ui.dialogs.project_exchange_dialogs import ImportPreviewDialog, ImportProgressDialog
from app.ui.dialogs.project_exchange_dialogs import ExportProgressDialog


def _make_manifest() -> ManifestInfo:
    return ManifestInfo(
        bundle_format_version=1,
        app_version="1.0.0",
        schema_version=65,
        project_name="Bundle Project",
        project_src_lang="he",
        project_tgt_lang="en",
        exported_at="2026-03-14T10:00:00Z",
        table_counts={"source_document": 2, "document_sentence": 5, "lemma": 3},
        pronunciation_metadata_count=4,
    )


def test_import_preview_dialog_renders_preflight_plan(qtbot):
    preflight = ImportPreflightReport(
        manifest=_make_manifest(),
        host_schema_version=65,
        original_project_name="Bundle Project",
        final_project_name="Bundle Project (imported 2026-03-14)",
        name_conflict=True,
        total_rows=10,
        warnings=[
            "Project name 'Bundle Project' already exists, renamed to 'Bundle Project (imported 2026-03-14)'"
        ],
    )

    dialog = ImportPreviewDialog(preflight)
    qtbot.addWidget(dialog)

    plan_text = dialog.plan_text.toPlainText()
    summary_text = dialog.summary_text.toPlainText()

    assert "Host schema compatibility: v65 host accepts v65 bundle" in plan_text
    assert "Auto-rename target: Bundle Project (imported 2026-03-14)" in plan_text
    assert "Pronunciation metadata rows: 4" in plan_text
    assert "Documents: 2" in summary_text
    assert "Sentences: 5" in summary_text


def test_import_progress_dialog_shows_success_details_and_open_flag(qtbot):
    dialog = ImportProgressDialog()
    qtbot.addWidget(dialog)

    report = ImportReport(
        success=True,
        new_project_id=42,
        new_project_name="Imported Project",
        table_counts={"source_document": 2, "document_sentence": 5},
        warnings=["Renamed on import"],
        elapsed_seconds=1.5,
        final_stage_id="completed",
        final_stage_label="Completed",
        artifact_info=ImportArtifactInfo(
            bundle_size_bytes=2,
            payload_quick_check="ok",
            manifest_project_name="Imported Project",
            total_rows=7,
        ),
        verification_info=ImportVerificationInfo(
            project_row_found=True,
            project_name_matches=True,
            verified_corpus_count=1,
            verified_document_count=2,
            verified_sentence_count=5,
            verified_lemma_count=0,
        ),
        stage_history=[
            ImportStageRecord(
                stage_id="verify_imported_project",
                stage_label="Verifying imported project",
                status="ok",
                started_at=0.0,
                ended_at=1.0,
                elapsed_seconds=1.0,
                detail="documents=2; sentences=5",
            )
        ],
    )

    dialog.set_completed(report)

    assert dialog.details_text.isHidden() is False
    details = dialog.details_text.toPlainText()
    assert "Imported Project" in details
    assert "Artifact Validation" in details
    assert "Post-import Verification" in details
    assert "Stage History" in details
    assert "verify_imported_project" in details
    assert dialog.should_open_project() is False

    dialog.on_open_project()

    assert dialog.should_open_project() is True
    assert dialog.get_new_project_id() == 42


def test_import_progress_dialog_renders_failure_stage_and_cleanup_details(qtbot):
    dialog = ImportProgressDialog()
    qtbot.addWidget(dialog)

    report = ImportReport(
        success=False,
        elapsed_seconds=2.5,
        error_message="Bundle contains duplicate source documents",
        failure_code="payload_duplicate_documents",
        final_stage_id="check_importability",
        final_stage_label="Checking importability",
        cleanup_status="not_needed",
        artifact_info=ImportArtifactInfo(
            bundle_size_bytes=2,
            payload_quick_check="ok",
            manifest_project_name="Bundle Project",
            total_rows=10,
        ),
        stage_history=[
            ImportStageRecord(
                stage_id="check_importability",
                stage_label="Checking importability",
                status="failed",
                started_at=0.0,
                ended_at=2.5,
                elapsed_seconds=2.5,
                detail="payload_duplicate_document_check=failed",
            )
        ],
    )

    dialog.set_completed(report)

    assert "Import failed during 'Checking importability'" == dialog.stage_label.text()
    details = dialog.details_text.toPlainText()
    assert "Failure code: payload_duplicate_documents" in details
    assert "Cleanup status: not_needed" in details
    assert "Stage History" in details


def test_export_progress_dialog_renders_artifact_validation_and_stage_history(qtbot, tmp_path):
    dialog = ExportProgressDialog()
    qtbot.addWidget(dialog)

    bundle_path = tmp_path / "bundle.hdleproj"
    bundle_path.write_bytes(b"ok")
    report = ExportReport(
        success=True,
        bundle_path=bundle_path,
        manifest=_make_manifest(),
        elapsed_seconds=2.0,
        final_stage_id="completed",
        final_stage_label="Completed",
        artifact_info=ExportArtifactInfo(
            bundle_size_bytes=2,
            payload_quick_check="ok",
            manifest_project_name="Bundle Project",
            total_rows=10,
        ),
        stage_history=[
            ExportStageRecord(
                stage_id="prune_payload",
                stage_label="Pruning excluded payload structures...",
                status="ok",
                started_at=0.0,
                ended_at=1.0,
                elapsed_seconds=1.0,
                detail="excluded_tables=10",
            )
        ],
    )

    dialog.set_completed(report)

    details = dialog.details_text.toPlainText()
    assert "Artifact Validation" in details
    assert "Payload quick_check: ok" in details
    assert "Stage History" in details
    assert "prune_payload" in details
