"""Document ingestion service."""
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.infra.sa_models import SourceDocument, DocumentText, SourceCorpus
from app.infra.util.hashing import sha256_file
from app.infra.extractors import txt_extractor, docx_extractor, pdf_extractor, pdf_ocr_extractor
from app.services.db_service import DBService
from app.infra.security import (
    validate_file_size,
    validate_path_security,
    sanitize_for_log,
    MAX_DOCUMENT_SIZE,
    ValidationError,
    PathSecurityError,
    AuditLogger,
)

logger = logging.getLogger(__name__)


class IngestService:
    """Service for document ingestion."""

    SUPPORTED_EXTENSIONS = {
        '.txt': 'text',
        '.docx': 'docx',
        '.pdf': 'pdf',
    }

    def __init__(self):
        self.db_service = DBService.get_instance()
        logger.info("IngestService initialized")

    def is_supported(self, file_path: Path) -> bool:
        """Check if file type is supported."""
        return file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def extract_text_from_file(self, file_path: Path, use_ocr: bool = False) -> tuple[str, bool]:
        """
        Extract text from a file.

        Args:
            file_path: Path to the file
            use_ocr: Whether to use OCR for PDFs (Premium feature)

        Returns:
            Tuple of (extracted_text, ocr_used)

        Raises:
            ValueError: If file type is not supported
            RuntimeError: If extraction fails
        """
        ext = file_path.suffix.lower()

        if ext not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {ext}")

        ocr_used = False

        try:
            if ext == '.txt':
                text = txt_extractor.extract_text(file_path)
            elif ext == '.docx':
                text = docx_extractor.extract_text(file_path)
            elif ext == '.pdf':
                if use_ocr:
                    try:
                        text = pdf_ocr_extractor.extract_text(file_path)
                        ocr_used = True
                    except NotImplementedError:
                        logger.warning("OCR not available, falling back to text extraction")
                        text = pdf_extractor.extract_text(file_path)
                else:
                    text = pdf_extractor.extract_text(file_path)
            else:
                raise ValueError(f"Unsupported file type: {ext}")

            return text, ocr_used

        except Exception as e:
            logger.exception(f"Text extraction failed for {sanitize_for_log(str(file_path))}")
            raise RuntimeError(f"Failed to extract text: {e}")

    def import_document(
        self,
        session: Session,
        corpus_id: int,
        file_path: Path,
        use_ocr: bool = False,
    ) -> SourceDocument:
        """
        Import a document into a corpus.

        Steps:
        1. Check if document already exists (by SHA256)
        2. Extract text
        3. Create document record
        4. Store raw text

        Args:
            session: Database session
            corpus_id: Corpus ID to add document to
            file_path: Path to the document file
            use_ocr: Whether to use OCR for PDFs

        Returns:
            SourceDocument instance

        Raises:
            ValueError: If file doesn't exist or is not supported
            RuntimeError: If extraction fails
        """
        if not file_path.exists():
            raise ValueError(f"File not found: {file_path}")

        # Initialize audit logger
        audit = AuditLogger(session)

        # Security: Validate path safety (block UNC, system dirs, resolve symlinks)
        try:
            safe_path = validate_path_security(file_path, operation="document import")
        except PathSecurityError as e:
            logger.warning(
                f"Path security check failed: {sanitize_for_log(str(file_path))}, "
                f"reason={e.reason}"
            )

            # Audit: Log BLOCK event
            audit.log_event(
                event_type="file_import",
                outcome="BLOCK",
                operation="import_document",
                resource_type="file",
                resource_id=sanitize_for_log(str(file_path)),
                reason=e.reason,
            )

            raise ValueError(f"File path not allowed: {e.reason}")

        # Security: Validate file size to prevent DoS
        try:
            validate_file_size(safe_path, MAX_DOCUMENT_SIZE, file_type="document")
        except ValidationError as e:
            logger.warning(
                f"File size limit exceeded: {sanitize_for_log(file_path.name)}, "
                f"size={e.value}"
            )

            # Audit: Log BLOCK event
            audit.log_event(
                event_type="file_import",
                outcome="BLOCK",
                operation="import_document",
                resource_type="file",
                resource_id=sanitize_for_log(file_path.name),
                reason="FILE_TOO_LARGE",
                details={"size_bytes": e.value, "max_bytes": MAX_DOCUMENT_SIZE},
            )

            raise ValueError(f"File too large: {e.value} bytes")

        if not self.is_supported(file_path):
            raise ValueError(f"Unsupported file type: {file_path.suffix}")

        # Check corpus exists
        corpus = session.get(SourceCorpus, corpus_id)
        if not corpus:
            raise ValueError(f"Corpus not found: {corpus_id}")

        # Calculate file hash
        file_hash = sha256_file(file_path)
        logger.info(f"File hash: {file_hash}")

        # Check for duplicates
        stmt = select(SourceDocument).where(
            SourceDocument.corpus_id == corpus_id,
            SourceDocument.sha256 == file_hash
        )
        existing = session.execute(stmt).scalar_one_or_none()

        if existing:
            logger.info(f"Document already exists: {existing.file_name} (ID: {existing.doc_id})")
            return existing

        # Extract text
        logger.info(f"Extracting text from: {sanitize_for_log(file_path.name)}")
        raw_text, ocr_used = self.extract_text_from_file(file_path, use_ocr=use_ocr)

        if not raw_text.strip():
            logger.warning(f"No text extracted from: {sanitize_for_log(file_path.name)}")

        # Get file metadata
        file_stat = file_path.stat()
        file_mtime = datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )

        # Create document record
        doc = SourceDocument(
            corpus_id=corpus_id,
            file_path=str(file_path.absolute()),
            file_name=file_path.name,
            file_ext=file_path.suffix.lower(),
            file_size_bytes=file_stat.st_size,
            sha256=file_hash,
            file_mtime_utc=file_mtime,
            status='imported',
        )
        session.add(doc)
        session.flush()  # Get doc_id

        # Store text
        doc_text = DocumentText(
            doc_id=doc.doc_id,
            raw_text=raw_text,
            ocr_used=1 if ocr_used else 0,
        )
        session.add(doc_text)

        session.commit()
        session.refresh(doc)

        logger.info(
            f"Imported document: {doc.file_name} "
            f"(ID: {doc.doc_id}, size: {len(raw_text)} chars, OCR: {ocr_used})"
        )

        # Audit: Log ALLOW event (successful import)
        audit.log_event(
            event_type="file_import",
            outcome="ALLOW",
            operation="import_document",
            resource_type="file",
            resource_id=sanitize_for_log(file_path.name),
            details={
                "doc_id": doc.doc_id,
                "file_size_bytes": doc.file_size_bytes,
                "text_length": len(raw_text),
                "ocr_used": ocr_used,
            },
        )

        return doc

    def import_documents_batch(
        self,
        session: Session,
        corpus_id: int,
        file_paths: List[Path],
        use_ocr: bool = False,
    ) -> List[tuple[Path, Optional[SourceDocument], Optional[str]]]:
        """
        Import multiple documents in batch.

        Args:
            session: Database session
            corpus_id: Corpus ID
            file_paths: List of file paths
            use_ocr: Whether to use OCR

        Returns:
            List of tuples: (file_path, document or None, error_message or None)
        """
        results = []

        for file_path in file_paths:
            try:
                doc = self.import_document(session, corpus_id, file_path, use_ocr=use_ocr)
                results.append((file_path, doc, None))
            except Exception as e:
                logger.exception(f"Failed to import {sanitize_for_log(file_path.name)}")
                results.append((file_path, None, str(e)))

        return results

    def get_document_text(self, session: Session, doc_id: int) -> Optional[str]:
        """Get raw text for a document."""
        doc_text = session.get(DocumentText, doc_id)
        return doc_text.raw_text if doc_text else None

    def delete_document(self, session: Session, doc_id: int) -> bool:
        """
        Delete a document with delta statistics update.

        Steps:
        1. Remove document statistics (M4: delta subtraction)
        2. Delete document (cascades to text, sentences, etc.)
        3. Commit transaction

        Args:
            session: Database session
            doc_id: Document ID

        Returns:
            True if deleted, False if not found
        """
        doc = session.get(SourceDocument, doc_id)
        if not doc:
            return False

        try:
            # M4: Remove statistics first (delta subtraction)
            if doc.status == 'processed':
                from app.services.process_service import ProcessService
                process_service = ProcessService()
                if not process_service.remove_document_stats(session, doc_id):
                    logger.warning(f"Failed to remove stats for document {doc_id}, continuing with delete")
                    # Continue anyway - better to delete than leave inconsistent state

            # Delete document (cascades to related records)
            session.delete(doc)
            session.commit()
            logger.info(f"Deleted document ID: {doc_id} ({doc.file_name})")
            return True

        except Exception as e:
            logger.exception(f"Failed to delete document {doc_id}")
            session.rollback()
            return False

    def bulk_delete(self, session: Session, doc_ids: List[int]) -> Tuple[int, int]:
        """
        Delete multiple documents with delta statistics.

        Args:
            session: Database session
            doc_ids: List of document IDs to delete

        Returns:
            Tuple of (success_count, error_count)
        """
        success = 0
        errors = 0

        logger.info(f"Bulk deleting {len(doc_ids)} documents")

        for doc_id in doc_ids:
            if self.delete_document(session, doc_id):
                success += 1
            else:
                errors += 1

        logger.info(f"Bulk delete complete: {success} succeeded, {errors} failed")
        return success, errors
