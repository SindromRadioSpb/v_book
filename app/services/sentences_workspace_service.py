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

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.infra.sa_models import (
    DocumentSentence,
    SourceDocument,
    SourceCorpus,
    TMEntry,
    PronunciationEntry,
)
from app.domain.dto import SentenceDTO
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
        stmt = (
            select(DocumentSentence, SourceDocument.file_name)
            .join(SourceDocument, DocumentSentence.doc_id == SourceDocument.doc_id)
            .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
            .where(SourceCorpus.project_id == project_id)
        )

        if doc_id_filter is not None:
            stmt = stmt.where(DocumentSentence.doc_id == doc_id_filter)

        if text_search:
            stmt = stmt.where(DocumentSentence.text.ilike(f"%{text_search}%"))

        # Safe sort allowlist
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

        # Pagination
        offset = (page - 1) * page_size
        stmt = stmt.limit(page_size).offset(offset)

        rows = session.execute(stmt).all()

        # Collect sentence IDs and texts for batch overlay lookups
        sentence_ids = [r[0].sentence_id for r in rows]
        sentence_texts = [r[0].text for r in rows]
        src_lang = self._get_project_src_lang(session, project_id)

        # Batch overlays
        translation_map = self._batch_get_translations(
            session, project_id, src_lang, sentence_texts
        )
        pronunciation_map = self._batch_get_pronunciations(session, src_lang, sentence_texts)
        audio_map = self._batch_get_audio(session, src_lang, sentence_texts)

        result = []
        for sent, doc_name in rows:
            text = sent.text
            norm = self._norm(src_lang, text)
            translation_entry = translation_map.get(norm)
            result.append(
                SentenceDTO(
                    sentence_id=sent.sentence_id,
                    doc_id=sent.doc_id,
                    doc_name=doc_name or "",
                    sent_index=sent.sent_index,
                    text=text,
                    translation=translation_entry[0] if translation_entry else None,
                    translation_status=translation_entry[1] if translation_entry else None,
                    translation_source=translation_entry[2] if translation_entry else None,
                    pronunciation_text=pronunciation_map.get(norm),
                    audio_status=audio_map.get(norm),
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
        """Count sentences for pagination without fetching rows."""
        stmt = (
            select(func.count(DocumentSentence.sentence_id))
            .join(SourceDocument, DocumentSentence.doc_id == SourceDocument.doc_id)
            .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
            .where(SourceCorpus.project_id == project_id)
        )
        if doc_id_filter is not None:
            stmt = stmt.where(DocumentSentence.doc_id == doc_id_filter)
        if text_search:
            stmt = stmt.where(DocumentSentence.text.ilike(f"%{text_search}%"))
        return session.execute(stmt).scalar_one_or_none() or 0

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
        stmt = (
            select(DocumentSentence.sentence_id)
            .join(SourceDocument, DocumentSentence.doc_id == SourceDocument.doc_id)
            .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
            .where(SourceCorpus.project_id == project_id)
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
        stmt = (
            select(DocumentSentence.sentence_id)
            .join(SourceDocument, DocumentSentence.doc_id == SourceDocument.doc_id)
            .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
            .where(SourceCorpus.project_id == project_id)
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

    def _batch_get_pronunciations(
        self,
        session: Session,
        src_lang: str,
        texts: List[str],
    ) -> Dict[str, str]:
        """Return {norm: niqqud_text} for sentence texts using PronunciationEntry.

        Normalizes raw texts before querying PronunciationEntry.src_norm.
        Returns dict keyed by normalized form so callers can use the same norm
        they compute per-row in list_sentences().
        """
        if not texts:
            return {}
        norms = [self._norm(src_lang, t) for t in texts]
        norm_set = list(set(norms))
        stmt = select(
            PronunciationEntry.src_norm,
            PronunciationEntry.niqqud_text,
        ).where(
            PronunciationEntry.lang == src_lang,
            PronunciationEntry.src_norm.in_(norm_set),
        )
        from app.services.pronunciation_quality_service import PronunciationQualityService
        return {
            src: pron
            for src, pron in session.execute(stmt).all()
            if pron and PronunciationQualityService.has_hebrew_nikud(pron)
        }

    def _batch_get_audio(
        self,
        session: Session,
        src_lang: str,
        texts: List[str],
    ) -> Dict[str, str]:
        """Return {norm_text: audio_status} using AudioAssetService.bulk_get_status_any."""
        if not texts:
            return {}
        try:
            from app.services.audio_asset_service import AudioAssetService
            norms = list({self._norm(src_lang, t) for t in texts})
            svc = AudioAssetService()
            return svc.bulk_get_status_any(session, lang=src_lang, norm_texts=norms)
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

    @staticmethod
    def _get_project_src_lang(session: Session, project_id: int) -> str:
        """Get src_lang for a project (default 'he')."""
        from app.infra.sa_models import DictProject
        proj = session.get(DictProject, project_id)
        return proj.src_lang if proj else "he"
