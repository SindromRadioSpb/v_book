from pathlib import Path
from unittest.mock import Mock, patch

from app.infra.local_mt.provider_manager import (
    ProviderLifecycleState,
    get_local_mt_provider_manager,
)
from app.infra.local_mt.worker_process import WorkerRequest, WorkerResult


def setup_function():
    manager = get_local_mt_provider_manager()
    manager.shutdown_all()
    manager._slots.clear()  # noqa: SLF001 - test reset


def test_manager_reuses_worker_for_repeated_requests(tmp_path):
    manager = get_local_mt_provider_manager()
    fake_worker = Mock()
    fake_worker.translate.return_value = WorkerResult(
        text="ok",
        source_lang="he",
        target_lang="ru",
        inference_time_ms=12.0,
    )

    with patch(
        "app.infra.local_mt.provider_manager.start_worker",
        return_value=fake_worker,
    ) as mock_start:
        request = WorkerRequest(text="a", source_lang="he", target_lang="ru")
        first_result = manager.run_request(
            model_path=tmp_path / "model",
            backend="transformers_causal",
            model_id="test/model",
            timeout=30.0,
            worker_request=request,
            idle_timeout_s=999.0,
        )
        second_result = manager.run_request(
            model_path=tmp_path / "model",
            backend="transformers_causal",
            model_id="test/model",
            timeout=30.0,
            worker_request=request,
            idle_timeout_s=999.0,
        )

    assert mock_start.call_count == 1
    snapshot = manager.get_state_snapshot("transformers_causal", "test/model")
    assert snapshot["load_count"] == 1
    assert snapshot["total_requests"] == 2
    assert snapshot["total_segments"] == 2
    assert snapshot["state"] == ProviderLifecycleState.IDLE.value
    assert first_result.runtime_metrics["batch_size"] == 1
    assert second_result.runtime_metrics["batch_size"] == 1


def test_manager_unloads_model_explicitly(tmp_path):
    manager = get_local_mt_provider_manager()
    fake_worker = Mock()
    fake_worker.translate.return_value = WorkerResult(
        text="ok",
        source_lang="he",
        target_lang="ru",
        inference_time_ms=12.0,
    )

    with patch(
        "app.infra.local_mt.provider_manager.start_worker",
        return_value=fake_worker,
    ):
        manager.run_request(
            model_path=tmp_path / "model",
            backend="transformers_causal",
            model_id="test/model",
            timeout=30.0,
            worker_request=WorkerRequest(text="a", source_lang="he", target_lang="ru"),
            idle_timeout_s=999.0,
        )

    assert manager.unload_model(
        backend="transformers_causal",
        model_id="test/model",
        reason="test",
        force=True,
    )
    fake_worker.shutdown.assert_called_once()
    snapshot = manager.get_state_snapshot("transformers_causal", "test/model")
    assert snapshot["state"] == ProviderLifecycleState.UNLOADED.value


def test_manager_batch_requests_use_single_worker_roundtrip(tmp_path):
    manager = get_local_mt_provider_manager()
    fake_worker = Mock()
    fake_worker.translate_batch.return_value = [
        WorkerResult(text="one", source_lang="he", target_lang="ru", inference_time_ms=10.0),
        WorkerResult(text="two", source_lang="he", target_lang="ru", inference_time_ms=10.0),
    ]

    with patch(
        "app.infra.local_mt.provider_manager.start_worker",
        return_value=fake_worker,
    ):
        results = manager.run_batch_requests(
            model_path=tmp_path / "model",
            backend="transformers_causal",
            model_id="test/model",
            timeout=30.0,
            worker_requests=[
                WorkerRequest(text="a", source_lang="he", target_lang="ru"),
                WorkerRequest(text="b", source_lang="he", target_lang="ru"),
            ],
            idle_timeout_s=999.0,
        )

    assert [item.text for item in results] == ["one", "two"]
    fake_worker.translate_batch.assert_called_once()
    assert results[0].runtime_metrics["batch_size"] == 2
    snapshot = manager.get_state_snapshot("transformers_causal", "test/model")
    assert snapshot["total_batches"] == 1
    assert snapshot["total_segments"] == 2
