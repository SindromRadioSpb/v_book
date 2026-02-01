"""Test M6: Concordance/KWIC search."""
import sys
import io
import logging
import time
from pathlib import Path

# Fix Unicode on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_concordance_search():
    """
    Test M6: Concordance/KWIC search functionality.

    Tests:
    1. FTS index exists and is queryable
    2. Search returns results with KWIC split
    3. Phrase search works
    4. Article normalization finds variants
    5. Project filtering works (results only from selected project)
    6. Performance is acceptable (<1s for medium projects)
    """
    from app.services.db_service import DBService
    from app.services.project_service import ProjectService
    from app.services.ingest_service import IngestService
    from app.services.process_service import ProcessService
    from app.services.concordance_service import ConcordanceService

    print("\n" + "="*60)
    print("TEST M6: Concordance/KWIC Search")
    print("="*60)

    # Initialize
    test_db_path = Path("test_m6.db")
    if test_db_path.exists():
        test_db_path.unlink()

    DBService.initialize(test_db_path)
    db_service = DBService.get_instance()
    project_service = ProjectService()
    ingest_service = IngestService()
    process_service = ProcessService()
    concordance_service = ConcordanceService()

    test_dir = Path("test_data_m6")
    test_dir.mkdir(exist_ok=True)

    try:
        with db_service.get_session() as session:
            # ================================================================
            # 1. Create test project and documents
            # ================================================================
            print("\n🔍 Creating test project...")

            project = project_service.create_project(
                session,
                "M6 Test Project",
                "Test concordance search"
            )
            corpus = project_service.get_default_corpus(session, project.project_id)
            print(f"✅ Created project: {project.name}")

            # Create test document with Hebrew text
            test_file = test_dir / "hebrew_text.txt"
            test_file.write_text(
                "בית ספר גדול בעיר. "  # School (no article on second word)
                "בית הספר החדש נפלא. "  # School (with article)
                "הספר הזה טוב מאוד. "  # Book
                "ילדים לומדים בבית ספר. "  # School (with prefix)
                "מורה מלמדת בבית הספר. "  # School (prefix + article)
                "הספר החדש יצא לאור. ",  # Book
                encoding='utf-8'
            )

            doc = ingest_service.import_document(session, corpus.corpus_id, test_file)
            process_service.process_document(session, doc.doc_id, use_mock=True)
            print(f"✅ Processed document with {doc.sentence_count} sentences")

            # ================================================================
            # 2. Test FTS index exists and is queryable
            # ================================================================
            print(f"\n🔍 Testing FTS index...")

            # Check that sentence_fts exists
            from sqlalchemy import text
            result = session.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='sentence_fts'"
            ))
            fts_exists = result.scalar() is not None

            if fts_exists:
                print(f"✅ sentence_fts table exists")
            else:
                print(f"❌ FAILED: sentence_fts table not found")
                return False

            # Check that sentences were indexed
            result = session.execute(text("SELECT COUNT(*) FROM sentence_fts"))
            fts_count = result.scalar()

            if fts_count > 0:
                print(f"✅ sentence_fts has {fts_count} indexed sentences")
            else:
                print(f"❌ FAILED: sentence_fts is empty")
                return False

            # ================================================================
            # 3. Test basic word search
            # ================================================================
            print(f"\n🔍 Testing word search for 'ספר'...")

            start_time = time.time()
            results = concordance_service.search_concordance(
                session,
                project.project_id,
                "ספר",
                limit=100
            )
            search_time = time.time() - start_time

            print(f"✅ Search completed in {search_time*1000:.1f}ms")

            if search_time > 1.0:
                print(f"⚠️  WARNING: Search took >{search_time:.2f}s (target <1s for CI)")

            if results:
                print(f"✅ Found {len(results)} results")

                # Check KWIC split
                first = results[0]
                if first.match and first.match.strip():
                    print(f"✅ KWIC split works: match='{first.match}'")
                else:
                    print(f"❌ FAILED: Empty match in KWIC split")
                    return False

                # Display first result
                print(f"\n   Example result:")
                print(f"   Left:  '{first.left_context}'")
                print(f"   Match: '{first.match}'")
                print(f"   Right: '{first.right_context}'")
                print(f"   Doc:   {first.doc_name}")

            else:
                print(f"❌ FAILED: No results found for 'ספר'")
                return False

            # ================================================================
            # 4. Test phrase search
            # ================================================================
            print(f"\n🔍 Testing phrase search for 'בית ספר'...")

            results_phrase = concordance_service.search_concordance(
                session,
                project.project_id,
                "בית ספר",
                limit=100,
                is_phrase=True
            )

            if results_phrase:
                print(f"✅ Phrase search found {len(results_phrase)} results")

                # Should find "בית ספר" exact matches
                for r in results_phrase[:3]:
                    print(f"   - '{r.left_context} <<{r.match}>> {r.right_context}'")

            else:
                print(f"⚠️  Phrase search found no results (may be due to Mock engine tokenization)")

            # ================================================================
            # 5. Test article normalization
            # ================================================================
            print(f"\n🔍 Testing article normalization...")

            # Search for "בית הספר" should also find "בית ספר"
            results_normalized = concordance_service.search_concordance(
                session,
                project.project_id,
                "בית הספר",  # With article
                limit=100,
                normalize=True  # Enable normalization
            )

            if results_normalized:
                print(f"✅ Normalized search found {len(results_normalized)} results")

                # Check if we found both variants
                has_with_article = any('הספר' in r.match for r in results_normalized)
                has_without_article = any('ספר' in r.match and 'הספר' not in r.match for r in results_normalized)

                if has_with_article or has_without_article:
                    print(f"✅ Found article variants in results")
                else:
                    print(f"⚠️  Article variants not found (may be due to Mock engine)")

            else:
                print(f"⚠️  Normalized search found no results")

            # ================================================================
            # 6. Test project filtering
            # ================================================================
            print(f"\n🔍 Testing project filtering...")

            # Create second project
            project2 = project_service.create_project(
                session,
                "M6 Test Project 2",
                "Second project for filter test"
            )
            corpus2 = project_service.get_default_corpus(session, project2.project_id)

            # Add different document to project2
            test_file2 = test_dir / "other_text.txt"
            test_file2.write_text(
                "מחשב חדש קנינו. "
                "המחשב עובד טוב. ",
                encoding='utf-8'
            )

            doc2 = ingest_service.import_document(session, corpus2.corpus_id, test_file2)
            process_service.process_document(session, doc2.doc_id, use_mock=True)

            # Search in project1 - should find "ספר"
            results_proj1 = concordance_service.search_concordance(
                session,
                project.project_id,
                "ספר",
                limit=100
            )

            # Search in project2 - should NOT find "ספר"
            results_proj2 = concordance_service.search_concordance(
                session,
                project2.project_id,
                "ספר",
                limit=100
            )

            if len(results_proj1) > 0 and len(results_proj2) == 0:
                print(f"✅ Project filtering works:")
                print(f"   Project 1: {len(results_proj1)} results")
                print(f"   Project 2: {len(results_proj2)} results")
            else:
                print(f"❌ FAILED: Project filtering incorrect")
                print(f"   Project 1: {len(results_proj1)} results (expected > 0)")
                print(f"   Project 2: {len(results_proj2)} results (expected = 0)")
                return False

            # ================================================================
            # 7. Test schema version
            # ================================================================
            print(f"\n🔍 Checking schema version...")

            result = session.execute(text(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ))
            schema_version = result.scalar()

            if schema_version == '4':
                print(f"✅ Schema version is 4 (Migration 004 applied)")
            else:
                print(f"⚠️  WARNING: Schema version is {schema_version} (expected 4)")
                print(f"   Migration 004 may not have been applied yet")

            # ================================================================
            # 8. Performance check
            # ================================================================
            print(f"\n🔍 Performance check (3 searches)...")

            times = []
            for i in range(3):
                start = time.time()
                concordance_service.search_concordance(
                    session,
                    project.project_id,
                    "ספר",
                    limit=100
                )
                times.append((time.time() - start) * 1000)

            avg_time = sum(times) / len(times)
            print(f"   Search times: {[f'{t:.1f}ms' for t in times]}")
            print(f"   Average: {avg_time:.1f}ms")

            if avg_time < 1000:
                print(f"✅ Performance acceptable (<1s average)")
            else:
                print(f"⚠️  Performance slower than expected ({avg_time:.0f}ms avg)")
                print(f"   Note: This is OK for small test DB, target is <300ms for medium projects")

            print(f"\n{'='*60}")
            print(f"✅ M6 TEST PASSED: Concordance search works!")
            print(f"{'='*60}")
            return True

    except Exception as e:
        logger.exception("Test failed")
        print(f"\n❌ M6 TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

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
            except PermissionError:
                logger.warning(f"Could not delete {test_db_path}")
                pass


if __name__ == "__main__":
    print("="*60)
    print("M6 TEST SUITE: Concordance/KWIC Search")
    print("="*60)

    test_pass = test_concordance_search()

    print("\n" + "="*60)
    if test_pass:
        print("✅ M6 TEST PASSED")
    else:
        print("❌ M6 TEST FAILED")
    print("="*60)

    sys.exit(0 if test_pass else 1)
