"""Runtime adapter for optional Phonikud pronunciation inference."""

from __future__ import annotations

import importlib
import logging
import os
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from app.infra.resource_paths import ResourcePaths

logger = logging.getLogger(__name__)


class PhonikudMode(str, Enum):
    """Runtime mode returned by adapter."""

    REAL_INFERENCE = "real_inference"
    FALLBACK = "fallback"
    ERROR = "error"


class PhonikudHealthStatus(str, Enum):
    """Health status persisted in settings."""

    OK = "ok"
    FALLBACK = "fallback"
    ERROR = "error"


@dataclass
class PhonikudHealthReport:
    """Health-check report for UI and diagnostics."""

    mode: str
    status: str
    latency_ms: int
    model_path: str
    details: str
    samples: List[Dict[str, str]]

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


class PhonikudAdapter:
    """Adapter for optional local pronunciation inference backend."""

    _CALLABLE_ATTRS = ("add_niqqud", "phonikud", "nekud", "diacritize")
    _BATCH_CALLABLE_ATTRS = ("batch_add_niqqud", "batch_phonikud", "batch_nekud")

    def __init__(
        self,
        *,
        model_path: Optional[str] = None,
        enabled: bool = True,
        module_name: str = "phonikud",
    ):
        self.enabled = bool(enabled)
        self.model_path = self._sanitize_model_path(model_path or "")
        self.module_name = module_name

        self._module = None
        self._callable = None
        self._batch_callable = None
        self._load_error = ""
        self._last_mode: PhonikudMode = PhonikudMode.FALLBACK

    @property
    def last_mode(self) -> str:
        return self._last_mode.value

    @property
    def model_path_effective(self) -> str:
        resolved = self._resolve_model_path()
        return resolved or ""

    def _resolve_model_path(self) -> Optional[str]:
        direct = self._expand_model_candidate(self.model_path)
        if direct:
            return direct
        env_candidate = self._expand_model_candidate(os.getenv("PHONIKUD_MODEL_PATH") or "")
        if env_candidate:
            return env_candidate
        settings_candidate = self._expand_model_candidate(self._load_settings_model_path())
        if settings_candidate:
            return settings_candidate
        return self._discover_default_model_path()

    @staticmethod
    def _load_settings_model_path() -> str:
        try:
            from app.infra.settings import SettingsService

            settings = SettingsService.get_instance()
            return str(settings.get_string("pronunciation/phonikud/model_path", "") or "")
        except Exception:
            return ""

    @staticmethod
    def _resolve_models_root() -> Optional[Path]:
        try:
            from app.infra.settings import SettingsService

            settings = SettingsService.get_instance()
            return ResourcePaths.build(settings=settings, create=False).models_root
        except Exception:
            try:
                return ResourcePaths.build(create=False).models_root
            except Exception:
                return None

    def _discover_default_model_path(self) -> Optional[str]:
        models_root = self._resolve_models_root()
        if models_root is None:
            return None
        models_dir = models_root / "phonikud"
        if not models_dir.exists():
            return None
        preferred = sorted(models_dir.glob("*int8.onnx"))
        if preferred:
            return str(preferred[0])
        regular = sorted(models_dir.glob("*.onnx"))
        if regular:
            return str(regular[0])
        return None

    def model_path_safe(self) -> str:
        path_value = self.model_path_effective
        if not path_value:
            return ""
        path_obj = Path(path_value)
        if len(path_obj.parts) >= 2:
            return str(Path(*path_obj.parts[-2:]))
        return path_obj.name or "<configured>"

    def _configure_env(self) -> None:
        model_path = self._sanitize_model_path(self.model_path_effective)
        if model_path:
            os.environ["PHONIKUD_MODEL_PATH"] = model_path
        else:
            os.environ.pop("PHONIKUD_MODEL_PATH", None)

    @staticmethod
    def _sanitize_model_path(value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        return text.strip("\"'").rstrip(" .")

    def _expand_model_candidate(self, value: str) -> Optional[str]:
        cleaned = self._sanitize_model_path(value)
        if not cleaned:
            return None
        path = Path(cleaned)
        if path.is_file() and path.suffix.lower() == ".onnx":
            return str(path)
        if path.is_dir():
            preferred = sorted(path.glob("*int8.onnx"))
            if preferred:
                return str(preferred[0])
            regular = sorted(path.glob("*.onnx"))
            if regular:
                return str(regular[0])
        return str(path)

    def _reset_module_cache(self) -> None:
        if self._module is None:
            return
        reset_fn = getattr(self._module, "reset_runtime_cache", None)
        if callable(reset_fn):
            try:
                reset_fn()
                return
            except Exception:
                logger.debug("Phonikud module cache reset failed via reset_runtime_cache", exc_info=True)
        cached_loader = getattr(self._module, "_load_model_bundle", None)
        cache_clear = getattr(cached_loader, "cache_clear", None)
        if callable(cache_clear):
            try:
                cache_clear()
            except Exception:
                logger.debug("Phonikud module cache_clear failed", exc_info=True)

    def _ensure_loaded(self) -> None:
        if self._module is not None:
            return
        if not self.enabled:
            self._last_mode = PhonikudMode.ERROR
            self._load_error = "Phonikud disabled in settings"
            return

        self._configure_env()
        try:
            self._module = importlib.import_module(self.module_name)
        except Exception as exc:
            self._last_mode = PhonikudMode.ERROR
            self._load_error = f"Failed to import {self.module_name}: {exc}"
            logger.debug("Phonikud import failed: %s", exc)
            return

        self._reset_module_cache()

        for attr in self._CALLABLE_ATTRS:
            fn = getattr(self._module, attr, None)
            if callable(fn):
                self._callable = fn
                break
        for attr in self._BATCH_CALLABLE_ATTRS:
            fn = getattr(self._module, attr, None)
            if callable(fn):
                self._batch_callable = fn
                break

        if self._callable is None:
            self._last_mode = PhonikudMode.ERROR
            self._load_error = f"{self.module_name} has no callable inference function"
        else:
            self._last_mode = self._read_module_mode(default=PhonikudMode.FALLBACK)

    def _read_module_details(self) -> str:
        if self._module is None:
            return ""
        fn = getattr(self._module, "get_runtime_details", None)
        if not callable(fn):
            return ""
        try:
            return str(fn() or "").strip()
        except Exception:
            return ""

    def _read_module_mode(self, *, default: PhonikudMode) -> PhonikudMode:
        if self._module is None:
            return default

        fn = getattr(self._module, "get_runtime_mode", None)
        if not callable(fn):
            return default

        try:
            raw = str(fn() or "").strip().lower()
        except Exception:
            return default

        if raw in {"real", "real_inference", "ok"}:
            return PhonikudMode.REAL_INFERENCE
        if raw in {"fallback", "noop", "identity"}:
            return PhonikudMode.FALLBACK
        if raw in {"error", "failed"}:
            return PhonikudMode.ERROR
        return default

    def is_available(self) -> bool:
        self._ensure_loaded()
        return self._callable is not None

    def infer(self, texts: List[str]) -> Dict[str, str]:
        self._ensure_loaded()
        normalized = [str(text or "").strip() for text in (texts or [])]
        normalized = [text for text in normalized if text]

        if not normalized:
            return {}
        if self._callable is None:
            self._last_mode = PhonikudMode.ERROR
            return {text: text for text in normalized}

        outputs: Dict[str, str] = {}
        changed_any = False
        if self._batch_callable is not None:
            try:
                raw_batch = self._batch_callable(normalized)
                batch = [str(item or "").strip() for item in (raw_batch or [])]
                if len(batch) == len(normalized):
                    for source, rendered in zip(normalized, batch):
                        value = rendered or source
                        outputs[source] = value
                        if value != source:
                            changed_any = True
                else:
                    raise RuntimeError("batch output length mismatch")
            except Exception as exc:
                logger.debug("Phonikud batch inference failed, falling back to single-call mode: %s", exc)
                outputs.clear()
                changed_any = False

        if outputs:
            module_mode = self._read_module_mode(default=PhonikudMode.FALLBACK)
            if module_mode == PhonikudMode.ERROR:
                self._last_mode = PhonikudMode.ERROR
            elif module_mode == PhonikudMode.REAL_INFERENCE:
                self._last_mode = PhonikudMode.REAL_INFERENCE
            else:
                self._last_mode = PhonikudMode.REAL_INFERENCE if changed_any else PhonikudMode.FALLBACK
            return outputs

        for text in normalized:
            try:
                raw = self._callable(text)
                rendered = str(raw or "").strip()
                if not rendered:
                    rendered = text
                outputs[text] = rendered
                if rendered != text:
                    changed_any = True
            except Exception as exc:
                logger.debug("Phonikud inference failed for '%s': %s", text, exc)
                outputs[text] = text

        module_mode = self._read_module_mode(default=PhonikudMode.FALLBACK)
        if module_mode == PhonikudMode.ERROR:
            self._last_mode = PhonikudMode.ERROR
        elif module_mode == PhonikudMode.REAL_INFERENCE:
            self._last_mode = PhonikudMode.REAL_INFERENCE
        else:
            self._last_mode = PhonikudMode.REAL_INFERENCE if changed_any else PhonikudMode.FALLBACK
        return outputs

    def health_check(self, sample_texts: Optional[List[str]] = None) -> PhonikudHealthReport:
        samples = sample_texts or ["\u05e9\u05dc\u05d5\u05dd", "\u05ea\u05d7\u05e0\u05d4"]
        start = time.perf_counter()
        outputs = self.infer(samples)
        latency_ms = int((time.perf_counter() - start) * 1000)

        mode = self.last_mode
        if mode == PhonikudMode.REAL_INFERENCE.value:
            status = PhonikudHealthStatus.OK.value
            details = self._read_module_details() or "Real inference active"
        elif mode == PhonikudMode.FALLBACK.value:
            status = PhonikudHealthStatus.FALLBACK.value
            details = self._read_module_details() or "Fallback mode active; baseline quality may be degraded"
        else:
            status = PhonikudHealthStatus.ERROR.value
            details = self._read_module_details() or self._load_error or "Phonikud runtime unavailable"
        if mode != PhonikudMode.REAL_INFERENCE.value:
            expected_root = self._resolve_models_root()
            if expected_root is not None:
                details = f"{details}. Expected model path: {expected_root / 'phonikud'}"

        samples_payload = [
            {"input": text, "output": outputs.get(text, text)}
            for text in samples
        ]
        return PhonikudHealthReport(
            mode=mode,
            status=status,
            latency_ms=latency_ms,
            model_path=self.model_path_safe(),
            details=details,
            samples=samples_payload,
        )
