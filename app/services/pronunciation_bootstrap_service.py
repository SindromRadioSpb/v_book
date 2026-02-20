"""Offline bootstrap for pronunciation layer."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional

from sqlalchemy import asc, select
from sqlalchemy.orm import Session

from app.infra.pronunciation import PhonikudAdapter, PhonikudHealthReport, PhonikudMode
from app.infra.sa_models import Lemma, TermCluster, UserDictionaryItem
from app.services.pronunciation_service import PronunciationService

logger = logging.getLogger(__name__)


@dataclass
class PronunciationBootstrapResult:
    total_candidates: int
    generated_candidates: int
    updated: int
    skipped: int
    failed: int
    cancelled: bool = False
    generator_mode: str = "fallback"


class PronunciationGenerator:
    """Generator interface for offline pronunciation enrichment."""

    def generate(self, lang: str, src_norms: List[str]) -> Dict[str, Dict[str, Optional[str]]]:
        raise NotImplementedError


class NoopPronunciationGenerator(PronunciationGenerator):
    """Fallback generator that produces no entries."""

    def generate(self, lang: str, src_norms: List[str]) -> Dict[str, Dict[str, Optional[str]]]:
        _ = lang
        _ = src_norms
        return {}


class PhonikudPronunciationGenerator(PronunciationGenerator):
    """Best-effort adapter for local Phonikud-like libraries."""

    def __init__(self, *, strict: bool = False, model_path: Optional[str] = None, enabled: bool = True):
        self.strict = strict
        self._adapter = PhonikudAdapter(model_path=model_path, enabled=enabled)

    @property
    def mode(self) -> str:
        return self._adapter.last_mode

    def health_check(self, sample_texts: Optional[List[str]] = None) -> PhonikudHealthReport:
        return self._adapter.health_check(sample_texts)

    def generate(self, lang: str, src_norms: List[str]) -> Dict[str, Dict[str, Optional[str]]]:
        if lang.strip().lower() not in {"he", "he-il"}:
            return {}
        if not self._adapter.is_available():
            if self.strict:
                raise RuntimeError("Phonikud generator is not available")
            return {}
        generated = self._adapter.infer(src_norms)
        mode = self._adapter.last_mode
        confidence = 0.8 if mode == PhonikudMode.REAL_INFERENCE.value else 0.2

        result: Dict[str, Dict[str, Optional[str]]] = {}
        for src_norm in src_norms:
            try:
                niqqud = generated.get(src_norm)
                if niqqud and str(niqqud).strip():
                    result[src_norm] = {
                        "niqqud_text": str(niqqud).strip(),
                        "ipa": None,
                        "reading_text": None,
                        "source": "auto_phonikud",
                        "confidence": confidence,
                        "notes": f"auto:phonikud:{mode}",
                    }
            except Exception as exc:
                logger.debug("Phonikud generation failed for '%s': %s", src_norm, exc)
        return result

class PronunciationBootstrapService:
    """Build pronunciation entries from existing lexical corpus."""

    def __init__(
        self,
        *,
        pronunciation_service: Optional[PronunciationService] = None,
        generator: Optional[PronunciationGenerator] = None,
    ):
        self.pronunciation_service = pronunciation_service or PronunciationService()
        self.generator = generator or NoopPronunciationGenerator()

    def collect_unique_src_norms(
        self,
        session: Session,
        *,
        lang: str,
        include_lemmas: bool = True,
        include_terms: bool = True,
        include_user_dictionary: bool = True,
    ) -> List[str]:
        """Collect unique source norms from lexical tables."""
        values = set()

        if include_lemmas:
            try:
                lemma_rows = session.execute(
                    select(Lemma.norm_text)
                    .where(Lemma.norm_text.is_not(None))
                    .order_by(asc(Lemma.norm_text))
                ).scalars().all()
                values.update(v.strip() for v in lemma_rows if (v or "").strip())
            except Exception as exc:
                logger.debug("collect_unique_src_norms lemmas skipped: %s", exc)

        if include_terms:
            try:
                term_rows = session.execute(
                    select(TermCluster.norm_text)
                    .where(TermCluster.norm_text.is_not(None))
                    .order_by(asc(TermCluster.norm_text))
                ).scalars().all()
                values.update(v.strip() for v in term_rows if (v or "").strip())
            except Exception as exc:
                logger.debug("collect_unique_src_norms terms skipped: %s", exc)

        if include_user_dictionary:
            try:
                ud_rows = session.execute(
                    select(UserDictionaryItem.src_norm)
                    .where(UserDictionaryItem.src_lang == lang)
                    .where(UserDictionaryItem.src_norm.is_not(None))
                    .order_by(asc(UserDictionaryItem.src_norm))
                ).scalars().all()
                values.update(v.strip() for v in ud_rows if (v or "").strip())
            except Exception as exc:
                logger.debug("collect_unique_src_norms user_dictionary skipped: %s", exc)

        return sorted(values)

    def bootstrap(
        self,
        session: Session,
        *,
        lang: str,
        chunk_size: int = 500,
        rebuild_auto: bool = False,
        limit: Optional[int] = None,
        include_lemmas: bool = True,
        include_terms: bool = True,
        include_user_dictionary: bool = True,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> PronunciationBootstrapResult:
        """Bootstrap pronunciation entries from available lexical norms."""
        src_norms = self.collect_unique_src_norms(
            session,
            lang=lang,
            include_lemmas=include_lemmas,
            include_terms=include_terms,
            include_user_dictionary=include_user_dictionary,
        )
        if limit is not None and int(limit) > 0:
            src_norms = src_norms[: int(limit)]
        total = len(src_norms)
        if total == 0:
            return PronunciationBootstrapResult(
                total_candidates=0,
                generated_candidates=0,
                updated=0,
                skipped=0,
                failed=0,
            )

        generated_candidates = 0
        updated = 0
        skipped = 0
        failed = 0
        cancelled = False
        processed = 0
        chunk_size = max(1, int(chunk_size))

        for idx in range(0, total, chunk_size):
            if cancel_check and cancel_check():
                cancelled = True
                break
            chunk = src_norms[idx : idx + chunk_size]
            generated_map = self.generator.generate(lang, chunk)
            generated_candidates += len(generated_map)

            entries = []
            for src_norm in chunk:
                item = generated_map.get(src_norm)
                if not item:
                    continue
                entries.append(
                    {
                        "src_norm": src_norm,
                        "niqqud_text": item.get("niqqud_text"),
                        "ipa": item.get("ipa"),
                        "reading_text": item.get("reading_text"),
                        "confidence": item.get("confidence"),
                        "notes": item.get("notes"),
                    }
                )

            result = self.pronunciation_service.bulk_upsert_auto(
                session,
                lang=lang,
                entries=entries,
                chunk_size=chunk_size,
                rebuild_auto=rebuild_auto,
                source="auto_phonikud",
            )
            updated += int(result.get("updated", 0))
            skipped += int(result.get("skipped", 0))
            failed += int(result.get("failed", 0))

            processed = min(total, idx + len(chunk))
            if progress_callback:
                progress_callback(processed, total)

        return PronunciationBootstrapResult(
            total_candidates=total,
            generated_candidates=generated_candidates,
            updated=updated,
            skipped=skipped,
            failed=failed,
            cancelled=cancelled,
            generator_mode=(getattr(self.generator, "mode", None) or "fallback"),
        )
