"""Project management service."""
import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.infra.sa_models import DictProject, Library, SourceCorpus
from app.services.db_service import DBService

logger = logging.getLogger(__name__)


class ProjectService:
    """Service for managing projects and libraries."""

    def __init__(self):
        self.db_service = DBService.get_instance()

    def get_or_create_default_library(self, session: Session) -> Library:
        """Get or create the default library."""
        stmt = select(Library).where(Library.name == "Default Library")
        library = session.execute(stmt).scalar_one_or_none()

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

    def create_project(
        self,
        session: Session,
        name: str,
        description: str = "",
        library: Optional[Library] = None,
    ) -> DictProject:
        """Create a new project."""
        if library is None:
            library = self.get_or_create_default_library(session)

        project = DictProject(
            library_id=library.library_id,
            name=name,
            description=description,
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

    def delete_project(self, session: Session, project_id: int) -> bool:
        """Delete a project."""
        project = self.get_project(session, project_id)
        if project:
            session.delete(project)
            session.commit()
            logger.info(f"Deleted project ID: {project_id}")
            return True
        return False

    def get_project_corpora(self, session: Session, project_id: int) -> List[SourceCorpus]:
        """Get all corpora for a project."""
        stmt = select(SourceCorpus).where(SourceCorpus.project_id == project_id)
        corpora = session.execute(stmt).scalars().all()
        return list(corpora)

    def get_default_corpus(self, session: Session, project_id: int) -> Optional[SourceCorpus]:
        """Get the default corpus for a project."""
        corpora = self.get_project_corpora(session, project_id)
        return corpora[0] if corpora else None
