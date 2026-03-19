"""E2E Test for Batch Translation V2 - PATCH-05.

This script creates Test_Translation project, processes documents,
and tests batch translation with the new BatchTranslateEngineV2.

Usage:
    python scripts/test_batch_translate_e2e_v2.py
"""

import logging
import sys
from pathlib import Path

# UTF-8 encoding for stdout
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.infra.sa_models import DictProject, Lemma, TermCluster
from app.services.project_service import ProjectService
from app.services.document_service import DocumentService
from app.services.processing_service import ProcessingService
from app.services.term_extraction_service import TermExtractionService
from app.services.batch_translate_engine_v2 import (
    BatchTranslateEngineV2,
    BatchTranslateItem,
    BatchTranslateOptions,
)
from app.infra.translators.local_providers_setup import initialize_local_providers


def main():
    """Run E2E test."""
    print("\n" + "=" * 80)
    print("BATCH TRANSLATE E2E TEST V2")
    print("=" * 80)

    # Database path
    db_path = Path(r"J:\Project_Vibe\V_book\hdle_premium.db")
    if not db_path.exists():
        print(f"\n[ERROR] Database not found: {db_path}")
        return 1

    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Step 1: Find or create Test_Translation project
        print("\n[STEP 1] Finding/creating Test_Translation project...")
        project_service = ProjectService()

        project = session.execute(
            select(DictProject).where(DictProject.name == "Test_Translation")
        ).scalar()

        if not project:
            print("  Creating new project...")
            project = project_service.create_project(
                session,
                name="Test_Translation",
                description="E2E test project for batch translation V2",
            )
            print(f"  ✓ Created project: {project.name} (ID: {project.project_id})")
        else:
            print(f"  ✓ Found existing project: {project.name} (ID: {project.project_id})")

        # Step 2: Import test document if needed
        print("\n[STEP 2] Checking documents...")
        doc_service = DocumentService()
        docs = doc_service.list_documents(session, project.project_id)

        if len(docs) == 0:
            print("  Importing test document...")
            test_file = Path(
                r"J:\Project_Vibe\V_book -info files\Тестовые тексты\Test_Translation.txt"
            )
            if not test_file.exists():
                print(f"  [ERROR] Test file not found: {test_file}")
                return 1

            doc_service.ingest_document(
                session, project_id=project.project_id, file_path=test_file, title="Test Document"
            )
            print("  ✓ Document imported")
        else:
            print(f"  ✓ Found {len(docs)} existing documents")

        # Step 3: Process documents
        print("\n[STEP 3] Processing documents...")
        processing_service = ProcessingService()

        unprocessed = [doc for doc in docs if doc.nlp_status != "completed"]
        if unprocessed or len(docs) == 0:
            print("  Running NLP processing...")
            # Get all docs again after import
            docs = doc_service.list_documents(session, project.project_id)
            for doc in docs:
                if doc.nlp_status != "completed":
                    processing_service.process_document(session, doc.doc_id)
                    print(f"  ✓ Processed: {doc.title}")
        else:
            print("  ✓ All documents already processed")

        # Step 4: Extract terms
        print("\n[STEP 4] Extracting terms...")
        term_service = TermExtractionService()
        clusters = (
            session.execute(select(TermCluster).where(TermCluster.project_id == project.project_id))
            .scalars()
            .all()
        )

        if len(clusters) == 0:
            print("  Running term extraction...")
            term_service.extract_project_terms(
                session,
                project_id=project.project_id,
                min_freq=1,
                enable_ngrams=True,
                ngram_ns=(2, 3),
                include_np=True,
                np_max_len=5,
            )
            print("  ✓ Terms extracted")

            # Refresh
            clusters = (
                session.execute(
                    select(TermCluster).where(TermCluster.project_id == project.project_id)
                )
                .scalars()
                .all()
            )
        else:
            print(f"  ✓ Found {len(clusters)} existing term clusters")

        # Step 5: Initialize providers
        print("\n[STEP 5] Initializing MT providers...")
        try:
            count = initialize_local_providers(db_session=session, project_id=project.project_id)
            print(f"  ✓ Registered {count} local providers")
        except Exception as e:
            print(f"  [WARNING] Provider init failed: {e}")
            print("  Continuing with lazy initialization...")

        # Step 6: Test Dictionary batch translate
        print("\n[STEP 6] Testing Dictionary batch translate...")
        lemmas = (
            session.execute(select(Lemma).where(Lemma.project_id == project.project_id))
            .scalars()
            .all()
        )

        print(f"  Found {len(lemmas)} lemmas")

        if len(lemmas) > 0:
            # Take first 5 lemmas
            test_lemmas = lemmas[: min(5, len(lemmas))]
            items = [
                BatchTranslateItem(
                    entity_type="lemma",
                    entity_id=lemma.lemma_text,
                    source_text=lemma.lemma_text,
                    src_lang="he",
                    tgt_lang="ru",
                    current_translation=None,
                    project_id=project.project_id,
                )
                for lemma in test_lemmas
            ]

            options = BatchTranslateOptions(
                provider_mode="chain",
                write_mode="fill_empty",
            )

            engine = BatchTranslateEngineV2()

            print(f"  Translating {len(items)} lemmas...")
            result = engine.execute(session, items, options)

            print(f"  ✓ Dictionary batch translate complete:")
            print(f"    Total: {result.total}")
            print(f"    Succeeded: {result.succeeded}")
            print(f"    Failed: {result.failed}")
            print(f"    Skipped: {result.skipped}")
            print(f"    Elapsed: {result.elapsed_ms}ms")

            if result.failed > 0:
                print(f"\n  Failed rows:")
                for row in result.row_results:
                    if row.error_message:
                        print(f"    - {row.entity_id}: {row.error_message}")

        # Step 7: Test Terms batch translate
        print("\n[STEP 7] Testing Terms batch translate...")

        if len(clusters) > 0:
            # Take first 5 clusters
            test_clusters = clusters[: min(5, len(clusters))]
            items = [
                BatchTranslateItem(
                    entity_type="term_cluster",
                    entity_id=cluster.representative_he,
                    source_text=cluster.representative_he,
                    src_lang="he",
                    tgt_lang="ru",
                    current_translation=cluster.pinned_translation,
                    project_id=project.project_id,
                )
                for cluster in test_clusters
            ]

            options = BatchTranslateOptions(
                provider_mode="chain",
                write_mode="fill_empty",
            )

            engine = BatchTranslateEngineV2()

            print(f"  Translating {len(items)} term clusters...")
            result = engine.execute(session, items, options)

            print(f"  ✓ Terms batch translate complete:")
            print(f"    Total: {result.total}")
            print(f"    Succeeded: {result.succeeded}")
            print(f"    Failed: {result.failed}")
            print(f"    Skipped: {result.skipped}")
            print(f"    Elapsed: {result.elapsed_ms}ms")

            if result.failed > 0:
                print(f"\n  Failed rows:")
                for row in result.row_results:
                    if row.error_message:
                        print(f"    - {row.entity_id}: {row.error_message}")

        # Final summary
        print("\n" + "=" * 80)
        print("E2E TEST COMPLETE")
        print("=" * 80)
        print("\nNext steps:")
        print(
            "1. Launch app: python -m app.main --db-path J:\\Project_Vibe\\V_book\\hdle_premium.db"
        )
        print("2. Open Test_Translation project")
        print("3. Verify translations appear in Dictionary and Terms tabs")
        print("\n")

        return 0

    except Exception as e:
        logger.exception("E2E test failed")
        print(f"\n[ERROR] Test failed: {e}")
        return 1

    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
