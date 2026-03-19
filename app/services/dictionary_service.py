"""
Dictionary service for paginated lemma queries.

Provides server-side pagination and filtering for Dictionary view.
PERF-SCALE PATCH-E:
  - FTS5 search routing: uses lemma_fts MATCH instead of LIKE when available.
  - TTL count cache: count_lemmas() results cached for COUNT_CACHE_TTL seconds
    to avoid redundant full-table counts on every UI keystroke.
"""

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import ClassVar

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.infra.fts_manager import inspect_lemma_fts_parity
from app.infra.sa_models import Lemma, LemmaProjectStat, TMEntry

logger = logging.getLogger(__name__)

#: TTL for the in-process count cache (seconds).  Counts are allowed to lag
#: briefly behind writes; the Dictionary view refreshes on every search change
#: anyway, so stale counts are only visible in rare concurrent-write scenarios.
COUNT_CACHE_TTL: float = 30.0
LEMMA_FTS_HEALTH_TTL: float = 60.0


class DictionaryService:
    """Service for Dictionary view queries with pagination support.

    PERF-SCALE PATCH-E additions:
    - _count_cache: class-level TTL cache for count_lemmas() results.
    - FTS5 routing in _apply_filters(): uses lemma_fts when available.
    """

    # Class-level TTL count cache: key → (count, expires_monotonic)
    _count_cache: ClassVar[dict[str, tuple[int, float]]] = {}
    _cache_lock: ClassVar[threading.Lock] = threading.Lock()
    _lemma_fts_health_cache: ClassVar[dict[str, tuple[bool, str, float]]] = {}
    _lemma_fts_health_lock: ClassVar[threading.Lock] = threading.Lock()
    _lemma_fts_warning_emitted: ClassVar[set[str]] = set()

    # ------------------------------------------------------------------
    # FTS5 helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fts5_escape_term(term: str) -> str:
        """Escape a user search term for FTS5 MATCH with prefix search.

        Wraps the term in double-quotes (inner quotes doubled) and appends *
        so that "term"* matches any token starting with that string.
        """
        escaped = term.replace('"', '""')
        return f'"{escaped}"*'

    @staticmethod
    def _is_lemma_fts_available(session: Session) -> bool:
        """Return True if lemma_fts FTS5 table exists (O(1) sqlite_master check)."""
        result = session.execute(
            text("SELECT name FROM sqlite_master" " WHERE type='table' AND name='lemma_fts'")
        ).fetchone()
        return result is not None

    @staticmethod
    def _get_db_path(session: Session) -> str:
        """Return a stable cache key for the current DB, preferring file path."""
        bind = session.get_bind()
        bind_url = getattr(bind, "url", None)
        db_path = getattr(bind_url, "database", None)
        if db_path:
            return str(Path(db_path))
        return "<unknown-db>"

    @staticmethod
    def _get_sqlite_connection(session: Session):
        """Return the raw sqlite3 connection behind the SQLAlchemy session."""
        connection = session.connection()
        raw_conn = getattr(connection.connection, "driver_connection", None)
        if raw_conn is None:
            raw_conn = getattr(connection.connection, "dbapi_connection", None)
        if raw_conn is None:
            raw_conn = connection.connection
        return raw_conn

    @classmethod
    def _get_cached_lemma_fts_health(cls, cache_key: str) -> tuple[bool, str] | None:
        with cls._lemma_fts_health_lock:
            entry = cls._lemma_fts_health_cache.get(cache_key)
            if entry is None:
                return None
            healthy, detail, expires = entry
            if time.monotonic() > expires:
                del cls._lemma_fts_health_cache[cache_key]
                return None
            return healthy, detail

    @classmethod
    def _set_cached_lemma_fts_health(
        cls,
        cache_key: str,
        healthy: bool,
        detail: str,
    ) -> None:
        with cls._lemma_fts_health_lock:
            cls._lemma_fts_health_cache[cache_key] = (
                healthy,
                detail,
                time.monotonic() + LEMMA_FTS_HEALTH_TTL,
            )

    @classmethod
    def _get_lemma_fts_health(cls, session: Session) -> tuple[bool, str]:
        """Return cached lemma_fts parity-health for runtime search routing."""
        cache_key = cls._get_db_path(session)
        cached = cls._get_cached_lemma_fts_health(cache_key)
        if cached is not None:
            return cached

        raw_conn = cls._get_sqlite_connection(session)
        parity = inspect_lemma_fts_parity(raw_conn, schema="main")
        detail = ", ".join(parity["issues"]) if parity["issues"] else "healthy"
        healthy = bool(parity["healthy"])
        cls._set_cached_lemma_fts_health(cache_key, healthy, detail)

        if not healthy:
            with cls._lemma_fts_health_lock:
                if cache_key not in cls._lemma_fts_warning_emitted:
                    logger.warning(
                        "lemma_fts parity unhealthy for Dictionary search on %s; "
                        "falling back to LIKE. Repair with: "
                        'python scripts/repair_lemma_fts.py --db-path "%s". '
                        "Details: %s",
                        cache_key,
                        cache_key,
                        detail,
                    )
                    cls._lemma_fts_warning_emitted.add(cache_key)

        return healthy, detail

    # ------------------------------------------------------------------
    # Count cache helpers
    # ------------------------------------------------------------------

    @classmethod
    def _make_cache_key(cls, project_id: int, filters: dict) -> str:
        """Stable cache key for (project_id, filters)."""
        # Sort keys for stability; use only JSON-serializable values.
        stable = json.dumps(
            {"project_id": project_id, **{k: v for k, v in sorted(filters.items())}},
            sort_keys=True,
            default=str,
        )
        return hashlib.md5(stable.encode(), usedforsecurity=False).hexdigest()

    @classmethod
    def _get_cached_count(cls, key: str) -> int | None:
        with cls._cache_lock:
            entry = cls._count_cache.get(key)
            if entry is None:
                return None
            count, expires = entry
            if time.monotonic() > expires:
                del cls._count_cache[key]
                return None
            return count

    @classmethod
    def _set_cached_count(cls, key: str, count: int) -> None:
        with cls._cache_lock:
            cls._count_cache[key] = (count, time.monotonic() + COUNT_CACHE_TTL)

    @classmethod
    def invalidate_count_cache(cls, project_id: int | None = None) -> None:
        """Invalidate count cache entries, optionally for a specific project.

        Call from write paths (term extraction, import) to prevent stale counts.
        If project_id is None, clears the entire cache.
        """
        with cls._cache_lock:
            if project_id is None:
                cls._count_cache.clear()
            else:
                # Cache keys are MD5 hashes, so we can't filter by project_id
                # without re-hashing. Clear all to be safe; cache is small.
                cls._count_cache.clear()
        with cls._lemma_fts_health_lock:
            cls._lemma_fts_health_cache.clear()
            cls._lemma_fts_warning_emitted.clear()

    def search_lemmas(
        self,
        session: Session,
        project_id: int,
        filters: dict,
        limit: int = 100,
        offset: int = 0,
        sort_column: str = "freq_abs",
        sort_direction: str = "desc",
    ) -> list[tuple[Lemma, LemmaProjectStat]]:
        """Search lemmas with pagination and filtering.

        Args:
            session: Database session
            project_id: Project ID
            filters: Filter dict with keys:
                - pos: POS filter ("All" or specific POS tag)
                - pos_tags: Optional list of POS tags for multi-select filter
                - hide_noise: bool (if True, hide noise entries)
                - search: str (search text, LIKE on lemma_text)
            limit: Page size
            offset: Page offset
            sort_column: Column to sort by (default: "freq_abs")
            sort_direction: "asc" or "desc" (default: "desc")

        Returns:
            List of (Lemma, LemmaProjectStat) tuples for current page
        """
        # For frequency-based sorts, start from lemma_project_stat to keep planner
        # aligned with project+freq indexes on very large corpora.
        if sort_column in {"freq_abs", "doc_freq"}:
            stmt = (
                select(Lemma, LemmaProjectStat)
                .select_from(LemmaProjectStat)
                .join(
                    Lemma,
                    (Lemma.lemma_id == LemmaProjectStat.lemma_id)
                    & (Lemma.project_id == LemmaProjectStat.project_id),
                )
                .where(
                    LemmaProjectStat.project_id == project_id,
                    Lemma.project_id == project_id,
                )
            )
        else:
            stmt = (
                select(Lemma, LemmaProjectStat)
                .select_from(Lemma)
                .join(
                    LemmaProjectStat,
                    (Lemma.lemma_id == LemmaProjectStat.lemma_id)
                    & (Lemma.project_id == LemmaProjectStat.project_id),
                )
                .where(
                    Lemma.project_id == project_id,
                    LemmaProjectStat.project_id == project_id,
                )
            )

        # Apply filters (passes session for FTS5 routing, PERF-SCALE PATCH-E)
        stmt = self._apply_filters(stmt, filters, session=session)

        # Apply sort
        stmt = self._apply_sort(stmt, sort_column, sort_direction)

        # Apply pagination
        stmt = stmt.limit(limit).offset(offset)

        results = session.execute(stmt).all()
        return results

    def count_lemmas(
        self,
        session: Session,
        project_id: int,
        filters: dict,
    ) -> int:
        """Count total lemmas matching filters (for pagination).

        PERF-SCALE PATCH-E: Results are cached with COUNT_CACHE_TTL to avoid
        redundant full-table counts on every UI keystroke.

        Args:
            session: Database session
            project_id: Project ID
            filters: Same filter dict as search_lemmas()

        Returns:
            Total count of matching lemmas
        """
        cache_key = self._make_cache_key(project_id, filters)
        cached = self._get_cached_count(cache_key)
        if cached is not None:
            logger.debug("count_lemmas cache hit for project %d", project_id)
            return cached

        # Count from lemma table only (filters apply to lemma fields); this avoids
        # an unnecessary join on every search refresh for large projects.
        stmt = select(func.count(Lemma.lemma_id)).where(Lemma.project_id == project_id)

        # Apply same filters as search (FTS routing included)
        stmt = self._apply_filters(stmt, filters, session=session)

        count = session.execute(stmt).scalar() or 0
        self._set_cached_count(cache_key, count)
        return count

    def _apply_filters(self, stmt, filters: dict, session: Session | None = None):
        """Apply filters to statement (shared by search and count).

        PERF-SCALE PATCH-E: when session is provided and lemma_fts is available,
        the text search uses FTS5 MATCH instead of LIKE.
        """
        # POS filter
        pos_tags = filters.get("pos_tags")
        if isinstance(pos_tags, list):
            selected = [str(pos).strip() for pos in pos_tags if str(pos).strip()]
            if selected:
                stmt = stmt.where(Lemma.pos.in_(selected))
        else:
            pos_filter = filters.get("pos", "All")
            if pos_filter and pos_filter != "All":
                stmt = stmt.where(Lemma.pos == pos_filter)

        # Noise filter
        if filters.get("hide_noise", True):
            # Hide noise: is_noise = 0 OR is_noise IS NULL (backward compatibility)
            stmt = stmt.where(or_(Lemma.is_noise == 0, Lemma.is_noise.is_(None)))

        # Search filter: FTS5 path when available, LIKE fallback otherwise.
        search = filters.get("search", "").strip()
        if search:
            use_fts = False
            if session is not None and self._is_lemma_fts_available(session):
                use_fts, _detail = self._get_lemma_fts_health(session)
            if use_fts:
                fts_term = self._fts5_escape_term(search)
                stmt = stmt.where(
                    text(
                        "lemma.lemma_id IN ("
                        "  SELECT rowid FROM lemma_fts"
                        "  WHERE lemma_fts MATCH :_lemma_fts_term"
                        ")"
                    ).bindparams(_lemma_fts_term=fts_term)
                )
                logger.debug("lemma search: FTS5 path, term=%r", fts_term)
            else:
                stmt = stmt.where(Lemma.lemma_text.contains(search))
                logger.debug("lemma search: LIKE fallback, term=%r", search)

        return stmt

    def _apply_sort(self, stmt, sort_column: str, sort_direction: str):
        """Apply sorting to statement."""
        # Map UI column names to SQLAlchemy attributes
        sort_map = {
            "freq_abs": LemmaProjectStat.freq_abs,
            "doc_freq": LemmaProjectStat.doc_freq,
            "lemma_text": Lemma.lemma_text,
            "pos": Lemma.pos,
        }

        column_attr = sort_map.get(sort_column, LemmaProjectStat.freq_abs)
        # Keep deterministic tie-break aligned with stats PK/index when sorting by
        # stats columns to avoid temp sort plans on very large projects.
        if sort_column in {"freq_abs", "doc_freq"}:
            tie_breaker = LemmaProjectStat.lemma_id
        else:
            tie_breaker = Lemma.lemma_id

        if sort_direction == "asc":
            stmt = stmt.order_by(column_attr.asc(), tie_breaker.asc())
        else:
            stmt = stmt.order_by(column_attr.desc(), tie_breaker.asc())

        return stmt

    def count_lemma_ids_for_translation(
        self,
        session: Session,
        project_id: int,
        filters: dict,
        write_mode: str,
    ) -> int:
        """Count lemmas matching filters for translation.

        Filters by empty translation if write_mode is FILL_EMPTY or SKIP_NON_EMPTY.

        Args:
            session: Database session
            project_id: Project ID
            filters: Same filter dict as search_lemmas()
            write_mode: "FILL_EMPTY" | "SKIP_NON_EMPTY" | "OVERWRITE"

        Returns:
            Total count of lemmas to translate
        """
        stmt = (
            select(func.count(Lemma.lemma_id.distinct()))
            .select_from(Lemma)
            .join(
                LemmaProjectStat,
                (Lemma.lemma_id == LemmaProjectStat.lemma_id)
                & (Lemma.project_id == LemmaProjectStat.project_id),
            )
            .where(
                Lemma.project_id == project_id,
                LemmaProjectStat.project_id == project_id,
            )
        )

        # Apply standard filters (pos, hide_noise, search) with FTS5 routing
        stmt = self._apply_filters(stmt, filters, session=session)

        # For FILL_EMPTY and SKIP_NON_EMPTY: only count lemmas without translation
        if write_mode in ("FILL_EMPTY", "SKIP_NON_EMPTY"):
            stmt = stmt.outerjoin(
                TMEntry,
                (TMEntry.lemma_id == Lemma.lemma_id)
                & (TMEntry.kind == "lemma")
                & (TMEntry.project_id == project_id),
            ).where(
                or_(
                    TMEntry.tm_id.is_(None),
                    TMEntry.translation.is_(None),
                    TMEntry.translation == "",
                )
            )

        count = session.execute(stmt).scalar()
        return count or 0

    def fetch_lemma_ids_for_translation(
        self,
        session: Session,
        project_id: int,
        filters: dict,
        write_mode: str,
        limit: int,
        offset: int,
    ) -> list[int]:
        """Fetch lemma IDs matching filters for translation (paginated).

        Args:
            session: Database session
            project_id: Project ID
            filters: Same filter dict as search_lemmas()
            write_mode: "FILL_EMPTY" | "SKIP_NON_EMPTY" | "OVERWRITE"
            limit: Chunk size
            offset: Offset for pagination

        Returns:
            List of lemma_id integers
        """
        stmt = (
            select(Lemma.lemma_id)
            .join(
                LemmaProjectStat,
                (Lemma.lemma_id == LemmaProjectStat.lemma_id)
                & (Lemma.project_id == LemmaProjectStat.project_id),
            )
            .where(
                Lemma.project_id == project_id,
                LemmaProjectStat.project_id == project_id,
            )
        )

        # Apply standard filters (pos, hide_noise, search) with FTS5 routing
        stmt = self._apply_filters(stmt, filters, session=session)

        # For FILL_EMPTY and SKIP_NON_EMPTY: only fetch lemmas without translation
        if write_mode in ("FILL_EMPTY", "SKIP_NON_EMPTY"):
            stmt = stmt.outerjoin(
                TMEntry,
                (TMEntry.lemma_id == Lemma.lemma_id)
                & (TMEntry.kind == "lemma")
                & (TMEntry.project_id == project_id),
            ).where(
                or_(
                    TMEntry.tm_id.is_(None),
                    TMEntry.translation.is_(None),
                    TMEntry.translation == "",
                )
            )

        # Order by lemma_id for deterministic chunking
        stmt = stmt.order_by(Lemma.lemma_id.asc())

        # Apply pagination
        stmt = stmt.limit(limit).offset(offset)

        results = session.execute(stmt).scalars().all()
        return list(results)
