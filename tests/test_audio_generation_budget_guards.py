"""Budget guard integration tests for audio generation service."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.infra.audio.base_provider import AudioGenerationRequest, AudioGenerationResult, BaseAudioProvider
from app.infra.audio.providers_registry import AudioProvidersRegistry
from app.infra.sa_models import AudioAsset
from app.services.audio_generation_service import AudioGenerationService


CREATE_AUDIO_USAGE_SQL = """
CREATE TABLE IF NOT EXISTS audio_usage (
    usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT NOT NULL,
    period_type TEXT NOT NULL,
    period_key TEXT NOT NULL,
    char_count INTEGER NOT NULL DEFAULT 0,
    request_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(provider_id, period_type, period_key)
)
"""


class _BudgetSettings:
    def __init__(self, *, fail_closed: bool):
        self.fail_closed = fail_closed

    def get_string(self, key: str, default: str = "") -> str:
        if key == "audio/voice_id":
            return "default"
        if key == "audio/speed":
            return "1.0"
        return default

    def get_json(self, key: str, default):
        if key == "audio/providers/chain":
            return ["budget_provider"]
        return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        if key == "audio/providers/enabled":
            return True
        if key == "audio/providers/budget_provider/enabled":
            return True
        if key == "audio/providers/budget_provider/fail_closed":
            return self.fail_closed
        return default

    def get_int(self, key: str, default: int = 0) -> int:
        if key == "audio/providers/budget_provider/max_requests_per_minute":
            return 1
        if key == "audio/providers/budget_provider/max_chars_per_request":
            return 10000
        if key == "audio/providers/budget_provider/retry_max_attempts":
            return 1
        if key == "audio/providers/budget_provider/retry_backoff_base_ms":
            return 100
        if key == "audio/providers/budget_provider/sample_rate_hz":
            return 24000
        return default


class _BudgetProvider(BaseAudioProvider):
    calls = 0

    @property
    def provider_id(self) -> str:
        return "budget_provider"

    @property
    def display_name(self) -> str:
        return "Budget Provider"

    def generate(self, _request: AudioGenerationRequest) -> AudioGenerationResult:
        _BudgetProvider.calls += 1
        return AudioGenerationResult(
            provider_id=self.provider_id,
            audio_bytes=b"RIFF....",
            mime_type="audio/wav",
        )


def _workspace_temp_dir(prefix: str) -> Path:
    root = Path("build") / "tmp_tests"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(root)))


def _prepare(monkeypatch, temp_dir: Path):
    monkeypatch.setattr("app.services.audio_generation_service.register_default_audio_providers", lambda: 0)
    monkeypatch.setattr("app.services.audio_generation_service._get_app_dir", lambda: temp_dir)
    AudioProvidersRegistry.reset()
    registry = AudioProvidersRegistry()
    registry.register(_BudgetProvider())


def test_budget_fail_closed_blocks_second_request(monkeypatch):
    temp_dir = _workspace_temp_dir("audio_budget_closed_")
    engine = create_engine(f"sqlite:///{temp_dir / 'audio.db'}")
    try:
        AudioAsset.__table__.create(engine, checkfirst=True)
        with Session(engine) as session:
            session.execute(text(CREATE_AUDIO_USAGE_SQL))
            session.commit()

        _prepare(monkeypatch, temp_dir)
        _BudgetProvider.calls = 0
        service = AudioGenerationService(settings=_BudgetSettings(fail_closed=True))

        with Session(engine) as session:
            first = service.generate_one(
                session,
                src_text="shalom",
                src_lang="he",
                source_norm="shalom",
                provider_mode="chain",
                force_regenerate=True,
                trace_id="budget-1",
            )
            second = service.generate_one(
                session,
                src_text="bayit",
                src_lang="he",
                source_norm="bayit",
                provider_mode="chain",
                force_regenerate=True,
                trace_id="budget-2",
            )
            session.commit()

            assert first["ok"] is True
            assert second["ok"] is False
            assert "budget" in str(second.get("error", "")).lower() or "rate" in str(second.get("error", "")).lower()
            assert _BudgetProvider.calls == 1
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_budget_fail_open_allows_second_request(monkeypatch):
    temp_dir = _workspace_temp_dir("audio_budget_open_")
    engine = create_engine(f"sqlite:///{temp_dir / 'audio.db'}")
    try:
        AudioAsset.__table__.create(engine, checkfirst=True)
        with Session(engine) as session:
            session.execute(text(CREATE_AUDIO_USAGE_SQL))
            session.commit()

        _prepare(monkeypatch, temp_dir)
        _BudgetProvider.calls = 0
        service = AudioGenerationService(settings=_BudgetSettings(fail_closed=False))

        with Session(engine) as session:
            first = service.generate_one(
                session,
                src_text="shalom",
                src_lang="he",
                source_norm="shalom",
                provider_mode="chain",
                force_regenerate=True,
                trace_id="budget-open-1",
            )
            second = service.generate_one(
                session,
                src_text="bayit",
                src_lang="he",
                source_norm="bayit",
                provider_mode="chain",
                force_regenerate=True,
                trace_id="budget-open-2",
            )
            session.commit()

            assert first["ok"] is True
            assert second["ok"] is True
            assert _BudgetProvider.calls == 2
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)
