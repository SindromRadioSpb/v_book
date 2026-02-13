"""Global TM canonical layer service.

Provides:
- upsert_global(): Upsert into tm_global with scoring/merge logic
- upsert_and_link(): Convenience method to upsert from TMEntry and link
- backfill(): One-time migration of existing tm_entry -> tm_global
- propagate_to_entries(): Push tm_global changes to all linked tm_entries

Scoring algorithm (deterministic):
1. translation non-empty > empty
2. status: approved > draft > deprecated > rejected
3. origin: user_edit > import > mt_accept > merge > mt_auto > revert
4. updated_at DESC
5. tm_id ASC (lowest = oldest = canonical tiebreaker)
"""

import logging
from datetime import datetime
from typing import Optional, List, Tuple, Dict

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.infra.sa_models import TMEntry, TMGlobal

logger = logging.getLogger(__name__)

# Scoring constants (higher = better)
STATUS_RANK = {"approved": 4, "draft": 3, "deprecated": 2, "rejected": 1}
ORIGIN_RANK = {
    "user_edit": 5,
    "import": 4,
    "mt_accept": 3,
    "merge": 2,
    "mt_auto": 1,
    "revert": 0,
}


class TMGlobalService:
    """Service for managing global canonical TM layer."""

    @staticmethod
    def score_candidate(entry: TMEntry) -> Tuple[int, int, int, str, int]:
        """Compute deterministic score tuple for a tm_entry.

        Returns (has_translation, status_rank, origin_rank, updated_at, -tm_id) for sorting.
        Higher tuple = better candidate.
        """
        has_translation = 1 if entry.translation and entry.translation.strip() else 0
        return (
            has_translation,
            STATUS_RANK.get(entry.status, 0),
            ORIGIN_RANK.get(entry.origin, 0),
            entry.updated_at or "",
            -(entry.tm_id or 999999),  # negative for ascending tie-break
        )

    def upsert_global(
        self,
        session: Session,
        src_lang: str,
        tgt_lang: str,
        kind: str,
        src_norm: str,
        src_text: str,
        translation: str,
        status: str = "draft",
        origin: str = "mt_auto",
        confidence: Optional[float] = None,
        is_noise: int = 0,
        noise_reason: Optional[str] = None,
        notes: Optional[str] = None,
        source_tm_id: Optional[int] = None,
    ) -> TMGlobal:
        """Upsert a tm_global row. If exists, update only if new entry wins scoring.

        Args:
            session: DB session
            src_lang: Source language (e.g. "he")
            tgt_lang: Target language (e.g. "ru")
            kind: Entry kind (lemma|ngram|term_cluster|surface)
            src_norm: Normalized source key (from normalize_for_tm)
            src_text: Representative source text
            translation: Translation text
            status: Status (draft|approved|rejected|deprecated)
            origin: Origin (user_edit|import|mt_accept|mt_auto|merge|revert)
            confidence: Confidence score (0-1)
            is_noise: Noise flag (0=not noise, 1=noise)
            noise_reason: Noise reason code
            notes: Notes
            source_tm_id: tm_entry.tm_id that won the merge

        Returns:
            TMGlobal row (existing or newly created)
        """
        stmt = select(TMGlobal).where(
            TMGlobal.src_lang == src_lang,
            TMGlobal.tgt_lang == tgt_lang,
            TMGlobal.kind == kind,
            TMGlobal.src_norm == src_norm,
        )
        existing = session.execute(stmt).scalar()

        # Compute new score
        has_translation = 1 if translation and translation.strip() else 0
        new_score = (
            has_translation,
            STATUS_RANK.get(status, 0),
            ORIGIN_RANK.get(origin, 0),
        )

        if existing:
            # Compare scores: new vs existing
            old_has_translation = 1 if existing.translation and existing.translation.strip() else 0
            old_score = (
                old_has_translation,
                STATUS_RANK.get(existing.status, 0),
                ORIGIN_RANK.get(existing.origin, 0),
            )

            if new_score >= old_score:
                # Update existing with better data
                existing.translation = translation
                existing.status = status
                existing.origin = origin
                existing.confidence = confidence
                existing.is_noise = is_noise
                existing.noise_reason = noise_reason
                existing.notes = notes
                existing.source_tm_id = source_tm_id
                existing.src_text = src_text  # Update representative text
                existing.updated_at = datetime.now().isoformat()

            return existing
        else:
            # Create new global entry
            g = TMGlobal(
                src_lang=src_lang,
                tgt_lang=tgt_lang,
                kind=kind,
                src_norm=src_norm,
                src_text=src_text,
                translation=translation,
                status=status,
                origin=origin,
                confidence=confidence,
                is_noise=is_noise,
                noise_reason=noise_reason,
                notes=notes,
                source_tm_id=source_tm_id,
            )
            session.add(g)
            session.flush()  # Get tm_global_id
            return g

    def upsert_and_link(self, session: Session, entry: TMEntry) -> TMGlobal:
        """Convenience: upsert tm_global from TMEntry fields, set entry.tm_global_id.

        Args:
            session: DB session
            entry: TMEntry instance (must be flushed to have tm_id)

        Returns:
            TMGlobal row (existing or newly created)
        """
        g = self.upsert_global(
            session=session,
            src_lang=entry.src_lang,
            tgt_lang=entry.tgt_lang,
            kind=entry.kind,
            src_norm=entry.src_norm,
            src_text=entry.src_text,
            translation=entry.translation,
            status=entry.status,
            origin=entry.origin,
            confidence=entry.confidence,
            is_noise=entry.is_noise or 0,
            noise_reason=entry.noise_reason,
            notes=entry.notes,
            source_tm_id=entry.tm_id,
        )
        entry.tm_global_id = g.tm_global_id
        return g

    def propagate_to_entries(
        self,
        session: Session,
        tm_global_id: int,
        fields: Optional[List[str]] = None,
    ) -> int:
        """Push tm_global translation/status to all linked tm_entries.

        Args:
            session: DB session
            tm_global_id: The tm_global row to propagate from
            fields: Which fields to propagate (default: translation only)

        Returns:
            Number of tm_entries updated
        """
        g = session.execute(
            select(TMGlobal).where(TMGlobal.tm_global_id == tm_global_id)
        ).scalar()
        if not g:
            return 0

        entries = session.execute(
            select(TMEntry).where(TMEntry.tm_global_id == tm_global_id)
        ).scalars().all()

        fields = fields or ["translation"]
        count = 0
        for entry in entries:
            changed = False
            if "translation" in fields and entry.translation != g.translation:
                entry.translation = g.translation
                changed = True
            if "status" in fields and entry.status != g.status:
                entry.status = g.status
                changed = True
            if "is_noise" in fields:
                entry.is_noise = g.is_noise
                entry.noise_reason = g.noise_reason
                changed = True
            if changed:
                entry.updated_at = datetime.now().isoformat()
                count += 1

        return count

    def backfill(
        self,
        session: Session,
        chunk_size: int = 500,
        dry_run: bool = False,
    ) -> Dict[str, int]:
        """Backfill tm_global from existing tm_entry rows.

        Groups by (src_lang, tgt_lang, kind, src_norm), picks best entry per group,
        creates tm_global row, links all tm_entries.

        Args:
            session: DB session
            chunk_size: Commit every N keys
            dry_run: If True, no changes are committed

        Returns:
            Dict with stats: groups_created, entries_linked, entries_skipped
        """
        stats = {
            "groups_created": 0,
            "entries_linked": 0,
            "entries_skipped": 0,
        }

        # Get all distinct keys
        key_stmt = (
            select(
                TMEntry.src_lang,
                TMEntry.tgt_lang,
                TMEntry.kind,
                TMEntry.src_norm,
            )
            .group_by(TMEntry.src_lang, TMEntry.tgt_lang, TMEntry.kind, TMEntry.src_norm)
        )
        keys = session.execute(key_stmt).all()

        logger.info(f"Backfill: Found {len(keys)} unique keys")

        for i, (src_lang, tgt_lang, kind, src_norm) in enumerate(keys):
            # Get all entries for this key
            entries_stmt = select(TMEntry).where(
                TMEntry.src_lang == src_lang,
                TMEntry.tgt_lang == tgt_lang,
                TMEntry.kind == kind,
                TMEntry.src_norm == src_norm,
            )
            entries = list(session.execute(entries_stmt).scalars().all())

            if not entries:
                stats["entries_skipped"] += 1
                continue

            # Pick best by score
            best = max(entries, key=self.score_candidate)

            # Determine noise: noise only if ALL entries are noise
            all_noise = all((e.is_noise == 1 if e.is_noise is not None else False) for e in entries)

            if not dry_run:
                g = self.upsert_global(
                    session=session,
                    src_lang=src_lang,
                    tgt_lang=tgt_lang,
                    kind=kind,
                    src_norm=src_norm,
                    src_text=best.src_text,
                    translation=best.translation,
                    status=best.status,
                    origin=best.origin,
                    confidence=best.confidence,
                    is_noise=1 if all_noise else 0,
                    noise_reason=best.noise_reason if all_noise else None,
                    notes=best.notes,
                    source_tm_id=best.tm_id,
                )

                # Link all entries
                for entry in entries:
                    entry.tm_global_id = g.tm_global_id
                    stats["entries_linked"] += 1

                stats["groups_created"] += 1

            # Chunked commit
            if not dry_run and (i + 1) % chunk_size == 0:
                session.commit()
                logger.info(f"Backfill progress: {i + 1}/{len(keys)} keys processed")

        if not dry_run:
            session.commit()

        logger.info(
            f"Backfill complete: {stats['groups_created']} tm_global rows created, "
            f"{stats['entries_linked']} entries linked"
        )
        return stats
