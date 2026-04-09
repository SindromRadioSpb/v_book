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
    last_load_ms: float = 0.0
    last_unload_ms: float = 0.0
    last_request_ms: float = 0.0
    max_observed_queue_depth: int = 0
    lock: threading.RLock = field(default_factory=threading.RLock)
    condition: threading.Condition = field(init=False)
    idle_timer: threading.Timer | None = None

    def __post_init__(self) -> None:
        self.condition = threading.Condition(self.lock)


class LocalMTProviderManager:
    """Singleton manager for local MT worker lifecycles."""

    _instance: LocalMTProviderManager | None = None
    _instance_lock = threading.Lock()

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
                    "load_count": 0,
                    "unload_count": 0,
                }
        with slot.lock:
            return {
                "state": slot.state.value,
                "active_requests": slot.active_requests,
                "pending_requests": slot.pending_requests,
                "load_count": slot.load_count,
                "unload_count": slot.unload_count,
                "last_load_ms": slot.last_load_ms,
                "last_unload_ms": slot.last_unload_ms,
                "last_request_ms": slot.last_request_ms,
                "max_observed_queue_depth": slot.max_observed_queue_depth,
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
        slot = self.get_slot(
            model_path=model_path,
            backend=backend,
            model_id=model_id,
            timeout=timeout,
            idle_timeout_s=idle_timeout_s,
            max_pending_requests=max_pending_requests,
        )
        self._acquire_queue_slot(slot)
        exec_lock = self._gpu_execution_lock if slot.is_gpu_heavy else threading.Lock()
        try:
            with exec_lock:
                worker = self._ensure_worker_loaded(slot)
                started = time.perf_counter()
                result = worker.translate(worker_request)
                slot.last_request_ms = (time.perf_counter() - started) * 1000
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
        slot = self.get_slot(
            model_path=model_path,
            backend=backend,
            model_id=model_id,
            timeout=timeout,
            idle_timeout_s=idle_timeout_s,
            max_pending_requests=max_pending_requests,
        )
        self._acquire_queue_slot(slot)
        exec_lock = self._gpu_execution_lock if slot.is_gpu_heavy else threading.Lock()
        try:
            with exec_lock:
                worker = self._ensure_worker_loaded(slot)
                started = time.perf_counter()
                results = worker.translate_batch(worker_requests)
                slot.last_request_ms = (time.perf_counter() - started) * 1000
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

    def shutdown_all(self) -> None:
        with self._slots_lock:
            slots = list(self._slots.values())
        for slot in slots:
            try:
                self._unload_slot(slot, reason="shutdown_all", force=True)
            except Exception as exc:
                logger.debug("LocalMTProviderManager shutdown skipped for %s: %s", slot.key, exc)

    def _acquire_queue_slot(self, slot: WorkerSlot) -> None:
        with slot.lock:
            while slot.pending_requests >= slot.max_pending_requests:
                logger.info("Local MT queue saturated for %s; waiting for free slot", slot.model_id)
                slot.condition.wait(timeout=1.0)
            slot.pending_requests += 1
            slot.max_observed_queue_depth = max(
                slot.max_observed_queue_depth, slot.pending_requests
            )
            self._cancel_idle_timer(slot)

    def _release_queue_slot(self, slot: WorkerSlot) -> None:
        with slot.lock:
            slot.pending_requests = max(0, slot.pending_requests - 1)
            slot.active_requests = max(0, slot.active_requests - 1)
            slot.last_used_monotonic = time.monotonic()
            if slot.worker is not None:
                slot.state = ProviderLifecycleState.IDLE
                self._schedule_idle_unload(slot)
            else:
                slot.state = ProviderLifecycleState.UNLOADED
            slot.condition.notify_all()

    def _ensure_worker_loaded(self, slot: WorkerSlot) -> LocalMTWorker:
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
                return slot.worker
            slot.state = ProviderLifecycleState.LOADING
            slot.last_error = None

        if slot.is_gpu_heavy:
            self._evict_other_idle_gpu_slots(slot.key)

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
        with slot.lock:
            slot.worker = worker
            slot.active_requests += 1
            slot.load_count += 1
            slot.last_load_ms = load_ms
            slot.last_used_monotonic = time.monotonic()
            slot.state = ProviderLifecycleState.BUSY
            slot.condition.notify_all()
            logger.info(
                "Local MT worker ready: model=%s state=%s load_ms=%.1f",
                slot.model_id,
                slot.state.value,
                slot.last_load_ms,
            )
            return worker

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

        started = time.perf_counter()
        try:
            worker.shutdown()
        except Exception as exc:
            logger.warning("Error unloading local MT worker %s: %s", slot.model_id, exc)
        unload_ms = (time.perf_counter() - started) * 1000

        with slot.lock:
            slot.unload_count += 1
            slot.last_unload_ms = unload_ms
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


def get_local_mt_provider_manager() -> LocalMTProviderManager:
    return LocalMTProviderManager()
