"""Tests for glossary postprocessing (PATCH-05).

Tests verify:
- Text normalization
- TM query with approved terms
- Alias matching
- Glossary application to segments
- Project vs global scope
- Metadata tracking
"""
import pytest
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.infra.sa_models import TMEntry, TMAlias
from app.services.local_mt.glossary_postprocess import (
    normalize_text,
    query_approved_terms,
    query_aliases,
    apply_glossary,
    apply_glossary_to_text,
    AppliedTerm,
    PostprocessResult,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def db_session():
    """Create in-memory database session for testing."""
    engine = create_engine("sqlite:///:memory:")

    # Create minimal TM schema using raw SQL
    with engine.connect() as conn:
        # Disable foreign keys for testing (we don't have full schema)
        conn.execute(text("PRAGMA foreign_keys = OFF"))

        # Create TM tables directly (minimal schema for testing)
        conn.execute(text("""
            CREATE TABLE tm_entry (
                tm_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NULL,
                kind TEXT NOT NULL,
                src_lang TEXT NOT NULL,
                tgt_lang TEXT NOT NULL,
                src_text TEXT NOT NULL,
                src_norm TEXT NOT NULL,
                translation TEXT NOT NULL,
                translation_norm TEXT NULL,
                pos TEXT NULL,
                domain TEXT NULL,
                notes TEXT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                confidence REAL NULL,
                origin TEXT NOT NULL,
                source_ref TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                approved_at TEXT NULL,
                approved_by TEXT NULL
            )
        """))

        conn.execute(text("""
            CREATE TABLE tm_alias (
                alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
                tm_id INTEGER NOT NULL,
                alias_text TEXT NOT NULL,
                alias_norm TEXT NOT NULL
            )
        """))

        conn.commit()

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def sample_tm_entries(db_session):
    """Create sample TM entries for testing."""
    entries = [
        # Global approved term (English → Hebrew)
        TMEntry(
            tm_id=1,
            project_id=None,
            kind="term_cluster",
            src_lang="eng_Latn",
            tgt_lang="heb_Hebr",
            src_text="database system",
            src_norm="database system",
            translation="מערכת בסיס נתונים",
            translation_norm="מערכת בסיס נתונים",
            status="approved",
            confidence=0.95,
            origin="user_edit",
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
        ),
        # Global approved term (English → Hebrew)
        TMEntry(
            tm_id=2,
            project_id=None,
            kind="lemma",
            src_lang="eng_Latn",
            tgt_lang="heb_Hebr",
            src_text="file",
            src_norm="file",
            translation="קובץ",
            translation_norm="קובץ",
            status="approved",
            confidence=1.0,
            origin="import",
            source_ref="dict.csv",
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
        ),
        # Draft term (should not be applied)
        TMEntry(
            tm_id=3,
            project_id=None,
            kind="lemma",
            src_lang="eng_Latn",
            tgt_lang="heb_Hebr",
            src_text="draft term",
            src_norm="draft term",
            translation="טרם אושר",
            translation_norm="טרם אושר",
            status="draft",
            confidence=0.5,
            origin="mt_auto",
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
        ),
        # Project-specific term (project_id=100)
        TMEntry(
            tm_id=4,
            project_id=100,
            kind="term_cluster",
            src_lang="eng_Latn",
            tgt_lang="heb_Hebr",
            src_text="project term",
            src_norm="project term",
            translation="מונח פרויקט",
            translation_norm="מונח פרויקט",
            status="approved",
            confidence=0.9,
            origin="user_edit",
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
        ),
    ]

    for entry in entries:
        db_session.add(entry)
    db_session.commit()

    return entries


@pytest.fixture
def sample_aliases(db_session, sample_tm_entries):
    """Create sample TM aliases for testing."""
    aliases = [
        # Alias for "database system" (tm_id=1)
        TMAlias(
            alias_id=1,
            tm_id=1,
            alias_text="DB system",
            alias_norm="db system",
        ),
        TMAlias(
            alias_id=2,
            tm_id=1,
            alias_text="database sys",
            alias_norm="database sys",
        ),
    ]

    for alias in aliases:
        db_session.add(alias)
    db_session.commit()

    return aliases


# ============================================================================
# Test 1: Text Normalization
# ============================================================================


def test_normalize_text_lowercase():
    """Normalization converts to lowercase."""
    assert normalize_text("Hello World") == "hello world"
    assert normalize_text("DATABASE") == "database"


def test_normalize_text_whitespace():
    """Normalization collapses whitespace."""
    assert normalize_text("hello  world") == "hello world"
    assert normalize_text("  trim  spaces  ") == "trim spaces"
    assert normalize_text("hello\tworld\n") == "hello world"


def test_normalize_text_empty():
    """Empty text returns empty string."""
    assert normalize_text("") == ""
    assert normalize_text("   ") == ""


# ============================================================================
# Test 2: Query Approved Terms
# ============================================================================


def test_query_approved_terms_global(db_session, sample_tm_entries):
    """Query global approved terms."""
    terms = query_approved_terms(
        db_session,
        src_lang="eng_Latn",
        tgt_lang="heb_Hebr",
        project_id=None,
    )

    # Should return 2 approved global terms (tm_id=1, tm_id=2)
    assert len(terms) == 2
    assert "database system" in terms
    assert "file" in terms

    # Draft term should not be included
    assert "draft term" not in terms

    # Project term should not be included (we asked for global only)
    assert "project term" not in terms


def test_query_approved_terms_with_project(db_session, sample_tm_entries):
    """Query terms for specific project (includes global + project terms)."""
    terms = query_approved_terms(
        db_session,
        src_lang="eng_Latn",
        tgt_lang="heb_Hebr",
        project_id=100,
    )

    # Should return 3 approved terms (2 global + 1 project)
    assert len(terms) == 3
    assert "database system" in terms
    assert "file" in terms
    assert "project term" in terms


def test_query_approved_terms_wrong_language(db_session, sample_tm_entries):
    """Query with wrong language pair returns empty."""
    terms = query_approved_terms(
        db_session,
        src_lang="eng_Latn",
        tgt_lang="rus_Cyrl",  # No terms for this pair
        project_id=None,
    )

    assert len(terms) == 0


# ============================================================================
# Test 3: Query Aliases
# ============================================================================


def test_query_aliases(db_session, sample_aliases):
    """Query aliases for TM entries."""
    alias_dict = query_aliases(db_session, tm_ids=[1])

    assert len(alias_dict) == 2
    assert "db system" in alias_dict
    assert "database sys" in alias_dict
    assert alias_dict["db system"] == 1
    assert alias_dict["database sys"] == 1


def test_query_aliases_empty(db_session):
    """Query with no TM IDs returns empty."""
    alias_dict = query_aliases(db_session, tm_ids=[])
    assert len(alias_dict) == 0


# ============================================================================
# Test 4: Apply Glossary - Basic
# ============================================================================


def test_apply_glossary_exact_match(db_session, sample_tm_entries):
    """Apply glossary with exact matches."""
    source = ["database system", "file"]
    target = ["מערכת נתוני בסיס", "תיקייה"]  # MT translations (different from TM)

    result = apply_glossary(
        db_session,
        source_segments=source,
        target_segments=target,
        src_lang="eng_Latn",
        tgt_lang="heb_Hebr",
        project_id=None,
    )

    # Both should be replaced with TM translations
    assert len(result.translations) == 2
    assert result.translations[0] == "מערכת בסיס נתונים"  # TM translation
    assert result.translations[1] == "קובץ"  # TM translation

    # Metadata
    assert result.match_count == 2
    assert len(result.applied_terms) == 2

    # Check first applied term
    term0 = result.applied_terms[0]
    assert term0.segment_index == 0
    assert term0.src_text == "database system"
    assert term0.tm_translation == "מערכת בסיס נתונים"
    assert term0.mt_translation == "מערכת נתוני בסיס"
    assert term0.tm_id == 1


def test_apply_glossary_partial_match(db_session, sample_tm_entries):
    """Apply glossary with partial matches."""
    source = ["database system", "unknown term", "file"]
    target = ["MT1", "MT2", "MT3"]

    result = apply_glossary(
        db_session,
        source_segments=source,
        target_segments=target,
        src_lang="eng_Latn",
        tgt_lang="heb_Hebr",
        project_id=None,
    )

    # First and third should be replaced, second kept as MT
    assert result.translations[0] == "מערכת בסיס נתונים"  # TM
    assert result.translations[1] == "MT2"  # MT (no match)
    assert result.translations[2] == "קובץ"  # TM

    assert result.match_count == 2
    assert len(result.applied_terms) == 2


def test_apply_glossary_no_matches(db_session, sample_tm_entries):
    """Apply glossary with no matches."""
    source = ["unknown1", "unknown2"]
    target = ["MT1", "MT2"]

    result = apply_glossary(
        db_session,
        source_segments=source,
        target_segments=target,
        src_lang="eng_Latn",
        tgt_lang="heb_Hebr",
        project_id=None,
    )

    # All should be kept as MT
    assert result.translations == target
    assert result.match_count == 0
    assert len(result.applied_terms) == 0


def test_apply_glossary_no_terms_available(db_session):
    """Apply glossary when no TM terms exist."""
    source = ["hello", "world"]
    target = ["MT1", "MT2"]

    result = apply_glossary(
        db_session,
        source_segments=source,
        target_segments=target,
        src_lang="eng_Latn",
        tgt_lang="heb_Hebr",
        project_id=None,
    )

    # All should be kept as MT
    assert result.translations == target
    assert result.match_count == 0


# ============================================================================
# Test 5: Apply Glossary - Aliases
# ============================================================================


def test_apply_glossary_alias_match(db_session, sample_tm_entries, sample_aliases):
    """Apply glossary with alias matches."""
    source = ["DB system", "database sys"]  # Aliases for "database system"
    target = ["MT1", "MT2"]

    result = apply_glossary(
        db_session,
        source_segments=source,
        target_segments=target,
        src_lang="eng_Latn",
        tgt_lang="heb_Hebr",
        project_id=None,
    )

    # Both should be replaced via alias matching
    assert result.translations[0] == "מערכת בסיס נתונים"
    assert result.translations[1] == "מערכת בסיס נתונים"
    assert result.match_count == 2


# ============================================================================
# Test 6: Apply Glossary - Case Insensitivity
# ============================================================================


def test_apply_glossary_case_insensitive(db_session, sample_tm_entries):
    """Apply glossary is case-insensitive."""
    source = ["DATABASE SYSTEM", "File"]  # Different cases
    target = ["MT1", "MT2"]

    result = apply_glossary(
        db_session,
        source_segments=source,
        target_segments=target,
        src_lang="eng_Latn",
        tgt_lang="heb_Hebr",
        project_id=None,
    )

    # Should match despite case differences
    assert result.translations[0] == "מערכת בסיס נתונים"
    assert result.translations[1] == "קובץ"
    assert result.match_count == 2


# ============================================================================
# Test 7: Apply Glossary - Project Scope
# ============================================================================


def test_apply_glossary_project_scope(db_session, sample_tm_entries):
    """Apply glossary respects project scope."""
    source = ["project term", "database system"]
    target = ["MT1", "MT2"]

    # Without project_id, project term should not match
    result_global = apply_glossary(
        db_session,
        source_segments=source,
        target_segments=target,
        src_lang="eng_Latn",
        tgt_lang="heb_Hebr",
        project_id=None,
    )

    assert result_global.translations[0] == "MT1"  # No match
    assert result_global.translations[1] == "מערכת בסיס נתונים"  # Global term matched
    assert result_global.match_count == 1

    # With project_id=100, project term should match
    result_project = apply_glossary(
        db_session,
        source_segments=source,
        target_segments=target,
        src_lang="eng_Latn",
        tgt_lang="heb_Hebr",
        project_id=100,
    )

    assert result_project.translations[0] == "מונח פרויקט"  # Project term matched
    assert result_project.translations[1] == "מערכת בסיס נתונים"  # Global term matched
    assert result_project.match_count == 2


# ============================================================================
# Test 8: Apply Glossary - Error Handling
# ============================================================================


def test_apply_glossary_segment_mismatch(db_session):
    """Apply glossary raises error on segment count mismatch."""
    source = ["hello", "world"]
    target = ["MT1"]  # Wrong count

    with pytest.raises(ValueError, match="Segment count mismatch"):
        apply_glossary(
            db_session,
            source_segments=source,
            target_segments=target,
            src_lang="eng_Latn",
            tgt_lang="heb_Hebr",
        )


# ============================================================================
# Test 9: Convenience Function
# ============================================================================


def test_apply_glossary_to_text(db_session, sample_tm_entries):
    """Convenience function for single text pair."""
    source = "database system"
    target = "מערכת נתוני בסיס"  # MT translation

    updated, applied = apply_glossary_to_text(
        db_session,
        source_text=source,
        target_text=target,
        src_lang="eng_Latn",
        tgt_lang="heb_Hebr",
    )

    assert updated == "מערכת בסיס נתונים"  # TM translation
    assert len(applied) == 1
    assert applied[0].src_text == source


# ============================================================================
# Test 10: Edge Cases
# ============================================================================


def test_apply_glossary_empty_segments(db_session):
    """Apply glossary handles empty segments."""
    result = apply_glossary(
        db_session,
        source_segments=[],
        target_segments=[],
        src_lang="eng_Latn",
        tgt_lang="heb_Hebr",
    )

    assert result.translations == []
    assert result.match_count == 0


def test_apply_glossary_whitespace_segments(db_session, sample_tm_entries):
    """Apply glossary handles whitespace normalization."""
    source = ["  database   system  "]  # Extra whitespace
    target = ["MT1"]

    result = apply_glossary(
        db_session,
        source_segments=source,
        target_segments=target,
        src_lang="eng_Latn",
        tgt_lang="heb_Hebr",
    )

    # Should match despite extra whitespace
    assert result.translations[0] == "מערכת בסיס נתונים"
    assert result.match_count == 1
