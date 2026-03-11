"""Migration regression for content-addressed audio_asset row identity."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.infra.db_path_resolver import get_supported_schema_version


def _apply_all_migrations(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        migrations = sorted(Path("app/infra/migrations").glob("*.sql"))
        for sql_file in migrations:
            conn.executescript(sql_file.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def test_audio_asset_migration_promotes_input_hash_identity():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        _apply_all_migrations(db_path)

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                """
                INSERT INTO audio_asset (
                    lang, norm_text, voice_id, speed, provider,
                    speech_hash, input_hash, asset_status, audio_rel_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "he",
                    "alpha",
                    "default",
                    1.0,
                    "google_cloud_tts",
                    "speech-1",
                    "input-1",
                    "ready",
                    "audio/a1.wav",
                ),
            )
            conn.execute(
                """
                INSERT INTO audio_asset (
                    lang, norm_text, voice_id, speed, provider,
                    speech_hash, input_hash, asset_status, audio_rel_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "he",
                    "alpha",
                    "default",
                    1.0,
                    "google_cloud_tts",
                    "speech-2",
                    "input-2",
                    "ready",
                    "audio/a2.wav",
                ),
            )
            conn.commit()

            count_rows = conn.execute(
                """
                SELECT COUNT(*) FROM audio_asset
                WHERE lang='he' AND norm_text='alpha' AND voice_id='default'
                  AND speed=1.0 AND provider='google_cloud_tts'
                """
            ).fetchone()[0]
            assert count_rows == 2

            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO audio_asset (
                        lang, norm_text, voice_id, speed, provider,
                        speech_hash, input_hash, asset_status, audio_rel_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "he",
                        "beta",
                        "default",
                        1.0,
                        "google_cloud_tts",
                        "speech-3",
                        "input-2",
                        "ready",
                        "audio/a3.wav",
                    ),
                )
                conn.commit()

            schema_version = conn.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
            assert schema_version is not None
            assert int(schema_version[0]) == get_supported_schema_version()
        finally:
            conn.close()
    finally:
        db_path.unlink(missing_ok=True)
