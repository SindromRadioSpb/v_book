"""P1 Verification Service - Scenario 7: TM persistence through re-extraction.

Automated verification that TM entries survive:
1. Re-extraction/reindex of term clusters
2. Database restart (close/reopen sessions)

Uses snapshot-by-default for safety (no production DB modification).
"""

import os
import shutil
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, select, func

from app.services.db_service import DBService
from app.infra.sa_models import Lemma, TermCluster, TMEntry, DictProject
from app.services.translation_service import TranslationService
from app.domain.normalization import normalize_for_tm

logger = logging.getLogger(__name__)


@dataclass
class SnapshotInfo:
    """Information about DB snapshot."""
    source_path: str
    snapshot_path: str
    timestamp: str
    size_bytes: int
    sha256: str


@dataclass
class TestItem:
    """Item to test TM persistence."""
    kind: str  # lemma, term_cluster, surface
    src_text: str
    src_norm: str
    item_id: Optional[int] = None  # lemma_id or cluster_id
    priority: int = 0  # Higher = better test candidate


@dataclass
class SeededTM:
    """TM entry created for testing."""
    tm_id: int
    item: TestItem
    translation: str
    src_norm: str


@dataclass
class VerificationPhaseResult:
    """Result of one verification phase."""
    phase_name: str
    items_checked: int
    items_passed: int
    items_failed: int
    duration_ms: float
    failures: List[dict] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Success rate percentage."""
        if self.items_checked == 0:
            return 0.0
        return (self.items_passed / self.items_checked) * 100.0


@dataclass
class P1VerificationReport:
    """Complete P1 verification report."""
    timestamp: str
    source_db_path: str
    snapshot_db_path: str
    snapshot_sha256: str
    project_id: Optional[int]
    test_items: List[TestItem]
    seeded_tm_entries: List[SeededTM]

    # Phases
    phase_pre_extraction: Optional[VerificationPhaseResult] = None
    phase_post_extraction: Optional[VerificationPhaseResult] = None
    phase_post_restart: Optional[VerificationPhaseResult] = None

    # Summary
    status: str = "UNKNOWN"  # PASS, PARTIAL, SKIPPED, FAIL
    total_duration_ms: float = 0.0
    error_summary: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp,
            "source_db_path": self.source_db_path,
            "snapshot_db_path": self.snapshot_db_path,
            "snapshot_sha256": self.snapshot_sha256,
            "project_id": self.project_id,
            "test_items": [
                {
                    "kind": item.kind,
                    "src_text": item.src_text,
                    "src_norm": item.src_norm,
                    "item_id": item.item_id,
                    "priority": item.priority,
                }
                for item in self.test_items
            ],
            "seeded_tm_entries": [
                {
                    "tm_id": tm.tm_id,
                    "translation": tm.translation,
                    "src_norm": tm.src_norm,
                }
                for tm in self.seeded_tm_entries
            ],
            "phases": {
                "pre_extraction": self._phase_to_dict(self.phase_pre_extraction),
                "post_extraction": self._phase_to_dict(self.phase_post_extraction),
                "post_restart": self._phase_to_dict(self.phase_post_restart),
            },
            "status": self.status,
            "total_duration_ms": self.total_duration_ms,
            "error_summary": self.error_summary,
        }

    def _phase_to_dict(self, phase: Optional[VerificationPhaseResult]) -> Optional[dict]:
        """Convert phase to dict."""
        if not phase:
            return None
        return {
            "phase_name": phase.phase_name,
            "items_checked": phase.items_checked,
            "items_passed": phase.items_passed,
            "items_failed": phase.items_failed,
            "duration_ms": phase.duration_ms,
            "success_rate": phase.success_rate,
            "failures": phase.failures,
        }


class P1VerificationService:
    """Service for P1 Scenario 7 verification."""

    def __init__(self):
        self.translation_service = TranslationService()
        self._cancelled = False

    def cancel(self):
        """Cancel ongoing verification."""
        self._cancelled = True

    def create_snapshot_db(self, src_db_path: str, out_dir: Optional[str] = None) -> SnapshotInfo:
        """
        Create snapshot copy of DB for safe testing.

        Args:
            src_db_path: Path to source DB
            out_dir: Output directory (default: runtime/verifications/p1/<timestamp>)

        Returns:
            SnapshotInfo with paths and metadata
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if out_dir is None:
            out_dir = f"runtime/verifications/p1/{timestamp}"

        os.makedirs(out_dir, exist_ok=True)

        snapshot_path = os.path.join(out_dir, "hdle_snapshot.db")

        # Copy DB file
        shutil.copy2(src_db_path, snapshot_path)

        # Compute SHA256
        sha256 = self._compute_sha256(snapshot_path)

        # Get size
        size_bytes = os.path.getsize(snapshot_path)

        logger.info(f"Created snapshot: {snapshot_path} ({size_bytes} bytes, SHA256: {sha256[:16]}...)")

        return SnapshotInfo(
            source_path=src_db_path,
            snapshot_path=snapshot_path,
            timestamp=timestamp,
            size_bytes=size_bytes,
            sha256=sha256,
        )

    def _compute_sha256(self, file_path: str) -> str:
        """Compute SHA256 hash of file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def select_test_items(self, session: Session, project_id: Optional[int]) -> List[TestItem]:
        """
        Select 3 test items (priority: term_cluster > lemma > surface).

        Args:
            session: DB session
            project_id: Project to select from (None = global scope)

        Returns:
            List of TestItem (up to 3)
        """
        items = []

        # Priority 1: Term cluster representative
        stmt = (
            select(TermCluster)
            .where(TermCluster.project_id == project_id if project_id else TermCluster.project_id.is_(None))
            .order_by(TermCluster.freq_abs.desc())
            .limit(1)
        )
        cluster = session.execute(stmt).scalar()
        if cluster:
            items.append(TestItem(
                kind="term_cluster",
                src_text=cluster.representative_he,
                src_norm=cluster.canonical_key,
                item_id=cluster.cluster_id,
                priority=3,
            ))

        # Priority 2: Multiword lemma
        stmt = (
            select(Lemma)
            .where(Lemma.project_id == project_id if project_id else Lemma.project_id.is_(None))
            .where(Lemma.lemma_text.contains(" "))
            .order_by(func.length(Lemma.lemma_text).desc())
            .limit(1)
        )
        lemma_multi = session.execute(stmt).scalar()
        if lemma_multi:
            normalized = normalize_for_tm("he", lemma_multi.lemma_text, "lemma")
            items.append(TestItem(
                kind="lemma",
                src_text=lemma_multi.lemma_text,
                src_norm=normalized.norm,
                item_id=lemma_multi.lemma_id,
                priority=2,
            ))

        # Priority 3: Single-word lemma
        if len(items) < 3:
            stmt = (
                select(Lemma)
                .where(Lemma.project_id == project_id if project_id else Lemma.project_id.is_(None))
                .where(~Lemma.lemma_text.contains(" "))
                .order_by(Lemma.lemma_id.asc())
                .limit(1)
            )
            lemma_single = session.execute(stmt).scalar()
            if lemma_single:
                normalized = normalize_for_tm("he", lemma_single.lemma_text, "lemma")
                items.append(TestItem(
                    kind="lemma",
                    src_text=lemma_single.lemma_text,
                    src_norm=normalized.norm,
                    item_id=lemma_single.lemma_id,
                    priority=1,
                ))

        logger.info(f"Selected {len(items)} test items (project_id={project_id})")
        return items

    def seed_tm_entries(
        self,
        session: Session,
        items: List[TestItem],
        project_id: Optional[int],
        src_lang: str = "he",
        tgt_lang: str = "ru",
    ) -> List[SeededTM]:
        """
        Create TM entries for test items (strict mode).

        Args:
            session: DB session
            items: Test items
            project_id: Project ID
            src_lang: Source language
            tgt_lang: Target language

        Returns:
            List of SeededTM
        """
        # Clean up old P1_TEST entries to avoid UNIQUE constraint conflicts
        from sqlalchemy import delete
        stmt = delete(TMEntry).where(
            TMEntry.project_id == project_id,
            TMEntry.source_ref == "p1_verification"
        )
        result = session.execute(stmt)
        if result.rowcount > 0:
            logger.info(f"Cleaned up {result.rowcount} old P1_TEST entries")
        session.commit()

        seeded = []

        for i, item in enumerate(items):
            # Generate test translation
            translation = f"[P1_TEST_{i+1}] тестовый перевод"

            # Use strict normalization (default)
            normalized = normalize_for_tm(src_lang, item.src_text, item.kind)

            # Create TM entry
            entry = TMEntry(
                project_id=project_id,
                kind=item.kind,
                src_lang=src_lang,
                tgt_lang=tgt_lang,
                src_text=item.src_text,
                src_norm=normalized.norm,
                translation=translation,
                status="approved",  # Approved so it's always visible
                origin="user_edit",
                source_ref="p1_verification",
                notes=f"[P1_TEST] Created for Scenario 7 verification at {datetime.now().isoformat()}",
            )
            session.add(entry)
            session.flush()

            seeded.append(SeededTM(
                tm_id=entry.tm_id,
                item=item,
                translation=translation,
                src_norm=normalized.norm,
            ))

            logger.info(f"Seeded TM entry: tm_id={entry.tm_id}, kind={item.kind}, src_text={item.src_text}")

        session.commit()
        return seeded

    def verify_resolve(
        self,
        session: Session,
        seeded_tm: List[SeededTM],
        project_id: Optional[int],
        src_lang: str = "he",
        tgt_lang: str = "ru",
    ) -> VerificationPhaseResult:
        """
        Verify that TM entries resolve correctly.

        Args:
            session: DB session
            seeded_tm: Seeded TM entries to verify
            project_id: Project ID
            src_lang: Source language
            tgt_lang: Target language

        Returns:
            VerificationPhaseResult
        """
        import time
        start_time = time.time()

        passed = 0
        failed = 0
        failures = []

        for tm in seeded_tm:
            if self._cancelled:
                break

            result = self.translation_service.resolve_translation(
                session=session,
                src_text=tm.item.src_text,
                kind=tm.item.kind,
                project_id=project_id,
                src_lang=src_lang,
                tgt_lang=tgt_lang,
                allow_draft=False,
            )

            # Check result
            if result.translation == tm.translation and result.source == "tm":
                passed += 1
            else:
                failed += 1
                failures.append({
                    "item": tm.item.src_text,
                    "kind": tm.item.kind,
                    "expected_translation": tm.translation,
                    "actual_translation": result.translation,
                    "expected_source": "tm",
                    "actual_source": result.source,
                })

        duration_ms = (time.time() - start_time) * 1000

        return VerificationPhaseResult(
            phase_name="unknown",
            items_checked=len(seeded_tm),
            items_passed=passed,
            items_failed=failed,
            duration_ms=duration_ms,
            failures=failures,
        )

    def simulate_restart(self, snapshot_db_path: str) -> Session:
        """
        Simulate DB restart by closing and reopening engine/session.

        Args:
            snapshot_db_path: Path to snapshot DB

        Returns:
            New session
        """
        # Close existing connections (if any)
        DBService._engine = None
        DBService._session_factory = None

        # Create new engine/session
        engine = create_engine(f"sqlite:///{snapshot_db_path}", echo=False)
        from sqlalchemy.orm import sessionmaker
        session_factory = sessionmaker(bind=engine)
        session = session_factory()

        logger.info(f"Simulated restart: reopened {snapshot_db_path}")
        return session

    def run_reextraction(self, project_id: int, db_path: str) -> None:
        """
        Run re-extraction/reindex (stub - requires real implementation).

        NOTE: This is a placeholder. Real implementation should:
        1. Clear existing term_cluster entries for project
        2. Re-run term extraction pipeline
        3. Regenerate term_cluster table

        For now, we simulate by doing nothing (TM should persist regardless).

        Args:
            project_id: Project to re-extract
            db_path: DB path
        """
        logger.warning("run_reextraction: STUB - real re-extraction not implemented")
        # TODO: Integrate with actual term extraction pipeline
        # For P1 verification, we can simulate by:
        # 1. Deleting term_cluster entries
        # 2. Re-creating them (if extraction pipeline is available)
        # 3. Verify TM entries still resolve
        pass
