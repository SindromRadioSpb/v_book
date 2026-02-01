"""Test M4: Live Update - Delta Statistics."""
import sys
import io
import logging
from pathlib import Path

# Fix Unicode on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_delta_statistics():
    """Test delta statistics on document deletion."""
    from app.services.db_service import DBService
    from app.services.project_service import ProjectService
    from app.services.ingest_service import IngestService
    from app.services.process_service import ProcessService
    from pathlib import Path
    from sqlalchemy import select, func
    from app.infra.sa_models import Lemma, LemmaProjectStat, SourceDocument

    print("\n" + "="*60)
    print("TEST 1: Delta Statistics on Delete")
    print("="*60)

    # Initialize
    test_db_path = Path("test_m4.db")
    if test_db_path.exists():
        test_db_path.unlink()

    DBService.initialize(test_db_path)
    db_service = DBService.get_instance()
    project_service = ProjectService()
    ingest_service = IngestService()
    process_service = ProcessService()

    # Create test files
    test_dir = Path("test_data_m4")
    test_dir.mkdir(exist_ok=True)

    file1 = test_dir / "doc1.txt"
    file1.write_text("בית ספר גדול. בית ספר קטן.", encoding='utf-8')

    file2 = test_dir / "doc2.txt"
    file2.write_text("בית ספר טוב. ילד טוב.", encoding='utf-8')

    try:
        with db_service.get_session() as session:
            # Create project
            project = project_service.create_project(session, "M4 Test", "Test M4 Delta")
            corpus = project_service.get_default_corpus(session, project.project_id)

            # Import documents
            doc1 = ingest_service.import_document(session, corpus.corpus_id, file1)
            doc2 = ingest_service.import_document(session, corpus.corpus_id, file2)

            print(f"✅ Imported 2 documents")

            # Process both documents
            process_service.process_document(session, doc1.doc_id, use_mock=True)
            process_service.process_document(session, doc2.doc_id, use_mock=True)

            print(f"✅ Processed 2 documents")

            # Check initial statistics
            lemma_count_before = session.execute(
                select(func.count()).select_from(Lemma).where(Lemma.project_id == project.project_id)
            ).scalar()

            # Get frequency of "בית ספר" before deletion
            stmt = select(Lemma, LemmaProjectStat).join(LemmaProjectStat).where(
                Lemma.project_id == project.project_id,
                Lemma.lemma_text == "בית"
            )
            result = session.execute(stmt).first()
            if result:
                lemma, stat = result
                freq_before = stat.freq_abs
                doc_freq_before = stat.doc_freq
                print(f"\n📊 Before deletion:")
                print(f"   Total lemmas: {lemma_count_before}")
                print(f"   'בית' frequency: {freq_before} (appears in {doc_freq_before} docs)")
            else:
                print(f"\n⚠️  Lemma 'בית' not found")
                freq_before = 0
                doc_freq_before = 0

            # Delete doc1
            print(f"\n🗑️  Deleting doc1...")
            success = ingest_service.delete_document(session, doc1.doc_id)

            if not success:
                print("❌ Failed to delete document")
                return False

            print(f"✅ Document deleted")

            # Check statistics after deletion
            lemma_count_after = session.execute(
                select(func.count()).select_from(Lemma).where(Lemma.project_id == project.project_id)
            ).scalar()

            # Get frequency of "בית" after deletion
            stmt = select(Lemma, LemmaProjectStat).join(LemmaProjectStat).where(
                Lemma.project_id == project.project_id,
                Lemma.lemma_text == "בית"
            )
            result = session.execute(stmt).first()
            if result:
                lemma, stat = result
                freq_after = stat.freq_abs
                doc_freq_after = stat.doc_freq
                print(f"\n📊 After deletion:")
                print(f"   Total lemmas: {lemma_count_after}")
                print(f"   'בית' frequency: {freq_after} (appears in {doc_freq_after} docs)")
            else:
                print(f"\n📊 After deletion:")
                print(f"   Total lemmas: {lemma_count_after}")
                print(f"   'בית' was removed (zero frequency)")
                freq_after = 0
                doc_freq_after = 0

            # Verify delta worked correctly
            # Doc1 had 2 occurrences of "בית", so freq should decrease by 2
            expected_freq = max(0, freq_before - 2)
            expected_doc_freq = max(0, doc_freq_before - 1)

            print(f"\n🔍 Verification:")
            print(f"   Expected 'בית' frequency: {expected_freq}")
            print(f"   Actual 'בית' frequency: {freq_after}")
            print(f"   Expected doc_freq: {expected_doc_freq}")
            print(f"   Actual doc_freq: {doc_freq_after}")

            if freq_after == expected_freq and doc_freq_after == expected_doc_freq:
                print(f"✅ Delta statistics PASSED!")
                return True
            else:
                print(f"❌ Delta statistics FAILED!")
                return False

    finally:
        # Cleanup
        import shutil
        if test_dir.exists():
            shutil.rmtree(test_dir)
        if test_db_path.exists():
            DBService._instance = None
            test_db_path.unlink()


def test_reprocessing():
    """Test document re-processing with delta update."""
    from app.services.db_service import DBService
    from app.services.project_service import ProjectService
    from app.services.ingest_service import IngestService
    from app.services.process_service import ProcessService
    from pathlib import Path
    from sqlalchemy import select
    from app.infra.sa_models import Lemma, LemmaProjectStat, SourceDocument

    print("\n" + "="*60)
    print("TEST 2: Document Re-processing")
    print("="*60)

    # Initialize
    test_db_path = Path("test_m4.db")
    if test_db_path.exists():
        test_db_path.unlink()

    DBService.initialize(test_db_path)
    db_service = DBService.get_instance()
    project_service = ProjectService()
    ingest_service = IngestService()
    process_service = ProcessService()

    # Create test file
    test_dir = Path("test_data_m4")
    test_dir.mkdir(exist_ok=True)

    file1 = test_dir / "doc1.txt"
    file1.write_text("בית ספר גדול.", encoding='utf-8')

    try:
        with db_service.get_session() as session:
            # Create project
            project = project_service.create_project(session, "M4 Test", "Test M4 Reprocess")
            corpus = project_service.get_default_corpus(session, project.project_id)

            # Import and process document
            doc1 = ingest_service.import_document(session, corpus.corpus_id, file1)
            process_service.process_document(session, doc1.doc_id, use_mock=True)

            print(f"✅ Processed document initially")

            # Get statistics before reprocessing
            stmt = select(Lemma, LemmaProjectStat).join(LemmaProjectStat).where(
                Lemma.project_id == project.project_id,
                Lemma.lemma_text == "בית"
            )
            result = session.execute(stmt).first()
            if result:
                lemma, stat = result
                freq_before = stat.freq_abs
                print(f"\n📊 Before reprocessing:")
                print(f"   'בית' frequency: {freq_before}")
            else:
                print(f"\n⚠️  Lemma 'בית' not found before reprocessing")
                return False

            # Re-process document
            print(f"\n🔄 Re-processing document...")
            success = process_service.reprocess_document(session, doc1.doc_id, use_mock=True)

            if not success:
                print("❌ Failed to re-process document")
                return False

            print(f"✅ Document re-processed")

            # Check status
            doc_updated = session.get(SourceDocument, doc1.doc_id)
            print(f"   Status: {doc_updated.status}")

            # Get statistics after reprocessing
            stmt = select(Lemma, LemmaProjectStat).join(LemmaProjectStat).where(
                Lemma.project_id == project.project_id,
                Lemma.lemma_text == "בית"
            )
            result = session.execute(stmt).first()
            if result:
                lemma, stat = result
                freq_after = stat.freq_abs
                print(f"\n📊 After reprocessing:")
                print(f"   'בית' frequency: {freq_after}")
            else:
                print(f"\n⚠️  Lemma 'בית' not found after reprocessing")
                return False

            # Verify frequency is the same (since text didn't change)
            if freq_after == freq_before and doc_updated.status == 'processed':
                print(f"✅ Re-processing PASSED!")
                return True
            else:
                print(f"❌ Re-processing FAILED!")
                print(f"   Expected frequency: {freq_before}, got: {freq_after}")
                return False

    finally:
        # Cleanup
        import shutil
        if test_dir.exists():
            shutil.rmtree(test_dir)
        if test_db_path.exists():
            DBService._instance = None
            test_db_path.unlink()


if __name__ == "__main__":
    print("="*60)
    print("M4 TEST SUITE: Live Update")
    print("="*60)

    test1_pass = test_delta_statistics()
    test2_pass = test_reprocessing()

    print("\n" + "="*60)
    if test1_pass and test2_pass:
        print("✅ ALL M4 TESTS PASSED")
    else:
        print("❌ SOME M4 TESTS FAILED")
        if not test1_pass:
            print("   - Delta statistics: FAILED")
        if not test2_pass:
            print("   - Re-processing: FAILED")
    print("="*60)

    sys.exit(0 if (test1_pass and test2_pass) else 1)
