"""Concordance search service (M6)."""
import logging
import re
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.dto import KWICResult
from app.services.db_service import DBService
from app.infra.security import (
    validate_query_complexity,
    sanitize_fts5_query,
    sanitize_for_log,
    QueryComplexityError,
)

logger = logging.getLogger(__name__)


def normalize_hebrew_search(query: str) -> List[str]:
    """
    Normalize Hebrew search query to handle article variations.

    Generates variants to find both:
    - "בית ספר" (without article)
    - "בית הספר" (with article)

    Args:
        query: User's search query

    Returns:
        List of normalized query variants for FTS5 OR matching
    """
    try:
        from app.domain.hebrew_utils import strip_nikud, strip_cantillation, normalize_whitespace

        # Basic normalization
        normalized = strip_nikud(query)
        normalized = strip_cantillation(normalized)
        normalized = normalize_whitespace(normalized)
        normalized = normalized.strip()

        if not normalized:
            return []

        variants = set()
        variants.add(normalized)

        # For phrases (multi-word), generate article variants
        tokens = normalized.split()

        if len(tokens) > 1:
            # Generate variant without article ה on second word
            # e.g., "בית הספר" → "בית ספר"
            tokens_no_article = []
            for token in tokens:
                if token.startswith('ה') and len(token) > 1:
                    tokens_no_article.append(token[1:])  # Strip leading ה
                else:
                    tokens_no_article.append(token)

            if tokens_no_article != tokens:
                variants.add(' '.join(tokens_no_article))

            # Generate variant with article ה on second word
            # e.g., "בית ספר" → "בית הספר"
            tokens_with_article = []
            for i, token in enumerate(tokens):
                if i > 0 and not token.startswith('ה') and len(token) > 0:
                    # Add article to non-first words
                    tokens_with_article.append('ה' + token)
                else:
                    tokens_with_article.append(token)

            if tokens_with_article != tokens:
                variants.add(' '.join(tokens_with_article))

        return list(variants)

    except Exception as e:
        from app.infra.security import sanitize_for_log
        logger.exception(
            f"Failed to normalize search query: {sanitize_for_log(query)}, error={str(e)}"
        )
        # Fallback: return original query as single variant
        return [query.strip()] if query.strip() else []


class ConcordanceService:
    """Service for concordance/KWIC search using FTS5."""

    def __init__(self):
        self.db_service = DBService.get_instance()
        logger.info("ConcordanceService initialized")

    def search_concordance(
        self,
        session: Session,
        project_id: int,
        query: str,
        *,
        limit: int = 100,
        offset: int = 0,
        is_phrase: bool = False,
        normalize: bool = True
    ) -> List[KWICResult]:
        """
        Search for concordance results using FTS5.

        Args:
            session: DB session
            project_id: Project ID to filter results
            query: Search query (user input - will be sanitized)
            limit: Maximum results to return
            offset: Pagination offset
            is_phrase: Treat query as exact phrase
            normalize: Apply Hebrew normalization (article variants)

        Returns:
            List of KWICResult with left/match/right context
        """
        if not query or not query.strip():
            return []

        # Security: Validate query complexity to prevent DoS
        try:
            validate_query_complexity(query)
        except QueryComplexityError as e:
            logger.warning(
                f"Query complexity limit exceeded: user_query={sanitize_for_log(query)}, "
                f"reason={e.reason}"
            )
            # Return empty results (graceful degradation)
            return []

        # Build FTS5 query
        if normalize and not is_phrase:
            # Generate variants for article matching
            # Note: variants are internally generated from user input,
            # but the variant generation itself is safe (no special chars injection)
            variants = normalize_hebrew_search(query)
            if not variants:
                return []

            # Build OR query: "variant1" OR "variant2" OR ...
            # Variants are already normalized and safe to quote
            fts_query = ' OR '.join(f'"{v}"' for v in variants)
        elif is_phrase:
            # Exact phrase match - sanitize to prevent FTS5 injection
            # Note: sanitize_fts5_query() already wraps in quotes
            fts_query = sanitize_fts5_query(query, strict=True)
        else:
            # Raw query (no normalization) - MUST sanitize for security
            fts_query = sanitize_fts5_query(query, strict=True)

        logger.info(
            f"Concordance search: project={project_id}, "
            f"user_query={sanitize_for_log(query)}, limit={limit}"
        )

        try:
            # FTS5 query with snippet() for KWIC
            # Join through: sentence_fts → document_sentence → source_document → source_corpus
            sql = text("""
                SELECT
                    ds.sentence_id,
                    ds.doc_id,
                    sd.file_name,
                    snippet(sentence_fts, 0, '<<', '>>', '...', 12) AS snip,
                    bm25(sentence_fts) AS rank,
                    ds.text AS full_sentence
                FROM sentence_fts
                JOIN document_sentence ds ON ds.sentence_id = sentence_fts.rowid
                JOIN source_document sd ON sd.doc_id = ds.doc_id
                JOIN source_corpus sc ON sc.corpus_id = sd.corpus_id
                WHERE sentence_fts MATCH :q
                  AND sc.project_id = :project_id
                ORDER BY rank ASC, ds.sentence_id ASC
                LIMIT :limit OFFSET :offset
            """)

            result = session.execute(
                sql,
                {
                    'q': fts_query,
                    'project_id': project_id,
                    'limit': limit,
                    'offset': offset
                }
            )

            rows = result.fetchall()

            # Parse snippet into left/match/right
            results = []
            for row in rows:
                sentence_id, doc_id, file_name, snip, rank, full_sentence = row

                # Parse snippet markers: << match >>
                left, match, right = self._parse_snippet(snip)

                results.append(KWICResult(
                    sentence_id=sentence_id,
                    doc_id=doc_id,
                    doc_name=file_name,
                    left_context=left,
                    match=match,
                    right_context=right
                ))

            logger.info(f"Concordance search returned {len(results)} results")
            return results

        except Exception as e:
            logger.exception(
                f"Concordance search failed: project={project_id}, "
                f"user_query={sanitize_for_log(query)}, error={str(e)}"
            )
            # Return empty list for graceful degradation
            # UI layer will show "No results" rather than crashing
            return []

    def _parse_snippet(self, snip: str) -> tuple[str, str, str]:
        """
        Parse FTS5 snippet into left/match/right.

        Snippet format: "...left <<match>> right..."

        Args:
            snip: Snippet from FTS5 with << >> markers

        Returns:
            Tuple of (left_context, match, right_context)
        """
        # Find first match (in case of multiple matches in sentence)
        match_start = snip.find('<<')
        match_end = snip.find('>>', match_start)

        if match_start == -1 or match_end == -1:
            # No match markers (shouldn't happen, but defensive)
            return ('', snip, '')

        left = snip[:match_start]
        match = snip[match_start + 2:match_end]
        right = snip[match_end + 2:]

        return (left.strip(), match.strip(), right.strip())
