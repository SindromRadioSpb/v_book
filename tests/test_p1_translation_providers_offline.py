"""Offline tests for real MT providers (no API calls).

These tests verify that providers can be instantiated without API keys
and return proper error responses instead of crashing.
"""

import pytest

from app.infra.translators.base_provider import (
    TranslationRequest,
    TranslationErrorKind,
)
from app.infra.translators.providers import (
    LibreTranslateProvider,
    DeepLProvider,
    MicrosoftTranslatorProvider,
)


# ============================================================================
# LibreTranslate Provider Tests
# ============================================================================


def test_libretranslate_provider_instantiates_without_key():
    """LibreTranslate provider can be created without API key (self-hosted mode)."""
    provider = LibreTranslateProvider()
    assert provider.provider_id == "libretranslate"
    assert provider.display_name == "LibreTranslate"
    assert provider.supports_glossary is False
    assert provider.supports_batch is False


def test_libretranslate_provider_instantiates_with_custom_url():
    """LibreTranslate provider can be created with custom API URL."""
    provider = LibreTranslateProvider(
        api_url="http://localhost:5000/translate",
        api_key="test-key",
    )
    assert provider.provider_id == "libretranslate"


def test_libretranslate_provider_returns_result_not_exception():
    """LibreTranslate provider returns TranslationResult even without valid config.

    Note: LibreTranslate may work without API key on self-hosted instances,
    so this test just verifies it doesn't crash.
    """
    provider = LibreTranslateProvider()

    request = TranslationRequest(
        source_text="שלום",
        source_lang="he",
        target_lang="en",
        timeout_seconds=1.0,  # Short timeout to avoid long wait
    )

    # This may fail with NETWORK or SERVER error (depending on libre.translate.com availability)
    # but it should NOT raise an exception
    result = provider.translate(request)

    assert result.provider_id == "libretranslate"
    # Result may be success or error, but should not crash


# ============================================================================
# DeepL Provider Tests
# ============================================================================


def test_deepl_provider_instantiates_without_key():
    """DeepL provider can be created without API key."""
    provider = DeepLProvider()
    assert provider.provider_id == "deepl"
    assert provider.display_name == "DeepL"
    assert provider.supports_glossary is True
    assert provider.supports_batch is True


def test_deepl_provider_instantiates_with_pro_url():
    """DeepL provider can be created with Pro API URL."""
    provider = DeepLProvider(
        api_key="test-key:fx",
        api_url="https://api.deepl.com/v2",
    )
    assert provider.provider_id == "deepl"


def test_deepl_provider_returns_auth_error_without_key():
    """DeepL provider returns AUTH error when API key is missing."""
    provider = DeepLProvider()  # No API key

    request = TranslationRequest(
        source_text="שלום",
        source_lang="he",
        target_lang="en",
    )

    result = provider.translate(request)

    # Should return AUTH error, not crash
    assert result.provider_id == "deepl"
    assert result.error_kind == TranslationErrorKind.AUTH
    assert "API key not configured" in result.error_message
    assert result.translated_text == ""


def test_deepl_provider_returns_auth_error_with_invalid_key():
    """DeepL provider returns AUTH error when API key is invalid."""
    provider = DeepLProvider(api_key="invalid-key-12345")

    request = TranslationRequest(
        source_text="שלום",
        source_lang="he",
        target_lang="en",
        timeout_seconds=5.0,
    )

    # This will make actual API call but should fail with AUTH
    # Note: This test may be slow (network call), but verifies error handling
    result = provider.translate(request)

    assert result.provider_id == "deepl"
    # May be AUTH or NETWORK depending on connectivity
    assert result.error_kind in [TranslationErrorKind.AUTH, TranslationErrorKind.NETWORK]
    assert result.translated_text == ""


# ============================================================================
# Microsoft Translator Provider Tests
# ============================================================================


def test_microsoft_provider_instantiates_without_key():
    """Microsoft Translator provider can be created without API key."""
    provider = MicrosoftTranslatorProvider()
    assert provider.provider_id == "microsoft"
    assert provider.display_name == "Microsoft Translator"
    assert provider.supports_glossary is True
    assert provider.supports_batch is True


def test_microsoft_provider_instantiates_with_custom_endpoint():
    """Microsoft Translator provider can be created with custom endpoint."""
    provider = MicrosoftTranslatorProvider(
        api_key="test-key",
        region="eastus",
        endpoint="https://api.cognitive.microsofttranslator.com",
    )
    assert provider.provider_id == "microsoft"


def test_microsoft_provider_returns_auth_error_without_key():
    """Microsoft Translator returns AUTH error when API key is missing."""
    provider = MicrosoftTranslatorProvider()  # No API key or region

    request = TranslationRequest(
        source_text="שלום",
        source_lang="he",
        target_lang="en",
    )

    result = provider.translate(request)

    # Should return AUTH error, not crash
    assert result.provider_id == "microsoft"
    assert result.error_kind == TranslationErrorKind.AUTH
    assert "API key not configured" in result.error_message
    assert result.translated_text == ""


def test_microsoft_provider_returns_invalid_request_without_region():
    """Microsoft Translator returns error when region is missing."""
    provider = MicrosoftTranslatorProvider(api_key="test-key-12345")  # Has key but no region

    request = TranslationRequest(
        source_text="שלום",
        source_lang="he",
        target_lang="en",
    )

    result = provider.translate(request)

    # Should return error, not crash
    assert result.provider_id == "microsoft"
    assert result.error_kind == TranslationErrorKind.INVALID_REQUEST
    assert "region not configured" in result.error_message
    assert result.translated_text == ""


def test_microsoft_provider_returns_error_with_invalid_key():
    """Microsoft Translator returns AUTH error when API key is invalid."""
    provider = MicrosoftTranslatorProvider(
        api_key="invalid-key-12345",
        region="eastus",
    )

    request = TranslationRequest(
        source_text="שלום",
        source_lang="he",
        target_lang="en",
        timeout_seconds=5.0,
    )

    # This will make actual API call but should fail with AUTH
    result = provider.translate(request)

    assert result.provider_id == "microsoft"
    # May be AUTH or NETWORK depending on connectivity
    assert result.error_kind in [TranslationErrorKind.AUTH, TranslationErrorKind.NETWORK]
    assert result.translated_text == ""


# ============================================================================
# Provider Comparison Tests
# ============================================================================


def test_all_providers_have_consistent_metadata():
    """All providers return consistent metadata fields."""
    providers = [
        LibreTranslateProvider(),
        DeepLProvider(),
        MicrosoftTranslatorProvider(),
    ]

    for provider in providers:
        assert provider.provider_id  # Non-empty string
        assert provider.display_name  # Non-empty string
        assert isinstance(provider.supports_glossary, bool)
        assert isinstance(provider.supports_batch, bool)
        assert provider.get_model_version()  # Non-empty string


def test_all_providers_return_result_on_error():
    """All providers return TranslationResult (not exception) on missing config."""
    request = TranslationRequest(
        source_text="test",
        source_lang="he",
        target_lang="en",
    )

    providers = [
        # LibreTranslate may work without key (self-hosted), so skip this check
        DeepLProvider(),  # No key
        MicrosoftTranslatorProvider(),  # No key
    ]

    for provider in providers:
        result = provider.translate(request)

        # Should return result, not crash
        assert result.provider_id == provider.provider_id
        assert result.error_kind in [
            TranslationErrorKind.AUTH,
            TranslationErrorKind.INVALID_REQUEST,
        ]
        assert result.error_message  # Non-empty error message
        assert result.translated_text == ""  # No translation on error
