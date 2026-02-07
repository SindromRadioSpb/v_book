#!/usr/bin/env python3
"""
PATCH-00: Benchmark Hebrew Wikipedia Reference Pipeline

Estimates runtime for:
1. "Process with NLP" (387,639 documents)
2. "Extract Terms" (387,639 documents)

Methodology:
- Select N sample documents from reference corpus (deterministic seed)
- Measure throughput (docs/sec) for NLP processing
- Measure throughput (docs/sec) for term extraction
- Extrapolate to full corpus size

Output:
- Console report with estimates
- JSON report saved to docs/BENCH_HEWIKI_PIPELINE_<timestamp>.json
- Markdown report saved to docs/BENCH_HEWIKI_PIPELINE_<timestamp>.md
"""

import argparse
import json
import logging
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import select, func
from app.infra.util.logging import setup_logging
from app.services.db_service import DBService
from app.services.process_service import ProcessService
from app.services.term_extraction_service import TermExtractionService
from app.infra.sa_models import SourceDocument, SourceCorpus, DictProject

logger = logging.getLogger(__name__)


def format_duration(seconds: float) -> str:
    """Format duration as human-readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}min"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"


def get_reference_project_docs(session, project_name: str, sample_size: int, seed: int) -> List[int]:
    """
    Get sample document IDs from reference corpus (deterministic).

    Args:
        session: Database session
        project_name: Reference project name
        sample_size: Number of docs to sample
        seed: Random seed for reproducibility

    Returns:
        List of document IDs
    """
    logger.info(f"Finding reference project: {project_name}")

    # Find project
    project = session.execute(
        select(DictProject).where(DictProject.name == project_name)
    ).scalar_one_or_none()

    if not project:
        raise ValueError(f"Project not found: {project_name}")

    logger.info(f"Found project ID={project.project_id}, is_general_corpus={project.is_general_corpus}")

    # Get all document IDs
    result = session.execute(
        select(SourceDocument.doc_id)
        .join(SourceCorpus)
        .where(SourceCorpus.project_id == project.project_id)
        .order_by(SourceDocument.doc_id)  # Deterministic ordering
    )
    all_doc_ids = [row[0] for row in result]

    total_docs = len(all_doc_ids)
    logger.info(f"Total documents in project: {total_docs:,}")

    if sample_size >= total_docs:
        logger.warning(f"Sample size ({sample_size}) >= total docs ({total_docs}), using all docs")
        return all_doc_ids

    # Deterministic sample
    random.seed(seed)
    sample_doc_ids = random.sample(all_doc_ids, sample_size)
    sample_doc_ids.sort()  # Keep sorted for consistency

    logger.info(f"Sampled {len(sample_doc_ids):,} documents (seed={seed})")
    return sample_doc_ids


def benchmark_nlp_processing(session, doc_ids: List[int], use_gpu: bool = False) -> Dict:
    """
    Benchmark NLP processing throughput.

    Args:
        session: Database session
        doc_ids: List of document IDs to process
        use_gpu: Whether to use GPU

    Returns:
        Dict with benchmark results
    """
    logger.info(f"=== BENCHMARK: NLP Processing ===")
    logger.info(f"Documents: {len(doc_ids):,}")
    logger.info(f"GPU: {use_gpu}")

    process_service = ProcessService()

    # Warm up (process 1 doc to load models)
    logger.info("Warming up NLP engine...")
    warmup_start = time.time()
    process_service.process_document(session, doc_ids[0], use_gpu=use_gpu, use_mock=False)
    warmup_duration = time.time() - warmup_start
    logger.info(f"Warmup complete: {warmup_duration:.2f}s")

    # Benchmark processing
    logger.info(f"Processing {len(doc_ids)-1:,} documents...")
    start_time = time.time()
    success_count = 0
    error_count = 0

    for i, doc_id in enumerate(doc_ids[1:], start=1):  # Skip warmup doc
        try:
            success = process_service.process_document(session, doc_id, use_gpu=use_gpu, use_mock=False)
            if success:
                success_count += 1
            else:
                error_count += 1
        except Exception as e:
            logger.error(f"Error processing doc {doc_id}: {e}")
            error_count += 1

        # Progress every 100 docs
        if i % 100 == 0:
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            logger.info(f"Progress: {i}/{len(doc_ids)-1} ({rate:.1f} docs/sec)")

    total_duration = time.time() - start_time
    throughput = (len(doc_ids) - 1) / total_duration if total_duration > 0 else 0

    result = {
        "phase": "nlp_processing",
        "sample_size": len(doc_ids) - 1,  # Exclude warmup
        "success": success_count,
        "errors": error_count,
        "duration_sec": total_duration,
        "warmup_sec": warmup_duration,
        "throughput_docs_per_sec": throughput,
        "use_gpu": use_gpu,
    }

    logger.info(f"NLP Processing complete:")
    logger.info(f"  Success: {success_count:,}")
    logger.info(f"  Errors: {error_count:,}")
    logger.info(f"  Duration: {format_duration(total_duration)}")
    logger.info(f"  Throughput: {throughput:.2f} docs/sec")

    return result


def benchmark_term_extraction(session, project_id: int, doc_ids: List[int]) -> Dict:
    """
    Benchmark term extraction throughput.

    Args:
        session: Database session
        project_id: Project ID
        doc_ids: List of document IDs (should be already processed with NLP)

    Returns:
        Dict with benchmark results
    """
    logger.info(f"=== BENCHMARK: Term Extraction ===")
    logger.info(f"Documents: {len(doc_ids):,}")

    term_service = TermExtractionService()

    # Extract terms for the project
    logger.info("Extracting terms...")
    start_time = time.time()

    report = term_service.extract_terms_for_project(session, project_id)

    total_duration = time.time() - start_time
    throughput = len(doc_ids) / total_duration if total_duration > 0 else 0

    result = {
        "phase": "term_extraction",
        "sample_size": len(doc_ids),
        "duration_sec": total_duration,
        "throughput_docs_per_sec": throughput,
        "ngrams_extracted": report.ngrams_extracted if report else 0,
        "clusters_created": report.clusters_created if report else 0,
    }

    logger.info(f"Term Extraction complete:")
    logger.info(f"  Duration: {format_duration(total_duration)}")
    logger.info(f"  Throughput: {throughput:.2f} docs/sec")
    logger.info(f"  N-grams: {result['ngrams_extracted']:,}")
    logger.info(f"  Clusters: {result['clusters_created']:,}")

    return result


def extrapolate_to_full_corpus(nlp_result: Dict, term_result: Dict, total_docs: int) -> Dict:
    """
    Extrapolate benchmark results to full corpus.

    Args:
        nlp_result: NLP benchmark results
        term_result: Term extraction benchmark results
        total_docs: Total documents in full corpus

    Returns:
        Dict with extrapolated estimates
    """
    nlp_throughput = nlp_result["throughput_docs_per_sec"]
    term_throughput = term_result["throughput_docs_per_sec"]

    nlp_estimated_sec = total_docs / nlp_throughput if nlp_throughput > 0 else float('inf')
    term_estimated_sec = total_docs / term_throughput if term_throughput > 0 else float('inf')
    total_estimated_sec = nlp_estimated_sec + term_estimated_sec

    return {
        "total_docs": total_docs,
        "nlp_processing": {
            "estimated_duration_sec": nlp_estimated_sec,
            "estimated_duration_human": format_duration(nlp_estimated_sec),
            "throughput_docs_per_sec": nlp_throughput,
        },
        "term_extraction": {
            "estimated_duration_sec": term_estimated_sec,
            "estimated_duration_human": format_duration(term_estimated_sec),
            "throughput_docs_per_sec": term_throughput,
        },
        "total_pipeline": {
            "estimated_duration_sec": total_estimated_sec,
            "estimated_duration_human": format_duration(total_estimated_sec),
        },
    }


def save_reports(benchmark_data: Dict, estimates: Dict, output_dir: Path):
    """Save benchmark reports in JSON and Markdown formats."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # JSON report
    json_path = output_dir / f"BENCH_HEWIKI_PIPELINE_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "benchmark_results": benchmark_data,
            "extrapolated_estimates": estimates,
            "timestamp": timestamp,
        }, f, indent=2, ensure_ascii=False)

    logger.info(f"JSON report saved: {json_path}")

    # Markdown report
    md_path = output_dir / f"BENCH_HEWIKI_PIPELINE_{timestamp}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Hebrew Wikipedia Pipeline Benchmark\n\n")
        f.write(f"**Date:** {timestamp}\n\n")
        f.write(f"## Sample Benchmark Results\n\n")
        f.write(f"### NLP Processing\n")
        f.write(f"- Sample size: {benchmark_data['nlp']['sample_size']:,} documents\n")
        f.write(f"- Duration: {format_duration(benchmark_data['nlp']['duration_sec'])}\n")
        f.write(f"- Throughput: {benchmark_data['nlp']['throughput_docs_per_sec']:.2f} docs/sec\n")
        f.write(f"- Success: {benchmark_data['nlp']['success']:,}\n")
        f.write(f"- Errors: {benchmark_data['nlp']['errors']}\n\n")

        f.write(f"### Term Extraction\n")
        f.write(f"- Sample size: {benchmark_data['term']['sample_size']:,} documents\n")
        f.write(f"- Duration: {format_duration(benchmark_data['term']['duration_sec'])}\n")
        f.write(f"- Throughput: {benchmark_data['term']['throughput_docs_per_sec']:.2f} docs/sec\n")
        f.write(f"- N-grams extracted: {benchmark_data['term']['ngrams_extracted']:,}\n")
        f.write(f"- Clusters created: {benchmark_data['term']['clusters_created']:,}\n\n")

        f.write(f"## Extrapolated Estimates (Full Corpus: {estimates['total_docs']:,} documents)\n\n")
        f.write(f"### NLP Processing\n")
        f.write(f"- **Estimated duration:** {estimates['nlp_processing']['estimated_duration_human']}\n")
        f.write(f"- Throughput: {estimates['nlp_processing']['throughput_docs_per_sec']:.2f} docs/sec\n\n")

        f.write(f"### Term Extraction\n")
        f.write(f"- **Estimated duration:** {estimates['term_extraction']['estimated_duration_human']}\n")
        f.write(f"- Throughput: {estimates['term_extraction']['throughput_docs_per_sec']:.2f} docs/sec\n\n")

        f.write(f"### Total Pipeline\n")
        f.write(f"- **Estimated total duration:** {estimates['total_pipeline']['estimated_duration_human']}\n\n")

        f.write(f"## Notes\n\n")
        f.write(f"- Estimates based on {benchmark_data['nlp']['sample_size']:,} sample documents\n")
        f.write(f"- Actual performance may vary based on document size, complexity, and system load\n")
        f.write(f"- GPU acceleration: {benchmark_data['nlp']['use_gpu']}\n")

    logger.info(f"Markdown report saved: {md_path}")

    return json_path, md_path


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark Hebrew Wikipedia reference pipeline"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        help="Path to database file (default: production DB)",
    )
    parser.add_argument(
        "--project-name",
        type=str,
        default="Hebrew Wikipedia Baseline",
        help="Reference project name (default: Hebrew Wikipedia Baseline)",
    )
    parser.add_argument(
        "--sample-docs",
        type=int,
        default=1000,
        help="Number of documents to sample (default: 1000)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--use-gpu",
        action="store_true",
        help="Use GPU for NLP processing",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="docs",
        help="Output directory for reports (default: docs/)",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(Path("logs"), level=logging.INFO)

    # Initialize database
    if args.db_path:
        db_path = Path(args.db_path).resolve()
    else:
        # Use production DB
        if sys.platform == "win32":
            db_path = Path(r"M:\V_book\HDLE\hdle_production_new.db")
        else:
            db_path = Path.home() / ".local" / "share" / "hdle" / "hdle.db"

    logger.info(f"Database: {db_path}")
    DBService.initialize(db_path)

    db_service = DBService.get_instance()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        with db_service.get_session() as session:
            # Get sample documents
            doc_ids = get_reference_project_docs(
                session,
                args.project_name,
                args.sample_docs,
                args.seed
            )

            # Get total doc count for extrapolation
            total_docs_result = session.execute(
                select(func.count(SourceDocument.doc_id))
                .join(SourceCorpus)
                .join(DictProject)
                .where(DictProject.name == args.project_name)
            )
            total_docs = total_docs_result.scalar()

            # Benchmark NLP processing
            nlp_result = benchmark_nlp_processing(session, doc_ids, args.use_gpu)
            session.commit()

            # Benchmark term extraction
            project = session.execute(
                select(DictProject).where(DictProject.name == args.project_name)
            ).scalar_one()

            term_result = benchmark_term_extraction(session, project.project_id, doc_ids)
            session.commit()

            # Extrapolate to full corpus
            estimates = extrapolate_to_full_corpus(nlp_result, term_result, total_docs)

            # Save reports
            benchmark_data = {
                "nlp": nlp_result,
                "term": term_result,
            }
            json_path, md_path = save_reports(benchmark_data, estimates, output_dir)

            # Print summary
            print("\n" + "="*80)
            print("BENCHMARK COMPLETE")
            print("="*80)
            print(f"\nSample Size: {args.sample_docs:,} documents")
            print(f"Total Corpus: {total_docs:,} documents")
            print(f"\nNLP Processing:")
            print(f"  Sample throughput: {nlp_result['throughput_docs_per_sec']:.2f} docs/sec")
            print(f"  Estimated for {total_docs:,} docs: {estimates['nlp_processing']['estimated_duration_human']}")
            print(f"\nTerm Extraction:")
            print(f"  Sample throughput: {term_result['throughput_docs_per_sec']:.2f} docs/sec")
            print(f"  Estimated for {total_docs:,} docs: {estimates['term_extraction']['estimated_duration_human']}")
            print(f"\nTotal Pipeline:")
            print(f"  Estimated duration: {estimates['total_pipeline']['estimated_duration_human']}")
            print(f"\nReports saved:")
            print(f"  {json_path}")
            print(f"  {md_path}")
            print("="*80)

    finally:
        DBService.shutdown()


if __name__ == "__main__":
    main()
