"""Unit tests for Google Cloud TTS provider."""

from __future__ import annotations

import base64
import io
import json
import urllib.error
from unittest.mock import Mock, patch

from app.infra.audio.audio_provider_config import AudioProviderAuthMode, AudioProviderConfig
from app.infra.audio.audio_provider_config_manager import AudioProviderConfigManager
from app.infra.audio.base_provider import AudioGenerationRequest
from app.infra.audio.providers.google_cloud_tts_provider import GoogleCloudTTSProvider


class _Response:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._payload


def test_google_tts_retries_without_voice_name_when_saved_voice_invalid():
    config_mgr = Mock(spec=AudioProviderConfigManager)
    config_mgr.load_config.return_value = AudioProviderConfig(
        provider_id="google_cloud_tts",
        enabled=True,
        auth_mode=AudioProviderAuthMode.SERVICE_ACCOUNT_JSON,
        default_voice="he-IL-Neural2-B",
        retry_max_attempts=2,
        retry_backoff_base_ms=1,
        timeout_seconds=5.0,
    )

    provider = GoogleCloudTTSProvider(config_manager=config_mgr)
    provider._resolve_access_token_and_project = Mock(return_value=("test-token", "test-project"))

    bad_voice_error = urllib.error.HTTPError(
        url="https://texttospeech.googleapis.com/v1/text:synthesize",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=io.BytesIO(
            b'{"error":{"message":"Voice \\"he-IL-Neural2-B\\" does not exist. Is it misspelled?"}}'
        ),
    )
    ok_payload = json.dumps({"audioContent": base64.b64encode(b"wav-bytes").decode("ascii")}).encode("utf-8")

    request = AudioGenerationRequest(
        source_text="shalom",
        source_lang="he",
        source_norm="shalom",
        trace_id="test-google-voice-fallback",
    )

    with patch("urllib.request.urlopen", side_effect=[bad_voice_error, _Response(ok_payload)]) as mock_urlopen:
        result = provider.generate(request)

    assert result.is_success is True
    assert result.audio_bytes == b"wav-bytes"
    assert mock_urlopen.call_count == 2

    first_req = mock_urlopen.call_args_list[0].args[0]
    second_req = mock_urlopen.call_args_list[1].args[0]
    first_body = json.loads(first_req.data.decode("utf-8"))
    second_body = json.loads(second_req.data.decode("utf-8"))
    assert first_body["voice"].get("name") == "he-IL-Neural2-B"
    assert "name" not in second_body["voice"]

