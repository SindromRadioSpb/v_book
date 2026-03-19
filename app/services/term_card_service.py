"""Term Card Service - M8 Term Curation.

Provides term curation workflow:
- Status management (auto → needs_review → approved/rejected)
- Alias management (variant matching)
- Stopword actions (mark terms as noise)
- Pin translation/example (override defaults)
- Review queue (filtered term lists for curation)
"""

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domain.dto import TermCardDTO
from app.infra.sa_models import (
    DocumentSentence,
    StopwordItem,
    StopwordSet,
    TermAlias,
    TermCluster,
    utc_now,
)


class TermCardService:
    """Service for term curation operations (M8)."""

    # ============================================================================
    # Core CRUD
    # ============================================================================

    def get_card(
        self,
        session: Session,
        project_id: int,
        cluster_id: int | None = None,
        canonical_key: str | None = None,
    ) -> TermCardDTO | None:
        """Get term card by cluster_id or canonical_key.

        Args:
            session: Database session
            project_id: Project ID
            cluster_id: Cluster ID (if known)
            canonical_key: Canonical key (alternative lookup)

        Returns:
            TermCardDTO if found, None otherwise
        """
        query = session.query(TermCluster).filter(TermCluster.project_id == project_id)

        if cluster_id is not None:
            query = query.filter(TermCluster.cluster_id == cluster_id)
        elif canonical_key is not None:
            query = query.filter(TermCluster.canonical_key == canonical_key)
        else:
            raise ValueError("Must provide either cluster_id or canonical_key")

        cluster = query.first()
        if not cluster:
            return None

        return self._cluster_to_dto(session, cluster)

    def _cluster_to_dto(self, session: Session, cluster: TermCluster) -> TermCardDTO:
        """Convert TermCluster ORM model to DTO.

        Args:
            session: Database session
            cluster: TermCluster ORM instance

        Returns:
            TermCardDTO
        """
        # Get aliases for this term
        aliases = (
            session.query(TermAlias)
            .filter(
                TermAlias.project_id == cluster.project_id,
                TermAlias.canonical == cluster.canonical_key,
            )
            .all()
        )
        alias_variants = [alias.variant for alias in aliases]

        # Check if marked as stopword
        is_stopword = self._is_stopword(session, cluster.project_id, cluster.canonical_key)

        # Get pinned example sentence text (if set)
        pinned_example_text = None
        if cluster.pinned_example_sent_id:
            sent = (
                session.query(DocumentSentence)
                .filter(DocumentSentence.sentence_id == cluster.pinned_example_sent_id)
                .first()
            )
            if sent:
                pinned_example_text = sent.text

        return TermCardDTO(
            cluster_id=cluster.cluster_id,
            project_id=cluster.project_id,
            canonical_key=cluster.canonical_key,
            representative_he=cluster.representative_he,
            representative_lemma=cluster.representative_lemma,
            freq_abs=cluster.freq_abs,
            doc_freq=cluster.doc_freq,
            members_count=cluster.members_count,
            best_pmi=cluster.best_pmi,
            best_llr=cluster.best_llr,
            best_dice=cluster.best_dice,
            best_tscore=cluster.best_tscore,
            tfidf=cluster.tfidf,
            weirdness=cluster.weirdness,
            source_kinds=cluster.source_kinds,
            curation_status=cluster.curation_status,
            pinned_translation=cluster.pinned_translation,
            pinned_translation_lang=cluster.pinned_translation_lang,
            pinned_example_sent_id=cluster.pinned_example_sent_id,
            pinned_example_text=pinned_example_text,
            curation_notes=cluster.curation_notes,
            curated_at=cluster.curated_at,
            curated_by=cluster.curated_by,
            aliases=alias_variants,
            is_stopword=is_stopword,
            created_at=cluster.created_at,
            updated_at=cluster.updated_at,
        )

    # ============================================================================
    # Status Workflow
    # ============================================================================

    def set_status(
        self,
        session: Session,
        cluster_id: int,
        status: str,
        curated_by: str,
        notes: str | None = None,
    ) -> bool:
        """Set curation status for a term.

        Args:
            session: Database session
            cluster_id: Term cluster ID
            status: New status (auto/needs_review/approved/rejected)
            curated_by: Curator identifier
            notes: Optional curation notes

        Returns:
            True if updated, False if cluster not found

        Raises:
            ValueError: If status is invalid
        """
        valid_statuses = ("auto", "needs_review", "approved", "rejected")
        if status not in valid_statuses:
            raise ValueError(f"Invalid status: {status}. Must be one of {valid_statuses}")

        cluster = session.query(TermCluster).filter(TermCluster.cluster_id == cluster_id).first()
        if not cluster:
            return False

        cluster.curation_status = status
        cluster.curated_at = utc_now()
        cluster.curated_by = curated_by
        if notes is not None:
            cluster.curation_notes = notes

        session.flush()
        return True

    def bulk_set_status(
        self,
        session: Session,
        cluster_ids: list[int],
        status: str,
        curated_by: str,
    ) -> int:
        """Set status for multiple terms in bulk.

        Args:
            session: Database session
            cluster_ids: List of cluster IDs
            status: New status
            curated_by: Curator identifier

        Returns:
            Number of clusters updated
        """
        valid_statuses = ("auto", "needs_review", "approved", "rejected")
        if status not in valid_statuses:
            raise ValueError(f"Invalid status: {status}")

        if not cluster_ids:
            return 0

        now = utc_now()
        count = (
            session.query(TermCluster)
            .filter(TermCluster.cluster_id.in_(cluster_ids))
            .update(
                {
                    "curation_status": status,
                    "curated_at": now,
                    "curated_by": curated_by,
                },
                synchronize_session=False,
            )
        )

        session.flush()
        return count

    # ============================================================================
    # Alias Management
    # ============================================================================

    def add_alias(
        self,
        session: Session,
        project_id: int,
        canonical_key: str,
        variant: str,
        note: str | None = None,
    ) -> bool:
        """Add variant alias for a term.

        Args:
            session: Database session
            project_id: Project ID
            canonical_key: Canonical key
            variant: Variant form
            note: Optional note

        Returns:
            True if added, False if already exists
        """
        # Check if alias already exists
        existing = (
            session.query(TermAlias)
            .filter(
                TermAlias.project_id == project_id,
                TermAlias.canonical == canonical_key,
                TermAlias.variant == variant,
            )
            .first()
        )

        if existing:
            return False

        alias = TermAlias(
            project_id=project_id,
            canonical=canonical_key,
            variant=variant,
            note=note,
        )
        session.add(alias)
        session.flush()
        return True

    def remove_alias(
        self,
        session: Session,
        project_id: int,
        canonical_key: str,
        variant: str,
    ) -> bool:
        """Remove variant alias for a term.

        Args:
            session: Database session
            project_id: Project ID
            canonical_key: Canonical key
            variant: Variant form

        Returns:
            True if removed, False if not found
        """
        deleted = (
            session.query(TermAlias)
            .filter(
                TermAlias.project_id == project_id,
                TermAlias.canonical == canonical_key,
                TermAlias.variant == variant,
            )
            .delete(synchronize_session=False)
        )

        session.flush()
        return deleted > 0

    def list_aliases(
        self,
        session: Session,
        project_id: int,
        canonical_key: str,
    ) -> list[dict[str, Any]]:
        """List all aliases for a term.

        Args:
            session: Database session
            project_id: Project ID
            canonical_key: Canonical key

        Returns:
            List of alias dictionaries
        """
        aliases = (
            session.query(TermAlias)
            .filter(
                TermAlias.project_id == project_id,
                TermAlias.canonical == canonical_key,
            )
            .all()
        )

        return [
            {
                "alias_id": alias.alias_id,
                "variant": alias.variant,
                "note": alias.note,
            }
            for alias in aliases
        ]

    # ============================================================================
    # Stopword Management
    # ============================================================================

    def set_stopword(
        self,
        session: Session,
        project_id: int,
        canonical_key: str,
        reason: str | None = None,
    ) -> bool:
        """Mark term as stopword.

        Args:
            session: Database session
            project_id: Project ID
            canonical_key: Canonical key
            reason: Optional reason for marking as stopword

        Returns:
            True if marked, False if already marked
        """
        # Get or create default stopword set
        stopset = (
            session.query(StopwordSet)
            .filter(
                StopwordSet.project_id == project_id,
                StopwordSet.name == "default",
            )
            .first()
        )

        if not stopset:
            stopset = StopwordSet(project_id=project_id, name="default")
            session.add(stopset)
            session.flush()

        # Check if already exists
        existing = (
            session.query(StopwordItem)
            .filter(
                StopwordItem.stopset_id == stopset.stopset_id,
                StopwordItem.lemma_text == canonical_key,
            )
            .first()
        )

        if existing:
            return False

        stopitem = StopwordItem(
            stopset_id=stopset.stopset_id,
            lemma_text=canonical_key,
            reason=reason,
        )
        session.add(stopitem)
        session.flush()
        return True

    def unset_stopword(
        self,
        session: Session,
        project_id: int,
        canonical_key: str,
    ) -> bool:
        """Unmark term as stopword.

        Args:
            session: Database session
            project_id: Project ID
            canonical_key: Canonical key

        Returns:
            True if unmarked, False if not found
        """
        # Get default stopword set
        stopset = (
            session.query(StopwordSet)
            .filter(
                StopwordSet.project_id == project_id,
                StopwordSet.name == "default",
            )
            .first()
        )

        if not stopset:
            return False

        deleted = (
            session.query(StopwordItem)
            .filter(
                StopwordItem.stopset_id == stopset.stopset_id,
                StopwordItem.lemma_text == canonical_key,
            )
            .delete(synchronize_session=False)
        )

        session.flush()
        return deleted > 0

    def _is_stopword(self, session: Session, project_id: int, canonical_key: str) -> bool:
        """Check if term is marked as stopword.

        Args:
            session: Database session
            project_id: Project ID
            canonical_key: Canonical key

        Returns:
            True if marked as stopword
        """
        stopset = (
            session.query(StopwordSet)
            .filter(
                StopwordSet.project_id == project_id,
                StopwordSet.name == "default",
            )
            .first()
        )

        if not stopset:
            return False

        exists = (
            session.query(StopwordItem)
            .filter(
                StopwordItem.stopset_id == stopset.stopset_id,
                StopwordItem.lemma_text == canonical_key,
            )
            .count()
        )

        return exists > 0

    # ============================================================================
    # Pin Translation/Example
    # ============================================================================

    def pin_translation(
        self,
        session: Session,
        cluster_id: int,
        translation: str,
        translation_lang: str = "ru",
    ) -> bool:
        """Pin translation for a term (overrides TM/Dict lookup).

        Args:
            session: Database session
            cluster_id: Term cluster ID
            translation: Translation text
            translation_lang: Translation language (default: ru)

        Returns:
            True if pinned, False if cluster not found
        """
        cluster = session.query(TermCluster).filter(TermCluster.cluster_id == cluster_id).first()
        if not cluster:
            return False

        cluster.pinned_translation = translation
        cluster.pinned_translation_lang = translation_lang
        session.flush()
        return True

    def unpin_translation(
        self,
        session: Session,
        cluster_id: int,
    ) -> bool:
        """Unpin translation for a term.

        Args:
            session: Database session
            cluster_id: Term cluster ID

        Returns:
            True if unpinned, False if cluster not found
        """
        cluster = session.query(TermCluster).filter(TermCluster.cluster_id == cluster_id).first()
        if not cluster:
            return False

        cluster.pinned_translation = None
        cluster.pinned_translation_lang = None
        session.flush()
        return True

    def pin_example(
        self,
        session: Session,
        cluster_id: int,
        sent_id: int,
    ) -> bool:
        """Pin example sentence for a term.

        Args:
            session: Database session
            cluster_id: Term cluster ID
            sent_id: Sentence ID

        Returns:
            True if pinned, False if cluster not found
        """
        cluster = session.query(TermCluster).filter(TermCluster.cluster_id == cluster_id).first()
        if not cluster:
            return False

        cluster.pinned_example_sent_id = sent_id
        session.flush()
        return True

    def unpin_example(
        self,
        session: Session,
        cluster_id: int,
    ) -> bool:
        """Unpin example sentence for a term.

        Args:
            session: Database session
            cluster_id: Term cluster ID

        Returns:
            True if unpinned, False if cluster not found
        """
        cluster = session.query(TermCluster).filter(TermCluster.cluster_id == cluster_id).first()
        if not cluster:
            return False

        cluster.pinned_example_sent_id = None
        session.flush()
        return True

    # ============================================================================
    # Review Queue
    # ============================================================================

    def list_review_queue(
        self,
        session: Session,
        project_id: int,
        status_filter: str | None = None,
        min_freq: int = 0,
        order_by: str = "freq",
        limit: int = 100,
        offset: int = 0,
    ) -> list[TermCardDTO]:
        """List terms for review queue.

        Args:
            session: Database session
            project_id: Project ID
            status_filter: Filter by status (None = all)
            min_freq: Minimum frequency threshold
            order_by: Sort order (freq/termhood/weirdness/pmi/alpha)
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of TermCardDTO
        """
        query = session.query(TermCluster).filter(TermCluster.project_id == project_id)

        # Status filter
        if status_filter:
            query = query.filter(TermCluster.curation_status == status_filter)

        # Frequency filter
        if min_freq > 0:
            query = query.filter(TermCluster.freq_abs >= min_freq)

        # Ordering
        if order_by == "freq":
            query = query.order_by(TermCluster.freq_abs.desc())
        elif order_by == "termhood" or order_by == "weirdness":
            query = query.order_by(TermCluster.weirdness.desc())
        elif order_by == "pmi":
            query = query.order_by(TermCluster.best_pmi.desc())
        elif order_by == "alpha":
            query = query.order_by(TermCluster.representative_he)
        else:
            # Default: frequency
            query = query.order_by(TermCluster.freq_abs.desc())

        # Pagination
        query = query.limit(limit).offset(offset)

        clusters = query.all()
        return [self._cluster_to_dto(session, cluster) for cluster in clusters]

    def count_review_queue(
        self,
        session: Session,
        project_id: int,
        status_filter: str | None = None,
        min_freq: int = 0,
    ) -> int:
        """Count terms in review queue.

        Args:
            session: Database session
            project_id: Project ID
            status_filter: Filter by status (None = all)
            min_freq: Minimum frequency threshold

        Returns:
            Total count
        """
        query = session.query(func.count(TermCluster.cluster_id)).filter(
            TermCluster.project_id == project_id
        )

        if status_filter:
            query = query.filter(TermCluster.curation_status == status_filter)

        if min_freq > 0:
            query = query.filter(TermCluster.freq_abs >= min_freq)

        return query.scalar() or 0
