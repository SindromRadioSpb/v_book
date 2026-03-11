from __future__ import annotations

from PyQt6.QtWidgets import QApplication

from app.domain.dto import (
    DerivedArtifactGovernanceSummaryDTO,
    DerivedArtifactMetricDTO,
)
from app.ui.dialogs.project_artifact_governance_dialog import (
    ProjectArtifactGovernanceDialog,
)


def _sample_summary() -> DerivedArtifactGovernanceSummaryDTO:
    return DerivedArtifactGovernanceSummaryDTO(
        project_id=1,
        project_name="Hebrew Wikipedia Baseline",
        is_reference_project=True,
        total_docs=387639,
        processed_docs=387639,
        snapshot_sentence_coverage_pct=38.1812,
        snapshot_doc_coverage_pct=30.9564,
        observability_note="Observational only. This view does not delete, compact, or backfill any data.",
        storage_note="Snapshot volume reuses the existing readiness aggregate because exact project-scoped snapshot row counts are too expensive on huge DBs.",
        lifecycle_note="Project-owned rows are deleted by explicit project delete paths.",
        snapshot_contract_note="Bounded staged validation exists for this workflow. Full-scale validation remains deferred.",
        last_refreshed_at="2026-03-11T10:05:00.000000Z",
        artifacts=[
            DerivedArtifactMetricDTO(
                artifact_key="lemma_doc_stat",
                display_name="lemma_doc_stat",
                ownership="project-owned stats",
                quantity_value=104177038,
                quantity_unit="rows",
                quantity_basis="exact project count",
                status="expected_large",
                summary="Expected large table at reference scale.",
                detail_lines=["Exact project row count via project_id."],
                maintenance_mode="reset_rebuild_only",
                maintenance_note="Use a future project-level reset/rebuild path instead of pruning by age.",
                maintenance_cli_hint="python scripts\\process_reference_corpus.py --db-path <db-path> --project-id 1 --reprocess-all --dry-run",
                maintenance_preflight_hint="python scripts\\process_reference_corpus.py --db-path <db-path> --project-id 1 --reprocess-all --backup-db-path <healthy-backup.db> --preflight-only",
            ),
            DerivedArtifactMetricDTO(
                artifact_key="sentence_nlp_snapshot",
                display_name="sentence_nlp_snapshot",
                ownership="project-owned sentence snapshots",
                quantity_value=5111646,
                quantity_unit="covered sentences",
                quantity_basis="snapshot readiness aggregate",
                status="coverage_partial",
                summary="Sentence coverage 38.18%; doc coverage 30.96%.",
                detail_lines=["Fully covered docs: 119,999 / 387,639."],
                maintenance_mode="reset_rebuild_only",
                maintenance_note="Do not prune snapshots by age.",
                maintenance_cli_hint="python scripts\\process_reference_corpus.py --db-path <db-path> --project-id 1 --reprocess-all --dry-run",
                maintenance_preflight_hint="python scripts\\process_reference_corpus.py --db-path <db-path> --project-id 1 --reprocess-all --backup-db-path <healthy-backup.db> --preflight-only",
            ),
            DerivedArtifactMetricDTO(
                artifact_key="processor_run",
                display_name="processor_run",
                ownership="project-owned telemetry",
                quantity_value=387613,
                quantity_unit="rows",
                quantity_basis="exact project count",
                status="retention_watch",
                summary="Operational telemetry is useful but needs retention planning.",
                detail_lines=["Status mix: ok=387,598, failed=15"],
                maintenance_mode="retention_available",
                maintenance_note="Use telemetry retention dry-run/apply, preserving non-ok and noted evidence rows.",
                maintenance_cli_hint="python scripts\\prune_project_telemetry.py --db-path <db-path> --project-id 1 --keep-latest-ok 200",
            ),
            DerivedArtifactMetricDTO(
                artifact_key="run_error",
                display_name="run_error",
                ownership="project-owned telemetry",
                quantity_value=15,
                quantity_unit="rows",
                quantity_basis="exact project count",
                status="low_volume",
                summary="Error telemetry is currently low-volume.",
                detail_lines=["Stage mix: crash_recovery=15"],
                maintenance_mode="retention_with_parent_runs",
                maintenance_note="Prune via parent processor_run retention only.",
            ),
        ],
    )


def test_project_artifact_governance_dialog_preserves_last_known_data_while_loading(qtbot):
    dialog = ProjectArtifactGovernanceDialog(1, "Hebrew Wikipedia Baseline", auto_refresh=False)
    qtbot.addWidget(dialog)

    summary = _sample_summary()
    dialog.set_summary(summary)
    assert dialog.total_docs_value.text() == "387,639"
    assert dialog.snapshot_coverage_value.text() == "38.18%"

    dialog.set_loading("Refreshing derived artifact governance...")

    assert dialog.total_docs_value.text() == "387,639"
    assert dialog.snapshot_coverage_value.text() == "38.18%"
    assert dialog.status_label.text() == "Refreshing derived artifact governance..."


def test_project_artifact_governance_dialog_renders_cards_and_notes(qtbot):
    dialog = ProjectArtifactGovernanceDialog(1, "Hebrew Wikipedia Baseline", auto_refresh=False)
    qtbot.addWidget(dialog)

    dialog.set_summary(_sample_summary())

    assert dialog.badge_label.text() == "Observational only"
    assert "Observational only" in dialog.note_label.text()
    assert "Snapshot volume reuses the existing readiness aggregate" in dialog.note_label.text()
    assert dialog._cards_layout.count() >= 4
    assert dialog.run_error_value.text() == "15"
    assert dialog.copy_telemetry_btn.isEnabled() is True
    assert dialog.copy_rebuild_btn.isEnabled() is True
    assert dialog.copy_rebuild_preflight_btn.isEnabled() is True


def test_project_artifact_governance_dialog_formats_relative_refresh(qtbot):
    dialog = ProjectArtifactGovernanceDialog(1, "Hebrew Wikipedia Baseline", auto_refresh=False)
    qtbot.addWidget(dialog)

    summary = _sample_summary()
    dialog.set_summary(summary)
    status = dialog._format_relative_refresh(summary.last_refreshed_at)

    assert "Refreshed" in status
    assert "2026-03-11 10:05 UTC" in status


def test_project_artifact_governance_dialog_copy_summary(qtbot):
    dialog = ProjectArtifactGovernanceDialog(1, "Hebrew Wikipedia Baseline", auto_refresh=False)
    qtbot.addWidget(dialog)
    dialog.set_summary(_sample_summary())

    app = QApplication.instance()
    assert app is not None
    dialog.copy_summary_to_clipboard()

    text = app.clipboard().text()
    assert "Derived Data Governance - Hebrew Wikipedia Baseline (#1)" in text
    assert "lemma_doc_stat" in text
    assert "sentence_nlp_snapshot" in text
    assert "Maintenance mode: Retention available" in text


def test_project_artifact_governance_dialog_can_copy_telemetry_cli(qtbot):
    dialog = ProjectArtifactGovernanceDialog(1, "Hebrew Wikipedia Baseline", auto_refresh=False)
    qtbot.addWidget(dialog)
    dialog.set_summary(_sample_summary())

    app = QApplication.instance()
    assert app is not None
    dialog.copy_telemetry_cli()

    text = app.clipboard().text()
    assert "prune_project_telemetry.py" in text
    assert "--project-id 1" in text


def test_project_artifact_governance_dialog_can_copy_rebuild_cli(qtbot):
    dialog = ProjectArtifactGovernanceDialog(1, "Hebrew Wikipedia Baseline", auto_refresh=False)
    qtbot.addWidget(dialog)
    dialog.set_summary(_sample_summary())

    app = QApplication.instance()
    assert app is not None
    dialog.copy_rebuild_cli()

    text = app.clipboard().text()
    assert "process_reference_corpus.py" in text
    assert "--project-id 1" in text
    assert "--reprocess-all" in text
    assert "--dry-run" in text


def test_project_artifact_governance_dialog_can_copy_rebuild_preflight_cli(qtbot):
    dialog = ProjectArtifactGovernanceDialog(1, "Hebrew Wikipedia Baseline", auto_refresh=False)
    qtbot.addWidget(dialog)
    dialog.set_summary(_sample_summary())

    app = QApplication.instance()
    assert app is not None
    dialog.copy_rebuild_preflight_cli()

    text = app.clipboard().text()
    assert "process_reference_corpus.py" in text
    assert "--project-id 1" in text
    assert "--reprocess-all" in text
    assert "--backup-db-path" in text
    assert "--preflight-only" in text
