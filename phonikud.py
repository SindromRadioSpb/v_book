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

import os
from pathlib import Path
from functools import lru_cache
from typing import Optional, Tuple

MODE_REAL = "real_inference"
MODE_FALLBACK = "fallback"
MODE_ERROR = "error"

_runtime_mode = MODE_FALLBACK
_runtime_details = "No PHONIKUD_MODEL_PATH configured; fallback mode"


def _normalize_input(text: str) -> str:
    return (text or "").strip()


def _ensure_hf_home() -> None:
    """Ensure Hugging Face cache points to a writable location."""
    if (os.getenv("HF_HOME") or "").strip():
        return

    candidates = []
    local_app_data = (os.getenv("LOCALAPPDATA") or "").strip()
    if local_app_data:
        candidates.append(Path(local_app_data) / "HDLE" / "hf_cache")
    candidates.append(Path(__file__).resolve().parent / "build" / "hf_cache")
    candidates.append(Path.cwd() / "build" / "hf_cache")

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            os.environ["HF_HOME"] = str(candidate)
            return
        except Exception:
            continue


def _resolve_model_target() -> tuple[Optional[str], Optional[Path]]:
    """Resolve configured model target as ('onnx'|'torch', path) or (None, None)."""
    raw = (os.getenv("PHONIKUD_MODEL_PATH") or "").strip()
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

    # Non-existing path: infer intent by extension.
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
