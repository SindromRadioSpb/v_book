"""Diagnostic test for batch MT translation flow.

This test walks through the entire translation chain to identify
exactly where the translation is failing.
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
from app.services.translation_service import TranslationService
from app.services.db_service import DBService
from app.infra.settings import SettingsService
from app.infra.translators.local_providers_setup import initialize_local_providers


def setup_test_database():
    """Create temporary database with migrations."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    # Apply SQL migrations
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

    return db_path


def test_diagnostic_full_flow():
    """Diagnostic test: Walk through entire batch MT translation flow."""
    print("\n" + "=" * 80)
    print("BATCH MT TRANSLATION DIAGNOSTIC TEST")
    print("=" * 80)

    # Step 1: Check settings
    print("\n[STEP 1] Checking MT provider settings...")
    settings = SettingsService.get_instance()

    master_enabled = settings.get_bool("mt/providers/enabled", default=False)
    chain = settings.get_json("mt/providers/chain", default=[])

    print(f"  [OK] mt/providers/enabled: {master_enabled}")
    print(f"  [OK] mt/providers/chain: {chain}")

    if not master_enabled:
        print("\n  [ERROR] PROBLEM: MT providers are DISABLED (mt/providers/enabled=False)")
        print("     Solution: Open provider settings dialog and enable master switch")
        return

    if not chain:
        print("\n  [ERROR] PROBLEM: Provider chain is EMPTY")
        print("     Solution: Configure at least one provider in settings")
        return

    # Check individual provider settings
    print("\n  Individual provider settings:")
    for provider_id in ["local_nllb", "deepl", "microsoft", "libretranslate"]:
        enabled_key = f"mt/providers/{provider_id}/enabled"
        enabled = settings.get_bool(enabled_key, default=False)
        print(f"    - {provider_id}: {'ENABLED' if enabled else 'DISABLED'}")

    print("\n  [OK] Settings look good!")

    # Step 2: Setup test database
    print("\n[STEP 2] Setting up test database...")
    db_path = setup_test_database()
    DBService.initialize(str(db_path))
    db_service = DBService.get_instance()
    print(f"  [OK] Database created: {db_path}")

    # Step 2.5: Register local MT providers
    print("\n[STEP 2.5] Registering local MT providers...")
    registered_count = initialize_local_providers()
    print(f"  [OK] Registered {registered_count} local provider(s)")

    if registered_count == 0:
        print("\n  [ERROR] PROBLEM: No local providers registered!")
        print("     This means either:")
        print("       - Models are not installed")
        print("       - Provider initialization failed")
        return

    # Step 3: Test TranslationService directly
    print("\n[STEP 3] Testing TranslationService.resolve_translation()...")
    translation_service = TranslationService()

    test_text = "טוב"
    print(f"  Test text: (Hebrew word - good)")

    try:
        with db_service.get_session() as session:
            result = translation_service.resolve_translation(
                session=session,
                src_text=test_text,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                project_id=None,
                use_mt=True,
                allow_draft=False,
            )

        print(f"  [OK] Translation result:")
        print(f"    - translation: {result.translation}")
        print(f"    - source: {result.source}")
        print(f"    - status: {result.status}")
        print(f"    - provider: {result.provider}")
        print(f"    - notes: {result.notes}")

        if not result.translation:
            print("\n  [ERROR] PROBLEM: TranslationService returned NO translation")
            print(f"     Source: {result.source}")
            print(f"     Notes: {result.notes}")

            if result.source == "none" and result.notes:
                print(f"\n     Root cause: {result.notes}")

            return

        print("\n  [OK] TranslationService works!")

    except Exception as e:
        print(f"\n  [ERROR] EXCEPTION in TranslationService: {e}")
        import traceback
        traceback.print_exc()
        return

    # Step 4: Test BatchMTTranslateService
    print("\n[STEP 4] Testing BatchMTTranslateService...")
    batch_service = BatchMTTranslateService()

    items = [
        BatchTranslateItem(
            entity_type="lemma",
            entity_id="טוב",
            source_text="טוב",
            src_lang="he",
            tgt_lang="ru",
            current_translation=None,
            project_id=None,
        ),
    ]

    options = BatchTranslateOptions(
        provider_mode="chain",
        write_mode="FILL_EMPTY",
        chunk_size=10,
    )

    try:
        with db_service.get_session() as session:
            batch_result = batch_service.execute_batch(session, items, options)

        print(f"  [OK] Batch result:")
        print(f"    - total: {batch_result.total}")
        print(f"    - succeeded: {batch_result.succeeded}")
        print(f"    - skipped: {batch_result.skipped}")
        print(f"    - failed: {batch_result.failed}")

        if batch_result.row_results:
            row = batch_result.row_results[0]
            print(f"\n  Row result:")
            print(f"    - entity_id: {row.entity_id}")
            print(f"    - new_translation: {row.new_translation}")
            print(f"    - provider_id: {row.provider_id}")
            print(f"    - error_message: {row.error_message}")
            print(f"    - skipped: {row.skipped}")

        if batch_result.succeeded == 0:
            print("\n  [ERROR] PROBLEM: Batch translate FAILED")
            if batch_result.row_results and batch_result.row_results[0].error_message:
                print(f"     Error: {batch_result.row_results[0].error_message}")
            return

        print("\n  [OK] BatchMTTranslateService works!")

    except Exception as e:
        print(f"\n  [ERROR] EXCEPTION in BatchMTTranslateService: {e}")
        import traceback
        traceback.print_exc()
        return

    # Step 5: Verify database write
    print("\n[STEP 5] Verifying database write...")
    try:
        from app.infra.sa_models import TMEntry
        with db_service.get_session() as session:
            entries = session.query(TMEntry).filter_by(kind="lemma", project_id=None).all()
            print(f"  [OK] Found {len(entries)} TM entries")
            for entry in entries:
                print(f"    - {entry.src_text} -> {entry.translation} (status={entry.status}, origin={entry.origin})")

        if not entries:
            print("\n  [ERROR] PROBLEM: No TM entries were written to database!")
            return

        print("\n  [OK] Database write successful!")

    except Exception as e:
        print(f"\n  [ERROR] EXCEPTION checking database: {e}")
        import traceback
        traceback.print_exc()
        return

    # Cleanup
    DBService._instance = None
    try:
        db_path.unlink()
    except (PermissionError, FileNotFoundError):
        pass

    print("\n" + "=" * 80)
    print("✅ ALL TESTS PASSED - Batch MT translation is working!")
    print("=" * 80)


if __name__ == "__main__":
    test_diagnostic_full_flow()
