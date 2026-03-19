"""Test M4: Live Update - Delta Statistics."""

import io
import logging
import sys
from pathlib import Path

# Fix Unicode on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_delta_statistics():
    """Test delta statistics on document deletion."""
    from sqlalchemy import func, select

    from app.infra.sa_models import Lemma, LemmaProjectStat
    from app.services.db_service import DBService
    from app.services.ingest_service import IngestService
    from app.services.process_service import ProcessService
    from app.services.project_service import ProjectService

    print("\n" + "=" * 60)
    print("TEST 1: Delta Statistics on Delete")
    print("=" * 60)

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
    file1.write_text("בית ספר גדול. בית ספר קטן.", encoding="utf-8")

    file2 = test_dir / "doc2.txt"
    file2.write_text("בית ספר טוב. ילד טוב.", encoding="utf-8")

    try:
        with db_service.get_session() as session:
            # Create project
            project = project_service.create_project(session, "M4 Test", "Test M4 Delta")
            corpus = project_service.get_default_corpus(session, project.project_id)

            # Import documents
            doc1 = ingest_service.import_document(session, corpus.corpus_id, file1)
            doc2 = ingest_service.import_document(session, corpus.corpus_id, file2)

            print("✅ Imported 2 documents")

            # Process both documents
            process_service.process_document(session, doc1.doc_id, use_mock=True)
            process_service.process_document(session, doc2.doc_id, use_mock=True)

            print("✅ Processed 2 documents")

            # Check initial statistics
            lemma_count_before = session.execute(
                select(func.count())
                .select_from(Lemma)
                .where(Lemma.project_id == project.project_id)
            ).scalar()

            # Get frequency of "בית ספר" before deletion
            stmt = (
                select(Lemma, LemmaProjectStat)
                .join(LemmaProjectStat)
                .where(Lemma.project_id == project.project_id, Lemma.lemma_text == "בית")
            )
            result = session.execute(stmt).first()
            if result:
                lemma, stat = result
                freq_before = stat.freq_abs
                doc_freq_before = stat.doc_freq
                print("\n📊 Before deletion:")
                print(f"   Total lemmas: {lemma_count_before}")
                print(f"   'בית' frequency: {freq_before} (appears in {doc_freq_before} docs)")
            else:
                print("\n⚠️  Lemma 'בית' not found")
                freq_before = 0
                doc_freq_before = 0

            # Delete doc1
            print("\n🗑️  Deleting doc1...")
            success = ingest_service.delete_document(session, doc1.doc_id)

            if not success:
                print("❌ Failed to delete document")
                return False

            print("✅ Document deleted")

            # Check statistics after deletion
            lemma_count_after = session.execute(
                select(func.count())
                .select_from(Lemma)
                .where(Lemma.project_id == project.project_id)
            ).scalar()

            # Get frequency of "בית" after deletion
            stmt = (
                select(Lemma, LemmaProjectStat)
                .join(LemmaProjectStat)
                .where(Lemma.project_id == project.project_id, Lemma.lemma_text == "בית")
            )
            result = session.execute(stmt).first()
            if result:
                lemma, stat = result
                freq_after = stat.freq_abs
                doc_freq_after = stat.doc_freq
                print("\n📊 After deletion:")
                print(f"   Total lemmas: {lemma_count_after}")
                print(f"   'בית' frequency: {freq_after} (appears in {doc_freq_after} docs)")
            else:
                print("\n📊 After deletion:")
                print(f"   Total lemmas: {lemma_count_after}")
                print("   'בית' was removed (zero frequency)")
                freq_after = 0
                doc_freq_after = 0

            # Verify delta worked correctly
            # Doc1 had 2 occurrences of "בית", so freq should decrease by 2
            expected_freq = max(0, freq_before - 2)
            expected_doc_freq = max(0, doc_freq_before - 1)

            print("\n🔍 Verification:")
            print(f"   Expected 'בית' frequency: {expected_freq}")
            print(f"   Actual 'בית' frequency: {freq_after}")
            print(f"   Expected doc_freq: {expected_doc_freq}")
            print(f"   Actual doc_freq: {doc_freq_after}")

            if freq_after == expected_freq and doc_freq_after == expected_doc_freq:
                print("✅ Delta statistics PASSED!")
                return True
            else:
                print("❌ Delta statistics FAILED!")
                return False

    finally:
        # Cleanup
        import shutil
        import time

        if test_dir.exists():
            shutil.rmtree(test_dir)

        # Close database connections before deleting file
        DBService.shutdown()
        time.sleep(0.1)  # Small delay for Windows to release file handle

        # Try to delete database file
        if test_db_path.exists():
            try:
                test_db_path.unlink()
            except PermissionError:
                # On Windows, file might still be locked
                logger.warning(f"Could not delete {test_db_path} (file locked)")
                pass


def test_reprocessing():
    """Test document re-processing with delta update."""
    from sqlalchemy import select

    from app.infra.sa_models import Lemma, LemmaProjectStat, SourceDocument
    from app.services.db_service import DBService
    from app.services.ingest_service import IngestService
    from app.services.process_service import ProcessService
    from app.services.project_service import ProjectService

    print("\n" + "=" * 60)
    print("TEST 2: Document Re-processing")
    print("=" * 60)

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
    file1.write_text("בית ספר גדול.", encoding="utf-8")

    try:
        with db_service.get_session() as session:
            # Create project
            project = project_service.create_project(session, "M4 Test", "Test M4 Reprocess")
            corpus = project_service.get_default_corpus(session, project.project_id)

            # Import and process document
            doc1 = ingest_service.import_document(session, corpus.corpus_id, file1)
            process_service.process_document(session, doc1.doc_id, use_mock=True)

            print("✅ Processed document initially")

            # Get statistics before reprocessing
            stmt = (
                select(Lemma, LemmaProjectStat)
                .join(LemmaProjectStat)
                .where(Lemma.project_id == project.project_id, Lemma.lemma_text == "בית")
            )
            result = session.execute(stmt).first()
            if result:
                lemma, stat = result
                freq_before = stat.freq_abs
                print("\n📊 Before reprocessing:")
                print(f"   'בית' frequency: {freq_before}")
            else:
                print("\n⚠️  Lemma 'בית' not found before reprocessing")
                return False

            # Re-process document
            print("\n🔄 Re-processing document...")
            success = process_service.reprocess_document(session, doc1.doc_id, use_mock=True)

            if not success:
                print("❌ Failed to re-process document")
                return False

            print("✅ Document re-processed")

            # Check status
            doc_updated = session.get(SourceDocument, doc1.doc_id)
            print(f"   Status: {doc_updated.status}")

            # Get statistics after reprocessing
            stmt = (
                select(Lemma, LemmaProjectStat)
                .join(LemmaProjectStat)
                .where(Lemma.project_id == project.project_id, Lemma.lemma_text == "בית")
            )
            result = session.execute(stmt).first()
            if result:
                lemma, stat = result
                freq_after = stat.freq_abs
                print("\n📊 After reprocessing:")
                print(f"   'בית' frequency: {freq_after}")
            else:
                print("\n⚠️  Lemma 'בית' not found after reprocessing")
                return False

            # Verify frequency is the same (since text didn't change)
            if freq_after == freq_before and doc_updated.status == "processed":
                print("✅ Re-processing PASSED!")
                return True
            else:
                print("❌ Re-processing FAILED!")
                print(f"   Expected frequency: {freq_before}, got: {freq_after}")
                return False

    finally:
        # Cleanup
        import shutil
        import time

        if test_dir.exists():
            shutil.rmtree(test_dir)

        # Close database connections before deleting file
        DBService.shutdown()
        time.sleep(0.1)  # Small delay for Windows to release file handle

        # Try to delete database file
        if test_db_path.exists():
            try:
                test_db_path.unlink()
            except PermissionError:
                # On Windows, file might still be locked
                logger.warning(f"Could not delete {test_db_path} (file locked)")
                pass


def test_project_deletion():
    """Test complete project deletion."""
    from sqlalchemy import func, select

    from app.infra.sa_models import DictProject, Lemma, SourceDocument
    from app.services.db_service import DBService
    from app.services.ingest_service import IngestService
    from app.services.process_service import ProcessService
    from app.services.project_service import ProjectService

    print("\n" + "=" * 60)
    print("TEST 3: Project Deletion")
    print("=" * 60)

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
    file1.write_text("בית ספר גדול. בית ספר קטן.", encoding="utf-8")

    try:
        with db_service.get_session() as session:
            # Create project
            project = project_service.create_project(session, "Test Project", "Test deletion")
            corpus = project_service.get_default_corpus(session, project.project_id)

            # Import and process document
            doc1 = ingest_service.import_document(session, corpus.corpus_id, file1)
            process_service.process_document(session, doc1.doc_id, use_mock=True)

            print("✅ Created project with 1 processed document")

            # Count items before deletion
            docs_before = session.execute(select(func.count()).select_from(SourceDocument)).scalar()

            lemmas_before = session.execute(
                select(func.count())
                .select_from(Lemma)
                .where(Lemma.project_id == project.project_id)
            ).scalar()

            print("\n📊 Before deletion:")
            print(f"   Documents: {docs_before}")
            print(f"   Lemmas: {lemmas_before}")

            # Delete project
            print("\n🗑️  Deleting project...")
            report = project_service.delete_project(session, project.project_id)

            if not report.success:
                print(f"❌ Deletion failed: {report.error_message}")
                return False

            print("✅ Project deleted")
            print("\n📊 Deletion report:")
            print(f"   Corpora: {report.corpora_deleted}")
            print(f"   Documents: {report.documents_deleted}")
            print(f"   Sentences: {report.sentences_deleted}")
            print(f"   Lemmas: {report.lemmas_deleted}")

            # Verify project is gone
            project_exists = session.execute(
                select(func.count())
                .select_from(DictProject)
                .where(DictProject.project_id == project.project_id)
            ).scalar()

            # Verify documents are gone
            docs_after = session.execute(select(func.count()).select_from(SourceDocument)).scalar()

            # Verify lemmas are gone
            lemmas_after = session.execute(
                select(func.count())
                .select_from(Lemma)
                .where(Lemma.project_id == project.project_id)
            ).scalar()

            print("\n🔍 Verification:")
            print(f"   Project exists: {project_exists == 1}")
            print(f"   Documents remaining: {docs_after}")
            print(f"   Lemmas remaining: {lemmas_after}")

            # Create another project to ensure DB is still functional
            project2 = project_service.create_project(session, "Test Project 2", "Verify DB works")
            print("\n✅ Created new project after deletion (DB is healthy)")

            if project_exists == 0 and docs_after == 0 and lemmas_after == 0:
                print("✅ Project deletion PASSED!")
                return True
            else:
                print("❌ Project deletion FAILED!")
                print(f"   Project should not exist: {project_exists}")
                print(f"   Documents should be 0: {docs_after}")
                print(f"   Lemmas should be 0: {lemmas_after}")
                return False

    finally:
        # Cleanup
        import shutil
        import time

        if test_dir.exists():
            shutil.rmtree(test_dir)

        # Close database connections before deleting file
        DBService.shutdown()
        time.sleep(0.1)

        # Try to delete database file
        if test_db_path.exists():
            try:
                test_db_path.unlink()
            except PermissionError:
                logger.warning(f"Could not delete {test_db_path} (file locked)")
                pass


if __name__ == "__main__":
    print("=" * 60)
    print("M4 TEST SUITE: Live Update + Project Deletion")
    print("=" * 60)

    test1_pass = test_delta_statistics()
    test2_pass = test_reprocessing()
    test3_pass = test_project_deletion()

    print("\n" + "=" * 60)
    if test1_pass and test2_pass and test3_pass:
        print("✅ ALL M4 TESTS PASSED")
    else:
        print("❌ SOME M4 TESTS FAILED")
        if not test1_pass:
            print("   - Delta statistics: FAILED")
        if not test2_pass:
            print("   - Re-processing: FAILED")
        if not test3_pass:
            print("   - Project deletion: FAILED")
    print("=" * 60)

    sys.exit(0 if (test1_pass and test2_pass and test3_pass) else 1)
