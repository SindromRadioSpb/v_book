"""Compatibility shim for local Phonikud integration.

This module keeps the expected top-level callables:
- add_niqqud
- phonikud
- nekud
- diacritize

It also exposes runtime diagnostics used by the premium UI gate:
- get_runtime_mode() -> real_inference | fallback | error
- get_runtime_details() -> human-readable state/error
"""

from __future__ import annotations

import importlib
from functools import lru_cache
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Optional, Tuple

MODE_REAL = "real_inference"
MODE_FALLBACK = "fallback"
MODE_ERROR = "error"

_runtime_mode = MODE_FALLBACK
_runtime_details = "No PHONIKUD_MODEL_PATH configured; fallback mode"
_SUBPROCESS_TIMEOUT_SEC = 120
_DLL_DIR_HANDLES: list[object] = []
_DLL_DIR_KEYS: set[str] = set()


def _normalize_input(text: str) -> str:
    return (text or "").strip()


def _sanitize_model_path(raw_value: str) -> str:
    value = (raw_value or "").strip()
    if not value:
        return ""
    # UI copy/paste frequently leaves quotes or trailing dot.
    value = value.strip("\"'").rstrip(" .")
    return value


def _ensure_hf_home() -> None:
    """Ensure Hugging Face cache points to a writable location."""
    configured = (os.getenv("HF_HOME") or "").strip()
    if configured:
        configured_path = Path(configured)
        try:
            configured_path.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=str(configured_path), prefix="hf_write_test_", delete=True):
                pass
            return
        except Exception:
            pass

    candidates = []
    candidates.append(Path.cwd() / "build" / "hf_cache")
    candidates.append(Path(__file__).resolve().parent / "build" / "hf_cache")
    local_app_data = (os.getenv("LOCALAPPDATA") or "").strip()
    if local_app_data:
        candidates.append(Path(local_app_data) / "HDLE" / "hf_cache")

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=str(candidate), prefix="hf_write_test_", delete=True):
                pass
            os.environ["HF_HOME"] = str(candidate)
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            return
        except Exception:
            continue


def _register_dll_directory(path: Path) -> None:
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return
    try:
        resolved = str(path.resolve())
    except Exception:
        resolved = str(path)
    key = resolved.lower()
    if key in _DLL_DIR_KEYS:
        return
    if not Path(resolved).exists():
        return
    try:
        handle = os.add_dll_directory(resolved)
    except Exception:
        return
    _DLL_DIR_HANDLES.append(handle)
    _DLL_DIR_KEYS.add(key)


def prepare_runtime_dll_paths() -> None:
    """Register likely ONNX runtime DLL folders for packaged Windows runs."""
    candidates: list[Path] = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        meipass_root = Path(str(meipass))
        candidates.append(meipass_root)
        candidates.append(meipass_root / "onnxruntime" / "capi")

    try:
        exe_root = Path(sys.executable).resolve().parent
        internal_root = exe_root / "_internal"
        candidates.append(internal_root)
        candidates.append(internal_root / "onnxruntime" / "capi")
    except Exception:
        pass

    try:
        spec = importlib.util.find_spec("onnxruntime")
        origin = getattr(spec, "origin", None)
        if origin:
            package_root = Path(origin).resolve().parent
            candidates.append(package_root)
            candidates.append(package_root / "capi")
    except Exception:
        pass

    for candidate in candidates:
        _register_dll_directory(candidate)


def _run_onnx_subprocess(model_path: Path, texts: list[str]) -> list[str]:
    """Run ONNX inference in isolated process to avoid in-process DLL conflicts."""
    payload = {
        "model_path": str(model_path),
        "texts": [str(text or "") for text in (texts or [])],
    }
    if not payload["texts"]:
        return []

    code = (
        "import json,sys\n"
        "from phonikud_onnx import Phonikud\n"
        "raw=sys.stdin.read() or '{}'\n"
        "data=json.loads(raw)\n"
        "model=Phonikud(str(data.get('model_path') or ''))\n"
        "inputs=data.get('texts') or []\n"
        "outs=[]\n"
        "for t in inputs:\n"
        " t=str(t or '')\n"
        " try:\n"
        "  rendered=str(model.add_diacritics(t) or '').strip()\n"
        " except Exception:\n"
        "  rendered=''\n"
        " outs.append(rendered or t)\n"
        "sys.stdout.write(json.dumps({'outputs': outs}, ensure_ascii=True))\n"
    )
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        input=json.dumps(payload, ensure_ascii=True),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_SUBPROCESS_TIMEOUT_SEC,
        env=env,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(stderr or f"Subprocess exited with code {proc.returncode}")
    try:
        parsed = json.loads(proc.stdout or "{}")
    except Exception as exc:
        raise RuntimeError(f"Subprocess returned invalid JSON: {exc}") from exc
    outputs = parsed.get("outputs") or []
    return [str(item or "") for item in outputs]


def _resolve_model_target() -> tuple[Optional[str], Optional[Path]]:
    """Resolve configured model target as ('onnx'|'torch', path) or (None, None)."""
    raw = _sanitize_model_path(os.getenv("PHONIKUD_MODEL_PATH") or "")
    if not raw:
        return None, None

    path = Path(raw).expanduser()

    if path.is_file() and path.suffix.lower() == ".onnx":
        return "onnx", path

    if path.is_dir():
        onnx_candidates = sorted(
            [p for p in path.glob("*.onnx") if p.is_file()],
            key=lambda p: (0 if "int8" in p.name.lower() else 1, p.name.lower()),
        )
        if onnx_candidates:
            return "onnx", onnx_candidates[0]
        return "torch", path

    # Non-existing path: recover common UI/manual inputs.
    if path.suffix.lower() != ".onnx":
        direct_onnx = Path(str(path) + ".onnx")
        if direct_onnx.is_file():
            return "onnx", direct_onnx

        parent = path.parent
        if parent.exists() and parent.is_dir():
            prefix = path.name
            matches = sorted(
                [p for p in parent.glob(f"{prefix}*.onnx") if p.is_file()],
                key=lambda p: (0 if "int8" in p.name.lower() else 1, p.name.lower()),
            )
            if matches:
                return "onnx", matches[0]

    # Infer intent by extension.
    if path.suffix.lower() == ".onnx":
        return "onnx", path
    return "torch", path


@lru_cache(maxsize=1)
def _load_model_bundle() -> Optional[Tuple[str, object, Optional[object]]]:
    global _runtime_mode, _runtime_details

    target_kind, target_path = _resolve_model_target()
    if not target_kind or target_path is None:
        _runtime_mode = MODE_FALLBACK
        _runtime_details = "PHONIKUD_MODEL_PATH is empty; fallback mode"
        return None

    if target_kind == "onnx":
        try:
            _ensure_hf_home()
            prepare_runtime_dll_paths()
            from phonikud_onnx import Phonikud as OnnxPhonikud

            model = OnnxPhonikud(str(target_path))
            _runtime_mode = MODE_REAL
            _runtime_details = f"ONNX model loaded: {target_path.name}"
            return "onnx", model, None
        except Exception as exc:
            try:
                # Probe isolated runtime to recover from in-process DLL init issues.
                probe_inputs = ["\u05e9\u05dc\u05d5\u05dd"]
                probe_outputs = _run_onnx_subprocess(target_path, probe_inputs)
                changed = any(
                    str(rendered or "").strip() != source
                    for source, rendered in zip(probe_inputs, probe_outputs)
                )
                if changed:
                    _runtime_mode = MODE_REAL
                    _runtime_details = f"ONNX subprocess backend active: {target_path.name}"
                else:
                    _runtime_mode = MODE_FALLBACK
                    _runtime_details = (
                        f"ONNX subprocess probe returned identity output: {target_path.name}"
                    )
                return "onnx_subprocess", str(target_path), None
            except Exception as sub_exc:
                _runtime_mode = MODE_ERROR
                _runtime_details = (
                    f"Failed to load ONNX model: {exc}; subprocess fallback failed: {sub_exc}"
                )
                return None

    try:
        from transformers import AutoTokenizer
        from src.model.phonikud_model import PhoNikudModel

        model = PhoNikudModel.from_pretrained(str(target_path), trust_remote_code=True)
        tokenizer = AutoTokenizer.from_pretrained(str(target_path))
        model.eval()
        _runtime_mode = MODE_REAL
        _runtime_details = "Model loaded successfully"
        return "torch", model, tokenizer
    except Exception as exc:
        _runtime_mode = MODE_ERROR
        _runtime_details = f"Failed to load model from path: {exc}"
        return None


def add_niqqud(text: str) -> str:
    source = _normalize_input(text)
    if not source:
        return ""

    rendered_list = batch_add_niqqud([source])
    if not rendered_list:
        return source
    return rendered_list[0] or source


def batch_add_niqqud(texts: list[str]) -> list[str]:
    normalized = [_normalize_input(text) for text in (texts or [])]
    if not normalized:
        return []

    bundle = _load_model_bundle()
    if not bundle:
        # Deterministic fallback without crashing worker flows.
        return normalized

    kind, model, tokenizer = bundle
    try:
        if kind == "onnx":
            rendered = []
            for source in normalized:
                value = str(model.add_diacritics(source) or "").strip()
                rendered.append(value or source)
            return rendered

        if kind == "onnx_subprocess":
            rendered = _run_onnx_subprocess(Path(str(model)), normalized)
            if len(rendered) != len(normalized):
                return normalized
            return [value.strip() or source for source, value in zip(normalized, rendered)]

        from src.model.phonikud_model import NIKUD_HASER
        result = model.predict(normalized, tokenizer, mark_matres_lectionis=NIKUD_HASER)
        if not result:
            return normalized
        rendered = []
        for idx, source in enumerate(normalized):
            value = str(result[idx]).strip() if idx < len(result) else ""
            rendered.append(value or source)
        return rendered
    except Exception as exc:
        global _runtime_mode, _runtime_details
        _runtime_mode = MODE_ERROR
        _runtime_details = f"Inference error: {exc}"
        return normalized


def phonikud(text: str) -> str:
    return add_niqqud(text)


def nekud(text: str) -> str:
    return add_niqqud(text)


def diacritize(text: str) -> str:
    return add_niqqud(text)


def batch_phonikud(texts: list[str]) -> list[str]:
    return batch_add_niqqud(texts)


def get_runtime_mode() -> str:
    return _runtime_mode


def get_runtime_details() -> str:
    return _runtime_details


def reset_runtime_cache() -> None:
    """Reset cached runtime bundle to support model-path changes in-process."""
    global _runtime_mode, _runtime_details
    _load_model_bundle.cache_clear()
    model_path = _sanitize_model_path(os.getenv("PHONIKUD_MODEL_PATH") or "")
    if model_path:
        _runtime_mode = MODE_FALLBACK
        _runtime_details = "Runtime cache cleared; awaiting model load"
    else:
        _runtime_mode = MODE_FALLBACK
        _runtime_details = "PHONIKUD_MODEL_PATH is empty; fallback mode"
