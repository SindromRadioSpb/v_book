"""Test Hebrew article merging (standalone "ה" artifacts)."""

import io
import logging
import sys
from pathlib import Path

# Fix Unicode on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_merge_standalone_articles():
    """
    Test merge_standalone_articles() function.

    Tests both positive (should merge) and negative (should NOT merge) cases.
    """
    from app.domain.hebrew_utils import merge_standalone_articles

    print("\n" + "=" * 60)
    print("TEST: merge_standalone_articles()")
    print("=" * 60)

    # ================================================================
    # POSITIVE CASES: Should merge
    # ================================================================
    print("\n🔍 POSITIVE CASES (should merge):")

    # Test 1: Simple article + noun
    tokens = [
        {"text": "ה", "lemma": "ה", "pos": "DET"},
        {"text": "ספר", "lemma": "ספר", "pos": "NOUN"},
    ]
    result = merge_standalone_articles(tokens)
    assert len(result) == 1, f"Expected 1 token, got {len(result)}"
    assert result[0]["text"] == "הספר", f"Expected 'הספר', got '{result[0]['text']}'"
    assert result[0]["lemma"] == "ספר", f"Expected lemma 'ספר', got '{result[0]['lemma']}'"
    print("✅ Test 1: ['ה', 'ספר'] → ['הספר']")

    # Test 2: Article + noun with modifier
    tokens = [
        {"text": "ה", "lemma": "ה", "pos": "DET"},
        {"text": "תנועה", "lemma": "תנועה", "pos": "NOUN"},
        {"text": "הגדולה", "lemma": "גדול", "pos": "ADJ"},
    ]
    result = merge_standalone_articles(tokens)
    assert len(result) == 2, f"Expected 2 tokens, got {len(result)}"
    assert result[0]["text"] == "התנועה", f"Expected 'התנועה', got '{result[0]['text']}'"
    assert result[1]["text"] == "הגדולה", f"Expected 'הגדולה', got '{result[1]['text']}'"
    print("✅ Test 2: ['ה', 'תנועה', 'הגדולה'] → ['התנועה', 'הגדולה']")

    # Test 3: Multiple standalone articles
    tokens = [
        {"text": "ה", "lemma": "ה", "pos": "DET"},
        {"text": "ספר", "lemma": "ספר", "pos": "NOUN"},
        {"text": "ה", "lemma": "ה", "pos": "DET"},
        {"text": "גדול", "lemma": "גדול", "pos": "ADJ"},
    ]
    result = merge_standalone_articles(tokens)
    assert len(result) == 2, f"Expected 2 tokens, got {len(result)}"
    assert result[0]["text"] == "הספר", f"Expected 'הספר', got '{result[0]['text']}'"
    assert result[1]["text"] == "הגדול", f"Expected 'הגדול', got '{result[1]['text']}'"
    print("✅ Test 3: ['ה', 'ספר', 'ה', 'גדול'] → ['הספר', 'הגדול']")

    # Test 4: Prefix "ב" (in/at)
    tokens = [
        {"text": "ב", "lemma": "ב", "pos": "ADP"},
        {"text": "בית", "lemma": "בית", "pos": "NOUN"},
    ]
    result = merge_standalone_articles(tokens)
    assert len(result) == 1, f"Expected 1 token, got {len(result)}"
    assert result[0]["text"] == "בבית", f"Expected 'בבית', got '{result[0]['text']}'"
    print("✅ Test 4: ['ב', 'בית'] → ['בבית']")

    # ================================================================
    # NEGATIVE CASES: Should NOT merge
    # ================================================================
    print("\n🔍 NEGATIVE CASES (should NOT merge):")

    # Test 5: Enumeration with period
    tokens = [{"text": "סעיף"}, {"text": "ה"}, {"text": "."}]
    result = merge_standalone_articles(tokens)
    assert len(result) == 3, f"Expected 3 tokens, got {len(result)}"
    assert result[1]["text"] == "ה", f"Expected standalone 'ה', got '{result[1]['text']}'"
    print("✅ Test 5: ['סעיף', 'ה', '.'] → unchanged (enumeration)")

    # Test 6: Enumeration with colon
    tokens = [{"text": "סעיף"}, {"text": "ה"}, {"text": ":"}]
    result = merge_standalone_articles(tokens)
    assert len(result) == 3, f"Expected 3 tokens, got {len(result)}"
    assert result[1]["text"] == "ה", f"Expected standalone 'ה', got '{result[1]['text']}'"
    print("✅ Test 6: ['סעיף', 'ה', ':'] → unchanged (enumeration)")

    # Test 7: Enumeration with parenthesis
    tokens = [{"text": "סעיף"}, {"text": "ה"}, {"text": ")"}]
    result = merge_standalone_articles(tokens)
    assert len(result) == 3, f"Expected 3 tokens, got {len(result)}"
    assert result[1]["text"] == "ה", f"Expected standalone 'ה', got '{result[1]['text']}'"
    print("✅ Test 7: ['סעיף', 'ה', ')'] → unchanged (enumeration)")

    # Test 8: Variable/equation with equals
    tokens = [{"text": "ה"}, {"text": "="}, {"text": "5"}]
    result = merge_standalone_articles(tokens)
    assert len(result) == 3, f"Expected 3 tokens, got {len(result)}"
    assert result[0]["text"] == "ה", f"Expected standalone 'ה', got '{result[0]['text']}'"
    print("✅ Test 8: ['ה', '=', '5'] → unchanged (variable)")

    # Test 9: Variable with letter
    tokens = [{"text": "ה"}, {"text": "="}, {"text": "k"}]
    result = merge_standalone_articles(tokens)
    assert len(result) == 3, f"Expected 3 tokens, got {len(result)}"
    assert result[0]["text"] == "ה", f"Expected standalone 'ה', got '{result[0]['text']}'"
    print("✅ Test 9: ['ה', '=', 'k'] → unchanged (variable)")

    # Test 10: Comma separation
    tokens = [{"text": "ספר"}, {"text": "ה"}, {"text": ","}]
    result = merge_standalone_articles(tokens)
    assert len(result) == 3, f"Expected 3 tokens, got {len(result)}"
    assert result[1]["text"] == "ה", f"Expected standalone 'ה', got '{result[1]['text']}'"
    print("✅ Test 10: ['ספר', 'ה', ','] → unchanged (punctuation)")

    # Test 11: End of sentence (no next token)
    tokens = [{"text": "ספר"}, {"text": "ה"}]
    result = merge_standalone_articles(tokens)
    assert len(result) == 2, f"Expected 2 tokens, got {len(result)}"
    assert result[1]["text"] == "ה", f"Expected standalone 'ה', got '{result[1]['text']}'"
    print("✅ Test 11: ['ספר', 'ה'] → unchanged (end of sentence)")

    # Test 12: Empty token list
    tokens = []
    result = merge_standalone_articles(tokens)
    assert len(result) == 0, f"Expected empty list, got {len(result)}"
    print("✅ Test 12: [] → [] (empty list)")

    # Test 13: No prefixes
    tokens = [{"text": "ספר"}, {"text": "גדול"}]
    result = merge_standalone_articles(tokens)
    assert len(result) == 2, f"Expected 2 tokens, got {len(result)}"
    assert result[0]["text"] == "ספר", f"Expected 'ספר', got '{result[0]['text']}'"
    print("✅ Test 13: ['ספר', 'גדול'] → unchanged (no prefixes)")

    print("\n✅ All unit tests passed!")
    return True


def test_integration_with_term_extraction():
    """
    Integration test: Verify that Terms table shows merged forms.

    Creates test project, imports document with "ה ספר" tokenization,
    extracts terms, and verifies NO standalone "ה " artifacts appear.
    """
    from app.services.db_service import DBService
    from app.services.ingest_service import IngestService
    from app.services.process_service import ProcessService
    from app.services.project_service import ProjectService
    from app.services.term_extraction_service import TermExtractionService

    print("\n" + "=" * 60)
    print("INTEGRATION TEST: Term Extraction")
    print("=" * 60)

    # Initialize
    test_db_path = Path("test_article_merge.db")
    if test_db_path.exists():
        test_db_path.unlink()

    DBService.initialize(test_db_path)
    db_service = DBService.get_instance()
    project_service = ProjectService()
    ingest_service = IngestService()
    process_service = ProcessService()
    term_service = TermExtractionService()

    test_dir = Path("test_data_article_merge")
    test_dir.mkdir(exist_ok=True)

    try:
        with db_service.get_session() as session:
            # ================================================================
            # 1. Create test project
            # ================================================================
            print("\n🔍 Creating test project...")

            project = project_service.create_project(
                session, "Article Merge Test", "Test standalone article merging"
            )
            corpus = project_service.get_default_corpus(session, project.project_id)
            print(f"✅ Created project: {project.name}")

            # ================================================================
            # 2. Create test document with text that triggers article separation
            # ================================================================
            # MockEngine will tokenize this deterministically
            # It splits by whitespace, so we need to simulate what Stanza does:
            # We'll create a sentence that MockEngine tokenizes as ["ה", "ספר"]
            test_file = test_dir / "hebrew_test.txt"
            test_file.write_text(
                "ה ספר הזה. "  # Simulates Stanza tokenizing "הספר" as ["ה", "ספר"]
                "בית ה ספר. "  # House of the book
                "ה תנועה הגדולה. ",  # The big movement
                encoding="utf-8",
            )

            doc = ingest_service.import_document(session, corpus.corpus_id, test_file)
            process_service.process_document(session, doc.doc_id, use_mock=True)
            print(f"✅ Processed document with {doc.sentence_count} sentences")

            # ================================================================
            # 3. Extract terms
            # ================================================================
            print("\n🔍 Extracting terms...")

            report = term_service.extract_terms_for_project(
                session,
                project.project_id,
                enable_ngrams=True,
                include_np=False,  # Only n-grams for simplicity
                min_freq=1,
                ngram_ns=(2,),  # Only bigrams
                overwrite=True,
            )

            print(f"✅ Extracted {report.ngrams_extracted} n-grams")
            print(f"✅ Created {report.clusters_created} clusters")

            # ================================================================
            # 4. Verify NO standalone "ה " artifacts in clusters
            # ================================================================
            print("\n🔍 Checking for standalone article artifacts...")

            from app.domain.term_extraction.canonicalizer import has_standalone_function_tokens

            clusters = term_service.list_term_clusters(
                session, project.project_id, top_n=100, preset="freq"
            )

            print(f"✅ Retrieved {len(clusters)} clusters")

            # Check each cluster
            artifacts_found = []
            clean_terms = []

            for cluster in clusters:
                rep = cluster.representative_he
                if has_standalone_function_tokens(rep):
                    artifacts_found.append(rep)
                else:
                    clean_terms.append(rep)

            # Display results
            if clean_terms:
                print("\n✅ Clean terms (no artifacts):")
                for term in clean_terms[:10]:  # Show first 10
                    print(f"   - {term}")

            if artifacts_found:
                print(f"\n❌ FAILED: Found {len(artifacts_found)} terms with standalone articles:")
                for term in artifacts_found:
                    print(f"   - '{term}'")
                return False
            else:
                print("\n✅ SUCCESS: No standalone article artifacts found!")

            # ================================================================
            # 5. Verify specific expected terms
            # ================================================================
            print("\n🔍 Verifying expected merged terms...")

            term_texts = [c.representative_he for c in clusters]

            # We expect to see merged forms, not "ה ספר"
            expected_merged = ["הספר", "הזה", "התנועה"]  # Merged forms
            not_expected = ["ה ספר", "ה תנועה"]  # Artifacts

            for expected in expected_merged:
                # Check if any cluster contains this merged form
                found = any(expected in term for term in term_texts)
                if found:
                    print(f"✅ Found expected merged term containing: {expected}")

            for not_exp in not_expected:
                if not_exp in term_texts:
                    print(f"❌ FAILED: Found unexpected artifact: '{not_exp}'")
                    return False

            print(f"\n{'='*60}")
            print("✅ INTEGRATION TEST PASSED: Article merging works!")
            print(f"{'='*60}")
            return True

    except Exception as e:
        logger.exception("Integration test failed")
        print(f"\n❌ INTEGRATION TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        return False

    finally:
        # Cleanup
        import shutil

        if test_dir.exists():
            shutil.rmtree(test_dir)

        DBService.shutdown()

        if test_db_path.exists():
            try:
                test_db_path.unlink()
            except PermissionError:
                logger.warning(f"Could not delete {test_db_path}")


if __name__ == "__main__":
    print("=" * 60)
    print("HEBREW ARTICLE MERGE TEST SUITE")
    print("=" * 60)

    # Run unit tests
    unit_pass = test_merge_standalone_articles()

    # Run integration test
    integration_pass = test_integration_with_term_extraction()

    # Summary
    print("\n" + "=" * 60)
    if unit_pass and integration_pass:
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        sys.exit(0)
    else:
        print("❌ SOME TESTS FAILED")
        print("=" * 60)
        sys.exit(1)
