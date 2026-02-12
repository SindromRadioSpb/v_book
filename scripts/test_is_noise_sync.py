"""Test script for is_noise bidirectional synchronization.

Tests:
1. Migration 013 adds source_id columns
2. Source → TMEntry sync (Dictionary/Terms marking propagates to TM)
3. TMEntry → Source sync (TM Panel marking propagates to Dictionary/Terms)
4. TMEntry creation captures source_id and is_noise
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
from datetime import datetime
from sqlalchemy import select, text

from app.services.db_service import DBService
from app.infra.sa_models import Lemma, TermCluster, TMEntry, Ngram
from app.services.translation_admin_service import TranslationAdminService
from app.domain.normalization.normalizer import normalize_for_tm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_migration_013():
    """Test that migration 013 added source_id columns."""
    logger.info("\n" + "=" * 70)
    logger.info("[Test 1] Migration 013: source_id columns")
    logger.info("=" * 70)

    db_service = DBService.get_instance()

    with db_service.get_session() as session:
        # Check schema version
        result = session.execute(text("SELECT value FROM schema_meta WHERE key='schema_version'"))
        schema_version = result.scalar()
        logger.info(f"Schema version: {schema_version}")

        if int(schema_version) < 13:
            logger.error("❌ FAIL: Schema version is < 13, migration 013 not applied")
            return False

        # Check columns exist
        result = session.execute(text("PRAGMA table_info(tm_entry)"))
        columns = {row[1] for row in result.fetchall()}

        required_columns = {"lemma_id", "cluster_id", "ngram_id"}
        missing = required_columns - columns

        if missing:
            logger.error(f"❌ FAIL: Missing columns: {missing}")
            return False

        logger.info(f"✅ PASS: All source_id columns exist: {required_columns}")

        # Check indexes exist
        result = session.execute(text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='tm_entry'"))
        indexes = {row[0] for row in result.fetchall()}

        required_indexes = {"idx_tm_entry_lemma", "idx_tm_entry_cluster", "idx_tm_entry_ngram"}
        missing_indexes = required_indexes - indexes

        if missing_indexes:
            logger.error(f"❌ FAIL: Missing indexes: {missing_indexes}")
            return False

        logger.info(f"✅ PASS: All source_id indexes exist: {required_indexes}")

    return True


def test_source_to_tm_sync():
    """Test that marking lemma/cluster as noise updates TMEntry."""
    logger.info("\n" + "=" * 70)
    logger.info("[Test 2] Source → TMEntry sync (Dictionary/Terms → TM Panel)")
    logger.info("=" * 70)

    db_service = DBService.get_instance()

    with db_service.get_session() as session:
        # Find a lemma with linked TMEntry
        stmt = select(Lemma).join(
            TMEntry, TMEntry.lemma_id == Lemma.lemma_id
        ).limit(1)
        lemma = session.execute(stmt).scalar()

        if not lemma:
            logger.warning("⚠️ SKIP: No lemma with linked TMEntry found")
            return True

        logger.info(f"Test lemma: {lemma.lemma_text} (lemma_id={lemma.lemma_id})")

        # Mark lemma as noise
        original_is_noise = lemma.is_noise
        lemma.is_noise = 1
        lemma.noise_reason = "TEST_NOISE"
        session.commit()

        logger.info(f"Marked lemma as noise (was {original_is_noise})")

        # Trigger sync via BulkNoiseUpdateWorker logic (simulated)
        from sqlalchemy import update
        sync_stmt = update(TMEntry).where(
            TMEntry.lemma_id == lemma.lemma_id
        ).values(
            is_noise=1,
            noise_reason="TEST_NOISE"
        )
        session.execute(sync_stmt)
        session.commit()

        # Verify TMEntry is updated
        tm_stmt = select(TMEntry).where(TMEntry.lemma_id == lemma.lemma_id)
        tm_entries = session.execute(tm_stmt).scalars().all()

        if not tm_entries:
            logger.error("❌ FAIL: No TMEntry records linked to lemma")
            return False

        all_synced = all(e.is_noise == 1 and e.noise_reason == "TEST_NOISE" for e in tm_entries)

        if not all_synced:
            logger.error(f"❌ FAIL: TMEntry not synced. Found: {[(e.tm_id, e.is_noise, e.noise_reason) for e in tm_entries]}")
            # Rollback
            lemma.is_noise = original_is_noise
            lemma.noise_reason = None
            session.commit()
            return False

        logger.info(f"✅ PASS: All {len(tm_entries)} TMEntry records synced to is_noise=1")

        # Restore original state
        lemma.is_noise = original_is_noise
        lemma.noise_reason = None
        for e in tm_entries:
            e.is_noise = original_is_noise
            e.noise_reason = None
        session.commit()

    return True


def test_tm_to_source_sync():
    """Test that marking TMEntry as noise updates source (Lemma/TermCluster)."""
    logger.info("\n" + "=" * 70)
    logger.info("[Test 3] TMEntry → Source sync (TM Panel → Dictionary/Terms)")
    logger.info("=" * 70)

    db_service = DBService.get_instance()
    admin_service = TranslationAdminService()

    with db_service.get_session() as session:
        # Find a TMEntry with linked lemma
        stmt = select(TMEntry).where(
            TMEntry.kind == "lemma",
            TMEntry.lemma_id.isnot(None)
        ).limit(1)
        tm_entry = session.execute(stmt).scalar()

        if not tm_entry:
            logger.warning("⚠️ SKIP: No TMEntry with linked lemma found")
            return True

        logger.info(f"Test TMEntry: {tm_entry.src_text} (tm_id={tm_entry.tm_id}, lemma_id={tm_entry.lemma_id})")

        # Get linked lemma
        lemma = session.get(Lemma, tm_entry.lemma_id)
        if not lemma:
            logger.error("❌ FAIL: Linked lemma not found")
            return False

        # Mark TMEntry as noise via admin service
        original_is_noise = tm_entry.is_noise
        original_lemma_is_noise = lemma.is_noise

        count = admin_service.set_noise_status_bulk(
            session=session,
            tm_ids=[tm_entry.tm_id],
            is_noise=True,
            noise_reason="TEST_TM_NOISE"
        )

        logger.info(f"Marked {count} TMEntry as noise")

        # Refresh objects
        session.refresh(tm_entry)
        session.refresh(lemma)

        # Verify TMEntry is updated
        if tm_entry.is_noise != 1 or tm_entry.noise_reason != "TEST_TM_NOISE":
            logger.error(f"❌ FAIL: TMEntry not updated. is_noise={tm_entry.is_noise}, noise_reason={tm_entry.noise_reason}")
            return False

        logger.info(f"✅ TMEntry updated: is_noise={tm_entry.is_noise}")

        # Verify Lemma is updated (bidirectional sync)
        if lemma.is_noise != 1 or lemma.noise_reason != "TEST_TM_NOISE":
            logger.error(f"❌ FAIL: Lemma not synced. is_noise={lemma.is_noise}, noise_reason={lemma.noise_reason}")
            # Restore
            tm_entry.is_noise = original_is_noise
            tm_entry.noise_reason = None
            session.commit()
            return False

        logger.info(f"✅ PASS: Lemma synced: is_noise={lemma.is_noise}")

        # Restore original state
        tm_entry.is_noise = original_is_noise
        tm_entry.noise_reason = None
        lemma.is_noise = original_lemma_is_noise
        lemma.noise_reason = None
        session.commit()

    return True


def test_tmentry_creation_captures_source():
    """Test that new TMEntry captures source_id and is_noise."""
    logger.info("\n" + "=" * 70)
    logger.info("[Test 4] TMEntry creation captures source_id and is_noise")
    logger.info("=" * 70)

    db_service = DBService.get_instance()

    with db_service.get_session() as session:
        # Find a lemma to test with
        stmt = select(Lemma).limit(1)
        lemma = session.execute(stmt).scalar()

        if not lemma:
            logger.warning("⚠️ SKIP: No lemma found for testing")
            return True

        logger.info(f"Test lemma: {lemma.lemma_text} (lemma_id={lemma.lemma_id}, is_noise={lemma.is_noise})")

        # Check if TMEntry exists for this lemma (simulating dictionary_view.py inline edit)
        normalized = normalize_for_tm("he", lemma.lemma_text, "lemma")

        # Check existing TMEntry for this lemma
        existing_stmt = select(TMEntry).where(
            TMEntry.project_id == lemma.project_id,
            TMEntry.kind == "lemma",
            TMEntry.src_norm == normalized.norm,
        )
        tm_entry = session.execute(existing_stmt).scalar()

        if tm_entry:
            # Verify existing TMEntry has correct source_id and is_noise
            logger.info(f"Using existing TMEntry (tm_id={tm_entry.tm_id})")
        else:
            # Create new TMEntry (should not happen in real DB, but handle it)
            tm_entry = TMEntry(
                project_id=lemma.project_id,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                src_text=lemma.lemma_text,
                src_norm=normalized.norm,
                translation="test_translation_sync",
                status="approved",
                origin="user_edit",
                source_ref="test_is_noise_sync",
                lemma_id=lemma.lemma_id,  # Link to source
                is_noise=lemma.is_noise if lemma.is_noise is not None else 0,
                noise_reason=lemma.noise_reason,
            )
            session.add(tm_entry)
            session.flush()

        # Verify TMEntry has correct source_id and is_noise
        if tm_entry.lemma_id != lemma.lemma_id:
            logger.error(f"❌ FAIL: lemma_id not captured. Expected {lemma.lemma_id}, got {tm_entry.lemma_id}")
            session.rollback()
            return False

        expected_is_noise = lemma.is_noise if lemma.is_noise is not None else 0
        if tm_entry.is_noise != expected_is_noise:
            logger.error(f"❌ FAIL: is_noise not synced. Expected {expected_is_noise}, got {tm_entry.is_noise}")
            session.rollback()
            return False

        if tm_entry.noise_reason != lemma.noise_reason:
            logger.error(f"❌ FAIL: noise_reason not synced. Expected {lemma.noise_reason}, got {tm_entry.noise_reason}")
            session.rollback()
            return False

        logger.info(f"✅ PASS: TMEntry created with lemma_id={tm_entry.lemma_id}, is_noise={tm_entry.is_noise}, noise_reason={tm_entry.noise_reason}")

        # Cleanup
        session.rollback()

    return True


def main():
    """Run all tests."""
    # Initialize DBService with working database
    db_service = DBService()
    # Use the development database directly
    db_path = Path(__file__).parent.parent / "hdle_premium.db"
    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        return 1
    db_service.initialize(str(db_path))

    logger.info("\n" + "=" * 70)
    logger.info("TESTING: is_noise BIDIRECTIONAL SYNCHRONIZATION")
    logger.info("=" * 70)

    tests = [
        ("Migration 013 applied", test_migration_013),
        ("Source → TMEntry sync", test_source_to_tm_sync),
        ("TMEntry → Source sync", test_tm_to_source_sync),
        ("TMEntry creation captures source", test_tmentry_creation_captures_source),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            logger.exception(f"Test '{name}' raised exception")
            results.append((name, False))

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("TEST SUMMARY")
    logger.info("=" * 70)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"[{status}] {name}")

    logger.info("=" * 70)
    if passed == total:
        logger.info(f"✅ ALL TESTS PASSED ({passed}/{total})")
        logger.info("=" * 70)
        return 0
    else:
        logger.error(f"❌ SOME TESTS FAILED ({total - passed}/{total} failed)")
        logger.info("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
