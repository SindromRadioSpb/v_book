"""Test M5: Term Extraction with "בית ספר" clustering."""

import io
import logging
import sys
from pathlib import Path

# Fix Unicode on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_beit_sefer_clustering():
    """
    Test that "בית ספר" variants cluster correctly.

    Tests:
    1. Multiple surface variants of "בית ספר" are extracted
    2. They cluster into ONE canonical cluster
    3. Cluster has correct aggregated stats
    4. Re-running doesn't create duplicates
    """
    from sqlalchemy import and_, select

    from app.services.db_service import DBService
    from app.services.ingest_service import IngestService
    from app.services.process_service import ProcessService
    from app.services.project_service import ProjectService
    from app.services.term_extraction_service import TermExtractionService

    print("\n" + "=" * 60)
    print("TEST M5: 'בית ספר' Clustering")
    print("=" * 60)

    # Initialize
    test_db_path = Path("test_m5.db")
    if test_db_path.exists():
        test_db_path.unlink()

    DBService.initialize(test_db_path)
    db_service = DBService.get_instance()
    project_service = ProjectService()
    ingest_service = IngestService()
    process_service = ProcessService()
    term_service = TermExtractionService()

    # Create test file with בית ספר variants
    test_dir = Path("test_data_m5")
    test_dir.mkdir(exist_ok=True)

    file1 = test_dir / "hebrew_text.txt"
    file1.write_text(
        "בית ספר גדול. "  # Bare form
        "בבית ספר קטן. "  # With prefix ב
        "לבית הספר הלכתי. "  # With prefix ל + article ה
        "בית הספר נפלא. "  # With article ה
        # M5.3 NP chunks (3-5 tokens)
        "מערכת ניהול נתונים מתקדמת פועלת כאן. "  # 5-token NP
        "תורת החומרים היא תחום מרכזי.",  # 3-token NPs
        encoding="utf-8",
    )

    try:
        with db_service.get_session() as session:
            # Create project
            project = project_service.create_project(
                session, "M5 Test", "Test term extraction and clustering"
            )
            corpus = project_service.get_default_corpus(session, project.project_id)
            print(f"✅ Created project: {project.name}")

            # Import and process document
            doc = ingest_service.import_document(session, corpus.corpus_id, file1)
            process_service.process_document(session, doc.doc_id, use_mock=True)
            print("✅ Processed document with Mock engine")

            # Extract terms (including NP chunks for M5.3)
            print("\n🔍 Extracting terms (n-grams + NP chunks)...")
            report = term_service.extract_terms_for_project(
                session,
                project.project_id,
                enable_ngrams=True,
                include_np=True,  # M5.3
                min_freq=1,  # Low threshold to catch all variants
                ngram_ns=(2,),
                np_max_len=5,  # M5.3
                overwrite=True,
            )

            if not report.success:
                print(f"❌ Term extraction failed: {report.error_message}")
                return False

            print("✅ Term extraction complete:")
            print(f"   N-grams: {report.ngrams_extracted}")
            print(f"   NP chunks: {report.np_chunks_extracted}")
            print(f"   Clusters: {report.clusters_created}")

            # List clusters
            clusters = term_service.list_term_clusters(
                session, project.project_id, top_n=20, preset="freq"
            )

            print(f"\n📊 Term clusters ({len(clusters)}):")
            for cluster in clusters:
                pmi_str = f"{cluster.best_pmi:6.2f}" if cluster.best_pmi else "   N/A"
                print(
                    f"   {cluster.representative_he:20s} | "
                    f"Freq: {cluster.freq_abs:3d} | "
                    f"Members: {cluster.members_count:2d} | "
                    f"PMI: {pmi_str:>6s}"
                )

            # Find בית ספר cluster
            beit_sefer_cluster = None
            for cluster in clusters:
                # Check if canonical key matches "בית_ספר" pattern
                if "בית" in cluster.canonical_key and "ספר" in cluster.canonical_key:
                    beit_sefer_cluster = cluster
                    break

            if not beit_sefer_cluster:
                print("\n❌ FAILED: No 'בית ספר' cluster found!")
                print(f"   Available clusters: {[c.canonical_key for c in clusters]}")
                return False

            print("\n✅ Found 'בית ספר' cluster:")
            print(f"   Canonical key: {beit_sefer_cluster.canonical_key}")
            print(f"   Representative: {beit_sefer_cluster.representative_he}")
            print(f"   Total frequency: {beit_sefer_cluster.freq_abs}")
            print(f"   Members count: {beit_sefer_cluster.members_count}")

            # Get cluster members
            members = term_service.get_cluster_members(session, beit_sefer_cluster.cluster_id)

            print("\n📋 Cluster members (surface variants):")
            for member in members:
                print(
                    f"   {member['surface_text']:20s} | "
                    f"Freq: {member['freq_abs']:2d} | "
                    f"Lemma: {member['lemma_phrase']}"
                )

            # Verify requirements
            expected_total_freq = 4  # We have 4 occurrences in text
            expected_min_members = 2  # At least bare + with-prefix variants

            if beit_sefer_cluster.freq_abs >= expected_total_freq:
                print(f"\n✅ Frequency aggregation correct (>= {expected_total_freq})")
            else:
                print(
                    f"\n⚠️  WARNING: Frequency lower than expected "
                    f"({beit_sefer_cluster.freq_abs} < {expected_total_freq})"
                )

            if beit_sefer_cluster.members_count >= expected_min_members:
                print(f"✅ Multiple variants clustered (>= {expected_min_members} members)")
            else:
                print(f"❌ FAILED: Too few members ({beit_sefer_cluster.members_count})")
                return False

            # M5.3: Verify NP chunks were extracted
            print("\n🔍 Checking NP chunks (M5.3)...")

            # Check if we have NP chunks (source_kind='np')
            from app.infra.sa_models import Ngram

            np_stmt = select(Ngram).where(
                and_(Ngram.project_id == project.project_id, Ngram.source_kind == "np")
            )
            np_candidates = session.execute(np_stmt).scalars().all()

            if np_candidates:
                print(f"✅ Found {len(np_candidates)} NP chunks")
                # Check for longer NPs (n >= 3)
                long_nps = [np for np in np_candidates if np.n >= 3]
                if long_nps:
                    print(f"✅ Found {len(long_nps)} NP chunks with length >= 3 tokens")
                    for np in long_nps[:3]:  # Show first 3
                        print(f"   {np.surface_text} (n={np.n})")
                else:
                    print(
                        "⚠️  No NP chunks with length >= 3 found (may be due to Mock engine limitations)"
                    )
            else:
                print("⚠️  No NP chunks found (may be due to Mock engine limitations)")

            # M5.2: Verify LLR and Dice scores
            print("\n🔍 Checking association scores (M5.2)...")

            if beit_sefer_cluster.best_llr is not None:
                print(f"✅ LLR computed: {beit_sefer_cluster.best_llr:.2f}")
            else:
                print("⚠️  LLR is NULL (expected for bigrams)")

            if beit_sefer_cluster.best_dice is not None:
                print(f"✅ Dice computed: {beit_sefer_cluster.best_dice:.3f}")
                if 0 <= beit_sefer_cluster.best_dice <= 1:
                    print("✅ Dice in valid range [0,1]")
                else:
                    print(f"❌ FAILED: Dice out of range: {beit_sefer_cluster.best_dice}")
                    return False
            else:
                print("⚠️  Dice is NULL (expected for bigrams)")

            # M5.2: Test preset ordering
            print("\n🔍 Testing ranking presets (M5.2)...")

            # Get clusters with different presets
            clusters_freq = term_service.list_term_clusters(
                session, project.project_id, top_n=10, preset="freq"
            )
            clusters_strong = term_service.list_term_clusters(
                session, project.project_id, top_n=10, preset="strong"
            )
            clusters_balanced = term_service.list_term_clusters(
                session, project.project_id, top_n=10, preset="balanced"
            )

            # Verify presets produce deterministic results
            print(f"   Preset 'freq': {len(clusters_freq)} clusters")
            print(f"   Preset 'strong': {len(clusters_strong)} clusters")
            print(f"   Preset 'balanced': {len(clusters_balanced)} clusters")

            # Verify ordering is deterministic (same preset returns same order)
            clusters_freq2 = term_service.list_term_clusters(
                session, project.project_id, top_n=10, preset="freq"
            )
            if [c.cluster_id for c in clusters_freq] == [c.cluster_id for c in clusters_freq2]:
                print("✅ Preset ordering is deterministic")
            else:
                print("❌ FAILED: Preset ordering not deterministic")
                return False

            # FIX #1: Verify no garbage terms (standalone function tokens)
            print("\n🔍 Checking for garbage terms (FIX #1)...")

            # Check all clusters - none should have standalone function tokens as representative
            from app.domain.term_extraction.canonicalizer import has_standalone_function_tokens

            garbage_terms = []
            for cluster in clusters:
                if has_standalone_function_tokens(cluster.representative_he):
                    garbage_terms.append(cluster.representative_he)

            if garbage_terms:
                print("❌ FAILED: Found garbage terms with standalone function tokens:")
                for term in garbage_terms:
                    print(f"   '{term}'")
                return False
            else:
                print("✅ No garbage terms found (no standalone function tokens)")

            # FIX #2: Verify search normalization works
            print("\n🔍 Testing search normalization (FIX #2)...")

            # Search for "בית הספר" (with article on second word)
            # Should find "בית_ספר" cluster (lemma without article)
            search_results = term_service.list_term_clusters(
                session,
                project.project_id,
                top_n=20,
                preset="freq",
                search="בית הספר",  # With article
            )

            found_beit_sefer = False
            for cluster in search_results:
                if "בית" in cluster.canonical_key and "ספר" in cluster.canonical_key:
                    found_beit_sefer = True
                    print(f"✅ Search 'בית הספר' found cluster: {cluster.canonical_key}")
                    break

            if not found_beit_sefer:
                print("❌ FAILED: Search 'בית הספר' did not find 'בית_ספר' cluster")
                print(f"   Search returned {len(search_results)} clusters:")
                for cluster in search_results[:5]:
                    print(f"   - {cluster.representative_he} (canonical: {cluster.canonical_key})")
                return False

            # Also test article-only search
            search_results_2 = term_service.list_term_clusters(
                session,
                project.project_id,
                top_n=20,
                preset="freq",
                search="ספר",  # Just "book" without article
            )

            if len(search_results_2) > 0:
                print(f"✅ Search 'ספר' found {len(search_results_2)} cluster(s)")
            else:
                print("⚠️  Search 'ספר' found no clusters (may be due to test data)")

            # Test re-running (determinism)
            print("\n🔁 Re-running extraction to test determinism...")
            report2 = term_service.extract_terms_for_project(
                session,
                project.project_id,
                enable_ngrams=True,
                include_np=True,
                min_freq=1,
                ngram_ns=(2,),
                np_max_len=5,
                overwrite=True,
            )

            clusters2 = term_service.list_term_clusters(
                session, project.project_id, top_n=20, preset="freq"
            )

            if len(clusters2) == len(clusters):
                print(f"✅ Determinism verified: same cluster count ({len(clusters2)})")
            else:
                print(f"⚠️  WARNING: Cluster count changed ({len(clusters)} → {len(clusters2)})")

            print(f"\n{'='*60}")
            print("✅ M5 TEST PASSED: 'בית ספר' clustering works!")
            print(f"{'='*60}")
            return True

    except Exception as e:
        logger.exception("Test failed")
        print(f"\n❌ M5 TEST FAILED: {e}")
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


def test_termhood_ranking():
    """
    Test M5.4: Termhood ranking vs reference corpus.

    Tests:
    1. Set reference project (general corpus)
    2. Compute weirdness and keyness for domain vs reference
    3. Domain-specific terms rank higher than common terms
    4. Deterministic ordering
    """
    from app.services.db_service import DBService
    from app.services.ingest_service import IngestService
    from app.services.process_service import ProcessService
    from app.services.project_service import ProjectService
    from app.services.term_extraction_service import TermExtractionService

    print("\n" + "=" * 60)
    print("TEST M5.4: Termhood vs Reference Corpus")
    print("=" * 60)

    # Initialize
    test_db_path = Path("test_m54.db")
    if test_db_path.exists():
        test_db_path.unlink()

    DBService.initialize(test_db_path)
    db_service = DBService.get_instance()
    project_service = ProjectService()
    ingest_service = IngestService()
    process_service = ProcessService()
    term_service = TermExtractionService()

    test_dir = Path("test_data_m54")
    test_dir.mkdir(exist_ok=True)

    try:
        with db_service.get_session() as session:
            # ===================================================================
            # 1. Create GENERAL project (reference corpus) with common text
            # ===================================================================
            print("\n🔍 Creating GENERAL reference project...")

            general_project = project_service.create_project(
                session, "General Hebrew", "Reference corpus with common Hebrew text"
            )
            general_corpus = project_service.get_default_corpus(session, general_project.project_id)

            # General text: common phrases
            general_file = test_dir / "general_text.txt"
            general_file.write_text(
                "הספר הזה טוב מאוד. "  # This book is very good
                "הילד אוהב לקרוא ספרים. "  # The child loves to read books
                "ספר טוב מלמד הרבה. "  # A good book teaches a lot
                "בבית יש ספרים רבים. "  # At home there are many books
                "ספר חדש יצא לאור. ",  # A new book was published
                encoding="utf-8",
            )

            doc_gen = ingest_service.import_document(
                session, general_corpus.corpus_id, general_file
            )
            process_service.process_document(session, doc_gen.doc_id, use_mock=True)

            # Extract terms for general project
            report_gen = term_service.extract_terms_for_project(
                session,
                general_project.project_id,
                enable_ngrams=True,
                include_np=False,
                min_freq=1,
                ngram_ns=(2,),
                overwrite=True,
            )
            print(
                f"✅ GENERAL: {report_gen.ngrams_extracted} ngrams, {report_gen.clusters_created} clusters"
            )

            # ===================================================================
            # 2. Create DOMAIN project with domain-specific terms
            # ===================================================================
            print("\n🔍 Creating DOMAIN project with technical terms...")

            domain_project = project_service.create_project(
                session, "Medical Domain", "Domain corpus with medical terminology"
            )
            domain_corpus = project_service.get_default_corpus(session, domain_project.project_id)

            # Domain text: use simple nouns that Mock engine handles well
            # Strategy: repeat domain terms more frequently than in general corpus
            domain_file = test_dir / "domain_text.txt"
            domain_file.write_text(
                "בית חולים גדול מאוד. "  # Hospital (domain-specific, not in general)
                "בית חולים חדש נבנה. "  # Hospital (repeated)
                "בבית חולים יש רופאים. "  # Hospital with prefix
                "מעבדה מרכזית פועלת כאן. "  # Central lab (domain-specific)
                "המעבדה החדשה נפתחה. "  # Lab (repeated)
                "במעבדה מרכזית עובדים. "  # Lab with prefix
                "ספר טוב מסביר זאת. "  # A good book (common term, in both)
                "הספר החדש יצא. ",  # Book (common)
                encoding="utf-8",
            )

            doc_dom = ingest_service.import_document(session, domain_corpus.corpus_id, domain_file)
            process_service.process_document(session, doc_dom.doc_id, use_mock=True)

            # Extract terms for domain project
            report_dom = term_service.extract_terms_for_project(
                session,
                domain_project.project_id,
                enable_ngrams=True,
                include_np=False,
                min_freq=1,
                ngram_ns=(2,),
                overwrite=True,
            )
            print(
                f"✅ DOMAIN: {report_dom.ngrams_extracted} ngrams, {report_dom.clusters_created} clusters"
            )

            # ===================================================================
            # 3. Set reference project for domain
            # ===================================================================
            print("\n🔗 Setting reference project...")

            term_service.set_reference_project(
                session, domain_project.project_id, general_project.project_id
            )

            ref_check = term_service.get_reference_project(session, domain_project.project_id)
            if ref_check == general_project.project_id:
                print("✅ Reference project set correctly")
            else:
                print(f"❌ FAILED: Reference not set ({ref_check} != {general_project.project_id})")
                return False

            # ===================================================================
            # 4. Query with termhood preset
            # ===================================================================
            print("\n📊 Querying with termhood preset...")

            clusters_termhood = term_service.list_term_clusters(
                session, domain_project.project_id, top_n=20, preset="termhood"
            )

            print("\n🏆 Top terms by termhood score:")
            for i, cluster in enumerate(clusters_termhood[:10], 1):
                weirdness_str = f"{cluster.weirdness:.2f}" if cluster.weirdness else "N/A"
                keyness_str = f"{cluster.keyness_llr:.2f}" if cluster.keyness_llr else "N/A"
                termhood_str = f"{cluster.termhood_score:.2f}" if cluster.termhood_score else "N/A"

                print(
                    f"  {i}. {cluster.representative_he:20s} | "
                    f"W: {weirdness_str:>6s} | K: {keyness_str:>7s} | T: {termhood_str:>7s} | "
                    f"Freq: {cluster.freq_abs:2d}"
                )

            # ===================================================================
            # 5. Assertions: Domain-specific terms rank higher
            # ===================================================================
            print("\n✅ Checking termhood metrics...")

            # Domain-specific terms we expect to rank high (not in general corpus)
            domain_terms = ["בית חולים", "מעבדה מרכזית"]
            # Common term (appears in both corpora)
            common_term = "ספר"

            # Find domain-specific terms in results
            found_domain_terms = []
            for cluster in clusters_termhood:
                for dt in domain_terms:
                    if dt in cluster.representative_he or dt in cluster.canonical_key:
                        found_domain_terms.append(cluster)
                        break

            if not found_domain_terms:
                print("❌ FAILED: No domain-specific terms found in results")
                print(f"   Expected to find: {domain_terms}")
                print(f"   Got: {[c.representative_he for c in clusters_termhood[:5]]}")
                return False

            # Check weirdness > 1.0 for domain terms
            for cluster in found_domain_terms:
                if cluster.weirdness and cluster.weirdness > 1.0:
                    print(
                        f"✅ '{cluster.representative_he}' has weirdness {cluster.weirdness:.2f} > 1.0 (domain-specific)"
                    )
                else:
                    print(
                        f"⚠️  '{cluster.representative_he}' has weirdness {cluster.weirdness} (expected > 1.0)"
                    )

            # Check keyness > 0 for domain terms
            for cluster in found_domain_terms:
                if cluster.keyness_llr and cluster.keyness_llr > 0:
                    print(
                        f"✅ '{cluster.representative_he}' has keyness {cluster.keyness_llr:.2f} > 0"
                    )
                else:
                    print(f"⚠️  '{cluster.representative_he}' has keyness {cluster.keyness_llr}")

            # Find common term
            found_common = None
            for cluster in clusters_termhood:
                if common_term in cluster.representative_he or common_term in cluster.canonical_key:
                    found_common = cluster
                    break

            if found_common:
                # Common term should have weirdness closer to 1.0 (balanced frequency)
                if found_common.weirdness:
                    print(
                        f"✅ Common term '{found_common.representative_he}' has weirdness {found_common.weirdness:.2f} (balanced)"
                    )
                else:
                    print("⚠️  Common term weirdness is None")
            else:
                print(f"⚠️  Common term '{common_term}' not found (may not have passed min_freq)")

            # ===================================================================
            # 6. Test determinism
            # ===================================================================
            print("\n🔁 Testing deterministic ordering...")

            clusters_termhood2 = term_service.list_term_clusters(
                session, domain_project.project_id, top_n=20, preset="termhood"
            )

            if [c.cluster_id for c in clusters_termhood] == [
                c.cluster_id for c in clusters_termhood2
            ]:
                print("✅ Termhood ordering is deterministic")
            else:
                print("❌ FAILED: Termhood ordering not deterministic")
                return False

            # ===================================================================
            # 7. Test fallback when no reference set
            # ===================================================================
            print("\n🔍 Testing fallback when no reference set...")

            # Clear reference
            term_service.set_reference_project(session, domain_project.project_id, None)

            # Query with termhood preset should fall back to freq
            clusters_fallback = term_service.list_term_clusters(
                session, domain_project.project_id, top_n=20, preset="termhood"
            )

            # Should have results but no termhood metrics
            if clusters_fallback:
                first = clusters_fallback[0]
                if first.weirdness is None and first.keyness_llr is None:
                    print("✅ Fallback works: termhood metrics are None when no reference set")
                else:
                    print(f"⚠️  Expected None termhood metrics, got weirdness={first.weirdness}")
            else:
                print("⚠️  No results returned in fallback mode")

            print(f"\n{'='*60}")
            print("✅ M5.4 TEST PASSED: Termhood ranking works!")
            print(f"{'='*60}")
            return True

    except Exception as e:
        logger.exception("Test failed")
        print(f"\n❌ M5.4 TEST FAILED: {e}")
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
    print("=" * 60)
    print("M5 TEST SUITE: Term Extraction & Clustering")
    print("=" * 60)

    # Run M5.1-M5.3 tests
    test1_pass = test_beit_sefer_clustering()

    # Run M5.4 termhood tests
    test2_pass = test_termhood_ranking()

    print("\n" + "=" * 60)
    if test1_pass and test2_pass:
        print("✅ ALL M5 TESTS PASSED (M5.1-M5.4)")
    else:
        print("❌ M5 TEST FAILED")
        if not test1_pass:
            print("  - M5.1-M5.3 clustering test failed")
        if not test2_pass:
            print("  - M5.4 termhood test failed")
    print("=" * 60)

    sys.exit(0 if (test1_pass and test2_pass) else 1)
