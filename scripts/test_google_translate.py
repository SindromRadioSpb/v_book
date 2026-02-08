"""Test Google Translate provider."""

if __name__ == '__main__':
    print("=== Google Translate Provider Test ===\n")

    # Import provider
    from app.infra.translators.providers.google_translate_provider import GoogleTranslateProvider
    from app.infra.translators.providers_registry import ProvidersRegistry
    from app.infra.translators.base_provider import TranslationRequest

    # Create and register provider
    provider = GoogleTranslateProvider()
    print(f"Provider ID: {provider.provider_id}")
    print(f"Display Name: {provider.display_name}")
    print(f"Supports Glossary: {provider.supports_glossary}")
    print(f"Supports Batch: {provider.supports_batch}")

    # Register
    registry = ProvidersRegistry()
    try:
        registry.register(provider)
        print(f"\n[OK] Provider registered successfully")
    except ValueError as e:
        print(f"\n[WARN] Provider already registered: {e}")

    # Healthcheck
    print(f"\nHealthcheck: ", end="")
    if provider.healthcheck():
        print("[PASSED]")
    else:
        print("[FAILED]")

    # Test translation
    print(f"\n--- Test Translation ---")
    request = TranslationRequest(
        source_text="Hello world",
        source_lang="en",
        target_lang="ru",
    )

    print(f"Source: {request.source_text} ({request.source_lang})")
    print(f"Target: {request.target_lang}")
    print(f"Translating...")

    result = provider.translate(request)

    if result.error_kind:
        print(f"[ERROR] {result.error_kind.value}")
        print(f"Message: {result.error_message}")
    else:
        print(f"[OK] Translation: {result.translated_text}")
        print(f"Latency: {result.latency_ms}ms")

    print(f"\n=== Test Complete ===")
