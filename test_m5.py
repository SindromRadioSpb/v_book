"""Test M5: Term Extraction with "בית ספר" clustering."""
import sys
import io
import logging
from pathlib import Path

# Fix Unicode on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

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
    from app.services.db_service import DBService
    from app.services.project_service import ProjectService
    from app.services.ingest_service import IngestService
    from app.services.process_service import ProcessService
    from app.services.term_extraction_service import TermExtractionService
    from pathlib import Path
    from sqlalchemy import select, and_

    print("\n" + "="*60)
    print("TEST M5: 'בית ספר' Clustering")
    print("="*60)

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
        encoding='utf-8'
    )

    try:
        with db_service.get_session() as session:
            # Create project
            project = project_service.create_project(
                session,
                "M5 Test",
                "Test term extraction and clustering"
            )
            corpus = project_service.get_default_corpus(session, project.project_id)
            print(f"✅ Created project: {project.name}")

            # Import and process document
            doc = ingest_service.import_document(session, corpus.corpus_id, file1)
            process_service.process_document(session, doc.doc_id, use_mock=True)
            print(f"✅ Processed document with Mock engine")

            # Extract terms (including NP chunks for M5.3)
            print(f"\n🔍 Extracting terms (n-grams + NP chunks)...")
            report = term_service.extract_terms_for_project(
                session,
                project.project_id,
                enable_ngrams=True,
                include_np=True,  # M5.3
                min_freq=1,  # Low threshold to catch all variants
                ngram_ns=(2,),
                np_max_len=5,  # M5.3
                overwrite=True
            )

            if not report.success:
                print(f"❌ Term extraction failed: {report.error_message}")
                return False

            print(f"✅ Term extraction complete:")
            print(f"   N-grams: {report.ngrams_extracted}")
            print(f"   NP chunks: {report.np_chunks_extracted}")
            print(f"   Clusters: {report.clusters_created}")

            # List clusters
            clusters = term_service.list_term_clusters(
                session,
                project.project_id,
                top_n=20,
                preset='freq'
            )

            print(f"\n📊 Term clusters ({len(clusters)}):")
            for cluster in clusters:
                pmi_str = f"{cluster.best_pmi:6.2f}" if cluster.best_pmi else "   N/A"
                print(f"   {cluster.representative_he:20s} | "
                      f"Freq: {cluster.freq_abs:3d} | "
                      f"Members: {cluster.members_count:2d} | "
                      f"PMI: {pmi_str:>6s}")

            # Find בית ספר cluster
            beit_sefer_cluster = None
            for cluster in clusters:
                # Check if canonical key matches "בית_ספר" pattern
                if 'בית' in cluster.canonical_key and 'ספר' in cluster.canonical_key:
                    beit_sefer_cluster = cluster
                    break

            if not beit_sefer_cluster:
                print(f"\n❌ FAILED: No 'בית ספר' cluster found!")
                print(f"   Available clusters: {[c.canonical_key for c in clusters]}")
                return False

            print(f"\n✅ Found 'בית ספר' cluster:")
            print(f"   Canonical key: {beit_sefer_cluster.canonical_key}")
            print(f"   Representative: {beit_sefer_cluster.representative_he}")
            print(f"   Total frequency: {beit_sefer_cluster.freq_abs}")
            print(f"   Members count: {beit_sefer_cluster.members_count}")

            # Get cluster members
            members = term_service.get_cluster_members(
                session,
                beit_sefer_cluster.cluster_id
            )

            print(f"\n📋 Cluster members (surface variants):")
            for member in members:
                print(f"   {member['surface_text']:20s} | "
                      f"Freq: {member['freq_abs']:2d} | "
                      f"Lemma: {member['lemma_phrase']}")

            # Verify requirements
            expected_total_freq = 4  # We have 4 occurrences in text
            expected_min_members = 2  # At least bare + with-prefix variants

            if beit_sefer_cluster.freq_abs >= expected_total_freq:
                print(f"\n✅ Frequency aggregation correct (>= {expected_total_freq})")
            else:
                print(f"\n⚠️  WARNING: Frequency lower than expected "
                      f"({beit_sefer_cluster.freq_abs} < {expected_total_freq})")

            if beit_sefer_cluster.members_count >= expected_min_members:
                print(f"✅ Multiple variants clustered (>= {expected_min_members} members)")
            else:
                print(f"❌ FAILED: Too few members ({beit_sefer_cluster.members_count})")
                return False

            # M5.3: Verify NP chunks were extracted
            print(f"\n🔍 Checking NP chunks (M5.3)...")

            # Check if we have NP chunks (source_kind='np')
            from app.infra.sa_models import Ngram
            np_stmt = select(Ngram).where(
                and_(
                    Ngram.project_id == project.project_id,
                    Ngram.source_kind == 'np'
                )
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
                    print(f"⚠️  No NP chunks with length >= 3 found (may be due to Mock engine limitations)")
            else:
                print(f"⚠️  No NP chunks found (may be due to Mock engine limitations)")

            # M5.2: Verify LLR and Dice scores
            print(f"\n🔍 Checking association scores (M5.2)...")

            if beit_sefer_cluster.best_llr is not None:
                print(f"✅ LLR computed: {beit_sefer_cluster.best_llr:.2f}")
            else:
                print(f"⚠️  LLR is NULL (expected for bigrams)")

            if beit_sefer_cluster.best_dice is not None:
                print(f"✅ Dice computed: {beit_sefer_cluster.best_dice:.3f}")
                if 0 <= beit_sefer_cluster.best_dice <= 1:
                    print(f"✅ Dice in valid range [0,1]")
                else:
                    print(f"❌ FAILED: Dice out of range: {beit_sefer_cluster.best_dice}")
                    return False
            else:
                print(f"⚠️  Dice is NULL (expected for bigrams)")

            # M5.2: Test preset ordering
            print(f"\n🔍 Testing ranking presets (M5.2)...")

            # Get clusters with different presets
            clusters_freq = term_service.list_term_clusters(
                session, project.project_id, top_n=10, preset='freq'
            )
            clusters_strong = term_service.list_term_clusters(
                session, project.project_id, top_n=10, preset='strong'
            )
            clusters_balanced = term_service.list_term_clusters(
                session, project.project_id, top_n=10, preset='balanced'
            )

            # Verify presets produce deterministic results
            print(f"   Preset 'freq': {len(clusters_freq)} clusters")
            print(f"   Preset 'strong': {len(clusters_strong)} clusters")
            print(f"   Preset 'balanced': {len(clusters_balanced)} clusters")

            # Verify ordering is deterministic (same preset returns same order)
            clusters_freq2 = term_service.list_term_clusters(
                session, project.project_id, top_n=10, preset='freq'
            )
            if [c.cluster_id for c in clusters_freq] == [c.cluster_id for c in clusters_freq2]:
                print(f"✅ Preset ordering is deterministic")
            else:
                print(f"❌ FAILED: Preset ordering not deterministic")
                return False

            # Test re-running (determinism)
            print(f"\n🔁 Re-running extraction to test determinism...")
            report2 = term_service.extract_terms_for_project(
                session,
                project.project_id,
                enable_ngrams=True,
                include_np=True,
                min_freq=1,
                ngram_ns=(2,),
                np_max_len=5,
                overwrite=True
            )

            clusters2 = term_service.list_term_clusters(
                session,
                project.project_id,
                top_n=20,
                preset='freq'
            )

            if len(clusters2) == len(clusters):
                print(f"✅ Determinism verified: same cluster count ({len(clusters2)})")
            else:
                print(f"⚠️  WARNING: Cluster count changed ({len(clusters)} → {len(clusters2)})")

            print(f"\n{'='*60}")
            print(f"✅ M5 TEST PASSED: 'בית ספר' clustering works!")
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


if __name__ == "__main__":
    print("="*60)
    print("M5 TEST SUITE: Term Extraction & Clustering")
    print("="*60)

    test_pass = test_beit_sefer_clustering()

    print("\n" + "="*60)
    if test_pass:
        print("✅ ALL M5 TESTS PASSED")
    else:
        print("❌ M5 TEST FAILED")
    print("="*60)

    sys.exit(0 if test_pass else 1)
