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
from functools import lru_cache
from typing import Optional, Tuple

MODE_REAL = "real_inference"
MODE_FALLBACK = "fallback"
MODE_ERROR = "error"

_runtime_mode = MODE_FALLBACK
_runtime_details = "No PHONIKUD_MODEL_PATH configured; fallback mode"


def _normalize_input(text: str) -> str:
    return (text or "").strip()


@lru_cache(maxsize=1)
def _load_model_bundle() -> Optional[Tuple[object, object]]:
    global _runtime_mode, _runtime_details

    model_path = (os.getenv("PHONIKUD_MODEL_PATH") or "").strip()
    if not model_path:
        _runtime_mode = MODE_FALLBACK
        _runtime_details = "PHONIKUD_MODEL_PATH is empty; fallback mode"
        return None

    try:
        from transformers import AutoTokenizer
        from src.model.phonikud_model import PhoNikudModel
    except Exception as exc:
        _runtime_mode = MODE_ERROR
        _runtime_details = f"Model dependencies are unavailable: {exc}"
        return None

    try:
        model = PhoNikudModel.from_pretrained(model_path, trust_remote_code=True)
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        model.eval()
        _runtime_mode = MODE_REAL
        _runtime_details = "Model loaded successfully"
        return model, tokenizer
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

    model, tokenizer = bundle
    try:
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
