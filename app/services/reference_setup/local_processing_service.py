"""Local processing service for offline reference corpus setup."""

import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infra.sa_models import DictProject, SourceDocument, SourceCorpus
from app.services.db_service import DBService
from app.services.process_service import ProcessService
from app.services.term_extraction_service import TermExtractionService
from .state import SetupState, SetupStage

logger = logging.getLogger(__name__)


class LocalProcessingService:
    """Service for local processing of reference corpus (offline mode)."""

    def __init__(self, work_dir: Path, state_file: Path, db_path: Path):
        """
        Initialize local processing service.

        Args:
            work_dir: Working directory for downloads and extraction
            state_file: Path to state JSON file
            db_path: Path to database
        """
        self.work_dir = work_dir
        self.state_file = state_file
        self.db_path = db_path
        self.work_dir.mkdir(parents=True, exist_ok=True)

        # Load or create state
        self.state = SetupState.load_from_file(state_file) or SetupState(mode="local_process")

        # Services (initialized on demand)
        self.process_service: Optional[ProcessService] = None
        self.term_service: Optional[TermExtractionService] = None

    def download_xml_dump(
        self,
        url: str,
        progress_callback: Optional[Callable[[SetupState], None]] = None,
    ) -> Path:
        """
        Download Wikipedia XML dump.

        Args:
            url: Download URL
            progress_callback: Progress callback

        Returns:
            Path to downloaded file
        """
        import urllib.request

        output_path = self.work_dir / "raw" / url.split("/")[-1]
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Check if already downloaded
        if output_path.exists():
            logger.info(f"XML dump already downloaded: {output_path}")
            return output_path

        logger.info(f"Downloading {url} → {output_path}")
        self.state.update_progress(stage=SetupStage.DOWNLOADING)
        self._save_state()

        # Download with progress
        def reporthook(block_num, block_size, total_size):
            downloaded = block_num * block_size
            self.state.bytes_downloaded = downloaded
            self.state.total_bytes = total_size
            self._save_state()
            if progress_callback:
                progress_callback(self.state)

        urllib.request.urlretrieve(url, output_path, reporthook)

        logger.info(f"Download complete: {output_path}")
        return output_path

    def extract_to_jsonl(
        self,
        dump_path: Path,
        progress_callback: Optional[Callable[[SetupState], None]] = None,
    ) -> Path:
        """
        Extract XML dump to JSONL shards.

        Args:
            dump_path: Path to XML.bz2 dump
            progress_callback: Progress callback

        Returns:
            Path to JSONL output directory
        """
        output_dir = self.work_dir / "jsonl"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Check if already extracted
        if list(output_dir.glob("*.jsonl")):
            logger.info(f"JSONL already extracted: {output_dir}")
            return output_dir

        logger.info(f"Extracting {dump_path} → {output_dir}")
        self.state.update_progress(stage=SetupStage.INSTALLING)  # Reuse stage
        self._save_state()

        # Run extraction script
        script_path = Path(__file__).parent.parent.parent.parent / "scripts" / "ref_corpora" / "extract_hewiki_to_jsonl.py"

        cmd = [
            sys.executable,
            str(script_path),
            "--dump", str(dump_path),
            "--out_dir", str(output_dir),
            "--overwrite",
        ]

        logger.info(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"Extraction failed: {result.stderr}")

        logger.info(f"Extraction complete: {output_dir}")
        return output_dir

    def import_to_database(
        self,
        jsonl_dir: Path,
        project_name: str = "Hebrew Wikipedia Baseline",
        corpus_name: str = "HEWiki-20260207",
        progress_callback: Optional[Callable[[SetupState], None]] = None,
    ) -> int:
        """
        Import JSONL to database.

        Args:
            jsonl_dir: Directory with JSONL shards
            project_name: Project name
            corpus_name: Corpus name
            progress_callback: Progress callback

        Returns:
            Project ID
        """
        logger.info(f"Importing JSONL from {jsonl_dir}")
        self.state.update_progress(stage=SetupStage.INSTALLING)
        self._save_state()

        # Run import script
        script_path = Path(__file__).parent.parent.parent.parent / "scripts" / "ref_corpora" / "import_ref_jsonl_to_project.py"

        jsonl_files = list(jsonl_dir.glob("*.jsonl"))
        if not jsonl_files:
            raise RuntimeError(f"No JSONL files found in {jsonl_dir}")

        cmd = [
            sys.executable,
            str(script_path),
            "--jsonl_files", *[str(f) for f in jsonl_files],
            "--project_name", project_name,
            "--corpus_name", corpus_name,
            "--source_key", "hewiki",
            "--db_path", str(self.db_path),
        ]

        logger.info(f"Running: {' '.join(cmd[:5])}... ({len(jsonl_files)} files)")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"Import failed: {result.stderr}")

        # Get project ID
        db_service = DBService.get_instance()
        with db_service.get_session() as session:
            project = session.execute(
                select(DictProject).where(DictProject.name == project_name)
            ).scalar_one_or_none()

            if not project:
                raise RuntimeError(f"Project '{project_name}' not found after import")

            project_id = project.project_id
            logger.info(f"Import complete: Project ID {project_id}")

        return project_id

    def process_with_nlp(
        self,
        project_id: int,
        use_gpu: bool = False,
        progress_callback: Optional[Callable[[SetupState], None]] = None,
    ):
        """
        Process documents with NLP pipeline.

        Args:
            project_id: Project ID
            use_gpu: Use GPU for processing
            progress_callback: Progress callback
        """
        logger.info(f"Processing project {project_id} with NLP (GPU={use_gpu})")

        if not self.process_service:
            self.process_service = ProcessService()

        db_service = DBService.get_instance()

        with db_service.get_session() as session:
            # Get all documents
            docs = session.execute(
                select(SourceDocument.doc_id)
                .join(SourceCorpus)
                .where(SourceCorpus.project_id == project_id)
                .order_by(SourceDocument.doc_id)
            ).scalars().all()

            total_docs = len(docs)
            logger.info(f"Processing {total_docs:,} documents")

            self.state.total_docs = total_docs
            self.state.update_progress(stage=SetupStage.INSTALLING)
            self._save_state()

            for i, doc_id in enumerate(docs, 1):
                try:
                    self.process_service.process_document(
                        session,
                        doc_id,
                        use_gpu=use_gpu,
                        use_mock=False,
                    )
                    session.commit()

                    self.state.docs_processed = i
                    if i % 100 == 0:  # Update every 100 docs
                        self._save_state()
                        if progress_callback:
                            progress_callback(self.state)

                except Exception as e:
                    logger.error(f"Error processing doc {doc_id}: {e}")
                    session.rollback()

            logger.info(f"NLP processing complete: {total_docs:,} documents")

    def extract_terms(
        self,
        project_id: int,
        progress_callback: Optional[Callable[[SetupState], None]] = None,
    ):
        """
        Extract terms from processed documents.

        Args:
            project_id: Project ID
            progress_callback: Progress callback
        """
        logger.info(f"Extracting terms for project {project_id}")

        if not self.term_service:
            self.term_service = TermExtractionService()

        db_service = DBService.get_instance()

        with db_service.get_session() as session:
            report = self.term_service.extract_terms_for_project(session, project_id)

            logger.info(f"Term extraction complete:")
            logger.info(f"  N-grams: {report.ngrams_extracted:,}")
            logger.info(f"  Clusters: {report.clusters_created:,}")

            if progress_callback:
                progress_callback(self.state)

    def run_full_pipeline(
        self,
        xml_url: str,
        project_name: str = "Hebrew Wikipedia Baseline",
        use_gpu: bool = False,
        progress_callback: Optional[Callable[[SetupState], None]] = None,
    ):
        """
        Run full pipeline: download → extract → import → NLP → terms.

        Args:
            xml_url: Wikipedia dump URL
            project_name: Project name
            use_gpu: Use GPU for NLP
            progress_callback: Progress callback
        """
        try:
            self.state.mark_started()
            self._save_state()

            # Step 1: Download XML
            logger.info("=== STEP 1: Download XML ===")
            dump_path = self.download_xml_dump(xml_url, progress_callback)

            # Step 2: Extract to JSONL
            logger.info("=== STEP 2: Extract to JSONL ===")
            jsonl_dir = self.extract_to_jsonl(dump_path, progress_callback)

            # Step 3: Import to database
            logger.info("=== STEP 3: Import to database ===")
            project_id = self.import_to_database(
                jsonl_dir,
                project_name=project_name,
                progress_callback=progress_callback,
            )

            # Step 4: Process with NLP
            logger.info("=== STEP 4: Process with NLP ===")
            self.process_with_nlp(project_id, use_gpu=use_gpu, progress_callback=progress_callback)

            # Step 5: Extract terms
            logger.info("=== STEP 5: Extract terms ===")
            self.extract_terms(project_id, progress_callback=progress_callback)

            # Mark completed
            self.state.mark_completed()
            self._save_state()

            logger.info("=== FULL PIPELINE COMPLETE ===")

        except Exception as e:
            error_msg = f"Pipeline failed: {e}"
            logger.error(error_msg)
            self.state.mark_failed(error_msg)
            self._save_state()
            raise

    def _save_state(self):
        """Save current state to file."""
        self.state.save_to_file(self.state_file)
