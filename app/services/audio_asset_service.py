"""Audio asset service (P0 stub).

P0 scope:
- Status lookup only (missing/ready/failed)
- Path sanitization helper for relative path contract
- No generation/playback in this stage
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Dict, Iterable, List

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.infra.sa_models import AudioAsset

logger = logging.getLogger(__name__)


class AudioAssetService:
    """Service for audio asset metadata lookup."""

    VALID_STATUSES = {"missing", "ready", "failed"}
    STATUS_PRIORITY = {
        "missing": 0,
        "failed": 1,
        "ready": 2,
    }

    @staticmethod
    def sanitize_relative_path(path_value: str) -> str:
        """Validate/sanitize relative audio path.

        Rules:
        - relative only (no drive letters, no leading slash/backslash)
        - no parent traversal (`..`)
        """
        value = (path_value or "").strip().replace("\\", "/")
        if not value:
            raise ValueError("audio path cannot be empty")
        if value.startswith("/") or value.startswith("\\"):
            raise ValueError("audio path must be relative")
        if ":" in value:
            raise ValueError("audio path must not contain drive specifier")
        parts = PurePosixPath(value).parts
        if ".." in parts:
            raise ValueError("audio path must not contain parent traversal")
        return str(PurePosixPath(value))

    def bulk_get_status(
        self,
        session: Session,
        *,
        lang: str,
        norm_texts: Iterable[str],
        voice_id: str = "default",
        speed: float = 1.0,
        provider: str = "none",
    ) -> Dict[str, str]:
        """Resolve audio status for norm_text list with default `missing`."""
        norm_list = [n for n in norm_texts if n]
        if not norm_list:
            return {}

        status_map = {norm: "missing" for norm in norm_list}
        stmt = (
            select(AudioAsset.norm_text, AudioAsset.asset_status)
            .where(
                AudioAsset.lang == lang,
                AudioAsset.voice_id == voice_id,
                AudioAsset.speed == speed,
                AudioAsset.provider == provider,
                AudioAsset.norm_text.in_(norm_list),
            )
        )
        for norm_text, status in session.execute(stmt).all():
            status_map[norm_text] = status if status in self.VALID_STATUSES else "failed"
        return status_map

    def bulk_get_status_any(
        self,
        session: Session,
        *,
        lang: str,
        norm_texts: Iterable[str],
    ) -> Dict[str, str]:
        """Resolve status across all provider/voice variants for given source norms."""
        norm_list = [n for n in norm_texts if n]
        if not norm_list:
            return {}

        status_map = {norm: "missing" for norm in norm_list}
        stmt = (
            select(AudioAsset.norm_text, AudioAsset.asset_status)
            .where(
                AudioAsset.lang == lang,
                AudioAsset.norm_text.in_(norm_list),
            )
        )
        for norm_text, status in session.execute(stmt).all():
            current = status_map.get(norm_text, "missing")
            candidate = status if status in self.VALID_STATUSES else "failed"
            if self.STATUS_PRIORITY.get(candidate, 0) >= self.STATUS_PRIORITY.get(current, 0):
                status_map[norm_text] = candidate
        return status_map

    def upsert_status(
        self,
        session: Session,
        *,
        lang: str,
        norm_text: str,
        voice_id: str = "default",
        speed: float = 1.0,
        provider: str = "none",
        speech_hash: str | None = None,
        input_hash: str | None = None,
        status: str = "missing",
        audio_rel_path: str | None = None,
        error_text: str | None = None,
    ) -> AudioAsset:
        """Internal helper used by tests/future generator integration."""
        if status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid asset status: {status}")
        safe_rel_path = None
        if audio_rel_path:
            safe_rel_path = self.sanitize_relative_path(audio_rel_path)

        stmt = select(AudioAsset).where(
            AudioAsset.lang == lang,
            AudioAsset.norm_text == norm_text,
            AudioAsset.voice_id == voice_id,
            AudioAsset.speed == speed,
            AudioAsset.provider == provider,
        )
        row = session.execute(stmt).scalar_one_or_none()
        if row:
            row.speech_hash = speech_hash
            row.input_hash = input_hash
            row.asset_status = status
            row.audio_rel_path = safe_rel_path
            row.error_text = error_text
            row.updated_at = self._now_str()
            return row

        row = AudioAsset(
            lang=lang,
            norm_text=norm_text,
            voice_id=voice_id,
            speed=speed,
            provider=provider,
            speech_hash=speech_hash,
            input_hash=input_hash,
            asset_status=status,
            audio_rel_path=safe_rel_path,
            error_text=error_text,
            updated_at=self._now_str(),
        )
        session.add(row)
        session.flush()
        return row

    def has_ready_input_hash(
        self,
        session: Session,
        *,
        lang: str,
        input_hash: str,
    ) -> bool:
        if not input_hash:
            return False
        stmt = select(AudioAsset.asset_id).where(
            and_(
                AudioAsset.lang == lang,
                AudioAsset.input_hash == input_hash,
                AudioAsset.asset_status == "ready",
                AudioAsset.audio_rel_path.is_not(None),
            )
        ).limit(1)
        return session.execute(stmt).scalar_one_or_none() is not None
    @staticmethod
    def _now_str() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
