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

from sqlalchemy import and_, asc, desc, func, or_, select, text
from sqlalchemy.orm import Session

from app.domain.dto import UserDictionaryDTO, UserDictionaryItemDTO
from app.domain.normalization.normalizer import normalize_for_tm
from app.infra.sa_models import TMGlobal, UserDictionary, UserDictionaryItem
from app.infra.security.sanitizer import sanitize_for_log

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

        if dictionary_row:
            dictionary_row.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        self._audit_event(
            session,
            event_type="user_dictionary_bulk_add",
            operation="bulk_add_user_dictionary_items",
            resource_id=str(dictionary_id),
            details={"added": added, "skipped": skipped, "failed": failed},
        )
        logger.info(
            "User dictionary bulk add: dict_id=%s, added=%s, skipped=%s, failed=%s",
            dictionary_id,
            added,
            skipped,
            failed,
        )
        return {
            "added": added,
            "skipped": skipped,
            "failed": failed,
            "processed": processed,
            "total": total,
            "cancelled": cancelled,
        }

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

        base_stmt = (
            select(UserDictionaryItem, TMGlobal)
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

        base_stmt = self._apply_item_filters(base_stmt, filters)

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
            .where(UserDictionaryItem.dictionary_id == dictionary_id)
        )
        count_stmt = self._apply_item_filters(count_stmt, filters)
        total = session.execute(count_stmt).scalar() or 0

        order_col = self.ITEM_SORT_COLUMNS.get(sort_column, UserDictionaryItem.updated_at)
        direction = asc if sort_direction == "asc" else desc
        stmt = base_stmt.order_by(direction(order_col), asc(UserDictionaryItem.item_id)).limit(limit).offset(offset)

        rows = session.execute(stmt).all()
        items = [self._item_to_dto(item, tm_global) for item, tm_global in rows]
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

    def _apply_item_filters(self, stmt, filters: Dict[str, Any]):
        """Apply supported filters to item query."""
        if filters.get("kind"):
            stmt = stmt.where(UserDictionaryItem.kind == filters["kind"])

        if filters.get("study_state"):
            stmt = stmt.where(UserDictionaryItem.study_state == filters["study_state"])

        if filters.get("src_lang"):
            stmt = stmt.where(UserDictionaryItem.src_lang == filters["src_lang"])

        if filters.get("tgt_lang"):
            stmt = stmt.where(UserDictionaryItem.tgt_lang == filters["tgt_lang"])

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

        src_norm = str(raw.get("src_norm") or "").strip()
        if not src_norm:
            src_norm = normalize_for_tm(src_lang, src_text, kind).norm
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

    def _item_to_dto(self, item: UserDictionaryItem, tm_global: Optional[TMGlobal]) -> UserDictionaryItemDTO:
        """Convert ORM row to item DTO with resolved translation fields."""
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
            audio_status="missing",
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
