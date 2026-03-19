"""Analyze expected terms for specific test text."""

import io
import sys

# Fix Unicode on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pathlib import Path

from app.services.db_service import DBService
from app.services.ingest_service import IngestService
from app.services.process_service import ProcessService
from app.services.project_service import ProjectService
from app.services.term_extraction_service import TermExtractionService

print("=" * 70)
print("ANALYSIS: Expected terms for specific test text")
print("=" * 70)

# Test text
test_text = """בית ספר גדול.
בית הספר החדש.
ה ספר הזה טוב."""

print("\nTest text:")
print(test_text)
print()

# Initialize
test_db_path = Path("test_analysis.db")
if test_db_path.exists():
    test_db_path.unlink()

DBService.initialize(test_db_path)
db_service = DBService.get_instance()
project_service = ProjectService()
ingest_service = IngestService()
process_service = ProcessService()
term_service = TermExtractionService()

# Create test file
test_dir = Path("test_data_analysis")
test_dir.mkdir(exist_ok=True)
test_file = test_dir / "hebrew_test.txt"
test_file.write_text(test_text, encoding="utf-8")

try:
    with db_service.get_session() as session:
        # Create project
        project = project_service.create_project(session, "Analysis", "Test")
        corpus = project_service.get_default_corpus(session, project.project_id)

        # Import and process
        doc = ingest_service.import_document(session, corpus.corpus_id, test_file)
        process_service.process_document(session, doc.doc_id, use_mock=True)

        # Extract terms (n-grams only, no NP chunks for clarity)
        report = term_service.extract_terms_for_project(
            session,
            project.project_id,
            enable_ngrams=True,
            include_np=False,  # Disable NP for cleaner results
            min_freq=1,
            ngram_ns=(2,),  # Only bigrams
            overwrite=True,
        )

        print("Extraction results:")
        print(f"  N-grams extracted: {report.ngrams_extracted}")
        print(f"  Clusters created: {report.clusters_created}")

        # List all clusters
        clusters = term_service.list_term_clusters(
            session, project.project_id, top_n=100, preset="freq"
        )

        print(f"\n{'='*70}")
        print(f"CLUSTERS IN TERMS TAB ({len(clusters)} total):")
        print(f"{'='*70}\n")

        for i, cluster in enumerate(clusters, 1):
            print(f"{i}. Term: '{cluster.representative_he}'")
            print(f"   Canonical: {cluster.canonical_key}")
            print(f"   Lemma: {cluster.representative_lemma}")
            print(f"   Freq: {cluster.freq_abs}")
            print(f"   Members: {cluster.members_count}")

            # Get cluster members
            members = term_service.get_cluster_members(session, cluster.cluster_id)
            print("   Variants:")
            for member in members:
                print(f"     - '{member['surface_text']}' (freq: {member['freq_abs']})")
            print()

        print(f"{'='*70}")
        print("SUMMARY FOR UI:")
        print(f"{'='*70}")
        print(f"Total terms in 'Term' column: {len(clusters)}")
        print("\nExpected entries (representatives):")
        for i, cluster in enumerate(clusters, 1):
            print(f"{i}. {cluster.representative_he}")

finally:
    # Cleanup
    import shutil
    import time

    if test_dir.exists():
        shutil.rmtree(test_dir)

    DBService.shutdown()
    time.sleep(0.1)

    if test_db_path.exists():
        try:
            test_db_path.unlink()
        except:
            pass
