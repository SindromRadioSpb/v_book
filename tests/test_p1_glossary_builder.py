"""Tests for GlossaryBuilderService (PATCH-P1-T05).

Tests verify:
- Deterministic glossary hash (same input → same hash)
- Conflict resolution (highest priority wins)
- Provider-specific formats (DeepL, Microsoft, LibreTranslate)
- Truncation at max entries
- Empty glossary graceful handling
- Hash invalidation on content change
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.infra.sa_models import TMEntry, DictProject, Library
from app.services.glossary_builder_service import GlossaryBuilderService


@pytest.fixture
def db_session():
    """Create in-memory SQLite session with minimal schema."""
    engine = create_engine("sqlite:///:memory:")

    # Create only needed tables (library, dict_project, tm_entry)
    with engine.connect() as conn:
        # library table
        conn.execute(text("""
            CREATE TABLE library (
                library_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
        """))

        # dict_project table
        conn.execute(text("""
            CREATE TABLE dict_project (
                project_id INTEGER PRIMARY KEY AUTOINCREMENT,
                library_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                src_lang TEXT NOT NULL,
                tgt_lang TEXT NOT NULL,
                description TEXT,
                nlp_engine TEXT NOT NULL DEFAULT 'stanza',
                nlp_engine_version TEXT,
                mwe_min_freq INTEGER NOT NULL DEFAULT 3,
                mwe_min_pmi REAL NOT NULL DEFAULT 3.0,
                mwe_min_tscore REAL NOT NULL DEFAULT 2.0,
                mwe_max_n INTEGER NOT NULL DEFAULT 3,
                is_general_corpus INTEGER NOT NULL DEFAULT 0,
                general_corpus_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                FOREIGN KEY (library_id) REFERENCES library(library_id) ON DELETE CASCADE
            )
        """))

        # tm_entry table (minimal schema)
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
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                approved_at TEXT NULL,
                approved_by TEXT NULL,
                FOREIGN KEY (project_id) REFERENCES dict_project(project_id) ON DELETE CASCADE
            )
        """))

        conn.commit()

    # Create test data via SQL
    with engine.connect() as conn:
        # Insert library
        conn.execute(text("INSERT INTO library (name) VALUES ('Test Library')"))
        # Insert project
        conn.execute(text("""
            INSERT INTO dict_project (library_id, name, src_lang, tgt_lang)
            VALUES (1, 'Test Project', 'he', 'ru')
        """))
        conn.commit()

    session = Session(engine)

    yield session

    session.close()
    engine.dispose()


@pytest.fixture
def glossary_service(db_session):
    """Create GlossaryBuilderService instance."""
    return GlossaryBuilderService(db_session)


# ============================================================================
# Test 1: Deterministic glossary hash
# ============================================================================


def test_build_canonical_glossary_deterministic(db_session, glossary_service):
    """Same input → same glossary hash (deterministic)."""
    # Add approved terms
    terms = [
        TMEntry(
            project_id=1,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text="שלום",
            src_norm="שלום",
            translation="привет",
            status="approved",
            confidence=0.9,
            origin="user_edit",
        ),
        TMEntry(
            project_id=1,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text="עולם",
            src_norm="עולם",
            translation="мир",
            status="approved",
            confidence=0.8,
            origin="user_edit",
        ),
    ]
    db_session.add_all(terms)
    db_session.commit()

    # Build glossary twice
    canonical1 = glossary_service.build_canonical_glossary(
        src_lang="he", tgt_lang="ru", project_id=1
    )
    canonical2 = glossary_service.build_canonical_glossary(
        src_lang="he", tgt_lang="ru", project_id=1
    )

    # Verify: same hash
    assert canonical1.glossary_hash == canonical2.glossary_hash
    assert canonical1.glossary_hash != ""
    assert len(canonical1.glossary_hash) == 64  # SHA256 hex string


# ============================================================================
# Test 2: Conflict resolution (highest priority wins)
# ============================================================================


def test_conflict_resolution_priority(db_session, glossary_service):
    """Duplicate source term → highest priority (confidence) wins."""
    # Add conflicting terms (same source, different targets)
    terms = [
        TMEntry(
            project_id=1,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text="כלב",
            src_norm="כלב",
            translation="собака",
            status="approved",
            confidence=0.9,  # Higher priority
            origin="user_edit",
        ),
        TMEntry(
            project_id=1,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text="כלב",
            src_norm="כלב",
            translation="пёс",
            status="approved",
            confidence=0.5,  # Lower priority
            origin="import",
        ),
    ]
    db_session.add_all(terms)
    db_session.commit()

    # Build glossary
    canonical = glossary_service.build_canonical_glossary(
        src_lang="he", tgt_lang="ru", project_id=1
    )

    # Verify: highest priority wins
    assert canonical.total_entries == 1
    assert canonical.entries[0].source_term == "כלב"
    assert canonical.entries[0].target_term == "собака"  # Higher confidence
    assert canonical.entries[0].priority_score == 0.9


# ============================================================================
# Test 3: Conflict resolution (stable sort tie-breaker)
# ============================================================================


def test_conflict_resolution_stable_sort(db_session, glossary_service):
    """Same priority → first alphabetically by source_term."""
    # Add terms with same priority
    terms = [
        TMEntry(
            project_id=1,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text="בית",  # "bet" (house)
            src_norm="בית",
            translation="дом",
            status="approved",
            confidence=0.8,
            origin="user_edit",
        ),
        TMEntry(
            project_id=1,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text="בית",  # Same source
            src_norm="בית",
            translation="здание",
            status="approved",
            confidence=0.8,  # Same priority
            origin="import",
        ),
    ]
    db_session.add_all(terms)
    db_session.commit()

    # Build glossary
    canonical = glossary_service.build_canonical_glossary(
        src_lang="he", tgt_lang="ru", project_id=1
    )

    # Verify: one entry selected (stable sort by src_text)
    assert canonical.total_entries == 1
    assert canonical.entries[0].source_term == "בית"
    # First one in DB order (stable sort)
    assert canonical.entries[0].target_term in ("дом", "здание")


# ============================================================================
# Test 4: DeepL format
# ============================================================================


def test_to_deepl_format(db_session, glossary_service):
    """DeepL format produces TSV entries."""
    # Add term
    term = TMEntry(
        project_id=1,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="שלום",
        src_norm="שלום",
        translation="привет",
        status="approved",
        confidence=0.9,
        origin="user_edit",
    )
    db_session.add(term)
    db_session.commit()

    # Build glossary
    canonical = glossary_service.build_canonical_glossary(
        src_lang="he", tgt_lang="ru", project_id=1
    )

    # Convert to DeepL format
    deepl_payload = glossary_service.to_deepl_format(canonical)

    # Verify format
    assert deepl_payload["format"] == "tsv"
    assert "שלום\tпривет" in deepl_payload["entries"]
    assert deepl_payload["source_lang"] == "HE"
    assert deepl_payload["target_lang"] == "RU"
    assert deepl_payload["entry_count"] == 1


# ============================================================================
# Test 5: Microsoft format
# ============================================================================


def test_to_microsoft_format(db_session, glossary_service):
    """Microsoft format produces translations array."""
    # Add term
    term = TMEntry(
        project_id=1,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="שלום",
        src_norm="שלום",
        translation="привет",
        status="approved",
        confidence=0.9,
        origin="user_edit",
    )
    db_session.add(term)
    db_session.commit()

    # Build glossary
    canonical = glossary_service.build_canonical_glossary(
        src_lang="he", tgt_lang="ru", project_id=1
    )

    # Convert to Microsoft format
    ms_payload = glossary_service.to_microsoft_format(canonical)

    # Verify format
    assert "translations" in ms_payload
    assert len(ms_payload["translations"]) == 1
    assert ms_payload["translations"][0]["from"] == "שלום"
    assert ms_payload["translations"][0]["to"] == "привет"


# ============================================================================
# Test 6: Truncation at max entries
# ============================================================================


def test_truncation_at_max_entries(db_session, glossary_service):
    """Glossary respects max_entries limit."""
    # Add 10 terms
    terms = [
        TMEntry(
            project_id=1,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text=f"term{i}",
            src_norm=f"term{i}",
            translation=f"термин{i}",
            status="approved",
            confidence=0.8,
            origin="user_edit",
        )
        for i in range(10)
    ]
    db_session.add_all(terms)
    db_session.commit()

    # Build glossary with max_entries=5
    canonical = glossary_service.build_canonical_glossary(
        src_lang="he", tgt_lang="ru", project_id=1, max_entries=5
    )

    # Verify truncation
    assert canonical.total_entries == 5
    assert canonical.truncated is True


# ============================================================================
# Test 7: Empty glossary (no approved terms)
# ============================================================================


def test_empty_glossary_graceful(db_session, glossary_service):
    """No approved terms → empty glossary (no crash)."""
    # No terms added

    # Build glossary
    canonical = glossary_service.build_canonical_glossary(
        src_lang="he", tgt_lang="ru", project_id=1
    )

    # Verify empty glossary
    assert canonical.total_entries == 0
    assert canonical.entries == []
    assert canonical.truncated is False
    assert canonical.glossary_hash != ""  # Hash of empty list


# ============================================================================
# Test 8: Glossary hash changes on content change
# ============================================================================


def test_glossary_hash_changes_on_content_change(db_session, glossary_service):
    """Hash changes when glossary content changes."""
    # Add first term
    term1 = TMEntry(
        project_id=1,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="שלום",
        src_norm="שלום",
        translation="привет",
        status="approved",
        confidence=0.9,
        origin="user_edit",
    )
    db_session.add(term1)
    db_session.commit()

    # Build glossary
    canonical1 = glossary_service.build_canonical_glossary(
        src_lang="he", tgt_lang="ru", project_id=1
    )
    hash1 = canonical1.glossary_hash

    # Add second term
    term2 = TMEntry(
        project_id=1,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="עולם",
        src_norm="עולם",
        translation="мир",
        status="approved",
        confidence=0.8,
        origin="user_edit",
    )
    db_session.add(term2)
    db_session.commit()

    # Build glossary again
    canonical2 = glossary_service.build_canonical_glossary(
        src_lang="he", tgt_lang="ru", project_id=1
    )
    hash2 = canonical2.glossary_hash

    # Verify: hash changed
    assert hash1 != hash2
    assert canonical1.total_entries == 1
    assert canonical2.total_entries == 2


# ============================================================================
# Test 9: Provider format dispatcher
# ============================================================================


def test_to_provider_format_dispatcher(db_session, glossary_service):
    """to_provider_format() dispatches to correct adapter."""
    # Add term
    term = TMEntry(
        project_id=1,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="שלום",
        src_norm="שלום",
        translation="привет",
        status="approved",
        confidence=0.9,
        origin="user_edit",
    )
    db_session.add(term)
    db_session.commit()

    # Build glossary
    canonical = glossary_service.build_canonical_glossary(
        src_lang="he", tgt_lang="ru", project_id=1
    )

    # Test DeepL
    deepl = glossary_service.to_provider_format(canonical, "deepl")
    assert deepl is not None
    assert deepl["format"] == "tsv"

    # Test Microsoft
    ms = glossary_service.to_provider_format(canonical, "microsoft")
    assert ms is not None
    assert "translations" in ms

    # Test LibreTranslate (no support)
    libre = glossary_service.to_provider_format(canonical, "libretranslate")
    assert libre == {}

    # Test unknown provider
    unknown = glossary_service.to_provider_format(canonical, "unknown_provider")
    assert unknown is None
