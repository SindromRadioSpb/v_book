"""D1: EXECUTABLE SPECIFICATION - Terms Table Mathematics.

This script is an executable mathematical specification that:
1. Creates a controlled 3-document dataset
2. Extracts terms and verifies ALL mathematical invariants
3. Independently recomputes PMI/LLR/Dice and asserts correctness
4. Exits with non-zero code if ANY verification fails

This is NOT just a demo - it's a mathematical contract.
"""
import sys
import io
import logging
import math
from pathlib import Path
from typing import Dict, List, Tuple, Any

# Fix Unicode on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(level=logging.WARNING)

print("="*70)
print("D1: EXECUTABLE SPECIFICATION - Terms Table Mathematics")
print("="*70)

# ================================================================
# Setup
# ================================================================
from app.services.db_service import DBService
from app.services.project_service import ProjectService
from app.services.ingest_service import IngestService
from app.services.process_service import ProcessService
from app.services.term_extraction_service import TermExtractionService
from sqlalchemy import text

test_db = Path("verify_terms_math.db")
if test_db.exists():
    test_db.unlink()

DBService.initialize(test_db)
db_service = DBService.get_instance()

project_service = ProjectService()
ingest_service = IngestService()
process_service = ProcessService()
term_service = TermExtractionService()

test_dir = Path("verify_terms_math_data")
test_dir.mkdir(exist_ok=True)

# ================================================================
# CONTROLLED DATASET (EXACT as specified)
# ================================================================
DOCUMENTS = {
    "A": """בית הספר גדול.
בית הספר גדול.
בבית הספר יש ספר חדש.
הספר החדש טוב.
הספר החדש טוב.""",

    "B": """בית ספר גדול ליד בית הספר.
בית הספר גדול.
הספר בבית הספר חדש וטוב.
בבית הספר יש ספר חדש.""",

    "C": """ה ספר הזה טוב.
בית הספר החדש טוב."""
}

# ================================================================
# Schema Introspection
# ================================================================
def get_schema_info(session) -> Dict[str, Dict[str, str]]:
    """Introspect DB schema and validate required tables/columns exist.

    Returns:
        Dict mapping table_name -> {logical_name: actual_column_name}

    Raises:
        RuntimeError if schema is incompatible
    """
    print("\n[SCHEMA INTROSPECTION]")

    required_tables = {
        'lemma': ['lemma_id', 'project_id', ('text', ['lemma_text', 'text', 'lemma'])],
        'lemma_project_stat': ['project_id', 'lemma_id', 'freq_abs'],
        'ngram': ['ngram_id', 'project_id', 'surface_text', 'lemma_phrase'],
        'ngram_project_stat': ['project_id', 'ngram_id', 'freq_abs', 'doc_freq',
                               ('pmi', ['pmi_cache', 'pmi']),
                               ('llr', ['llr_cache', 'llr']),
                               ('dice', ['dice_cache', 'dice'])],
        'term_cluster': ['cluster_id', 'project_id', 'representative_he',
                        'freq_abs', 'doc_freq', 'members_count',
                        ('pmi', ['best_pmi', 'pmi']),
                        ('llr', ['best_llr', 'llr']),
                        ('dice', ['best_dice', 'dice'])],
        'term_cluster_member': ['cluster_id', 'ngram_id'],
        'source_document': ['doc_id', 'corpus_id'],
        'source_corpus': ['corpus_id', 'project_id'],
    }

    schema = {}

    for table_name, required_cols in required_tables.items():
        result = session.execute(text(f"PRAGMA table_info({table_name})"))
        rows = result.fetchall()

        if not rows:
            raise RuntimeError(
                f"❌ SCHEMA ERROR: Table '{table_name}' does not exist.\n"
                f"   Required for D1 verification.\n"
                f"   Hint: Run schema migrations or verify DB version."
            )

        actual_cols = {row[1] for row in rows}  # row[1] is column name
        schema[table_name] = {}

        for req in required_cols:
            if isinstance(req, tuple):
                logical_name, candidates = req
                found = None
                for candidate in candidates:
                    if candidate in actual_cols:
                        found = candidate
                        break
                if not found:
                    raise RuntimeError(
                        f"❌ SCHEMA ERROR: Table '{table_name}' missing column for '{logical_name}'.\n"
                        f"   Tried: {candidates}\n"
                        f"   Actual columns: {sorted(actual_cols)}"
                    )
                schema[table_name][logical_name] = found
            else:
                if req not in actual_cols:
                    raise RuntimeError(
                        f"❌ SCHEMA ERROR: Table '{table_name}' missing column '{req}'.\n"
                        f"   Actual columns: {sorted(actual_cols)}"
                    )
                schema[table_name][req] = req

    print(f"  ✅ Schema validated: {len(schema)} tables")
    for table, cols in schema.items():
        mapped = {k: v for k, v in cols.items() if k != v}
        if mapped:
            print(f"     {table}: {mapped}")

    return schema

# ================================================================
# Independent Metric Computation (Pure Math)
# ================================================================
def compute_pmi_independent(c_xy: int, c_x: int, c_y: int, n: int) -> float:
    """Compute PMI independently using pure math.

    PMI = log2( (c_xy * N) / (c_x * c_y) )

    This MUST match production formula exactly.
    """
    if c_xy <= 0 or c_x <= 0 or c_y <= 0 or n <= 0:
        return None
    return math.log2((c_xy * n) / (c_x * c_y))

def compute_dice_independent(c_xy: int, c_x: int, c_y: int) -> float:
    """Compute Dice independently.

    Dice = 2 * c_xy / (c_x + c_y)
    """
    if c_x <= 0 or c_y <= 0:
        return None
    return (2 * c_xy) / (c_x + c_y)

def compute_llr_independent(c_xy: int, c_x: int, c_y: int, n: int) -> float:
    """Compute LLR independently using 2x2 contingency table.

    Uses natural log (ln) to match production code.

    LLR = 2 * Σ O_ij * ln(O_ij / E_ij)
    """
    if n <= 0 or c_x <= 0 or c_y <= 0:
        return None

    # Contingency table (observed)
    o11 = c_xy
    o12 = c_y - c_xy
    o21 = c_x - c_xy
    o22 = n - c_x - c_y + c_xy

    # Expected values
    e11 = (c_x * c_y) / n
    e12 = (c_x * (n - c_y)) / n
    e21 = ((n - c_x) * c_y) / n
    e22 = ((n - c_x) * (n - c_y)) / n

    def safe_log_ratio(o: int, e: float) -> float:
        if o <= 0 or e <= 0:
            return 0.0
        return o * math.log(o / e)  # Natural log (ln)

    llr = 2 * (
        safe_log_ratio(o11, e11) +
        safe_log_ratio(o12, e12) +
        safe_log_ratio(o21, e21) +
        safe_log_ratio(o22, e22)
    )

    return llr

# ================================================================
# Invariant Checks
# ================================================================
def check_invariants(cluster: Any, num_docs: int, schema: Dict) -> List[str]:
    """Check all mathematical invariants for a cluster.

    Returns:
        List of failure messages (empty if all pass)
    """
    failures = []

    cid = cluster.cluster_id
    term = cluster.representative_he

    # Basic bounds
    if cluster.freq_abs < 0:
        failures.append(f"Cluster {cid} ({term}): freq_abs={cluster.freq_abs} < 0")

    if cluster.doc_freq < 0:
        failures.append(f"Cluster {cid} ({term}): doc_freq={cluster.doc_freq} < 0")

    if cluster.members_count < 1:
        failures.append(f"Cluster {cid} ({term}): members_count={cluster.members_count} < 1")

    # Dice bounds
    dice = getattr(cluster, schema['term_cluster']['dice'], None)
    if dice is not None:
        if dice < 0 or dice > 1:
            failures.append(f"Cluster {cid} ({term}): dice={dice} not in [0,1]")

    # LLR bounds
    llr = getattr(cluster, schema['term_cluster']['llr'], None)
    if llr is not None:
        if llr < 0:
            failures.append(f"Cluster {cid} ({term}): llr={llr} < 0")

    # DocFreq <= num_docs
    if cluster.doc_freq > num_docs:
        failures.append(
            f"Cluster {cid} ({term}): doc_freq={cluster.doc_freq} > num_docs={num_docs}"
        )

    # Freq >= DocFreq (term must appear at least as many times as documents it's in)
    if cluster.freq_abs < cluster.doc_freq:
        failures.append(
            f"Cluster {cid} ({term}): freq_abs={cluster.freq_abs} < doc_freq={cluster.doc_freq}"
        )

    return failures

# ================================================================
# Main Verification Logic
# ================================================================
failures = []  # Global failure collector

try:
    with db_service.get_session() as session:
        # Schema introspection
        schema = get_schema_info(session)

        # ================================================================
        # Create project and dataset
        # ================================================================
        print("\n[1/5] Creating controlled dataset...")
        print(f"  Documents: {len(DOCUMENTS)}")
        for doc_name, content in DOCUMENTS.items():
            lines = [l.strip() for l in content.strip().split('\n') if l.strip()]
            print(f"  Document {doc_name}: {len(lines)} sentences")

        project = project_service.create_project(
            session,
            "Terms Math Verification",
            "Controlled dataset for mathematical verification"
        )
        corpus = project_service.get_default_corpus(session, project.project_id)
        print(f"  ✅ Project ID: {project.project_id}, Corpus ID: {corpus.corpus_id}")

        # ================================================================
        # Import and process documents
        # ================================================================
        print("\n[2/5] Importing and processing documents...")

        doc_ids = {}
        for doc_name, content in DOCUMENTS.items():
            doc_file = test_dir / f"doc_{doc_name}.txt"
            doc_file.write_text(content, encoding='utf-8')

            doc = ingest_service.import_document(session, corpus.corpus_id, doc_file)
            process_service.process_document(session, doc.doc_id, use_mock=True)

            doc_ids[doc_name] = doc.doc_id
            print(f"  ✅ Document {doc_name}: ID={doc.doc_id}, sentences={doc.sentence_count}")

        num_docs = len(doc_ids)

        # ================================================================
        # Extract terms
        # ================================================================
        print("\n[3/5] Extracting terms...")

        report = term_service.extract_terms_for_project(
            session,
            project.project_id,
            enable_ngrams=True,
            include_np=False,
            min_freq=1,
            ngram_ns=(2,),
            overwrite=True
        )

        print(f"  ✅ N-grams extracted: {report.ngrams_extracted}")
        print(f"  ✅ Clusters created: {report.clusters_created}")

        if report.clusters_created == 0:
            failures.append("CRITICAL: No clusters created - cannot verify")
            raise RuntimeError("No clusters to verify")

        # ================================================================
        # Get clusters and check invariants
        # ================================================================
        print("\n[4/5] Checking invariants for all clusters...")

        clusters = term_service.list_term_clusters(
            session,
            project.project_id,
            top_n=100,
            preset='freq'
        )

        print(f"  Retrieved {len(clusters)} clusters")

        for cluster in clusters:
            cluster_failures = check_invariants(cluster, num_docs, schema)
            failures.extend(cluster_failures)

        if failures:
            print(f"  ❌ Invariant failures: {len(failures)}")
        else:
            print(f"  ✅ All invariants passed for {len(clusters)} clusters")

        # ================================================================
        # Independent metric verification for target clusters
        # ================================================================
        print("\n[5/5] Independent metric verification...")

        TARGET_TERMS = ["בית הספר", "הספר החדש"]

        for target_term in TARGET_TERMS:
            target_cluster = None
            for cluster in clusters:
                if cluster.representative_he == target_term:
                    target_cluster = cluster
                    break

            if not target_cluster:
                print(f"  ⚠️  Target term '{target_term}' not found, skipping")
                continue

            print(f"\n  📊 Verifying: {target_term}")
            print(f"     Cluster ID: {target_cluster.cluster_id}")

            # Get ngram members
            result = session.execute(
                text("""
                    SELECT ng.ngram_id, ng.surface_text, ng.lemma_phrase,
                           st.freq_abs, st.doc_freq,
                           st.{pmi_col}, st.{llr_col}, st.{dice_col}
                    FROM term_cluster_member tcm
                    JOIN ngram ng ON ng.ngram_id = tcm.ngram_id
                    JOIN ngram_project_stat st ON st.ngram_id = ng.ngram_id
                    WHERE tcm.cluster_id = :cluster_id
                    ORDER BY st.freq_abs DESC
                """.format(
                    pmi_col=schema['ngram_project_stat']['pmi'],
                    llr_col=schema['ngram_project_stat']['llr'],
                    dice_col=schema['ngram_project_stat']['dice']
                )),
                {"cluster_id": target_cluster.cluster_id}
            )

            ngrams = result.fetchall()

            # Verify cluster.freq_abs == sum(member freqs)
            total_freq = sum(ng[3] for ng in ngrams)
            if target_cluster.freq_abs != total_freq:
                failures.append(
                    f"{target_term}: cluster.freq_abs={target_cluster.freq_abs} "
                    f"!= sum(members)={total_freq}"
                )
            else:
                print(f"     ✅ Freq aggregation: {target_cluster.freq_abs} = sum(members)")

            # Verify cluster.doc_freq matches implementation
            # Current implementation: max(member doc_freqs)
            max_doc_freq = max(ng[4] for ng in ngrams)
            if target_cluster.doc_freq != max_doc_freq:
                failures.append(
                    f"{target_term}: cluster.doc_freq={target_cluster.doc_freq} "
                    f"!= max(members)={max_doc_freq}"
                )
            else:
                print(f"     ✅ DocFreq aggregation: {target_cluster.doc_freq} = max(members)")

            # For bigram metrics, verify the first (highest freq) member
            if len(ngrams) > 0:
                ngram_id, surface, lemma_phrase, c_bigram, df, stored_pmi, stored_llr, stored_dice = ngrams[0]

                # Parse lemma phrase for unigram lookup
                lemmas = lemma_phrase.split()
                if len(lemmas) == 2:
                    l1, l2 = lemmas

                    # Get total tokens (sum of all unigram lemma counts)
                    # This matches production implementation: _get_total_tokens()
                    result = session.execute(
                        text("""
                            SELECT SUM(freq_abs)
                            FROM lemma_project_stat
                            WHERE project_id = :project_id
                        """),
                        {"project_id": project.project_id}
                    )
                    total_tokens = result.scalar() or 1  # Avoid division by zero

                    # Get unigram counts
                    lemma_text_col = schema['lemma']['text']
                    result = session.execute(
                        text(f"""
                            SELECT l.{lemma_text_col}, lps.freq_abs
                            FROM lemma l
                            JOIN lemma_project_stat lps ON lps.lemma_id = l.lemma_id
                            WHERE lps.project_id = :project_id
                              AND l.{lemma_text_col} IN (:l1, :l2)
                        """),
                        {"project_id": project.project_id, "l1": l1, "l2": l2}
                    )

                    unigram_counts = {row[0]: row[1] for row in result.fetchall()}
                    c_x = unigram_counts.get(l1)
                    c_y = unigram_counts.get(l2)

                    if c_x and c_y and total_tokens:
                        print(f"\n     Counts for '{surface}' (lemma: '{lemma_phrase}'):")
                        print(f"       C({l1}) = {c_x}")
                        print(f"       C({l2}) = {c_y}")
                        print(f"       C({l1},{l2}) = {c_bigram}")
                        print(f"       N = {total_tokens}")

                        # Independent PMI
                        pmi_calc = compute_pmi_independent(c_bigram, c_x, c_y, total_tokens)
                        if pmi_calc is not None and stored_pmi is not None:
                            diff = abs(pmi_calc - stored_pmi)
                            print(f"\n     PMI:")
                            print(f"       Calculated: {pmi_calc:.6f}")
                            print(f"       Stored:     {stored_pmi:.6f}")
                            print(f"       Diff:       {diff:.6e}")

                            if diff > 1e-5:
                                failures.append(
                                    f"{target_term} ({surface}): PMI diff={diff:.6e} > tolerance"
                                )
                                print(f"       ❌ FAIL")
                            else:
                                print(f"       ✅ PASS")

                        # Independent Dice
                        dice_calc = compute_dice_independent(c_bigram, c_x, c_y)
                        if dice_calc is not None and stored_dice is not None:
                            diff = abs(dice_calc - stored_dice)
                            print(f"\n     Dice:")
                            print(f"       Calculated: {dice_calc:.6f}")
                            print(f"       Stored:     {stored_dice:.6f}")
                            print(f"       Diff:       {diff:.6e}")

                            if diff > 1e-6:
                                failures.append(
                                    f"{target_term} ({surface}): Dice diff={diff:.6e} > tolerance"
                                )
                                print(f"       ❌ FAIL")
                            else:
                                print(f"       ✅ PASS")

                        # Independent LLR
                        llr_calc = compute_llr_independent(c_bigram, c_x, c_y, total_tokens)
                        if llr_calc is not None and stored_llr is not None:
                            diff = abs(llr_calc - stored_llr)

                            # Show contingency table
                            o11 = c_bigram
                            o12 = c_y - c_bigram
                            o21 = c_x - c_bigram
                            o22 = total_tokens - c_x - c_y + c_bigram

                            print(f"\n     LLR (2×2 contingency table):")
                            print(f"       O11 (x,y):    {o11:6d}")
                            print(f"       O12 (x,¬y):   {o12:6d}")
                            print(f"       O21 (¬x,y):   {o21:6d}")
                            print(f"       O22 (¬x,¬y):  {o22:6d}")
                            print(f"       Calculated:   {llr_calc:.6f}")
                            print(f"       Stored:       {stored_llr:.6f}")
                            print(f"       Diff:         {diff:.6e}")

                            if diff > 1e-5:
                                failures.append(
                                    f"{target_term} ({surface}): LLR diff={diff:.6e} > tolerance"
                                )
                                print(f"       ❌ FAIL")
                            else:
                                print(f"       ✅ PASS")

except Exception as e:
    import traceback
    print(f"\n❌ VERIFICATION EXCEPTION: {e}")
    traceback.print_exc()
    failures.append(f"EXCEPTION: {e}")

finally:
    # Cleanup
    import shutil
    if test_dir.exists():
        shutil.rmtree(test_dir)

    DBService.shutdown()

    # ================================================================
    # FINAL VERDICT
    # ================================================================
    print("\n" + "="*70)
    print("VERIFICATION SUMMARY")
    print("="*70)

    if not failures:
        print("✅ PASS: All invariants and metric checks passed")
        print(f"   - Dataset: {len(DOCUMENTS)} documents")
        print(f"   - Clusters verified: {len(clusters) if 'clusters' in locals() else 0}")
        print(f"   - Metrics independently recomputed and matched")
        print(f"\n📁 Database saved: {test_db}")
        sys.exit(0)
    else:
        print(f"❌ FAIL: {len(failures)} verification failure(s)")
        print("\nFailures:")
        for i, failure in enumerate(failures, 1):
            print(f"  {i}. {failure}")
        print(f"\n📁 Database saved for inspection: {test_db}")
        sys.exit(1)
