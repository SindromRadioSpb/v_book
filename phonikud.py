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

from functools import lru_cache
import os
from pathlib import Path
import tempfile
from typing import Optional, Tuple

MODE_REAL = "real_inference"
MODE_FALLBACK = "fallback"
MODE_ERROR = "error"

_runtime_mode = MODE_FALLBACK
_runtime_details = "No PHONIKUD_MODEL_PATH configured; fallback mode"


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
            from phonikud_onnx import Phonikud as OnnxPhonikud

            model = OnnxPhonikud(str(target_path))
            _runtime_mode = MODE_REAL
            _runtime_details = f"ONNX model loaded: {target_path.name}"
            return "onnx", model, None
        except Exception as exc:
            _runtime_mode = MODE_ERROR
            _runtime_details = f"Failed to load ONNX model: {exc}"
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

    bundle = _load_model_bundle()
    if not bundle:
        # Deterministic fallback without crashing worker flows.
        return source

    kind, model, tokenizer = bundle
    try:
        if kind == "onnx":
            rendered = str(model.add_diacritics(source) or "").strip()
            return rendered or source

        from src.model.phonikud_model import NIKUD_HASER
        result = model.predict([source], tokenizer, mark_matres_lectionis=NIKUD_HASER)
        rendered = str(result[0]).strip() if result else ""
        return rendered or source
    except Exception as exc:
        global _runtime_mode, _runtime_details
        _runtime_mode = MODE_ERROR
        _runtime_details = f"Inference error: {exc}"
        return source


def phonikud(text: str) -> str:
    return add_niqqud(text)


def nekud(text: str) -> str:
    return add_niqqud(text)


def diacritize(text: str) -> str:
    return add_niqqud(text)


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
