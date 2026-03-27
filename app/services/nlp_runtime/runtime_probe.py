"""Machine-readable readiness probes for NLP runtimes."""

from __future__ import annotations

import logging
import os
from dataclasses import replace
from pathlib import Path

from app.infra.nlp_engines.stanza_engine import create_stanza_engine

from .dto import NlpRuntimeStatus

logger = logging.getLogger(__name__)


class NlpRuntimeProbe:
    """Best-effort runtime diagnostics for the current machine/environment."""

    STANZA_MODEL_ID = "he/tokenize,pos,lemma"

    def probe_stanza(self, *, use_gpu: bool = False, run_smoke: bool = True) -> NlpRuntimeStatus:
        runtime_mode = "gpu" if use_gpu else "cpu"
        cuda_available = self._probe_cuda_available()
        model_path = self._detect_stanza_model_path()
        model_present = bool(model_path and Path(model_path).exists())

        try:
            import stanza
        except ImportError as exc:
            return NlpRuntimeStatus(
                configured_engine_id="stanza",
                effective_engine_id=None,
                package_installed=False,
                model_present=model_present,
                pipeline_init_ok=False,
                smoke_ok=False,
                cuda_available=cuda_available,
                runtime_mode=runtime_mode,
                fallback_used=False,
                error_code="package_missing",
                error_detail=str(exc),
                remediation="Install the Python package in the active environment: pip install stanza",
                model_id=self.STANZA_MODEL_ID,
                model_path=model_path,
            )

        try:
            engine = create_stanza_engine(use_gpu=use_gpu)
        except RuntimeError as exc:
            error_detail = str(exc)
            error_code = "model_missing" if self._looks_like_missing_model(error_detail) else "pipeline_init_failed"
            remediation = (
                "Install or import the Hebrew Stanza model resources, then retry."
                if error_code == "model_missing"
                else "Check the active interpreter, model path, and runtime environment, then retry."
            )
            return NlpRuntimeStatus(
                configured_engine_id="stanza",
                effective_engine_id=None,
                package_installed=True,
                model_present=model_present,
                pipeline_init_ok=False,
                smoke_ok=False,
                cuda_available=cuda_available,
                runtime_mode=runtime_mode,
                fallback_used=False,
                error_code=error_code,
                error_detail=error_detail,
                remediation=remediation,
                engine_version=getattr(stanza, "__version__", None),
                model_id=self.STANZA_MODEL_ID,
                model_path=model_path,
            )

        status = NlpRuntimeStatus(
            configured_engine_id="stanza",
            effective_engine_id="stanza",
            package_installed=True,
            model_present=True if model_path else True,
            pipeline_init_ok=True,
            smoke_ok=not run_smoke,
            cuda_available=cuda_available,
            runtime_mode=runtime_mode,
            fallback_used=False,
            remediation="",
            engine_version=engine.get_version(),
            model_id=self.STANZA_MODEL_ID,
            model_path=model_path,
        )

        if not run_smoke:
            return status

        try:
            engine.process("שלום עולם.")
        except Exception as exc:
            logger.warning("Stanza smoke probe failed: %s", exc)
            return replace(
                status,
                effective_engine_id=None,
                smoke_ok=False,
                error_code="smoke_failed",
                error_detail=str(exc),
                remediation="The pipeline initialized but failed the smoke sentence. Reinstall the model or inspect the runtime logs.",
            )

        return replace(status, smoke_ok=True)

    @staticmethod
    def build_mock_status(
        *,
        configured_engine_id: str = "mock",
        fallback_used: bool = False,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> NlpRuntimeStatus:
        return NlpRuntimeStatus(
            configured_engine_id=configured_engine_id,
            effective_engine_id="mock",
            package_installed=True,
            model_present=False,
            pipeline_init_ok=True,
            smoke_ok=True,
            cuda_available=False,
            runtime_mode="cpu",
            fallback_used=fallback_used,
            error_code=error_code,
            error_detail=error_detail,
            remediation="Mock runtime is active only for diagnostic/demo or explicit fallback use.",
            engine_version="1.0.0",
            model_id=None,
            model_path=None,
        )

    @staticmethod
    def _probe_cuda_available() -> bool:
        try:
            import torch

            return bool(torch.cuda.is_available())
        except Exception:
            return False

    @staticmethod
    def _looks_like_missing_model(message: str) -> bool:
        text = str(message or "").lower()
        return "download" in text or "model" in text or "resource" in text

    @staticmethod
    def _detect_stanza_model_path() -> str | None:
        candidates: list[Path] = []

        explicit = os.getenv("STANZA_RESOURCES_DIR", "").strip()
        if explicit:
            candidates.append(Path(explicit) / "he")
            candidates.append(Path(explicit))

        candidates.append(Path.home() / "stanza_resources" / "he")

        local_appdata = os.getenv("LOCALAPPDATA", "").strip()
        if local_appdata:
            cache_root = Path(local_appdata) / "StanfordNLP" / "stanza" / "Cache"
            if cache_root.exists():
                for version_dir in sorted(cache_root.iterdir(), reverse=True):
                    if version_dir.is_dir():
                        candidates.append(version_dir / "resources" / "he")

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return None
