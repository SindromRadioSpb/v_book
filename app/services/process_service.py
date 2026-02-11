"""Document processing service."""
import logging
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import select, update

from app.infra.sa_models import (
    SourceDocument,
    DocumentText,
    DocumentSentence,
    Lemma,
    LemmaDocStat,
    LemmaProjectStat,
    ProcessorRun,
    RunError,
    DictProject,
)
from app.infra.nlp_engines.base import NLPEngine
from app.infra.nlp_engines.stanza_engine import create_stanza_engine
from app.domain.preprocessing import preprocess_text
from app.domain.sentence_splitter import split_into_sentences
from app.services.db_service import DBService
from app.services.entity_classifier import classify_text

logger = logging.getLogger(__name__)


class ProcessService:
    """Service for NLP document processing."""

    def __init__(self):
        self.db_service = DBService.get_instance()
        self._engine: Optional[NLPEngine] = None
        logger.info("ProcessService initialized")

    def get_nlp_engine(self, use_gpu: bool = False, use_mock: bool = False) -> NLPEngine:
        """
        Get or create NLP engine (singleton).

        Args:
            use_gpu: Whether to use GPU
            use_mock: Use mock engine instead of Stanza (for testing)

        Returns:
            NLPEngine instance

        Raises:
            RuntimeError: If engine initialization fails
        """
        if self._engine is None:
            if use_mock:
                logger.info("Creating Mock NLP engine (rule-based)...")
                from app.infra.nlp_engines.mock_engine import create_mock_engine
                self._engine = create_mock_engine()
            else:
                logger.info("Creating Stanza NLP engine...")
                try:
                    self._engine = create_stanza_engine(use_gpu=use_gpu)
                except (ImportError, RuntimeError) as e:
                    logger.warning(f"Stanza not available: {e}")
                    logger.info("Falling back to Mock engine")
                    from app.infra.nlp_engines.mock_engine import create_mock_engine
                    self._engine = create_mock_engine()

            logger.info(f"NLP engine ready: {self._engine.get_name()} v{self._engine.get_version()}")
        return self._engine

    def process_document(
        self,
        session: Session,
        doc_id: int,
        use_gpu: bool = False,
        use_mock: bool = False,
    ) -> bool:
        """
        Process a document with NLP pipeline.

        Steps:
        1. Get raw text
        2. Preprocess
        3. Split into sentences
        4. NLP (tokenize + lemmatize + POS)
        5. Store sentences
        6. Calculate lemma statistics
        7. Update document status

        Args:
            session: Database session
            doc_id: Document ID
            use_gpu: Whether to use GPU for NLP

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Processing document {doc_id}...")

        # Get document
        doc = session.get(SourceDocument, doc_id)
        if not doc:
            logger.error(f"Document not found: {doc_id}")
            return False

        # Get project
        from app.infra.sa_models import SourceCorpus
        corpus = session.get(SourceCorpus, doc.corpus_id)
        project_id = corpus.project_id

        # Start processor run
        engine = self.get_nlp_engine(use_gpu=use_gpu, use_mock=use_mock)

        # Update project's NLP engine (for term extraction to use same engine)
        project = session.get(DictProject, project_id)
        if project:
            project.nlp_engine = engine.get_name()
            project.nlp_engine_version = engine.get_version()

        run = ProcessorRun(
            project_id=project_id,
            engine=engine.get_name(),
            engine_version=engine.get_version(),
            status='running',
        )
        session.add(run)
        session.flush()

        try:
            # Update status
            doc.status = 'processing'
            session.commit()

            # Get raw text
            doc_text = session.get(DocumentText, doc_id)
            if not doc_text or not doc_text.raw_text:
                raise ValueError("No text available for document")

            raw_text = doc_text.raw_text

            # Preprocess
            logger.debug("Preprocessing text...")
            cleaned_text = preprocess_text(raw_text)
            doc_text.cleaned_text = cleaned_text
            session.commit()

            # Split into sentences (simple splitting first)
            logger.debug("Splitting into sentences...")
            sentence_texts = split_into_sentences(cleaned_text)
            logger.info(f"Found {len(sentence_texts)} sentences")

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
            logger.debug("Running NLP pipeline...")
            lemma_counter: Counter = Counter()
            lemma_pos_map: Dict[str, str] = {}  # lemma_text -> most common POS
            lemma_sample_sentences: Dict[str, int] = {}  # lemma_text -> sentence_id

            # Get all sentences back with IDs
            stmt = select(DocumentSentence).where(
                DocumentSentence.doc_id == doc_id
            ).order_by(DocumentSentence.sent_index)
            sentences = session.execute(stmt).scalars().all()

            total_tokens = 0

            for sent_row in sentences:
                # Process sentence with NLP
                nlp_sentences = engine.process(sent_row.text)

                if not nlp_sentences:
                    logger.warning(f"No NLP output for sentence {sent_row.sentence_id}")
                    continue

                # Typically one sentence, but could be split differently by Stanza
                for nlp_sent in nlp_sentences:
                    for token in nlp_sent.tokens:
                        total_tokens += 1

                        lemma_text = token.lemma.strip()
                        if not lemma_text:
                            continue

                        # Count lemma
                        lemma_counter[lemma_text] += 1

                        # Track most common POS for this lemma
                        if lemma_text not in lemma_pos_map:
                            lemma_pos_map[lemma_text] = token.pos

                        # Save first example sentence
                        if lemma_text not in lemma_sample_sentences:
                            lemma_sample_sentences[lemma_text] = sent_row.sentence_id

            logger.info(f"Processed {total_tokens} tokens, {len(lemma_counter)} unique lemmas")

            # Create or get lemmas
            lemma_id_map = self._create_or_get_lemmas(
                session,
                project_id,
                lemma_counter,
                lemma_pos_map,
            )

            # Calculate statistics
            self._update_lemma_statistics(
                session,
                project_id,
                doc_id,
                lemma_counter,
                lemma_id_map,
                lemma_sample_sentences,
            )

            # Update document status and metrics (Migration 003)
            doc.status = 'processed'
            doc.processed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            doc.sentence_count = len(sentences)
            doc.token_count = total_tokens
            session.commit()

            # Update run
            run.status = 'ok'
            run.finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            run.docs_processed = 1
            run.tokens_total = total_tokens
            run.lemmas_total = len(lemma_counter)
            session.commit()

            logger.info(f"Document {doc_id} processed successfully")
            return True

        except Exception as e:
            logger.exception(f"Failed to process document {doc_id}")

            # Record error
            error = RunError(
                run_id=run.run_id,
                doc_id=doc_id,
                stage='processing',
                message=str(e),
            )
            session.add(error)

            # Update statuses
            doc.status = 'failed'
            doc.error_message = str(e)

            run.status = 'failed'
            run.finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

            session.commit()

            return False

    def _create_or_get_lemmas(
        self,
        session: Session,
        project_id: int,
        lemma_counter: Counter,
        lemma_pos_map: Dict[str, str],
    ) -> Dict[str, int]:
        """
        Create or get existing lemmas.

        Args:
            session: Database session
            project_id: Project ID
            lemma_counter: Counter of lemma frequencies
            lemma_pos_map: Mapping of lemma to POS

        Returns:
            Dictionary mapping lemma_text to lemma_id
        """
        lemma_id_map = {}
        stats = {'new': 0, 'existing': 0, 'noise': 0, 'classes': Counter()}

        for lemma_text in lemma_counter:
            # Try to find existing lemma
            stmt = select(Lemma).where(
                Lemma.project_id == project_id,
                Lemma.lemma_text == lemma_text,
            )
            lemma = session.execute(stmt).scalar_one_or_none()

            if not lemma:
                # Classify the lemma (Task 11: Entity Classification)
                classification = classify_text(lemma_text)

                # Create new lemma with classification
                pos = lemma_pos_map.get(lemma_text, 'X')
                lemma = Lemma(
                    project_id=project_id,
                    lemma_text=lemma_text,
                    pos=pos,
                    entity_class=classification.entity_class,
                    is_noise=1 if classification.is_noise else 0,
                    noise_reason=classification.noise_reason,
                    norm_text=classification.norm_text,
                )
                session.add(lemma)
                session.flush()

                stats['new'] += 1
                stats['classes'][classification.entity_class] += 1
                if classification.is_noise:
                    stats['noise'] += 1

                logger.debug(f"Created lemma: {lemma_text} ({pos}) -> {classification.entity_class}")
            else:
                stats['existing'] += 1

            lemma_id_map[lemma_text] = lemma.lemma_id

        # Log classification summary
        if stats['new'] > 0:
            logger.info(
                f"Created {stats['new']} new lemmas ({stats['noise']} noise, "
                f"{stats['new'] - stats['noise']} valid). "
                f"Classes: {dict(stats['classes'])}"
            )

        return lemma_id_map

    def _update_lemma_statistics(
        self,
        session: Session,
        project_id: int,
        doc_id: int,
        lemma_counter: Counter,
        lemma_id_map: Dict[str, int],
        lemma_sample_sentences: Dict[str, int],
    ) -> None:
        """
        Update lemma statistics (doc + project level).

        Args:
            session: Database session
            project_id: Project ID
            doc_id: Document ID
            lemma_counter: Counter of lemma frequencies
            lemma_id_map: Mapping of lemma_text to lemma_id
            lemma_sample_sentences: Sample sentences for each lemma
        """
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
                # Update existing
                proj_stat.freq_abs += freq
                proj_stat.doc_freq += 1
                proj_stat.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            else:
                # Create new
                proj_stat = LemmaProjectStat(
                    project_id=project_id,
                    lemma_id=lemma_id,
                    freq_abs=freq,
                    doc_freq=1,
                    sample_sentence_id=sample_sent_id,
                )
                session.add(proj_stat)

        session.flush()
        logger.debug(f"Updated statistics for {len(lemma_counter)} lemmas")

    def process_documents_batch(
        self,
        session: Session,
        doc_ids: List[int],
        use_gpu: bool = False,
        use_mock: bool = False,
    ) -> Tuple[int, int]:
        """
        Process multiple documents.

        Args:
            session: Database session
            doc_ids: List of document IDs
            use_gpu: Whether to use GPU

        Returns:
            Tuple of (success_count, error_count)
        """
        success = 0
        errors = 0

        for doc_id in doc_ids:
            if self.process_document(session, doc_id, use_gpu=use_gpu, use_mock=use_mock):
                success += 1
            else:
                errors += 1

        logger.info(f"Batch processing complete: {success} succeeded, {errors} failed")
        return success, errors

    # ========================================================================
    # M4: Live Update - Delta Statistics
    # ========================================================================

    def remove_document_stats(self, session: Session, doc_id: int) -> bool:
        """
        Remove document statistics using delta subtraction.

        This is called before deleting a document to maintain accurate
        project-level statistics.

        Args:
            session: Database session
            doc_id: Document ID to remove stats for

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get document to find project_id
            doc = session.get(SourceDocument, doc_id)
            if not doc:
                logger.warning(f"Document {doc_id} not found")
                return False

            # Get corpus to find project_id
            from app.infra.sa_models import SourceCorpus
            corpus = session.get(SourceCorpus, doc.corpus_id)
            if not corpus:
                logger.warning(f"Corpus {doc.corpus_id} not found")
                return False

            project_id = corpus.project_id

            logger.info(f"Removing statistics for document {doc_id} (project {project_id})")

            # Get all doc-level stats for this document
            stmt = select(LemmaDocStat).where(LemmaDocStat.doc_id == doc_id)
            doc_stats = session.execute(stmt).scalars().all()

            if not doc_stats:
                logger.info("No statistics to remove")
                return True

            # For each lemma, subtract from project stats
            for doc_stat in doc_stats:
                # Get project stat
                proj_stmt = select(LemmaProjectStat).where(
                    LemmaProjectStat.project_id == project_id,
                    LemmaProjectStat.lemma_id == doc_stat.lemma_id,
                )
                proj_stat = session.execute(proj_stmt).scalar_one_or_none()

                if proj_stat:
                    # Subtract frequency
                    proj_stat.freq_abs -= doc_stat.freq_abs
                    proj_stat.doc_freq -= 1
                    proj_stat.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

                    # If frequency reaches zero, delete project stat
                    if proj_stat.freq_abs <= 0 or proj_stat.doc_freq <= 0:
                        session.delete(proj_stat)
                        logger.debug(f"Deleted project stat for lemma {doc_stat.lemma_id} (zero frequency)")

                # Delete doc-level stat
                session.delete(doc_stat)

            session.flush()

            # Delete lemmas that no longer have any project stats
            # (orphaned lemmas)
            self._cleanup_orphaned_lemmas(session, project_id)

            logger.info(f"Removed statistics for {len(doc_stats)} lemmas")
            return True

        except Exception as e:
            logger.exception(f"Failed to remove document stats for {doc_id}")
            return False

    def _cleanup_orphaned_lemmas(self, session: Session, project_id: int) -> int:
        """
        Delete lemmas that no longer have any project statistics.

        Args:
            session: Database session
            project_id: Project ID

        Returns:
            Number of lemmas deleted
        """
        # Find lemmas without project stats
        from sqlalchemy import and_, exists

        stmt = select(Lemma).where(
            Lemma.project_id == project_id,
            ~exists(
                select(1).where(
                    and_(
                        LemmaProjectStat.project_id == project_id,
                        LemmaProjectStat.lemma_id == Lemma.lemma_id,
                    )
                )
            ),
        )

        orphaned_lemmas = session.execute(stmt).scalars().all()

        count = 0
        for lemma in orphaned_lemmas:
            session.delete(lemma)
            count += 1
            logger.debug(f"Deleted orphaned lemma: {lemma.lemma_text}")

        if count > 0:
            session.flush()
            logger.info(f"Cleaned up {count} orphaned lemmas")

        return count

    def reprocess_document(
        self,
        session: Session,
        doc_id: int,
        use_gpu: bool = False,
        use_mock: bool = False,
    ) -> bool:
        """
        Re-process a document with automatic delta statistics update.

        Steps:
        1. Check document exists and is processed
        2. Set status to 'processing'
        3. Remove old statistics (delta subtraction)
        4. Delete old sentences
        5. Run NLP processing again
        6. Set status to 'processed'

        Args:
            session: Database session
            doc_id: Document ID to reprocess
            use_gpu: Whether to use GPU
            use_mock: Use mock engine instead of Stanza

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get document
            doc = session.get(SourceDocument, doc_id)
            if not doc:
                logger.error(f"Document {doc_id} not found")
                return False

            if doc.status not in ('processed', 'failed'):
                logger.warning(f"Document {doc_id} is not processed (status: {doc.status})")
                # Allow reprocessing anyway (for failed docs)

            logger.info(f"Re-processing document {doc_id}: {doc.file_name}")

            # Step 1: Set status to 'processing'
            doc.status = 'processing'
            session.flush()

            # Step 2: Remove old statistics
            if not self.remove_document_stats(session, doc_id):
                logger.error(f"Failed to remove old stats for document {doc_id}")
                doc.status = 'failed'
                doc.error_message = "Failed to remove old statistics"
                session.commit()
                return False

            # Step 3: Delete old sentences
            stmt = select(DocumentSentence).where(DocumentSentence.doc_id == doc_id)
            old_sentences = session.execute(stmt).scalars().all()
            for sent in old_sentences:
                session.delete(sent)
            session.flush()
            logger.info(f"Deleted {len(old_sentences)} old sentences")

            # Step 4: Run NLP processing
            # Note: process_document will handle the rest
            # We need to temporarily reset status to 'imported' so process_document works
            doc.status = 'imported'
            doc.processed_at = None
            session.flush()

            # Process
            success = self.process_document(session, doc_id, use_gpu=use_gpu, use_mock=use_mock)

            if success:
                logger.info(f"Document {doc_id} re-processed successfully")
            else:
                logger.error(f"Failed to re-process document {doc_id}")

            return success

        except Exception as e:
            logger.exception(f"Failed to reprocess document {doc_id}")
            # Set status to failed
            doc = session.get(SourceDocument, doc_id)
            if doc:
                doc.status = 'failed'
                doc.error_message = f"Re-processing error: {str(e)}"
                session.commit()
            return False

    def bulk_reprocess(
        self,
        session: Session,
        doc_ids: List[int],
        use_gpu: bool = False,
        use_mock: bool = False,
    ) -> Tuple[int, int]:
        """
        Re-process multiple documents with delta statistics.

        Args:
            session: Database session
            doc_ids: List of document IDs
            use_gpu: Whether to use GPU
            use_mock: Use mock engine

        Returns:
            Tuple of (success_count, error_count)
        """
        success = 0
        errors = 0

        logger.info(f"Bulk re-processing {len(doc_ids)} documents")

        for doc_id in doc_ids:
            if self.reprocess_document(session, doc_id, use_gpu=use_gpu, use_mock=use_mock):
                success += 1
            else:
                errors += 1

        logger.info(f"Bulk re-processing complete: {success} succeeded, {errors} failed")
        return success, errors
