"""Operations Center singleton registry for heavy background operations.

Tracks all active heavy operations (NLP process, ingest, term extract, and
other write-heavy flows) and enforces a process-wide heavy-operation slot so
that multiple workers cannot compete for the SQLite write lock simultaneously.

Thread-safety:
  The center is a QObject; all signal emissions happen on the thread that calls
  register()/unregister(). Workers call these from their QThread.run() scope.
  Qt's auto-connection type queues the emission safely to main-thread slots.

Usage in workers:
    def run(self):
        op_id = OperationsCenter.instance().register(
            "NLP Process (42 docs)",
            "nlp_process",
            enforce_limit=True,
        )
        try:
            ...
        finally:
            if op_id:
                OperationsCenter.instance().unregister(op_id)
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import ClassVar

logger = logging.getLogger(__name__)

# PyQt6 may not be available in pure-Python tests; guard import.
try:
    from PyQt6.QtCore import QObject
    from PyQt6.QtCore import pyqtSignal as _Signal

    class _SignalHost(QObject):
        operation_registered = _Signal(str, str, str)  # op_id, name, category
        operation_unregistered = _Signal(str)  # op_id
        active_count_changed = _Signal(int)  # new total active count

    _HAS_PYQT = True
except ImportError:  # pragma: no cover
    _SignalHost = object  # type: ignore[misc,assignment]
    _HAS_PYQT = False


@dataclass
class OperationEntry:
    """Snapshot of a single registered operation."""

    op_id: str
    name: str
    category: str
    started_at: float = field(default_factory=time.monotonic)


class OperationsCenterBusyError(RuntimeError):
    """Raised when a guarded operation cannot claim the heavy-operation slot."""

    def __init__(self, category: str, active_ops: list[OperationEntry]):
        self.category = str(category)
        self.active_ops = list(active_ops)
        active_names = ", ".join(op.name for op in self.active_ops) or "unknown operation"
        super().__init__(f"Heavy operation slot is busy for {self.category}: {active_names}")


#: Maximum number of concurrent heavy operations allowed process-wide.
MAX_HEAVY_CONCURRENT: int = 1

#: Categories that count as "heavy" (DB write-intensive).
HEAVY_CATEGORIES: frozenset[str] = frozenset(
    {
        "dictionary_import",
        "document_delete",
        "ingest",
        "nlp_process",
        "project_import",
        "pronunciation_bootstrap",
        "term_extract",
    }
)


class OperationsCenter(_SignalHost):  # type: ignore[misc]
    """Singleton registry for heavy background operations."""

    _instance: ClassVar[OperationsCenter | None] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def instance(cls) -> OperationsCenter:
        """Return the process-wide singleton, creating it if necessary."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_for_tests(cls) -> None:
        """Destroy the singleton. Call only in test teardown."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance._ops.clear()
            cls._instance = None

    def __init__(self) -> None:
        if _HAS_PYQT:
            super().__init__()
        self._ops: dict[str, OperationEntry] = {}
        self._mu = threading.Lock()

    def _blocking_ops_locked(self, category: str) -> list[OperationEntry]:
        if category in HEAVY_CATEGORIES:
            return [entry for entry in self._ops.values() if entry.category in HEAVY_CATEGORIES]
        return [entry for entry in self._ops.values() if entry.category == category]

    def register(self, name: str, category: str, *, enforce_limit: bool = False) -> str:
        """Register a new operation and return its op_id."""
        op_id = str(uuid.uuid4())[:8]
        entry = OperationEntry(op_id=op_id, name=name, category=category)
        with self._mu:
            if enforce_limit:
                blocking_ops = self._blocking_ops_locked(category)
                if blocking_ops:
                    raise OperationsCenterBusyError(category, blocking_ops)
            self._ops[op_id] = entry
            count = len(self._ops)

        logger.debug("OperationsCenter: registered %s '%s' [%s]", op_id, name, category)

        if _HAS_PYQT:
            self.operation_registered.emit(op_id, name, category)
            self.active_count_changed.emit(count)

        return op_id

    def unregister(self, op_id: str) -> None:
        """Mark an operation as complete and remove it from the registry."""
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

    def active_ops(self) -> list[OperationEntry]:
        """Return a snapshot of all currently active operations."""
        with self._mu:
            return list(self._ops.values())

    def blocking_ops(self, category: str) -> list[OperationEntry]:
        """Return active ops that block a new operation in this category."""
        with self._mu:
            return list(self._blocking_ops_locked(category))

    def active_count(self) -> int:
        """Return total number of active operations."""
        with self._mu:
            return len(self._ops)

    def heavy_count(self, category: str | None = None) -> int:
        """Return number of active heavy operations."""
        with self._mu:
            if category is not None:
                return sum(1 for e in self._ops.values() if e.category == category)
            return sum(1 for e in self._ops.values() if e.category in HEAVY_CATEGORIES)

    def is_slot_available(self, category: str) -> bool:
        """Return True if another operation of this category may start now."""
        if category not in HEAVY_CATEGORIES:
            return True
        return self.heavy_count() < MAX_HEAVY_CONCURRENT
