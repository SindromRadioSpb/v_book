from unittest.mock import Mock, patch

from app.infra.local_mt.worker_process import WorkerResult
from app.infra.translators.base_provider import TranslationRequest
from app.infra.translators.providers.local_hymt_7b_gptq_provider import LocalHYMT7BGPTQProvider


def _mock_model_manager():
    manager = Mock()
    manager.is_installed.return_value = (True, None)
    manager.model_dir.return_value = "/fake/hymt7b/path"
    return manager


def _make_request(text: str) -> TranslationRequest:
    return TranslationRequest(
        source_text=text,
        source_lang="he",
        target_lang="ru",
        options={},
    )


def _snapshot(
    *, used_mb: int, total_mb: int, avg_inference_ms: float = 4000.0
) -> dict[str, object]:
    return {
        "state": "IDLE",
        "pending_requests": 0,
        "avg_inference_ms_per_segment": avg_inference_ms,
        "last_resource_snapshot": {
            "gpu_memory": {
                "used_mb": used_mb,
                "total_mb": total_mb,
            }
        },
    }


def test_adaptive_batching_uses_four_way_batch_for_short_prompts():
    with patch(
        "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
        return_value=_mock_model_manager(),
    ):
        provider = LocalHYMT7BGPTQProvider()

    batch_sizes: list[int] = []

    def fake_run(worker_requests):
        batch_sizes.append(len(worker_requests))
        return [
            WorkerResult(
                text=f"перевод-{idx}",
                source_lang="he",
                target_lang="ru",
                inference_time_ms=20.0,
                runtime_metrics={"batch_size": len(worker_requests)},
            )
            for idx, _ in enumerate(worker_requests)
        ]

    provider._run_worker_batch_requests = Mock(side_effect=fake_run)  # noqa: SLF001
    with patch.object(
        provider._provider_manager,  # noqa: SLF001 - focused planner test
        "get_state_snapshot",
        return_value=_snapshot(used_mb=5400, total_mb=8192),
    ):
        results = provider.translate_batch([_make_request("שלום")] * 4)

    assert len(results) == 4
    assert batch_sizes == [4]
    assert results[0].meta["runtime"]["batch"]["adaptive_plan"]["selected_size"] == 4


def test_adaptive_batching_reduces_to_singletons_for_large_prompts():
    with patch(
        "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
        return_value=_mock_model_manager(),
    ):
        provider = LocalHYMT7BGPTQProvider()

    batch_sizes: list[int] = []

    def fake_run(worker_requests):
        batch_sizes.append(len(worker_requests))
        return [
            WorkerResult(
                text=f"перевод-{idx}",
                source_lang="he",
                target_lang="ru",
                inference_time_ms=20.0,
                runtime_metrics={"batch_size": len(worker_requests)},
            )
            for idx, _ in enumerate(worker_requests)
        ]

    provider._run_worker_batch_requests = Mock(side_effect=fake_run)  # noqa: SLF001

    large_text = "א" * 2600
    with patch.object(
        provider._provider_manager,  # noqa: SLF001 - focused planner test
        "get_state_snapshot",
        return_value=_snapshot(used_mb=5400, total_mb=8192),
    ):
        results = provider.translate_batch([_make_request(large_text) for _ in range(3)])

    assert len(results) == 3
    assert batch_sizes == [1, 1, 1]
    assert results[0].meta["runtime"]["batch"]["adaptive_plan"]["selected_size"] == 1
    assert "prompt_budget_large" in results[0].meta["runtime"]["batch"]["adaptive_plan"]["reasons"]


def test_adaptive_batching_caps_batch_when_gpu_headroom_is_low():
    with patch(
        "app.infra.translators.providers.local_hymt_provider.ModelResourceManager",
        return_value=_mock_model_manager(),
    ):
        provider = LocalHYMT7BGPTQProvider()

    batch_sizes: list[int] = []

    def fake_run(worker_requests):
        batch_sizes.append(len(worker_requests))
        return [
            WorkerResult(
                text=f"перевод-{idx}",
                source_lang="he",
                target_lang="ru",
                inference_time_ms=20.0,
                runtime_metrics={"batch_size": len(worker_requests)},
            )
            for idx, _ in enumerate(worker_requests)
        ]

    provider._run_worker_batch_requests = Mock(side_effect=fake_run)  # noqa: SLF001
    with patch.object(
        provider._provider_manager,  # noqa: SLF001 - focused planner test
        "get_state_snapshot",
        return_value=_snapshot(used_mb=7100, total_mb=8192),
    ):
        results = provider.translate_batch([_make_request("שלום")] * 3)

    assert len(results) == 3
    assert batch_sizes == [1, 1, 1]
    assert "gpu_headroom_lt_1100" in results[0].meta["runtime"]["batch"]["adaptive_plan"]["reasons"]
