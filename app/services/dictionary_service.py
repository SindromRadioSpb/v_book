"""
Dictionary service for paginated lemma queries.

Provides server-side pagination and filtering for Dictionary view.
"""

import logging
from typing import List, Tuple

from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from app.infra.sa_models import Lemma, LemmaProjectStat

logger = logging.getLogger(__name__)


class DictionaryService:
    """Service for Dictionary view queries with pagination support."""

    def search_lemmas(
        self,
        session: Session,
        project_id: int,
        filters: dict,
        limit: int = 100,
        offset: int = 0,
        sort_column: str = "freq_abs",
        sort_direction: str = "desc",
    ) -> List[Tuple[Lemma, LemmaProjectStat]]:
        """Search lemmas with pagination and filtering.

        Args:
            session: Database session
            project_id: Project ID
            filters: Filter dict with keys:
                - pos: POS filter ("All" or specific POS tag)
                - hide_noise: bool (if True, hide noise entries)
                - search: str (search text, LIKE on lemma_text)
            limit: Page size
            offset: Page offset
            sort_column: Column to sort by (default: "freq_abs")
            sort_direction: "asc" or "desc" (default: "desc")

        Returns:
            List of (Lemma, LemmaProjectStat) tuples for current page
        """
        stmt = select(Lemma, LemmaProjectStat).join(
            LemmaProjectStat,
            Lemma.lemma_id == LemmaProjectStat.lemma_id
        ).where(
            Lemma.project_id == project_id
        )

        # Apply filters
        stmt = self._apply_filters(stmt, filters)

        # Apply sort
        stmt = self._apply_sort(stmt, sort_column, sort_direction)

        # Apply pagination
        stmt = stmt.limit(limit).offset(offset)

        results = session.execute(stmt).all()
        return results

    def count_lemmas(
        self,
        session: Session,
        project_id: int,
        filters: dict,
    ) -> int:
        """Count total lemmas matching filters (for pagination).

        Args:
            session: Database session
            project_id: Project ID
            filters: Same filter dict as search_lemmas()

        Returns:
            Total count of matching lemmas
        """
        stmt = select(func.count()).select_from(Lemma).join(
            LemmaProjectStat,
            Lemma.lemma_id == LemmaProjectStat.lemma_id
        ).where(
            Lemma.project_id == project_id
        )

        # Apply same filters as search
        stmt = self._apply_filters(stmt, filters)

        count = session.execute(stmt).scalar()
        return count or 0

    def _apply_filters(self, stmt, filters: dict):
        """Apply filters to statement (shared by search and count)."""
        # POS filter
        pos_filter = filters.get("pos", "All")
        if pos_filter and pos_filter != "All":
            stmt = stmt.where(Lemma.pos == pos_filter)

        # Noise filter
        if filters.get("hide_noise", True):
            # Hide noise: is_noise = 0 OR is_noise IS NULL (backward compatibility)
            stmt = stmt.where(or_(Lemma.is_noise == 0, Lemma.is_noise.is_(None)))

        # Search filter (server-side LIKE on lemma_text)
        search = filters.get("search", "").strip()
        if search:
            stmt = stmt.where(Lemma.lemma_text.contains(search))

        return stmt

    def _apply_sort(self, stmt, sort_column: str, sort_direction: str):
        """Apply sorting to statement."""
        # Map UI column names to SQLAlchemy attributes
        sort_map = {
            "freq_abs": LemmaProjectStat.freq_abs,
            "doc_freq": LemmaProjectStat.doc_freq,
            "lemma_text": Lemma.lemma_text,
            "pos": Lemma.pos,
        }

        column_attr = sort_map.get(sort_column, LemmaProjectStat.freq_abs)

        if sort_direction == "asc":
            stmt = stmt.order_by(column_attr.asc())
        else:
            stmt = stmt.order_by(column_attr.desc())

        return stmt
