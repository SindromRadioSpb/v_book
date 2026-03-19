"""Audio playback helpers."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from sqlalchemy import and_, desc, select
from sqlalchemy.orm import Session

from app.infra.resource_paths import ResourcePaths
from app.infra.sa_models import AudioAsset
from app.services.audio_cache_key_service import AudioCacheKeyService


def _get_app_dir() -> Path:
    return ResourcePaths.resolve_data_root(create=True)


class AudioPlaybackService:
    """Resolve ready audio asset path for UI playback controls."""

    _cache_keys = AudioCacheKeyService()

    @staticmethod
    def _launch_external(path: Path) -> None:
        """Open audio file with OS default player."""
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
            return
        subprocess.Popen(["xdg-open", str(path)])

    @staticmethod
    def launch_audio_file(path: Path, *, label: str = "", play_mode: str | None = None) -> None:
        """Play one audio file using internal player (fallback: external launcher)."""
        try:
            from app.services.audio_player_service import AudioPlayerService

            player = AudioPlayerService.get_instance()
            if player.is_available:
                player.play_path(path, label=label or path.stem, play_mode=play_mode or "interrupt")
                return
        except Exception:
            # Fall back to external playback for environments without QtMultimedia.
            pass
        AudioPlaybackService._launch_external(path)

    @staticmethod
    def launch_audio_files(
        paths: Sequence[Path],
        *,
        labels: Sequence[str] | None = None,
        play_mode: str = "enqueue",
        contexts: Sequence[dict[str, object]] | None = None,
        start_immediately: bool = False,
    ) -> int:
        """Play/enqueue many audio files using internal player (fallback: first external)."""
        valid_paths = [Path(p) for p in paths if p and Path(p).exists()]
        if not valid_paths:
            return 0

        try:
            from app.services.audio_player_service import AudioPlayerService

            player = AudioPlayerService.get_instance()
            if player.is_available:
                return player.play_paths(
                    valid_paths,
                    labels=labels,
                    play_mode=play_mode,
                    contexts=contexts,
                    start_immediately=start_immediately,
                )
        except Exception:
            pass

        # External fallback cannot safely queue cross-platform; open first file.
        AudioPlaybackService._launch_external(valid_paths[0])
        return 1

    @staticmethod
    def resolve_ready_paths(
        session: Session,
        *,
        items: Iterable[dict],
    ) -> list[tuple[Path, dict]]:
        """Resolve ready audio paths for many source items in deterministic order."""
        resolved: list[tuple[Path, dict]] = []
        for item in items:
            try:
                lang = str(item.get("src_lang") or "").strip()
                norm_text = str(item.get("src_norm") or "").strip()
                src_text = str(item.get("src_text") or "").strip()
            except Exception:
                continue
            if not lang or not norm_text:
                continue
            path = AudioPlaybackService.resolve_ready_path(
                session,
                lang=lang,
                norm_text=norm_text,
                source_text=src_text or None,
            )
            if path:
                resolved.append((path, item))
        return resolved

    @staticmethod
    def resolve_ready_path(
        session: Session,
        *,
        lang: str,
        norm_text: str,
        source_text: str | None = None,
    ) -> Path | None:
        speech_hash = None
        if source_text:
            payload = AudioPlaybackService._cache_keys.prepare_pronunciation_payload(
                session=session,
                src_lang=lang,
                source_text=source_text,
                source_norm=norm_text,
            )
            speech_hash = AudioPlaybackService._cache_keys.build_speech_hash(
                src_lang=lang,
                source_text=source_text,
                source_norm=norm_text,
                pronunciation_payload=payload,
            )

        filters = [
            AudioAsset.lang == lang,
            AudioAsset.asset_status == "ready",
            AudioAsset.audio_rel_path.is_not(None),
        ]
        if speech_hash:
            filters.append(AudioAsset.speech_hash == speech_hash)
        else:
            filters.append(AudioAsset.norm_text == norm_text)

        stmt = (
            select(AudioAsset)
            .where(and_(*filters))
            .order_by(
                desc(AudioAsset.updated_at),
                desc(AudioAsset.asset_id),
            )
            .limit(1)
        )
        row = session.execute(stmt).scalar_one_or_none()
        if not row or not row.audio_rel_path:
            return None
        rel = Path(str(row.audio_rel_path))
        # Safety: keep relative-only contract.
        if rel.is_absolute() or ".." in rel.parts:
            return None
        abs_path = _get_app_dir() / rel
        if abs_path.exists():
            return abs_path
        return None
