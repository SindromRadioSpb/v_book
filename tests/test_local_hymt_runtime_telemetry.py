from unittest.mock import Mock, patch

from app.infra.local_mt.worker_process import WorkerResult
from app.infra.translators.base_provider import TranslationRequest
from app.infra.translators.providers.local_hymt_7b_gptq_provider import LocalHYMT7BGPTQProvider


def _mock_model_manager():
    manager = Mock()
    manager.is_installed.return_value = (True, None)
    manager.model_dir.return_value = "/fake/hymt7b/path"
    return manager


def _make_request(text: str, trace_id: str = "") -> TranslationRequest:
    return TranslationRequest(
        source_text=text,
        source_lang="he",
        target_lang="ru",
        trace_id=trace_id,
        options={},
    )


def test_translate_exposes_runtime_stage_timings():
    with patch(
        "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
        return_value=_mock_model_manager(),
    ):
        provider = LocalHYMT7BGPTQProvider()

    provider._run_worker_request = Mock(  # noqa: SLF001 - focused contract test
        return_value=WorkerResult(
            text="перевод",
            source_lang="he",
            target_lang="ru",
            inference_time_ms=42.0,
            runtime_metrics={
                "queue_wait_ms": 7.0,
                "gpu_wait_ms": 3.0,
                "load_ms": 11.0,
                "manager_wall_ms": 55.0,
                "batch_size": 1,
            },
        )
    )

    result = provider.translate(_make_request("שלום"))

    runtime = result.meta["runtime"]
    assert runtime["stage_timings_ms"]["queue_wait"] == 7
    assert runtime["stage_timings_ms"]["gpu_wait"] == 3
    assert runtime["stage_timings_ms"]["model_load"] == 11
    assert runtime["stage_timings_ms"]["worker_inference"] == 42
    assert runtime["stage_timings_ms"]["total"] == result.latency_ms
    assert runtime["batch"]["size"] == 1


def test_translate_batch_exposes_runtime_stage_timings():
    with patch(
        "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
        return_value=_mock_model_manager(),
    ):
        provider = LocalHYMT7BGPTQProvider()

    shared_metrics = {
        "queue_wait_ms": 5.0,
        "gpu_wait_ms": 2.0,
        "load_ms": 0.0,
        "manager_wall_ms": 80.0,
        "batch_size": 2,
        "batch_inference_total_ms": 60.0,
    }
    provider._run_worker_batch_requests = Mock(  # noqa: SLF001 - focused contract test
        return_value=[
            WorkerResult(
                text="один",
                source_lang="he",
                target_lang="ru",
                inference_time_ms=30.0,
                runtime_metrics=dict(shared_metrics),
            ),
            WorkerResult(
                text="два",
                source_lang="he",
                target_lang="ru",
                inference_time_ms=30.0,
                runtime_metrics=dict(shared_metrics),
            ),
        ]
    )

    results = provider.translate_batch([_make_request("שלום"), _make_request("עולם")])

    assert len(results) == 2
    for item in results:
        runtime = item.meta["runtime"]
        assert runtime["batch"]["size"] == 2
        assert runtime["batch"]["batch_inference_total_ms"] == 60
        assert runtime["stage_timings_ms"]["queue_wait"] == 5
        assert runtime["stage_timings_ms"]["worker_inference"] == 30
        assert runtime["stage_timings_ms"]["total"] == item.latency_ms
