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
from typing import Dict, Iterable, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.infra.sa_models import AudioAsset
from app.services.audio_cache_key_service import AudioCacheKeyService

logger = logging.getLogger(__name__)


class AudioAssetService:
    """Service for audio asset metadata lookup."""

    VALID_STATUSES = {"missing", "ready", "failed"}
    STATUS_PRIORITY = {
        "missing": 0,
        "failed": 1,
        "ready": 2,
    }

    def __init__(self) -> None:
        self._cache_keys = AudioCacheKeyService()

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

    @staticmethod
    def _has_input_hash(value: str | None) -> bool:
        return bool(str(value or "").strip())

    def find_existing_asset(
        self,
        session: Session,
        *,
        lang: str,
        norm_text: str,
        voice_id: str = "default",
        speed: float = 1.0,
        provider: str = "none",
        input_hash: str | None = None,
    ) -> Optional[AudioAsset]:
        """Resolve the canonical metadata row for upsert/update purposes.

        New rows are identified by `(lang, input_hash)` when the exact request hash
        exists. Legacy/no-hash rows still fall back to the older weak lookup key.
        """
        if self._has_input_hash(input_hash):
            stmt = select(AudioAsset).where(
                AudioAsset.lang == lang,
                AudioAsset.input_hash == str(input_hash).strip(),
            )
            return session.execute(stmt).scalar_one_or_none()

        stmt = select(AudioAsset).where(
            AudioAsset.lang == lang,
            AudioAsset.norm_text == norm_text,
            AudioAsset.voice_id == voice_id,
            AudioAsset.speed == speed,
            AudioAsset.provider == provider,
        )
        return session.execute(stmt).scalar_one_or_none()

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
            current = status_map.get(norm_text, "missing")
            candidate = status if status in self.VALID_STATUSES else "failed"
            if self.STATUS_PRIORITY.get(candidate, 0) >= self.STATUS_PRIORITY.get(current, 0):
                status_map[norm_text] = candidate
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

    def bulk_get_status_for_items(
        self,
        session: Session,
        *,
        items: Iterable[dict],
    ) -> Dict[tuple[str, str, str], str]:
        """Resolve audio status for current pronunciation-aware source items.

        Each input item must provide:
        - `lang`
        - `norm_text`
        - `source_text`

        Returns:
        - `{(lang, norm_text, source_text): status}`
        """
        prepared: Dict[tuple[str, str, str], str] = {}
        speech_hashes_by_lang: Dict[str, Dict[str, List[tuple[str, str, str]]]] = {}

        for raw in items:
            lang = str(raw.get("lang") or "").strip()
            norm_text = str(raw.get("norm_text") or "").strip()
            source_text = str(raw.get("source_text") or "").strip()
            if not lang or not norm_text:
                continue
            key = (lang, norm_text, source_text)
            prepared[key] = "missing"
            if not source_text:
                continue
            payload = self._cache_keys.prepare_pronunciation_payload(
                session=session,
                src_lang=lang,
                source_text=source_text,
                source_norm=norm_text,
            )
            speech_hash = self._cache_keys.build_speech_hash(
                src_lang=lang,
                source_text=source_text,
                source_norm=norm_text,
                pronunciation_payload=payload,
            )
            speech_hashes_by_lang.setdefault(lang, {}).setdefault(speech_hash, []).append(key)

        for lang, hash_map in speech_hashes_by_lang.items():
            stmt = (
                select(AudioAsset.speech_hash, AudioAsset.asset_status)
                .where(
                    AudioAsset.lang == lang,
                    AudioAsset.speech_hash.in_(list(hash_map.keys())),
                )
            )
            for speech_hash, status in session.execute(stmt).all():
                candidate = status if status in self.VALID_STATUSES else "failed"
                for key in hash_map.get(str(speech_hash or ""), []):
                    current = prepared.get(key, "missing")
                    if self.STATUS_PRIORITY.get(candidate, 0) >= self.STATUS_PRIORITY.get(current, 0):
                        prepared[key] = candidate

        unresolved_by_lang: Dict[str, Dict[str, List[tuple[str, str, str]]]] = {}
        for key, status in prepared.items():
            if status != "missing":
                continue
            lang, norm_text, source_text = key
            if not source_text:
                continue
            unresolved_by_lang.setdefault(lang, {}).setdefault(norm_text, []).append(key)

        for lang, norm_map in unresolved_by_lang.items():
            stmt = (
                select(AudioAsset.norm_text, AudioAsset.asset_status)
                .where(
                    AudioAsset.lang == lang,
                    AudioAsset.norm_text.in_(list(norm_map.keys())),
                    AudioAsset.asset_status == "failed",
                )
            )
            for norm_text, _status in session.execute(stmt).all():
                for key in norm_map.get(str(norm_text or ""), []):
                    if prepared.get(key, "missing") == "missing":
                        prepared[key] = "failed"
        return prepared

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

        row = self.find_existing_asset(
            session,
            lang=lang,
            norm_text=norm_text,
            voice_id=voice_id,
            speed=speed,
            provider=provider,
            input_hash=input_hash,
        )
        if row:
            row.lang = lang
            row.norm_text = norm_text
            row.voice_id = voice_id
            row.speed = speed
            row.provider = provider
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
