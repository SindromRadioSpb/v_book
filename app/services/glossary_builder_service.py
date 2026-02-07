"""Glossary Builder Service for MT Provider Chain.

Builds canonical glossary from approved terms with deterministic hashing
and provider-specific adapters.

Architecture:
- Extract approved terms from tm_entry (status='approved')
- Build canonical glossary with stable sort
- Compute deterministic glossary_hash (SHA256)
- Provide provider-specific adapters (DeepL, Microsoft, LibreTranslate)
- Handle conflicts (duplicate source terms → highest priority)

Usage:
    service = GlossaryBuilderService(session)
    canonical = service.build_canonical_glossary(
        src_lang="he",
        tgt_lang="ru",
        project_id=1
    )
    glossary_hash = canonical.glossary_hash
    deepl_payload = service.to_deepl_format(canonical)
"""
import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infra.sa_models import TMEntry
from app.infra.settings import SettingsService

logger = logging.getLogger(__name__)


@dataclass
class GlossaryEntry:
    """Single glossary entry (source → target)."""

    source_term: str  # Original source term
    target_term: str  # Approved translation
    canonical_key: str  # Normalized key for dedup (lowercase, strip)
    priority_score: float  # Higher = more important (default: 1.0)


@dataclass
class CanonicalGlossary:
    """Canonical glossary format (provider-agnostic)."""

    entries: List[GlossaryEntry]
    source_lang: str  # e.g., "he" (Hebrew)
    target_lang: str  # e.g., "ru" (Russian)
    glossary_hash: str  # SHA256 of deterministic JSON
    total_entries: int
    truncated: bool  # True if hit provider limit
    size_bytes: int  # Estimate for provider payload


class GlossaryBuilderService:
    """
    Build canonical glossary from approved terms.

    Responsibilities:
    - Query approved terms from tm_entry (status='approved')
    - Build canonical glossary with deterministic sort
    - Compute glossary_hash (SHA256 of sorted JSON)
    - Handle conflicts (duplicate source → highest priority)
    - Provide provider-specific adapters
    """

    def __init__(self, session: Session):
        """
        Initialize glossary builder.

        Args:
            session: SQLAlchemy session
        """
        self._session = session
        self._settings = SettingsService.get_instance()

    def build_canonical_glossary(
        self,
        src_lang: str,
        tgt_lang: str,
        project_id: Optional[int] = None,
        max_entries: Optional[int] = None,
    ) -> CanonicalGlossary:
        """
        Build canonical glossary from approved terms.

        Args:
            src_lang: Source language (e.g., "he")
            tgt_lang: Target language (e.g., "ru")
            project_id: Project ID (None = global terms)
            max_entries: Max entries (None = use default from settings)

        Returns:
            CanonicalGlossary with deterministic hash
        """
        # Get max entries from settings if not specified
        if max_entries is None:
            max_entries = self._settings.get_int(
                "mt/glossary/max_entries_default", default=5000
            )

        # Query approved terms
        stmt = (
            select(TMEntry)
            .where(
                TMEntry.status == "approved",
                TMEntry.src_lang == src_lang,
                TMEntry.tgt_lang == tgt_lang,
            )
        )

        # Filter by project (include NULL = global terms)
        if project_id is not None:
            stmt = stmt.where(
                (TMEntry.project_id == project_id) | (TMEntry.project_id.is_(None))
            )
        else:
            stmt = stmt.where(TMEntry.project_id.is_(None))

        # Order by confidence DESC (higher confidence = higher priority)
        # Then by src_text ASC (stable tie-breaker)
        stmt = stmt.order_by(
            TMEntry.confidence.desc().nulls_last(),
            TMEntry.src_text.asc()
        )

        results = self._session.execute(stmt).scalars().all()

        # Build entries with conflict resolution
        entries_dict: Dict[str, GlossaryEntry] = {}  # canonical_key → entry
        for tm_entry in results:
            canonical_key = self._normalize_key(tm_entry.src_text)
            priority_score = tm_entry.confidence if tm_entry.confidence else 0.5

            # Conflict resolution: keep entry with highest priority
            if canonical_key in entries_dict:
                existing = entries_dict[canonical_key]
                if priority_score > existing.priority_score:
                    logger.warning(
                        f"Glossary conflict: '{tm_entry.src_text}' has multiple targets, "
                        f"selected '{tm_entry.translation}' (priority: {priority_score:.2f}) "
                        f"over '{existing.target_term}' (priority: {existing.priority_score:.2f})"
                    )
                    entries_dict[canonical_key] = GlossaryEntry(
                        source_term=tm_entry.src_text,
                        target_term=tm_entry.translation,
                        canonical_key=canonical_key,
                        priority_score=priority_score,
                    )
                else:
                    logger.debug(
                        f"Glossary conflict: '{tm_entry.src_text}' → '{tm_entry.translation}' "
                        f"skipped (priority {priority_score:.2f} <= {existing.priority_score:.2f})"
                    )
            else:
                entries_dict[canonical_key] = GlossaryEntry(
                    source_term=tm_entry.src_text,
                    target_term=tm_entry.translation,
                    canonical_key=canonical_key,
                    priority_score=priority_score,
                )

        # Sort entries by canonical_key (stable sort)
        entries = sorted(entries_dict.values(), key=lambda e: e.canonical_key)

        # Truncate if needed
        total_entries = len(entries)
        truncated = total_entries > max_entries
        if truncated:
            logger.info(
                f"Glossary truncated: {total_entries} entries → {max_entries} "
                f"(provider limit)"
            )
            entries = entries[:max_entries]

        # Build canonical glossary
        canonical = CanonicalGlossary(
            entries=entries,
            source_lang=src_lang,
            target_lang=tgt_lang,
            glossary_hash="",  # Computed below
            total_entries=len(entries),
            truncated=truncated,
            size_bytes=0,  # Computed below
        )

        # Compute hash and size
        canonical.glossary_hash = self._compute_glossary_hash(canonical)
        canonical.size_bytes = self._estimate_size_bytes(canonical)

        logger.info(
            f"Built canonical glossary: {len(entries)} entries, "
            f"hash={canonical.glossary_hash[:8]}..., "
            f"size={canonical.size_bytes} bytes"
        )

        return canonical

    def _normalize_key(self, text: str) -> str:
        """
        Normalize text for canonical key (dedup).

        Args:
            text: Source text

        Returns:
            Normalized key (lowercase, stripped)
        """
        return text.strip().lower()

    def _compute_glossary_hash(self, canonical: CanonicalGlossary) -> str:
        """
        Compute deterministic hash for cache keying.

        Formula: SHA256(JSON with sorted keys)

        Args:
            canonical: Canonical glossary

        Returns:
            SHA256 hash (hex string)
        """
        payload = {
            "source_lang": canonical.source_lang,
            "target_lang": canonical.target_lang,
            "entries": [
                {"source": e.source_term, "target": e.target_term}
                for e in canonical.entries
            ],
        }

        # Sort keys for determinism
        json_str = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()

    def _estimate_size_bytes(self, canonical: CanonicalGlossary) -> int:
        """
        Estimate glossary payload size (for logging/monitoring).

        Args:
            canonical: Canonical glossary

        Returns:
            Estimated size in bytes
        """
        total_bytes = 0
        for entry in canonical.entries:
            # Estimate: len(source) + len(target) + separators
            total_bytes += len(entry.source_term.encode("utf-8"))
            total_bytes += len(entry.target_term.encode("utf-8"))
            total_bytes += 4  # Separator overhead (tab + newline)

        return total_bytes

    # ========================================================================
    # Provider-specific adapters
    # ========================================================================

    def to_provider_format(
        self, canonical: CanonicalGlossary, provider_id: str
    ) -> Optional[Dict]:
        """
        Convert canonical glossary to provider-specific format.

        Args:
            canonical: Canonical glossary
            provider_id: Provider ID (e.g., "deepl", "microsoft")

        Returns:
            Provider-specific payload or None if not supported
        """
        if provider_id == "deepl":
            return self.to_deepl_format(canonical)
        elif provider_id in ("microsoft", "microsoft_translator"):
            return self.to_microsoft_format(canonical)
        elif provider_id == "libretranslate":
            return self.to_libretranslate_format(canonical)
        else:
            logger.debug(f"Provider {provider_id} glossary format not implemented")
            return None

    def to_deepl_format(self, canonical: CanonicalGlossary) -> Dict:
        """
        Convert to DeepL glossary format.

        DeepL supports TSV format: source\\ttarget\\n
        Max entries: 5000 (configurable)

        Args:
            canonical: Canonical glossary

        Returns:
            DeepL-specific payload
        """
        max_entries = self._settings.get_int(
            "mt/glossary/max_entries_deepl", default=5000
        )

        entries = canonical.entries[:max_entries]
        entries_tsv = "\n".join(
            f"{e.source_term}\t{e.target_term}" for e in entries
        )

        return {
            "format": "tsv",
            "entries": entries_tsv,
            "source_lang": canonical.source_lang.upper(),
            "target_lang": canonical.target_lang.upper(),
            "entry_count": len(entries),
        }

    def to_microsoft_format(self, canonical: CanonicalGlossary) -> Dict:
        """
        Convert to Microsoft Custom Translator format.

        Microsoft supports dictionary (parallel arrays)
        Max entries: 10000 (configurable)

        Args:
            canonical: Canonical glossary

        Returns:
            Microsoft-specific payload
        """
        max_entries = self._settings.get_int(
            "mt/glossary/max_entries_microsoft", default=10000
        )

        entries = canonical.entries[:max_entries]

        return {
            "translations": [
                {"from": e.source_term, "to": e.target_term} for e in entries
            ]
        }

    def to_libretranslate_format(self, canonical: CanonicalGlossary) -> Dict:
        """
        Convert to LibreTranslate format.

        LibreTranslate does not support glossaries natively.
        Return empty dict, provider will skip glossary.

        Args:
            canonical: Canonical glossary

        Returns:
            Empty dict (no glossary support)
        """
        return {}
