"""P2 Translation Administration Service.

Provides TM entry management:
- Search/filter TM entries
- Set status (approve/reject/deprecate)
- View history
- Revert to previous versions
- Update translations

All operations are transactional.
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_, and_, update, case

from app.infra.sa_models import (
    AudioAsset,
    PronunciationEntry,
    TMEntry,
    TMEntryHistory,
    Lemma,
    TermCluster,
    Ngram,
    StudyProgress,
    UserDictionaryItem,
)
from app.domain.dto import TMEntryDTO, TMHistoryDTO
from app.domain.normalization.normalizer import normalize_for_tm
from app.services.tm_global_service import TMGlobalService
from app.services.user_dictionary_service import UserDictionaryService

logger = logging.getLogger(__name__)


class TranslationAdminService:
    """Service for TM entry administration."""

    # SQL injection prevention: allowlist of sortable columns
    SORT_COLUMNS = {
        "tm_id": TMEntry.tm_id,
        "kind": TMEntry.kind,
        "src_text": TMEntry.src_text,
        "translation": TMEntry.translation,
        "status": TMEntry.status,
        "project_id": TMEntry.project_id,
        "origin": TMEntry.origin,
        "source_ref": TMEntry.source_ref,
        "updated_at": TMEntry.updated_at,
    }

    @staticmethod
    def _canonical_match_clause():
        return and_(
            UserDictionaryItem.src_lang == TMEntry.src_lang,
            UserDictionaryItem.tgt_lang == TMEntry.tgt_lang,
            UserDictionaryItem.kind == TMEntry.kind,
            UserDictionaryItem.src_norm == TMEntry.src_norm,
        )

    def _ud_marker_sort_expression(self):
        """Sortable rank for UD marker column: 0=none, 1=saved."""
        ud_count_subq = (
            select(func.count(UserDictionaryItem.item_id))
            .where(self._canonical_match_clause())
            .correlate(TMEntry)
            .scalar_subquery()
        )
        return case(
            (func.coalesce(ud_count_subq, 0) > 0, 1),
            else_=0,
        )

    def _last_review_sort_expression(self):
        """Sortable rank for Last Review column: Added(0), Again(1), Hard(2), Good(3), Easy(4)."""
        grade_rank = case(
            (StudyProgress.last_grade == "again", 1),
            (StudyProgress.last_grade == "hard", 2),
            (StudyProgress.last_grade == "good", 3),
            (StudyProgress.last_grade == "easy", 4),
            else_=0,
        )
        rank_subq = (
            select(func.max(grade_rank))
            .select_from(UserDictionaryItem)
            .outerjoin(StudyProgress, StudyProgress.id == UserDictionaryItem.study_progress_id)
            .where(self._canonical_match_clause())
            .correlate(TMEntry)
            .scalar_subquery()
        )
        return func.coalesce(rank_subq, 0)

    def _audio_status_sort_expression(self):
        """Sortable rank for audio status: missing(0), failed(1), ready(2)."""
        ready_subq = (
            select(func.count(AudioAsset.asset_id))
            .where(
                and_(
                    AudioAsset.lang == TMEntry.src_lang,
                    AudioAsset.norm_text == TMEntry.src_norm,
                    AudioAsset.asset_status == "ready",
                )
            )
            .correlate(TMEntry)
            .scalar_subquery()
        )
        failed_subq = (
            select(func.count(AudioAsset.asset_id))
            .where(
                and_(
                    AudioAsset.lang == TMEntry.src_lang,
                    AudioAsset.norm_text == TMEntry.src_norm,
                    AudioAsset.asset_status == "failed",
                )
            )
            .correlate(TMEntry)
            .scalar_subquery()
        )
        return case(
            (func.coalesce(ready_subq, 0) > 0, 2),
            (func.coalesce(failed_subq, 0) > 0, 1),
            else_=0,
        )

    def _pronunciation_sort_expression(self):
        """Server-safe expression for pronunciation sorting (sanitized effective text)."""
        pronunciation_subq = (
            select(
                func.coalesce(
                    func.nullif(
                        func.trim(
                            func.replace(func.replace(func.coalesce(PronunciationEntry.niqqud_text, ""), "_", " "), "|", " ")
                        ),
                        "",
                    ),
                    func.nullif(
                        func.trim(
                            func.replace(func.replace(func.coalesce(PronunciationEntry.reading_text, ""), "_", " "), "|", " ")
                        ),
                        "",
                    ),
                    "",
                )
            )
            .where(
                and_(
                    PronunciationEntry.lang == TMEntry.src_lang,
                    PronunciationEntry.src_norm == TMEntry.src_norm,
                )
            )
            .correlate(TMEntry)
            .scalar_subquery()
        )
        return pronunciation_subq

    def _resolve_sort_column(self, sort_column: str):
        """Return safe sort expression for requested column."""
        if sort_column == "ud_marker":
            return self._ud_marker_sort_expression()
        if sort_column == "last_review":
            return self._last_review_sort_expression()
        if sort_column == "audio_status":
            return self._audio_status_sort_expression()
        if sort_column == "pronunciation":
            return self._pronunciation_sort_expression()
        return self.SORT_COLUMNS.get(sort_column, TMEntry.updated_at)

    def search_tm_entries(
        self,
        session: Session,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0,
        sort_column: str = "updated_at",
        sort_direction: str = "desc",
    ) -> List[TMEntryDTO]:
        """Search TM entries with filters.

        Args:
            session: Database session
            filters: Optional filters:
                - kind: str (lemma|ngram|term_cluster|surface)
                - status: str (draft|approved|rejected|deprecated)
                - scope: str (project|global) — DEPRECATED, use project_ids instead
                - project_id: int (only for scope=project) — DEPRECATED
                - project_ids: List[int] (multi-project filter, -1 = global/None)
                - src_lang: str
                - tgt_lang: str
                - search_text: str (search in src_text or translation)
                - source_ref: str
                - origin: str (user_edit|import|mt_accept|mt_auto|merge)
            limit: Maximum results
            offset: Pagination offset
            sort_column: Column to sort by (validated against SORT_COLUMNS allowlist)
            sort_direction: Sort direction ("asc" or "desc")

        Returns:
            List of TMEntryDTO
        """
        filters = filters or {}

        # Build query
        stmt = select(TMEntry)

        # Apply filters
        # Support both legacy single-kind ("kind") and multi-select ("kinds" list)
        if "kinds" in filters and filters["kinds"]:
            kinds_list = [k for k in filters["kinds"] if k]
            if kinds_list:
                stmt = stmt.where(TMEntry.kind.in_(kinds_list))
        elif "kind" in filters and filters["kind"]:
            stmt = stmt.where(TMEntry.kind == filters["kind"])

        if "status" in filters and filters["status"]:
            stmt = stmt.where(TMEntry.status == filters["status"])

        # Multi-project filter (new) or legacy scope filter (deprecated)
        if "project_ids" in filters and filters["project_ids"] is not None:
            project_ids = filters["project_ids"]
            include_global = -1 in project_ids or None in project_ids
            real_ids = [pid for pid in project_ids if pid is not None and pid != -1]

            conditions = []
            if real_ids:
                conditions.append(TMEntry.project_id.in_(real_ids))
            if include_global:
                conditions.append(TMEntry.project_id.is_(None))

            if conditions:
                stmt = stmt.where(or_(*conditions))
            elif not real_ids and not include_global:
                # No projects selected = show nothing
                stmt = stmt.where(TMEntry.project_id == -999999)  # Never matches
        elif "scope" in filters:
            # Legacy scope filter (deprecated, kept for backward compat)
            if filters["scope"] == "global":
                stmt = stmt.where(TMEntry.project_id.is_(None))
            elif filters["scope"] == "project" and "project_id" in filters:
                stmt = stmt.where(TMEntry.project_id == filters["project_id"])

        if "src_lang" in filters and filters["src_lang"]:
            stmt = stmt.where(TMEntry.src_lang == filters["src_lang"])

        if "tgt_lang" in filters and filters["tgt_lang"]:
            stmt = stmt.where(TMEntry.tgt_lang == filters["tgt_lang"])

        if "search_text" in filters and filters["search_text"]:
            search = f"%{filters['search_text']}%"
            stmt = stmt.where(
                or_(
                    TMEntry.src_text.like(search),
                    TMEntry.translation.like(search),
                )
            )

        if "source_ref" in filters and filters["source_ref"]:
            stmt = stmt.where(TMEntry.source_ref == filters["source_ref"])

        if "origin" in filters and filters["origin"]:
            stmt = stmt.where(TMEntry.origin == filters["origin"])

        # Hide noise filter (same as Dictionary/Terms views)
        if filters.get("hide_noise", True):  # Default: hide noise
            stmt = stmt.where(or_(TMEntry.is_noise == 0, TMEntry.is_noise.is_(None)))

        # Server-side sorting
        sort_col = self._resolve_sort_column(sort_column)
        if sort_direction == "asc":
            stmt = stmt.order_by(sort_col.asc(), TMEntry.tm_id.asc())
        else:
            stmt = stmt.order_by(sort_col.desc(), TMEntry.tm_id.asc())

        # Pagination
        stmt = stmt.limit(limit).offset(offset)

        # Execute
        results = session.execute(stmt).scalars().all()

        # Convert to DTOs
        dtos = [self._entry_to_dto(entry) for entry in results]
        self._apply_study_overlays(session, dtos)
        return dtos

    def count_tm_entries(
        self,
        session: Session,
        filters: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Count TM entries matching filters.

        Args:
            session: Database session
            filters: Same as search_tm_entries

        Returns:
            Count of matching entries
        """
        filters = filters or {}

        # Build query
        stmt = select(func.count()).select_from(TMEntry)

        # Apply same filters as search
        if "kinds" in filters and filters["kinds"]:
            kinds_list = [k for k in filters["kinds"] if k]
            if kinds_list:
                stmt = stmt.where(TMEntry.kind.in_(kinds_list))
        elif "kind" in filters and filters["kind"]:
            stmt = stmt.where(TMEntry.kind == filters["kind"])

        if "status" in filters and filters["status"]:
            stmt = stmt.where(TMEntry.status == filters["status"])

        # Multi-project filter (same as search_tm_entries)
        if "project_ids" in filters and filters["project_ids"] is not None:
            project_ids = filters["project_ids"]
            include_global = -1 in project_ids or None in project_ids
            real_ids = [pid for pid in project_ids if pid is not None and pid != -1]

            conditions = []
            if real_ids:
                conditions.append(TMEntry.project_id.in_(real_ids))
            if include_global:
                conditions.append(TMEntry.project_id.is_(None))

            if conditions:
                stmt = stmt.where(or_(*conditions))
            elif not real_ids and not include_global:
                # No projects selected = show nothing
                stmt = stmt.where(TMEntry.project_id == -999999)  # Never matches
        elif "scope" in filters:
            # Legacy scope filter (deprecated, kept for backward compat)
            if filters["scope"] == "global":
                stmt = stmt.where(TMEntry.project_id.is_(None))
            elif filters["scope"] == "project" and "project_id" in filters:
                stmt = stmt.where(TMEntry.project_id == filters["project_id"])

        if "src_lang" in filters and filters["src_lang"]:
            stmt = stmt.where(TMEntry.src_lang == filters["src_lang"])

        if "tgt_lang" in filters and filters["tgt_lang"]:
            stmt = stmt.where(TMEntry.tgt_lang == filters["tgt_lang"])

        if "search_text" in filters and filters["search_text"]:
            search = f"%{filters['search_text']}%"
            stmt = stmt.where(
                or_(
                    TMEntry.src_text.like(search),
                    TMEntry.translation.like(search),
                )
            )

        if "source_ref" in filters and filters["source_ref"]:
            stmt = stmt.where(TMEntry.source_ref == filters["source_ref"])

        if "origin" in filters and filters["origin"]:
            stmt = stmt.where(TMEntry.origin == filters["origin"])

        # Hide noise filter (same as search_tm_entries)
        if filters.get("hide_noise", True):  # Default: hide noise
            stmt = stmt.where(or_(TMEntry.is_noise == 0, TMEntry.is_noise.is_(None)))

        # Execute
        count = session.execute(stmt).scalar()
        return count or 0

    def count_tm_ids_for_translation(
        self,
        session: Session,
        filters: Optional[Dict[str, Any]],
        write_mode: str,
    ) -> int:
        """Count TM entry IDs eligible for batch translation.

        Applies the same filters as TM search, plus write mode semantics:
        - FILL_EMPTY / SKIP_NON_EMPTY: only rows with empty translation
        - OVERWRITE: all filtered rows
        """
        filters = filters or {}

        stmt = select(func.count()).select_from(TMEntry)

        # Apply same filters as search/count
        if "kinds" in filters and filters["kinds"]:
            kinds_list = [k for k in filters["kinds"] if k]
            if kinds_list:
                stmt = stmt.where(TMEntry.kind.in_(kinds_list))
        elif "kind" in filters and filters["kind"]:
            stmt = stmt.where(TMEntry.kind == filters["kind"])

        if "status" in filters and filters["status"]:
            stmt = stmt.where(TMEntry.status == filters["status"])

        if "project_ids" in filters and filters["project_ids"] is not None:
            project_ids = filters["project_ids"]
            include_global = -1 in project_ids or None in project_ids
            real_ids = [pid for pid in project_ids if pid is not None and pid != -1]

            conditions = []
            if real_ids:
                conditions.append(TMEntry.project_id.in_(real_ids))
            if include_global:
                conditions.append(TMEntry.project_id.is_(None))

            if conditions:
                stmt = stmt.where(or_(*conditions))
            elif not real_ids and not include_global:
                stmt = stmt.where(TMEntry.project_id == -999999)
        elif "scope" in filters:
            if filters["scope"] == "global":
                stmt = stmt.where(TMEntry.project_id.is_(None))
            elif filters["scope"] == "project" and "project_id" in filters:
                stmt = stmt.where(TMEntry.project_id == filters["project_id"])

        if "src_lang" in filters and filters["src_lang"]:
            stmt = stmt.where(TMEntry.src_lang == filters["src_lang"])

        if "tgt_lang" in filters and filters["tgt_lang"]:
            stmt = stmt.where(TMEntry.tgt_lang == filters["tgt_lang"])

        if "search_text" in filters and filters["search_text"]:
            search = f"%{filters['search_text']}%"
            stmt = stmt.where(
                or_(
                    TMEntry.src_text.like(search),
                    TMEntry.translation.like(search),
                )
            )

        if "source_ref" in filters and filters["source_ref"]:
            stmt = stmt.where(TMEntry.source_ref == filters["source_ref"])

        if "origin" in filters and filters["origin"]:
            stmt = stmt.where(TMEntry.origin == filters["origin"])

        if filters.get("hide_noise", True):
            stmt = stmt.where(or_(TMEntry.is_noise == 0, TMEntry.is_noise.is_(None)))

        # Write mode filter
        if write_mode in ("FILL_EMPTY", "SKIP_NON_EMPTY"):
            stmt = stmt.where(
                or_(
                    TMEntry.translation.is_(None),
                    func.trim(TMEntry.translation) == "",
                )
            )

        count = session.execute(stmt).scalar()
        return count or 0

    def fetch_tm_ids_for_translation(
        self,
        session: Session,
        filters: Optional[Dict[str, Any]],
        write_mode: str,
        limit: int,
        offset: int,
    ) -> List[int]:
        """Fetch TM entry IDs for batch translation in deterministic order."""
        filters = filters or {}

        stmt = select(TMEntry.tm_id)

        # Apply same filters as search/count
        if "kinds" in filters and filters["kinds"]:
            kinds_list = [k for k in filters["kinds"] if k]
            if kinds_list:
                stmt = stmt.where(TMEntry.kind.in_(kinds_list))
        elif "kind" in filters and filters["kind"]:
            stmt = stmt.where(TMEntry.kind == filters["kind"])

        if "status" in filters and filters["status"]:
            stmt = stmt.where(TMEntry.status == filters["status"])

        if "project_ids" in filters and filters["project_ids"] is not None:
            project_ids = filters["project_ids"]
            include_global = -1 in project_ids or None in project_ids
            real_ids = [pid for pid in project_ids if pid is not None and pid != -1]

            conditions = []
            if real_ids:
                conditions.append(TMEntry.project_id.in_(real_ids))
            if include_global:
                conditions.append(TMEntry.project_id.is_(None))

            if conditions:
                stmt = stmt.where(or_(*conditions))
            elif not real_ids and not include_global:
                stmt = stmt.where(TMEntry.project_id == -999999)
        elif "scope" in filters:
            if filters["scope"] == "global":
                stmt = stmt.where(TMEntry.project_id.is_(None))
            elif filters["scope"] == "project" and "project_id" in filters:
                stmt = stmt.where(TMEntry.project_id == filters["project_id"])

        if "src_lang" in filters and filters["src_lang"]:
            stmt = stmt.where(TMEntry.src_lang == filters["src_lang"])

        if "tgt_lang" in filters and filters["tgt_lang"]:
            stmt = stmt.where(TMEntry.tgt_lang == filters["tgt_lang"])

        if "search_text" in filters and filters["search_text"]:
            search = f"%{filters['search_text']}%"
            stmt = stmt.where(
                or_(
                    TMEntry.src_text.like(search),
                    TMEntry.translation.like(search),
                )
            )

        if "source_ref" in filters and filters["source_ref"]:
            stmt = stmt.where(TMEntry.source_ref == filters["source_ref"])

        if "origin" in filters and filters["origin"]:
            stmt = stmt.where(TMEntry.origin == filters["origin"])

        if filters.get("hide_noise", True):
            stmt = stmt.where(or_(TMEntry.is_noise == 0, TMEntry.is_noise.is_(None)))

        # Write mode filter
        if write_mode in ("FILL_EMPTY", "SKIP_NON_EMPTY"):
            stmt = stmt.where(
                or_(
                    TMEntry.translation.is_(None),
                    func.trim(TMEntry.translation) == "",
                )
            )

        stmt = stmt.order_by(TMEntry.tm_id.asc()).limit(limit).offset(offset)
        return list(session.execute(stmt).scalars().all())

    def get_entry(self, session: Session, tm_id: int) -> Optional[TMEntryDTO]:
        """Get single TM entry by ID.

        Args:
            session: Database session
            tm_id: TM entry ID

        Returns:
            TMEntryDTO or None if not found
        """
        stmt = select(TMEntry).where(TMEntry.tm_id == tm_id)
        entry = session.execute(stmt).scalar()

        if not entry:
            return None

        return self._entry_to_dto(entry)

    def set_status(
        self,
        session: Session,
        tm_id: int,
        status: str,
        approved_by: Optional[str] = None,
    ) -> None:
        """Set status for a TM entry.

        Args:
            session: Database session
            tm_id: TM entry ID
            status: New status (approved|rejected|deprecated)
            approved_by: Optional approver identifier

        Raises:
            ValueError: If entry not found or invalid status
        """
        if status not in ("approved", "rejected", "deprecated", "draft"):
            raise ValueError(f"Invalid status: {status}")

        stmt = select(TMEntry).where(TMEntry.tm_id == tm_id)
        entry = session.execute(stmt).scalar()

        if not entry:
            raise ValueError(f"TM entry not found: {tm_id}")

        # Create history entry
        # Map status to change_kind (status uses -ed suffix, change_kind doesn't)
        change_kind_map = {
            "approved": "approve",
            "rejected": "reject",
            "deprecated": "deprecate",
            "draft": "edit",
        }
        change_kind = change_kind_map.get(status, "edit")
        self._create_history_entry(session, entry, change_kind=change_kind)

        # Update status
        old_status = entry.status
        entry.status = status
        entry.updated_at = datetime.now()

        if status == "approved":
            entry.approved_at = datetime.now()
            entry.approved_by = approved_by or "ui"
        elif status in ("rejected", "deprecated"):
            # Clear approval info for rejected/deprecated
            entry.approved_at = None
            entry.approved_by = None

        # PATCH-19-02: Upsert tm_global and link
        session.flush()
        TMGlobalService().upsert_and_link(session, entry)

        session.commit()

        logger.info(f"TM entry {tm_id} status: {old_status} → {status}")

    def bulk_set_status(
        self,
        session: Session,
        tm_ids: List[int],
        status: str,
        approved_by: Optional[str] = None,
    ) -> int:
        """Set status for multiple TM entries in a single transaction.

        Args:
            session: Database session
            tm_ids: List of TM entry IDs
            status: New status
            approved_by: Optional approver identifier

        Returns:
            Number of entries updated

        Raises:
            ValueError: If invalid status
        """
        if status not in ("approved", "rejected", "deprecated", "draft"):
            raise ValueError(f"Invalid status: {status}")

        # Get all entries
        stmt = select(TMEntry).where(TMEntry.tm_id.in_(tm_ids))
        entries = session.execute(stmt).scalars().all()

        count = 0
        # Map status to change_kind
        change_kind_map = {
            "approved": "approve",
            "rejected": "reject",
            "deprecated": "deprecate",
            "draft": "edit",
        }
        change_kind = change_kind_map.get(status, "edit")

        for entry in entries:
            # Create history
            self._create_history_entry(session, entry, change_kind=change_kind)

            # Update
            entry.status = status
            entry.updated_at = datetime.now()

            if status == "approved":
                entry.approved_at = datetime.now()
                entry.approved_by = approved_by or "ui"
            elif status in ("rejected", "deprecated"):
                # Clear approval info for rejected/deprecated
                entry.approved_at = None
                entry.approved_by = None

            count += 1

        # PATCH-19-02: Upsert tm_global and link for all entries
        session.flush()
        for entry in entries:
            TMGlobalService().upsert_and_link(session, entry)

        session.commit()

        logger.info(f"Bulk set status {status} for {count} entries")
        return count

    def get_history(self, session: Session, tm_id: int) -> List[TMHistoryDTO]:
        """Get history entries for a TM entry.

        Args:
            session: Database session
            tm_id: TM entry ID

        Returns:
            List of TMHistoryDTO, ordered by version descending
        """
        stmt = (
            select(TMEntryHistory)
            .where(TMEntryHistory.tm_id == tm_id)
            .order_by(TMEntryHistory.version.desc())
        )
        history_entries = session.execute(stmt).scalars().all()

        return [self._history_to_dto(h) for h in history_entries]

    def revert(
        self,
        session: Session,
        tm_id: int,
        version: int,
        approved_by: Optional[str] = None,
    ) -> None:
        """Revert TM entry to a previous version.

        Args:
            session: Database session
            tm_id: TM entry ID
            version: Version to revert to
            approved_by: Optional approver identifier

        Raises:
            ValueError: If entry or version not found
        """
        # Get current entry
        stmt = select(TMEntry).where(TMEntry.tm_id == tm_id)
        entry = session.execute(stmt).scalar()

        if not entry:
            raise ValueError(f"TM entry not found: {tm_id}")

        # Get target version
        stmt = select(TMEntryHistory).where(
            and_(
                TMEntryHistory.tm_id == tm_id,
                TMEntryHistory.version == version,
            )
        )
        target_version = session.execute(stmt).scalar()

        if not target_version:
            raise ValueError(f"Version {version} not found for TM entry {tm_id}")

        # Create history entry for current state before reverting
        self._create_history_entry(session, entry, change_kind="revert")

        # Revert
        entry.translation = target_version.translation
        entry.notes = target_version.notes
        entry.status = target_version.status
        entry.origin = "user_edit"  # P2 FIX: Use allowed origin (history tracks revert via change_kind)
        entry.updated_at = datetime.now()

        if entry.status == "approved":
            entry.approved_at = datetime.now()
            if approved_by:
                entry.approved_by = approved_by

        # PATCH-19-02: Upsert tm_global and link
        session.flush()
        TMGlobalService().upsert_and_link(
            session,
            entry,
            force_global_update=(not bool((entry.translation or "").strip())),
        )

        session.commit()

        logger.info(f"Reverted TM entry {tm_id} to version {version}")

    def update_translation(
        self,
        session: Session,
        tm_id: int,
        translation: str,
        notes: Optional[str] = None,
    ) -> None:
        """Update translation for a TM entry.

        Args:
            session: Database session
            tm_id: TM entry ID
            translation: New translation
            notes: Optional notes

        Raises:
            ValueError: If entry not found
        """
        stmt = select(TMEntry).where(TMEntry.tm_id == tm_id)
        entry = session.execute(stmt).scalar()

        if not entry:
            raise ValueError(f"TM entry not found: {tm_id}")

        # Create history entry
        self._create_history_entry(session, entry, change_kind="edit")

        # Update
        entry.translation = translation
        if notes is not None:
            entry.notes = notes
        entry.origin = "user_edit"
        entry.updated_at = datetime.now()

        # PATCH-19-02: Upsert tm_global and link
        session.flush()
        TMGlobalService().upsert_and_link(
            session,
            entry,
            force_global_update=(not bool((translation or "").strip())),
        )

        session.commit()

        logger.info(f"Updated translation for TM entry {tm_id}")

    def set_noise_status_bulk(
        self,
        session: Session,
        tm_ids: List[int],
        is_noise: bool,
        noise_reason: Optional[str] = None,
    ) -> int:
        """Set noise status for multiple TM entries.

        Args:
            session: Database session
            tm_ids: List of TM entry IDs
            is_noise: True = mark as noise, False = mark as valid
            noise_reason: Optional reason code (e.g., NOISE_PUNCT_ONLY)

        Returns:
            Number of entries updated
        """
        if not tm_ids:
            return 0

        noise_value = 1 if is_noise else 0

        stmt = (
            select(TMEntry)
            .where(TMEntry.tm_id.in_(tm_ids))
        )
        entries = session.execute(stmt).scalars().all()

        count = 0
        # Track source IDs for bidirectional sync
        lemma_ids_to_update = set()
        cluster_ids_to_update = set()

        for entry in entries:
            entry.is_noise = noise_value
            entry.noise_reason = noise_reason if is_noise else None
            entry.updated_at = datetime.now()
            count += 1

            # Collect source IDs for bidirectional sync
            if entry.kind == 'lemma' and entry.lemma_id:
                lemma_ids_to_update.add(entry.lemma_id)
            elif entry.kind == 'term_cluster' and entry.cluster_id:
                cluster_ids_to_update.add(entry.cluster_id)

        # Bidirectional sync: Update source tables to maintain Single Source of Truth
        if lemma_ids_to_update:
            from app.infra.sa_models import Lemma
            session.execute(
                update(Lemma)
                .where(Lemma.lemma_id.in_(lemma_ids_to_update))
                .values(is_noise=noise_value, noise_reason=noise_reason if is_noise else None)
            )
            logger.info(f"Synced is_noise to {len(lemma_ids_to_update)} lemmas")

        if cluster_ids_to_update:
            from app.infra.sa_models import TermCluster
            session.execute(
                update(TermCluster)
                .where(TermCluster.cluster_id.in_(cluster_ids_to_update))
                .values(is_noise=noise_value, noise_reason=noise_reason if is_noise else None)
            )
            logger.info(f"Synced is_noise to {len(cluster_ids_to_update)} term clusters")

        # PATCH-19-02: Upsert tm_global and link for all entries
        session.flush()
        for entry in entries:
            TMGlobalService().upsert_and_link(session, entry)

        session.commit()

        action = "noise" if is_noise else "valid"
        logger.info(f"Marked {count} TM entries as {action}")

        return count

    def _entry_to_dto(self, entry: TMEntry) -> TMEntryDTO:
        """Convert TMEntry model to DTO."""
        return TMEntryDTO(
            tm_id=entry.tm_id,
            project_id=entry.project_id,
            kind=entry.kind,
            src_lang=entry.src_lang,
            tgt_lang=entry.tgt_lang,
            src_text=entry.src_text,
            src_norm=entry.src_norm,
            translation=entry.translation,
            translation_norm=entry.translation_norm,
            pos=entry.pos,
            domain=entry.domain,
            notes=entry.notes,
            status=entry.status,
            confidence=entry.confidence,
            origin=entry.origin,
            source_ref=entry.source_ref,
            created_at=str(entry.created_at),
            updated_at=str(entry.updated_at),
            approved_at=str(entry.approved_at) if entry.approved_at else None,
            approved_by=entry.approved_by,
            is_noise=entry.is_noise,
            noise_reason=entry.noise_reason,
            norm_text=entry.norm_text,
            lemma_id=entry.lemma_id,
            cluster_id=entry.cluster_id,
            ngram_id=entry.ngram_id,
            tm_global_id=entry.tm_global_id,  # PATCH-19-03
            raw_src_norm=None,
        )

    @staticmethod
    def _resolve_tm_raw_norms(session: Session, entries: List[TMEntryDTO]) -> Dict[int, str]:
        """Resolve legacy/raw source norms from linked lexical entities."""
        if not entries:
            return {}

        lemma_ids = sorted({int(entry.lemma_id) for entry in entries if entry.lemma_id})
        cluster_ids = sorted({int(entry.cluster_id) for entry in entries if entry.cluster_id})
        ngram_ids = sorted({int(entry.ngram_id) for entry in entries if entry.ngram_id})

        lemma_norm_by_id: Dict[int, str] = {}
        cluster_norm_by_id: Dict[int, str] = {}
        ngram_norm_by_id: Dict[int, str] = {}

        if lemma_ids:
            for lemma_id, norm_text in session.execute(
                select(Lemma.lemma_id, Lemma.norm_text).where(Lemma.lemma_id.in_(lemma_ids))
            ).all():
                lemma_norm_by_id[int(lemma_id)] = (norm_text or "").strip()

        if cluster_ids:
            for cluster_id, norm_text in session.execute(
                select(TermCluster.cluster_id, TermCluster.norm_text).where(TermCluster.cluster_id.in_(cluster_ids))
            ).all():
                cluster_norm_by_id[int(cluster_id)] = (norm_text or "").strip()

        if ngram_ids:
            for ngram_id, he_canonical in session.execute(
                select(Ngram.ngram_id, Ngram.he_canonical).where(Ngram.ngram_id.in_(ngram_ids))
            ).all():
                ngram_norm_by_id[int(ngram_id)] = (he_canonical or "").strip()

        resolved: Dict[int, str] = {}
        for entry in entries:
            raw_norm = normalize_for_tm(entry.src_lang, entry.src_text, "surface").norm
            raw_norm = (raw_norm or "").strip()
            if entry.kind == "lemma" and entry.lemma_id:
                raw_norm = raw_norm or lemma_norm_by_id.get(int(entry.lemma_id), "")
            elif entry.kind == "term_cluster" and entry.cluster_id:
                raw_norm = raw_norm or cluster_norm_by_id.get(int(entry.cluster_id), "")
            elif entry.kind == "ngram" and entry.ngram_id:
                raw_norm = raw_norm or ngram_norm_by_id.get(int(entry.ngram_id), "")

            raw_norm = (raw_norm or "").strip()
            if not raw_norm:
                raw_norm = (entry.norm_text or "").strip()
            if not raw_norm:
                raw_norm = (entry.src_norm or "").strip()
            resolved[int(entry.tm_id)] = raw_norm
        return resolved

    def _apply_study_overlays(self, session: Session, entries: List[TMEntryDTO]) -> None:
        """Attach non-intrusive study tooltip metadata for TM panel rows."""
        if not entries:
            return

        user_dict_service = UserDictionaryService()
        raw_norms_by_tm_id = self._resolve_tm_raw_norms(session, entries)
        payloads = []
        overlay_hash_by_tm_id: Dict[int, str] = {}
        for entry in entries:
            raw_src_norm = (raw_norms_by_tm_id.get(int(entry.tm_id)) or "").strip()
            canonical_norm = user_dict_service._canonical_src_norm(
                src_lang=entry.src_lang,
                src_text=entry.src_text,
                kind=entry.kind,
                fallback_norm=(entry.src_norm or "").strip(),
            )
            overlay_hash_by_tm_id[int(entry.tm_id)] = user_dict_service.build_canonical_hash(
                entry.src_lang,
                entry.tgt_lang,
                entry.kind,
                canonical_norm,
            )
            entry.raw_src_norm = raw_src_norm
            payloads.append(
                {
                    "src_lang": entry.src_lang,
                    "tgt_lang": entry.tgt_lang,
                    "kind": entry.kind,
                    "src_text": entry.src_text,
                    "src_norm": entry.src_norm,
                    "raw_src_norm": raw_src_norm,
                }
            )

        try:
            overlay_map = user_dict_service.resolve_cross_view_status(session, payloads)
        except Exception as e:
            logger.warning("Failed to resolve TM study overlays: %s", e)
            return

        pronunciation_pairs = []
        for entry in entries:
            raw_src_norm = (entry.raw_src_norm or "").strip()
            if raw_src_norm:
                pronunciation_pairs.append((entry.src_lang, raw_src_norm))
            canonical_norm = (entry.src_norm or "").strip()
            if canonical_norm:
                pronunciation_pairs.append((entry.src_lang, canonical_norm))
        pronunciation_map = user_dict_service._resolve_pronunciation_overlay(session, pronunciation_pairs)

        for entry in entries:
            canonical_hash = overlay_hash_by_tm_id.get(int(entry.tm_id))
            if not canonical_hash:
                canonical_hash = user_dict_service.build_canonical_hash(
                    entry.src_lang,
                    entry.tgt_lang,
                    entry.kind,
                    entry.src_norm,
                )
            overlay = overlay_map.get(canonical_hash) or {}
            if overlay:
                entry.in_user_dictionary_count = int(overlay.get("in_user_dictionary_count") or 0)
                entry.study_state = overlay.get("study_state")
                entry.study_due_human = overlay.get("study_due_human")
                entry.last_grade = overlay.get("last_grade")
                entry.last_graded_at = overlay.get("last_graded_at")
                entry.study_tooltip = overlay.get("study_tooltip")
                entry.audio_status = overlay.get("audio_status")
                entry.pronunciation_text = overlay.get("pronunciation_text")
                entry.pronunciation_source = overlay.get("pronunciation_source")
                entry.pronunciation_confidence = overlay.get("pronunciation_confidence")
                entry.pronunciation_qc = overlay.get("pronunciation_qc")

            row_pron = pronunciation_map.get((entry.src_lang, (entry.raw_src_norm or "").strip()))
            if not row_pron:
                row_pron = pronunciation_map.get((entry.src_lang, (entry.src_norm or "").strip()))
            if row_pron:
                entry.pronunciation_text = row_pron.get("pronunciation_text")
                entry.pronunciation_source = row_pron.get("pronunciation_source")
                entry.pronunciation_confidence = row_pron.get("pronunciation_confidence")
                entry.pronunciation_qc = row_pron.get("pronunciation_qc")

    def _history_to_dto(self, history: TMEntryHistory) -> TMHistoryDTO:
        """Convert TMEntryHistory model to DTO."""
        return TMHistoryDTO(
            hist_id=history.hist_id,
            tm_id=history.tm_id,
            version=history.version,
            translation=history.translation,
            notes=history.notes,
            status=history.status,
            origin=history.origin,
            changed_at=str(history.changed_at),
            change_kind=history.change_kind,
        )

    def _create_history_entry(
        self,
        session: Session,
        entry: TMEntry,
        change_kind: str,
    ) -> None:
        """Create history entry for current state of TM entry.

        Args:
            session: Database session
            entry: TMEntry instance
            change_kind: Type of change (edit|approve|reject|deprecate|revert)
        """
        # Get current max version
        stmt = (
            select(func.max(TMEntryHistory.version))
            .where(TMEntryHistory.tm_id == entry.tm_id)
        )
        max_version = session.execute(stmt).scalar()
        next_version = (max_version or 0) + 1

        # Create history entry
        history = TMEntryHistory(
            tm_id=entry.tm_id,
            version=next_version,
            translation=entry.translation,
            notes=entry.notes,
            status=entry.status,
            origin=entry.origin,
            changed_at=datetime.now(),
            change_kind=change_kind,
        )
        session.add(history)
        session.flush()
