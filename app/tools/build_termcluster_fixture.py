"""Build test fixture DB with real term clusters for E2E testing.

Creates a minimal SQLite DB with:
- Full schema (migrations applied)
- 1 project
- 1 document with Hebrew text
- Term extraction pipeline run to generate term_clusters

Returns path to fixture DB and project_id for testing.
"""

import os
import shutil
import sqlite3
import tempfile
import logging
from pathlib import Path
from datetime import datetime
from typing import Tuple

logger = logging.getLogger(__name__)


class FixtureBuilder:
    """Builds test fixture DB with term clusters."""

    # Minimal Hebrew text for testing (enough to generate term clusters)
    SAMPLE_HEBREW_TEXT = """
    בית הספר הגדול נמצא ברחוב הראשי של העיר.
    התלמידים לומדים בבית הספר כל יום.
    המורים בבית הספר מלמדים עברית ומתמטיקה.
    ספר טוב הוא מתנה טובה לתלמיד.
    הספר החדש של המורה מעניין מאוד.
    """

    def __init__(self):
        self.fixture_dir = None
        self.db_path = None

    def build(self) -> Tuple[str, int]:
        """
        Build fixture DB with term clusters.

        Returns:
            Tuple of (db_path, project_id)
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.fixture_dir = Path(f"runtime/fixtures/termcluster/{timestamp}")
        self.fixture_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.fixture_dir / "fixture.db"

        logger.info(f"Building fixture DB: {self.db_path}")

        # Step 1: Create DB and apply migrations
        self._apply_migrations()

        # Step 2: Create project
        project_id = self._create_project()

        # Step 3: Create minimal lemmas and term clusters (no documents needed)
        self._create_test_data(project_id)

        # Step 4: Verify term clusters created
        cluster_count = self._verify_clusters(project_id)

        logger.info(f"Fixture DB created: {self.db_path}")
        logger.info(f"Project ID: {project_id}")
        logger.info(f"Term clusters: {cluster_count}")

        if cluster_count == 0:
            logger.warning("No term clusters created - fixture may be incomplete")

        return (str(self.db_path), project_id)

    def _apply_migrations(self):
        """Apply all migrations to create schema."""
        from app.services.db_service import DBService

        # Initialize DBService (applies migrations automatically)
        DBService.initialize(self.db_path)
        db_service = DBService.get_instance()

        # Apply M7 migrations manually (004_m7 + 005_m7_revert)
        migration_m7 = Path("schema/004_m7_translation_memory.sql").read_text(encoding='utf-8')
        migration_m7_revert = Path("schema/005_m7_add_revert_origin.sql").read_text(encoding='utf-8')

        con = sqlite3.connect(str(self.db_path))
        con.executescript(migration_m7)
        con.executescript(migration_m7_revert)
        con.close()

        # Shutdown to release connection
        DBService.shutdown()

        logger.info("Migrations applied")

    def _create_project(self) -> int:
        """Create test project."""
        from app.services.db_service import DBService
        from app.infra.sa_models import Library, DictProject

        DBService.initialize(self.db_path)
        db_service = DBService.get_instance()

        with db_service.get_session() as session:
            # Create library
            library = Library(
                library_id=1,
                name="Fixture Library",
                created_at=datetime.now().isoformat() + "Z",
            )
            session.add(library)

            # Create project
            project = DictProject(
                library_id=1,
                name="Fixture Project",
                src_lang="he",
                tgt_lang="ru",
                created_at=datetime.now().isoformat() + "Z",
            )
            session.add(project)
            session.flush()

            project_id = project.project_id
            session.commit()

        DBService.shutdown()

        logger.info(f"Project created: {project_id}")
        return project_id

    def _create_test_data(self, project_id: int):
        """Create minimal test data (lemmas and term clusters).

        For E2E testing, we create term data directly
        to avoid dependency on full NLP/document pipeline.
        """
        from app.services.db_service import DBService
        from app.infra.sa_models import Lemma, LemmaProjectStat, TermCluster
        from app.domain.normalization import normalize_for_tm

        DBService.initialize(self.db_path)
        db_service = DBService.get_instance()

        try:
            with db_service.get_session() as session:
                # Create sample lemmas
                lemmas_data = [
                    ("בית", "NOUN", 15),  # house
                    ("ספר", "NOUN", 12),  # book
                    ("בית ספר", "NOUN", 8),  # school (multiword)
                    ("תלמיד", "NOUN", 6),  # student
                    ("מורה", "NOUN", 5),  # teacher
                ]

                for lemma_text, pos, freq in lemmas_data:
                    lemma = Lemma(
                        project_id=project_id,
                        lemma_text=lemma_text,
                        pos=pos,
                    )
                    session.add(lemma)
                    session.flush()

                    stat = LemmaProjectStat(
                        lemma_id=lemma.lemma_id,
                        project_id=project_id,
                        freq_abs=freq,
                        doc_freq=1,
                    )
                    session.add(stat)

                # Create sample term clusters
                clusters_data = [
                    ("בית הספר", ["בית הספר", "בית ספר"], 8),  # school
                    ("תלמיד טוב", ["תלמיד טוב", "תלמידים טובים"], 4),  # good student
                ]

                for representative_he, variants, freq in clusters_data:
                    # Normalize representative for canonical_key
                    normalized = normalize_for_tm("he", representative_he, "term_cluster")

                    cluster = TermCluster(
                        project_id=project_id,
                        representative_he=representative_he,
                        canonical_key=normalized.norm,
                        freq_abs=freq,
                        doc_freq=1,
                        members_count=len(variants),
                    )
                    session.add(cluster)

                session.commit()

                logger.info(f"Created {len(lemmas_data)} lemmas and {len(clusters_data)} term clusters")

        except Exception as e:
            logger.exception("Extraction pipeline failed")
            raise

        finally:
            DBService.shutdown()

        logger.info("Extraction pipeline completed")

    def _verify_clusters(self, project_id: int) -> int:
        """Verify term clusters were created."""
        from app.services.db_service import DBService
        from app.infra.sa_models import TermCluster
        from sqlalchemy import select, func

        DBService.initialize(self.db_path)
        db_service = DBService.get_instance()

        with db_service.get_session() as session:
            stmt = select(func.count()).select_from(TermCluster).where(
                TermCluster.project_id == project_id
            )
            count = session.execute(stmt).scalar()

        DBService.shutdown()

        return count


def build_fixture() -> Tuple[str, int]:
    """
    Build fixture DB with term clusters.

    Returns:
        Tuple of (db_path, project_id)
    """
    builder = FixtureBuilder()
    return builder.build()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db_path, project_id = build_fixture()
    print(f"Fixture DB: {db_path}")
    print(f"Project ID: {project_id}")
