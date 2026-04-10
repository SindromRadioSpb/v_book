"""Canonical lifecycle manager for local MT worker processes.

Focus:
- single-flight worker load per model/backend pair
- canonical ownership of worker subprocesses
- bounded queueing / serialized GPU access for HY-MT models
- idle-time unload with explicit state tracking
- graceful bulk shutdown on app exit
"""

from __future__ import annotations

import atexit
import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .worker_process import LocalMTWorker, WorkerRequest, WorkerResult, start_worker

logger = logging.getLogger(__name__)


class ProviderLifecycleState(StrEnum):
    UNLOADED = "UNLOADED"
    LOADING = "LOADING"
    READY = "READY"
    BUSY = "BUSY"
    IDLE = "IDLE"
    UNLOADING = "UNLOADING"
    FAILED = "FAILED"


@dataclass(slots=True)
class WorkerSlot:
    key: tuple[str, str]
    model_path: Path
    backend: str
    model_id: str
    timeout: float
    idle_timeout_s: float
    max_pending_requests: int
    is_gpu_heavy: bool
    worker: LocalMTWorker | None = None
    state: ProviderLifecycleState = ProviderLifecycleState.UNLOADED
    active_requests: int = 0
    pending_requests: int = 0
    last_error: str | None = None
    last_used_monotonic: float = 0.0
    load_count: int = 0
    unload_count: int = 0
    total_requests: int = 0
    total_batches: int = 0
    total_segments: int = 0
    last_load_ms: float = 0.0
    last_unload_ms: float = 0.0
    last_request_ms: float = 0.0
    last_queue_wait_ms: float = 0.0
    last_gpu_wait_ms: float = 0.0
    last_batch_size: int = 0
    total_queue_wait_ms: float = 0.0
    total_gpu_wait_ms: float = 0.0
    total_inference_ms: float = 0.0
    total_wall_ms: float = 0.0
    max_observed_queue_depth: int = 0
    last_unload_reason: str | None = None
    unload_reasons: dict[str, int] = field(default_factory=dict)
    last_resource_snapshot: dict[str, object] | None = None
    last_load_resource_snapshot: dict[str, object] | None = None
    last_unload_resource_snapshot: dict[str, object] | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)
    condition: threading.Condition = field(init=False)
    idle_timer: threading.Timer | None = None

    def __post_init__(self) -> None:
        self.condition = threading.Condition(self.lock)


class LocalMTProviderManager:
    """Singleton manager for local MT worker lifecycles."""

    _instance: LocalMTProviderManager | None = None
    _instance_lock = threading.Lock()
    _PRESSURE_MIN_HEADROOM_MB = 1400
    _PRESSURE_MAX_USED_RATIO = 0.84

    def __new__(cls) -> LocalMTProviderManager:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_once()
        return cls._instance

    def _init_once(self) -> None:
        self._slots: dict[tuple[str, str], WorkerSlot] = {}
        self._slots_lock = threading.RLock()
        self._gpu_execution_lock = threading.Lock()
        self._shutdown_event = threading.Event()
        atexit.register(self.shutdown_all)

    @staticmethod
    def _is_gpu_heavy_backend(backend: str, model_id: str) -> bool:
        return backend == "transformers_causal" or "gptq" in model_id.lower()

    def get_slot(
        self,
        *,
        model_path: Path,
        backend: str,
        model_id: str,
        timeout: float,
        idle_timeout_s: float,
        max_pending_requests: int,
    ) -> WorkerSlot:
        key = (backend, model_id)
        with self._slots_lock:
            slot = self._slots.get(key)
            if slot is None:
                slot = WorkerSlot(
                    key=key,
                    model_path=model_path,
                    backend=backend,
                    model_id=model_id,
                    timeout=timeout,
                    idle_timeout_s=idle_timeout_s,
                    max_pending_requests=max_pending_requests,
                    is_gpu_heavy=self._is_gpu_heavy_backend(backend, model_id),
                )
                self._slots[key] = slot
            else:
                slot.model_path = model_path
                slot.timeout = timeout
                slot.idle_timeout_s = idle_timeout_s
                slot.max_pending_requests = max_pending_requests
            return slot

    def get_state_snapshot(self, backend: str, model_id: str) -> dict[str, object]:
        key = (backend, model_id)
        with self._slots_lock:
            slot = self._slots.get(key)
            if slot is None:
                return {
                    "state": ProviderLifecycleState.UNLOADED.value,
                    "active_requests": 0,
                    "pending_requests": 0,
                    "shutdown_requested": self.is_shutdown_requested(),
                    "load_count": 0,
                    "unload_count": 0,
                    "total_requests": 0,
                    "total_batches": 0,
                    "total_segments": 0,
                }
        with slot.lock:
            avg_queue_wait_ms = (
                slot.total_queue_wait_ms / slot.total_requests if slot.total_requests else 0.0
            )
            avg_gpu_wait_ms = (
                slot.total_gpu_wait_ms / slot.total_requests if slot.total_requests else 0.0
            )
            avg_inference_ms_per_segment = (
                slot.total_inference_ms / slot.total_segments if slot.total_segments else 0.0
            )
            return {
                "state": slot.state.value,
                "active_requests": slot.active_requests,
                "pending_requests": slot.pending_requests,
                "shutdown_requested": self.is_shutdown_requested(),
                "load_count": slot.load_count,
                "unload_count": slot.unload_count,
                "total_requests": slot.total_requests,
                "total_batches": slot.total_batches,
                "total_segments": slot.total_segments,
                "last_load_ms": slot.last_load_ms,
                "last_unload_ms": slot.last_unload_ms,
                "last_request_ms": slot.last_request_ms,
                "last_queue_wait_ms": slot.last_queue_wait_ms,
                "last_gpu_wait_ms": slot.last_gpu_wait_ms,
                "last_batch_size": slot.last_batch_size,
                "avg_queue_wait_ms": avg_queue_wait_ms,
                "avg_gpu_wait_ms": avg_gpu_wait_ms,
                "avg_inference_ms_per_segment": avg_inference_ms_per_segment,
                "max_observed_queue_depth": slot.max_observed_queue_depth,
                "last_unload_reason": slot.last_unload_reason,
                "unload_reasons": dict(slot.unload_reasons),
                "last_resource_snapshot": dict(slot.last_resource_snapshot or {}),
                "last_load_resource_snapshot": dict(slot.last_load_resource_snapshot or {}),
                "last_unload_resource_snapshot": dict(slot.last_unload_resource_snapshot or {}),
                "last_error": slot.last_error,
            }

    def run_request(
        self,
        *,
        model_path: Path,
        backend: str,
        model_id: str,
        timeout: float,
        worker_request: WorkerRequest,
        idle_timeout_s: float,
        max_pending_requests: int = 2,
    ) -> WorkerResult:
        self._ensure_accepting_requests()
        slot = self.get_slot(
            model_path=model_path,
            backend=backend,
            model_id=model_id,
            timeout=timeout,
            idle_timeout_s=idle_timeout_s,
            max_pending_requests=max_pending_requests,
        )
        request_started = time.perf_counter()
        queue_wait_ms = self._acquire_queue_slot(slot)
        exec_lock = self._gpu_execution_lock if slot.is_gpu_heavy else threading.Lock()
        try:
            exec_wait_started = time.perf_counter()
            with exec_lock:
                gpu_wait_ms = (time.perf_counter() - exec_wait_started) * 1000
                worker, load_ms = self._ensure_worker_loaded(slot)
                started = time.perf_counter()
                result = worker.translate(worker_request)
                slot.last_request_ms = (time.perf_counter() - started) * 1000
                wall_ms = (time.perf_counter() - request_started) * 1000
                self._record_request_metrics(
                    slot=slot,
                    queue_wait_ms=queue_wait_ms,
                    gpu_wait_ms=gpu_wait_ms,
                    batch_size=1,
                    wall_ms=wall_ms,
                    inference_ms=result.inference_time_ms,
                )
                result.runtime_metrics = {
                    "queue_wait_ms": queue_wait_ms,
                    "gpu_wait_ms": gpu_wait_ms,
                    "load_ms": load_ms,
                    "manager_wall_ms": wall_ms,
                    "batch_size": 1,
                }
                return result
        finally:
            self._release_queue_slot(slot)

    def run_batch_requests(
        self,
        *,
        model_path: Path,
        backend: str,
        model_id: str,
        timeout: float,
        worker_requests: list[WorkerRequest],
        idle_timeout_s: float,
        max_pending_requests: int = 2,
    ) -> list[WorkerResult]:
        if not worker_requests:
            return []
        self._ensure_accepting_requests()
        slot = self.get_slot(
            model_path=model_path,
            backend=backend,
            model_id=model_id,
            timeout=timeout,
            idle_timeout_s=idle_timeout_s,
            max_pending_requests=max_pending_requests,
        )
        request_started = time.perf_counter()
        queue_wait_ms = self._acquire_queue_slot(slot)
        exec_lock = self._gpu_execution_lock if slot.is_gpu_heavy else threading.Lock()
        try:
            exec_wait_started = time.perf_counter()
            with exec_lock:
                gpu_wait_ms = (time.perf_counter() - exec_wait_started) * 1000
                worker, load_ms = self._ensure_worker_loaded(slot)
                started = time.perf_counter()
                results = worker.translate_batch(worker_requests)
                slot.last_request_ms = (time.perf_counter() - started) * 1000
                wall_ms = (time.perf_counter() - request_started) * 1000
                inference_total_ms = sum(item.inference_time_ms for item in results)
                batch_size = len(worker_requests)
                self._record_request_metrics(
                    slot=slot,
                    queue_wait_ms=queue_wait_ms,
                    gpu_wait_ms=gpu_wait_ms,
                    batch_size=batch_size,
                    wall_ms=wall_ms,
                    inference_ms=inference_total_ms,
                )
                shared_metrics = {
                    "queue_wait_ms": queue_wait_ms,
                    "gpu_wait_ms": gpu_wait_ms,
                    "load_ms": load_ms,
                    "manager_wall_ms": wall_ms,
                    "batch_size": batch_size,
                    "batch_inference_total_ms": inference_total_ms,
                }
                for item in results:
                    item.runtime_metrics = dict(shared_metrics)
                return results
        finally:
            self._release_queue_slot(slot)

    def unload_model(
        self,
        *,
        backend: str,
        model_id: str,
        reason: str = "manual",
        force: bool = False,
    ) -> bool:
        key = (backend, model_id)
        with self._slots_lock:
            slot = self._slots.get(key)
        if slot is None:
            return False
        return self._unload_slot(slot, reason=reason, force=force)

    def shutdown_all(self, graceful_timeout_s: float = 15.0) -> None:
        self._shutdown_event.set()
        with self._slots_lock:
            slots = list(self._slots.values())
        for slot in slots:
            with slot.lock:
                self._cancel_idle_timer(slot)
                slot.condition.notify_all()
        deadline = time.monotonic() + max(0.0, graceful_timeout_s)
        try:
            for slot in slots:
                self._wait_for_slot_drain(slot, deadline=deadline)
            for slot in slots:
                try:
                    force = self._slot_has_inflight_work(slot)
                    self._unload_slot(slot, reason="shutdown_all", force=force)
                except Exception as exc:
                    logger.debug(
                        "LocalMTProviderManager shutdown skipped for %s: %s", slot.key, exc
                    )
        finally:
            self._shutdown_event.clear()

    def _acquire_queue_slot(self, slot: WorkerSlot) -> float:
        wait_started = time.perf_counter()
        with slot.lock:
            while True:
                self._raise_if_shutdown_requested()
                if slot.pending_requests < slot.max_pending_requests:
                    break
                logger.info("Local MT queue saturated for %s; waiting for free slot", slot.model_id)
                slot.condition.wait(timeout=1.0)
            slot.pending_requests += 1
            slot.max_observed_queue_depth = max(
                slot.max_observed_queue_depth, slot.pending_requests
            )
            self._cancel_idle_timer(slot)
            return (time.perf_counter() - wait_started) * 1000

    def _release_queue_slot(self, slot: WorkerSlot) -> None:
        pressure_snapshot: dict[str, int] | None = None
        should_pressure_unload = False
        with slot.lock:
            slot.pending_requests = max(0, slot.pending_requests - 1)
            slot.active_requests = max(0, slot.active_requests - 1)
            slot.last_used_monotonic = time.monotonic()
            if slot.worker is not None:
                slot.state = ProviderLifecycleState.IDLE
                if not self.is_shutdown_requested():
                    if slot.is_gpu_heavy:
                        pressure_snapshot = self._sample_gpu_memory_mb()
                        should_pressure_unload = self._is_memory_pressure_snapshot(
                            pressure_snapshot
                        )
                    self._schedule_idle_unload(slot)
            else:
                slot.state = ProviderLifecycleState.UNLOADED
            slot.condition.notify_all()
        if should_pressure_unload and self._unload_slot(
            slot,
            reason="memory_pressure",
            force=False,
        ):
            logger.info(
                "Memory-pressure unload complete for %s with snapshot=%s",
                slot.model_id,
                pressure_snapshot,
            )

    def _ensure_worker_loaded(self, slot: WorkerSlot) -> tuple[LocalMTWorker, float]:
        with slot.lock:
            while slot.state == ProviderLifecycleState.LOADING:
                slot.condition.wait(timeout=0.5)
            if slot.worker is not None and slot.state in (
                ProviderLifecycleState.READY,
                ProviderLifecycleState.IDLE,
                ProviderLifecycleState.BUSY,
            ):
                slot.active_requests += 1
                slot.state = ProviderLifecycleState.BUSY
                return slot.worker, 0.0
            slot.state = ProviderLifecycleState.LOADING
            slot.last_error = None

        if slot.is_gpu_heavy:
            self._evict_other_idle_gpu_slots(slot.key)

        before_load_snapshot = self._capture_resource_snapshot(slot)
        started = time.perf_counter()
        try:
            worker = start_worker(
                model_path=slot.model_path,
                backend=slot.backend,
                model_id=slot.model_id,
                timeout=slot.timeout,
            )
        except Exception as exc:
            with slot.lock:
                slot.state = ProviderLifecycleState.FAILED
                slot.last_error = str(exc)
                slot.condition.notify_all()
            raise

        load_ms = (time.perf_counter() - started) * 1000
        after_load_snapshot = self._capture_resource_snapshot(slot)
        with slot.lock:
            slot.worker = worker
            slot.active_requests += 1
            slot.load_count += 1
            slot.last_load_ms = load_ms
            slot.last_load_resource_snapshot = {
                "before": before_load_snapshot,
                "after": after_load_snapshot,
            }
            slot.last_resource_snapshot = dict(after_load_snapshot)
            slot.last_used_monotonic = time.monotonic()
            slot.state = ProviderLifecycleState.BUSY
            slot.condition.notify_all()
            logger.info(
                "Local MT worker ready: model=%s state=%s load_ms=%.1f",
                slot.model_id,
                slot.state.value,
                slot.last_load_ms,
            )
            return worker, load_ms

    def _schedule_idle_unload(self, slot: WorkerSlot) -> None:
        if slot.idle_timeout_s <= 0:
            return
        self._cancel_idle_timer(slot)
        timer = threading.Timer(
            slot.idle_timeout_s,
            self._idle_unload_callback,
            kwargs={"backend": slot.backend, "model_id": slot.model_id},
        )
        timer.daemon = True
        slot.idle_timer = timer
        timer.start()

    def _cancel_idle_timer(self, slot: WorkerSlot) -> None:
        timer = slot.idle_timer
        if timer is not None:
            timer.cancel()
            slot.idle_timer = None

    def _idle_unload_callback(self, *, backend: str, model_id: str) -> None:
        try:
            unloaded = self.unload_model(
                backend=backend,
                model_id=model_id,
                reason="idle_timeout",
                force=False,
            )
            if unloaded:
                logger.info("Idle unload complete for %s", model_id)
        except Exception as exc:
            logger.debug("Idle unload failed for %s: %s", model_id, exc)

    def _evict_other_idle_gpu_slots(self, current_key: tuple[str, str]) -> None:
        with self._slots_lock:
            candidates = [
                slot
                for key, slot in self._slots.items()
                if key != current_key and slot.is_gpu_heavy
            ]
        for slot in candidates:
            self._unload_slot(slot, reason=f"gpu_switch->{current_key[1]}", force=False)

    def _unload_slot(self, slot: WorkerSlot, *, reason: str, force: bool) -> bool:
        with slot.lock:
            if slot.worker is None:
                slot.state = ProviderLifecycleState.UNLOADED
                return False
            if not force and (slot.active_requests > 0 or slot.pending_requests > 0):
                return False
            worker = slot.worker
            slot.worker = None
            slot.state = ProviderLifecycleState.UNLOADING
            self._cancel_idle_timer(slot)

        before_unload_snapshot = self._capture_resource_snapshot(slot)
        started = time.perf_counter()
        try:
            worker.shutdown()
        except Exception as exc:
            logger.warning("Error unloading local MT worker %s: %s", slot.model_id, exc)
        unload_ms = (time.perf_counter() - started) * 1000
        after_unload_snapshot = self._capture_resource_snapshot(slot)

        with slot.lock:
            slot.unload_count += 1
            slot.last_unload_ms = unload_ms
            slot.last_unload_reason = reason
            slot.unload_reasons[reason] = slot.unload_reasons.get(reason, 0) + 1
            slot.last_unload_resource_snapshot = {
                "before": before_unload_snapshot,
                "after": after_unload_snapshot,
            }
            slot.last_resource_snapshot = dict(after_unload_snapshot)
            slot.last_used_monotonic = time.monotonic()
            slot.state = ProviderLifecycleState.UNLOADED
            slot.condition.notify_all()
            logger.info(
                "Local MT worker unloaded: model=%s reason=%s unload_ms=%.1f",
                slot.model_id,
                reason,
                slot.last_unload_ms,
            )
        return True

    def _record_request_metrics(
        self,
        *,
        slot: WorkerSlot,
        queue_wait_ms: float,
        gpu_wait_ms: float,
        batch_size: int,
        wall_ms: float,
        inference_ms: float,
    ) -> None:
        with slot.lock:
            slot.total_requests += 1
            if batch_size > 1:
                slot.total_batches += 1
            slot.total_segments += batch_size
            slot.last_queue_wait_ms = queue_wait_ms
            slot.last_gpu_wait_ms = gpu_wait_ms
            slot.last_batch_size = batch_size
            slot.total_queue_wait_ms += queue_wait_ms
            slot.total_gpu_wait_ms += gpu_wait_ms
            slot.total_wall_ms += wall_ms
            slot.total_inference_ms += inference_ms

    def is_shutdown_requested(self) -> bool:
        return self._shutdown_event.is_set()

    def _ensure_accepting_requests(self) -> None:
        self._raise_if_shutdown_requested()

    def _raise_if_shutdown_requested(self) -> None:
        if self.is_shutdown_requested():
            raise RuntimeError("Local MT provider manager is shutting down")

    @staticmethod
    def _slot_has_inflight_work(slot: WorkerSlot) -> bool:
        with slot.lock:
            return slot.active_requests > 0 or slot.pending_requests > 0

    def _wait_for_slot_drain(self, slot: WorkerSlot, *, deadline: float) -> None:
        with slot.lock:
            while slot.worker is not None and (
                slot.active_requests > 0 or slot.pending_requests > 0
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                slot.condition.wait(timeout=min(0.25, remaining))

    @classmethod
    def _is_memory_pressure_snapshot(cls, snapshot: dict[str, int] | None) -> bool:
        if not snapshot:
            return False
        total_mb = int(snapshot.get("total_mb", 0) or 0)
        used_mb = int(snapshot.get("used_mb", 0) or 0)
        if total_mb <= 0 or used_mb < 0:
            return False
        headroom_mb = max(total_mb - used_mb, 0)
        used_ratio = used_mb / total_mb if total_mb else 0.0
        return (
            headroom_mb <= cls._PRESSURE_MIN_HEADROOM_MB
            or used_ratio >= cls._PRESSURE_MAX_USED_RATIO
        )

    @staticmethod
    def _capture_resource_snapshot(slot: WorkerSlot) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "timestamp_monotonic": round(time.monotonic(), 3),
            "backend": slot.backend,
            "model_id": slot.model_id,
        }
        process_rss_mb = LocalMTProviderManager._sample_process_rss_mb()
        if process_rss_mb is not None:
            snapshot["manager_process_rss_mb"] = process_rss_mb
        gpu_memory = LocalMTProviderManager._sample_gpu_memory_mb()
        if gpu_memory:
            snapshot["gpu_memory"] = gpu_memory
        return snapshot

    @staticmethod
    def _sample_process_rss_mb() -> float | None:
        try:
            import psutil

            return round(psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024, 1)
        except Exception:
            return None

    @staticmethod
    def _sample_gpu_memory_mb() -> dict[str, int] | None:
        nvidia_smi = shutil.which("nvidia-smi")
        if not nvidia_smi:
            return None
        try:
            out = subprocess.check_output(
                [
                    nvidia_smi,
                    "--query-gpu=memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).strip()
        except Exception:
            return None

        first_line = out.splitlines()[0].strip() if out else ""
        if not first_line:
            return None
        try:
            used_mb, total_mb = [int(part.strip()) for part in first_line.split(",")[:2]]
        except Exception:
            return None
        return {"used_mb": used_mb, "total_mb": total_mb}


def get_local_mt_provider_manager() -> LocalMTProviderManager:
    return LocalMTProviderManager()
