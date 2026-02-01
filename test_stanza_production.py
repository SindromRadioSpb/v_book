"""Test Stanza engine in production environment."""
import sys
import io
import logging

# Fix Unicode on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_stanza_import():
    """Test if Stanza can be imported."""
    try:
        import stanza
        import torch
        print("✅ Stanza imported successfully")
        print(f"   Stanza version: {stanza.__version__}")
        print(f"   PyTorch version: {torch.__version__}")
        print(f"   CUDA available: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            print(f"   CUDA device: {torch.cuda.get_device_name(0)}")
        return True
    except ImportError as e:
        print(f"❌ Failed to import Stanza: {e}")
        return False

def test_stanza_engine():
    """Test StanzaEngine class."""
    try:
        from app.infra.nlp_engines.stanza_engine import StanzaEngine
        import torch

        print("\n" + "="*60)
        print("Testing StanzaEngine")
        print("="*60)

        use_gpu = torch.cuda.is_available()
        print(f"\nInitializing StanzaEngine (GPU: {use_gpu})...")

        engine = StanzaEngine(use_gpu=use_gpu)
        print("✅ StanzaEngine initialized")

        # Test Hebrew text
        test_text = "זה טקסט בעברית. יש כאן שתי משפטים."

        print(f"\nProcessing text: {test_text}")
        result = engine.process(test_text)

        print(f"\n✅ Processed successfully")
        print(f"   Sentences: {len(result)}")
        print(f"   Total tokens: {sum(len(s.tokens) for s in result)}")

        print("\n📊 Results:")
        for i, sent in enumerate(result, 1):
            print(f"\n  Sentence {i}: {sent.text}")
            for tok in sent.tokens[:5]:  # Show first 5 tokens
                print(f"    {tok.text:10s} → lemma={tok.lemma:10s} pos={tok.pos}")

        return True

    except Exception as e:
        logger.exception("Failed to test StanzaEngine")
        print(f"❌ StanzaEngine test failed: {e}")
        return False

def test_process_service_with_stanza():
    """Test ProcessService with real Stanza engine."""
    test_dir = None
    try:
        from app.services.db_service import DBService
        from app.services.project_service import ProjectService
        from app.services.ingest_service import IngestService
        from app.services.process_service import ProcessService
        from pathlib import Path

        print("\n" + "="*60)
        print("Testing ProcessService with Stanza")
        print("="*60)

        # Initialize DBService with test database
        test_db_path = Path("test_stanza.db")
        if test_db_path.exists():
            test_db_path.unlink()

        DBService.initialize(test_db_path)
        db_service = DBService.get_instance()
        project_service = ProjectService()
        ingest_service = IngestService()
        process_service = ProcessService()

        # Create test file
        test_dir = Path("test_data_stanza")
        test_dir.mkdir(exist_ok=True)

        test_file = test_dir / "test_hebrew.txt"
        test_file.write_text(
            "זהו מסמך בדיקה בעברית. "
            "הוא מכיל מספר משפטים. "
            "נבדוק את הלמטיזציה ותיוג חלקי הדיבור. "
            "בית ספר, בתי ספר, ביה\"ס - כל אלה צריכים להפוך ל'בית ספר'.",
            encoding='utf-8'
        )

        with db_service.get_session() as session:
            # Create project
            project = project_service.create_project(
                session,
                "Stanza Test",
                "Test project for Stanza engine"
            )
            print(f"✅ Created project: {project.name} (ID: {project.project_id})")

            # Get corpus
            corpus = project_service.get_default_corpus(session, project.project_id)
            print(f"✅ Got corpus: {corpus.name} (ID: {corpus.corpus_id})")

            # Import document
            doc = ingest_service.import_document(
                session,
                corpus.corpus_id,
                test_file,
                use_ocr=False
            )
            print(f"✅ Imported document: {doc.file_name} (ID: {doc.doc_id})")

            # Process with Stanza (use_mock=False)
            print(f"\n🔄 Processing with Stanza engine...")
            success = process_service.process_document(
                session,
                doc.doc_id,
                use_gpu=False,  # Set True if you want to use GPU
                use_mock=False  # Use real Stanza
            )

            if success:
                print(f"✅ Document processed successfully")

                # Get document stats
                from app.infra.sa_models import SourceDocument, Lemma, LemmaProjectStat, DocumentSentence
                from sqlalchemy import select, func

                doc_updated = session.get(SourceDocument, doc.doc_id)
                print(f"\n📊 Document status: {doc_updated.status}")

                # Count sentences
                sentence_count = session.execute(
                    select(func.count()).select_from(DocumentSentence).where(
                        DocumentSentence.doc_id == doc.doc_id
                    )
                ).scalar()
                print(f"   Sentences: {sentence_count}")

                # Count lemmas for this project
                lemma_count = session.execute(
                    select(func.count()).select_from(Lemma).where(
                        Lemma.project_id == project.project_id
                    )
                ).scalar()
                print(f"   Unique lemmas: {lemma_count}")

                # Get top lemmas
                stmt = select(Lemma, LemmaProjectStat).join(
                    LemmaProjectStat
                ).where(
                    Lemma.project_id == project.project_id
                ).order_by(
                    LemmaProjectStat.freq_abs.desc()
                ).limit(10)

                results = session.execute(stmt).all()

                print(f"\n📚 Top 10 lemmas:")
                for lemma, stat in results:
                    print(f"   {lemma.lemma_text:15s} | {lemma.pos:6s} | Freq: {stat.freq_abs:3d} | DocFreq: {stat.doc_freq}")

                # Get processor run info
                from app.infra.sa_models import ProcessorRun
                run = session.execute(
                    select(ProcessorRun).order_by(ProcessorRun.run_id.desc()).limit(1)
                ).scalar_one_or_none()

                if run:
                    print(f"\n🔧 Processor run:")
                    print(f"   Engine: {run.engine} v{run.engine_version}")
                    print(f"   Status: {run.status}")
                    print(f"   Docs processed: {run.docs_processed}")
                    print(f"   Tokens total: {run.tokens_total}")
                    print(f"   Lemmas total: {run.lemmas_total}")

                return True
            else:
                print(f"❌ Processing failed")
                return False

    except Exception as e:
        logger.exception("Failed to test ProcessService")
        print(f"❌ ProcessService test failed: {e}")
        return False
    finally:
        # Cleanup
        import shutil
        from pathlib import Path

        if test_dir and test_dir.exists():
            shutil.rmtree(test_dir)

        # Cleanup test database
        test_db_path = Path("test_stanza.db")
        if test_db_path.exists():
            try:
                DBService._instance = None  # Reset singleton
                test_db_path.unlink()
            except Exception:
                pass

if __name__ == "__main__":
    print("="*60)
    print("STANZA PRODUCTION TEST")
    print("="*60)

    # Test 1: Import
    if not test_stanza_import():
        sys.exit(1)

    # Test 2: Engine
    if not test_stanza_engine():
        sys.exit(1)

    # Test 3: Full pipeline
    if not test_process_service_with_stanza():
        sys.exit(1)

    print("\n" + "="*60)
    print("✅ ALL TESTS PASSED - Stanza is working!")
    print("="*60)
    print("\nYou can now use Stanza in the GUI:")
    print("  1. Run: python -m app.main")
    print("  2. Import documents")
    print("  3. Click 'Process with NLP'")
    print("  4. Stanza engine will be used automatically")
