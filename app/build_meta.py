"""Build metadata helpers for runtime traceability."""

from __future__ import annotations

from typing import Any

from app import __version__

_FALLBACK_BUILD_COMMIT = "unknown"
_FALLBACK_BUILD_DIRTY = 0
_FALLBACK_BUILD_TIME_UTC = "unknown"


def _normalize_dirty(value: Any) -> int:
    try:
        return 1 if int(value) else 0
    except (TypeError, ValueError):
        text = str(value or "").strip().lower()
        return 1 if text in {"1", "true", "yes", "dirty"} else 0


def _load_generated_build_info() -> dict[str, Any]:
    try:
        from app._generated import build_info as generated_build_info
    except Exception:
        return {}

    return {
        "commit": str(
            getattr(generated_build_info, "BUILD_COMMIT", _FALLBACK_BUILD_COMMIT)
            or _FALLBACK_BUILD_COMMIT
        ),
        "dirty": _normalize_dirty(
            getattr(generated_build_info, "BUILD_DIRTY", _FALLBACK_BUILD_DIRTY)
        ),
        "built_at_utc": str(
            getattr(generated_build_info, "BUILD_TIME_UTC", _FALLBACK_BUILD_TIME_UTC)
            or _FALLBACK_BUILD_TIME_UTC
        ),
    }


_GENERATED_BUILD_INFO = _load_generated_build_info()

APP_VERSION = __version__
BUILD_COMMIT = str(_GENERATED_BUILD_INFO.get("commit", _FALLBACK_BUILD_COMMIT))
BUILD_DIRTY = _normalize_dirty(_GENERATED_BUILD_INFO.get("dirty", _FALLBACK_BUILD_DIRTY))
BUILD_TIME_UTC = str(_GENERATED_BUILD_INFO.get("built_at_utc", _FALLBACK_BUILD_TIME_UTC))


def get_build_meta() -> dict[str, Any]:
    """Return normalized build metadata payload used by runtime/UI/scripts."""
    return {
        "version": APP_VERSION,
        "commit": BUILD_COMMIT,
        "dirty": BUILD_DIRTY,
        "built_at_utc": BUILD_TIME_UTC,
    }


def format_build_meta_line() -> str:
    meta = get_build_meta()
    return (
        f"HDLE Premium version={meta['version']} "
        f"commit={meta['commit']} dirty={meta['dirty']} "
        f"built_at={meta['built_at_utc']}"
    )
