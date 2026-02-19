"""Audio generation service (source-only canonical pipeline)."""

from __future__ import annotations

import hashlib
import logging
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infra.audio import AudioGenerationRequest
from app.infra.audio.local_providers_setup import register_default_audio_providers
from app.infra.audio.providers_registry import AudioProvidersRegistry
from app.infra.sa_models import AudioAsset
from app.infra.settings import SettingsService
from app.services.audio_asset_service import AudioAssetService

logger = logging.getLogger(__name__)


def _get_app_dir() -> Path:
    """Resolve app data directory (same contract as app.main.get_app_dir)."""
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            app_dir = Path(local) / "HDLE"
        else:
            app_dir = Path.home() / "AppData" / "Local" / "HDLE"
    elif sys.platform == "darwin":
        app_dir = Path.home() / "Library" / "Application Support" / "HDLE"
    else:
        app_dir = Path.home() / ".local" / "share" / "hdle"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def list_available_audio_providers() -> List[str]:
    """List registered audio provider IDs (auto-register defaults once)."""
    register_default_audio_providers()
    return AudioProvidersRegistry().list_provider_ids()


class AudioGenerationService:
    """Generate and persist audio for canonical source terms."""

    DEFAULT_CHAIN = ["mock_local_audio", "mock_online_audio"]

    def __init__(
        self,
        *,
        settings: Optional[SettingsService] = None,
        audio_asset_service: Optional[AudioAssetService] = None,
    ):
        self.settings = settings or SettingsService.get_instance()
        self.audio_asset_service = audio_asset_service or AudioAssetService()
        register_default_audio_providers()

    def _resolve_voice_speed(self) -> Tuple[str, float]:
        voice_id = (self.settings.get_string("audio/voice_id", "default") or "default").strip() or "default"
        speed_raw = self.settings.get_string("audio/speed", "1.0")
        try:
            speed = float(speed_raw)
        except Exception:
            speed = 1.0
        speed = max(0.5, min(2.0, speed))
        return voice_id, speed

    def _resolve_provider_chain(self, provider_mode: str) -> List[str]:
        registry = AudioProvidersRegistry()
        if provider_mode.startswith("force:"):
            forced = provider_mode.split(":", 1)[1].strip()
            return [forced] if registry.get(forced) else []

        chain = self.settings.get_json("audio/providers/chain", self.DEFAULT_CHAIN)
        if not isinstance(chain, list) or not chain:
            chain = list(self.DEFAULT_CHAIN)
        resolved = [pid for pid in chain if registry.get(str(pid))]
        if not resolved:
            resolved = [pid for pid in self.DEFAULT_CHAIN if registry.get(pid)]
        return resolved

    @staticmethod
    def _asset_rel_path(
        *,
        provider_id: str,
        src_lang: str,
        source_norm: str,
        voice_id: str,
        speed: float,
    ) -> str:
        digest = hashlib.sha256(f"{src_lang}|{source_norm}|{voice_id}|{speed:.2f}".encode("utf-8")).hexdigest()[:20]
        safe_provider = provider_id.replace("/", "_").replace("\\", "_")
        safe_lang = src_lang.replace("/", "_").replace("\\", "_")
        return f"audio/{safe_provider}/{safe_lang}/{digest}.wav"

    @staticmethod
    def _write_atomic(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".tmp_audio_", suffix=".wav", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as tmp:
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                try:
                    os.remove(temp_name)
                except OSError:
                    pass

    def _has_ready_asset(
        self,
        session: Session,
        *,
        src_lang: str,
        source_norm: str,
    ) -> bool:
        status_map = self.audio_asset_service.bulk_get_status_any(
            session=session,
            lang=src_lang,
            norm_texts=[source_norm],
        )
        return status_map.get(source_norm) == "ready"

    def generate_one(
        self,
        session: Session,
        *,
        src_text: str,
        src_lang: str,
        source_norm: str,
        provider_mode: str = "chain",
        force_regenerate: bool = False,
        trace_id: str = "",
    ) -> Dict[str, object]:
        """Generate audio for source text only (translation is intentionally ignored)."""
        source_text = (src_text or "").strip()
        source_norm_clean = (source_norm or "").strip()
        source_lang_clean = (src_lang or "").strip()

        if not source_text or not source_norm_clean or not source_lang_clean:
            return {"ok": False, "status": "failed", "provider_id": None, "error": "invalid source payload"}

        if not force_regenerate and self._has_ready_asset(
            session,
            src_lang=source_lang_clean,
            source_norm=source_norm_clean,
        ):
            return {"ok": True, "status": "skipped", "provider_id": None, "error": None}

        voice_id, speed = self._resolve_voice_speed()
        provider_chain = self._resolve_provider_chain(provider_mode)
        if not provider_chain:
            return {"ok": False, "status": "failed", "provider_id": None, "error": "No audio provider available"}

        registry = AudioProvidersRegistry()
        req_trace = trace_id or str(uuid.uuid4())
        last_error = "All providers failed"
        app_dir = _get_app_dir()

        for provider_id in provider_chain:
            provider = registry.get(provider_id)
            if not provider:
                continue

            request = AudioGenerationRequest(
                source_text=source_text,
                source_lang=source_lang_clean,
                source_norm=source_norm_clean,
                voice_id=voice_id,
                speed=speed,
                trace_id=req_trace,
            )
            result = provider.generate(request)
            if not result.is_success:
                last_error = result.error_message or "generation failed"
                self.audio_asset_service.upsert_status(
                    session=session,
                    lang=source_lang_clean,
                    norm_text=source_norm_clean,
                    voice_id=voice_id,
                    speed=speed,
                    provider=provider_id,
                    status="failed",
                    error_text=last_error[:1000],
                )
                continue

            rel_path = self._asset_rel_path(
                provider_id=provider_id,
                src_lang=source_lang_clean,
                source_norm=source_norm_clean,
                voice_id=voice_id,
                speed=speed,
            )
            safe_rel = self.audio_asset_service.sanitize_relative_path(rel_path)
            abs_path = app_dir / safe_rel
            self._write_atomic(abs_path, result.audio_bytes)
            payload_sha = hashlib.sha256(result.audio_bytes).hexdigest()

            row = self.audio_asset_service.upsert_status(
                session=session,
                lang=source_lang_clean,
                norm_text=source_norm_clean,
                voice_id=voice_id,
                speed=speed,
                provider=provider_id,
                status="ready",
                audio_rel_path=safe_rel,
                error_text=None,
            )
            row.duration_ms = result.duration_ms
            row.sha256 = payload_sha
            row.error_text = None
            return {
                "ok": True,
                "status": "ready",
                "provider_id": provider_id,
                "error": None,
                "audio_rel_path": safe_rel,
            }

        return {"ok": False, "status": "failed", "provider_id": None, "error": last_error}

    def count_ready_assets(self, session: Session) -> int:
        """Diagnostic helper for UI summary."""
        stmt = select(func.count(AudioAsset.asset_id)).where(AudioAsset.asset_status == "ready")
        return int(session.execute(stmt).scalar() or 0)
