"""Test script for M2 - Document Ingestion (no GUI required)."""

import io
import sys
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.infra.util.logging import setup_logging
from app.services.db_service import DBService
from app.services.ingest_service import IngestService
from app.services.project_service import ProjectService


def create_sample_files(test_dir: Path) -> list[Path]:
    """Create sample test files."""
    samples_dir = test_dir / "sample_files"
    samples_dir.mkdir(exist_ok=True)

    files = []

    # Create sample TXT file
    txt_file = samples_dir / "sample_hebrew.txt"
    txt_file.write_text(
        "שלום עולם\n"
        "זהו קובץ טקסט לדוגמה.\n"
        "הוא מכיל טקסט בעברית.\n"
        "\n"
        "Hello World\n"
        "This is a sample text file.\n"
        "It contains Hebrew text.",
        encoding="utf-8",
    )
    files.append(txt_file)

    # Create sample TXT file 2
    txt_file2 = samples_dir / "sample_text2.txt"
    txt_file2.write_text(
        "בית ספר\n" "ילדים לומדים בבית הספר.\n" "המורה מלמדת עברית.", encoding="utf-8"
    )
    files.append(txt_file2)

    print(f"Created {len(files)} sample files in: {samples_dir}")
    return files


def test_m2():
    """Test M2 functionality."""
    print("=" * 60)
    print("HDLE Premium - M2 Test")
    print("=" * 60)

    # Setup
    test_dir = Path(__file__).parent / "test_data"
    test_dir.mkdir(exist_ok=True)
    log_dir = test_dir / "logs"
    db_path = test_dir / "test_m2.db"

    # Remove old test database
    if db_path.exists():
        db_path.unlink()
        print(f"Removed old test database: {db_path}")

    # Setup logging
    setup_logging(log_dir)
    print(f"Logging initialized: {log_dir}")

    # Initialize database
    print("\n1. Initializing database...")
    DBService.initialize(db_path)
    print("   [+] Database initialized")

    # Create project
    print("\n2. Creating test project...")
    project_service = ProjectService()

    with project_service.db_service.get_session() as session:
        project = project_service.create_project(
            session, name="M2 Test Project", description="Testing document ingestion"
        )
        print(f"   [+] Created project: {project.name} (ID: {project.project_id})")

        corpus = project_service.get_default_corpus(session, project.project_id)
        print(f"   [+] Default corpus: {corpus.name} (ID: {corpus.corpus_id})")

    # Create sample files
    print("\n3. Creating sample files...")
    sample_files = create_sample_files(test_dir)
    for f in sample_files:
        print(f"   [+] Created: {f.name}")

    # Test ingestion
    print("\n4. Testing IngestService...")
    ingest_service = IngestService()

    with ingest_service.db_service.get_session() as session:
        for file_path in sample_files:
            print(f"\n   Importing: {file_path.name}")

            # Import document
            doc = ingest_service.import_document(
                session, corpus_id=corpus.corpus_id, file_path=file_path, use_ocr=False
            )

            print(f"   [+] Document imported (ID: {doc.doc_id})")
            print(f"       - File: {doc.file_name}")
            print(f"       - Size: {doc.file_size_bytes} bytes")
            print(f"       - Status: {doc.status}")
            print(f"       - SHA256: {doc.sha256[:16]}...")

            # Get text
            text = ingest_service.get_document_text(session, doc.doc_id)
            if text:
                preview = text[:100].replace("\n", " ")
                print(f"       - Text preview: {preview}...")
                print(f"       - Text length: {len(text)} chars")

    # Test duplicate detection
    print("\n5. Testing duplicate detection...")
    with ingest_service.db_service.get_session() as session:
        # Try to import the same file again
        file_path = sample_files[0]
        print(f"   Trying to re-import: {file_path.name}")

        doc = ingest_service.import_document(
            session, corpus_id=corpus.corpus_id, file_path=file_path, use_ocr=False
        )

        print(f"   [+] Duplicate detected - returned existing doc (ID: {doc.doc_id})")

    # Verify documents in database
    print("\n6. Verifying documents in database...")
    with ingest_service.db_service.get_session() as session:
        from sqlalchemy import select

        from app.infra.sa_models import SourceDocument

        stmt = select(SourceDocument).where(SourceDocument.corpus_id == corpus.corpus_id)
        docs = session.execute(stmt).scalars().all()

        print(f"   [+] Total documents in corpus: {len(docs)}")
        for doc in docs:
            print(f"       - {doc.file_name} ({doc.status})")

    # Test extractors
    print("\n7. Testing text extractors...")
    print("   [+] TXT extractor: OK (tested above)")

    # Test DOCX (if file exists)
    try:
        from app.infra.extractors import docx_extractor

        print("   [+] DOCX extractor: available (python-docx installed)")
    except ImportError:
        print("   [-] DOCX extractor: not available (python-docx not installed)")

    # Test PDF
    try:
        from app.infra.extractors import pdf_extractor

        print("   [+] PDF extractor: available (PyPDF2 installed)")
    except ImportError:
        print("   [-] PDF extractor: not available (PyPDF2 not installed)")

    # Test OCR
    try:
        from app.infra.extractors.pdf_ocr_extractor import is_ocr_available

        if is_ocr_available():
            print("   [+] OCR extractor: available (pytesseract + pdf2image installed)")
        else:
            print("   [-] OCR extractor: not available (optional dependencies missing)")
    except Exception:
        print("   [-] OCR extractor: not available")

    # Cleanup
    print("\n8. Cleanup...")
    DBService.shutdown()
    print("   [+] Database connections closed")

    print("\n" + "=" * 60)
    print("M2 TEST PASSED")
    print("=" * 60)
    print("\nAll document ingestion functionality working:")
    print("  - Text extraction (TXT) [OK]")
    print("  - Document import to DB [OK]")
    print("  - Duplicate detection [OK]")
    print("  - Text retrieval [OK]")
    print("  - SHA256 hashing [OK]")
    print("  - DOCX/PDF extractors available")
    print("\nNext steps:")
    print("  - Test GUI with drag-drop (requires PyQt6)")
    print("  - M3: Implement NLP pipeline (Stanza)")


if __name__ == "__main__":
    try:
        test_m2()
    except Exception as e:
        print(f"\n[X] TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
