"""
Test suite for Task 13: DB-level trigger synchronization for is_noise

Tests verify that SQLite triggers (migration 014) automatically sync is_noise
from source entities (lemma/term_cluster) to linked tm_entry records.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def test_db():
    """Create a temporary test database with schema v14."""
    # Create temporary DB
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Minimal schema for testing triggers
    cursor.executescript(
        """
        -- Schema metadata
        CREATE TABLE schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        INSERT INTO schema_meta (key, value) VALUES ('schema_version', '14');

        -- Projects
        CREATE TABLE dict_project (
            project_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL
        );
        INSERT INTO dict_project (project_id, title) VALUES (1, 'Test Project');

        -- Lemmas
        CREATE TABLE lemma (
            lemma_id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            lemma_text TEXT NOT NULL,
            norm_text TEXT,
            is_noise INTEGER DEFAULT 0,
            noise_reason TEXT
        );

        -- Term clusters
        CREATE TABLE term_cluster (
            cluster_id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            representative_he TEXT NOT NULL,
            norm_text TEXT,
            is_noise INTEGER DEFAULT 0,
            noise_reason TEXT
        );

        -- TM entries
        CREATE TABLE tm_entry (
            tm_id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            src_text TEXT NOT NULL,
            src_norm TEXT NOT NULL,
            translation TEXT NOT NULL,
            is_noise INTEGER DEFAULT 0,
            noise_reason TEXT,
            lemma_id INTEGER,
            cluster_id INTEGER
        );

        -- Triggers (migration 014)
        CREATE TRIGGER trg_lemma_noise_to_tm_entry
        AFTER UPDATE OF is_noise, noise_reason ON lemma
        WHEN (NEW.is_noise IS NOT OLD.is_noise) OR (NEW.noise_reason IS NOT OLD.noise_reason)
        BEGIN
          UPDATE tm_entry
          SET is_noise = COALESCE(NEW.is_noise, 0),
              noise_reason = NEW.noise_reason
          WHERE tm_entry.lemma_id = NEW.lemma_id;
        END;

        CREATE TRIGGER trg_cluster_noise_to_tm_entry
        AFTER UPDATE OF is_noise, noise_reason ON term_cluster
        WHEN (NEW.is_noise IS NOT OLD.is_noise) OR (NEW.noise_reason IS NOT OLD.noise_reason)
        BEGIN
          UPDATE tm_entry
          SET is_noise = COALESCE(NEW.is_noise, 0),
              noise_reason = NEW.noise_reason
          WHERE tm_entry.cluster_id = NEW.cluster_id;
        END;
    """
    )

    conn.commit()

    yield conn

    # Cleanup
    conn.close()
    db_path.unlink()


def test_trigger_lemma_to_tm_valid_to_noise(test_db):
    """Test trigger: lemma.is_noise (Valid->Noise) syncs to linked tm_entry."""
    cursor = test_db.cursor()

    # Create lemma (Valid)
    cursor.execute(
        """
        INSERT INTO lemma (lemma_id, project_id, lemma_text, norm_text, is_noise)
        VALUES (1, 1, 'תתקש', 'תתקש', 0)
    """
    )

    # Create linked tm_entry (Valid)
    cursor.execute(
        """
        INSERT INTO tm_entry (tm_id, project_id, kind, src_text, src_norm, translation, lemma_id, is_noise)
        VALUES (1, 1, 'lemma', 'תתקש', 'תתקש', 'test translation', 1, 0)
    """
    )
    test_db.commit()

    # Verify initial state
    cursor.execute("SELECT is_noise FROM lemma WHERE lemma_id = 1")
    assert cursor.fetchone()[0] == 0, "Lemma should be Valid (0)"

    cursor.execute("SELECT is_noise FROM tm_entry WHERE tm_id = 1")
    assert cursor.fetchone()[0] == 0, "TMEntry should be Valid (0)"

    # UPDATE lemma to Noise
    cursor.execute(
        """
        UPDATE lemma
        SET is_noise = 1, noise_reason = 'NOISE_TEST'
        WHERE lemma_id = 1
    """
    )
    test_db.commit()

    # Verify trigger synced to tm_entry
    cursor.execute("SELECT is_noise, noise_reason FROM lemma WHERE lemma_id = 1")
    lemma_row = cursor.fetchone()
    assert lemma_row[0] == 1, "Lemma should be Noise (1)"
    assert lemma_row[1] == "NOISE_TEST", "Lemma noise_reason should be set"

    cursor.execute("SELECT is_noise, noise_reason FROM tm_entry WHERE tm_id = 1")
    tm_row = cursor.fetchone()
    assert tm_row[0] == 1, "TMEntry should be Noise (1) - SYNCED BY TRIGGER"
    assert tm_row[1] == "NOISE_TEST", "TMEntry noise_reason should be synced"


def test_trigger_lemma_to_tm_noise_to_valid(test_db):
    """Test trigger: lemma.is_noise (Noise->Valid) syncs to linked tm_entry."""
    cursor = test_db.cursor()

    # Create lemma (Noise)
    cursor.execute(
        """
        INSERT INTO lemma (lemma_id, project_id, lemma_text, norm_text, is_noise, noise_reason)
        VALUES (2, 1, 'מבחן', 'מבחן', 1, 'NOISE_PUNCT_ONLY')
    """
    )

    # Create linked tm_entry (Noise)
    cursor.execute(
        """
        INSERT INTO tm_entry (tm_id, project_id, kind, src_text, src_norm, translation, lemma_id, is_noise, noise_reason)
        VALUES (2, 1, 'lemma', 'מבחן', 'מבחן', 'test', 2, 1, 'NOISE_PUNCT_ONLY')
    """
    )
    test_db.commit()

    # Verify initial state
    cursor.execute("SELECT is_noise FROM lemma WHERE lemma_id = 2")
    assert cursor.fetchone()[0] == 1, "Lemma should be Noise (1)"

    cursor.execute("SELECT is_noise FROM tm_entry WHERE tm_id = 2")
    assert cursor.fetchone()[0] == 1, "TMEntry should be Noise (1)"

    # UPDATE lemma to Valid
    cursor.execute(
        """
        UPDATE lemma
        SET is_noise = 0, noise_reason = NULL
        WHERE lemma_id = 2
    """
    )
    test_db.commit()

    # Verify trigger synced to tm_entry
    cursor.execute("SELECT is_noise, noise_reason FROM lemma WHERE lemma_id = 2")
    lemma_row = cursor.fetchone()
    assert lemma_row[0] == 0, "Lemma should be Valid (0)"
    assert lemma_row[1] is None, "Lemma noise_reason should be cleared"

    cursor.execute("SELECT is_noise, noise_reason FROM tm_entry WHERE tm_id = 2")
    tm_row = cursor.fetchone()
    assert tm_row[0] == 0, "TMEntry should be Valid (0) - SYNCED BY TRIGGER"
    assert tm_row[1] is None, "TMEntry noise_reason should be cleared"


def test_trigger_cluster_to_tm_valid_to_noise(test_db):
    """Test trigger: term_cluster.is_noise (Valid->Noise) syncs to linked tm_entry."""
    cursor = test_db.cursor()

    # Create term_cluster (Valid)
    cursor.execute(
        """
        INSERT INTO term_cluster (cluster_id, project_id, representative_he, norm_text, is_noise)
        VALUES (1, 1, 'תשובה ג', 'תשובה_ג', 0)
    """
    )

    # Create linked tm_entry (Valid)
    cursor.execute(
        """
        INSERT INTO tm_entry (tm_id, project_id, kind, src_text, src_norm, translation, cluster_id, is_noise)
        VALUES (3, 1, 'term_cluster', 'תשובה ג', 'תשובה_ג', 'answer c', 1, 0)
    """
    )
    test_db.commit()

    # UPDATE term_cluster to Noise
    cursor.execute(
        """
        UPDATE term_cluster
        SET is_noise = 1, noise_reason = 'NOISE_TEST'
        WHERE cluster_id = 1
    """
    )
    test_db.commit()

    # Verify trigger synced to tm_entry
    cursor.execute("SELECT is_noise, noise_reason FROM term_cluster WHERE cluster_id = 1")
    cluster_row = cursor.fetchone()
    assert cluster_row[0] == 1, "Cluster should be Noise (1)"
    assert cluster_row[1] == "NOISE_TEST", "Cluster noise_reason should be set"

    cursor.execute("SELECT is_noise, noise_reason FROM tm_entry WHERE tm_id = 3")
    tm_row = cursor.fetchone()
    assert tm_row[0] == 1, "TMEntry should be Noise (1) - SYNCED BY TRIGGER"
    assert tm_row[1] == "NOISE_TEST", "TMEntry noise_reason should be synced"


def test_trigger_cluster_to_tm_noise_to_valid(test_db):
    """Test trigger: term_cluster.is_noise (Noise->Valid) syncs to linked tm_entry."""
    cursor = test_db.cursor()

    # Create term_cluster (Noise)
    cursor.execute(
        """
        INSERT INTO term_cluster (cluster_id, project_id, representative_he, norm_text, is_noise, noise_reason)
        VALUES (2, 1, 'מבחן טכני', 'מבחן_טכני', 1, 'NOISE_NUMBER_ONLY')
    """
    )

    # Create linked tm_entry (Noise)
    cursor.execute(
        """
        INSERT INTO tm_entry (tm_id, project_id, kind, src_text, src_norm, translation, cluster_id, is_noise, noise_reason)
        VALUES (4, 1, 'term_cluster', 'מבחן טכני', 'מבחן_טכני', 'technical test', 2, 1, 'NOISE_NUMBER_ONLY')
    """
    )
    test_db.commit()

    # UPDATE term_cluster to Valid
    cursor.execute(
        """
        UPDATE term_cluster
        SET is_noise = 0, noise_reason = NULL
        WHERE cluster_id = 2
    """
    )
    test_db.commit()

    # Verify trigger synced to tm_entry
    cursor.execute("SELECT is_noise, noise_reason FROM term_cluster WHERE cluster_id = 2")
    cluster_row = cursor.fetchone()
    assert cluster_row[0] == 0, "Cluster should be Valid (0)"
    assert cluster_row[1] is None, "Cluster noise_reason should be cleared"

    cursor.execute("SELECT is_noise, noise_reason FROM tm_entry WHERE tm_id = 4")
    tm_row = cursor.fetchone()
    assert tm_row[0] == 0, "TMEntry should be Valid (0) - SYNCED BY TRIGGER"
    assert tm_row[1] is None, "TMEntry noise_reason should be cleared"


def test_trigger_no_unlinked_side_effects(test_db):
    """Test trigger: unlinked tm_entry (lemma_id=NULL) is NOT affected by trigger."""
    cursor = test_db.cursor()

    # Create lemma
    cursor.execute(
        """
        INSERT INTO lemma (lemma_id, project_id, lemma_text, norm_text, is_noise)
        VALUES (3, 1, 'בדיקה', 'בדיקה', 0)
    """
    )

    # Create UNLINKED tm_entry (lemma_id=NULL)
    cursor.execute(
        """
        INSERT INTO tm_entry (tm_id, project_id, kind, src_text, src_norm, translation, lemma_id, is_noise)
        VALUES (5, 1, 'lemma', 'אחר', 'אחר', 'other', NULL, 0)
    """
    )
    test_db.commit()

    # UPDATE lemma to Noise
    cursor.execute(
        """
        UPDATE lemma
        SET is_noise = 1, noise_reason = 'NOISE_TEST'
        WHERE lemma_id = 3
    """
    )
    test_db.commit()

    # Verify unlinked tm_entry was NOT affected
    cursor.execute("SELECT is_noise FROM tm_entry WHERE tm_id = 5")
    assert (
        cursor.fetchone()[0] == 0
    ), "Unlinked TMEntry should remain Valid (0) - NOT affected by trigger"


def test_trigger_multiple_tm_entries_per_source(test_db):
    """Test trigger: multiple tm_entry records linked to same lemma all get synced."""
    cursor = test_db.cursor()

    # Create lemma (Valid)
    cursor.execute(
        """
        INSERT INTO lemma (lemma_id, project_id, lemma_text, norm_text, is_noise)
        VALUES (4, 1, 'מרובה', 'מרובה', 0)
    """
    )

    # Create 3 linked tm_entry records (all Valid)
    for i in range(6, 9):
        cursor.execute(
            f"""
            INSERT INTO tm_entry (tm_id, project_id, kind, src_text, src_norm, translation, lemma_id, is_noise)
            VALUES ({i}, 1, 'lemma', 'מרובה', 'מרובה', 'translation {i}', 4, 0)
        """
        )
    test_db.commit()

    # UPDATE lemma to Noise
    cursor.execute(
        """
        UPDATE lemma
        SET is_noise = 1, noise_reason = 'NOISE_TEST'
        WHERE lemma_id = 4
    """
    )
    test_db.commit()

    # Verify ALL 3 tm_entry records were synced
    cursor.execute("SELECT COUNT(*) FROM tm_entry WHERE lemma_id = 4 AND is_noise = 1")
    assert cursor.fetchone()[0] == 3, "All 3 linked TMEntry records should be synced to Noise (1)"

    cursor.execute(
        "SELECT COUNT(*) FROM tm_entry WHERE lemma_id = 4 AND noise_reason = 'NOISE_TEST'"
    )
    assert cursor.fetchone()[0] == 3, "All 3 linked TMEntry records should have synced noise_reason"


def test_schema_version_14(test_db):
    """Test: schema_version is set to 14 after migration."""
    cursor = test_db.cursor()

    cursor.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'")
    version = cursor.fetchone()[0]

    assert version == "14", "Schema version should be 14 after migration 014"


if __name__ == "__main__":
    # Run tests with verbose output
    pytest.main([__file__, "-v"])
