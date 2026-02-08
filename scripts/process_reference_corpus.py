#!/usr/bin/env python3
"""Process reference corpus with NLP pipeline."""

import argparse
import logging
from pathlib import Path

from app.infra.util.logging import setup_logging
from app.services.db_service import DBService
from app.services.process_service import ProcessService
from app.infra.sa_models import SourceDocument, SourceCorpus, DictProject
from sqlalchemy import select

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Process reference corpus with NLP")
    parser.add_argument("--db-path", type=str, required=True)
    parser.add_argument("--project-name", type=str, required=True)
    parser.add_argument("--use-gpu", action="store_true")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()

    db_path = Path(args.db_path)
    setup_logging(db_path.parent / "logs", level=logging.INFO)

    DBService.initialize(db_path)
    db_service = DBService.get_instance()
    process_service = ProcessService()

    try:
        with db_service.get_session() as session:
            # Get project
            project = session.execute(
                select(DictProject).where(DictProject.name == args.project_name)
            ).scalar_one()

            # Count total and processed documents
            from sqlalchemy import func
            total_all = session.execute(
                select(func.count(SourceDocument.doc_id))
                .join(SourceCorpus)
                .where(SourceCorpus.project_id == project.project_id)
            ).scalar()

            already_processed = session.execute(
                select(func.count(SourceDocument.doc_id))
                .join(SourceCorpus)
                .where(SourceCorpus.project_id == project.project_id)
                .where(SourceDocument.status == 'processed')
            ).scalar()

            # Get only UNPROCESSED documents
            docs = session.execute(
                select(SourceDocument.doc_id)
                .join(SourceCorpus)
                .where(SourceCorpus.project_id == project.project_id)
                .where(SourceDocument.status != 'processed')  # Skip already processed
                .order_by(SourceDocument.doc_id)
            ).scalars().all()

            total = len(docs)
            logger.info(f"Total documents: {total_all:,}")
            logger.info(f"Already processed: {already_processed:,} ({already_processed/total_all*100:.1f}%)")
            logger.info(f"To process: {total:,} ({total/total_all*100:.1f}%)")
            logger.info(f"GPU: {args.use_gpu}")

            if total == 0:
                logger.info("All documents already processed!")
                return

            processed_count = 0
            for i, doc_id in enumerate(docs, 1):
                try:
                    process_service.process_document(
                        session, doc_id, use_gpu=args.use_gpu
                    )
                    session.commit()
                    processed_count += 1

                    if processed_count % args.batch_size == 0:
                        overall_progress = (already_processed + processed_count) / total_all * 100
                        logger.info(
                            f"Progress: {processed_count:,}/{total:,} this run "
                            f"| Overall: {already_processed + processed_count:,}/{total_all:,} ({overall_progress:.1f}%)"
                        )

                except Exception as e:
                    logger.error(f"Error processing doc {doc_id}: {e}")
                    session.rollback()

            logger.info(f"NLP processing complete: {processed_count:,} documents processed in this run")
            logger.info(f"Overall: {already_processed + processed_count:,}/{total_all:,} documents processed")

    finally:
        DBService.shutdown()


if __name__ == "__main__":
    main()
