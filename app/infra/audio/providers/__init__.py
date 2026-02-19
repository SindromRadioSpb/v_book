"""Built-in audio providers."""

from .azure_speech_tts_provider import AzureSpeechTTSProvider
from .google_cloud_tts_provider import GoogleCloudTTSProvider
from .mms_tts_local_provider import MMSTTSLocalProvider
from .mock_local_audio_provider import MockLocalAudioProvider
from .mock_online_audio_provider import MockOnlineAudioProvider

__all__ = [
    "GoogleCloudTTSProvider",
    "AzureSpeechTTSProvider",
    "MMSTTSLocalProvider",
    "MockLocalAudioProvider",
    "MockOnlineAudioProvider",
]
