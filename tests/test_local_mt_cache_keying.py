"""Tests for local MT cache keying (PATCH-09).

Tests verify:
- Deterministic cache key generation
- Model version included in cache key
- Glossary hash invalidates cache
- Backend change invalidates cache
- Cache hit/miss behavior
- Feature-safe: cache errors don't break translation
"""

import pytest
import hashlib
from unittest.mock import Mock, MagicMock, patch
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.services.translation_service import TranslationService
from app.infra.translators.base_provider import (
    TranslationRequest,
    TranslationResult,
)
from app.infra.translators.providers_registry import ProvidersRegistry


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def registry():
    """Create clean registry for each test."""
    ProvidersRegistry.reset()
    return ProvidersRegistry()


@pytest.fixture
def translation_service():
    """Create TranslationService instance."""
    return TranslationService()


@pytest.fixture
def db_session():
    """Create in-memory database session."""
    engine = create_engine("sqlite:///:memory:")

    # Create minimal schema (mt_cache table)
    with engine.connect() as conn:
        conn.execute(
            text(
                """
            CREATE TABLE mt_cache (
                cache_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NULL,
                provider TEXT NOT NULL,
                src_lang TEXT NOT NULL,
                tgt_lang TEXT NOT NULL,
                request_key TEXT NOT NULL,
                src_text TEXT NOT NULL,
                src_norm TEXT NOT NULL,
                glossary_hash TEXT NULL,
                translation TEXT NOT NULL,
                confidence REAL NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NULL,
                hit_count INTEGER NOT NULL DEFAULT 0,
                last_hit_at TEXT NULL,
                UNIQUE (provider, src_lang, tgt_lang, request_key)
            )
        """
            )
        )
        conn.commit()

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


# ============================================================================
# Test 1: Deterministic Cache Key
# ============================================================================


def test_build_cache_key_deterministic(translation_service):
    """Same inputs produce same cache key."""
    request = TranslationRequest(
        source_text="hello world",
        source_lang="en",
        target_lang="he",
        glossary_hash="abc123",
    )

    key1 = translation_service._build_cache_key(request, "local_nllb", "model_v1")
    key2 = translation_service._build_cache_key(request, "local_nllb", "model_v1")

    assert key1 == key2
    assert len(key1) == 64  # SHA256 hex digest


def test_build_cache_key_includes_all_params(translation_service):
    """Cache key changes when any parameter changes."""
    base_request = TranslationRequest(
        source_text="hello world",
        source_lang="en",
        target_lang="he",
        glossary_hash="abc123",
    )

    base_key = translation_service._build_cache_key(base_request, "local_nllb", "model_v1")

    # Change source text
    req1 = TranslationRequest(
        source_text="goodbye world",  # Different
        source_lang="en",
        target_lang="he",
        glossary_hash="abc123",
    )
    key1 = translation_service._build_cache_key(req1, "local_nllb", "model_v1")
    assert key1 != base_key

    # Change source language
    req2 = TranslationRequest(
        source_text="hello world",
        source_lang="ru",  # Different
        target_lang="he",
        glossary_hash="abc123",
    )
    key2 = translation_service._build_cache_key(req2, "local_nllb", "model_v1")
    assert key2 != base_key

    # Change target language
    req3 = TranslationRequest(
        source_text="hello world",
        source_lang="en",
        target_lang="ru",  # Different
        glossary_hash="abc123",
    )
    key3 = translation_service._build_cache_key(req3, "local_nllb", "model_v1")
    assert key3 != base_key

    # Change glossary_hash
    req4 = TranslationRequest(
        source_text="hello world",
        source_lang="en",
        target_lang="he",
        glossary_hash="xyz789",  # Different
    )
    key4 = translation_service._build_cache_key(req4, "local_nllb", "model_v1")
    assert key4 != base_key

    # Change model_version (PATCH-09)
    key5 = translation_service._build_cache_key(base_request, "local_nllb", "model_v2")  # Different
    assert key5 != base_key

    # Change provider_id
    key6 = translation_service._build_cache_key(
        base_request, "deepl", "model_v1"
    )  # Different provider
    assert key6 != base_key


# ============================================================================
# Test 2: Model Version Isolation
# ============================================================================


def test_cache_key_different_backends(translation_service):
    """Different backends produce different cache keys."""
    request = TranslationRequest(
        source_text="hello world",
        source_lang="en",
        target_lang="he",
    )

    key_ct2 = translation_service._build_cache_key(
        request, "local_nllb", "facebook_nllb-200-distilled-1.3B_ctranslate2"
    )
    key_transformers = translation_service._build_cache_key(
        request, "local_nllb", "facebook_nllb-200-distilled-1.3B_transformers"
    )

    assert key_ct2 != key_transformers


def test_cache_key_different_models(translation_service):
    """Different models produce different cache keys."""
    request = TranslationRequest(
        source_text="hello world",
        source_lang="en",
        target_lang="he",
    )

    key_nllb = translation_service._build_cache_key(
        request, "local_nllb", "facebook_nllb-200-distilled-1.3B_ctranslate2"
    )
    key_seamless = translation_service._build_cache_key(
        request, "local_seamless", "facebook_seamless-m4t-v2-large_transformers"
    )

    assert key_nllb != key_seamless


# ============================================================================
# Test 3: Glossary Hash Invalidation
# ============================================================================


def test_glossary_hash_change_invalidates_cache(translation_service):
    """Changing glossary_hash produces different cache key."""
    request1 = TranslationRequest(
        source_text="hello world",
        source_lang="en",
        target_lang="he",
        glossary_hash="hash1",
    )

    request2 = TranslationRequest(
        source_text="hello world",
        source_lang="en",
        target_lang="he",
        glossary_hash="hash2",  # Different glossary
    )

    key1 = translation_service._build_cache_key(request1, "local_nllb", "model_v1")
    key2 = translation_service._build_cache_key(request2, "local_nllb", "model_v1")

    assert key1 != key2


def test_empty_glossary_hash_stable(translation_service):
    """Empty/None glossary_hash is handled consistently."""
    request1 = TranslationRequest(
        source_text="hello world",
        source_lang="en",
        target_lang="he",
        glossary_hash="",
    )

    request2 = TranslationRequest(
        source_text="hello world",
        source_lang="en",
        target_lang="he",
        glossary_hash=None,
    )

    # Empty string and None should produce same key (both mean no glossary)
    key1 = translation_service._build_cache_key(request1, "local_nllb", "model_v1")
    key2 = translation_service._build_cache_key(request2, "local_nllb", "model_v1")

    assert key1 == key2


# ============================================================================
# Test 4: Text Normalization
# ============================================================================


def test_cache_key_whitespace_normalization(translation_service):
    """Whitespace differences are normalized."""
    request1 = TranslationRequest(
        source_text="hello  world",  # Double space
        source_lang="en",
        target_lang="he",
    )

    request2 = TranslationRequest(
        source_text="hello world",  # Single space
        source_lang="en",
        target_lang="he",
    )

    request3 = TranslationRequest(
        source_text="  hello world  ",  # Leading/trailing spaces
        source_lang="en",
        target_lang="he",
    )

    key1 = translation_service._build_cache_key(request1, "local_nllb", "model_v1")
    key2 = translation_service._build_cache_key(request2, "local_nllb", "model_v1")
    key3 = translation_service._build_cache_key(request3, "local_nllb", "model_v1")

    # All should produce same key after normalization
    assert key1 == key2 == key3


# ============================================================================
# Test 5: Model Version from Provider
# ============================================================================


def test_local_nllb_provider_model_version_includes_backend():
    """LocalNLLBProvider.get_model_version() includes backend."""
    from app.infra.translators.providers.local_nllb_provider import LocalNLLBProvider

    # Mock dependencies
    with patch(
        "app.infra.translators.providers.local_nllb_provider.ModelResourceManager"
    ) as MockManager:
        with patch(
            "app.infra.translators.providers.local_nllb_provider.start_worker"
        ) as mock_worker:
            mock_manager = MockManager.return_value
            mock_manager.is_installed = Mock(return_value=(True, None))
            mock_manager.model_dir = Mock(return_value="/fake/path")
            mock_worker.return_value = Mock(ping=Mock(return_value=True))

            provider = LocalNLLBProvider(
                model_id="facebook/nllb-200-distilled-1.3B",
                backend="ctranslate2",
            )

            model_version = provider.get_model_version()

            # Should include both model_id and backend
            assert "nllb-200-distilled-1.3B" in model_version
            assert "ctranslate2" in model_version
            assert "/" not in model_version  # Slashes should be replaced


# ============================================================================
# Test 6: Feature Safety - Cache Errors
# ============================================================================


def test_cache_error_does_not_break_translation(translation_service, db_session):
    """Cache lookup error doesn't prevent translation (feature-safe)."""
    # Simulate cache error by corrupting session
    broken_session = Mock()
    broken_session.execute = Mock(side_effect=Exception("Database error"))

    request = TranslationRequest(
        source_text="hello",
        source_lang="en",
        target_lang="he",
    )

    # Should return None on error, not raise
    result = translation_service._lookup_provider_cache(
        broken_session, request, "local_nllb", "model_v1"
    )

    # Cache miss = None (safe fallback)
    assert result is None


# ============================================================================
# Test 7: Empty Model Version
# ============================================================================


def test_empty_model_version_handled(translation_service):
    """Empty model_version is handled gracefully."""
    request = TranslationRequest(
        source_text="hello world",
        source_lang="en",
        target_lang="he",
    )

    # Empty model_version (for providers without get_model_version)
    key1 = translation_service._build_cache_key(request, "deepl", "")
    key2 = translation_service._build_cache_key(request, "deepl", "")

    # Should be deterministic
    assert key1 == key2

    # Should differ from non-empty version
    key3 = translation_service._build_cache_key(request, "deepl", "v1")
    assert key1 != key3
