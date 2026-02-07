"""
Import reference corpus JSONL files into HDLE project database.

This script imports Wikipedia articles (or other reference corpora) from JSONL
shards into a project's source documents. Each JSONL record becomes a SourceDocument
with virtual file path for deduplication.

Usage:
    python scripts/ref_corpora/import_ref_jsonl_to_project.py \\
        --jsonl_files ref_corpora/hewiki/jsonl/*.jsonl \\
        --project_name "Hebrew Wikipedia Baseline" \\
        --corpus_name "HEWiki-20260201" \\
        --source_key "hewiki"

Features:
- Idempotent: Uses SHA256(source_key:doc_id) for deduplication
- Progress tracking with live stats
- Dry-run mode for preview
- Import report with detailed statistics
"""

import argparse
import json
import logging
import hashlib
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

# Add project root to path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.infra.sa_models import (
    Library,
    DictProject,
    SourceCorpus,
    SourceDocument,
    DocumentText,
)
from app.services.db_service import DBService
from app.services.project_service import ProjectService

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@dataclass
class ImportReport:
    """Import statistics report."""

    started_at: str
    ended_at: Optional[str] = None
    duration_ms: int = 0

    source_key: str = ""
    corpus_name: str = ""
    project_name: str = ""
    project_id: Optional[int] = None

    jsonl_files: List[str] = field(default_factory=list)
    total_records: int = 0
    added: int = 0
    skipped_duplicate: int = 0
    skipped_empty: int = 0
    errors: int = 0
    error_details: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "source": {
                "source_key": self.source_key,
                "corpus_name": self.corpus_name,
                "project_name": self.project_name,
                "project_id": self.project_id,
            },
            "input": {
                "jsonl_files": self.jsonl_files,
                "total_records": self.total_records,
            },
            "results": {
                "added": self.added,
                "skipped_duplicate": self.skipped_duplicate,
                "skipped_empty": self.skipped_empty,
                "errors": self.errors,
            },
            "error_details": self.error_details[:100],  # Limit to first 100 errors
        }


def compute_doc_hash(source_key: str, doc_id: str) -> str:
    """
    Compute SHA256 hash for deduplication.

    Uses format: source_key:doc_id (e.g., "hewiki:מתמטיקה")
    This ensures idempotency across re-imports.

    Args:
        source_key: Source identifier (e.g., "hewiki", "enwiki")
        doc_id: Document ID from JSONL

    Returns:
        SHA256 hex digest
    """
    unique_key = f"{source_key}:{doc_id}"
    return hashlib.sha256(unique_key.encode("utf-8")).hexdigest()


def get_or_create_corpus(
    session: Session,
    project_id: int,
    corpus_name: str,
) -> SourceCorpus:
    """
    Get existing corpus or create new one.

    Args:
        session: Database session
        project_id: Project ID
        corpus_name: Corpus name

    Returns:
        SourceCorpus instance
    """
    stmt = select(SourceCorpus).where(
        SourceCorpus.project_id == project_id,
        SourceCorpus.name == corpus_name,
    )
    corpus = session.execute(stmt).scalar_one_or_none()

    if corpus is None:
        corpus = SourceCorpus(
            project_id=project_id,
            name=corpus_name,
            description=f"Reference corpus: {corpus_name}",
        )
        session.add(corpus)
        session.flush()
        logger.info(f"Created corpus: {corpus_name} (ID: {corpus.corpus_id})")
    else:
        logger.info(f"Using existing corpus: {corpus_name} (ID: {corpus.corpus_id})")

    return corpus


def import_jsonl_record(
    session: Session,
    corpus_id: int,
    record: Dict[str, Any],
    source_key: str,
    dry_run: bool = False,
) -> Tuple[bool, str]:
    """
    Import a single JSONL record as SourceDocument.

    Args:
        session: Database session
        corpus_id: Corpus ID
        record: JSONL record (dict with doc_id, title, text, url, etc.)
        source_key: Source identifier (e.g., "hewiki")
        dry_run: If True, skip actual DB operations

    Returns:
        Tuple of (success: bool, status: str)
        Status values: "added", "skipped_duplicate", "skipped_empty", "error:<msg>"
    """
    try:
        # Extract fields from JSONL
        doc_id = record.get("doc_id") or record.get("id") or ""
        title = record.get("title") or ""
        text = record.get("text") or ""
        url = record.get("url") or ""
        language = record.get("language") or ""

        if not doc_id or not text.strip():
            return False, "skipped_empty"

        # Compute deduplication hash
        doc_hash = compute_doc_hash(source_key, doc_id)

        # Check for duplicates
        stmt = select(SourceDocument).where(
            SourceDocument.corpus_id == corpus_id,
            SourceDocument.sha256 == doc_hash,
        )
        existing = session.execute(stmt).scalar_one_or_none()

        if existing:
            logger.debug(f"Duplicate: {title} (hash: {doc_hash[:16]}...)")
            return False, "skipped_duplicate"

        if dry_run:
            logger.info(f"[DRY RUN] Would import: {title} ({len(text)} chars)")
            return True, "added"

        # Create virtual file path: source_key:doc_id
        virtual_path = f"{source_key}:{doc_id}"

        # Create SourceDocument
        doc = SourceDocument(
            corpus_id=corpus_id,
            file_path=virtual_path,
            file_name=title or doc_id,
            file_ext=".wiki",
            file_size_bytes=len(text.encode("utf-8")),
            sha256=doc_hash,
            file_mtime_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            status="imported",
        )
        session.add(doc)
        session.flush()  # Get doc_id

        # Create DocumentText
        doc_text = DocumentText(
            doc_id=doc.doc_id,
            raw_text=text,
            ocr_used=0,
        )
        session.add(doc_text)

        logger.debug(
            f"Imported: {title} (doc_id={doc.doc_id}, {len(text)} chars, hash={doc_hash[:16]}...)"
        )
        return True, "added"

    except Exception as e:
        logger.exception(f"Error importing record: {record.get('title', 'UNKNOWN')}")
        return False, f"error:{str(e)}"


def import_jsonl_files(
    session: Session,
    jsonl_files: List[Path],
    project_id: int,
    corpus_name: str,
    source_key: str,
    dry_run: bool = False,
    commit_every: int = 100,
) -> ImportReport:
    """
    Import multiple JSONL files into project.

    Args:
        session: Database session
        jsonl_files: List of JSONL file paths
        project_id: Target project ID
        corpus_name: Corpus name
        source_key: Source identifier (e.g., "hewiki")
        dry_run: If True, preview without committing
        commit_every: Commit frequency for large imports

    Returns:
        ImportReport with statistics
    """
    started_at = datetime.now(timezone.utc)
    report = ImportReport(
        started_at=started_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        source_key=source_key,
        corpus_name=corpus_name,
        project_id=project_id,
        jsonl_files=[str(f) for f in jsonl_files],
    )

    # Get or create corpus
    corpus = get_or_create_corpus(session, project_id, corpus_name)

    # Import records
    pending_commits = 0

    for jsonl_file in jsonl_files:
        logger.info(f"Processing: {jsonl_file.name}")

        if not jsonl_file.exists():
            logger.warning(f"File not found: {jsonl_file}")
            report.errors += 1
            report.error_details.append({"file": str(jsonl_file), "error": "File not found"})
            continue

        try:
            with open(jsonl_file, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue

                    report.total_records += 1

                    try:
                        record = json.loads(line)
                        success, status = import_jsonl_record(
                            session, corpus.corpus_id, record, source_key, dry_run
                        )

                        if status == "added":
                            report.added += 1
                            pending_commits += 1
                        elif status == "skipped_duplicate":
                            report.skipped_duplicate += 1
                        elif status == "skipped_empty":
                            report.skipped_empty += 1
                        elif status.startswith("error:"):
                            report.errors += 1
                            report.error_details.append({
                                "file": str(jsonl_file),
                                "line": line_num,
                                "error": status[6:],  # Remove "error:" prefix
                            })

                        # Commit periodically
                        if not dry_run and pending_commits >= commit_every:
                            session.commit()
                            pending_commits = 0
                            logger.info(
                                f"Progress: {report.added} added, "
                                f"{report.skipped_duplicate} duplicates, "
                                f"{report.errors} errors"
                            )

                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON at {jsonl_file.name}:{line_num}: {e}")
                        report.errors += 1
                        report.error_details.append({
                            "file": str(jsonl_file),
                            "line": line_num,
                            "error": f"JSON parse error: {e}",
                        })

        except Exception as e:
            logger.exception(f"Error processing file: {jsonl_file}")
            report.errors += 1
            report.error_details.append({"file": str(jsonl_file), "error": str(e)})

    # Final commit
    if not dry_run and pending_commits > 0:
        session.commit()

    ended_at = datetime.now(timezone.utc)
    report.ended_at = ended_at.isoformat(timespec="seconds").replace("+00:00", "Z")
    report.duration_ms = int((ended_at - started_at).total_seconds() * 1000)

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Import reference corpus JSONL files into HDLE project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Import all hewiki shards into new project
  python scripts/ref_corpora/import_ref_jsonl_to_project.py \\
      --jsonl_files ref_corpora/hewiki/jsonl/*.jsonl \\
      --project_name "Hebrew Wikipedia" \\
      --corpus_name "HEWiki-20260201" \\
      --source_key "hewiki"

  # Import into existing project (dry run first)
  python scripts/ref_corpora/import_ref_jsonl_to_project.py \\
      --jsonl_files ref_corpora/hewiki/jsonl/shard_00000.jsonl \\
      --project_id 5 \\
      --corpus_name "Test Corpus" \\
      --source_key "hewiki" \\
      --dry_run

  # Import with custom database
  python scripts/ref_corpora/import_ref_jsonl_to_project.py \\
      --jsonl_files ref_corpora/hewiki/jsonl/*.jsonl \\
      --project_name "HEWiki" \\
      --source_key "hewiki" \\
      --db_path /path/to/custom.db
        """,
    )

    parser.add_argument(
        "--jsonl_files",
        nargs="+",
        required=True,
        help="JSONL shard file(s) to import (supports glob patterns)",
    )
    parser.add_argument(
        "--project_id",
        type=int,
        help="Existing project ID (mutually exclusive with --project_name)",
    )
    parser.add_argument(
        "--project_name",
        help="Project name to create or use (mutually exclusive with --project_id)",
    )
    parser.add_argument(
        "--corpus_name",
        required=True,
        help="Corpus name for imported documents (e.g., 'HEWiki-20260201')",
    )
    parser.add_argument(
        "--source_key",
        required=True,
        help="Source identifier for deduplication (e.g., 'hewiki', 'enwiki')",
    )
    parser.add_argument(
        "--db_path",
        type=Path,
        help="Path to HDLE database (defaults to app's configured database)",
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="Preview import without committing to database",
    )
    parser.add_argument(
        "--commit_every",
        type=int,
        default=100,
        help="Commit frequency for large imports (default: 100)",
    )
    parser.add_argument(
        "--report_path",
        type=Path,
        help="Save import report to JSON file",
    )

    args = parser.parse_args()

    # Validate arguments
    if args.project_id and args.project_name:
        parser.error("--project_id and --project_name are mutually exclusive")
    if not args.project_id and not args.project_name:
        parser.error("Either --project_id or --project_name is required")

    # Resolve JSONL file paths (expand globs if needed)
    jsonl_files = []
    for pattern in args.jsonl_files:
        path = Path(pattern)
        if path.exists() and path.is_file():
            jsonl_files.append(path)
        else:
            # Try glob expansion
            matched = list(Path(".").glob(pattern))
            if not matched:
                logger.warning(f"No files matched pattern: {pattern}")
            jsonl_files.extend(matched)

    if not jsonl_files:
        logger.error("No JSONL files found")
        return 1

    logger.info(f"Found {len(jsonl_files)} JSONL file(s)")

    # Initialize database
    if args.db_path:
        DBService.initialize(str(args.db_path))
        logger.info(f"Using database: {args.db_path}")
    else:
        # Use default database path (create in current directory if not specified)
        default_db = Path("hdle_premium.db")
        DBService.initialize(str(default_db))
        logger.info(f"Using database: {default_db.absolute()}")

    db_service = DBService.get_instance()

    # Get or create project
    with db_service.get_session() as session:
        project_service = ProjectService()

        if args.project_id:
            project = project_service.get_project(session, args.project_id)
            if not project:
                logger.error(f"Project not found: {args.project_id}")
                return 1
            logger.info(f"Using existing project: {project.name} (ID: {project.project_id})")
        else:
            # Check if project exists
            stmt = select(DictProject).where(DictProject.name == args.project_name)
            project = session.execute(stmt).scalar_one_or_none()

            if project:
                logger.info(f"Using existing project: {project.name} (ID: {project.project_id})")
            else:
                project = project_service.create_project(
                    session,
                    name=args.project_name,
                    description=f"Reference corpus: {args.source_key}",
                )
                logger.info(f"Created project: {project.name} (ID: {project.project_id})")

        # Set project name for report
        project_name = project.name

        # Import JSONL files
        logger.info("Starting import...")
        if args.dry_run:
            logger.info("DRY RUN MODE - No changes will be committed")

        report = import_jsonl_files(
            session,
            jsonl_files,
            project.project_id,
            args.corpus_name,
            args.source_key,
            dry_run=args.dry_run,
            commit_every=args.commit_every,
        )
        report.project_name = project_name

    # Print summary
    logger.info("=" * 60)
    logger.info("IMPORT COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Project: {report.project_name} (ID: {report.project_id})")
    logger.info(f"Corpus: {report.corpus_name}")
    logger.info(f"Source: {report.source_key}")
    logger.info(f"Duration: {report.duration_ms / 1000:.2f}s")
    logger.info("-" * 60)
    logger.info(f"Total records: {report.total_records}")
    logger.info(f"✓ Added: {report.added}")
    logger.info(f"○ Skipped (duplicate): {report.skipped_duplicate}")
    logger.info(f"○ Skipped (empty): {report.skipped_empty}")
    logger.info(f"✗ Errors: {report.errors}")

    if report.errors > 0:
        logger.warning(f"Errors encountered: {report.errors}")
        logger.warning(f"First few errors: {report.error_details[:5]}")

    # Save report
    if args.report_path:
        with open(args.report_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info(f"Report saved: {args.report_path}")

    return 0 if report.errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
