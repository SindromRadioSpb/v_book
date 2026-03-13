"""Document service — metadata CRUD, search/filter/sort for DocumentsView.

Covers:
- List documents with title search + metadata filters + safe sort allowlist.
- Update document metadata (tag, link_url, level, topic).
- link_url validation (http/https only, length limit).
All DB operations are short-transaction, WAL-safe.
"""
import logging
import re
from collections import Counter
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse

from sqlalchemy import select, func, or_, exists, union, false, text
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
_TAG_SPLIT_RE = re.compile(r"[,;\n\r]+")


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
    """Trim, canonicalize, and validate tag length."""
    if tag is None:
        return None
    tag = canonicalize_tag_text(tag)
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


def split_tag_tokens(raw_tag: Optional[str]) -> List[str]:
    """Return normalized tag tokens from a raw metadata string.

    Supported separators are explicit: comma, semicolon, newline. Whitespace-only
    splitting is intentionally not used because multi-word tags are valid.
    """
    text = str(raw_tag or "").strip()
    if not text:
        return []
    parts = _TAG_SPLIT_RE.split(text)
    tokens: List[str] = []
    seen: set[str] = set()
    for part in parts:
        token = re.sub(r"\s+", " ", part.strip())
        if not token:
            continue
        norm = token.casefold()
        if norm in seen:
            continue
        seen.add(norm)
        tokens.append(token)
    if tokens:
        return tokens
    collapsed = re.sub(r"\s+", " ", text)
    return [collapsed] if collapsed else []


def canonicalize_tag_text(raw_tag: Optional[str]) -> Optional[str]:
    """Persist tags in a stable comma-separated format."""
    tokens = split_tag_tokens(raw_tag)
    if not tokens:
        return None
    return ", ".join(tokens)


def parse_tag_filter_input(raw_value: Optional[str]) -> List[str]:
    """Parse tag filter input using the same explicit separators as storage."""
    return split_tag_tokens(raw_value)


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

    @staticmethod
    def _fts5_escape_term(term: str) -> str:
        """Escape a user search term for safe use in FTS5 MATCH expression.

        Returns a double-quoted phrase with trailing '*' for prefix/token-start matching.
        Any embedded double-quotes in the term are doubled per FTS5 phrase quoting rules.

        Examples:
            'מתמטי'   -> '"מתמטי"*'
            'foo bar'  -> '"foo bar"*'
            'foo "bar' -> '"foo ""bar"*'
        """
        escaped = term.replace('"', '""')
        return f'"{escaped}"*'

    @staticmethod
    def _is_document_name_fts_available(session: Session) -> bool:
        """Return True if the document_name_fts FTS5 table exists in the database.

        Uses a sqlite_master lookup (in-memory metadata, effectively O(1)).
        Called once per search request; result is not cached to remain correct
        across migrations applied at runtime.
        """
        result = session.execute(
            text(
                "SELECT 1 FROM sqlite_master"
                " WHERE type='table' AND name='document_name_fts'"
            )
        ).fetchone()
        return result is not None

    def _build_project_picker_doc_ids_subquery(
        self,
        project_id: int,
        *,
        search_query: str,
        session: Optional[Session] = None,
    ):
        """Build deduplicated doc-id subquery for picker search.

        Fast path (PERF-SCALE PATCH-D): if document_name_fts FTS5 table is present
        (created by migration 027), routes file_name search through FTS5 MATCH instead
        of LIKE '%query%'. On hewiki scale (387K rows) this reduces picker_page_search
        p95 from ~2s to sub-100ms.

        Fallback: if document_name_fts is not available (pre-migration or test env),
        falls back to the original LIKE-based search transparently.

        Explicit tag search mode: `tag:<text>` always uses LIKE on tag column.
        """
        project_id = int(project_id)
        query = (search_query or "").strip()
        if not query:
            return None

        # --- tag: prefix mode — explicit tag contains search (LIKE, always) ----------
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

        # --- FTS5 path (migration 027+) — file_name via document_name_fts MATCH ------
        use_fts = session is not None and self._is_document_name_fts_available(session)

        project_scope_exists = self._project_scope_exists(project_id)

        if use_fts:
            fts_term = self._fts5_escape_term(query)
            # FTS5 MATCH subquery: find doc_ids where file_name matches the term.
            # text() inside .where() is the canonical SQLAlchemy 2.x pattern for
            # raw SQL predicates with named bind parameters.
            selectors = [
                select(SourceDocument.doc_id)
                .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
                .where(
                    SourceCorpus.project_id == project_id,
                    text(
                        "source_document.doc_id IN ("
                        "  SELECT rowid FROM document_name_fts"
                        "  WHERE document_name_fts MATCH :_fts_term"
                        ")"
                    ).bindparams(_fts_term=fts_term),
                ),
                select(SourceDocument.doc_id)
                .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
                .where(
                    SourceCorpus.project_id == project_id,
                    SourceDocument.file_name.ilike(f"%{query}%"),
                ),
            ]
        else:
            # --- LIKE fallback (pre-migration 027 or test env without FTS table) ------
            like_q = f"%{query}%"
            selectors = [
                select(SourceDocument.doc_id)
                .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
                .where(
                    SourceCorpus.project_id == project_id,
                    SourceDocument.file_name.like(like_q),
                )
            ]

        # Tag exact match: always included regardless of FTS availability.
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

        # Numeric doc_id exact match.
        if query.isdigit():
            selectors.append(
                select(SourceDocument.doc_id).where(
                    SourceDocument.doc_id == int(query),
                    project_scope_exists,
                )
            )

        return union(*selectors).subquery("project_doc_match_ids")

    def _apply_project_picker_filters(
        self,
        stmt,
        *,
        project_id: int,
        document_filter: Optional[str] = None,
        document_id: Optional[int] = None,
        tag_filter: Optional[str] = None,
        topic_filter: Optional[str] = None,
        level_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        tag_match_mode: str = "any",
        session: Optional[Session] = None,
    ):
        """Apply explicit picker filters with deterministic AND semantics."""
        stmt = (
            stmt.join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
            .where(SourceCorpus.project_id == int(project_id))
        )

        document_filter_clean = (document_filter or "").strip()
        if document_filter_clean:
            doc_ids_subquery = self._build_project_picker_doc_ids_subquery(
                project_id,
                search_query=document_filter_clean,
                session=session,
            )
            stmt = stmt.join(
                doc_ids_subquery,
                SourceDocument.doc_id == doc_ids_subquery.c.doc_id,
            )

        if document_id is not None:
            stmt = stmt.where(SourceDocument.doc_id == int(document_id))

        tag_tokens = parse_tag_filter_input(tag_filter)
        if tag_tokens:
            predicates = [SourceDocument.tag.ilike(f"%{token}%") for token in tag_tokens]
            stmt = stmt.where(SourceDocument.tag.is_not(None))
            if str(tag_match_mode or "any").strip().lower() == "all":
                for predicate in predicates:
                    stmt = stmt.where(predicate)
            else:
                stmt = stmt.where(or_(*predicates))

        topic_filter_clean = (topic_filter or "").strip()
        if topic_filter_clean:
            stmt = stmt.where(SourceDocument.topic.ilike(f"%{topic_filter_clean}%"))

        level_filter_clean = validate_level(level_filter) if level_filter is not None else None
        if level_filter_clean:
            stmt = stmt.where(SourceDocument.level == level_filter_clean)

        status_filter_clean = (status_filter or "").strip()
        if status_filter_clean:
            stmt = stmt.where(SourceDocument.status == status_filter_clean)

        return stmt

    def build_project_documents_query(
        self,
        project_id: int,
        *,
        search_query: Optional[str] = None,
        document_filter: Optional[str] = None,
        document_id: Optional[int] = None,
        tag_filter: Optional[str] = None,
        topic_filter: Optional[str] = None,
        level_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        tag_match_mode: str = "any",
        sort_by: str = "doc_id",
        sort_dir: str = "desc",
        session: Optional[Session] = None,
    ):
        """Build project-scoped query for document picker (search + sort, no pagination).

        session is optional but strongly recommended: when provided, enables the
        FTS5 fast path for file_name search (PERF-SCALE PATCH-D).
        """
        explicit_filters_active = any(
            (
                (document_filter or "").strip(),
                document_id is not None,
                (tag_filter or "").strip(),
                (topic_filter or "").strip(),
                (level_filter or "").strip(),
            )
        )
        query = (search_query or "").strip()
        if query and not explicit_filters_active:
            doc_ids_subquery = self._build_project_picker_doc_ids_subquery(
                project_id,
                search_query=query,
                session=session,
            )
            stmt = select(SourceDocument).join(
                doc_ids_subquery,
                SourceDocument.doc_id == doc_ids_subquery.c.doc_id,
            )
        else:
            stmt = select(SourceDocument)

        if explicit_filters_active:
            stmt = self._apply_project_picker_filters(
                stmt,
                project_id=project_id,
                document_filter=document_filter,
                document_id=document_id,
                tag_filter=tag_filter,
                topic_filter=topic_filter,
                level_filter=level_filter,
                status_filter=status_filter,
                tag_match_mode=tag_match_mode,
                session=session,
            )
        elif not query:
            stmt = (
                stmt.join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
                .where(SourceCorpus.project_id == int(project_id))
            )

        status_filter_clean = (status_filter or "").strip()
        if status_filter_clean and not explicit_filters_active:
            stmt = stmt.where(SourceDocument.status == status_filter_clean)

        stmt = self._apply_documents_sort(stmt, sort_by=sort_by, sort_dir=sort_dir)
        return stmt

    def get_project_documents_total_count(
        self,
        session: Session,
        project_id: int,
        *,
        search_query: Optional[str] = None,
        document_filter: Optional[str] = None,
        document_id: Optional[int] = None,
        tag_filter: Optional[str] = None,
        topic_filter: Optional[str] = None,
        level_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        tag_match_mode: str = "any",
    ) -> int:
        """Return project-scoped count for document picker search."""
        explicit_filters_active = any(
            (
                (document_filter or "").strip(),
                document_id is not None,
                (tag_filter or "").strip(),
                (topic_filter or "").strip(),
                (level_filter or "").strip(),
            )
        )
        query = (search_query or "").strip()
        if query and not explicit_filters_active:
            doc_ids_subquery = self._build_project_picker_doc_ids_subquery(
                project_id,
                search_query=query,
                session=session,
            )
            status_filter_clean = (status_filter or "").strip()
            if status_filter_clean:
                stmt = (
                    select(func.count())
                    .select_from(SourceDocument)
                    .join(doc_ids_subquery, SourceDocument.doc_id == doc_ids_subquery.c.doc_id)
                    .where(SourceDocument.status == status_filter_clean)
                )
            else:
                stmt = select(func.count()).select_from(doc_ids_subquery)
        else:
            stmt = select(func.count(SourceDocument.doc_id)).select_from(SourceDocument)
            if explicit_filters_active:
                stmt = self._apply_project_picker_filters(
                    stmt,
                    project_id=project_id,
                    document_filter=document_filter,
                    document_id=document_id,
                    tag_filter=tag_filter,
                    topic_filter=topic_filter,
                    level_filter=level_filter,
                    status_filter=status_filter,
                    tag_match_mode=tag_match_mode,
                    session=session,
                )
            else:
                stmt = (
                    stmt.join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
                    .where(SourceCorpus.project_id == int(project_id))
                )
                status_filter_clean = (status_filter or "").strip()
                if status_filter_clean:
                    stmt = stmt.where(SourceDocument.status == status_filter_clean)

        return int(session.execute(stmt).scalar() or 0)

    def fetch_project_documents_page(
        self,
        session: Session,
        project_id: int,
        *,
        search_query: Optional[str] = None,
        document_filter: Optional[str] = None,
        document_id: Optional[int] = None,
        tag_filter: Optional[str] = None,
        topic_filter: Optional[str] = None,
        level_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        tag_match_mode: str = "any",
        sort_by: str = "doc_id",
        sort_dir: str = "desc",
        limit: int = 25,
        offset: int = 0,
    ) -> List[DocumentDTO]:
        """Return one project-scoped page for document picker."""
        stmt = self.build_project_documents_query(
            project_id,
            search_query=search_query,
            document_filter=document_filter,
            document_id=document_id,
            tag_filter=tag_filter,
            topic_filter=topic_filter,
            level_filter=level_filter,
            status_filter=status_filter,
            tag_match_mode=tag_match_mode,
            sort_by=sort_by,
            sort_dir=sort_dir,
            session=session,
        )
        stmt = stmt.limit(max(1, int(limit))).offset(max(0, int(offset)))
        docs = session.execute(stmt).scalars().all()
        return [self._to_dto(d) for d in docs]

    def get_project_frequent_tags(
        self,
        session: Session,
        project_id: int,
        *,
        limit: int = 5,
    ) -> List[str]:
        """Return most frequent normalized tag tokens for a project."""
        rows = (
            session.execute(
                select(SourceDocument.tag, func.count(SourceDocument.doc_id))
                .select_from(SourceDocument)
                .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
                .where(
                    SourceCorpus.project_id == int(project_id),
                    SourceDocument.tag.is_not(None),
                    func.trim(SourceDocument.tag) != "",
                )
                .group_by(SourceDocument.tag)
            )
            .all()
        )
        counter: Counter[str] = Counter()
        display_map: Dict[str, str] = {}
        for raw_tag, row_count in rows:
            for token in split_tag_tokens(raw_tag):
                norm = token.casefold()
                display_map.setdefault(norm, token)
                counter[norm] += int(row_count or 0)
        top = sorted(
            counter.items(),
            key=lambda item: (-item[1], display_map[item[0]].casefold()),
        )[: max(1, int(limit))]
        return [display_map[norm] for norm, _count in top]

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
