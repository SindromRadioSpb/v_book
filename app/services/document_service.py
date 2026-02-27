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

from sqlalchemy import select, func, or_, exists, union, false
from sqlalchemy.orm import Session

from app.infra.sa_models import SourceCorpus, SourceDocument
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
    "file_path": SourceDocument.file_path,
    "link_url": SourceDocument.link_url,
    "tag": SourceDocument.tag,
    "level": SourceDocument.level,
    "topic": SourceDocument.topic,
}

# Field length limits
_MAX_TAG_LEN = 200
_MAX_TOPIC_LEN = 500
_MAX_URL_LEN = 2000
_TAG_SEARCH_PREFIX = "tag:"


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

    @staticmethod
    def _project_scope_exists(project_id: int):
        """Return EXISTS predicate that constrains SourceDocument rows to project scope."""
        return exists(
            select(1)
            .select_from(SourceCorpus)
            .where(
                SourceCorpus.corpus_id == SourceDocument.corpus_id,
                SourceCorpus.project_id == int(project_id),
            )
        )

    def _build_project_picker_doc_ids_subquery(
        self,
        project_id: int,
        *,
        search_query: str,
    ):
        """Build deduplicated doc-id subquery for picker search.

        Fast path avoids `OR ... tag LIKE ...` because it regresses to long scans on
        huge datasets. Default behavior:
        - file_name contains search,
        - doc_id exact match for numeric queries,
        - tag exact match via `idx_doc_tag` index.

        Optional explicit mode: `tag:<text>` enables legacy tag contains search.
        """
        project_id = int(project_id)
        query = (search_query or "").strip()
        if not query:
            return None

        if query.lower().startswith(_TAG_SEARCH_PREFIX):
            tag_term = query[len(_TAG_SEARCH_PREFIX):].strip()
            if not tag_term:
                return (
                    select(SourceDocument.doc_id)
                    .where(false())
                    .subquery("project_doc_match_ids")
                )
            tag_like = f"%{tag_term}%"
            return (
                select(SourceDocument.doc_id)
                .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
                .where(
                    SourceCorpus.project_id == project_id,
                    SourceDocument.tag.is_not(None),
                    SourceDocument.tag.like(tag_like),
                )
                .subquery("project_doc_match_ids")
            )

        like_q = f"%{query}%"
        project_scope_exists = self._project_scope_exists(project_id)

        selectors = [
            select(SourceDocument.doc_id)
            .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
            .where(
                SourceCorpus.project_id == project_id,
                SourceDocument.file_name.like(like_q),
            )
        ]

        tag_candidates = {query}
        lower_query = query.lower()
        if lower_query != query:
            tag_candidates.add(lower_query)
        for tag_value in sorted(tag_candidates):
            selectors.append(
                select(SourceDocument.doc_id).where(
                    SourceDocument.tag == tag_value,
                    project_scope_exists,
                )
            )

        if query.isdigit():
            selectors.append(
                select(SourceDocument.doc_id).where(
                    SourceDocument.doc_id == int(query),
                    project_scope_exists,
                )
            )

        return union(*selectors).subquery("project_doc_match_ids")

    def build_project_documents_query(
        self,
        project_id: int,
        *,
        search_query: Optional[str] = None,
        sort_by: str = "doc_id",
        sort_dir: str = "desc",
    ):
        """Build project-scoped query for document picker (search + sort, no pagination)."""
        query = (search_query or "").strip()
        if query:
            doc_ids_subquery = self._build_project_picker_doc_ids_subquery(
                project_id,
                search_query=query,
            )
            stmt = select(SourceDocument).join(
                doc_ids_subquery,
                SourceDocument.doc_id == doc_ids_subquery.c.doc_id,
            )
        else:
            stmt = (
                select(SourceDocument)
                .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
                .where(SourceCorpus.project_id == int(project_id))
            )

        stmt = self._apply_documents_sort(stmt, sort_by=sort_by, sort_dir=sort_dir)
        return stmt

    def get_project_documents_total_count(
        self,
        session: Session,
        project_id: int,
        *,
        search_query: Optional[str] = None,
    ) -> int:
        """Return project-scoped count for document picker search."""
        query = (search_query or "").strip()
        if query:
            doc_ids_subquery = self._build_project_picker_doc_ids_subquery(
                project_id,
                search_query=query,
            )
            stmt = select(func.count()).select_from(doc_ids_subquery)
        else:
            stmt = (
                select(func.count(SourceDocument.doc_id))
                .select_from(SourceDocument)
                .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
                .where(SourceCorpus.project_id == int(project_id))
            )

        return int(session.execute(stmt).scalar() or 0)

    def fetch_project_documents_page(
        self,
        session: Session,
        project_id: int,
        *,
        search_query: Optional[str] = None,
        sort_by: str = "doc_id",
        sort_dir: str = "desc",
        limit: int = 25,
        offset: int = 0,
    ) -> List[DocumentDTO]:
        """Return one project-scoped page for document picker."""
        stmt = self.build_project_documents_query(
            project_id,
            search_query=search_query,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        stmt = stmt.limit(max(1, int(limit))).offset(max(0, int(offset)))
        docs = session.execute(stmt).scalars().all()
        return [self._to_dto(d) for d in docs]

    def build_documents_query(
        self,
        corpus_id: int,
        *,
        title_search: Optional[str] = None,
        tag_filter: Optional[str] = None,
        level_filter: Optional[str] = None,
        topic_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        sort_by: str = "imported_at",
        sort_dir: str = "desc",
    ):
        """Build safe global documents query (filters + sorting, no pagination)."""
        stmt = select(SourceDocument).where(SourceDocument.corpus_id == corpus_id)
        stmt = self._apply_documents_filters(
            stmt,
            title_search=title_search,
            tag_filter=tag_filter,
            level_filter=level_filter,
            topic_filter=topic_filter,
            status_filter=status_filter,
        )
        stmt = self._apply_documents_sort(stmt, sort_by=sort_by, sort_dir=sort_dir)
        return stmt

    def get_documents_total_count(
        self,
        session: Session,
        corpus_id: int,
        *,
        title_search: Optional[str] = None,
        tag_filter: Optional[str] = None,
        level_filter: Optional[str] = None,
        topic_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> int:
        """Return total rows count with global filters applied."""
        stmt = select(func.count(SourceDocument.doc_id)).where(SourceDocument.corpus_id == corpus_id)
        stmt = self._apply_documents_filters(
            stmt,
            title_search=title_search,
            tag_filter=tag_filter,
            level_filter=level_filter,
            topic_filter=topic_filter,
            status_filter=status_filter,
        )
        return int(session.execute(stmt).scalar() or 0)

    def fetch_documents_page(
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
        limit: int = 25,
        offset: int = 0,
    ) -> List[DocumentDTO]:
        """Return one paged slice (global filter + global sort + LIMIT/OFFSET)."""
        stmt = self.build_documents_query(
            corpus_id,
            title_search=title_search,
            tag_filter=tag_filter,
            level_filter=level_filter,
            topic_filter=topic_filter,
            status_filter=status_filter,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        stmt = stmt.limit(max(1, int(limit))).offset(max(0, int(offset)))
        docs = session.execute(stmt).scalars().all()
        return [self._to_dto(d) for d in docs]

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
        if limit is not None:
            return self.fetch_documents_page(
                session,
                corpus_id,
                title_search=title_search,
                tag_filter=tag_filter,
                level_filter=level_filter,
                topic_filter=topic_filter,
                status_filter=status_filter,
                sort_by=sort_by,
                sort_dir=sort_dir,
                limit=limit,
                offset=offset,
            )

        stmt = self.build_documents_query(
            corpus_id,
            title_search=title_search,
            tag_filter=tag_filter,
            level_filter=level_filter,
            topic_filter=topic_filter,
            status_filter=status_filter,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
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

    @staticmethod
    def _apply_documents_filters(
        stmt,
        *,
        title_search: Optional[str] = None,
        tag_filter: Optional[str] = None,
        level_filter: Optional[str] = None,
        topic_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
    ):
        """Apply global documents filters to query."""
        if title_search:
            stmt = stmt.where(SourceDocument.file_name.ilike(f"%{title_search}%"))
        if tag_filter:
            stmt = stmt.where(SourceDocument.tag.ilike(f"%{tag_filter}%"))
        if level_filter and level_filter in VALID_LEVELS:
            stmt = stmt.where(SourceDocument.level == level_filter)
        if topic_filter:
            stmt = stmt.where(SourceDocument.topic.ilike(f"%{topic_filter}%"))
        if status_filter:
            stmt = stmt.where(SourceDocument.status == status_filter)
        return stmt

    @staticmethod
    def _apply_documents_sort(stmt, *, sort_by: str, sort_dir: str):
        """Apply safe global sorting with stable secondary ordering."""
        sort_col = _SORT_ALLOWLIST.get(sort_by, SourceDocument.imported_at)
        sort_dir_clean = str(sort_dir or "desc").strip().lower()
        if sort_dir_clean == "asc":
            stmt = stmt.order_by(sort_col.asc(), SourceDocument.doc_id.asc())
        else:
            stmt = stmt.order_by(sort_col.desc(), SourceDocument.doc_id.asc())
        return stmt
