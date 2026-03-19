"""Process-level file locking with stale lock detection.

This module provides a context manager for acquiring exclusive process locks,
with support for detecting and removing stale locks from terminated processes.
"""

import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class ProcessLock:
    """Process-level file lock with PID-based stale detection."""

    def __init__(self, lock_path: Path, timeout_seconds: int = 30):
        """
        Initialize process lock.

        Args:
            lock_path: Path to lock file
            timeout_seconds: Maximum time to wait for lock acquisition
        """
        self.lock_path = lock_path
        self.lock_file = None
        self.timeout = timeout_seconds

    def __enter__(self):
        """
        Acquire lock with timeout.

        Returns:
            self

        Raises:
            RuntimeError: If lock cannot be acquired within timeout
        """
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        # Check for stale lock (process not running)
        if self.lock_path.exists():
            try:
                pid_str = self.lock_path.read_text().strip()
                if pid_str:
                    pid = int(pid_str)

                    # Check if PID still running
                    try:
                        import psutil

                        if not psutil.pid_exists(pid):
                            logger.warning(f"Removing stale lock (PID {pid} not running)")
                            self.lock_path.unlink()
                        else:
                            logger.debug(f"Lock held by running process PID {pid}")

                    except ImportError:
                        logger.warning("psutil not available - cannot detect stale locks reliably")
                        # Fallback: check if we can delete (Windows will prevent if locked)
                        try:
                            self.lock_path.unlink()
                            logger.warning("Removed potentially stale lock file")
                        except PermissionError:
                            pass  # Lock is held by running process

            except (ValueError, OSError) as e:
                logger.warning(f"Removing corrupt lock file: {e}")
                try:
                    self.lock_path.unlink()
                except Exception:
                    pass

        # Acquire lock
        start_time = time.time()

        if sys.platform == "win32":
            import msvcrt

            while True:
                try:
                    # Open in exclusive mode
                    self.lock_file = open(self.lock_path, "w")

                    try:
                        # Try to lock the file
                        msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)

                        # Write PID to lock file
                        self.lock_file.write(str(os.getpid()))
                        self.lock_file.flush()

                        logger.debug(f"Lock acquired: {self.lock_path}")
                        break

                    except OSError:
                        # Lock held by another process
                        self.lock_file.close()
                        self.lock_file = None

                        if time.time() - start_time > self.timeout:
                            raise RuntimeError(
                                f"Could not acquire lock within {self.timeout}s - "
                                "migration already in progress or app already running"
                            )

                        time.sleep(0.5)

                except PermissionError:
                    # File locked by another process
                    if time.time() - start_time > self.timeout:
                        raise RuntimeError(
                            f"Could not acquire lock within {self.timeout}s - "
                            "migration already in progress or app already running"
                        )

                    time.sleep(0.5)

        else:
            # POSIX systems (Linux, macOS)
            import fcntl

            while True:
                try:
                    self.lock_file = open(self.lock_path, "w")

                    try:
                        fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

                        # Write PID to lock file
                        self.lock_file.write(str(os.getpid()))
                        self.lock_file.flush()

                        logger.debug(f"Lock acquired: {self.lock_path}")
                        break

                    except OSError:
                        # Lock held by another process
                        self.lock_file.close()
                        self.lock_file = None

                        if time.time() - start_time > self.timeout:
                            raise RuntimeError(
                                f"Could not acquire lock within {self.timeout}s - "
                                "migration already in progress or app already running"
                            )

                        time.sleep(0.5)

                except PermissionError:
                    if time.time() - start_time > self.timeout:
                        raise RuntimeError(
                            f"Could not acquire lock within {self.timeout}s - "
                            "migration already in progress or app already running"
                        )

                    time.sleep(0.5)

        return self

    def __exit__(self, *args):
        """Release lock and clean up lock file."""
        if self.lock_file:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    try:
                        msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                    except Exception as e:
                        logger.warning(f"Failed to unlock file: {e}")
                else:
                    import fcntl

                    try:
                        fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
                    except Exception as e:
                        logger.warning(f"Failed to unlock file: {e}")

                self.lock_file.close()

            except Exception as e:
                logger.warning(f"Error closing lock file: {e}")

            # Remove lock file
            try:
                self.lock_path.unlink(missing_ok=True)
                logger.debug(f"Lock released: {self.lock_path}")
            except Exception as e:
                logger.warning(f"Failed to remove lock file: {e}")

            self.lock_file = None
