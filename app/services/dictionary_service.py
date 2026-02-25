"""
Dictionary service for paginated lemma queries.

Provides server-side pagination and filtering for Dictionary view.
"""

import logging
from typing import List, Tuple

from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from app.infra.sa_models import Lemma, LemmaProjectStat, TMEntry

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
        # For frequency-based sorts, start from lemma_project_stat to keep planner
        # aligned with project+freq indexes on very large corpora.
        if sort_column in {"freq_abs", "doc_freq"}:
            stmt = (
                select(Lemma, LemmaProjectStat)
                .select_from(LemmaProjectStat)
                .join(
                    Lemma,
                    (Lemma.lemma_id == LemmaProjectStat.lemma_id)
                    & (Lemma.project_id == LemmaProjectStat.project_id),
                )
                .where(
                    LemmaProjectStat.project_id == project_id,
                    Lemma.project_id == project_id,
                )
            )
        else:
            stmt = (
                select(Lemma, LemmaProjectStat)
                .select_from(Lemma)
                .join(
                    LemmaProjectStat,
                    (Lemma.lemma_id == LemmaProjectStat.lemma_id)
                    & (Lemma.project_id == LemmaProjectStat.project_id),
                )
                .where(
                    Lemma.project_id == project_id,
                    LemmaProjectStat.project_id == project_id,
                )
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
        # Count from lemma table only (filters apply to lemma fields); this avoids
        # an unnecessary join on every search refresh for large projects.
        stmt = select(func.count(Lemma.lemma_id)).where(Lemma.project_id == project_id)

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
        # Keep deterministic tie-break aligned with stats PK/index when sorting by
        # stats columns to avoid temp sort plans on very large projects.
        if sort_column in {"freq_abs", "doc_freq"}:
            tie_breaker = LemmaProjectStat.lemma_id
        else:
            tie_breaker = Lemma.lemma_id

        if sort_direction == "asc":
            stmt = stmt.order_by(column_attr.asc(), tie_breaker.asc())
        else:
            stmt = stmt.order_by(column_attr.desc(), tie_breaker.asc())

        return stmt

    def count_lemma_ids_for_translation(
        self,
        session: Session,
        project_id: int,
        filters: dict,
        write_mode: str,
    ) -> int:
        """Count lemmas matching filters for translation.

        Filters by empty translation if write_mode is FILL_EMPTY or SKIP_NON_EMPTY.

        Args:
            session: Database session
            project_id: Project ID
            filters: Same filter dict as search_lemmas()
            write_mode: "FILL_EMPTY" | "SKIP_NON_EMPTY" | "OVERWRITE"

        Returns:
            Total count of lemmas to translate
        """
        stmt = select(func.count(Lemma.lemma_id.distinct())).select_from(Lemma).join(
            LemmaProjectStat,
            (Lemma.lemma_id == LemmaProjectStat.lemma_id)
            & (Lemma.project_id == LemmaProjectStat.project_id)
        ).where(
            Lemma.project_id == project_id,
            LemmaProjectStat.project_id == project_id,
        )

        # Apply standard filters (pos, hide_noise, search)
        stmt = self._apply_filters(stmt, filters)

        # For FILL_EMPTY and SKIP_NON_EMPTY: only count lemmas without translation
        if write_mode in ("FILL_EMPTY", "SKIP_NON_EMPTY"):
            stmt = stmt.outerjoin(
                TMEntry,
                (TMEntry.lemma_id == Lemma.lemma_id) &
                (TMEntry.kind == "lemma") &
                (TMEntry.project_id == project_id)
            ).where(
                or_(
                    TMEntry.tm_id.is_(None),
                    TMEntry.translation.is_(None),
                    TMEntry.translation == ""
                )
            )

        count = session.execute(stmt).scalar()
        return count or 0

    def fetch_lemma_ids_for_translation(
        self,
        session: Session,
        project_id: int,
        filters: dict,
        write_mode: str,
        limit: int,
        offset: int,
    ) -> List[int]:
        """Fetch lemma IDs matching filters for translation (paginated).

        Args:
            session: Database session
            project_id: Project ID
            filters: Same filter dict as search_lemmas()
            write_mode: "FILL_EMPTY" | "SKIP_NON_EMPTY" | "OVERWRITE"
            limit: Chunk size
            offset: Offset for pagination

        Returns:
            List of lemma_id integers
        """
        stmt = select(Lemma.lemma_id).join(
            LemmaProjectStat,
            (Lemma.lemma_id == LemmaProjectStat.lemma_id)
            & (Lemma.project_id == LemmaProjectStat.project_id)
        ).where(
            Lemma.project_id == project_id,
            LemmaProjectStat.project_id == project_id,
        )

        # Apply standard filters (pos, hide_noise, search)
        stmt = self._apply_filters(stmt, filters)

        # For FILL_EMPTY and SKIP_NON_EMPTY: only fetch lemmas without translation
        if write_mode in ("FILL_EMPTY", "SKIP_NON_EMPTY"):
            stmt = stmt.outerjoin(
                TMEntry,
                (TMEntry.lemma_id == Lemma.lemma_id) &
                (TMEntry.kind == "lemma") &
                (TMEntry.project_id == project_id)
            ).where(
                or_(
                    TMEntry.tm_id.is_(None),
                    TMEntry.translation.is_(None),
                    TMEntry.translation == ""
                )
            )

        # Order by lemma_id for deterministic chunking
        stmt = stmt.order_by(Lemma.lemma_id.asc())

        # Apply pagination
        stmt = stmt.limit(limit).offset(offset)

        results = session.execute(stmt).scalars().all()
        return list(results)
