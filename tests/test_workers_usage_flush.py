"""Tests for batch-end forced flush of deferred MT usage counters."""

from unittest.mock import Mock

from app.services.batch_mt_translate_service import (
    BatchTranslateOptions,
    BatchTranslateResult,
)
from app.ui.workers import BatchTranslateWorker, TranslateAllFilteredWorker


def test_batch_translate_worker_forces_usage_flush(monkeypatch):
    """Selected-rows worker should force-flush usage queue when batch ends."""

    class DummySessionCtx:
        def __enter__(self):
            return Mock()

        def __exit__(self, exc_type, exc, tb):
            return False

    class DummyDB:
        def get_session(self):
            return DummySessionCtx()

    class DummyBatchService:
        def execute_batch(self, session, items, options, progress_callback, cancel_check, item_callback=None):
            return BatchTranslateResult(
                total=1,
                succeeded=1,
                skipped=0,
                failed=0,
                row_results=[],
                trace_id="test",
                elapsed_ms=1,
            )

    flush_reasons = []

    monkeypatch.setattr(
        "app.services.db_service.DBService.get_instance",
        lambda: DummyDB(),
    )
    monkeypatch.setattr(
        "app.services.batch_mt_translate_service.BatchMTTranslateService",
        DummyBatchService,
    )
    monkeypatch.setattr(
        "app.ui.workers._flush_mt_usage_queue",
        lambda reason: flush_reasons.append(reason),
    )

    worker = BatchTranslateWorker(
        items=[object()],
        options=BatchTranslateOptions(
            provider_mode="chain",
            write_mode="FILL_EMPTY",
            chunk_size=50,
        ),
        tab_type="dictionary",
    )
    worker.run()

    assert flush_reasons == ["batch_translate:dictionary"]


def test_translate_all_filtered_worker_forces_usage_flush_on_empty(monkeypatch):
    """All-filtered worker should force-flush usage queue even on empty target set."""

    class DummySessionCtx:
        def __enter__(self):
            return Mock()

        def __exit__(self, exc_type, exc, tb):
            return False

    class DummyDB:
        def get_session(self):
            return DummySessionCtx()

    class DummyAdminService:
        def count_tm_ids_for_translation(self, session, filters, write_mode):
            return 0

    flush_reasons = []

    monkeypatch.setattr(
        "app.services.db_service.DBService.get_instance",
        lambda: DummyDB(),
    )
    monkeypatch.setattr(
        "app.services.translation_admin_service.TranslationAdminService",
        DummyAdminService,
    )
    monkeypatch.setattr(
        "app.ui.workers._flush_mt_usage_queue",
        lambda reason: flush_reasons.append(reason),
    )

    worker = TranslateAllFilteredWorker(
        entity_type="tm_entry",
        project_id=None,
        filters={},
        provider_mode="chain",
        write_mode="FILL_EMPTY",
    )
    worker.run()

    assert flush_reasons == ["translate_all_filtered:tm_entry:empty"]
