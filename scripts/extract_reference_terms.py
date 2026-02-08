#!/usr/bin/env python3
"""Extract terms from reference corpus."""

import argparse
import logging
from pathlib import Path

from app.infra.util.logging import setup_logging
from app.services.db_service import DBService
from app.services.term_extraction_service import TermExtractionService
from app.infra.sa_models import DictProject
from sqlalchemy import select

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Extract terms from reference corpus")
    parser.add_argument("--db-path", type=str, required=True)
    parser.add_argument("--project-name", type=str, required=True)
    args = parser.parse_args()

    db_path = Path(args.db_path)
    setup_logging(db_path.parent / "logs", level=logging.INFO)

    DBService.initialize(db_path)
    db_service = DBService.get_instance()
    term_service = TermExtractionService()

    try:
        with db_service.get_session() as session:
            # Get project
            project = session.execute(
                select(DictProject).where(DictProject.name == args.project_name)
            ).scalar_one()

            logger.info(f"Extracting terms for project: {project.name}")

            # Extract terms
            report = term_service.extract_terms_for_project(session, project.project_id)

            logger.info(f"Term extraction complete:")
            logger.info(f"  N-grams: {report.ngrams_extracted:,}")
            logger.info(f"  Clusters: {report.clusters_created:,}")

    finally:
        DBService.shutdown()


if __name__ == "__main__":
    main()
