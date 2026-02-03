"""P2 QA/Coverage Service.

Provides coverage metrics and untranslated item lists:
- Lemma coverage (% of lemmas with translations)
- Term cluster coverage (% of clusters with translations)
- List untranslated items ranked by freq/termhood

Optimized for performance: 1-3 SQL queries per metric, no N+1.
"""

import logging
from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import select, func, and_, or_

from app.infra.sa_models import Lemma, LemmaProjectStat, TermCluster, TMEntry, DictEntry
from app.domain.dto import (
    CoverageMetrics,
    LemmaCoverageRow,
    TermClusterCoverageRow,
)

logger = logging.getLogger(__name__)


class CoverageService:
    """Service for QA/Coverage calculations."""

    def compute_lemma_coverage(
        self,
        session: Session,
        project_id: int,
        include_draft: bool = False,
    ) -> CoverageMetrics:
        """Compute lemma coverage for a project.

        Coverage = % of lemmas that have translations from TM or dict.

        Args:
            session: Database session
            project_id: Project ID
            include_draft: Include draft TM entries in coverage

        Returns:
            CoverageMetrics
        """
        # Count total lemmas
        stmt_total = (
            select(func.count())
            .select_from(Lemma)
            .where(Lemma.project_id == project_id)
        )
        total = session.execute(stmt_total).scalar() or 0

        if total == 0:
            return CoverageMetrics(total=0, covered=0, uncovered=0, coverage_pct=0.0)

        # Count covered lemmas using a single query with LEFT JOINs
        # A lemma is covered if it has a TM entry or dict entry
        from app.domain.normalization import normalize_for_tm

        # Build subquery for TM coverage
        tm_statuses = ["approved"]
        if include_draft:
            tm_statuses.append("draft")

        # We need to join lemmas with TM and dict to find coverage
        # Use DISTINCT to count unique lemmas
        stmt_covered = (
            select(func.count(func.distinct(Lemma.lemma_id)))
            .select_from(Lemma)
            .outerjoin(
                TMEntry,
                and_(
                    TMEntry.kind == "lemma",
                    TMEntry.project_id == project_id,
                    TMEntry.status.in_(tm_statuses),
                    # Match on normalized text
                    # Note: We can't directly normalize in SQL, so we match on src_text
                    # The normalization should have been done at TM creation time
                    TMEntry.src_text == Lemma.lemma_text,
                ),
            )
            .outerjoin(
                DictEntry,
                and_(
                    DictEntry.kind == "lemma",
                    DictEntry.status == "approved",
                    DictEntry.src_text == Lemma.lemma_text,
                ),
            )
            .where(
                and_(
                    Lemma.project_id == project_id,
                    or_(
                        TMEntry.tm_id.isnot(None),
                        DictEntry.dict_entry_id.isnot(None),
                    ),
                )
            )
        )

        covered = session.execute(stmt_covered).scalar() or 0
        uncovered = total - covered
        coverage_pct = (covered / total) * 100.0 if total > 0 else 0.0

        logger.info(
            f"Lemma coverage (project={project_id}, include_draft={include_draft}): "
            f"{covered}/{total} = {coverage_pct:.1f}%"
        )

        return CoverageMetrics(
            total=total,
            covered=covered,
            uncovered=uncovered,
            coverage_pct=coverage_pct,
        )

    def compute_termcluster_coverage(
        self,
        session: Session,
        project_id: int,
        include_draft: bool = False,
    ) -> CoverageMetrics:
        """Compute term cluster coverage for a project.

        Coverage = % of term clusters that have translations from TM or dict.

        Args:
            session: Database session
            project_id: Project ID
            include_draft: Include draft TM entries in coverage

        Returns:
            CoverageMetrics
        """
        # Count total clusters
        stmt_total = (
            select(func.count())
            .select_from(TermCluster)
            .where(TermCluster.project_id == project_id)
        )
        total = session.execute(stmt_total).scalar() or 0

        if total == 0:
            return CoverageMetrics(total=0, covered=0, uncovered=0, coverage_pct=0.0)

        # Count covered clusters
        tm_statuses = ["approved"]
        if include_draft:
            tm_statuses.append("draft")

        stmt_covered = (
            select(func.count(func.distinct(TermCluster.cluster_id)))
            .select_from(TermCluster)
            .outerjoin(
                TMEntry,
                and_(
                    TMEntry.kind == "term_cluster",
                    TMEntry.project_id == project_id,
                    TMEntry.status.in_(tm_statuses),
                    TMEntry.src_text == TermCluster.representative_he,
                ),
            )
            .outerjoin(
                DictEntry,
                and_(
                    DictEntry.kind == "term_cluster",
                    DictEntry.status == "approved",
                    DictEntry.src_text == TermCluster.representative_he,
                ),
            )
            .where(
                and_(
                    TermCluster.project_id == project_id,
                    or_(
                        TMEntry.tm_id.isnot(None),
                        DictEntry.dict_entry_id.isnot(None),
                    ),
                )
            )
        )

        covered = session.execute(stmt_covered).scalar() or 0
        uncovered = total - covered
        coverage_pct = (covered / total) * 100.0 if total > 0 else 0.0

        logger.info(
            f"TermCluster coverage (project={project_id}, include_draft={include_draft}): "
            f"{covered}/{total} = {coverage_pct:.1f}%"
        )

        return CoverageMetrics(
            total=total,
            covered=covered,
            uncovered=uncovered,
            coverage_pct=coverage_pct,
        )

    def list_untranslated_lemmas(
        self,
        session: Session,
        project_id: int,
        limit: int = 100,
        order_by: str = "freq",
        include_draft: bool = False,
    ) -> List[LemmaCoverageRow]:
        """List untranslated lemmas.

        Args:
            session: Database session
            project_id: Project ID
            limit: Maximum results
            order_by: Sort order ("freq" or "alpha")
            include_draft: Include draft TM entries as "translated"

        Returns:
            List of LemmaCoverageRow
        """
        tm_statuses = ["approved"]
        if include_draft:
            tm_statuses.append("draft")

        # Get untranslated lemmas
        # A lemma is untranslated if it has no TM entry and no dict entry
        stmt = (
            select(Lemma, LemmaProjectStat)
            .join(
                LemmaProjectStat,
                Lemma.lemma_id == LemmaProjectStat.lemma_id,
            )
            .outerjoin(
                TMEntry,
                and_(
                    TMEntry.kind == "lemma",
                    TMEntry.project_id == project_id,
                    TMEntry.status.in_(tm_statuses),
                    TMEntry.src_text == Lemma.lemma_text,
                ),
            )
            .outerjoin(
                DictEntry,
                and_(
                    DictEntry.kind == "lemma",
                    DictEntry.status == "approved",
                    DictEntry.src_text == Lemma.lemma_text,
                ),
            )
            .where(
                and_(
                    Lemma.project_id == project_id,
                    LemmaProjectStat.project_id == project_id,
                    TMEntry.tm_id.is_(None),
                    DictEntry.dict_entry_id.is_(None),
                )
            )
        )

        # Order by
        if order_by == "freq":
            stmt = stmt.order_by(LemmaProjectStat.freq_abs.desc())
        else:  # alpha
            stmt = stmt.order_by(Lemma.lemma_text.asc())

        stmt = stmt.limit(limit)

        # Execute
        results = session.execute(stmt).all()

        # Convert to DTOs
        rows = []
        for lemma, stat in results:
            rows.append(
                LemmaCoverageRow(
                    lemma_id=lemma.lemma_id,
                    lemma_text=lemma.lemma_text,
                    pos=lemma.pos,
                    freq_abs=stat.freq_abs,
                    doc_freq=stat.doc_freq,
                )
            )

        logger.info(
            f"Found {len(rows)} untranslated lemmas (project={project_id}, "
            f"order_by={order_by}, include_draft={include_draft})"
        )

        return rows

    def list_untranslated_termclusters(
        self,
        session: Session,
        project_id: int,
        limit: int = 100,
        order_by: str = "termhood",
        include_draft: bool = False,
    ) -> List[TermClusterCoverageRow]:
        """List untranslated term clusters.

        Args:
            session: Database session
            project_id: Project ID
            limit: Maximum results
            order_by: Sort order ("termhood", "freq", or "alpha")
            include_draft: Include draft TM entries as "translated"

        Returns:
            List of TermClusterCoverageRow
        """
        tm_statuses = ["approved"]
        if include_draft:
            tm_statuses.append("draft")

        # Get untranslated clusters
        stmt = (
            select(TermCluster)
            .outerjoin(
                TMEntry,
                and_(
                    TMEntry.kind == "term_cluster",
                    TMEntry.project_id == project_id,
                    TMEntry.status.in_(tm_statuses),
                    TMEntry.src_text == TermCluster.representative_he,
                ),
            )
            .outerjoin(
                DictEntry,
                and_(
                    DictEntry.kind == "term_cluster",
                    DictEntry.status == "approved",
                    DictEntry.src_text == TermCluster.representative_he,
                ),
            )
            .where(
                and_(
                    TermCluster.project_id == project_id,
                    TMEntry.tm_id.is_(None),
                    DictEntry.dict_entry_id.is_(None),
                )
            )
        )

        # Order by
        if order_by == "termhood":
            # Order by weirdness descending (proxy for termhood, nulls last)
            stmt = stmt.order_by(
                TermCluster.weirdness.desc().nulls_last(),
                TermCluster.freq_abs.desc(),
            )
        elif order_by == "freq":
            stmt = stmt.order_by(TermCluster.freq_abs.desc())
        else:  # alpha
            stmt = stmt.order_by(TermCluster.representative_he.asc())

        stmt = stmt.limit(limit)

        # Execute
        results = session.execute(stmt).scalars().all()

        # Convert to DTOs
        rows = []
        for cluster in results:
            rows.append(
                TermClusterCoverageRow(
                    cluster_id=cluster.cluster_id,
                    representative_he=cluster.representative_he,
                    canonical_key=cluster.canonical_key,
                    freq_abs=cluster.freq_abs,
                    doc_freq=cluster.doc_freq,
                    termhood_score=cluster.weirdness,  # Use weirdness as proxy for termhood
                )
            )

        logger.info(
            f"Found {len(rows)} untranslated term clusters (project={project_id}, "
            f"order_by={order_by}, include_draft={include_draft})"
        )

        return rows
