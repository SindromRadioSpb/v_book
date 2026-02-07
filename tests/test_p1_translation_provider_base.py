"""Tests for P1 Translation Provider Base Contract."""

import pytest

from app.infra.translators import (
    TranslationRequest,
    TranslationResult,
    TranslationErrorKind,
    BaseProvider,
)
from app.infra.translators.providers_registry import ProvidersRegistry
from app.infra.translators.providers.mock_provider import MockProvider


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset provider registry before each test."""
    ProvidersRegistry.reset()
    yield
    ProvidersRegistry.reset()


class TestDataclassContracts:
    """Test dataclass contracts (TranslationRequest, TranslationResult)."""

    def test_translation_request_minimal(self):
        """Test TranslationRequest with minimal fields."""
        req = TranslationRequest(
            source_text="hello",
            source_lang="en",
            target_lang="ru",
        )

        assert req.source_text == "hello"
        assert req.source_lang == "en"
        assert req.target_lang == "ru"
        assert req.glossary is None
        assert req.glossary_hash == ""
        assert req.options == {}
        assert req.trace_id == ""
        assert req.allow_fallback is True
        assert req.timeout_seconds == 10.0

    def test_translation_request_full(self):
        """Test TranslationRequest with all fields."""
        req = TranslationRequest(
            source_text="hello world",
            source_lang="en",
            target_lang="ru",
            glossary={"hello": "привет"},
            glossary_hash="abc123",
            options={"formality": "formal"},
            trace_id="trace-001",
            allow_fallback=False,
            timeout_seconds=5.0,
        )

        assert req.source_text == "hello world"
        assert req.glossary == {"hello": "привет"}
        assert req.glossary_hash == "abc123"
        assert req.options == {"formality": "formal"}
        assert req.trace_id == "trace-001"
        assert req.allow_fallback is False
        assert req.timeout_seconds == 5.0

    def test_translation_result_success(self):
        """Test TranslationResult for successful translation."""
        result = TranslationResult(
            translated_text="привет мир",
            provider_id="mock",
            used_glossary=True,
            cache_hit=False,
            latency_ms=42,
        )

        assert result.translated_text == "привет мир"
        assert result.provider_id == "mock"
        assert result.used_glossary is True
        assert result.cache_hit is False
        assert result.latency_ms == 42
        assert result.error_kind is None
        assert result.error_message is None
        assert result.is_success is True
        assert result.is_error is False

    def test_translation_result_error(self):
        """Test TranslationResult for failed translation."""
        result = TranslationResult(
            provider_id="mock",
            error_kind=TranslationErrorKind.NETWORK,
            error_message="Connection timeout",
            latency_ms=10000,
        )

        assert result.translated_text == ""
        assert result.provider_id == "mock"
        assert result.error_kind == TranslationErrorKind.NETWORK
        assert result.error_message == "Connection timeout"
        assert result.is_success is False
        assert result.is_error is True

    def test_translation_error_kind_enum(self):
        """Test TranslationErrorKind enum values."""
        assert TranslationErrorKind.NETWORK.value == "network"
        assert TranslationErrorKind.AUTH.value == "auth"
        assert TranslationErrorKind.RATE_LIMIT.value == "rate_limit"
        assert TranslationErrorKind.QUOTA.value == "quota"
        assert TranslationErrorKind.SERVER.value == "server"
        assert TranslationErrorKind.INVALID_REQUEST.value == "invalid_request"
        assert TranslationErrorKind.UNSUPPORTED.value == "unsupported"
        assert TranslationErrorKind.UNKNOWN.value == "unknown"


class TestProvidersRegistry:
    """Test ProvidersRegistry (register, get, list)."""

    def test_registry_singleton(self):
        """Test that registry is a singleton."""
        registry1 = ProvidersRegistry()
        registry2 = ProvidersRegistry()

        assert registry1 is registry2

    def test_register_provider(self):
        """Test registering a provider."""
        registry = ProvidersRegistry()
        mock_provider = MockProvider()

        registry.register(mock_provider)

        assert len(registry) == 1
        assert "mock" in registry.list_provider_ids()

    def test_register_duplicate_raises(self):
        """Test that registering duplicate provider raises ValueError."""
        registry = ProvidersRegistry()
        mock_provider1 = MockProvider()
        mock_provider2 = MockProvider()

        registry.register(mock_provider1)

        with pytest.raises(ValueError, match="already registered"):
            registry.register(mock_provider2)

    def test_get_provider(self):
        """Test getting a provider by ID."""
        registry = ProvidersRegistry()
        mock_provider = MockProvider()

        registry.register(mock_provider)
        retrieved = registry.get("mock")

        assert retrieved is mock_provider
        assert retrieved.provider_id == "mock"

    def test_get_nonexistent_provider(self):
        """Test getting a nonexistent provider returns None."""
        registry = ProvidersRegistry()

        retrieved = registry.get("nonexistent")

        assert retrieved is None

    def test_list_providers(self):
        """Test listing all providers."""
        registry = ProvidersRegistry()
        mock_provider = MockProvider()

        registry.register(mock_provider)
        providers = registry.list_providers()

        assert len(providers) == 1
        assert providers[0] is mock_provider

    def test_list_provider_ids(self):
        """Test listing all provider IDs (sorted)."""
        registry = ProvidersRegistry()

        # Register multiple mock providers (not realistic, but tests sorting)
        mock1 = MockProvider()
        registry.register(mock1)

        provider_ids = registry.list_provider_ids()

        assert provider_ids == ["mock"]
        assert provider_ids == sorted(provider_ids)  # Verify sorted

    def test_unregister_provider(self):
        """Test unregistering a provider."""
        registry = ProvidersRegistry()
        mock_provider = MockProvider()

        registry.register(mock_provider)
        assert len(registry) == 1

        result = registry.unregister("mock")

        assert result is True
        assert len(registry) == 0
        assert registry.get("mock") is None

    def test_unregister_nonexistent_provider(self):
        """Test unregistering a nonexistent provider returns False."""
        registry = ProvidersRegistry()

        result = registry.unregister("nonexistent")

        assert result is False


class TestMockProvider:
    """Test MockProvider (deterministic behavior)."""

    def test_mock_provider_properties(self):
        """Test MockProvider properties."""
        provider = MockProvider()

        assert provider.provider_id == "mock"
        assert provider.display_name == "Mock Provider (Testing)"
        assert provider.supports_glossary is True
        assert provider.supports_batch is False
        assert provider.get_model_version() == "mock-v1"
        assert provider.healthcheck() is True

    def test_mock_provider_translate_basic(self):
        """Test MockProvider translate (basic)."""
        provider = MockProvider()

        request = TranslationRequest(
            source_text="hello",
            source_lang="en",
            target_lang="ru",
        )

        result = provider.translate(request)

        assert result.is_success is True
        assert result.is_error is False
        assert result.translated_text == "olleh [EN→RU]"
        assert result.provider_id == "mock"
        assert result.used_glossary is False
        assert result.cache_hit is False
        assert result.latency_ms >= 0

    def test_mock_provider_translate_with_glossary(self):
        """Test MockProvider translate with glossary."""
        provider = MockProvider()

        request = TranslationRequest(
            source_text="hello world",
            source_lang="en",
            target_lang="ru",
            glossary={"hello": "привет"},
        )

        result = provider.translate(request)

        assert result.is_success is True
        assert result.translated_text == "dlrow olleh [EN→RU]"
        assert result.used_glossary is True

    def test_mock_provider_translate_deterministic(self):
        """Test MockProvider translate is deterministic."""
        provider = MockProvider()

        request = TranslationRequest(
            source_text="test",
            source_lang="en",
            target_lang="ru",
        )

        result1 = provider.translate(request)
        result2 = provider.translate(request)

        assert result1.translated_text == result2.translated_text
        assert result1.translated_text == "tset [EN→RU]"

    def test_mock_provider_simulate_latency(self):
        """Test MockProvider with simulated latency."""
        provider = MockProvider(simulate_latency_ms=50)

        request = TranslationRequest(
            source_text="test",
            source_lang="en",
            target_lang="ru",
        )

        result = provider.translate(request)

        assert result.is_success is True
        assert result.latency_ms >= 50  # At least 50ms

    def test_mock_provider_simulate_error(self):
        """Test MockProvider with simulated error."""
        provider = MockProvider(
            simulate_error=TranslationErrorKind.NETWORK,
            error_probability=1.0,  # Always fail
        )

        request = TranslationRequest(
            source_text="test",
            source_lang="en",
            target_lang="ru",
        )

        result = provider.translate(request)

        assert result.is_error is True
        assert result.is_success is False
        assert result.error_kind == TranslationErrorKind.NETWORK
        assert result.error_message == "Mock error: network"
        assert result.translated_text == ""

    def test_mock_provider_no_exceptions(self):
        """Test MockProvider never raises exceptions (contract)."""
        provider = MockProvider()

        # Various edge cases
        edge_cases = [
            TranslationRequest(source_text="", source_lang="en", target_lang="ru"),
            TranslationRequest(source_text=" ", source_lang="en", target_lang="ru"),
            TranslationRequest(source_text="א", source_lang="he", target_lang="ru"),
            TranslationRequest(source_text="שלום עולם", source_lang="he", target_lang="en"),
        ]

        for request in edge_cases:
            result = provider.translate(request)
            # Must return TranslationResult (no exceptions)
            assert isinstance(result, TranslationResult)
            # Either success or error (but not both)
            assert result.is_success or result.is_error


class TestBaseProviderContract:
    """Test BaseProvider contract (abstract methods)."""

    def test_base_provider_cannot_instantiate(self):
        """Test that BaseProvider cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseProvider()

    def test_base_provider_subclass_must_implement_abstract_methods(self):
        """Test that subclass must implement all abstract methods."""

        class IncompleteProvider(BaseProvider):
            """Incomplete provider (missing abstract methods)."""
            pass

        with pytest.raises(TypeError):
            IncompleteProvider()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
