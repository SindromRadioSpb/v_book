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
from sqlalchemy import select, func, or_, and_, update

from app.infra.sa_models import TMEntry, TMEntryHistory, Lemma, TermCluster
from app.domain.dto import TMEntryDTO, TMHistoryDTO
from app.services.tm_global_service import TMGlobalService

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
        if "kind" in filters and filters["kind"]:
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
        sort_col = self.SORT_COLUMNS.get(sort_column, TMEntry.updated_at)
        if sort_direction == "asc":
            stmt = stmt.order_by(sort_col.asc())
        else:
            stmt = stmt.order_by(sort_col.desc())

        # Pagination
        stmt = stmt.limit(limit).offset(offset)

        # Execute
        results = session.execute(stmt).scalars().all()

        # Convert to DTOs
        return [self._entry_to_dto(entry) for entry in results]

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
        if "kind" in filters and filters["kind"]:
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
        TMGlobalService().upsert_and_link(session, entry)

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
        TMGlobalService().upsert_and_link(session, entry)

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
        )

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
