"""Document service — metadata CRUD, search/filter/sort for DocumentsView.

Covers:
- List documents with title search + metadata filters + safe sort allowlist.
- Update document metadata (tag, link_url, level, topic).
- link_url validation (http/https only, length limit).
All DB operations are short-transaction, WAL-safe.
"""
import logging
import re
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.infra.sa_models import SourceDocument
from app.domain.dto import DocumentDTO
from app.infra.security import sanitize_for_log

logger = logging.getLogger(__name__)

# Levels allowed by DB CHECK constraint
VALID_LEVELS = frozenset({"aleph", "bet", "gimel", "he"})

# Safe sort column allowlist (DB column name → ORM attribute)
_SORT_ALLOWLIST: Dict[str, Any] = {
    "doc_id": SourceDocument.doc_id,
    "file_name": SourceDocument.file_name,
    "file_size_bytes": SourceDocument.file_size_bytes,
    "status": SourceDocument.status,
    "sentence_count": SourceDocument.sentence_count,
    "token_count": SourceDocument.token_count,
    "imported_at": SourceDocument.imported_at,
    "processed_at": SourceDocument.processed_at,
    "tag": SourceDocument.tag,
    "level": SourceDocument.level,
    "topic": SourceDocument.topic,
}

# Field length limits
_MAX_TAG_LEN = 200
_MAX_TOPIC_LEN = 500
_MAX_URL_LEN = 2000


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_link_url(url: Optional[str]) -> Optional[str]:
    """Validate and normalise link_url.

    Allowed schemes: http, https only.
    Max length: 2000 characters.
    Returns stripped URL on success, raises ValueError on violation.
    """
    if url is None:
        return None
    url = url.strip()
    if not url:
        return None
    if len(url) > _MAX_URL_LEN:
        raise ValueError(f"link_url too long ({len(url)} > {_MAX_URL_LEN})")
    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise ValueError(f"link_url is not a valid URL: {exc}") from exc
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"link_url scheme '{parsed.scheme}' not allowed. Only http/https are permitted."
        )
    if not parsed.netloc:
        raise ValueError("link_url has no host")
    return url


def validate_tag(tag: Optional[str]) -> Optional[str]:
    """Trim and validate tag length."""
    if tag is None:
        return None
    tag = tag.strip()
    if not tag:
        return None
    if len(tag) > _MAX_TAG_LEN:
        raise ValueError(f"tag too long ({len(tag)} > {_MAX_TAG_LEN})")
    return tag


def validate_level(level: Optional[str]) -> Optional[str]:
    """Validate level against allowed enum."""
    if level is None:
        return None
    level = level.strip()
    if not level:
        return None
    if level not in VALID_LEVELS:
        raise ValueError(f"level '{level}' not allowed. Must be one of: {sorted(VALID_LEVELS)}")
    return level


def validate_topic(topic: Optional[str]) -> Optional[str]:
    """Trim and validate topic length."""
    if topic is None:
        return None
    topic = topic.strip()
    if not topic:
        return None
    if len(topic) > _MAX_TOPIC_LEN:
        raise ValueError(f"topic too long ({len(topic)} > {_MAX_TOPIC_LEN})")
    return topic


# ---------------------------------------------------------------------------
# DocumentService
# ---------------------------------------------------------------------------


class DocumentService:
    """CRUD + query service for SourceDocument with metadata support."""

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def list_documents(
        self,
        session: Session,
        corpus_id: int,
        *,
        title_search: Optional[str] = None,
        tag_filter: Optional[str] = None,
        level_filter: Optional[str] = None,
        topic_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        sort_by: str = "imported_at",
        sort_dir: str = "desc",
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[DocumentDTO]:
        """Return documents for corpus with optional search/filter/sort.

        Args:
            corpus_id: Target corpus.
            title_search: Case-insensitive substring match on file_name.
            tag_filter: Exact tag match (case-insensitive LIKE).
            level_filter: Exact level value (validated against allowlist).
            topic_filter: Case-insensitive substring match on topic.
            status_filter: Exact status value.
            sort_by: Column name from _SORT_ALLOWLIST (safe allowlist applied).
            sort_dir: "asc" or "desc".
            limit/offset: Pagination.
        Returns:
            List of DocumentDTO.
        """
        stmt = select(SourceDocument).where(SourceDocument.corpus_id == corpus_id)

        # --- Filters ---
        if title_search:
            pattern = f"%{title_search}%"
            stmt = stmt.where(SourceDocument.file_name.ilike(pattern))

        if tag_filter:
            stmt = stmt.where(SourceDocument.tag.ilike(f"%{tag_filter}%"))

        if level_filter and level_filter in VALID_LEVELS:
            stmt = stmt.where(SourceDocument.level == level_filter)

        if topic_filter:
            stmt = stmt.where(SourceDocument.topic.ilike(f"%{topic_filter}%"))

        if status_filter:
            stmt = stmt.where(SourceDocument.status == status_filter)

        # --- Sort (safe allowlist) ---
        sort_col = _SORT_ALLOWLIST.get(sort_by, SourceDocument.imported_at)
        if sort_dir == "asc":
            stmt = stmt.order_by(sort_col.asc())
        else:
            stmt = stmt.order_by(sort_col.desc())

        # --- Pagination ---
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)

        docs = session.execute(stmt).scalars().all()
        return [self._to_dto(d) for d in docs]

    def get_document(self, session: Session, doc_id: int) -> Optional[DocumentDTO]:
        """Get a single document by ID."""
        doc = session.get(SourceDocument, doc_id)
        if doc is None:
            return None
        return self._to_dto(doc)

    # ------------------------------------------------------------------
    # Metadata update
    # ------------------------------------------------------------------

    def update_metadata(
        self,
        session: Session,
        doc_id: int,
        *,
        tag: Optional[str] = ...,
        link_url: Optional[str] = ...,
        level: Optional[str] = ...,
        topic: Optional[str] = ...,
    ) -> DocumentDTO:
        """Update document metadata fields.

        Pass ``...`` (Ellipsis) to leave a field unchanged.
        Pass ``None`` to clear a field.
        Raises ValueError on validation failure.
        Raises LookupError if doc_id not found.
        """
        doc = session.get(SourceDocument, doc_id)
        if doc is None:
            raise LookupError(f"Document {doc_id} not found")

        if tag is not ...:
            doc.tag = validate_tag(tag)
        if link_url is not ...:
            doc.link_url = validate_link_url(link_url)
        if level is not ...:
            doc.level = validate_level(level)
        if topic is not ...:
            doc.topic = validate_topic(topic)

        session.flush()
        session.commit()
        logger.info(
            "Updated metadata for doc %d: tag=%s level=%s",
            doc_id,
            sanitize_for_log(str(doc.tag)),
            doc.level,
        )
        return self._to_dto(doc)

    # ------------------------------------------------------------------
    # DTO mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _to_dto(doc: SourceDocument) -> DocumentDTO:
        return DocumentDTO(
            doc_id=doc.doc_id,
            corpus_id=doc.corpus_id,
            file_name=doc.file_name,
            file_path=doc.file_path,
            file_size_bytes=doc.file_size_bytes or 0,
            status=doc.status,
            sentence_count=doc.sentence_count or 0,
            token_count=doc.token_count or 0,
            imported_at=doc.imported_at or "",
            processed_at=doc.processed_at,
            tag=doc.tag,
            link_url=doc.link_url,
            level=doc.level,
            topic=doc.topic,
        )
