"""Test batch translate on real project.

This script tests batch translate functionality programmatically to diagnose issues.
"""

import logging
import sys
from pathlib import Path

# Set UTF-8 encoding for stdout to handle Hebrew text
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Setup logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.infra.sa_models import Base, DictProject, TermCluster
from app.services.batch_mt_translate_service import (
    BatchMTTranslateService,
    BatchTranslateItem,
    BatchTranslateOptions,
)
from app.infra.translators.local_providers_setup import initialize_local_providers


def test_batch_translate():
    """Test batch translate on 'Тест_Перевод' project."""
    print("\n" + "=" * 80)
    print("BATCH TRANSLATE LIVE TEST")
    print("=" * 80)

    # Step 1: Connect to database
    print("\n[STEP 1] Connecting to database...")
    db_path = Path(r"J:\Project_Vibe\V_book\hdle_premium.db")
    if not db_path.exists():
        print(f"  [ERROR] Database not found: {db_path}")
        return

    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()

    # Step 2: Find project
    print("\n[STEP 2] Finding project 'Тест_Перевод'...")
    project = session.query(DictProject).filter(DictProject.name == "Тест_Перевод").first()

    if not project:
        print("  [ERROR] Project 'Тест_Перевод' not found!")
        print("\n  Available projects:")
        for p in session.query(DictProject).all():
            print(f"    - {p.name} (ID: {p.project_id})")
        return

    print(f"  [OK] Found project: {project.name} (ID: {project.project_id})")

    # Step 3: Get term clusters without translation
    print("\n[STEP 3] Finding term clusters without Russian translation...")
    clusters = (
        session.query(TermCluster)
        .filter(
            TermCluster.project_id == project.project_id,
            (TermCluster.pinned_translation == None) | (TermCluster.pinned_translation == ""),
        )
        .limit(5)
        .all()
    )  # Limit to 5 for testing

    if not clusters:
        print("  [INFO] No term clusters without translation found")
        # Try to get ANY clusters
        clusters = (
            session.query(TermCluster)
            .filter(TermCluster.project_id == project.project_id)
            .limit(5)
            .all()
        )

    print(f"  [OK] Found {len(clusters)} term clusters")
    for cluster in clusters:
        print(f"    - '{cluster.representative_he}' → '{cluster.pinned_translation or '(empty)'}'")

    if not clusters:
        print("  [ERROR] No term clusters in project!")
        return

    # Step 4: Initialize local providers
    print("\n[STEP 4] Initializing local MT providers...")
    try:
        registered_count = initialize_local_providers(
            db_session=session, project_id=project.project_id
        )
        print(f"  [OK] Registered {registered_count} local providers")
    except Exception as e:
        print(f"  [WARNING] Failed to initialize providers: {e}")
        print("  Continuing anyway - will use lazy initialization")

    # Step 5: Prepare batch translate items
    print("\n[STEP 5] Preparing batch translate items...")
    items = []
    for cluster in clusters:
        item = BatchTranslateItem(
            entity_type="term_cluster",
            entity_id=cluster.representative_he,
            source_text=cluster.representative_he,
            src_lang="he",
            tgt_lang="ru",
            current_translation=cluster.pinned_translation,
            project_id=project.project_id,
        )
        items.append(item)

    print(f"  [OK] Prepared {len(items)} items for translation")

    # Step 6: Create batch translate service
    print("\n[STEP 6] Creating batch translate service...")
    service = BatchMTTranslateService()
    print("  [OK] Service created")

    # Step 7: Execute batch translate
    print("\n[STEP 7] Executing batch translate...")
    print("  This will test worker startup and translation...")

    options = BatchTranslateOptions(
        provider_mode="chain",  # Use provider chain
        write_mode="FILL_EMPTY",
    )

    try:
        # Use progress callback to see what's happening
        def progress_callback(current, total):
            print(f"  Progress: {current}/{total}")

        result = service.execute_batch(
            session=session,
            items=items,
            options=options,
            progress_callback=progress_callback,
        )

        print(f"\n[STEP 8] Batch translate completed!")
        print(f"  Total: {result.total}")
        print(f"  Succeeded: {result.succeeded}")
        print(f"  Failed: {result.failed}")
        print(f"  Skipped: {result.skipped}")
        print(f"  Elapsed: {result.elapsed_ms}ms")

        if result.failed > 0:
            print(f"\n  Failed rows:")
            for row_result in result.row_results:
                if row_result.error_message:
                    print(f"    - {row_result.entity_id}: {row_result.error_message}")

        # Step 9: Verify database writes
        print("\n[STEP 9] Verifying database writes...")
        session.refresh(clusters[0])
        print(f"  First cluster translation: '{clusters[0].pinned_translation or '(empty)'}'")

        print("\n" + "=" * 80)
        print("SUCCESS: Batch translate test completed!")
        print("=" * 80)

    except Exception as e:
        print(f"\n  [ERROR] Batch translate failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    test_batch_translate()
