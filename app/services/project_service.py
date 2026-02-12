"""Project management service."""
import logging
from typing import List, Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session, joinedload

from app.infra.sa_models import (
    DictProject,
    Library,
    SourceCorpus,
    SourceDocument,
    DocumentSentence,
    Lemma,
    Ngram,
    TermCard,
)
from app.domain.dto import DeleteReport
from app.domain.exceptions import ReferenceCorpusReadonlyError
from app.services.db_service import DBService
from app.infra.fts_manager import ensure_fts_tables

logger = logging.getLogger(__name__)


class ProjectService:
    """Service for managing projects and libraries."""

    def __init__(self):
        self.db_service = DBService.get_instance()

    def get_or_create_default_library(self, session: Session) -> Library:
        """Get or create the default library."""
        stmt = select(Library).where(Library.name == "Default Library")
        library = session.execute(stmt).scalars().first()

        if library is None:
            library = Library(name="Default Library")
            session.add(library)
            session.commit()
            logger.info("Created default library")

        return library

    def list_projects(self, session: Session) -> List[DictProject]:
        """List all projects."""
        stmt = select(DictProject).options(joinedload(DictProject.library))
        projects = session.execute(stmt).scalars().all()
        return list(projects)

    def get_project(self, session: Session, project_id: int) -> Optional[DictProject]:
        """Get a project by ID."""
        stmt = select(DictProject).where(DictProject.project_id == project_id)
        return session.execute(stmt).scalar_one_or_none()

    def get_default_reference_project(self, session: Session) -> Optional[int]:
        """
        Get the default reference corpus project ID.

        Returns the project marked as is_general_corpus=1 (deterministic: lowest ID first),
        or falls back to "Hebrew Wikipedia Baseline" by name if no general corpus is marked.

        Returns:
            Reference project ID or None if not found
        """
        # First: look for is_general_corpus=1 (deterministic: lowest project_id)
        stmt = (
            select(DictProject.project_id)
            .where(DictProject.is_general_corpus == 1)
            .order_by(DictProject.project_id.asc())
            .limit(1)
        )
        ref_id = session.execute(stmt).scalar_one_or_none()

        if ref_id:
            return ref_id

        # Fallback: search by name "Hebrew Wikipedia Baseline" (lowest ID first)
        stmt = (
            select(DictProject.project_id)
            .where(DictProject.name == "Hebrew Wikipedia Baseline")
            .order_by(DictProject.project_id.asc())
            .limit(1)
        )
        ref_id = session.execute(stmt).scalar()

        return ref_id

    def create_project(
        self,
        session: Session,
        name: str,
        description: str = "",
        library: Optional[Library] = None,
        auto_assign_reference: bool = True,
    ) -> DictProject:
        """
        Create a new project.

        Args:
            session: Database session
            name: Project name
            description: Project description
            library: Library to assign (defaults to "Default Library")
            auto_assign_reference: If True, automatically assign default reference corpus

        Returns:
            Created DictProject instance
        """
        if library is None:
            library = self.get_or_create_default_library(session)

        # Get default reference corpus (if auto-assign enabled)
        reference_id = None
        if auto_assign_reference:
            reference_id = self.get_default_reference_project(session)
            if reference_id:
                logger.info(f"Auto-assigning reference corpus ID: {reference_id}")

        project = DictProject(
            library_id=library.library_id,
            name=name,
            description=description,
            general_corpus_id=reference_id,
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        # Create default corpus
        corpus = SourceCorpus(
            project_id=project.project_id,
            name="Main Corpus",
            description="Default corpus",
        )
        session.add(corpus)
        session.commit()

        logger.info(f"Created project: {name} (ID: {project.project_id})")
        return project

    def rename_project(
        self,
        session: Session,
        project_id: int,
        new_name: str,
    ) -> DictProject:
        """
        Rename a project.

        Args:
            session: Database session
            project_id: Project ID to rename
            new_name: New project name

        Returns:
            Updated DictProject instance

        Raises:
            ValueError: If validation fails (empty, too long, forbidden chars, duplicate)
            Exception: If project not found or rename fails
        """
        from app.infra.sa_models import utc_now
        from app.infra.security import AuditLogger, sanitize_for_log

        # Validate new name
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("Project name cannot be empty")

        if len(new_name) > 255:
            raise ValueError("Project name cannot exceed 255 characters")

        # Check for forbidden characters (same as CreateProjectDialog)
        forbidden_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        bad_chars = [char for char in new_name if char in forbidden_chars]
        if bad_chars:
            raise ValueError(
                f"Project name cannot contain forbidden characters: / \\ : * ? \" < > |"
            )

        # Get project
        project = self.get_project(session, project_id)
        if not project:
            raise Exception(f"Project with ID {project_id} not found")

        old_name = project.name

        # Skip if name unchanged
        if new_name == old_name:
            return project

        # Check uniqueness within library
        existing = session.execute(
            select(DictProject)
            .where(
                DictProject.library_id == project.library_id,
                DictProject.name == new_name,
                DictProject.project_id != project_id,
            )
        ).scalar_one_or_none()

        if existing:
            raise ValueError(
                f"A project named '{new_name}' already exists in this library"
            )

        # Update project
        project.name = new_name
        project.updated_at = utc_now()

        session.commit()
        session.refresh(project)

        logger.info(
            f"Renamed project {project_id}: '{old_name}' → '{new_name}'"
        )

        # Audit log
        try:
            audit = AuditLogger(session)
            audit.log_event(
                event_type="project_rename",
                outcome="ALLOW",
                operation="rename_project",
                resource_type="project",
                resource_id=sanitize_for_log(str(project_id)),
                details={
                    "old_name": sanitize_for_log(old_name),
                    "new_name": sanitize_for_log(new_name),
                },
                project_id=project_id,
            )
        except Exception as e:
            logger.warning(f"Failed to log project rename audit: {e}")

        return project

    def delete_project(self, session: Session, project_id: int) -> DeleteReport:
        """
        Delete a project and all its related data.

        This will cascade delete:
        - All corpora
        - All documents (and their text, sentences)
        - All lemmas and statistics
        - All n-grams and statistics
        - All term cards
        - All FTS entries

        Args:
            session: Database session
            project_id: Project ID to delete

        Returns:
            DeleteReport with counts of deleted items

        Raises:
            ReferenceCorpusReadonlyError: If attempting to delete a reference corpus
        """
        # Get project
        project = self.get_project(session, project_id)
        if not project:
            return DeleteReport(
                project_id=project_id,
                project_name="Unknown",
                corpora_deleted=0,
                documents_deleted=0,
                sentences_deleted=0,
                lemmas_deleted=0,
                ngrams_deleted=0,
                term_cards_deleted=0,
                success=False,
                error_message="Project not found",
            )

        # GUARD: Prevent deletion of reference corpus (BEFORE try block)
        if project.is_general_corpus == 1:
            raise ReferenceCorpusReadonlyError(
                f"Cannot delete reference corpus '{project.name}'. "
                f"Reference corpora are read-only and used for termhood calculations. "
                f"To remove, first unmark as reference corpus (set is_general_corpus=0)."
            )

        try:
            project_name = project.name

            logger.info(f"Deleting project: {project_name} (ID: {project_id})")

            # CRITICAL: Ensure FTS tables exist before deletion
            # DELETE triggers on document_sentence/term_search reference sentence_fts/term_fts
            conn = session.connection().connection  # Get raw SQLite connection
            ensure_fts_tables(conn, schema="main", rebuild=False)

            # Count what will be deleted (for reporting)
            corpora_count = session.execute(
                select(func.count()).select_from(SourceCorpus).where(
                    SourceCorpus.project_id == project_id
                )
            ).scalar()

            # Count documents across all corpora
            documents_count = session.execute(
                select(func.count())
                .select_from(SourceDocument)
                .join(SourceCorpus)
                .where(SourceCorpus.project_id == project_id)
            ).scalar()

            # Count sentences across all documents
            sentences_count = session.execute(
                select(func.count())
                .select_from(DocumentSentence)
                .join(SourceDocument)
                .join(SourceCorpus)
                .where(SourceCorpus.project_id == project_id)
            ).scalar()

            lemmas_count = session.execute(
                select(func.count()).select_from(Lemma).where(
                    Lemma.project_id == project_id
                )
            ).scalar()

            ngrams_count = session.execute(
                select(func.count()).select_from(Ngram).where(
                    Ngram.project_id == project_id
                )
            ).scalar()

            term_cards_count = session.execute(
                select(func.count()).select_from(TermCard).where(
                    TermCard.project_id == project_id
                )
            ).scalar()

            # Delete project (CASCADE will handle all related data)
            session.delete(project)
            session.commit()

            logger.info(
                f"Deleted project '{project_name}': "
                f"{corpora_count} corpora, {documents_count} documents, "
                f"{sentences_count} sentences, {lemmas_count} lemmas, "
                f"{ngrams_count} ngrams, {term_cards_count} term cards"
            )

            return DeleteReport(
                project_id=project_id,
                project_name=project_name,
                corpora_deleted=corpora_count,
                documents_deleted=documents_count,
                sentences_deleted=sentences_count,
                lemmas_deleted=lemmas_count,
                ngrams_deleted=ngrams_count,
                term_cards_deleted=term_cards_count,
                success=True,
            )

        except Exception as e:
            logger.exception(f"Failed to delete project {project_id}")
            session.rollback()
            return DeleteReport(
                project_id=project_id,
                project_name=project.name if project else "Unknown",
                corpora_deleted=0,
                documents_deleted=0,
                sentences_deleted=0,
                lemmas_deleted=0,
                ngrams_deleted=0,
                term_cards_deleted=0,
                success=False,
                error_message=str(e),
            )

    def get_project_corpora(self, session: Session, project_id: int) -> List[SourceCorpus]:
        """Get all corpora for a project."""
        stmt = select(SourceCorpus).where(SourceCorpus.project_id == project_id)
        corpora = session.execute(stmt).scalars().all()
        return list(corpora)

    def get_default_corpus(self, session: Session, project_id: int) -> Optional[SourceCorpus]:
        """Get the default corpus for a project."""
        corpora = self.get_project_corpora(session, project_id)
        return corpora[0] if corpora else None

    def get_project_stats(self, session: Session, project_id: int) -> dict:
        """
        Get project statistics (document counts, lemma counts, ngram counts).

        Returns dict with keys:
        - total_docs: Total documents in all corpora
        - processed_docs: Documents with status='processed'
        - total_lemmas: Total unique lemmas
        - total_ngrams: Total unique n-grams
        """
        # Count documents
        total_docs = session.execute(
            select(func.count())
            .select_from(SourceDocument)
            .join(SourceCorpus)
            .where(SourceCorpus.project_id == project_id)
        ).scalar() or 0

        processed_docs = session.execute(
            select(func.count())
            .select_from(SourceDocument)
            .join(SourceCorpus)
            .where(
                SourceCorpus.project_id == project_id,
                SourceDocument.status == "processed",
            )
        ).scalar() or 0

        # Count lemmas
        total_lemmas = session.execute(
            select(func.count()).select_from(Lemma).where(Lemma.project_id == project_id)
        ).scalar() or 0

        # Count ngrams
        total_ngrams = session.execute(
            select(func.count()).select_from(Ngram).where(Ngram.project_id == project_id)
        ).scalar() or 0

        return {
            "total_docs": total_docs,
            "processed_docs": processed_docs,
            "total_lemmas": total_lemmas,
            "total_ngrams": total_ngrams,
        }
