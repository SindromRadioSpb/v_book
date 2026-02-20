"""Audio generation service (source-only canonical pipeline)."""

from __future__ import annotations

import hashlib
import html
import logging
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infra.audio.audio_provider_config_manager import AudioProviderConfigManager
from app.infra.audio import AudioGenerationRequest
from app.infra.audio.local_providers_setup import register_default_audio_providers
from app.infra.audio.providers_registry import AudioProvidersRegistry
from app.infra.sa_models import AudioAsset
from app.infra.settings import SettingsService
from app.services.audio_asset_service import AudioAssetService
from app.services.audio_usage_tracker import AudioUsageTracker
from app.services.pronunciation_quality_service import PronunciationQualityService
from app.services.pronunciation_service import PronunciationService
from app.domain.normalization.normalizer import normalize_for_tm

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

    DEFAULT_CHAIN = [
        "google_cloud_tts",
        "azure_speech_tts",
        "mock_local_audio",
        "mock_online_audio",
    ]

    def __init__(
        self,
        *,
        settings: Optional[SettingsService] = None,
        audio_asset_service: Optional[AudioAssetService] = None,
    ):
        self.settings = settings or SettingsService.get_instance()
        self.audio_asset_service = audio_asset_service or AudioAssetService()
        self.audio_provider_config = AudioProviderConfigManager(settings=self.settings)
        self.pronunciation_service = PronunciationService()
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
        if not self.settings.get_bool("audio/providers/enabled", True):
            return []
        if provider_mode.startswith("force:"):
            forced = provider_mode.split(":", 1)[1].strip()
            if not registry.get(forced):
                return []
            if not self._is_provider_enabled(forced):
                return []
            return [forced]

        chain = self.settings.get_json("audio/providers/chain", self.DEFAULT_CHAIN)
        if not isinstance(chain, list) or not chain:
            chain = list(self.DEFAULT_CHAIN)
        resolved = [
            pid
            for pid in chain
            if registry.get(str(pid)) and self._is_provider_enabled(str(pid))
        ]
        if not resolved:
            resolved = [
                pid
                for pid in self.DEFAULT_CHAIN
                if registry.get(pid) and self._is_provider_enabled(pid)
            ]
        return resolved

    def _is_provider_enabled(self, provider_id: str) -> bool:
        try:
            return bool(self.audio_provider_config.load_config(provider_id).enabled)
        except Exception:
            return True

    @staticmethod
    def _provider_supports_ssml(provider_id: str) -> bool:
        return provider_id in {"google_cloud_tts", "azure_speech_tts"}

    @staticmethod
    def _build_ssml_text(text_value: str) -> str:
        safe_text = PronunciationQualityService.sanitize_tts_text(text_value)
        escaped = html.escape(safe_text, quote=False)
        return f"<speak version='1.0'>{escaped}</speak>"

    @staticmethod
    def _build_ssml_ipa(surface_text: str, ipa_value: str) -> str:
        safe_surface = PronunciationQualityService.sanitize_tts_text(surface_text)
        escaped_surface = html.escape(safe_surface, quote=False)
        escaped_ipa = html.escape(ipa_value or "", quote=True)
        return (
            "<speak version='1.0'>"
            f"<phoneme alphabet='ipa' ph='{escaped_ipa}'>{escaped_surface}</phoneme>"
            "</speak>"
        )

    def _apply_token_pronunciation(
        self,
        session: Session,
        *,
        src_lang: str,
        source_text: str,
    ) -> str:
        parts = re.findall(r"\w+|[^\w]+", source_text, flags=re.UNICODE)
        if not parts:
            return source_text
        token_norms: Dict[str, str] = {}
        for part in parts:
            if not part or not part.strip() or not any(ch.isalnum() for ch in part):
                continue
            norm = normalize_for_tm(src_lang, part, "surface").norm
            if norm:
                token_norms[part] = norm
        if not token_norms:
            return source_text

        entries = self.pronunciation_service.bulk_lookup(
            session=session,
            lang=src_lang,
            src_norms=list(token_norms.values()),
        )
        if not entries:
            return source_text

        result_parts: List[str] = []
        changed = False
        for part in parts:
            norm = token_norms.get(part)
            if not norm:
                result_parts.append(part)
                continue
            entry = entries.get(norm)
            replacement = (entry.niqqud_text or "") if entry else ""
            if replacement:
                result_parts.append(replacement)
                if replacement != part:
                    changed = True
            else:
                result_parts.append(part)
        return "".join(result_parts) if changed else source_text

    def _prepare_pronunciation_payload(
        self,
        session: Session,
        *,
        src_lang: str,
        source_text: str,
        source_norm: str,
    ) -> Dict[str, str]:
        try:
            applied = self.pronunciation_service.apply_to_text(
                session=session,
                src_lang=src_lang,
                source_text=source_text,
                source_norm=source_norm,
            )
        except Exception:
            return {
                "text": source_text,
                "token_text": source_text,
                "ssml": "",
                "mode": "none",
                "is_valid": True,
                "qc_flag": None,
            }
        return {
            "text": applied.text or source_text,
            "token_text": applied.token_text or source_text,
            "ssml": applied.ssml or "",
            "mode": applied.mode or "none",
            "is_valid": bool(getattr(applied, "is_valid", True)),
            "qc_flag": getattr(applied, "qc_flag", None),
        }

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
        source_text = PronunciationQualityService.sanitize_tts_text((src_text or "").strip())
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

        global_voice_id, global_speed = self._resolve_voice_speed()
        provider_chain = self._resolve_provider_chain(provider_mode)
        if not provider_chain:
            last_error = "No audio provider available"
            self.audio_asset_service.upsert_status(
                session=session,
                lang=source_lang_clean,
                norm_text=source_norm_clean,
                voice_id=global_voice_id,
                speed=global_speed,
                provider="none",
                status="failed",
                error_text=last_error,
            )
            return {"ok": False, "status": "failed", "provider_id": None, "error": last_error}

        registry = AudioProvidersRegistry()
        usage_tracker = AudioUsageTracker(session)
        req_trace = trace_id or str(uuid.uuid4())
        last_error = "All providers failed"
        failed_recorded = False
        app_dir = _get_app_dir()
        source_char_count = len(source_text)
        pronunciation_payload = self._prepare_pronunciation_payload(
            session=session,
            src_lang=source_lang_clean,
            source_text=source_text,
            source_norm=source_norm_clean,
        )

        for provider_id in provider_chain:
            provider = registry.get(provider_id)
            if not provider:
                continue
            provider_cfg = self.audio_provider_config.load_config(provider_id)
            provider_voice_id = (
                global_voice_id
                if global_voice_id and global_voice_id != "default"
                else (provider_cfg.default_voice or "default")
            )
            provider_speed = global_speed
            if abs(provider_speed - 1.0) < 1e-6:
                provider_speed = max(0.5, min(2.0, float(provider_cfg.speech_rate or 1.0)))

            if source_char_count > int(provider_cfg.max_chars_per_request):
                last_error = (
                    f"Per-request limit exceeded for {provider_id}: "
                    f"{source_char_count}/{provider_cfg.max_chars_per_request} chars"
                )
                self.audio_asset_service.upsert_status(
                    session=session,
                    lang=source_lang_clean,
                    norm_text=source_norm_clean,
                    voice_id=provider_voice_id,
                    speed=provider_speed,
                    provider=provider_id,
                    status="failed",
                    error_text=last_error[:1000],
                )
                failed_recorded = True
                continue

            limits = provider_cfg.to_budget_limits()
            if limits.fail_closed and limits.has_budget_guards():
                try:
                    allowed, error_msg = usage_tracker.can_spend(
                        provider_id=provider_id,
                        char_count=source_char_count,
                        limits=limits,
                    )
                    if not allowed:
                        last_error = f"Budget limit exceeded: {error_msg}"
                        self.audio_asset_service.upsert_status(
                            session=session,
                            lang=source_lang_clean,
                            norm_text=source_norm_clean,
                            voice_id=provider_voice_id,
                            speed=provider_speed,
                            provider=provider_id,
                            status="failed",
                            error_text=last_error[:1000],
                        )
                        failed_recorded = True
                        continue
                except Exception as budget_err:
                    err_text = str(budget_err).lower()
                    if "no such table: audio_usage" in err_text:
                        logger.warning(
                            "Audio usage table is missing; skipping budget check for %s",
                            provider_id,
                        )
                        allowed = True
                        error_msg = None
                    elif limits.fail_closed:
                        last_error = f"Failed to check budget usage: {budget_err}"
                        self.audio_asset_service.upsert_status(
                            session=session,
                            lang=source_lang_clean,
                            norm_text=source_norm_clean,
                            voice_id=provider_voice_id,
                            speed=provider_speed,
                            provider=provider_id,
                            status="failed",
                            error_text=str(last_error)[:1000],
                        )
                        failed_recorded = True
                        continue
                    logger.warning(
                        "Audio budget check failed for %s (%s), continuing (fail_open)",
                        provider_id,
                        budget_err,
                    )

            prepared_text = pronunciation_payload.get("token_text") or source_text
            prepared_text = PronunciationQualityService.sanitize_tts_text(str(prepared_text))
            is_pron_valid = bool(pronunciation_payload.get("is_valid", True))
            fallback_reason: Optional[str] = None
            if not prepared_text:
                prepared_text = source_text
                fallback_reason = "qc:tts_sanitized_fallback:empty_after_tts_sanitize"
            if not is_pron_valid:
                prepared_text = source_text
                fallback_reason = "qc:tts_sanitized_fallback:invalid_pronunciation_payload"
            if fallback_reason:
                logger.info(
                    "Audio pronunciation fallback applied (%s): provider=%s lang=%s norm=%s trace=%s",
                    fallback_reason,
                    provider_id,
                    source_lang_clean,
                    source_norm_clean,
                    req_trace,
                )
            options: Dict[str, object] = {}
            if self._provider_supports_ssml(provider_id):
                ssml_payload = (pronunciation_payload.get("ssml") or "").strip()
                if ssml_payload and is_pron_valid:
                    options["ssml"] = ssml_payload

            request = AudioGenerationRequest(
                source_text=prepared_text,
                source_lang=source_lang_clean,
                source_norm=source_norm_clean,
                voice_id=provider_voice_id,
                speed=provider_speed,
                trace_id=req_trace,
                options=options,
            )
            result = provider.generate(request)
            if not result.is_success:
                last_error = result.error_message or "generation failed"
                self.audio_asset_service.upsert_status(
                    session=session,
                    lang=source_lang_clean,
                    norm_text=source_norm_clean,
                    voice_id=provider_voice_id,
                    speed=provider_speed,
                    provider=provider_id,
                    status="failed",
                    error_text=last_error[:1000],
                )
                failed_recorded = True
                continue

            rel_path = self._asset_rel_path(
                provider_id=provider_id,
                src_lang=source_lang_clean,
                source_norm=source_norm_clean,
                voice_id=provider_voice_id,
                speed=provider_speed,
            )
            safe_rel = self.audio_asset_service.sanitize_relative_path(rel_path)
            abs_path = app_dir / safe_rel
            self._write_atomic(abs_path, result.audio_bytes)
            payload_sha = hashlib.sha256(result.audio_bytes).hexdigest()

            row = self.audio_asset_service.upsert_status(
                session=session,
                lang=source_lang_clean,
                norm_text=source_norm_clean,
                voice_id=provider_voice_id,
                speed=provider_speed,
                provider=provider_id,
                status="ready",
                audio_rel_path=safe_rel,
                error_text=None,
            )
            row.duration_ms = result.duration_ms
            row.sha256 = payload_sha
            row.error_text = None
            try:
                usage_tracker.record_spend(
                    provider_id=provider_id,
                    char_count=source_char_count,
                    request_count=1,
                    commit=False,
                )
            except Exception as usage_err:
                logger.warning(
                    "Failed to record audio usage for %s (%s): %s",
                    provider_id,
                    req_trace,
                    usage_err,
                )
            return {
                "ok": True,
                "status": "ready",
                "provider_id": provider_id,
                "error": None,
                "audio_rel_path": safe_rel,
            }

        if not failed_recorded:
            self.audio_asset_service.upsert_status(
                session=session,
                lang=source_lang_clean,
                norm_text=source_norm_clean,
                voice_id=global_voice_id,
                speed=global_speed,
                provider="none",
                status="failed",
                error_text=last_error[:1000],
            )

        return {"ok": False, "status": "failed", "provider_id": None, "error": last_error}

    def count_ready_assets(self, session: Session) -> int:
        """Diagnostic helper for UI summary."""
        stmt = select(func.count(AudioAsset.asset_id)).where(AudioAsset.asset_status == "ready")
        return int(session.execute(stmt).scalar() or 0)
