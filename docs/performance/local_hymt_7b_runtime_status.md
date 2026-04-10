# local_hymt_7b_gptq Runtime Status

Last updated: 2026-04-10
Current lifecycle baseline commit: `107d959`
Current telemetry baseline commit: `460cd08`
Scope: `local_hymt_7b_gptq` runtime only. No global translation-stack redesign.

## Purpose

This document is the handoff source of truth for the `local_hymt_7b_gptq` runtime on the target machine:

- Windows 11
- Ryzen 5 5600G
- 32 GB RAM
- RTX 3070 8 GB
- NVMe SSD

It records:

- what is already implemented,
- what the current runtime architecture is,
- what metrics were measured,
- what risks remain,
- which patches are approved next.

## Current Architecture

Canonical runtime owner:

- `app/infra/local_mt/provider_manager.py`

Key components:

- `LocalMTProviderManager`
  - single-flight worker load per `(backend, model_id)`
  - bounded queue
  - serialized GPU execution for GPU-heavy local MT backends
  - idle unload
  - explicit unload
  - bulk shutdown on unregister/app exit
- `LocalHYMTProvider`
  - lazy model availability check
  - manager-backed worker execution
  - batch translation API
  - request-local DB session usage
  - runtime/lifecycle meta in `TranslationResult.meta`
- `LocalHYMT7BGPTQProvider`
  - 7B-specific policy
  - idle timeout: `45s`
  - max pending requests: `2`
  - adaptive micro-batch ceiling: `4`
- `worker_process.py`
  - subprocess model hosting
  - batched causal inference path
  - cleanup on shutdown with `gc.collect()`, CUDA sync, cache cleanup

## What Is Already Done

Implemented before PATCH-04:

- canonical lifecycle manager
- lazy load
- explicit unload
- idle-timeout unload
- double-load race fix
- bounded queue
- serialized GPU execution
- batched HY-MT execution path
- request-local DB session
- provider unregister -> manager shutdown

## Current Runtime Contract

Current lifecycle states:

- `UNLOADED`
- `LOADING`
- `READY`
- `BUSY`
- `IDLE`
- `UNLOADING`
- `FAILED`

Current runtime rules:

- only one canonical worker may own `local_hymt_7b_gptq`
- no unload while `active_requests > 0` or `pending_requests > 0`
- idle unload is allowed only after queue drain
- GPU-heavy local MT work is serialized through the provider manager
- force-HY-MT TM batch path uses batched provider execution instead of per-row single inference

PATCH-08 lifecycle hardening contract:

- `shutdown_all()` enters a manager-level shutdown phase and rejects new requests immediately
- requests already admitted before shutdown are allowed to drain until the bounded `graceful_timeout_s`
- idle timers are cancelled during shutdown, so no new idle-unload cycle is scheduled while inflight work drains
- after the graceful window, any still-resident worker is forcibly unloaded as the last-resort shutdown path
- after shutdown completes, the manager returns to accepting mode for the next cold start

## Measured Performance

### Before lifecycle/batch patch

Measured on the target machine with `tencent/HY-MT1.5-7B-GPTQ-Int4`:

- provider init: `31.068s`
- first request after init: `5.426s`
- cold path to first result: `36.494s`
- warm average single-request latency: `16.279s`
- warm throughput: `0.0614 seg/s`
- unload/shutdown: `5.204s`
- VRAM: `1333 MB -> 6718 MB -> 1350 MB`

Observed problem:

- shutdown still hit force terminate in practice, so graceful unload was not reliable enough

### After lifecycle/batch patch

Measured on the same machine:

- provider init: `0.003s`
- cold path to first result: `17.227s`
- warm average single-request latency: `5.082s`
- warm throughput: `0.1968 seg/s`
- unload: `5.001s`
- reload first request: `17.386s`
- VRAM: `1413 MB -> 6813 MB -> 1466 MB -> 1311 MB final`

### Sequential vs batched comparison

Warm model, same input set:

| Segments | Sequential | Batched | Speedup |
|---|---:|---:|---:|
| 2 | `8.455s` | `5.319s` | `1.59x` |
| 4 | `33.337s` | `23.095s` | `1.44x` |
| 8 | `87.023s` | `56.534s` | `1.54x` |

## PATCH-04 Telemetry Surface

PATCH-04 extends runtime observability without changing the ownership model.

Manager snapshot now tracks:

- `state`
- `active_requests`
- `pending_requests`
- `load_count`
- `unload_count`
- `total_requests`
- `total_batches`
- `total_segments`
- `last_load_ms`
- `last_unload_ms`
- `last_request_ms`
- `last_queue_wait_ms`
- `last_gpu_wait_ms`
- `last_batch_size`
- `avg_queue_wait_ms`
- `avg_gpu_wait_ms`
- `avg_inference_ms_per_segment`
- `max_observed_queue_depth`
- `last_unload_reason`
- `unload_reasons`
- resource snapshots captured around load/unload

Provider result meta now exposes:

- `meta["runtime"]["stage_timings_ms"]`
  - `preprocess`
  - `queue_wait`
  - `gpu_wait`
  - `model_load`
  - `worker_inference`
  - `postprocess`
  - `total`
- `meta["runtime"]["batch"]`
  - `size`
  - `manager_wall_ms`
  - `batch_inference_total_ms`

Batch MT row results for the HY-MT force path may now carry:

- `meta["runtime"]["translate_batch_ms"]`
- `meta["runtime"]["persist_ms"]`
- `meta["runtime"]["provider_runtime"]`

## PATCH-05 Adaptive Micro-Batching

PATCH-05 keeps the existing lifecycle owner and changes only batch planning in
`LocalHYMTProvider.translate_batch()`.

Current planner inputs:

- candidate batch size up to provider ceiling
- prompt payload length
- latest GPU headroom snapshot from manager telemetry
- historical average inference time per segment
- queue depth

Current 7B policy:

- `max batch size = 4`
- short prompts may batch at `4`
- large prompt budgets collapse to `1`
- low GPU headroom collapses to `1` or `2`
- active queue depth caps fairness at `2`

### PATCH-05 measured result

Warm model, same 8 short segments on the target machine:

| Mode | Time | Throughput |
|---|---:|---:|
| Fixed batch `2` | `46.654s` | `0.171 seg/s` |
| Adaptive batch `<=4` | `38.490s` | `0.208 seg/s` |

Observed result:

- adaptive planner selected `4` for all 8 short segments
- wall-clock improved by about `17.5%`
- throughput improved by about `21.6%`
- average per-item latency increased, which is acceptable for bulk TM-style throughput mode

## PATCH-06A Forced Unload On Provider Switch

PATCH-06A adds an explicit provider-switch preparation step for force-provider
paths and local lazy init.

Current behavior:

- before explicit switch to another provider, idle GPU-heavy local providers are
  asked to unload via the canonical manager
- the target provider is never unloaded during its own switch
- busy providers are never force-killed by this path; they are reported as
  `skipped_busy`
- chain fallback is intentionally unchanged in this patch to avoid adding reload
  churn to fallback latency

Current switch entrypoints covered:

- force-provider path in batch MT service
- force-provider path in user-dictionary/global translation worker
- local provider lazy initialization

Current contract:

- explicit provider switch may proactively free VRAM
- active or queued HY-MT work is preserved
- provider objects can remain registered; only worker residency is reduced

## Remaining Risks

Still open after PATCH-08:

- there is no cross-provider GPU arbiter yet
- unload is not yet pressure-triggered
- persist path is still inline; telemetry must confirm whether it is a real bottleneck before PATCH-07

Still open after PATCH-05:

- adaptive planner is heuristic, not pressure-event-driven
- no direct VRAM allocator telemetry from inside the worker process yet
- planner is currently tuned for 7B short-burst translation, not mixed-provider fairness

Still open after PATCH-06A:

- unload on switch is event-driven, not memory-pressure-driven
- cloud/chain paths still rely on idle timeout rather than global GPU arbitration
- provider switch fairness across all GPU-heavy subsystems still requires PATCH-09

## Approved Next Patch Order

1. `PATCH-06B` memory-pressure-triggered unload
2. `PATCH-07` background persist queue, only if PATCH-04 telemetry proves persist is a bottleneck
3. `PATCH-09` long-term global GPU arbiter

## Test Matrix

Current mandatory checks for this runtime:

- targeted provider/manager unit tests
- import smoke
- cold/warm benchmark
- sequential vs batched benchmark
- fixed `2` vs adaptive `<=4` benchmark
- provider switch unload regression tests

Still missing but approved next:

- pressure-triggered unload smoke

## Handoff Notes

For the next engineer or model:

- do not revisit lifecycle ownership; it is already solved at the correct layer
- do not build a second worker owner path inside the provider or UI
- use PATCH-04 telemetry before proposing PATCH-07
- keep all GPU-heavy decisions realistic for `8 GB VRAM`
- avoid architecture that keeps the 7B model loaded indefinitely "just in case"
