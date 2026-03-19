"""Project Statistics Service.

Computes project-level metrics with precise definitions and bounded ranges.
All coverage metrics are in range [0, 100].
"""

import logging
from dataclasses import dataclass

from sqlalchemy import exists, func
from sqlalchemy.orm import Session

from app.infra.sa_models import DictEntry, DictProject, DictSource, Lemma, TermCluster, TMEntry

logger = logging.getLogger(__name__)


@dataclass
class ProjectStats:
    """Project statistics with explicit metric definitions.

    All percentage metrics are in range [0.0, 100.0].
    Ratio metrics can exceed 1.0 (density metrics, not coverage).
    """

    # Project info
    project_id: int
    project_name: str

    # Counts
    document_count: int
    lemma_count: int
    term_cluster_count: int
    tm_entry_count: int
    dict_entry_count: int

    # Approved counts
    tm_approved_count: int
    term_approved_count: int

    # Covered counts (lemmas with at least one translation)
    lemmas_with_translation_count: int

    # Coverage metrics [0-100%]
    lemma_coverage_pct: float  # % of lemmas that have ≥1 translation

    # Approval rate metrics [0-100%]
    tm_approval_rate_pct: float  # % of TM entries that are approved
    term_approval_rate_pct: float  # % of term clusters that are approved

    # Density metrics (can exceed 100%)
    tm_entries_per_lemma_ratio: float  # Average TM entries per lemma (can be >1.0)
    tm_entries_per_lemma_pct: float  # Same as ratio * 100 (for backward compat)


class StatsService:
    """Service for computing project statistics."""

    def compute_project_stats(
        self, session: Session, project_id: int, *, translation_status_filter: str = "approved"
    ) -> ProjectStats:
        """Compute comprehensive project statistics.

        Args:
            session: Database session
            project_id: Project ID
            translation_status_filter: Which TM entry status counts as "translation"
                - "approved": Only approved TM entries (default)
                - "all": All TM entries (approved + draft + rejected + deprecated)

        Returns:
            ProjectStats with all computed metrics

        Note:
            All coverage metrics are bounded [0, 100].
            Density metrics (ratios) can exceed 100%.
        """
        # Get project
        project = session.query(DictProject).filter(DictProject.project_id == project_id).first()

        project_name = project.name if project else "Unknown"

        # === Basic counts ===

        # Documents (note: SourceDocument uses corpus_id, not project_id)
        # For M9, we use 0 as doc count (focus is on exports)
        document_count = 0

        # Total lemmas
        lemma_count = (
            session.query(func.count(Lemma.lemma_id))
            .filter(Lemma.project_id == project_id)
            .scalar()
            or 0
        )

        # Total term clusters
        term_cluster_count = (
            session.query(func.count(TermCluster.cluster_id))
            .filter(TermCluster.project_id == project_id)
            .scalar()
            or 0
        )

        # Total TM entries
        tm_entry_count = (
            session.query(func.count(TMEntry.tm_id))
            .filter(TMEntry.project_id == project_id)
            .scalar()
            or 0
        )

        # Total dictionary entries
        dict_entry_count = (
            session.query(func.count(DictEntry.dict_entry_id))
            .join(DictSource)
            .filter(DictSource.project_id == project_id)
            .scalar()
            or 0
        )

        # === Approved counts ===

        # Approved TM entries
        tm_approved_count = (
            session.query(func.count(TMEntry.tm_id))
            .filter(TMEntry.project_id == project_id, TMEntry.status == "approved")
            .scalar()
            or 0
        )

        # Approved term clusters
        term_approved_count = (
            session.query(func.count(TermCluster.cluster_id))
            .filter(TermCluster.project_id == project_id, TermCluster.curation_status == "approved")
            .scalar()
            or 0
        )

        # === Coverage metrics ===

        # Count lemmas that have at least one translation
        # (based on translation_status_filter)
        # Match strategy: TMEntry.src_text == Lemma.lemma_text (same as XLSX export logic)
        if translation_status_filter == "approved":
            # Count distinct lemma_id where there exists an approved TM entry of kind "lemma"
            lemmas_with_translation_count = (
                session.query(func.count(func.distinct(Lemma.lemma_id)))
                .filter(
                    Lemma.project_id == project_id,
                    exists().where(
                        TMEntry.project_id == project_id,
                        TMEntry.kind == "lemma",
                        TMEntry.status == "approved",
                        TMEntry.src_text == Lemma.lemma_text,
                    ),
                )
                .scalar()
                or 0
            )
        else:
            # Count all lemmas with any TM entry (regardless of status)
            lemmas_with_translation_count = (
                session.query(func.count(func.distinct(Lemma.lemma_id)))
                .filter(
                    Lemma.project_id == project_id,
                    exists().where(
                        TMEntry.project_id == project_id,
                        TMEntry.kind == "lemma",
                        TMEntry.src_text == Lemma.lemma_text,
                    ),
                )
                .scalar()
                or 0
            )

        # === Compute metrics ===

        # Lemma coverage: % of lemmas that have ≥1 translation [0-100]
        if lemma_count > 0:
            lemma_coverage_pct = 100.0 * lemmas_with_translation_count / lemma_count
        else:
            lemma_coverage_pct = 0.0

        # TM approval rate: % of TM entries that are approved [0-100]
        if tm_entry_count > 0:
            tm_approval_rate_pct = 100.0 * tm_approved_count / tm_entry_count
        else:
            tm_approval_rate_pct = 0.0

        # Term approval rate: % of term clusters that are approved [0-100]
        if term_cluster_count > 0:
            term_approval_rate_pct = 100.0 * term_approved_count / term_cluster_count
        else:
            term_approval_rate_pct = 0.0

        # TM entries per lemma (density metric, can exceed 1.0 / 100%)
        if lemma_count > 0:
            tm_entries_per_lemma_ratio = tm_approved_count / lemma_count
            tm_entries_per_lemma_pct = tm_entries_per_lemma_ratio * 100.0
        else:
            tm_entries_per_lemma_ratio = 0.0
            tm_entries_per_lemma_pct = 0.0

        logger.info(
            f"Project {project_id} stats: "
            f"{lemma_count} lemmas, {lemmas_with_translation_count} covered "
            f"({lemma_coverage_pct:.1f}% coverage), "
            f"{tm_approved_count} TM approved, "
            f"{tm_entries_per_lemma_pct:.1f}% density"
        )

        return ProjectStats(
            project_id=project_id,
            project_name=project_name,
            document_count=document_count,
            lemma_count=lemma_count,
            term_cluster_count=term_cluster_count,
            tm_entry_count=tm_entry_count,
            dict_entry_count=dict_entry_count,
            tm_approved_count=tm_approved_count,
            term_approved_count=term_approved_count,
            lemmas_with_translation_count=lemmas_with_translation_count,
            lemma_coverage_pct=lemma_coverage_pct,
            tm_approval_rate_pct=tm_approval_rate_pct,
            term_approval_rate_pct=term_approval_rate_pct,
            tm_entries_per_lemma_ratio=tm_entries_per_lemma_ratio,
            tm_entries_per_lemma_pct=tm_entries_per_lemma_pct,
        )
