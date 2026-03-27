"""Helpers for deterministic QThread shutdown from UI owners."""

from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)


def shutdown_qthread(
    worker: Any,
    *,
    label: str,
    cancel_first: bool = True,
    wait_timeout_ms: int = 1500,
    terminate_timeout_ms: int = 1500,
) -> bool:
    """Request cooperative stop, then force-stop before owner destruction.

    Returns True when the worker is no longer running.
    """

    if worker is None:
        return True

    is_running = getattr(worker, "isRunning", None)
    if not callable(is_running) or not bool(is_running()):
        return True

    if cancel_first:
        cancel = getattr(worker, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except Exception:
                logger.debug("Worker cancel failed for %s", label, exc_info=True)
        else:
            quit_method = getattr(worker, "quit", None)
            if callable(quit_method):
                try:
                    quit_method()
                except Exception:
                    logger.debug("Worker quit failed for %s", label, exc_info=True)

    wait_method = getattr(worker, "wait", None)
    if callable(wait_method):
        try:
            if bool(wait_method(wait_timeout_ms)):
                return True
        except Exception:
            logger.debug("Worker wait failed for %s", label, exc_info=True)

    terminate = getattr(worker, "terminate", None)
    if callable(terminate):
        logger.warning("Force-terminating worker during owner shutdown: %s", label)
        try:
            terminate()
        except Exception:
            logger.debug("Worker terminate failed for %s", label, exc_info=True)

    if callable(wait_method):
        try:
            if bool(wait_method(terminate_timeout_ms)):
                return True
        except Exception:
            logger.debug("Worker post-terminate wait failed for %s", label, exc_info=True)

    try:
        return not bool(is_running())
    except Exception:
        return False
