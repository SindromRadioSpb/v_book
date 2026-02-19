"""Audio playback helpers."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from sqlalchemy import and_, desc, select
from sqlalchemy.orm import Session

from app.infra.sa_models import AudioAsset


def _get_app_dir() -> Path:
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


class AudioPlaybackService:
    """Resolve ready audio asset path for UI playback controls."""

    @staticmethod
    def launch_audio_file(path: Path) -> None:
        """Open audio file with OS default player."""
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
            return
        subprocess.Popen(["xdg-open", str(path)])

    @staticmethod
    def resolve_ready_path(
        session: Session,
        *,
        lang: str,
        norm_text: str,
    ) -> Optional[Path]:
        stmt = (
            select(AudioAsset)
            .where(
                and_(
                    AudioAsset.lang == lang,
                    AudioAsset.norm_text == norm_text,
                    AudioAsset.asset_status == "ready",
                    AudioAsset.audio_rel_path.is_not(None),
                )
            )
            .order_by(desc(AudioAsset.updated_at), desc(AudioAsset.asset_id))
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
