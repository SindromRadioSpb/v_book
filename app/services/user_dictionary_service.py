"""User Dictionaries service (P0).

Canonical contract:
- user_dictionary_item stores study entities only.
- Translation is resolved from tm_global by (src_lang, tgt_lang, kind, src_norm).
- No translation is persisted in user_dictionary_item.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import and_, asc, desc, func, or_, select, text, update
from sqlalchemy.orm import Session

from app.domain.dto import StudyProgressSummaryDTO, UserDictionaryDTO, UserDictionaryItemDTO
from app.domain.normalization.normalizer import normalize_for_tm
from app.infra.sa_models import (
    AudioAsset,
    Lemma,
    StudyProgress,
    TMEntry,
    TMGlobal,
    TermCluster,
    UserDictionary,
    UserDictionaryItem,
)
from app.infra.security.sanitizer import sanitize_for_log
from app.services.audio_asset_service import AudioAssetService
from app.services.study_service import StudyService

logger = logging.getLogger(__name__)


class UserDictionaryService:
    """Service for user dictionaries and their items."""

    ITEM_SORT_COLUMNS = {
        "item_id": UserDictionaryItem.item_id,
        "kind": UserDictionaryItem.kind,
        "src_text": UserDictionaryItem.src_text,
        "src_norm": UserDictionaryItem.src_norm,
        "study_state": UserDictionaryItem.study_state,
        "is_noise": UserDictionaryItem.is_noise,
        "created_at": UserDictionaryItem.created_at,
        "updated_at": UserDictionaryItem.updated_at,
        "translation": TMGlobal.translation,
        "translation_status": TMGlobal.status,
    }

    def create_dictionary(
        self,
        session: Session,
        name: str,
        description: Optional[str] = None,
        *,
        is_pinned: int = 0,
        sort_order: int = 0,
    ) -> UserDictionaryDTO:
        """Create a user dictionary."""
        clean_name = self._validate_dictionary_name(name)
        clean_description = (description or "").strip() or None

        existing = session.execute(
            select(UserDictionary).where(UserDictionary.name == clean_name)
        ).scalar_one_or_none()
        if existing:
            raise ValueError(f"Dictionary '{clean_name}' already exists")

        row = UserDictionary(
            name=clean_name,
            description=clean_description,
            is_pinned=1 if is_pinned else 0,
            sort_order=sort_order,
        )
        session.add(row)
        session.flush()

        self._audit_event(
            session,
            event_type="user_dictionary_create",
            operation="create_user_dictionary",
            resource_id=str(row.dictionary_id),
            details={"name": sanitize_for_log(clean_name)},
        )
        logger.info("Created user dictionary: id=%s, name=%s", row.dictionary_id, clean_name)
        return self._dictionary_to_dto(row, item_count=0)

    def rename_dictionary(self, session: Session, dictionary_id: int, new_name: str) -> UserDictionaryDTO:
        """Rename a user dictionary."""
        clean_name = self._validate_dictionary_name(new_name)
        row = session.get(UserDictionary, dictionary_id)
        if not row:
            raise ValueError(f"Dictionary not found: {dictionary_id}")

        if row.name == clean_name:
            return self._dictionary_to_dto(row, item_count=self._count_items(session, dictionary_id))

        existing = session.execute(
            select(UserDictionary)
            .where(UserDictionary.name == clean_name, UserDictionary.dictionary_id != dictionary_id)
        ).scalar_one_or_none()
        if existing:
            raise ValueError(f"Dictionary '{clean_name}' already exists")

        old_name = row.name
        row.name = clean_name
        row.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        session.flush()

        self._audit_event(
            session,
            event_type="user_dictionary_rename",
            operation="rename_user_dictionary",
            resource_id=str(dictionary_id),
            details={
                "old_name": sanitize_for_log(old_name),
                "new_name": sanitize_for_log(clean_name),
            },
        )
        logger.info("Renamed user dictionary: id=%s, old=%s, new=%s", dictionary_id, old_name, clean_name)
        return self._dictionary_to_dto(row, item_count=self._count_items(session, dictionary_id))

    def delete_dictionary(self, session: Session, dictionary_id: int) -> bool:
        """Delete a user dictionary."""
        row = session.get(UserDictionary, dictionary_id)
        if not row:
            return False

        name = row.name
        session.delete(row)
        session.flush()

        self._audit_event(
            session,
            event_type="user_dictionary_delete",
            operation="delete_user_dictionary",
            resource_id=str(dictionary_id),
            details={"name": sanitize_for_log(name)},
        )
        logger.info("Deleted user dictionary: id=%s, name=%s", dictionary_id, name)
        return True

    def list_dictionaries(self, session: Session) -> List[UserDictionaryDTO]:
        """List dictionaries with item counts."""
        stmt = (
            select(UserDictionary, func.count(UserDictionaryItem.item_id))
            .outerjoin(UserDictionaryItem, UserDictionaryItem.dictionary_id == UserDictionary.dictionary_id)
            .group_by(UserDictionary.dictionary_id)
            .order_by(desc(UserDictionary.is_pinned), asc(UserDictionary.sort_order), asc(UserDictionary.name))
        )
        rows = session.execute(stmt).all()
        return [self._dictionary_to_dto(dictionary, item_count=count or 0) for dictionary, count in rows]

    def get_dictionary(self, session: Session, dictionary_id: int) -> Optional[UserDictionaryDTO]:
        """Get dictionary by ID."""
        row = session.get(UserDictionary, dictionary_id)
        if not row:
            return None
        return self._dictionary_to_dto(row, item_count=self._count_items(session, dictionary_id))

    @staticmethod
    def build_canonical_hash(src_lang: str, dst_lang: str, kind: str, src_norm: str) -> str:
        """Build canonical hash as SHA256(src_lang+dst_lang+kind+src_norm)."""
        payload = f"{src_lang}{dst_lang}{kind}{src_norm}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def bulk_add_items(
        self,
        session: Session,
        dictionary_id: int,
        items: Iterable[Dict[str, Any]],
        *,
        include_noise: bool = False,
        skip_duplicates: bool = True,
        materialize_tm: bool = True,
        chunk_size: int = 500,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, int]:
        """Add items to dictionary with dedupe and noise policy."""
        if not session.get(UserDictionary, dictionary_id):
            raise ValueError(f"Dictionary not found: {dictionary_id}")

        item_list = list(items)
        total = len(item_list)
        added = 0
        skipped = 0
        failed = 0
        processed = 0
        cancelled = False
        pending = 0
        existing_hashes = set()
        added_rows: List[UserDictionaryItem] = []
        if skip_duplicates:
            existing_hashes = set(
                session.execute(
                    select(UserDictionaryItem.canonical_hash).where(
                        UserDictionaryItem.dictionary_id == dictionary_id
                    )
                ).scalars().all()
            )
        dictionary_row = session.get(UserDictionary, dictionary_id)
        for raw in item_list:
            if cancel_check and cancel_check():
                cancelled = True
                break
            try:
                item_payload = self._normalize_item_payload(raw)
                if item_payload["is_noise"] == 1 and not include_noise:
                    skipped += 1
                    processed += 1
                    if progress_callback:
                        progress_callback(processed, total)
                    continue

                canonical_hash = self.build_canonical_hash(
                    item_payload["src_lang"],
                    item_payload["tgt_lang"],
                    item_payload["kind"],
                    item_payload["src_norm"],
                )

                if skip_duplicates and canonical_hash in existing_hashes:
                    skipped += 1
                    processed += 1
                    if progress_callback:
                        progress_callback(processed, total)
                    continue

                row = UserDictionaryItem(
                    dictionary_id=dictionary_id,
                    kind=item_payload["kind"],
                    src_lang=item_payload["src_lang"],
                    tgt_lang=item_payload["tgt_lang"],
                    src_text=item_payload["src_text"],
                    src_norm=item_payload["src_norm"],
                    canonical_hash=canonical_hash,
                    tags_json=item_payload["tags_json"],
                    notes=item_payload["notes"],
                    is_noise=item_payload["is_noise"],
                    noise_reason=item_payload["noise_reason"],
                    study_state=item_payload["study_state"],
                    seen_count=item_payload["seen_count"],
                    origin_project_id=item_payload["origin_project_id"],
                    origin_entity_type=item_payload["origin_entity_type"],
                    origin_entity_id=item_payload["origin_entity_id"],
                    origin_tm_entry_id=item_payload["origin_tm_entry_id"],
                    origin_doc_id=item_payload["origin_doc_id"],
                    origin_source_ref=item_payload["origin_source_ref"],
                )
                session.add(row)
                added_rows.append(row)
                if skip_duplicates:
                    existing_hashes.add(canonical_hash)
                added += 1
                pending += 1

                if pending >= chunk_size:
                    session.flush()
                    pending = 0
            except Exception as e:
                logger.warning("Failed to add user dictionary item: %s", e)
                failed += 1
            finally:
                processed += 1
                if progress_callback:
                    progress_callback(processed, total)

        if pending:
            session.flush()

        # Global SRS progress is keyed by canonical_hash and linked per item.
        study_service = StudyService()
        progress_cache: Dict[str, int] = {}
        for row in added_rows:
            progress_id = progress_cache.get(row.canonical_hash)
            if progress_id is None:
                progress_id = study_service.ensure_progress(session, row.canonical_hash)
                progress_cache[row.canonical_hash] = progress_id
            row.study_progress_id = progress_id
            if row.study_state in ("learning", "mastered"):
                study_service.seed_progress_state(session, progress_id, row.study_state)
            if row.study_state == "suspended":
                row.is_suspended = 1

        tm_created = 0
        tm_reused = 0
        tm_linked = 0
        if materialize_tm and added_rows:
            projection_stats = self._materialize_tm_entries_for_items(
                session=session,
                items=added_rows,
            )
            tm_created = projection_stats["created"]
            tm_reused = projection_stats["reused"]
            tm_linked = projection_stats["linked"]

        if dictionary_row:
            dictionary_row.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        self._audit_event(
            session,
            event_type="user_dictionary_bulk_add",
            operation="bulk_add_user_dictionary_items",
            resource_id=str(dictionary_id),
            details={
                "added": added,
                "skipped": skipped,
                "failed": failed,
                "tm_created": tm_created,
                "tm_reused": tm_reused,
                "tm_linked": tm_linked,
            },
        )
        logger.info(
            "User dictionary bulk add: dict_id=%s, added=%s, skipped=%s, failed=%s, tm_created=%s, tm_reused=%s",
            dictionary_id,
            added,
            skipped,
            failed,
            tm_created,
            tm_reused,
        )
        return {
            "added": added,
            "skipped": skipped,
            "failed": failed,
            "processed": processed,
            "total": total,
            "cancelled": cancelled,
            "tm_created": tm_created,
            "tm_reused": tm_reused,
            "tm_linked": tm_linked,
        }

    def _materialize_tm_entries_for_items(
        self,
        session: Session,
        items: List[UserDictionaryItem],
    ) -> Dict[str, int]:
        """Ensure user dictionary rows are represented in TM entries for TM panel visibility."""
        from app.services.tm_global_service import TMGlobalService

        if not items:
            return {"created": 0, "reused": 0, "linked": 0}

        tm_global_service = TMGlobalService()
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        cache: Dict[Tuple[Optional[int], str, str, str, str], TMEntry] = {}
        touched_global_ids = set()
        created = 0
        reused = 0
        linked = 0

        for item in items:
            src_norm = self._canonical_src_norm(item.src_lang, item.src_text, item.kind, item.src_norm)
            project_scope = item.origin_project_id if item.origin_project_id is not None else None
            key = (project_scope, item.kind, item.src_lang, item.tgt_lang, src_norm)
            entry = None
            global_row = session.execute(
                select(TMGlobal).where(
                    TMGlobal.src_lang == item.src_lang,
                    TMGlobal.tgt_lang == item.tgt_lang,
                    TMGlobal.kind == item.kind,
                    TMGlobal.src_norm == src_norm,
                )
            ).scalar_one_or_none()

            if item.origin_tm_entry_id:
                candidate = session.get(TMEntry, item.origin_tm_entry_id)
                if self._tm_entry_matches_item(candidate, item, src_norm):
                    entry = candidate

            if not entry:
                entry = cache.get(key)

            if not entry:
                stmt = (
                    select(TMEntry)
                    .where(
                        TMEntry.kind == item.kind,
                        TMEntry.src_lang == item.src_lang,
                        TMEntry.tgt_lang == item.tgt_lang,
                        TMEntry.src_norm == src_norm,
                    )
                    .order_by(asc(TMEntry.tm_id))
                )
                if project_scope is None:
                    stmt = stmt.where(TMEntry.project_id.is_(None))
                else:
                    stmt = stmt.where(TMEntry.project_id == project_scope)
                entry = session.execute(stmt).scalar_one_or_none()

            if entry:
                reused += 1
            else:
                entry = TMEntry(
                    project_id=project_scope,
                    kind=item.kind,
                    src_lang=item.src_lang,
                    tgt_lang=item.tgt_lang,
                    src_text=item.src_text,
                    src_norm=src_norm,
                    translation=(global_row.translation if global_row else "") or "",
                    status=(global_row.status if global_row else "draft") or "draft",
                    origin=(global_row.origin if global_row else "import") or "import",
                    source_ref="user_dictionary_add",
                    is_noise=item.is_noise or 0,
                    noise_reason=item.noise_reason,
                    notes=item.notes,
                )
                self._attach_source_links(entry, item)
                session.add(entry)
                session.flush()
                created += 1

            if item.origin_tm_entry_id != entry.tm_id:
                item.origin_tm_entry_id = entry.tm_id
            item.src_norm = src_norm
            item.updated_at = now_str

            if entry.source_ref in (None, ""):
                entry.source_ref = "user_dictionary_add"
            if entry.src_text != item.src_text:
                entry.src_text = item.src_text
            if entry.is_noise != (item.is_noise or 0):
                entry.is_noise = item.is_noise or 0
            if entry.noise_reason != item.noise_reason:
                entry.noise_reason = item.noise_reason

            if entry.lemma_id is None and item.kind == "lemma":
                self._attach_source_links(entry, item)
            if entry.cluster_id is None and item.kind == "term_cluster":
                self._attach_source_links(entry, item)

            cache[key] = entry
            if global_row:
                if entry.tm_global_id != global_row.tm_global_id:
                    entry.tm_global_id = global_row.tm_global_id
                touched_global_ids.add(global_row.tm_global_id)
            elif entry.tm_global_id:
                touched_global_ids.add(entry.tm_global_id)
            elif (entry.translation or "").strip():
                linked_global = tm_global_service.upsert_and_link(session, entry, immediate_propagate=False)
                touched_global_ids.add(linked_global.tm_global_id)
            linked += 1

        for tm_global_id in sorted(touched_global_ids):
            tm_global_service.propagate_to_entries(
                session=session,
                tm_global_id=tm_global_id,
                fields=["translation", "status", "origin", "confidence", "is_noise", "noise_reason"],
            )

        return {"created": created, "reused": reused, "linked": linked}

    @staticmethod
    def _tm_entry_matches_item(
        entry: Optional[TMEntry],
        item: UserDictionaryItem,
        src_norm: str,
    ) -> bool:
        if not entry:
            return False
        if entry.kind != item.kind or entry.src_lang != item.src_lang or entry.tgt_lang != item.tgt_lang:
            return False
        if entry.src_norm != src_norm:
            return False
        item_scope = item.origin_project_id if item.origin_project_id is not None else None
        entry_scope = entry.project_id if entry.project_id is not None else None
        return entry_scope == item_scope

    @staticmethod
    def _attach_source_links(entry: TMEntry, item: UserDictionaryItem) -> None:
        """Attach source entity IDs to TM entry when available."""
        try:
            entity_id = int(item.origin_entity_id) if item.origin_entity_id is not None else None
        except Exception:
            entity_id = None
        if item.kind == "lemma" and item.origin_entity_type == "lemma" and entity_id is not None:
            entry.lemma_id = entity_id
        if item.kind == "term_cluster" and item.origin_entity_type in ("term_cluster", "term_card") and entity_id is not None:
            entry.cluster_id = entity_id

    def bulk_remove_items(
        self,
        session: Session,
        item_ids: List[int],
        *,
        chunk_size: int = 500,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, int]:
        """Remove items by IDs in chunks."""
        if not item_ids:
            return {"removed": 0, "processed": 0, "total": 0, "cancelled": False}

        removed = 0
        processed = 0
        total = len(item_ids)
        cancelled = False
        dictionary_ids = set(
            session.execute(
                select(UserDictionaryItem.dictionary_id).where(UserDictionaryItem.item_id.in_(item_ids))
            ).scalars().all()
        )
        for i in range(0, len(item_ids), chunk_size):
            if cancel_check and cancel_check():
                cancelled = True
                break
            chunk = item_ids[i : i + chunk_size]
            stmt = (
                UserDictionaryItem.__table__.delete()
                .where(UserDictionaryItem.item_id.in_(chunk))
            )
            result = session.execute(stmt)
            removed += result.rowcount or 0
            processed += len(chunk)
            if progress_callback:
                progress_callback(processed, total)

        if dictionary_ids:
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            session.execute(
                UserDictionary.__table__.update()
                .where(UserDictionary.dictionary_id.in_(dictionary_ids))
                .values(updated_at=now_str)
            )

        self._audit_event(
            session,
            event_type="user_dictionary_bulk_remove",
            operation="bulk_remove_user_dictionary_items",
            details={"removed": removed, "processed": processed, "total": total, "cancelled": cancelled},
        )
        logger.info("User dictionary bulk remove: removed=%s, processed=%s, total=%s", removed, processed, total)
        return {
            "removed": removed,
            "processed": processed,
            "total": total,
            "cancelled": cancelled,
        }

    def update_item_translation(
        self,
        session: Session,
        item_id: int,
        translation: Optional[str],
    ) -> None:
        """Update canonical translation for a dictionary item and propagate to TM entries."""
        from app.services.tm_global_service import TMGlobalService

        item = session.get(UserDictionaryItem, item_id)
        if not item:
            raise ValueError(f"User dictionary item not found: {item_id}")

        translation_value = (translation or "").strip()
        src_norm = self._canonical_src_norm(item.src_lang, item.src_text, item.kind, item.src_norm)
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        tm_global_service = TMGlobalService()

        # Prefer existing TM entry (explicit origin link first, then project+canonical key)
        entry = None
        if item.origin_tm_entry_id:
            entry = session.get(TMEntry, item.origin_tm_entry_id)
            if entry and (
                entry.kind != item.kind
                or entry.src_lang != item.src_lang
                or entry.tgt_lang != item.tgt_lang
            ):
                entry = None

        if not entry and item.origin_project_id is not None:
            entry = session.execute(
                select(TMEntry).where(
                    TMEntry.project_id == item.origin_project_id,
                    TMEntry.kind == item.kind,
                    TMEntry.src_lang == item.src_lang,
                    TMEntry.tgt_lang == item.tgt_lang,
                    TMEntry.src_norm == src_norm,
                )
            ).scalar_one_or_none()

        if entry:
            entry.translation = translation_value
            entry.status = "approved"
            entry.origin = "user_edit"
            entry.updated_at = now_str
            session.flush()
            global_row = tm_global_service.upsert_and_link(
                session,
                entry,
                force_global_update=True,
            )
        elif item.origin_project_id is not None:
            # Ensure TM panel/project views see user-dictionary edits in project context.
            created = TMEntry(
                project_id=item.origin_project_id,
                kind=item.kind,
                src_lang=item.src_lang,
                tgt_lang=item.tgt_lang,
                src_text=item.src_text,
                src_norm=src_norm,
                translation=translation_value,
                status="approved",
                origin="user_edit",
                source_ref="user_dictionary_inline_edit",
                is_noise=item.is_noise or 0,
                noise_reason=item.noise_reason,
            )
            if item.kind == "lemma" and item.origin_entity_type == "lemma" and item.origin_entity_id:
                try:
                    created.lemma_id = int(item.origin_entity_id)
                except Exception:
                    created.lemma_id = None
            if item.kind == "term_cluster" and item.origin_entity_type in ("term_cluster", "term_card") and item.origin_entity_id:
                try:
                    created.cluster_id = int(item.origin_entity_id)
                except Exception:
                    created.cluster_id = None
            session.add(created)
            session.flush()
            item.origin_tm_entry_id = created.tm_id
            global_row = tm_global_service.upsert_and_link(
                session,
                created,
                force_global_update=True,
            )
        else:
            existing_global = session.execute(
                select(TMGlobal).where(
                    TMGlobal.src_lang == item.src_lang,
                    TMGlobal.tgt_lang == item.tgt_lang,
                    TMGlobal.kind == item.kind,
                    TMGlobal.src_norm == src_norm,
                )
            ).scalar_one_or_none()
            global_row = tm_global_service.upsert_global(
                session=session,
                src_lang=item.src_lang,
                tgt_lang=item.tgt_lang,
                kind=item.kind,
                src_norm=src_norm,
                src_text=item.src_text,
                translation=translation_value,
                status="approved",
                origin="user_edit",
                confidence=existing_global.confidence if existing_global else None,
                is_noise=existing_global.is_noise if existing_global else (item.is_noise or 0),
                noise_reason=existing_global.noise_reason if existing_global else item.noise_reason,
                notes=existing_global.notes if existing_global else item.notes,
                source_tm_id=item.origin_tm_entry_id,
                force_update=True,
            )
            tm_global_service.propagate_to_entries(
                session=session,
                tm_global_id=global_row.tm_global_id,
                fields=["translation", "status", "origin", "confidence", "is_noise", "noise_reason"],
            )

        item.updated_at = now_str

        self._audit_event(
            session,
            event_type="user_dictionary_translation_update",
            operation="update_user_dictionary_item_translation",
            resource_id=str(item_id),
            details={
                "dictionary_id": item.dictionary_id,
                "tm_global_id": global_row.tm_global_id if global_row else None,
                "translation_empty": 1 if translation_value == "" else 0,
            },
        )

    def set_items_noise_status_bulk(
        self,
        session: Session,
        item_ids: List[int],
        is_noise: bool,
        noise_reason: Optional[str] = None,
    ) -> int:
        """Set noise status for selected user dictionary items and sync TM layers."""
        if not item_ids:
            return 0

        from app.services.tm_global_service import TMGlobalService

        noise_value = 1 if is_noise else 0
        reason_value = noise_reason if is_noise else None
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        items = list(
            session.execute(
                select(UserDictionaryItem)
                .where(UserDictionaryItem.item_id.in_(item_ids))
                .order_by(asc(UserDictionaryItem.item_id))
            ).scalars().all()
        )
        if not items:
            return 0

        touched_dictionary_ids = set()
        key_rows: Dict[Tuple[str, str, str, str], UserDictionaryItem] = {}
        for item in items:
            item.is_noise = noise_value
            item.noise_reason = reason_value
            item.updated_at = now_str
            touched_dictionary_ids.add(item.dictionary_id)
            canonical_norm = self._canonical_src_norm(item.src_lang, item.src_text, item.kind, item.src_norm)
            key_rows[(item.src_lang, item.tgt_lang, item.kind, canonical_norm)] = item

        tm_global_service = TMGlobalService()
        touched_lemma_ids = set()
        touched_cluster_ids = set()

        for (src_lang, tgt_lang, kind, src_norm), sample_item in key_rows.items():
            entries = list(
                session.execute(
                    select(TMEntry).where(
                        TMEntry.src_lang == src_lang,
                        TMEntry.tgt_lang == tgt_lang,
                        TMEntry.kind == kind,
                        TMEntry.src_norm == src_norm,
                    )
                ).scalars().all()
            )

            for entry in entries:
                entry.is_noise = noise_value
                entry.noise_reason = reason_value
                entry.updated_at = now_str
                if entry.kind == "lemma" and entry.lemma_id:
                    touched_lemma_ids.add(entry.lemma_id)
                if entry.kind == "term_cluster" and entry.cluster_id:
                    touched_cluster_ids.add(entry.cluster_id)

            global_row = session.execute(
                select(TMGlobal).where(
                    TMGlobal.src_lang == src_lang,
                    TMGlobal.tgt_lang == tgt_lang,
                    TMGlobal.kind == kind,
                    TMGlobal.src_norm == src_norm,
                )
            ).scalar_one_or_none()

            if global_row:
                global_row.is_noise = noise_value
                global_row.noise_reason = reason_value
                global_row.updated_at = now_str
                tm_global_service.propagate_to_entries(
                    session=session,
                    tm_global_id=global_row.tm_global_id,
                    fields=["is_noise", "noise_reason"],
                )
            elif entries:
                global_row = tm_global_service.upsert_global(
                    session=session,
                    src_lang=src_lang,
                    tgt_lang=tgt_lang,
                    kind=kind,
                    src_norm=src_norm,
                    src_text=sample_item.src_text,
                    translation=entries[0].translation,
                    status=entries[0].status,
                    origin=entries[0].origin,
                    confidence=entries[0].confidence,
                    is_noise=noise_value,
                    noise_reason=reason_value,
                    notes=entries[0].notes,
                    source_tm_id=entries[0].tm_id,
                    force_update=True,
                )
                for entry in entries:
                    entry.tm_global_id = global_row.tm_global_id
                tm_global_service.propagate_to_entries(
                    session=session,
                    tm_global_id=global_row.tm_global_id,
                    fields=["is_noise", "noise_reason"],
                )

        if touched_lemma_ids:
            session.execute(
                update(Lemma)
                .where(Lemma.lemma_id.in_(sorted(touched_lemma_ids)))
                .values(is_noise=noise_value, noise_reason=reason_value)
            )
        if touched_cluster_ids:
            session.execute(
                update(TermCluster)
                .where(TermCluster.cluster_id.in_(sorted(touched_cluster_ids)))
                .values(is_noise=noise_value, noise_reason=reason_value)
            )
        if touched_dictionary_ids:
            session.execute(
                update(UserDictionary)
                .where(UserDictionary.dictionary_id.in_(sorted(touched_dictionary_ids)))
                .values(updated_at=now_str)
            )

        self._audit_event(
            session,
            event_type="user_dictionary_noise_bulk_update",
            operation="set_user_dictionary_items_noise_status_bulk",
            details={
                "count": len(items),
                "is_noise": noise_value,
            },
        )
        return len(items)

    def query_items(
        self,
        session: Session,
        dictionary_id: int,
        filters: Optional[Dict[str, Any]] = None,
        *,
        limit: int = 100,
        offset: int = 0,
        sort_column: str = "updated_at",
        sort_direction: str = "desc",
    ) -> Tuple[List[UserDictionaryItemDTO], int]:
        """Query dictionary items with translation resolution from tm_global."""
        filters = filters or {}
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        audio_table_exists = self._table_exists(session, "audio_asset")

        base_stmt = (
            select(UserDictionaryItem, TMGlobal, StudyProgress)
            .select_from(UserDictionaryItem)
            .outerjoin(
                TMGlobal,
                and_(
                    TMGlobal.src_lang == UserDictionaryItem.src_lang,
                    TMGlobal.tgt_lang == UserDictionaryItem.tgt_lang,
                    TMGlobal.kind == UserDictionaryItem.kind,
                    TMGlobal.src_norm == UserDictionaryItem.src_norm,
                ),
            )
            .outerjoin(StudyProgress, StudyProgress.id == UserDictionaryItem.study_progress_id)
            .where(UserDictionaryItem.dictionary_id == dictionary_id)
        )
        if audio_table_exists:
            base_stmt = base_stmt.outerjoin(
                AudioAsset,
                and_(
                    AudioAsset.lang == UserDictionaryItem.src_lang,
                    AudioAsset.norm_text == UserDictionaryItem.src_norm,
                    AudioAsset.voice_id == "default",
                    AudioAsset.speed == 1.0,
                    AudioAsset.provider == "none",
                ),
            )

        base_stmt = self._apply_item_filters(base_stmt, filters, now_str, include_audio=audio_table_exists)

        # Count query (same filters)
        count_stmt = (
            select(func.count())
            .select_from(UserDictionaryItem)
            .outerjoin(
                TMGlobal,
                and_(
                    TMGlobal.src_lang == UserDictionaryItem.src_lang,
                    TMGlobal.tgt_lang == UserDictionaryItem.tgt_lang,
                    TMGlobal.kind == UserDictionaryItem.kind,
                    TMGlobal.src_norm == UserDictionaryItem.src_norm,
                ),
            )
            .outerjoin(StudyProgress, StudyProgress.id == UserDictionaryItem.study_progress_id)
            .where(UserDictionaryItem.dictionary_id == dictionary_id)
        )
        if audio_table_exists:
            count_stmt = count_stmt.outerjoin(
                AudioAsset,
                and_(
                    AudioAsset.lang == UserDictionaryItem.src_lang,
                    AudioAsset.norm_text == UserDictionaryItem.src_norm,
                    AudioAsset.voice_id == "default",
                    AudioAsset.speed == 1.0,
                    AudioAsset.provider == "none",
                ),
            )
        count_stmt = self._apply_item_filters(count_stmt, filters, now_str, include_audio=audio_table_exists)
        total = session.execute(count_stmt).scalar() or 0

        order_col = self.ITEM_SORT_COLUMNS.get(sort_column, UserDictionaryItem.updated_at)
        direction = asc if sort_direction == "asc" else desc
        stmt = base_stmt.order_by(direction(order_col), asc(UserDictionaryItem.item_id)).limit(limit).offset(offset)

        rows = session.execute(stmt).all()
        source_items = [item for item, _tm_global, _progress in rows]
        hashes = [item.canonical_hash for item in source_items]

        study_service = StudyService()
        summaries = study_service.get_progress_summaries(session, hashes)

        audio_status_by_item: Dict[int, str] = {}
        if source_items:
            audio_service = AudioAssetService()
            by_lang: Dict[str, List[Tuple[int, str]]] = {}
            for item in source_items:
                by_lang.setdefault(item.src_lang, []).append((item.item_id, item.src_norm))
            for lang, tuples in by_lang.items():
                try:
                    status_map = audio_service.bulk_get_status(
                        session,
                        lang=lang,
                        norm_texts=[norm for _item_id, norm in tuples],
                        voice_id="default",
                        speed=1.0,
                        provider="none",
                    )
                except Exception:
                    # Keep backward compatibility for fixture DBs without audio_asset.
                    status_map = {}
                for item_id, norm_text in tuples:
                    audio_status_by_item[item_id] = status_map.get(norm_text, "missing")

        items = []
        now_dt = datetime.now(timezone.utc)
        for item, tm_global, _progress in rows:
            resolved_tm_global = self._resolve_tm_global_for_item(session, item, tm_global)
            summary = summaries.get(item.canonical_hash)
            if summary:
                summary.is_suspended = bool(item.is_suspended)
                summary.study_state = study_service.compute_study_state(summary, now_dt)
                summary.due_human = study_service.compute_due_human(summary, now_dt)
            dto = self._item_to_dto(
                item,
                resolved_tm_global,
                summary,
                audio_status_by_item.get(item.item_id, "missing"),
            )
            items.append(dto)
        return items, total

    def count_item_ids_for_translation(
        self,
        session: Session,
        dictionary_id: int,
        filters: Optional[Dict[str, Any]],
        write_mode: str,
    ) -> int:
        """Count item IDs eligible for translation by write mode."""
        filters = dict(filters or {})
        # For translation scope selection, we only need dictionary filters.
        stmt = (
            select(func.count())
            .select_from(UserDictionaryItem)
            .outerjoin(
                TMGlobal,
                and_(
                    TMGlobal.src_lang == UserDictionaryItem.src_lang,
                    TMGlobal.tgt_lang == UserDictionaryItem.tgt_lang,
                    TMGlobal.kind == UserDictionaryItem.kind,
                    TMGlobal.src_norm == UserDictionaryItem.src_norm,
                ),
            )
            .where(UserDictionaryItem.dictionary_id == dictionary_id)
        )
        stmt = self._apply_item_filters(stmt, filters)
        stmt = self._apply_write_mode_filter(stmt, write_mode)
        return session.execute(stmt).scalar() or 0

    def fetch_item_ids_for_translation(
        self,
        session: Session,
        dictionary_id: int,
        filters: Optional[Dict[str, Any]],
        write_mode: str,
        *,
        limit: int,
        offset: int,
    ) -> List[int]:
        """Fetch item IDs for translation in deterministic order."""
        filters = dict(filters or {})
        stmt = (
            select(UserDictionaryItem.item_id)
            .select_from(UserDictionaryItem)
            .outerjoin(
                TMGlobal,
                and_(
                    TMGlobal.src_lang == UserDictionaryItem.src_lang,
                    TMGlobal.tgt_lang == UserDictionaryItem.tgt_lang,
                    TMGlobal.kind == UserDictionaryItem.kind,
                    TMGlobal.src_norm == UserDictionaryItem.src_norm,
                ),
            )
            .where(UserDictionaryItem.dictionary_id == dictionary_id)
        )
        stmt = self._apply_item_filters(stmt, filters)
        stmt = self._apply_write_mode_filter(stmt, write_mode)
        stmt = stmt.order_by(asc(UserDictionaryItem.item_id)).limit(limit).offset(offset)
        return list(session.execute(stmt).scalars().all())

    def get_items_by_ids(self, session: Session, item_ids: List[int]) -> List[UserDictionaryItem]:
        """Get user dictionary items by IDs in deterministic order."""
        if not item_ids:
            return []
        stmt = (
            select(UserDictionaryItem)
            .where(UserDictionaryItem.item_id.in_(item_ids))
            .order_by(asc(UserDictionaryItem.item_id))
        )
        return list(session.execute(stmt).scalars().all())

    def _apply_item_filters(
        self,
        stmt,
        filters: Dict[str, Any],
        now_str: Optional[str] = None,
        *,
        include_audio: bool = False,
    ):
        """Apply supported filters to item query."""
        if filters.get("kind"):
            stmt = stmt.where(UserDictionaryItem.kind == filters["kind"])

        study_filter = (filters.get("study_state") or "").strip().lower()
        now_value = now_str or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        mastered_clause = and_(
            func.coalesce(StudyProgress.review_count, 0) >= StudyService.MASTERED_MIN_REVIEWS,
            func.coalesce(StudyProgress.interval_days, 0) >= StudyService.MASTERED_INTERVAL_DAYS,
            or_(StudyProgress.due_at.is_(None), StudyProgress.due_at > now_value),
        )
        if study_filter == "suspended":
            stmt = stmt.where(UserDictionaryItem.is_suspended == 1)
        elif study_filter == "new":
            stmt = stmt.where(UserDictionaryItem.is_suspended == 0)
            stmt = stmt.where(func.coalesce(StudyProgress.review_count, 0) <= 0)
        elif study_filter == "due":
            stmt = stmt.where(UserDictionaryItem.is_suspended == 0)
            stmt = stmt.where(func.coalesce(StudyProgress.review_count, 0) > 0)
            stmt = stmt.where(StudyProgress.due_at <= now_value)
        elif study_filter == "mastered":
            stmt = stmt.where(UserDictionaryItem.is_suspended == 0)
            stmt = stmt.where(mastered_clause)
        elif study_filter == "learning":
            stmt = stmt.where(UserDictionaryItem.is_suspended == 0)
            stmt = stmt.where(func.coalesce(StudyProgress.review_count, 0) > 0)
            stmt = stmt.where(or_(StudyProgress.due_at.is_(None), StudyProgress.due_at > now_value))
            stmt = stmt.where(~mastered_clause)

        if filters.get("src_lang"):
            stmt = stmt.where(UserDictionaryItem.src_lang == filters["src_lang"])

        if filters.get("tgt_lang"):
            stmt = stmt.where(UserDictionaryItem.tgt_lang == filters["tgt_lang"])

        if "origin_project_id" in filters and filters["origin_project_id"] is not None:
            stmt = stmt.where(UserDictionaryItem.origin_project_id == filters["origin_project_id"])

        origin_filter = (filters.get("origin_filter") or "").strip().lower()
        if origin_filter == "project":
            stmt = stmt.where(UserDictionaryItem.origin_project_id.is_not(None))
        elif origin_filter == "manual":
            stmt = stmt.where(UserDictionaryItem.origin_project_id.is_(None))
            stmt = stmt.where(
                or_(
                    UserDictionaryItem.origin_source_ref.is_(None),
                    ~func.lower(UserDictionaryItem.origin_source_ref).like("%import%"),
                )
            )
        elif origin_filter == "imported":
            stmt = stmt.where(func.lower(func.coalesce(UserDictionaryItem.origin_source_ref, "")).like("%import%"))

        hide_noise = filters.get("hide_noise", True)
        if hide_noise:
            stmt = stmt.where(or_(UserDictionaryItem.is_noise == 0, UserDictionaryItem.is_noise.is_(None)))

        search_text = (filters.get("search_text") or "").strip()
        if search_text:
            like = f"%{search_text}%"
            stmt = stmt.where(
                or_(
                    UserDictionaryItem.src_text.like(like),
                    UserDictionaryItem.src_norm.like(like),
                    TMGlobal.translation.like(like),
                )
            )

        translation_filter = (filters.get("translation_filter") or "all").lower()
        if translation_filter == "empty":
            stmt = stmt.where(or_(TMGlobal.translation.is_(None), func.trim(TMGlobal.translation) == ""))
        elif translation_filter == "non_empty":
            stmt = stmt.where(and_(TMGlobal.translation.is_not(None), func.trim(TMGlobal.translation) != ""))

        translation_tier = (filters.get("translation_tier") or "").strip().lower()
        if translation_tier == "missing":
            stmt = stmt.where(or_(TMGlobal.translation.is_(None), func.trim(TMGlobal.translation) == ""))
        elif translation_tier == "deprecated":
            stmt = stmt.where(TMGlobal.status == "deprecated")
            stmt = stmt.where(and_(TMGlobal.translation.is_not(None), func.trim(TMGlobal.translation) != ""))
        elif translation_tier == "approved":
            stmt = stmt.where(TMGlobal.status == "approved")
            stmt = stmt.where(and_(TMGlobal.translation.is_not(None), func.trim(TMGlobal.translation) != ""))
        elif translation_tier == "user":
            stmt = stmt.where(
                TMGlobal.origin.in_(["user_edit", "import", "mt_accept", "merge", "revert"])
            )
            stmt = stmt.where(and_(TMGlobal.translation.is_not(None), func.trim(TMGlobal.translation) != ""))
            stmt = stmt.where(or_(TMGlobal.status.is_(None), ~TMGlobal.status.in_(["approved", "deprecated"])))
        elif translation_tier == "mt":
            stmt = stmt.where(TMGlobal.origin == "mt_auto")
            stmt = stmt.where(and_(TMGlobal.translation.is_not(None), func.trim(TMGlobal.translation) != ""))

        audio_filter = (filters.get("audio_filter") or "").strip().lower()
        if include_audio and audio_filter and audio_filter != "all":
            if audio_filter == "missing":
                stmt = stmt.where(or_(AudioAsset.asset_status.is_(None), AudioAsset.asset_status == "missing"))
            else:
                stmt = stmt.where(AudioAsset.asset_status == audio_filter)

        return stmt

    @staticmethod
    def _apply_write_mode_filter(stmt, write_mode: str):
        """Apply translation write mode filter using tm_global state."""
        if write_mode in ("FILL_EMPTY", "SKIP_NON_EMPTY"):
            return stmt.where(or_(TMGlobal.translation.is_(None), func.trim(TMGlobal.translation) == ""))
        return stmt

    def _normalize_item_payload(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize incoming item payload and compute src_norm when needed."""
        kind = str(raw.get("kind") or "").strip()
        src_lang = str(raw.get("src_lang") or "").strip()
        tgt_lang = str(raw.get("tgt_lang") or "").strip()
        src_text = str(raw.get("src_text") or "").strip()
        if not kind or not src_lang or not tgt_lang or not src_text:
            raise ValueError("Item requires kind, src_lang, tgt_lang, src_text")

        src_norm = self._canonical_src_norm(
            src_lang=src_lang,
            src_text=src_text,
            kind=kind,
            fallback_norm=str(raw.get("src_norm") or "").strip(),
        )
        if not src_norm:
            raise ValueError("Failed to compute src_norm")

        tags_json = raw.get("tags_json")
        if tags_json is None:
            tags_json = "[]"
        elif isinstance(tags_json, (list, tuple)):
            tags_json = json.dumps(list(tags_json), ensure_ascii=False)
        else:
            tags_json = str(tags_json)

        return {
            "kind": kind,
            "src_lang": src_lang,
            "tgt_lang": tgt_lang,
            "src_text": src_text,
            "src_norm": src_norm,
            "tags_json": tags_json,
            "notes": raw.get("notes"),
            "is_noise": 1 if raw.get("is_noise") else 0,
            "noise_reason": raw.get("noise_reason"),
            "study_state": self._validate_study_state(raw.get("study_state") or "new"),
            "seen_count": int(raw.get("seen_count") or 0),
            "origin_project_id": raw.get("origin_project_id"),
            "origin_entity_type": raw.get("origin_entity_type"),
            "origin_entity_id": str(raw.get("origin_entity_id")) if raw.get("origin_entity_id") is not None else None,
            "origin_tm_entry_id": raw.get("origin_tm_entry_id"),
            "origin_doc_id": raw.get("origin_doc_id"),
            "origin_source_ref": raw.get("origin_source_ref"),
        }

    @staticmethod
    def _canonical_src_norm(
        src_lang: str,
        src_text: str,
        kind: str,
        fallback_norm: str = "",
    ) -> str:
        """Compute canonical src_norm for TM key lookups with safe fallback."""
        try:
            normalized = normalize_for_tm(src_lang, src_text, kind).norm
            normalized = (normalized or "").strip()
            if normalized:
                return normalized
        except Exception as exc:
            logger.warning("normalize_for_tm failed for user dictionary item: %s", exc)
        return (fallback_norm or "").strip()

    def _resolve_tm_global_for_item(
        self,
        session: Session,
        item: UserDictionaryItem,
        joined_tm_global: Optional[TMGlobal],
    ) -> Optional[TMGlobal]:
        """Resolve TMGlobal row, including fallback for legacy non-canonical src_norm."""
        if joined_tm_global is not None:
            return joined_tm_global

        canonical_norm = self._canonical_src_norm(item.src_lang, item.src_text, item.kind, item.src_norm)
        if not canonical_norm or canonical_norm == item.src_norm:
            return None

        return session.execute(
            select(TMGlobal).where(
                TMGlobal.src_lang == item.src_lang,
                TMGlobal.tgt_lang == item.tgt_lang,
                TMGlobal.kind == item.kind,
                TMGlobal.src_norm == canonical_norm,
            )
        ).scalar_one_or_none()

    def _item_to_dto(
        self,
        item: UserDictionaryItem,
        tm_global: Optional[TMGlobal],
        summary: Optional[StudyProgressSummaryDTO],
        audio_status: str,
    ) -> UserDictionaryItemDTO:
        """Convert ORM row to item DTO with resolved translation fields."""
        study_service = StudyService()
        effective_summary = summary or StudyProgressSummaryDTO(
            progress_id=item.study_progress_id,
            canonical_hash=item.canonical_hash,
            first_seen_at=item.created_at,
            last_review_at=None,
            due_at=item.created_at,
            review_count=0,
            lapse_count=0,
            interval_days=0,
            ease_factor=2.5,
            last_quality=None,
            is_suspended=bool(item.is_suspended),
        )
        effective_summary.is_suspended = bool(item.is_suspended)
        if not effective_summary.study_state:
            effective_summary.study_state = study_service.compute_study_state(effective_summary)
        if not effective_summary.due_human:
            effective_summary.due_human = study_service.compute_due_human(effective_summary)

        translation_tier = study_service.compute_translation_tier(
            translation=tm_global.translation if tm_global else None,
            status=tm_global.status if tm_global else None,
            origin=tm_global.origin if tm_global else None,
        )
        origin_kind = study_service.compute_origin_kind(
            origin_project_id=item.origin_project_id,
            origin_source_ref=item.origin_source_ref,
            origin_entity_type=item.origin_entity_type,
        )

        return UserDictionaryItemDTO(
            item_id=item.item_id,
            dictionary_id=item.dictionary_id,
            kind=item.kind,
            src_lang=item.src_lang,
            tgt_lang=item.tgt_lang,
            src_text=item.src_text,
            src_norm=item.src_norm,
            canonical_hash=item.canonical_hash,
            tags_json=item.tags_json or "[]",
            notes=item.notes,
            is_noise=item.is_noise or 0,
            noise_reason=item.noise_reason,
            study_state=item.study_state,
            study_progress_id=item.study_progress_id,
            is_suspended=item.is_suspended or 0,
            suspended_reason=item.suspended_reason,
            last_seen_at=item.last_seen_at,
            seen_count=item.seen_count or 0,
            origin_project_id=item.origin_project_id,
            origin_entity_type=item.origin_entity_type,
            origin_entity_id=item.origin_entity_id,
            origin_tm_entry_id=item.origin_tm_entry_id,
            origin_doc_id=item.origin_doc_id,
            origin_source_ref=item.origin_source_ref,
            created_at=str(item.created_at),
            updated_at=str(item.updated_at),
            translation=tm_global.translation if tm_global else None,
            translation_status=tm_global.status if tm_global else None,
            translation_origin=tm_global.origin if tm_global else None,
            translation_confidence=tm_global.confidence if tm_global else None,
            tm_global_id=tm_global.tm_global_id if tm_global else None,
            audio_status=audio_status,
            origin_kind=origin_kind,
            computed_study_state=effective_summary.study_state,
            study_due_human=effective_summary.due_human,
            study_review_count=effective_summary.review_count,
            study_lapse_count=effective_summary.lapse_count,
            study_interval_days=effective_summary.interval_days,
            study_ease_factor=effective_summary.ease_factor,
            translation_tier=translation_tier,
            status_tooltip=self._build_status_tooltip(
                item=item,
                summary=effective_summary,
                tm_global=tm_global,
                audio_status=audio_status,
                translation_tier=translation_tier,
                origin_kind=origin_kind,
            ),
        )

    @staticmethod
    def _build_status_tooltip(
        *,
        item: UserDictionaryItem,
        summary: StudyProgressSummaryDTO,
        tm_global: Optional[TMGlobal],
        audio_status: str,
        translation_tier: str,
        origin_kind: str,
    ) -> str:
        translation_bits = [
            f"tier={translation_tier}",
            f"status={(tm_global.status if tm_global else 'none') or 'none'}",
            f"origin={(tm_global.origin if tm_global else 'none') or 'none'}",
        ]
        if tm_global and tm_global.confidence is not None:
            translation_bits.append(f"confidence={tm_global.confidence:.2f}")
        study_bits = [
            f"state={summary.study_state}",
            f"due={summary.due_human or 'n/a'}",
            f"reviews={summary.review_count}",
            f"lapses={summary.lapse_count}",
            f"interval={summary.interval_days}d",
            f"EF={summary.ease_factor:.2f}",
        ]
        return (
            f"Origin: {origin_kind}\n"
            f"Study: {', '.join(study_bits)}\n"
            f"Translation: {', '.join(translation_bits)}\n"
            f"Audio: {audio_status}\n"
            f"Noise: {'yes' if item.is_noise else 'no'}"
        )

    def _dictionary_to_dto(self, row: UserDictionary, *, item_count: int) -> UserDictionaryDTO:
        """Convert dictionary ORM row to DTO."""
        return UserDictionaryDTO(
            dictionary_id=row.dictionary_id,
            name=row.name,
            description=row.description,
            is_pinned=row.is_pinned,
            sort_order=row.sort_order,
            created_at=str(row.created_at),
            updated_at=str(row.updated_at),
            item_count=item_count,
        )

    @staticmethod
    def _validate_study_state(study_state: str) -> str:
        if study_state == "due":
            # Legacy column doesn't support "due"; due is computed from progress.
            return "learning"
        valid = {"new", "learning", "mastered", "suspended"}
        if study_state not in valid:
            raise ValueError(f"Invalid study_state: {study_state}")
        return study_state

    @staticmethod
    def _validate_dictionary_name(name: str) -> str:
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("Dictionary name cannot be empty")
        if len(clean_name) > 255:
            raise ValueError("Dictionary name cannot exceed 255 characters")
        forbidden_chars = ["/", "\\", ":", "*", "?", "\"", "<", ">", "|"]
        if any(ch in clean_name for ch in forbidden_chars):
            raise ValueError("Dictionary name contains forbidden characters: / \\ : * ? \" < > |")
        return clean_name

    @staticmethod
    def _count_items(session: Session, dictionary_id: int) -> int:
        stmt = select(func.count()).select_from(UserDictionaryItem).where(
            UserDictionaryItem.dictionary_id == dictionary_id
        )
        return session.execute(stmt).scalar() or 0

    @staticmethod
    def _table_exists(session: Session, table_name: str) -> bool:
        try:
            stmt = text(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name LIMIT 1"
            )
            return session.execute(stmt, {"name": table_name}).scalar() is not None
        except Exception:
            return False

    @staticmethod
    def _audit_event(
        session: Session,
        *,
        event_type: str,
        operation: str,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write audit entry without forcing commit of caller transaction."""
        try:
            stmt = text(
                """
                INSERT INTO security_audit_log (
                    event_type, outcome, operation, resource_type, resource_id, details
                ) VALUES (
                    :event_type, 'ALLOW', :operation, 'user_dictionary', :resource_id, :details
                )
                """
            )
            details_json = json.dumps(details or {}, ensure_ascii=False)
            session.execute(
                stmt,
                {
                    "event_type": event_type,
                    "operation": operation,
                    "resource_id": sanitize_for_log(resource_id or ""),
                    "details": details_json,
                },
            )
        except Exception as e:
            logger.warning("Failed to write user dictionary audit event: %s", e)
