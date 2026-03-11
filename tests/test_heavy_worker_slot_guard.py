"""Regression tests for heavy worker runtime slot guards."""

from __future__ import annotations

from pathlib import Path

from app.services.operations_center import OperationEntry, OperationsCenterBusyError
from app.services.project_exchange.dto import ImportOptions
from app.services.project_exchange.worker import ProjectImportWorker
from app.ui.workers import ImportWorker


class _FakeOpsCenter:
    def __init__(self, blocking_name: str, blocking_category: str):
        self._error = OperationsCenterBusyError(
            "blocked",
            [OperationEntry(op_id="op-1", name=blocking_name, category=blocking_category)],
        )

    def register(self, *_args, **_kwargs):
        raise self._error

    def unregister(self, _op_id):
        return None


def test_project_import_worker_reports_busy_when_heavy_slot_taken(monkeypatch, tmp_path):
    from app.services.operations_center import OperationsCenter

    monkeypatch.setattr(
        OperationsCenter,
        "instance",
        classmethod(lambda cls: _FakeOpsCenter("NLP Process (42 docs)", "nlp_process")),
    )

    worker = ProjectImportWorker(tmp_path / "bundle.hdle", ImportOptions())
    errors = []
    worker.error.connect(errors.append)
    worker.run()

    assert errors
    assert "Project Import" in errors[0]
    assert "NLP Process (42 docs)" in errors[0]


def test_dictionary_import_worker_reports_busy_when_heavy_slot_taken(monkeypatch):
    from app.services.operations_center import OperationsCenter

    monkeypatch.setattr(
        OperationsCenter,
        "instance",
        classmethod(lambda cls: _FakeOpsCenter("Project Import (bundle.hdle)", "project_import")),
    )

    worker = ImportWorker(
        file_path=str(Path("dictionary.csv")),
        project_id=None,
        scope="global",
        on_conflict="skip",
        normalize_mode="strict",
        default_kind="lemma",
        default_status="candidate",
    )
    errors = []
    worker.error.connect(errors.append)
    worker.run()

    assert errors
    assert "Dictionary Import" in errors[0]
    assert "Project Import (bundle.hdle)" in errors[0]
