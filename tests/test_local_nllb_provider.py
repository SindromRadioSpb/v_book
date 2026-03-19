"""Tests for LocalNLLBProvider (PATCH-06).

Tests verify:
- Provider properties and interface
- Language code mapping
- Translation with segmentation
- Glossary postprocessing integration
- Error handling
- Worker lifecycle management
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.infra.translators.base_provider import (
    TranslationRequest,
    TranslationResult,
    TranslationErrorKind,
)
from app.infra.translators.providers.local_nllb_provider import (
    LocalNLLBProvider,
    map_iso_to_nllb,
)
from app.infra.local_mt import WorkerRequest, WorkerResult
from app.services.local_mt import TextSegment
from app.infra.sa_models import TMEntry


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_worker():
    """Create mock worker for testing."""
    worker = Mock()
    worker.ping = Mock(return_value=True)
    worker.translate = Mock()
    worker.shutdown = Mock()
    return worker


@pytest.fixture
def mock_model_manager():
    """Create mock ModelResourceManager."""
    manager = Mock()
    manager.is_installed = Mock(return_value=(True, None))
    manager.model_dir = Mock(return_value="/fake/model/path")
    return manager


@pytest.fixture
def db_session():
    """Create in-memory database session for glossary testing."""
    from app.infra.sa_models import TMEntry, TMAlias

    engine = create_engine("sqlite:///:memory:")
    TMEntry.__table__.create(engine, checkfirst=True)
    TMAlias.__table__.create(engine, checkfirst=True)

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


# ============================================================================
# Test 1: Language Code Mapping
# ============================================================================


def test_map_iso_to_nllb_hebrew():
    """Map Hebrew ISO codes to NLLB."""
    assert map_iso_to_nllb("he") == "heb_Hebr"
    assert map_iso_to_nllb("iw") == "heb_Hebr"  # Alternative code
    assert map_iso_to_nllb("HE") == "heb_Hebr"  # Case insensitive


def test_map_iso_to_nllb_common_languages():
    """Map common languages to NLLB."""
    assert map_iso_to_nllb("en") == "eng_Latn"
    assert map_iso_to_nllb("ru") == "rus_Cyrl"
    assert map_iso_to_nllb("ar") == "arb_Arab"
    assert map_iso_to_nllb("es") == "spa_Latn"
    assert map_iso_to_nllb("fr") == "fra_Latn"
    assert map_iso_to_nllb("de") == "deu_Latn"


def test_map_iso_to_nllb_chinese():
    """Map Chinese variants to NLLB."""
    assert map_iso_to_nllb("zh") == "zho_Hans"  # Simplified
    assert map_iso_to_nllb("zh-CN") == "zho_Hans"  # Simplified
    assert map_iso_to_nllb("zh-TW") == "zho_Hant"  # Traditional


def test_map_iso_to_nllb_unsupported():
    """Unsupported language returns None."""
    assert map_iso_to_nllb("xx") is None
    assert map_iso_to_nllb("unsupported") is None


# ============================================================================
# Test 2: Provider Properties
# ============================================================================


def test_provider_properties(mock_model_manager, mock_worker):
    """Provider properties are correct."""
    with patch(
        "app.infra.translators.providers.local_nllb_provider.start_worker", return_value=mock_worker
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
            return_value=mock_model_manager,
        ):
            provider = LocalNLLBProvider()

            assert provider.provider_id == "local_nllb"
            assert "NLLB" in provider.display_name
            assert provider.supports_glossary is True
            assert provider.supports_batch is False
            assert "nllb" in provider.get_model_version()


def test_provider_healthcheck(mock_model_manager, mock_worker):
    """Healthcheck returns worker status."""
    with patch(
        "app.infra.translators.providers.local_nllb_provider.start_worker", return_value=mock_worker
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
            return_value=mock_model_manager,
        ):
            provider = LocalNLLBProvider()

            # Worker alive
            mock_worker.ping.return_value = True
            assert provider.healthcheck() is True

            # Worker dead
            mock_worker.ping.return_value = False
            assert provider.healthcheck() is False


# ============================================================================
# Test 3: Translation - Basic
# ============================================================================


def test_translate_simple(mock_model_manager, mock_worker):
    """Translate simple text."""
    # Mock worker response
    mock_worker.translate.return_value = WorkerResult(
        text="שלום עולם",
        source_lang="eng_Latn",
        target_lang="heb_Hebr",
        inference_time_ms=100.0,
    )

    with patch(
        "app.infra.translators.providers.local_nllb_provider.start_worker", return_value=mock_worker
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
            return_value=mock_model_manager,
        ):
            provider = LocalNLLBProvider()

            request = TranslationRequest(
                source_text="hello world",
                source_lang="en",
                target_lang="he",
            )

            result = provider.translate(request)

            # Check result
            assert result.is_success
            assert result.translated_text == "שלום עולם"
            assert result.provider_id == "local_nllb"
            assert result.cache_hit is False
            assert result.latency_ms >= 0

            # Check metadata
            assert "segment_count" in result.meta
            assert "inference_time_ms" in result.meta
            assert "model_id" in result.meta


def test_translate_empty_text(mock_model_manager, mock_worker):
    """Translate empty text returns empty."""
    with patch(
        "app.infra.translators.providers.local_nllb_provider.start_worker", return_value=mock_worker
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
            return_value=mock_model_manager,
        ):
            provider = LocalNLLBProvider()

            request = TranslationRequest(
                source_text="",
                source_lang="en",
                target_lang="he",
            )

            result = provider.translate(request)

            # Empty text returns empty result (not considered error)
            assert result.is_error is False
            assert result.translated_text == ""
            assert result.meta["segment_count"] == 0


# ============================================================================
# Test 4: Translation - Segmentation
# ============================================================================


def test_translate_long_text(mock_model_manager, mock_worker):
    """Long text is segmented and reassembled."""

    # Mock worker to return segment-by-segment translations
    def mock_translate(req: WorkerRequest) -> WorkerResult:
        # Simple mock: add [TRANSLATED] marker
        return WorkerResult(
            text=f"{req.text}[TRANSLATED]",
            source_lang=req.source_lang,
            target_lang=req.target_lang,
            inference_time_ms=50.0,
        )

    mock_worker.translate.side_effect = mock_translate

    with patch(
        "app.infra.translators.providers.local_nllb_provider.start_worker", return_value=mock_worker
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
            return_value=mock_model_manager,
        ):
            provider = LocalNLLBProvider()

            # Long text with multiple sentences
            request = TranslationRequest(
                source_text="First sentence here. Second sentence here. Third sentence here.",
                source_lang="en",
                target_lang="he",
            )

            result = provider.translate(request)

            assert result.is_success
            assert "[TRANSLATED]" in result.translated_text
            assert result.meta["segment_count"] >= 1  # At least one segment


# ============================================================================
# Test 5: Translation - Glossary Postprocess
# ============================================================================


def test_translate_with_glossary(mock_model_manager, mock_worker, db_session):
    """Translation applies glossary terms."""
    # Add approved TM entry
    tm_entry = TMEntry(
        tm_id=1,
        project_id=None,
        kind="term_cluster",
        src_lang="eng_Latn",
        tgt_lang="heb_Hebr",
        src_text="hello",
        src_norm="hello",
        translation="שלום (TM)",
        translation_norm="שלום (tm)",
        status="approved",
        origin="user_edit",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    db_session.add(tm_entry)
    db_session.commit()

    # Mock worker response (MT translation, different from TM)
    mock_worker.translate.return_value = WorkerResult(
        text="שלום (MT)",
        source_lang="eng_Latn",
        target_lang="heb_Hebr",
        inference_time_ms=100.0,
    )

    with patch(
        "app.infra.translators.providers.local_nllb_provider.start_worker", return_value=mock_worker
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
            return_value=mock_model_manager,
        ):
            provider = LocalNLLBProvider(db_session=db_session)

            request = TranslationRequest(
                source_text="hello",
                source_lang="en",
                target_lang="he",
            )

            result = provider.translate(request)

            # TM term should replace MT output
            assert result.is_success
            assert "TM" in result.translated_text  # TM translation used
            assert result.used_glossary is True
            assert result.meta["applied_terms_count"] == 1


def test_translate_without_glossary(mock_model_manager, mock_worker):
    """Translation without DB session skips glossary."""
    mock_worker.translate.return_value = WorkerResult(
        text="שלום עולם",
        source_lang="eng_Latn",
        target_lang="heb_Hebr",
        inference_time_ms=100.0,
    )

    with patch(
        "app.infra.translators.providers.local_nllb_provider.start_worker", return_value=mock_worker
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
            return_value=mock_model_manager,
        ):
            # No db_session provided
            provider = LocalNLLBProvider(db_session=None)

            request = TranslationRequest(
                source_text="hello world",
                source_lang="en",
                target_lang="he",
            )

            result = provider.translate(request)

            assert result.is_success
            assert result.used_glossary is False
            assert result.meta["applied_terms_count"] == 0


# ============================================================================
# Test 6: Error Handling
# ============================================================================


def test_translate_unsupported_language(mock_model_manager, mock_worker):
    """Unsupported language returns error."""
    with patch(
        "app.infra.translators.providers.local_nllb_provider.start_worker", return_value=mock_worker
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
            return_value=mock_model_manager,
        ):
            provider = LocalNLLBProvider()

            request = TranslationRequest(
                source_text="hello",
                source_lang="xx",  # Unsupported
                target_lang="he",
            )

            result = provider.translate(request)

            assert result.is_error
            assert result.error_kind == TranslationErrorKind.UNSUPPORTED
            assert "Unsupported language" in result.error_message


def test_translate_worker_error(mock_model_manager, mock_worker):
    """Worker error returns error result."""
    # Mock worker error
    mock_worker.translate.return_value = WorkerResult(
        text="",
        source_lang="eng_Latn",
        target_lang="heb_Hebr",
        inference_time_ms=0,
        error="Worker failed",
    )

    with patch(
        "app.infra.translators.providers.local_nllb_provider.start_worker", return_value=mock_worker
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
            return_value=mock_model_manager,
        ):
            provider = LocalNLLBProvider()

            request = TranslationRequest(
                source_text="hello",
                source_lang="en",
                target_lang="he",
            )

            result = provider.translate(request)

            assert result.is_error
            assert result.error_kind == TranslationErrorKind.SERVER
            assert (
                "Worker translation error" in result.error_message
                or "Translation failed" in result.error_message
            )


def test_translate_no_worker(mock_model_manager):
    """Translation without worker returns error."""
    with patch(
        "app.infra.translators.providers.local_nllb_provider.start_worker", return_value=None
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
            return_value=mock_model_manager,
        ):
            provider = LocalNLLBProvider()
            provider.worker = None  # Force no worker

            request = TranslationRequest(
                source_text="hello",
                source_lang="en",
                target_lang="he",
            )

            result = provider.translate(request)

            assert result.is_error
            assert result.error_kind == TranslationErrorKind.SERVER
            assert "Worker not initialized" in result.error_message


# ============================================================================
# Test 7: Worker Lifecycle
# ============================================================================


def test_provider_shutdown(mock_model_manager, mock_worker):
    """Provider shuts down worker cleanly."""
    with patch(
        "app.infra.translators.providers.local_nllb_provider.start_worker", return_value=mock_worker
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
            return_value=mock_model_manager,
        ):
            provider = LocalNLLBProvider()

            provider.shutdown()

            # Worker shutdown should be called
            mock_worker.shutdown.assert_called_once()

            # Worker reference cleared
            assert provider.worker is None


def test_provider_init_model_not_installed():
    """Provider initialization fails if model not installed."""
    mock_manager = Mock()
    mock_manager.is_installed = Mock(return_value=(False, "Model not found"))

    with patch(
        "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
        return_value=mock_manager,
    ):
        with pytest.raises(RuntimeError, match="Model not installed"):
            LocalNLLBProvider()


# ============================================================================
# Test 8: Language Pairs
# ============================================================================


def test_translate_various_language_pairs(mock_model_manager, mock_worker):
    """Test various language pair combinations."""
    mock_worker.translate.return_value = WorkerResult(
        text="translated",
        source_lang="eng_Latn",
        target_lang="rus_Cyrl",
        inference_time_ms=100.0,
    )

    with patch(
        "app.infra.translators.providers.local_nllb_provider.start_worker", return_value=mock_worker
    ):
        with patch(
            "app.infra.translators.providers.local_nllb_provider.ModelResourceManager",
            return_value=mock_model_manager,
        ):
            provider = LocalNLLBProvider()

            # Test pairs
            pairs = [
                ("en", "he"),
                ("en", "ru"),
                ("he", "en"),
                ("ru", "he"),
                ("en", "es"),
                ("fr", "de"),
            ]

            for src, tgt in pairs:
                request = TranslationRequest(
                    source_text="test",
                    source_lang=src,
                    target_lang=tgt,
                )

                result = provider.translate(request)
                assert result.is_success, f"Failed for {src}→{tgt}"
