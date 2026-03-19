"""Tests for BatchMTTranslateService (PATCH-UI-BATCH-T01).

Tests batch translation with deterministic MockProvider:
- Write mode behaviors (FILL_EMPTY, OVERWRITE, SKIP_NON_EMPTY)
- Per-row error handling (continue vs stop_on_error)
- Chunk commits with partial failures
- Cancel mid-batch
- Constraint validation
"""

import pytest
import tempfile
import sqlite3
from pathlib import Path

from app.services.batch_mt_translate_service import (
    BatchMTTranslateService,
    BatchTranslateItem,
    BatchTranslateOptions,
)
from app.infra.sa_models import TMEntry, TMGlobal
from app.services.translation_service import TranslationResult
from app.services.db_service import DBService
from app.services.tm_global_service import TMGlobalService


class MockTranslationService:
    """Mock translation service with deterministic output."""

    def __init__(self, translation_map=None, error_ids=None):
        """Initialize mock.

        Args:
            translation_map: dict[src_text] -> translation (default: uppercase)
            error_ids: set of entity_ids that should fail translation
        """
        self.translation_map = translation_map or {}
        self.error_ids = error_ids or set()
        self.call_count = 0

    def resolve_translation(
        self,
        session,
        src_text,
        kind,
        src_lang,
        tgt_lang,
        project_id=None,
        use_mt=True,
        allow_draft=False,
    ):
        """Mock resolve_translation - returns deterministic output."""
        self.call_count += 1

        # Simulate error for specific IDs
        if src_text in self.error_ids:
            raise Exception(f"Mock translation error for {src_text}")

        # Return translation
        if src_text in self.translation_map:
            translation = self.translation_map[src_text]
        else:
            translation = src_text.upper()  # Default: uppercase

        return TranslationResult(
            translation=translation,
            source="mock_provider",
            status="approved",
            provider="mock_provider",
        )


@pytest.fixture
def temp_db():
    """Create temporary database for testing using SQL migrations."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    # Apply SQL migrations directly
    migrations_dir = Path("app/infra/migrations")
    migration_files = sorted(migrations_dir.glob("*.sql"))

    conn = sqlite3.connect(str(db_path))
    try:
        for migration_file in migration_files:
            with open(migration_file, "r", encoding="utf-8") as f:
                sql = f.read()
                conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()

    # Initialize DBService
    DBService.initialize(str(db_path))

    yield db_path

    # Cleanup: Close DBService connections and reset singleton
    DBService._instance = None

    # Delete temp file
    try:
        db_path.unlink()
    except (PermissionError, FileNotFoundError):
        pass


def test_batch_translate_fill_empty_only(temp_db):
    """Test FILL_EMPTY mode - only translates empty rows."""
    service = BatchMTTranslateService()
    service.translation_service = MockTranslationService(
        translation_map={
            "hello": "HELLO_TRANSLATED",
            "world": "WORLD_TRANSLATED",
            "foo": "FOO_TRANSLATED",
        }
    )

    items = [
        BatchTranslateItem(
            entity_type="lemma",
            entity_id="hello",
            source_text="hello",
            src_lang="en",
            tgt_lang="ru",
            current_translation=None,  # Empty
            project_id=None,  # Global TM (no FK constraint)
        ),
        BatchTranslateItem(
            entity_type="lemma",
            entity_id="world",
            source_text="world",
            src_lang="en",
            tgt_lang="ru",
            current_translation="existing_translation",  # Not empty
            project_id=None,  # Global TM
        ),
        BatchTranslateItem(
            entity_type="lemma",
            entity_id="foo",
            source_text="foo",
            src_lang="en",
            tgt_lang="ru",
            current_translation="",  # Empty string
            project_id=None,  # Global TM
        ),
    ]

    options = BatchTranslateOptions(
        provider_mode="chain",
        write_mode="FILL_EMPTY",
        chunk_size=10,
    )

    db_service = DBService.get_instance()
    with db_service.get_session() as session:
        result = service.execute_batch(session, items, options)

    # Verify counts
    assert result.total == 3
    assert result.succeeded == 2  # hello, foo
    assert result.skipped == 1  # world (has existing translation)
    assert result.failed == 0

    # Verify row results
    assert result.row_results[0].new_translation == "HELLO_TRANSLATED"
    assert result.row_results[0].skipped is False

    assert result.row_results[1].new_translation is None
    assert result.row_results[1].skipped is True

    assert result.row_results[2].new_translation == "FOO_TRANSLATED"
    assert result.row_results[2].skipped is False

    # Verify DB writes
    with db_service.get_session() as session:
        entries = session.query(TMEntry).filter_by(kind="lemma", project_id=None).all()
        assert len(entries) == 2  # Only hello and foo written
        translations = {e.src_text: e.translation for e in entries}
        assert translations["hello"] == "HELLO_TRANSLATED"
        assert translations["foo"] == "FOO_TRANSLATED"


def test_batch_translate_overwrite_existing(temp_db):
    """Test OVERWRITE mode - translates ALL rows, replaces existing."""
    service = BatchMTTranslateService()
    service.translation_service = MockTranslationService(
        translation_map={
            "hello": "NEW_HELLO",
            "world": "NEW_WORLD",
        }
    )

    items = [
        BatchTranslateItem(
            entity_type="lemma",
            entity_id="hello",
            source_text="hello",
            src_lang="en",
            tgt_lang="ru",
            current_translation=None,
            project_id=None,
        ),
        BatchTranslateItem(
            entity_type="lemma",
            entity_id="world",
            source_text="world",
            src_lang="en",
            tgt_lang="ru",
            current_translation="old_translation",
            project_id=None,
        ),
    ]

    options = BatchTranslateOptions(
        provider_mode="chain",
        write_mode="OVERWRITE",
        chunk_size=10,
    )

    db_service = DBService.get_instance()
    with db_service.get_session() as session:
        result = service.execute_batch(session, items, options)

    # Verify counts
    assert result.total == 2
    assert result.succeeded == 2
    assert result.skipped == 0
    assert result.failed == 0

    # Verify translations
    assert result.row_results[0].new_translation == "NEW_HELLO"
    assert result.row_results[1].new_translation == "NEW_WORLD"
    assert result.row_results[1].old_translation == "old_translation"


def test_batch_translate_overwrite_forces_tm_global_update(temp_db):
    """OVERWRITE should replace existing higher-ranked tm_global translation."""
    service = BatchMTTranslateService()
    service.translation_service = MockTranslationService(translation_map={"alpha": "MT_NEW"})

    db_service = DBService.get_instance()
    with db_service.get_session() as session:
        existing = TMEntry(
            project_id=None,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text="alpha",
            src_norm="alpha",
            translation="USER_OLD",
            status="approved",
            origin="user_edit",
        )
        session.add(existing)
        session.flush()
        TMGlobalService().upsert_and_link(session, existing)
        session.commit()

    items = [
        BatchTranslateItem(
            entity_type="lemma",
            entity_id="alpha",
            source_text="alpha",
            src_lang="he",
            tgt_lang="ru",
            current_translation="USER_OLD",
            project_id=None,
        ),
    ]
    options = BatchTranslateOptions(
        provider_mode="chain",
        write_mode="OVERWRITE",
        chunk_size=10,
    )

    with db_service.get_session() as session:
        result = service.execute_batch(session, items, options)

    assert result.succeeded == 1
    assert result.failed == 0

    with db_service.get_session() as session:
        entry = (
            session.query(TMEntry).filter_by(kind="lemma", src_norm="alpha", project_id=None).one()
        )
        global_row = session.query(TMGlobal).filter_by(kind="lemma", src_norm="alpha").one()
        assert entry.translation == "MT_NEW"
        assert global_row.translation == "MT_NEW"


def test_batch_translate_per_row_error_continue(temp_db):
    """Test per-row error handling - continues on failure (default)."""
    service = BatchMTTranslateService()
    service.translation_service = MockTranslationService(error_ids={"world"})  # world will fail

    items = [
        BatchTranslateItem(
            entity_type="lemma",
            entity_id="hello",
            source_text="hello",
            src_lang="en",
            tgt_lang="ru",
            current_translation=None,
            project_id=None,
        ),
        BatchTranslateItem(
            entity_type="lemma",
            entity_id="world",
            source_text="world",
            src_lang="en",
            tgt_lang="ru",
            current_translation=None,
            project_id=None,
        ),
        BatchTranslateItem(
            entity_type="lemma",
            entity_id="foo",
            source_text="foo",
            src_lang="en",
            tgt_lang="ru",
            current_translation=None,
            project_id=None,
        ),
    ]

    options = BatchTranslateOptions(
        provider_mode="chain",
        write_mode="OVERWRITE",
        chunk_size=10,
        stop_on_error=False,  # Continue on error
    )

    db_service = DBService.get_instance()
    with db_service.get_session() as session:
        result = service.execute_batch(session, items, options)

    # Verify counts
    assert result.total == 3
    assert result.succeeded == 2  # hello, foo
    assert result.skipped == 0
    assert result.failed == 1  # world

    # Verify error message
    assert result.row_results[1].error_message is not None
    assert "Mock translation error" in result.row_results[1].error_message

    # Verify successful items still written
    with db_service.get_session() as session:
        entries = session.query(TMEntry).filter_by(kind="lemma", project_id=None).all()
        assert len(entries) == 2  # hello and foo


def test_batch_translate_dry_run(temp_db):
    """Test dry_run mode - no DB writes."""
    service = BatchMTTranslateService()
    service.translation_service = MockTranslationService()

    items = [
        BatchTranslateItem(
            entity_type="lemma",
            entity_id="hello",
            source_text="hello",
            src_lang="en",
            tgt_lang="ru",
            current_translation=None,
            project_id=None,
        ),
    ]

    options = BatchTranslateOptions(
        provider_mode="chain",
        write_mode="OVERWRITE",
        chunk_size=10,
        dry_run=True,  # Dry run
    )

    db_service = DBService.get_instance()
    with db_service.get_session() as session:
        result = service.execute_batch(session, items, options)

    # Verify counts
    assert result.total == 1
    assert result.succeeded == 1

    # Verify NO DB writes (dry run)
    with db_service.get_session() as session:
        entries = session.query(TMEntry).filter_by(kind="lemma", project_id=None).all()
        assert len(entries) == 0  # No writes in dry run


def test_batch_translate_trace_id(temp_db):
    """Test trace_id generation and logging."""
    service = BatchMTTranslateService()
    service.translation_service = MockTranslationService()

    items = [
        BatchTranslateItem(
            entity_type="lemma",
            entity_id="hello",
            source_text="hello",
            src_lang="en",
            tgt_lang="ru",
            current_translation=None,
            project_id=None,
        ),
    ]

    options = BatchTranslateOptions(
        provider_mode="chain",
        write_mode="OVERWRITE",
        chunk_size=10,
    )

    db_service = DBService.get_instance()
    with db_service.get_session() as session:
        result = service.execute_batch(session, items, options)

    # Verify trace_id generated
    assert result.trace_id is not None
    assert len(result.trace_id) == 36  # UUID format
