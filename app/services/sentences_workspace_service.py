"""Sentences workspace service — paginated sentence listing with overlay data.

Provides:
- Paginated list of DocumentSentence rows for a project/corpus.
- Batch overlay lookups (translation, pronunciation, audio) — no per-row queries.
- ID-set helpers: selected IDs, current-page IDs, all-filtered IDs.

Threading: all methods run in a caller thread (typically a QThread worker).
WAL safety: short read transactions only; writes go through existing services.
"""
import logging
from typing import List, Optional, Dict, Set

from sqlalchemy import select, func, text
from sqlalchemy.orm import Session

from app.infra.sa_models import (
    DocumentSentence,
    SourceDocument,
    SourceCorpus,
    TMEntry,
    SentencePronunciation,
)
from app.domain.dto import SentenceDTO, SentenceNiqqudOverlay
from app.domain.normalization.normalizer import normalize_for_tm

logger = logging.getLogger(__name__)


class SentencesWorkspaceService:
    """Paginated sentence listing with batch overlays (translation/pronunciation/audio)."""

    # ------------------------------------------------------------------
    # Query — paginated list
    # ------------------------------------------------------------------

    def list_sentences(
        self,
        session: Session,
        project_id: int,
        *,
        doc_id_filter: Optional[int] = None,
        text_search: Optional[str] = None,
        sort_by: str = "sentence_id",
        sort_dir: str = "asc",
        page: int = 1,
        page_size: int = 100,
    ) -> List[SentenceDTO]:
        """Return one page of sentences for the project with overlay data.

        Args:
            project_id: Project scope (all corpora of this project).
            doc_id_filter: If set, restrict to one document.
            text_search: Case-insensitive substring match on sentence text.
            sort_by: Column ('sentence_id', 'doc_id', 'sent_index'). Validated allowlist.
            sort_dir: 'asc' or 'desc'.
            page: 1-based page number.
            page_size: Rows per page.
        Returns:
            List of SentenceDTO with overlays populated.
        """
        corpus_ids = self._get_project_corpus_ids(session, project_id)
        rows = self._load_sentence_page_rows(
            session,
            corpus_ids=corpus_ids,
            doc_id_filter=doc_id_filter,
            text_search=text_search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            page=page,
            page_size=page_size,
        )

        # Collect sentence IDs and texts for batch overlay lookups
        sentence_ids = [int(row["sentence_id"]) for row in rows]
        sentence_texts = [str(row["text"]) for row in rows]
        src_lang = self._get_project_src_lang(session, project_id)

        # Batch overlays
        translation_map = self._batch_get_translations(
            session, project_id, src_lang, sentence_texts
        )
        # Use sentence-level niqqud (sentence_pronunciation table)
        niqqud_map = self._batch_get_sentence_niqqud(session, sentence_ids)
        audio_map = self._batch_get_audio(session, src_lang, sentence_texts)

        result = []
        for row in rows:
            sentence_id = int(row["sentence_id"])
            text = str(row["text"])
            norm = self._norm(src_lang, text)
            translation_entry = translation_map.get(norm)
            overlay: Optional[SentenceNiqqudOverlay] = niqqud_map.get(sentence_id)
            result.append(
                SentenceDTO(
                    sentence_id=sentence_id,
                    doc_id=int(row["doc_id"]),
                    doc_name=str(row.get("file_name") or ""),
                    sent_index=int(row["sent_index"]),
                    text=text,
                    translation=translation_entry[0] if translation_entry else None,
                    translation_status=translation_entry[1] if translation_entry else None,
                    translation_source=translation_entry[2] if translation_entry else None,
                    pronunciation_text=overlay.niqqud_text if overlay else None,
                    niqqud_qc=overlay.qc_status if overlay else None,
                    niqqud_source=overlay.source if overlay else None,
                    niqqud_confidence=overlay.confidence if overlay else None,
                    niqqud_coverage=overlay.niqqud_coverage if overlay else None,
                    niqqud_is_override=overlay.is_override if overlay else False,
                    niqqud_review=overlay.review_status if overlay else None,
                    audio_status=audio_map.get((norm, text)),
                )
            )
        return result

    def count_sentences(
        self,
        session: Session,
        project_id: int,
        *,
        doc_id_filter: Optional[int] = None,
        text_search: Optional[str] = None,
    ) -> int:
        """Count sentences for pagination.

        Fast path (migration-030 covering index): when no doc/text filter is
        active, uses SUM(sentence_count) over source_document rows rather than
        a full 13 M-row JOIN COUNT on document_sentence.
        Typical latency on hewiki scale:
          filtered   path (doc_id / text): <5 ms  (idx_sentence_doc)
          unfiltered path (SUM):           ~10 ms (idx_doc_corpus_sentence_count_sum)
          old JOIN COUNT (unfiltered):     >2 s   (TEMP B-TREE on 13 M rows)
        """
        # Fast path: no per-sentence filtering needed — sum the cached column.
        if doc_id_filter is None and not text_search:
            stmt = (
                select(func.coalesce(func.sum(SourceDocument.sentence_count), 0))
                .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
                .where(SourceCorpus.project_id == project_id)
            )
            return int(session.execute(stmt).scalar() or 0)

        # Filtered path: must touch individual sentence rows.
        # PATCH-Q: use corpus_id on document_sentence to avoid 3-table JOIN.
        corpus_ids = self._get_project_corpus_ids(session, project_id)
        stmt = select(func.count(DocumentSentence.sentence_id)).where(
            DocumentSentence.corpus_id.in_(corpus_ids)
        )
        if doc_id_filter is not None:
            stmt = stmt.where(DocumentSentence.doc_id == doc_id_filter)
        if text_search:
            stmt = stmt.where(DocumentSentence.text.ilike(f"%{text_search}%"))
        return int(session.execute(stmt).scalar_one_or_none() or 0)

    # ------------------------------------------------------------------
    # ID-set helpers (for batch action scope)
    # ------------------------------------------------------------------

    def get_page_sentence_ids(
        self,
        session: Session,
        project_id: int,
        *,
        doc_id_filter: Optional[int] = None,
        text_search: Optional[str] = None,
        page: int = 1,
        page_size: int = 100,
    ) -> List[int]:
        """Return sentence_ids for the current page (for batch actions)."""
        corpus_ids = self._get_project_corpus_ids(session, project_id)
        stmt = (
            select(DocumentSentence.sentence_id)
            .where(DocumentSentence.corpus_id.in_(corpus_ids))
            .order_by(DocumentSentence.sentence_id.asc())
        )
        if doc_id_filter is not None:
            stmt = stmt.where(DocumentSentence.doc_id == doc_id_filter)
        if text_search:
            stmt = stmt.where(DocumentSentence.text.ilike(f"%{text_search}%"))
        offset = (page - 1) * page_size
        stmt = stmt.limit(page_size).offset(offset)
        return [row[0] for row in session.execute(stmt).all()]

    def get_all_filtered_sentence_ids(
        self,
        session: Session,
        project_id: int,
        *,
        doc_id_filter: Optional[int] = None,
        text_search: Optional[str] = None,
    ) -> List[int]:
        """Return all sentence_ids matching current filter (for 'All Filtered' batch action)."""
        corpus_ids = self._get_project_corpus_ids(session, project_id)
        stmt = (
            select(DocumentSentence.sentence_id)
            .where(DocumentSentence.corpus_id.in_(corpus_ids))
            .order_by(DocumentSentence.sentence_id.asc())
        )
        if doc_id_filter is not None:
            stmt = stmt.where(DocumentSentence.doc_id == doc_id_filter)
        if text_search:
            stmt = stmt.where(DocumentSentence.text.ilike(f"%{text_search}%"))
        return [row[0] for row in session.execute(stmt).all()]

    def get_sentence_texts_by_ids(
        self,
        session: Session,
        sentence_ids: List[int],
    ) -> Dict[int, str]:
        """Batch-fetch sentence texts for a list of IDs (for batch action workers)."""
        if not sentence_ids:
            return {}
        stmt = select(
            DocumentSentence.sentence_id, DocumentSentence.text
        ).where(DocumentSentence.sentence_id.in_(sentence_ids))
        return {sid: text for sid, text in session.execute(stmt).all()}

    # ------------------------------------------------------------------
    # Internal overlay helpers (batch, no per-row queries)
    # ------------------------------------------------------------------

    def _batch_get_translations(
        self,
        session: Session,
        project_id: int,
        src_lang: str,
        texts: List[str],
    ) -> Dict[str, tuple]:
        """Return {norm_text: (translation, status, source)} for sentence texts.

        Looks up kind='surface' TM entries for this project.
        Returns dict keyed by normalized text.
        """
        if not texts:
            return {}
        norms = [self._norm(src_lang, t) for t in texts]
        norm_set = list(set(norms))

        stmt = select(
            TMEntry.src_norm,
            TMEntry.translation,
            TMEntry.status,
            TMEntry.origin,
        ).where(
            TMEntry.kind == "surface",
            TMEntry.src_lang == src_lang,
            TMEntry.src_norm.in_(norm_set),
            TMEntry.project_id == project_id,
            TMEntry.status.in_(["draft", "approved"]),
        ).order_by(
            # Prefer approved over draft when duplicates
            TMEntry.status.desc()
        )

        result: Dict[str, tuple] = {}
        for src_norm, translation, status, origin in session.execute(stmt).all():
            if src_norm not in result:  # first wins (ordered by status desc)
                result[src_norm] = (translation, status, origin)
        return result

    def _batch_get_sentence_niqqud(
        self,
        session: Session,
        sentence_ids: List[int],
    ) -> Dict[int, "SentenceNiqqudOverlay"]:
        """Return {sentence_id: SentenceNiqqudOverlay} from sentence_pronunciation table.

        Uses the dedicated sentence-level niqqud store (Migration 024).
        Only returns rows; the SentencePronunciationService._to_overlay() filters
        entries without actual nikud marks.
        """
        if not sentence_ids:
            return {}
        try:
            from app.services.sentence_pronunciation_service import SentencePronunciationService
            svc = SentencePronunciationService()
            return svc.bulk_get_niqqud(session, sentence_ids)
        except Exception:
            logger.debug("sentence_pronunciation lookup failed (table may not exist yet)", exc_info=True)
            return {}

    def _batch_get_audio(
        self,
        session: Session,
        src_lang: str,
        texts: List[str],
    ) -> Dict[tuple[str, str], str]:
        """Return {(norm_text, source_text): audio_status} using hash-aware audio lookup."""
        if not texts:
            return {}
        try:
            from app.services.audio_asset_service import AudioAssetService
            svc = AudioAssetService()
            items = [
                {
                    "lang": src_lang,
                    "norm_text": self._norm(src_lang, text),
                    "source_text": text,
                }
                for text in texts
                if text
            ]
            mapping = svc.bulk_get_status_for_items(session, items=items)
            return {
                (norm_text, source_text): status
                for (_lang, norm_text, source_text), status in mapping.items()
            }
        except Exception:
            logger.debug("Audio status lookup failed (skipping overlay)", exc_info=True)
            return {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _norm(lang: str, text: str) -> str:
        """Normalize text to TM surface key."""
        try:
            return normalize_for_tm(lang, text, "surface").norm
        except Exception:
            return text.strip().lower()

    def _load_sentence_page_rows(
        self,
        session: Session,
        *,
        corpus_ids: List[int],
        doc_id_filter: Optional[int],
        text_search: Optional[str],
        sort_by: str,
        sort_dir: str,
        page: int,
        page_size: int,
    ) -> List[dict]:
        if not corpus_ids:
            return []

        if self._should_use_sentence_id_pk_scan(
            doc_id_filter=doc_id_filter,
            sort_by=sort_by,
            sort_dir=sort_dir,
        ):
            return self._load_sentence_page_rows_pk_scan(
                session,
                corpus_ids=corpus_ids,
                text_search=text_search,
                page=page,
                page_size=page_size,
            )

        stmt = (
            select(DocumentSentence, SourceDocument.file_name)
            .join(SourceDocument, DocumentSentence.doc_id == SourceDocument.doc_id)
            .where(DocumentSentence.corpus_id.in_(corpus_ids))
        )

        if doc_id_filter is not None:
            stmt = stmt.where(DocumentSentence.doc_id == doc_id_filter)

        if text_search:
            stmt = stmt.where(DocumentSentence.text.ilike(f"%{text_search}%"))

        # Keep the general ORM path for non-default sorts and doc-scoped queries.
        _sort_map = {
            "sentence_id": DocumentSentence.sentence_id,
            "doc_id": DocumentSentence.doc_id,
            "sent_index": DocumentSentence.sent_index,
        }
        sort_col = _sort_map.get(sort_by, DocumentSentence.sentence_id)
        if sort_dir == "desc":
            stmt = stmt.order_by(sort_col.desc(), DocumentSentence.sent_index.asc())
        else:
            stmt = stmt.order_by(sort_col.asc(), DocumentSentence.sent_index.asc())

        offset = (page - 1) * page_size
        stmt = stmt.limit(page_size).offset(offset)
        return [
            {
                "sentence_id": int(sent.sentence_id),
                "doc_id": int(sent.doc_id),
                "sent_index": int(sent.sent_index),
                "text": sent.text,
                "file_name": doc_name or "",
            }
            for sent, doc_name in session.execute(stmt).all()
        ]

    @staticmethod
    def _should_use_sentence_id_pk_scan(
        *,
        doc_id_filter: Optional[int],
        sort_by: str,
        sort_dir: str,
    ) -> bool:
        return (
            doc_id_filter is None
            and (sort_by or "sentence_id") == "sentence_id"
            and (sort_dir or "asc").lower() == "asc"
        )

    def _load_sentence_page_rows_pk_scan(
        self,
        session: Session,
        *,
        corpus_ids: List[int],
        text_search: Optional[str],
        page: int,
        page_size: int,
    ) -> List[dict]:
        # On large multi-corpus projects, SQLite can choose idx_sentence_corpus_sent_id
        # plus TEMP B-TREE ORDER BY for the default page load. For the actual
        # user-visible path (sentence_id ASC), a rowid/PK-ordered scan is cheaper.
        corpus_params = {
            f"corpus_id_{idx}": int(corpus_id)
            for idx, corpus_id in enumerate(corpus_ids)
        }
        where_parts = [
            "corpus_id IN ({})".format(
                ", ".join(f":{name}" for name in corpus_params.keys())
            )
        ]
        params: Dict[str, object] = {
            **corpus_params,
            "limit": int(page_size),
            "offset": int((page - 1) * page_size),
        }
        if text_search:
            where_parts.append("lower(text) LIKE lower(:text_search)")
            params["text_search"] = f"%{text_search}%"

        stmt = text(
            f"""
            SELECT sentence_id, doc_id, sent_index, text
            FROM document_sentence NOT INDEXED
            WHERE {' AND '.join(where_parts)}
            ORDER BY sentence_id ASC
            LIMIT :limit OFFSET :offset
            """
        )
        rows = [dict(row) for row in session.execute(stmt, params).mappings().all()]
        if not rows:
            return rows

        doc_name_map = self._get_doc_names_by_ids(
            session,
            [int(row["doc_id"]) for row in rows],
        )
        for row in rows:
            row["file_name"] = doc_name_map.get(int(row["doc_id"]), "")
        return rows

    @staticmethod
    def _get_doc_names_by_ids(session: Session, doc_ids: List[int]) -> Dict[int, str]:
        if not doc_ids:
            return {}
        unique_doc_ids = sorted({int(doc_id) for doc_id in doc_ids})
        stmt = select(SourceDocument.doc_id, SourceDocument.file_name).where(
            SourceDocument.doc_id.in_(unique_doc_ids)
        )
        return {
            int(doc_id): file_name or ""
            for doc_id, file_name in session.execute(stmt).all()
        }

    @staticmethod
    def _get_project_corpus_ids(session: Session, project_id: int) -> List[int]:
        """Return all corpus_ids belonging to project_id (cached in caller for batch use)."""
        stmt = select(SourceCorpus.corpus_id).where(SourceCorpus.project_id == project_id)
        return [row[0] for row in session.execute(stmt).all()]

    @staticmethod
    def _get_project_src_lang(session: Session, project_id: int) -> str:
        """Get src_lang for a project (default 'he')."""
        from app.infra.sa_models import DictProject
        proj = session.get(DictProject, project_id)
        return proj.src_lang if proj else "he"
