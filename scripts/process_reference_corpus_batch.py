#!/usr/bin/env python3
"""Process reference corpus with NLP pipeline - Batch optimized version.

This script fixes the database locking issue by:
1. Creating ONE ProcessorRun for the entire batch
2. Committing only after each successful document (not multiple times per doc)
3. Using proper transaction management
"""

import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
from typing import Dict

from app.infra.util.logging import setup_logging
from app.services.db_service import DBService
from app.infra.sa_models import (
    SourceDocument,
    SourceCorpus,
    DictProject,
    DocumentText,
    DocumentSentence,
    Lemma,
    LemmaDocStat,
    LemmaProjectStat,
    ProcessorRun,
    RunError,
)
from app.domain.preprocessing import preprocess_text
from app.domain.sentence_splitter import split_into_sentences
from sqlalchemy import select, func

logger = logging.getLogger(__name__)


def process_document_no_run(session, doc_id, engine, project_id) -> tuple[bool, int, int]:
    """
    Process a single document WITHOUT creating a ProcessorRun.

    Returns:
        (success, total_tokens, unique_lemmas)
    """
    # Get document
    doc = session.get(SourceDocument, doc_id)
    if not doc:
        logger.error(f"Document not found: {doc_id}")
        return False, 0, 0

    try:
        # Update status
        doc.status = "processing"
        session.flush()  # Don't commit yet

        # Get raw text
        doc_text = session.get(DocumentText, doc_id)
        if not doc_text or not doc_text.raw_text:
            raise ValueError("No text available for document")

        raw_text = doc_text.raw_text

        # Preprocess
        cleaned_text = preprocess_text(raw_text)
        doc_text.cleaned_text = cleaned_text
        session.flush()  # Don't commit yet

        # Split into sentences
        sentence_texts = split_into_sentences(cleaned_text)

        # Store sentences
        for sent_index, sent_text in enumerate(sentence_texts):
            sent = DocumentSentence(
                doc_id=doc_id,
                sent_index=sent_index,
                text=sent_text,
            )
            session.add(sent)

        session.flush()

        # NLP processing
        lemma_counter: Counter = Counter()
        lemma_pos_map: Dict[str, str] = {}
        lemma_sample_sentences: Dict[str, int] = {}

        # Get all sentences back with IDs
        stmt = (
            select(DocumentSentence)
            .where(DocumentSentence.doc_id == doc_id)
            .order_by(DocumentSentence.sent_index)
        )
        sentences = session.execute(stmt).scalars().all()

        total_tokens = 0

        for sent_row in sentences:
            nlp_sentences = engine.process(sent_row.text)

            if not nlp_sentences:
                continue

            for nlp_sent in nlp_sentences:
                for token in nlp_sent.tokens:
                    total_tokens += 1

                    lemma_text = token.lemma.strip()
                    if not lemma_text:
                        continue

                    lemma_counter[lemma_text] += 1

                    if lemma_text not in lemma_pos_map:
                        lemma_pos_map[lemma_text] = token.pos

                    if lemma_text not in lemma_sample_sentences:
                        lemma_sample_sentences[lemma_text] = sent_row.sentence_id

        # Create or get lemmas
        lemma_id_map = {}
        for lemma_text in lemma_counter:
            stmt = select(Lemma).where(
                Lemma.project_id == project_id,
                Lemma.lemma_text == lemma_text,
            )
            lemma = session.execute(stmt).scalar_one_or_none()

            if not lemma:
                pos = lemma_pos_map.get(lemma_text, "X")
                lemma = Lemma(
                    project_id=project_id,
                    lemma_text=lemma_text,
                    pos=pos,
                )
                session.add(lemma)
                session.flush()

            lemma_id_map[lemma_text] = lemma.lemma_id

        # Update statistics
        for lemma_text, freq in lemma_counter.items():
            lemma_id = lemma_id_map[lemma_text]
            sample_sent_id = lemma_sample_sentences.get(lemma_text)

            # Create doc-level stat
            doc_stat = LemmaDocStat(
                project_id=project_id,
                doc_id=doc_id,
                lemma_id=lemma_id,
                freq_abs=freq,
                sample_sentence_id=sample_sent_id,
            )
            session.add(doc_stat)

            # Update project-level stat
            stmt = select(LemmaProjectStat).where(
                LemmaProjectStat.project_id == project_id,
                LemmaProjectStat.lemma_id == lemma_id,
            )
            proj_stat = session.execute(stmt).scalar_one_or_none()

            if proj_stat:
                proj_stat.freq_abs += freq
                proj_stat.doc_freq += 1
                proj_stat.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            else:
                proj_stat = LemmaProjectStat(
                    project_id=project_id,
                    lemma_id=lemma_id,
                    freq_abs=freq,
                    doc_freq=1,
                    sample_sentence_id=sample_sent_id,
                )
                session.add(proj_stat)

        session.flush()

        # Update document status
        doc.status = "processed"
        doc.processed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        doc.sentence_count = len(sentences)
        doc.token_count = total_tokens
        session.flush()  # Don't commit yet - caller will commit

        return True, total_tokens, len(lemma_counter)

    except Exception as e:
        logger.exception(f"Failed to process document {doc_id}")
        doc.status = "failed"
        doc.error_message = str(e)
        session.flush()
        return False, 0, 0


def main():
    parser = argparse.ArgumentParser(
        description="Process reference corpus with NLP (batch optimized)"
    )
    parser.add_argument("--db-path", type=str, required=True)
    parser.add_argument("--project-name", type=str, required=True)
    parser.add_argument("--use-gpu", action="store_true")
    parser.add_argument("--batch-size", type=int, default=100, help="Commit every N documents")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    setup_logging(db_path.parent / "logs", level=logging.INFO)

    DBService.initialize(db_path)
    db_service = DBService.get_instance()

    try:
        with db_service.get_session() as session:
            # Get project
            project = session.execute(
                select(DictProject).where(DictProject.name == args.project_name)
            ).scalar_one()

            # Count total and processed documents
            total_all = session.execute(
                select(func.count(SourceDocument.doc_id))
                .join(SourceCorpus)
                .where(SourceCorpus.project_id == project.project_id)
            ).scalar()

            already_processed = session.execute(
                select(func.count(SourceDocument.doc_id))
                .join(SourceCorpus)
                .where(SourceCorpus.project_id == project.project_id)
                .where(SourceDocument.status == "processed")
            ).scalar()

            # Get only UNPROCESSED documents
            docs = (
                session.execute(
                    select(SourceDocument.doc_id)
                    .join(SourceCorpus)
                    .where(SourceCorpus.project_id == project.project_id)
                    .where(SourceDocument.status != "processed")
                    .order_by(SourceDocument.doc_id)
                )
                .scalars()
                .all()
            )

            total = len(docs)
            logger.info(f"Total documents: {total_all:,}")
            logger.info(
                f"Already processed: {already_processed:,} ({already_processed/total_all*100:.1f}%)"
            )
            logger.info(f"To process: {total:,} ({total/total_all*100:.1f}%)")
            logger.info(f"GPU: {args.use_gpu}")
            logger.info(f"Batch size: {args.batch_size}")

            if total == 0:
                logger.info("All documents already processed!")
                return

            # Initialize NLP engine
            from app.services.process_service import ProcessService

            process_service = ProcessService()
            engine = process_service.get_nlp_engine(use_gpu=args.use_gpu)

            # Update project's NLP engine
            project.nlp_engine = engine.get_name()
            project.nlp_engine_version = engine.get_version()
            session.commit()

            # Create ONE ProcessorRun for the entire batch
            run = ProcessorRun(
                project_id=project.project_id,
                engine=engine.get_name(),
                engine_version=engine.get_version(),
                status="running",
            )
            session.add(run)
            session.commit()

            logger.info(f"Started ProcessorRun {run.run_id}")

            processed_count = 0
            error_count = 0
            total_tokens = 0
            total_lemmas = 0

            for i, doc_id in enumerate(docs, 1):
                try:
                    success, tokens, lemmas = process_document_no_run(
                        session, doc_id, engine, project.project_id
                    )

                    if success:
                        # Commit after each successful document
                        session.commit()
                        processed_count += 1
                        total_tokens += tokens
                        total_lemmas += lemmas

                        if processed_count % args.batch_size == 0:
                            overall_progress = (
                                (already_processed + processed_count) / total_all * 100
                            )
                            logger.info(
                                f"Progress: {processed_count:,}/{total:,} this run "
                                f"({processed_count/total*100:.1f}%) | "
                                f"Overall: {already_processed + processed_count:,}/{total_all:,} ({overall_progress:.1f}%) | "
                                f"Tokens: {total_tokens:,} | Unique lemmas: {total_lemmas:,}"
                            )
                    else:
                        # Record error
                        error = RunError(
                            run_id=run.run_id,
                            doc_id=doc_id,
                            stage="processing",
                            message=f"Processing failed (see document error_message)",
                        )
                        session.add(error)
                        session.commit()
                        error_count += 1

                except Exception as e:
                    logger.error(f"Error processing doc {doc_id}: {e}")
                    session.rollback()
                    error_count += 1

            # Update run status
            run.status = "ok" if error_count == 0 else "completed_with_errors"
            run.finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            run.docs_processed = processed_count
            run.tokens_total = total_tokens
            run.lemmas_total = total_lemmas
            run.note = f"Processed {processed_count:,} docs, {error_count:,} errors"
            session.commit()

            logger.info(f"=" * 80)
            logger.info(f"NLP processing complete!")
            logger.info(f"  Processed: {processed_count:,} documents")
            logger.info(f"  Errors: {error_count:,} documents")
            logger.info(f"  Tokens: {total_tokens:,}")
            logger.info(f"  Unique lemmas: {total_lemmas:,}")
            logger.info(
                f"  Overall: {already_processed + processed_count:,}/{total_all:,} documents processed"
            )
            logger.info(f"=" * 80)

    finally:
        DBService.shutdown()


if __name__ == "__main__":
    main()
