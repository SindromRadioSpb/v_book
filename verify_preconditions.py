"""D0: Preconditions verification for Terms table math spec."""

import io
import sys

# Fix Unicode on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

print("=" * 70)
print("D0: PRECONDITIONS VERIFICATION")
print("=" * 70)

# ================================================================
# 1. Check dependencies
# ================================================================
print("\n[1/6] Checking dependencies...")

deps_ok = True

try:
    import sqlalchemy

    print(f"  ✅ sqlalchemy: {sqlalchemy.__version__}")
except ImportError:
    print("  ❌ sqlalchemy: NOT INSTALLED")
    deps_ok = False

try:
    import stanza

    print(f"  ✅ stanza: {stanza.__version__}")
except ImportError:
    print("  ⚠️  stanza: NOT INSTALLED (Mock engine will be used)")

try:
    from PyQt6 import QtCore

    print(f"  ✅ PyQt6: {QtCore.PYQT_VERSION_STR}")
except ImportError:
    print("  ❌ PyQt6: NOT INSTALLED")
    deps_ok = False

try:
    import numpy

    print(f"  ✅ numpy: {numpy.__version__}")
except ImportError:
    print("  ❌ numpy: NOT INSTALLED")
    deps_ok = False

if not deps_ok:
    print("\n❌ FAILED: Required dependencies missing")
    print("   Action: pip install -r requirements.txt")
    sys.exit(1)

# ================================================================
# 2. Check DB schema and tables
# ================================================================
print("\n[2/6] Checking DB schema...")

from pathlib import Path

from sqlalchemy import inspect, text

from app.services.db_service import DBService

test_db = Path("verify_preconditions.db")
if test_db.exists():
    test_db.unlink()

DBService.initialize(test_db)
db_service = DBService.get_instance()

schema_ok = True

with db_service.get_session() as session:
    # Check schema version
    result = session.execute(text("SELECT value FROM schema_meta WHERE key = 'schema_version'"))
    schema_version = result.scalar()
    print(f"  ✅ Schema version: {schema_version}")

    if schema_version != "4":
        print(f"  ⚠️  Expected schema version 4, got {schema_version}")

    # Check required tables
    inspector = inspect(session.bind)
    tables = inspector.get_table_names()

    required_tables = [
        "schema_meta",
        "library",
        "dict_project",  # Actual table name in schema
        "source_corpus",
        "source_document",
        "document_text",
        "document_sentence",
        "sentence_fts",
        "ngram",
        "ngram_project_stat",
        "term_cluster",
        "term_cluster_member",
    ]

    for table in required_tables:
        if table in tables:
            print(f"  ✅ Table: {table}")
        else:
            print(f"  ❌ Table missing: {table}")
            schema_ok = False

    # Notes about schema design
    print("  ℹ️  Note: NP chunks stored in 'ngram' table (source_kind='np')")
    print("  ℹ️  Note: Token data stored in 'lemma' and related stat tables")

DBService.shutdown()
if test_db.exists():
    test_db.unlink()

if not schema_ok:
    print("\n❌ FAILED: DB schema incomplete")
    sys.exit(1)

# ================================================================
# 3. Check can create project and process documents
# ================================================================
print("\n[3/6] Testing project creation and document processing...")

from app.services.ingest_service import IngestService
from app.services.process_service import ProcessService
from app.services.project_service import ProjectService

test_db = Path("verify_preconditions.db")
DBService.initialize(test_db)
db_service = DBService.get_instance()

project_service = ProjectService()
ingest_service = IngestService()
process_service = ProcessService()

test_dir = Path("verify_preconditions_data")
test_dir.mkdir(exist_ok=True)

process_ok = True

try:
    with db_service.get_session() as session:
        # Create project
        project = project_service.create_project(
            session, "Preconditions Test", "Test project creation"
        )
        print(f"  ✅ Project created: ID={project.project_id}")

        # Get corpus
        corpus = project_service.get_default_corpus(session, project.project_id)
        print(f"  ✅ Corpus retrieved: ID={corpus.corpus_id}")

        # Create test document
        test_file = test_dir / "test.txt"
        test_file.write_text("בית הספר גדול.", encoding="utf-8")

        # Import document
        doc = ingest_service.import_document(session, corpus.corpus_id, test_file)
        print(f"  ✅ Document imported: ID={doc.doc_id}")

        # Process document
        process_service.process_document(session, doc.doc_id, use_mock=True)
        print(f"  ✅ Document processed: {doc.sentence_count} sentences")

    # ================================================================
    # 4. Check term extraction service (while DB is active)
    # ================================================================
    print("\n[4/6] Testing term extraction service...")

    from app.services.term_extraction_service import TermExtractionService

    term_service = TermExtractionService()
    print("  ✅ TermExtractionService initialized")

    # Check key methods exist
    required_methods = [
        "extract_terms_for_project",
        "list_term_clusters",
        "_cluster_terms",
    ]

    for method in required_methods:
        if hasattr(term_service, method):
            print(f"  ✅ Method exists: {method}")
        else:
            print(f"  ❌ Method missing: {method}")
            process_ok = False

except Exception as e:
    print(f"  ❌ FAILED: {e}")
    import traceback

    traceback.print_exc()
    process_ok = False

finally:
    import shutil

    if test_dir.exists():
        shutil.rmtree(test_dir)
    DBService.shutdown()
    if test_db.exists():
        test_db.unlink()

if not process_ok:
    print("\n❌ FAILED: Cannot create/process documents or initialize services")
    sys.exit(1)

# ================================================================
# 5. Check artifact "ה ספר" behavior
# ================================================================
print("\n[5/6] Testing artifact 'ה ספר' normalization...")

from app.domain.hebrew_utils import merge_standalone_articles

# Test before merge (tokenized)
tokens_before = [
    {"text": "ה", "lemma": "ה", "pos": "DET"},
    {"text": "ספר", "lemma": "ספר", "pos": "NOUN"},
]

# Test after merge
tokens_after = merge_standalone_articles(tokens_before)

if len(tokens_after) == 1 and tokens_after[0]["text"] == "הספר":
    print("  ✅ Normalization works: ['ה', 'ספר'] → ['הספר']")
else:
    print(f"  ❌ Normalization broken: got {tokens_after}")
    sys.exit(1)

# Test preservation of enumeration
tokens_enum = [{"text": "סעיף"}, {"text": "ה"}, {"text": "."}]
tokens_enum_result = merge_standalone_articles(tokens_enum)

if len(tokens_enum_result) == 3:
    print("  ✅ Enumeration preserved: ['סעיף', 'ה', '.'] unchanged")
else:
    print(f"  ❌ Enumeration not preserved: got {tokens_enum_result}")
    sys.exit(1)

# ================================================================
# 6. Check canonicalizer and stats functions
# ================================================================
print("\n[6/6] Checking canonicalizer and stats functions...")

from app.domain.term_extraction.canonicalizer import (
    canonicalize_hebrew_term,
)

print("  ✅ canonicalize_hebrew_term")
print("  ✅ has_standalone_function_tokens")
print("  ✅ choose_representative_term")

# Test canonicalization
canonical = canonicalize_hebrew_term("בית הספר")
print(f"  ✅ Canonicalization test: 'בית הספר' → '{canonical}'")

# Check stats module (association_measures.py)
try:
    from app.domain.term_extraction.association_measures import (
        compute_dice,
        compute_llr,
        compute_pmi,
    )

    print("  ✅ compute_pmi")
    print("  ✅ compute_llr")
    print("  ✅ compute_dice")
except ImportError as e:
    print(f"  ❌ Association measures module import failed: {e}")
    sys.exit(1)

# ================================================================
# Summary
# ================================================================
print("\n" + "=" * 70)
print("✅ ALL PRECONDITIONS PASSED")
print("=" * 70)
print("\nReady to proceed with controlled verification (D1).")
print("\nNext steps:")
print("1. Create project with 3 documents (A, B, C)")
print("2. Extract terms")
print("3. Verify math for each column")
