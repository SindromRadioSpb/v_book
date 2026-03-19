"""
Setup Hebrew Wikipedia Baseline as default reference corpus.

This script:
1. Marks "Hebrew Wikipedia Baseline" as is_general_corpus=1
2. Optionally assigns it as reference for existing projects
3. Future projects will auto-assign it via ProjectService.create_project()

Usage:
    python scripts/ref_corpora/setup_hewiki_as_default_reference.py [--assign-existing]
"""

import sys
import argparse
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import select, update
from app.infra.sa_models import DictProject
from app.services.db_service import DBService

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Setup Hebrew Wikipedia Baseline as default reference corpus"
    )
    parser.add_argument(
        "--assign-existing",
        action="store_true",
        help="Also assign HEWiki as reference for existing projects (excluding HEWiki itself)",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path("hdle_premium.db"),
        help="Path to database file (default: hdle_premium.db)",
    )
    args = parser.parse_args()

    # Initialize database
    DBService.initialize(str(args.db_path))
    logger.info(f"Using database: {args.db_path}")

    db_service = DBService.get_instance()

    with db_service.get_session() as session:
        # Find Hebrew Wikipedia Baseline project
        stmt = select(DictProject).where(DictProject.name == "Hebrew Wikipedia Baseline")
        hewiki_project = session.execute(stmt).scalar_one_or_none()

        if not hewiki_project:
            logger.error("Hebrew Wikipedia Baseline project not found!")
            logger.error(
                "Please run import first: scripts/ref_corpora/import_ref_jsonl_to_project.py"
            )
            return 1

        hewiki_id = hewiki_project.project_id
        logger.info(f"Found Hebrew Wikipedia Baseline (ID: {hewiki_id})")

        # Mark as general corpus
        if hewiki_project.is_general_corpus != 1:
            hewiki_project.is_general_corpus = 1
            session.commit()
            logger.info("✓ Marked as is_general_corpus=1")
        else:
            logger.info("✓ Already marked as is_general_corpus=1")

        # Optionally assign to existing projects
        if args.assign_existing:
            stmt = (
                update(DictProject)
                .where(
                    DictProject.project_id != hewiki_id,  # Exclude HEWiki itself
                    DictProject.general_corpus_id.is_(None),  # Only unassigned projects
                )
                .values(general_corpus_id=hewiki_id)
            )
            result = session.execute(stmt)
            session.commit()
            count = result.rowcount
            logger.info(f"✓ Assigned HEWiki as reference for {count} existing project(s)")
        else:
            # Just count how many projects would be affected
            stmt = select(DictProject).where(
                DictProject.project_id != hewiki_id, DictProject.general_corpus_id.is_(None)
            )
            projects = session.execute(stmt).scalars().all()
            if projects:
                logger.info(f"Note: {len(projects)} existing project(s) have no reference assigned")
                logger.info("Run with --assign-existing to auto-assign HEWiki to them")

    logger.info("✓ Setup complete!")
    logger.info("ℹ New projects will automatically use HEWiki as reference corpus")
    return 0


if __name__ == "__main__":
    sys.exit(main())
