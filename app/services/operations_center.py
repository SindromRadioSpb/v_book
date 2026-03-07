"""Operations Center — singleton registry for heavy background operations (PERF-SCALE PATCH-B).

Tracks all active heavy operations (NLP process, ingest, term extract, …) and
enforces a per-category concurrency limit so that multiple write-heavy workers
cannot compete for the SQLite write-lock simultaneously.

Thread-safety:
  The center is a QObject; all signal emissions happen on the thread that calls
  register()/unregister().  Workers call these from their QThread.run() scope.
  Qt's auto-connection type queues the emission safely to main-thread slots.

Usage in workers:
    def run(self):
        op_id = OperationsCenter.instance().register("NLP Process (42 docs)", "nlp_process")
        try:
            ...
        finally:
            OperationsCenter.instance().unregister(op_id)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import ClassVar, Optional

logger = logging.getLogger(__name__)

# PyQt6 may not be available in pure-Python tests; guard import.
try:
    from PyQt6.QtCore import QObject, pyqtSignal as _Signal

    class _SignalHost(QObject):
        operation_registered = _Signal(str, str, str)    # op_id, name, category
        operation_unregistered = _Signal(str)            # op_id
        active_count_changed = _Signal(int)              # new total active count

    _HAS_PYQT = True
except ImportError:  # pragma: no cover
    _SignalHost = object  # type: ignore[misc,assignment]
    _HAS_PYQT = False


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class OperationEntry:
    """Snapshot of a single registered operation."""

    op_id: str
    name: str
    category: str
    started_at: float = field(default_factory=time.monotonic)


# ---------------------------------------------------------------------------
# OperationsCenter
# ---------------------------------------------------------------------------

#: Maximum number of concurrent heavy operations allowed per category.
MAX_HEAVY_CONCURRENT: int = 1

#: Categories that count as "heavy" (DB write-intensive).
HEAVY_CATEGORIES: frozenset[str] = frozenset(
    {"nlp_process", "ingest", "term_extract", "pronunciation_bootstrap"}
)


class OperationsCenter(_SignalHost):  # type: ignore[misc]
    """Singleton registry for heavy background operations.

    All public methods are thread-safe (protected by a reentrant lock).
    """

    _instance: ClassVar[Optional["OperationsCenter"]] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------

    @classmethod
    def instance(cls) -> "OperationsCenter":
        """Return the process-wide singleton, creating it if necessary."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_for_tests(cls) -> None:
        """Destroy the singleton.  Call only in test teardown."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance._ops.clear()
            cls._instance = None

    # ------------------------------------------------------------------
    # Internal state
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        if _HAS_PYQT:
            super().__init__()
        self._ops: dict[str, OperationEntry] = {}
        self._mu = threading.Lock()

    # ------------------------------------------------------------------
    # Registration API
    # ------------------------------------------------------------------

    def register(self, name: str, category: str) -> str:
        """Register a new operation and return its op_id.

        Args:
            name:     Human-readable label (shown in UI status widget).
            category: Operation category (see HEAVY_CATEGORIES).

        Returns:
            Unique op_id string.  Pass this to unregister() when done.
        """
        op_id = str(uuid.uuid4())[:8]
        entry = OperationEntry(op_id=op_id, name=name, category=category)
        with self._mu:
            self._ops[op_id] = entry
            count = len(self._ops)

        logger.debug("OperationsCenter: registered %s '%s' [%s]", op_id, name, category)

        if _HAS_PYQT:
            self.operation_registered.emit(op_id, name, category)
            self.active_count_changed.emit(count)

        return op_id

    def unregister(self, op_id: str) -> None:
        """Mark an operation as complete and remove it from the registry.

        No-op if op_id is unknown (safe to call from finally blocks).

        Args:
            op_id: The value returned by register().
        """
        with self._mu:
            entry = self._ops.pop(op_id, None)
            count = len(self._ops)

        if entry is None:
            logger.debug("OperationsCenter: unregister called for unknown op_id %s", op_id)
            return

        elapsed = time.monotonic() - entry.started_at
        logger.debug(
            "OperationsCenter: unregistered %s '%s' after %.1fs",
            op_id,
            entry.name,
            elapsed,
        )

        if _HAS_PYQT:
            self.operation_unregistered.emit(op_id)
            self.active_count_changed.emit(count)

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def active_ops(self) -> list[OperationEntry]:
        """Return a snapshot of all currently active operations."""
        with self._mu:
            return list(self._ops.values())

    def active_count(self) -> int:
        """Return total number of active operations."""
        with self._mu:
            return len(self._ops)

    def heavy_count(self, category: str | None = None) -> int:
        """Return number of active heavy operations.

        Args:
            category: If given, restrict to this category; else count all HEAVY_CATEGORIES.
        """
        with self._mu:
            if category is not None:
                return sum(1 for e in self._ops.values() if e.category == category)
            return sum(1 for e in self._ops.values() if e.category in HEAVY_CATEGORIES)

    def is_slot_available(self, category: str) -> bool:
        """Return True if another operation of this category may start now.

        Heavy categories are limited to MAX_HEAVY_CONCURRENT simultaneous
        operations.  Non-heavy categories are always available.

        Args:
            category: Category string to check.
        """
        if category not in HEAVY_CATEGORIES:
            return True
        return self.heavy_count(category) < MAX_HEAVY_CONCURRENT
