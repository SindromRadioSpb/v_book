"""M7 Translation Service with deterministic precedence.

Order of precedence (strict):
1. TM override (status=approved, then draft if allowed)
   - Project-scoped first, then global
2. Offline dict entries (status=approved), by priority
3. MT cache (if MT enabled)
4. MT provider (if MT enabled) → cached
5. None

All lookups use exact match on src_norm (normalized key).
"""
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.domain.normalization import normalize_for_tm
from app.infra.sa_models import TMEntry, TMAlias, DictEntry, DictSource, MTCache

logger = logging.getLogger(__name__)


@dataclass
class TranslationResult:
    """Result of translation lookup with explainability."""

    translation: Optional[str] = None
    source: str = "none"  # tm|dict|mt_cache|mt|none
    status: Optional[str] = None
    confidence: Optional[float] = None
    origin: Optional[str] = None
    matched_on: Optional[str] = None  # src_norm|alias_norm|variant_norm
    match_key_used: Optional[str] = None
    provider: Optional[str] = None  # MT provider name
    dict_source_name: Optional[str] = None
    tm_id: Optional[int] = None
    notes: Optional[str] = None


class TranslationService:
    """Translation Memory service with deterministic lookup."""

    def __init__(self):
        self.logger = logger

    def resolve_translation(
        self,
        session: Session,
        src_text: str,
        kind: str,
        src_lang: str = "he",
        tgt_lang: str = "ru",
        project_id: Optional[int] = None,
        allow_draft: bool = False,
        use_mt: bool = False,
    ) -> TranslationResult:
        """
        Resolve translation for given text using precedence order.

        Args:
            session: SQLAlchemy session
            src_text: Source text to translate
            kind: Entry kind (lemma|ngram|term_cluster|surface)
            src_lang: Source language
            tgt_lang: Target language
            project_id: Project ID for project-scoped lookup (None = global only)
            allow_draft: Include draft TM entries
            use_mt: Use MT fallback if no manual translation found

        Returns:
            TranslationResult with translation and provenance
        """
        # Normalize input text
        normalized = normalize_for_tm(src_lang, src_text, kind)

        if not normalized.norm:
            self.logger.warning(f"Normalization produced empty key for: {src_text}")
            return TranslationResult()

        # 1. TM override lookup (project-scoped first, then global)
        result = self._lookup_tm(session, normalized.norm, kind, src_lang, tgt_lang, project_id, allow_draft)
        if result.translation:
            return result

        # 2. TM aliases lookup
        result = self._lookup_tm_aliases(session, normalized.norm, kind, src_lang, tgt_lang, project_id, allow_draft)
        if result.translation:
            return result

        # 3. Offline dict lookup
        result = self._lookup_dict(session, normalized.norm, kind, src_lang, tgt_lang, project_id)
        if result.translation:
            return result

        # 4. MT cache lookup (if MT enabled)
        if use_mt:
            result = self._lookup_mt_cache(session, normalized.norm, src_lang, tgt_lang, project_id)
            if result.translation:
                return result

            # 5. MT provider (not implemented yet - would go here)
            # result = self._query_mt_provider(...)

        # No translation found
        return TranslationResult()

    def _lookup_tm(
        self,
        session: Session,
        src_norm: str,
        kind: str,
        src_lang: str,
        tgt_lang: str,
        project_id: Optional[int],
        allow_draft: bool,
    ) -> TranslationResult:
        """Lookup TM entries (project-scoped first, then global)."""
        # Build status filter
        if allow_draft:
            status_filter = TMEntry.status.in_(["approved", "draft"])
        else:
            status_filter = TMEntry.status == "approved"

        # Try project-scoped first
        if project_id is not None:
            stmt = (
                select(TMEntry)
                .where(
                    and_(
                        TMEntry.project_id == project_id,
                        TMEntry.kind == kind,
                        TMEntry.src_lang == src_lang,
                        TMEntry.tgt_lang == tgt_lang,
                        TMEntry.src_norm == src_norm,
                        status_filter,
                    )
                )
                .order_by(
                    TMEntry.status.desc(),  # approved > draft
                    TMEntry.updated_at.desc(),
                )
                .limit(1)
            )

            entry = session.execute(stmt).scalar()
            if entry:
                return TranslationResult(
                    translation=entry.translation,
                    source="tm",
                    status=entry.status,
                    confidence=entry.confidence,
                    origin=entry.origin,
                    matched_on="src_norm",
                    match_key_used=src_norm,
                    tm_id=entry.tm_id,
                    notes=entry.notes,
                )

        # Try global TM
        stmt = (
            select(TMEntry)
            .where(
                and_(
                    TMEntry.project_id.is_(None),
                    TMEntry.kind == kind,
                    TMEntry.src_lang == src_lang,
                    TMEntry.tgt_lang == tgt_lang,
                    TMEntry.src_norm == src_norm,
                    status_filter,
                )
            )
            .order_by(
                TMEntry.status.desc(),
                TMEntry.updated_at.desc(),
            )
            .limit(1)
        )

        entry = session.execute(stmt).scalar()
        if entry:
            return TranslationResult(
                translation=entry.translation,
                source="tm",
                status=entry.status,
                confidence=entry.confidence,
                origin=entry.origin,
                matched_on="src_norm",
                match_key_used=src_norm,
                tm_id=entry.tm_id,
                notes=entry.notes,
            )

        return TranslationResult()

    def _lookup_tm_aliases(
        self,
        session: Session,
        src_norm: str,
        kind: str,
        src_lang: str,
        tgt_lang: str,
        project_id: Optional[int],
        allow_draft: bool,
    ) -> TranslationResult:
        """Lookup TM entries via aliases."""
        # Build status filter
        if allow_draft:
            status_filter = TMEntry.status.in_(["approved", "draft"])
        else:
            status_filter = TMEntry.status == "approved"

        # Query aliases
        stmt = (
            select(TMEntry, TMAlias.alias_norm)
            .join(TMAlias, TMAlias.tm_id == TMEntry.tm_id)
            .where(
                and_(
                    TMAlias.alias_norm == src_norm,
                    TMEntry.kind == kind,
                    TMEntry.src_lang == src_lang,
                    TMEntry.tgt_lang == tgt_lang,
                    status_filter,
                )
            )
        )

        # Prioritize project-scoped over global
        if project_id is not None:
            stmt = stmt.order_by(
                TMEntry.project_id.isnot(None).desc(),  # project-scoped first
                TMEntry.status.desc(),
                TMEntry.updated_at.desc(),
            )
        else:
            stmt = stmt.order_by(TMEntry.status.desc(), TMEntry.updated_at.desc())

        stmt = stmt.limit(1)

        result = session.execute(stmt).first()
        if result:
            entry, alias_norm = result
            return TranslationResult(
                translation=entry.translation,
                source="tm",
                status=entry.status,
                confidence=entry.confidence,
                origin=entry.origin,
                matched_on="alias_norm",
                match_key_used=alias_norm,
                tm_id=entry.tm_id,
                notes=entry.notes,
            )

        return TranslationResult()

    def _lookup_dict(
        self,
        session: Session,
        src_norm: str,
        kind: str,
        src_lang: str,
        tgt_lang: str,
        project_id: Optional[int],
    ) -> TranslationResult:
        """Lookup offline dictionary entries."""
        # Query dict entries with source info
        stmt = (
            select(DictEntry, DictSource.name)
            .join(DictSource, DictSource.dict_source_id == DictEntry.dict_source_id)
            .where(
                and_(
                    DictEntry.src_norm == src_norm,
                    DictEntry.kind == kind,
                    DictEntry.src_lang == src_lang,
                    DictEntry.tgt_lang == tgt_lang,
                    DictEntry.status == "approved",
                )
            )
        )

        # Prioritize project-scoped over global, then by priority
        if project_id is not None:
            stmt = stmt.order_by(
                DictSource.project_id.isnot(None).desc(),  # project-scoped first
                DictEntry.priority.desc(),
                DictEntry.dict_entry_id.desc(),
            )
        else:
            stmt = stmt.order_by(DictEntry.priority.desc(), DictEntry.dict_entry_id.desc())

        stmt = stmt.limit(1)

        result = session.execute(stmt).first()
        if result:
            entry, dict_name = result
            return TranslationResult(
                translation=entry.translation,
                source="dict",
                status=entry.status,
                matched_on="src_norm",
                match_key_used=src_norm,
                dict_source_name=dict_name,
                notes=entry.notes,
            )

        return TranslationResult()

    def _lookup_mt_cache(
        self,
        session: Session,
        src_norm: str,
        src_lang: str,
        tgt_lang: str,
        project_id: Optional[int],
    ) -> TranslationResult:
        """Lookup MT cache."""
        stmt = (
            select(MTCache)
            .where(
                and_(
                    MTCache.src_norm == src_norm,
                    MTCache.src_lang == src_lang,
                    MTCache.tgt_lang == tgt_lang,
                )
            )
            .order_by(MTCache.created_at.desc())
            .limit(1)
        )

        entry = session.execute(stmt).scalar()
        if entry:
            return TranslationResult(
                translation=entry.translation,
                source="mt_cache",
                confidence=entry.confidence,
                matched_on="src_norm",
                match_key_used=src_norm,
                provider=entry.provider,
            )

        return TranslationResult()

    def bulk_resolve(
        self,
        session: Session,
        items: List[Tuple[str, str]],  # [(src_text, kind), ...]
        src_lang: str = "he",
        tgt_lang: str = "ru",
        project_id: Optional[int] = None,
        allow_draft: bool = False,
    ) -> Dict[Tuple[str, str], TranslationResult]:
        """
        Bulk resolve translations for multiple items.

        This is optimized to avoid N+1 queries by batching lookups.

        Args:
            session: SQLAlchemy session
            items: List of (src_text, kind) tuples
            src_lang: Source language
            tgt_lang: Target language
            project_id: Project ID
            allow_draft: Include draft entries

        Returns:
            Dict mapping (src_text, kind) → TranslationResult
        """
        if not items:
            return {}

        # Normalize all items
        normalized_map = {}
        for src_text, kind in items:
            normalized = normalize_for_tm(src_lang, src_text, kind)
            if normalized.norm:
                normalized_map[(src_text, kind)] = normalized.norm

        if not normalized_map:
            return {item: TranslationResult() for item in items}

        # Batch lookup from TM
        norm_keys = list(set(normalized_map.values()))
        tm_results = self._batch_lookup_tm(session, norm_keys, src_lang, tgt_lang, project_id, allow_draft)

        # Batch lookup from dict
        dict_results = self._batch_lookup_dict(session, norm_keys, src_lang, tgt_lang, project_id)

        # Merge results with precedence
        results = {}
        for item in items:
            src_text, kind = item
            norm_key = normalized_map.get(item)

            if not norm_key:
                results[item] = TranslationResult()
                continue

            # Check TM first (higher precedence)
            tm_result = tm_results.get((norm_key, kind))
            if tm_result and tm_result.translation:
                results[item] = tm_result
                continue

            # Check dict
            dict_result = dict_results.get((norm_key, kind))
            if dict_result and dict_result.translation:
                results[item] = dict_result
                continue

            # No translation
            results[item] = TranslationResult()

        return results

    def _batch_lookup_tm(
        self,
        session: Session,
        norm_keys: List[str],
        src_lang: str,
        tgt_lang: str,
        project_id: Optional[int],
        allow_draft: bool,
    ) -> Dict[Tuple[str, str], TranslationResult]:
        """Batch lookup TM entries."""
        if not norm_keys:
            return {}

        status_filter = TMEntry.status.in_(["approved", "draft"]) if allow_draft else TMEntry.status == "approved"

        stmt = select(TMEntry).where(
            and_(
                TMEntry.src_norm.in_(norm_keys),
                TMEntry.src_lang == src_lang,
                TMEntry.tgt_lang == tgt_lang,
                status_filter,
            )
        )

        if project_id is not None:
            stmt = stmt.where(or_(TMEntry.project_id == project_id, TMEntry.project_id.is_(None)))

        stmt = stmt.order_by(
            TMEntry.project_id.isnot(None).desc(),  # project-scoped first
            TMEntry.status.desc(),
            TMEntry.updated_at.desc(),
        )

        entries = session.execute(stmt).scalars().all()

        # Build result map: (norm_key, kind) → best entry
        results = {}
        for entry in entries:
            key = (entry.src_norm, entry.kind)
            if key not in results:  # First entry wins (already ordered by precedence)
                results[key] = TranslationResult(
                    translation=entry.translation,
                    source="tm",
                    status=entry.status,
                    confidence=entry.confidence,
                    origin=entry.origin,
                    matched_on="src_norm",
                    match_key_used=entry.src_norm,
                    tm_id=entry.tm_id,
                    notes=entry.notes,
                )

        return results

    def _batch_lookup_dict(
        self,
        session: Session,
        norm_keys: List[str],
        src_lang: str,
        tgt_lang: str,
        project_id: Optional[int],
    ) -> Dict[Tuple[str, str], TranslationResult]:
        """Batch lookup dict entries."""
        if not norm_keys:
            return {}

        stmt = (
            select(DictEntry, DictSource.name)
            .join(DictSource, DictSource.dict_source_id == DictEntry.dict_source_id)
            .where(
                and_(
                    DictEntry.src_norm.in_(norm_keys),
                    DictEntry.src_lang == src_lang,
                    DictEntry.tgt_lang == tgt_lang,
                    DictEntry.status == "approved",
                )
            )
        )

        if project_id is not None:
            stmt = stmt.where(or_(DictSource.project_id == project_id, DictSource.project_id.is_(None)))

        stmt = stmt.order_by(
            DictSource.project_id.isnot(None).desc(),  # project-scoped first
            DictEntry.priority.desc(),
        )

        results_list = session.execute(stmt).all()

        # Build result map
        results = {}
        for entry, dict_name in results_list:
            key = (entry.src_norm, entry.kind)
            if key not in results:  # First entry wins
                results[key] = TranslationResult(
                    translation=entry.translation,
                    source="dict",
                    status=entry.status,
                    matched_on="src_norm",
                    match_key_used=entry.src_norm,
                    dict_source_name=dict_name,
                    notes=entry.notes,
                )

        return results

    def revert_tm_entry(
        self,
        session: Session,
        tm_id: int,
        target_version: int,
        actor: str = "system",
    ) -> bool:
        """
        Revert TM entry to a previous version.

        Args:
            session: SQLAlchemy session
            tm_id: TM entry ID
            target_version: Version number to revert to
            actor: Actor performing revert

        Returns:
            True if revert successful, False otherwise
        """
        from sqlalchemy import select, func
        from app.infra.sa_models import TMEntry, TMEntryHistory

        # Get current entry
        entry = session.get(TMEntry, tm_id)
        if not entry:
            self.logger.error(f"TM entry {tm_id} not found")
            return False

        # Get target version from history
        stmt = select(TMEntryHistory).where(
            TMEntryHistory.tm_id == tm_id,
            TMEntryHistory.version == target_version
        )
        target_history = session.execute(stmt).scalar()

        if not target_history:
            self.logger.error(f"Version {target_version} not found for TM entry {tm_id}")
            return False

        # Get next version number
        max_version_stmt = select(func.max(TMEntryHistory.version)).where(
            TMEntryHistory.tm_id == tm_id
        )
        max_version = session.execute(max_version_stmt).scalar() or 0
        next_version = max_version + 1

        # Create history record for current state (before revert)
        current_history = TMEntryHistory(
            tm_id=entry.tm_id,
            version=next_version,
            translation=entry.translation,
            notes=entry.notes,
            status=entry.status,
            origin=entry.origin,
            change_kind="revert",
        )
        session.add(current_history)

        # Revert entry to target version
        entry.translation = target_history.translation
        entry.status = target_history.status
        entry.origin = "revert"
        entry.notes = target_history.notes or f"Reverted to v{target_version}"
        entry.updated_at = utc_now()

        session.commit()

        self.logger.info(f"TM entry {tm_id} reverted to version {target_version}")
        return True
