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
from sqlalchemy import select, func, or_, and_

from app.infra.sa_models import TMEntry, TMEntryHistory
from app.domain.dto import TMEntryDTO, TMHistoryDTO

logger = logging.getLogger(__name__)


class TranslationAdminService:
    """Service for TM entry administration."""

    def search_tm_entries(
        self,
        session: Session,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[TMEntryDTO]:
        """Search TM entries with filters.

        Args:
            session: Database session
            filters: Optional filters:
                - kind: str (lemma|ngram|term_cluster|surface)
                - status: str (draft|approved|rejected|deprecated)
                - scope: str (project|global)
                - project_id: int (only for scope=project)
                - src_lang: str
                - tgt_lang: str
                - search_text: str (search in src_text or translation)
                - source_ref: str
                - origin: str (user_edit|import|mt_accept|mt_auto|merge)
            limit: Maximum results
            offset: Pagination offset

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

        if "scope" in filters:
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

        # Order by most recently updated
        stmt = stmt.order_by(TMEntry.updated_at.desc())

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

        if "scope" in filters:
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

        session.commit()

        logger.info(f"Updated translation for TM entry {tm_id}")

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
