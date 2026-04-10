import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

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


def test_shutdown_blocks_new_requests_and_drains_inflight_work(tmp_path):
    manager = get_local_mt_provider_manager()
    fake_worker = Mock()
    request_started = threading.Event()
    allow_finish = threading.Event()

    def _blocking_translate(_request):
        request_started.set()
        assert allow_finish.wait(timeout=2.0)
        return WorkerResult(
            text="ok",
            source_lang="he",
            target_lang="ru",
            inference_time_ms=12.0,
        )

    fake_worker.translate.side_effect = _blocking_translate

    with patch(
        "app.infra.local_mt.provider_manager.start_worker",
        return_value=fake_worker,
    ):
        result_holder = {}

        def _run_request():
            result_holder["result"] = manager.run_request(
                model_path=tmp_path / "model",
                backend="transformers_causal",
                model_id="test/model",
                timeout=30.0,
                worker_request=WorkerRequest(text="a", source_lang="he", target_lang="ru"),
                idle_timeout_s=999.0,
            )

        request_thread = threading.Thread(target=_run_request)
        request_thread.start()
        assert request_started.wait(timeout=1.0)

        shutdown_thread = threading.Thread(
            target=manager.shutdown_all, kwargs={"graceful_timeout_s": 1.0}
        )
        shutdown_thread.start()

        deadline = time.time() + 1.0
        while not manager.is_shutdown_requested() and time.time() < deadline:
            time.sleep(0.01)
        assert manager.is_shutdown_requested() is True

        with pytest.raises(RuntimeError, match="shutting down"):
            manager.run_request(
                model_path=tmp_path / "model",
                backend="transformers_causal",
                model_id="test/model",
                timeout=30.0,
                worker_request=WorkerRequest(text="b", source_lang="he", target_lang="ru"),
                idle_timeout_s=999.0,
            )

        allow_finish.set()
        request_thread.join(timeout=2.0)
        shutdown_thread.join(timeout=2.0)

    assert result_holder["result"].text == "ok"
    fake_worker.shutdown.assert_called_once()
    snapshot = manager.get_state_snapshot("transformers_causal", "test/model")
    assert snapshot["state"] == ProviderLifecycleState.UNLOADED.value
    assert snapshot["shutdown_requested"] is False
    assert snapshot["unload_reasons"]["shutdown_all"] == 1


def test_followup_request_cancels_previous_idle_unload_timer(tmp_path):
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
        request = WorkerRequest(text="a", source_lang="he", target_lang="ru")
        manager.run_request(
            model_path=tmp_path / "model",
            backend="transformers_causal",
            model_id="test/model",
            timeout=30.0,
            worker_request=request,
            idle_timeout_s=0.05,
        )
        time.sleep(0.03)
        manager.run_request(
            model_path=tmp_path / "model",
            backend="transformers_causal",
            model_id="test/model",
            timeout=30.0,
            worker_request=request,
            idle_timeout_s=0.05,
        )
        time.sleep(0.03)
        mid_snapshot = manager.get_state_snapshot("transformers_causal", "test/model")
        assert mid_snapshot["unload_count"] == 0

        deadline = time.time() + 0.5
        final_snapshot = manager.get_state_snapshot("transformers_causal", "test/model")
        while (
            final_snapshot["state"] != ProviderLifecycleState.UNLOADED.value
            and time.time() < deadline
        ):
            time.sleep(0.01)
            final_snapshot = manager.get_state_snapshot("transformers_causal", "test/model")

    assert final_snapshot["state"] == ProviderLifecycleState.UNLOADED.value
    assert final_snapshot["unload_count"] == 1
    assert final_snapshot["last_unload_reason"] == "idle_timeout"


def test_repeated_load_unload_cycles_leave_clean_unloaded_state(tmp_path):
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
        request = WorkerRequest(text="a", source_lang="he", target_lang="ru")
        for index in range(4):
            manager.run_request(
                model_path=tmp_path / "model",
                backend="transformers_causal",
                model_id="test/model",
                timeout=30.0,
                worker_request=request,
                idle_timeout_s=999.0,
            )
            assert manager.unload_model(
                backend="transformers_causal",
                model_id="test/model",
                reason=f"cycle_{index}",
                force=False,
            )

    snapshot = manager.get_state_snapshot("transformers_causal", "test/model")
    assert snapshot["state"] == ProviderLifecycleState.UNLOADED.value
    assert snapshot["load_count"] == 4
    assert snapshot["unload_count"] == 4
    assert snapshot["total_requests"] == 4
