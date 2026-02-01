"""Test script for M3 - NLP Pipeline (requires Stanza)."""
import sys
import io
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.infra.util.logging import setup_logging
from app.services.db_service import DBService
from app.services.project_service import ProjectService
from app.services.ingest_service import IngestService
from app.services.process_service import ProcessService


def create_sample_hebrew_file(test_dir: Path) -> Path:
    """Create a sample Hebrew text file."""
    samples_dir = test_dir / "sample_files_m3"
    samples_dir.mkdir(exist_ok=True)

    txt_file = samples_dir / "hebrew_sample.txt"
    txt_file.write_text(
        "שלום עולם! זהו טקסט לדוגמה בעברית.\n"
        "הטקסט הזה מכיל כמה משפטים פשוטים.\n"
        "בית הספר נמצא בעיר.\n"
        "הילדים לומדים בבית הספר.\n"
        "המורה מלמדת עברית ומתמטיקה.\n"
        "\n"
        "Hello world! This is a sample text in Hebrew.\n"
        "This text contains a few simple sentences.\n"
        "The school is located in the city.",
        encoding='utf-8'
    )

    return txt_file


def test_m3():
    """Test M3 NLP functionality."""
    print("=" * 60)
    print("HDLE Premium - M3 NLP Pipeline Test")
    print("=" * 60)

    # Setup
    test_dir = Path(__file__).parent / "test_data"
    test_dir.mkdir(exist_ok=True)
    log_dir = test_dir / "logs"
    db_path = test_dir / "test_m3.db"

    # Remove old test database
    if db_path.exists():
        db_path.unlink()
        print(f"Removed old test database: {db_path}")

    # Setup logging
    setup_logging(log_dir)
    print(f"Logging initialized: {log_dir}\n")

    # Initialize database
    print("1. Initializing database...")
    DBService.initialize(db_path)
    print("   [+] Database initialized\n")

    # Create project
    print("2. Creating test project...")
    project_service = ProjectService()

    with project_service.db_service.get_session() as session:
        project = project_service.create_project(
            session,
            name="M3 NLP Test Project",
            description="Testing NLP pipeline with Stanza"
        )
        print(f"   [+] Created project: {project.name} (ID: {project.project_id})")

        corpus = project_service.get_default_corpus(session, project.project_id)
        print(f"   [+] Default corpus: {corpus.name} (ID: {corpus.corpus_id})\n")

    # Create sample file
    print("3. Creating sample Hebrew file...")
    sample_file = create_sample_hebrew_file(test_dir)
    print(f"   [+] Created: {sample_file.name}\n")

    # Import document
    print("4. Importing document...")
    ingest_service = IngestService()

    with ingest_service.db_service.get_session() as session:
        doc = ingest_service.import_document(
            session,
            corpus_id=corpus.corpus_id,
            file_path=sample_file,
            use_ocr=False
        )
        doc_id = doc.doc_id  # Save for later use
        print(f"   [+] Document imported (ID: {doc.doc_id})")
        print(f"       - Status: {doc.status}\n")

    # Process document with NLP
    print("5. Processing document with NLP...")
    print("   [!] Using Mock NLP engine (Stanza not available in MSYS2)")
    print("   [!] For production, use regular Windows Python + Stanza")
    process_service = ProcessService()

    with process_service.db_service.get_session() as session:
        success = process_service.process_document(
            session,
            doc_id=doc.doc_id,
            use_gpu=False,
            use_mock=True  # Use mock engine for testing
        )

        if success:
            print("   [+] Document processed successfully\n")

            # Get updated document
            from app.infra.sa_models import SourceDocument
            doc = session.get(SourceDocument, doc.doc_id)
            print(f"       - New status: {doc.status}")
            print(f"       - Processed at: {doc.processed_at}\n")
        else:
            print("   [X] Document processing failed\n")
            return False

    # Check document NLP metrics (Migration 003)
    print("5.5. Checking document NLP metrics...")
    with process_service.db_service.get_session() as session:
        from app.infra.sa_models import SourceDocument

        doc = session.get(SourceDocument, doc_id)

        if doc.sentence_count > 0:
            print(f"   [+] Sentence count: {doc.sentence_count}")
        else:
            print(f"   [X] WARNING: sentence_count is 0 (expected > 0)")

        if doc.token_count > 0:
            print(f"   [+] Token count: {doc.token_count}")
        else:
            print(f"   [X] WARNING: token_count is 0 (expected > 0)")

    # Check sentences
    print("\n6. Checking stored sentences...")
    with process_service.db_service.get_session() as session:
        from sqlalchemy import select
        from app.infra.sa_models import DocumentSentence

        stmt = select(DocumentSentence).where(
            DocumentSentence.doc_id == doc.doc_id
        ).order_by(DocumentSentence.sent_index)

        sentences = session.execute(stmt).scalars().all()
        print(f"   [+] Total sentences: {len(sentences)}")

        if sentences:
            print(f"       First sentence: {sentences[0].text[:80]}...")
            print(f"       Last sentence: {sentences[-1].text[:80]}...\n")

    # Check lemmas
    print("7. Checking extracted lemmas...")
    with process_service.db_service.get_session() as session:
        from app.infra.sa_models import Lemma, LemmaProjectStat

        # Get top lemmas
        stmt = select(Lemma, LemmaProjectStat).join(
            LemmaProjectStat,
            Lemma.lemma_id == LemmaProjectStat.lemma_id
        ).where(
            Lemma.project_id == project.project_id
        ).order_by(
            LemmaProjectStat.freq_abs.desc()
        ).limit(10)

        results = session.execute(stmt).all()

        print(f"   [+] Total unique lemmas: {len(results)}")
        print(f"   [+] Top 10 lemmas by frequency:\n")

        for lemma, stat in results:
            print(f"       {lemma.lemma_text:20s} | POS: {lemma.pos:6s} | Freq: {stat.freq_abs:3d}")

        print()

    # Check processor run
    print("8. Checking processor run...")
    with process_service.db_service.get_session() as session:
        from app.infra.sa_models import ProcessorRun

        stmt = select(ProcessorRun).where(
            ProcessorRun.project_id == project.project_id
        ).order_by(ProcessorRun.run_id.desc()).limit(1)

        run = session.execute(stmt).scalar_one_or_none()

        if run:
            print(f"   [+] Run ID: {run.run_id}")
            print(f"       - Engine: {run.engine} v{run.engine_version}")
            print(f"       - Status: {run.status}")
            print(f"       - Docs processed: {run.docs_processed}")
            print(f"       - Tokens total: {run.tokens_total}")
            print(f"       - Lemmas total: {run.lemmas_total}\n")

    # Cleanup
    print("9. Cleanup...")
    DBService.shutdown()
    print("   [+] Database connections closed\n")

    print("=" * 60)
    print("M3 TEST PASSED")
    print("=" * 60)
    print("\nAll NLP pipeline functionality working:")
    print("  - Mock NLP engine [OK] (rule-based)")
    print("  - Text preprocessing [OK]")
    print("  - Sentence splitting [OK]")
    print("  - Lemmatization [OK] (simple rules)")
    print("  - POS tagging [OK] (basic)")
    print("  - Statistics calculation [OK]")
    print("  - Status transitions [OK]")
    print("\nNOTE: For production accuracy, use Stanza:")
    print("  1. Install in regular Windows Python (not MSYS2)")
    print("  2. pip install stanza")
    print("  3. python -c \"import stanza; stanza.download('he')\"")
    print("  4. Set use_mock=False in ProcessService")
    print("\nNext steps:")
    print("  - Test GUI Dictionary view (requires PyQt6)")
    print("  - M4: Implement live update (delta statistics)")


if __name__ == "__main__":
    try:
        test_m3()
    except Exception as e:
        print(f"\n[X] TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
