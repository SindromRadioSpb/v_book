from __future__ import annotations

import ctypes
import importlib.util
import os
import sys
from pathlib import Path

_TORCH_DLL_HANDLES: list[object] = []
_TORCH_DLL_KEYS: set[str] = set()
_TORCH_PRELOAD_HANDLES: list[object] = []
_TORCH_PRELOAD_KEYS: set[str] = set()


def _normalize_path(path: Path) -> str:
    try:
        return str(path.resolve())
    except Exception:
        return str(path)


def _register_dll_directory(path: Path) -> str | None:
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return "unavailable"
    resolved = _normalize_path(path)
    key = resolved.lower()
    if key in _TORCH_DLL_KEYS or not Path(resolved).exists():
        return None
    try:
        handle = os.add_dll_directory(resolved)
    except Exception as exc:
        return str(exc)
    _TORCH_DLL_HANDLES.append(handle)
    _TORCH_DLL_KEYS.add(key)
    return None


def _load_preflight_dll(path: Path, *, win_dll: bool) -> str | None:
    resolved = _normalize_path(path)
    key = resolved.lower()
    if key in _TORCH_PRELOAD_KEYS or not Path(resolved).exists():
        return None
    try:
        loader = ctypes.WinDLL if win_dll else ctypes.CDLL
        handle = loader(resolved)
    except Exception as exc:
        return str(exc)
    _TORCH_PRELOAD_HANDLES.append(handle)
    _TORCH_PRELOAD_KEYS.add(key)
    return None


def _iter_torch_runtime_dirs() -> list[Path]:
    candidates: list[Path] = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        meipass_root = Path(str(meipass))
        candidates.append(meipass_root)
        candidates.append(meipass_root / "torch")
        candidates.append(meipass_root / "torch" / "lib")

    try:
        exe_root = Path(sys.executable).resolve().parent
        candidates.append(exe_root)
        candidates.append(exe_root / "_internal")
        candidates.append(exe_root / "_internal" / "torch")
        candidates.append(exe_root / "_internal" / "torch" / "lib")
    except Exception:
        pass

    spec = importlib.util.find_spec("torch")
    origin = getattr(spec, "origin", None)
    if origin:
        package_root = Path(origin).resolve().parent
        candidates.append(package_root.parent)
        candidates.append(package_root)
        candidates.append(package_root / "lib")

    if not bool(getattr(sys, "frozen", False)):
        for key, value in os.environ.items():
            if key.upper().startswith("CUDA_PATH") and value:
                candidates.append(Path(value) / "bin")

    return candidates


def _find_frozen_internal_root() -> Path | None:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(str(meipass))
        if candidate.exists():
            return candidate
    try:
        candidate = Path(sys.executable).resolve().parent / "_internal"
    except Exception:
        return None
    return candidate if candidate.exists() else None


def _preload_frozen_torch_dlls() -> dict[str, str]:
    if os.name != "nt" or not bool(getattr(sys, "frozen", False)):
        return {}
    internal_root = _find_frozen_internal_root()
    if internal_root is None:
        return {}
    torch_lib = internal_root / "torch" / "lib"
    errors: dict[str, str] = {}
    preload_plan = (
        (internal_root / "vcruntime140.dll", False),
        (internal_root / "msvcp140.dll", False),
        (internal_root / "vcruntime140_1.dll", False),
        (torch_lib / "c10.dll", True),
    )
    for path, win_dll in preload_plan:
        error = _load_preflight_dll(path, win_dll=win_dll)
        if error is not None:
            errors[_normalize_path(path)] = error
    return errors


def prepare_torch_runtime_paths(*, preload_frozen_torch: bool = False) -> dict[str, object]:
    if os.name != "nt":
        return {
            "os_name": os.name,
            "has_add_dll_directory": hasattr(os, "add_dll_directory"),
            "sys_executable": str(getattr(sys, "executable", "")),
            "meipass": str(getattr(sys, "_MEIPASS", "") or ""),
            "candidates": [],
            "registered": [],
            "errors": {},
            "path_prefix": [],
            "preloaded": [],
            "preload_errors": {},
        }

    existing_path = os.environ.get("PATH", "")
    normalized_path = existing_path.lower()
    prefix_parts: list[str] = []
    candidate_strings: list[str] = []
    registered: list[str] = []
    errors: dict[str, str] = {}
    for candidate in _iter_torch_runtime_dirs():
        resolved = _normalize_path(candidate)
        candidate_strings.append(resolved)
        if not Path(resolved).exists():
            continue
        error = _register_dll_directory(Path(resolved))
        if error is not None:
            errors[resolved] = error
        else:
            registered.append(resolved)
        if resolved.lower() not in normalized_path and resolved not in prefix_parts:
            prefix_parts.append(resolved)
    if prefix_parts:
        os.environ["PATH"] = (
            ";".join(prefix_parts + [existing_path]) if existing_path else ";".join(prefix_parts)
        )

    preload_errors = _preload_frozen_torch_dlls() if preload_frozen_torch else {}
    return {
        "os_name": os.name,
        "has_add_dll_directory": hasattr(os, "add_dll_directory"),
        "sys_executable": str(getattr(sys, "executable", "")),
        "meipass": str(getattr(sys, "_MEIPASS", "") or ""),
        "candidates": candidate_strings,
        "registered": registered,
        "errors": errors,
        "path_prefix": list(prefix_parts),
        "preloaded": sorted(_TORCH_PRELOAD_KEYS),
        "preload_errors": preload_errors,
    }
