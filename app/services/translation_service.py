"""M7 Translation Service with deterministic precedence.

Order of precedence (strict):
1. TM override (status=approved, then draft if allowed)
   - Project-scoped first, then global
2. Offline dict entries (status=approved), by priority
3. MT cache (if MT enabled)
4. MT provider (if MT enabled) → cached
5. None

All lookups use exact match on src_norm (normalized key).
"""

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.domain.normalization import normalize_for_tm
from app.infra.reliability import CircuitBreaker, RateLimiter
from app.infra.sa_models import DictEntry, DictSource, MTCache, TMAlias, TMEntry, TMGlobal, utc_now
from app.infra.settings import SettingsService
from app.infra.translators.base_provider import (
    TranslationRequest,
)
from app.infra.translators.base_provider import (
    TranslationResult as ProviderTranslationResult,
)
from app.infra.translators.providers_registry import ProvidersRegistry

logger = logging.getLogger(__name__)


@dataclass
class TranslationResult:
    """Result of translation lookup with explainability."""

    translation: str | None = None
    source: str = "none"  # tm|dict|mt_cache|mt|none
    status: str | None = None
    confidence: float | None = None
    origin: str | None = None
    matched_on: str | None = None  # src_norm|alias_norm|variant_norm
    match_key_used: str | None = None
    provider: str | None = None  # MT provider name
    dict_source_name: str | None = None
    tm_id: int | None = None
    notes: str | None = None


class TranslationService:
    """Translation Memory service with deterministic lookup."""

    def __init__(self):
        self.logger = logger

        # PATCH-P1-T04: Circuit breaker for MT providers
        settings = SettingsService.get_instance()
        cb_enabled = settings.get_bool("mt/circuit_breaker/enabled", default=True)
        if cb_enabled:
            failure_threshold = settings.get_int("mt/circuit_breaker/failure_threshold", default=3)
            cooldown_seconds = settings.get_int("mt/circuit_breaker/cooldown_seconds", default=60)
            self._circuit_breaker = CircuitBreaker(
                failure_threshold=failure_threshold,
                cooldown_seconds=cooldown_seconds,
            )
        else:
            self._circuit_breaker = None

        # PATCH-P1-T04: Rate limiter for MT providers
        self._rate_limiter = RateLimiter()

    def resolve_translation(
        self,
        session: Session,
        src_text: str,
        kind: str,
        src_lang: str = "he",
        tgt_lang: str = "ru",
        project_id: int | None = None,
        allow_draft: bool = False,
        use_mt: bool = False,
    ) -> TranslationResult:
        """
        Resolve translation for given text using precedence order.

        Args:
            session: SQLAlchemy session
            src_text: Source text to translate
            kind: Entry kind (lemma|ngram|term_cluster|surface)
            src_lang: Source language
            tgt_lang: Target language
            project_id: Project ID for project-scoped lookup (None = global only)
            allow_draft: Include draft TM entries
            use_mt: Use MT fallback if no manual translation found

        Returns:
            TranslationResult with translation and provenance
        """
        # Normalize input text
        normalized = normalize_for_tm(src_lang, src_text, kind)

        if not normalized.norm:
            self.logger.warning(f"Normalization produced empty key for: {src_text}")
            return TranslationResult()

        # 1. TM override lookup (project-scoped first, then global)
        result = self._lookup_tm(
            session, normalized.norm, kind, src_lang, tgt_lang, project_id, allow_draft
        )
        if result.translation:
            return result

        # 2. TM aliases lookup
        result = self._lookup_tm_aliases(
            session, normalized.norm, kind, src_lang, tgt_lang, project_id, allow_draft
        )
        if result.translation:
            return result

        # 3. Offline dict lookup
        result = self._lookup_dict(session, normalized.norm, kind, src_lang, tgt_lang, project_id)
        if result.translation:
            return result

        # 4. MT cache lookup (if MT enabled)
        if use_mt:
            result = self._lookup_mt_cache(session, normalized.norm, src_lang, tgt_lang, project_id)
            if result.translation:
                return result

            # 5. MT provider (PATCH-P1-T03: provider chain)
            result = self._translate_via_provider_chain(
                session=session,
                src_text=src_text,
                src_lang=src_lang,
                tgt_lang=tgt_lang,
                glossary=None,  # TODO P1-T05: Build glossary from approved terms
                allow_fallback=True,  # TODO P1-T05: Make configurable per-request
                trace_id="",  # Auto-generated if empty
            )
            if result.translation:
                return result

        # No translation found
        return TranslationResult()

    def _lookup_tm(
        self,
        session: Session,
        src_norm: str,
        kind: str,
        src_lang: str,
        tgt_lang: str,
        project_id: int | None,
        allow_draft: bool,
    ) -> TranslationResult:
        """Lookup TM entries (project-scoped first, then global)."""
        # Build status filter
        if allow_draft:
            status_filter = TMEntry.status.in_(["approved", "draft"])
        else:
            status_filter = TMEntry.status == "approved"

        # Try project-scoped first
        if project_id is not None:
            stmt = (
                select(TMEntry)
                .where(
                    and_(
                        TMEntry.project_id == project_id,
                        TMEntry.kind == kind,
                        TMEntry.src_lang == src_lang,
                        TMEntry.tgt_lang == tgt_lang,
                        TMEntry.src_norm == src_norm,
                        status_filter,
                    )
                )
                .order_by(
                    TMEntry.status.desc(),  # approved > draft
                    TMEntry.updated_at.desc(),
                )
                .limit(1)
            )

            entry = session.execute(stmt).scalar()
            if entry:
                return TranslationResult(
                    translation=entry.translation,
                    source="tm",
                    status=entry.status,
                    confidence=entry.confidence,
                    origin=entry.origin,
                    matched_on="src_norm",
                    match_key_used=src_norm,
                    tm_id=entry.tm_id,
                    notes=entry.notes,
                )

        # Try global TM
        stmt = (
            select(TMEntry)
            .where(
                and_(
                    TMEntry.project_id.is_(None),
                    TMEntry.kind == kind,
                    TMEntry.src_lang == src_lang,
                    TMEntry.tgt_lang == tgt_lang,
                    TMEntry.src_norm == src_norm,
                    status_filter,
                )
            )
            .order_by(
                TMEntry.status.desc(),
                TMEntry.updated_at.desc(),
            )
            .limit(1)
        )

        entry = session.execute(stmt).scalar()
        if entry:
            return TranslationResult(
                translation=entry.translation,
                source="tm",
                status=entry.status,
                confidence=entry.confidence,
                origin=entry.origin,
                matched_on="src_norm",
                match_key_used=src_norm,
                tm_id=entry.tm_id,
                notes=entry.notes,
            )

        # PATCH-19-03: Fallback to tm_global canonical layer
        stmt = (
            select(TMGlobal)
            .where(
                and_(
                    TMGlobal.src_lang == src_lang,
                    TMGlobal.tgt_lang == tgt_lang,
                    TMGlobal.kind == kind,
                    TMGlobal.src_norm == src_norm,
                    status_filter if allow_draft else TMGlobal.status == "approved",
                )
            )
            .limit(1)
        )
        global_entry = session.execute(stmt).scalar()
        if global_entry and global_entry.translation:
            return TranslationResult(
                translation=global_entry.translation,
                source="tm_global",
                status=global_entry.status,
                confidence=global_entry.confidence,
                origin=global_entry.origin,
                matched_on="src_norm",
                match_key_used=src_norm,
                notes=global_entry.notes,
            )

        return TranslationResult()

    def _lookup_tm_aliases(
        self,
        session: Session,
        src_norm: str,
        kind: str,
        src_lang: str,
        tgt_lang: str,
        project_id: int | None,
        allow_draft: bool,
    ) -> TranslationResult:
        """Lookup TM entries via aliases."""
        # Build status filter
        if allow_draft:
            status_filter = TMEntry.status.in_(["approved", "draft"])
        else:
            status_filter = TMEntry.status == "approved"

        # Query aliases
        stmt = (
            select(TMEntry, TMAlias.alias_norm)
            .join(TMAlias, TMAlias.tm_id == TMEntry.tm_id)
            .where(
                and_(
                    TMAlias.alias_norm == src_norm,
                    TMEntry.kind == kind,
                    TMEntry.src_lang == src_lang,
                    TMEntry.tgt_lang == tgt_lang,
                    status_filter,
                )
            )
        )

        # Prioritize project-scoped over global
        if project_id is not None:
            stmt = stmt.order_by(
                TMEntry.project_id.isnot(None).desc(),  # project-scoped first
                TMEntry.status.desc(),
                TMEntry.updated_at.desc(),
            )
        else:
            stmt = stmt.order_by(TMEntry.status.desc(), TMEntry.updated_at.desc())

        stmt = stmt.limit(1)

        result = session.execute(stmt).first()
        if result:
            entry, alias_norm = result
            return TranslationResult(
                translation=entry.translation,
                source="tm",
                status=entry.status,
                confidence=entry.confidence,
                origin=entry.origin,
                matched_on="alias_norm",
                match_key_used=alias_norm,
                tm_id=entry.tm_id,
                notes=entry.notes,
            )

        return TranslationResult()

    def _lookup_dict(
        self,
        session: Session,
        src_norm: str,
        kind: str,
        src_lang: str,
        tgt_lang: str,
        project_id: int | None,
    ) -> TranslationResult:
        """Lookup offline dictionary entries."""
        # Query dict entries with source info
        stmt = (
            select(DictEntry, DictSource.name)
            .join(DictSource, DictSource.dict_source_id == DictEntry.dict_source_id)
            .where(
                and_(
                    DictEntry.src_norm == src_norm,
                    DictEntry.kind == kind,
                    DictEntry.src_lang == src_lang,
                    DictEntry.tgt_lang == tgt_lang,
                    DictEntry.status == "approved",
                )
            )
        )

        # Prioritize project-scoped over global, then by priority
        if project_id is not None:
            stmt = stmt.order_by(
                DictSource.project_id.isnot(None).desc(),  # project-scoped first
                DictEntry.priority.desc(),
                DictEntry.dict_entry_id.desc(),
            )
        else:
            stmt = stmt.order_by(DictEntry.priority.desc(), DictEntry.dict_entry_id.desc())

        stmt = stmt.limit(1)

        result = session.execute(stmt).first()
        if result:
            entry, dict_name = result
            return TranslationResult(
                translation=entry.translation,
                source="dict",
                status=entry.status,
                matched_on="src_norm",
                match_key_used=src_norm,
                dict_source_name=dict_name,
                notes=entry.notes,
            )

        return TranslationResult()

    def _lookup_mt_cache(
        self,
        session: Session,
        src_norm: str,
        src_lang: str,
        tgt_lang: str,
        project_id: int | None,
    ) -> TranslationResult:
        """Lookup MT cache."""
        stmt = (
            select(MTCache)
            .where(
                and_(
                    MTCache.src_norm == src_norm,
                    MTCache.src_lang == src_lang,
                    MTCache.tgt_lang == tgt_lang,
                )
            )
            .order_by(MTCache.created_at.desc())
            .limit(1)
        )

        entry = session.execute(stmt).scalar()
        if entry:
            return TranslationResult(
                translation=entry.translation,
                source="mt_cache",
                confidence=entry.confidence,
                matched_on="src_norm",
                match_key_used=src_norm,
                provider=entry.provider,
            )

        return TranslationResult()

    def bulk_resolve(
        self,
        session: Session,
        items: list[tuple[str, str]],  # [(src_text, kind), ...]
        src_lang: str = "he",
        tgt_lang: str = "ru",
        project_id: int | None = None,
        allow_draft: bool = False,
    ) -> dict[tuple[str, str], TranslationResult]:
        """
        Bulk resolve translations for multiple items.

        This is optimized to avoid N+1 queries by batching lookups.

        Args:
            session: SQLAlchemy session
            items: List of (src_text, kind) tuples
            src_lang: Source language
            tgt_lang: Target language
            project_id: Project ID
            allow_draft: Include draft entries

        Returns:
            Dict mapping (src_text, kind) → TranslationResult
        """
        if not items:
            return {}

        # Normalize all items
        normalized_map = {}
        for src_text, kind in items:
            normalized = normalize_for_tm(src_lang, src_text, kind)
            if normalized.norm:
                normalized_map[(src_text, kind)] = normalized.norm

        if not normalized_map:
            return {item: TranslationResult() for item in items}

        # Batch lookup from TM
        norm_keys = list(set(normalized_map.values()))
        tm_results = self._batch_lookup_tm(
            session, norm_keys, src_lang, tgt_lang, project_id, allow_draft
        )

        # Batch lookup from dict
        dict_results = self._batch_lookup_dict(session, norm_keys, src_lang, tgt_lang, project_id)

        # Merge results with precedence
        results = {}
        for item in items:
            src_text, kind = item
            norm_key = normalized_map.get(item)

            if not norm_key:
                results[item] = TranslationResult()
                continue

            # Check TM first (higher precedence)
            tm_result = tm_results.get((norm_key, kind))
            if tm_result and tm_result.translation:
                results[item] = tm_result
                continue

            # Check dict
            dict_result = dict_results.get((norm_key, kind))
            if dict_result and dict_result.translation:
                results[item] = dict_result
                continue

            # No translation
            results[item] = TranslationResult()

        return results

    def _batch_lookup_tm(
        self,
        session: Session,
        norm_keys: list[str],
        src_lang: str,
        tgt_lang: str,
        project_id: int | None,
        allow_draft: bool,
    ) -> dict[tuple[str, str], TranslationResult]:
        """Batch lookup TM entries."""
        if not norm_keys:
            return {}

        status_filter = (
            TMEntry.status.in_(["approved", "draft"])
            if allow_draft
            else TMEntry.status == "approved"
        )

        stmt = select(TMEntry).where(
            and_(
                TMEntry.src_norm.in_(norm_keys),
                TMEntry.src_lang == src_lang,
                TMEntry.tgt_lang == tgt_lang,
                status_filter,
            )
        )

        if project_id is not None:
            stmt = stmt.where(or_(TMEntry.project_id == project_id, TMEntry.project_id.is_(None)))

        stmt = stmt.order_by(
            TMEntry.project_id.isnot(None).desc(),  # project-scoped first
            TMEntry.status.desc(),
            TMEntry.updated_at.desc(),
        )

        entries = session.execute(stmt).scalars().all()

        # Build result map: (norm_key, kind) → best entry
        results = {}
        for entry in entries:
            key = (entry.src_norm, entry.kind)
            if key not in results:  # First entry wins (already ordered by precedence)
                results[key] = TranslationResult(
                    translation=entry.translation,
                    source="tm",
                    status=entry.status,
                    confidence=entry.confidence,
                    origin=entry.origin,
                    matched_on="src_norm",
                    match_key_used=entry.src_norm,
                    tm_id=entry.tm_id,
                    notes=entry.notes,
                )

        # PATCH-19-03: Fallback to tm_global for keys not found in tm_entry
        missing_keys = [
            k
            for k in norm_keys
            if not any(
                (k, kind) in results for kind in ["lemma", "term_cluster", "ngram", "surface"]
            )
        ]
        if missing_keys:
            global_status_filter = (
                TMGlobal.status.in_(["approved", "draft"])
                if allow_draft
                else TMGlobal.status == "approved"
            )
            global_stmt = select(TMGlobal).where(
                and_(
                    TMGlobal.src_norm.in_(missing_keys),
                    TMGlobal.src_lang == src_lang,
                    TMGlobal.tgt_lang == tgt_lang,
                    global_status_filter,
                )
            )
            global_entries = session.execute(global_stmt).scalars().all()
            for g_entry in global_entries:
                key = (g_entry.src_norm, g_entry.kind)
                if key not in results and g_entry.translation:
                    results[key] = TranslationResult(
                        translation=g_entry.translation,
                        source="tm_global",
                        status=g_entry.status,
                        confidence=g_entry.confidence,
                        origin=g_entry.origin,
                        matched_on="src_norm",
                        match_key_used=g_entry.src_norm,
                        notes=g_entry.notes,
                    )

        return results

    def _batch_lookup_dict(
        self,
        session: Session,
        norm_keys: list[str],
        src_lang: str,
        tgt_lang: str,
        project_id: int | None,
    ) -> dict[tuple[str, str], TranslationResult]:
        """Batch lookup dict entries."""
        if not norm_keys:
            return {}

        stmt = (
            select(DictEntry, DictSource.name)
            .join(DictSource, DictSource.dict_source_id == DictEntry.dict_source_id)
            .where(
                and_(
                    DictEntry.src_norm.in_(norm_keys),
                    DictEntry.src_lang == src_lang,
                    DictEntry.tgt_lang == tgt_lang,
                    DictEntry.status == "approved",
                )
            )
        )

        if project_id is not None:
            stmt = stmt.where(
                or_(DictSource.project_id == project_id, DictSource.project_id.is_(None))
            )

        stmt = stmt.order_by(
            DictSource.project_id.isnot(None).desc(),  # project-scoped first
            DictEntry.priority.desc(),
        )

        results_list = session.execute(stmt).all()

        # Build result map
        results = {}
        for entry, dict_name in results_list:
            key = (entry.src_norm, entry.kind)
            if key not in results:  # First entry wins
                results[key] = TranslationResult(
                    translation=entry.translation,
                    source="dict",
                    status=entry.status,
                    matched_on="src_norm",
                    match_key_used=entry.src_norm,
                    dict_source_name=dict_name,
                    notes=entry.notes,
                )

        return results

    def revert_tm_entry(
        self,
        session: Session,
        tm_id: int,
        target_version: int,
        actor: str = "system",
    ) -> bool:
        """
        Revert TM entry to a previous version.

        Args:
            session: SQLAlchemy session
            tm_id: TM entry ID
            target_version: Version number to revert to
            actor: Actor performing revert

        Returns:
            True if revert successful, False otherwise
        """
        from sqlalchemy import func, select

        from app.infra.sa_models import TMEntry, TMEntryHistory

        # Get current entry
        entry = session.get(TMEntry, tm_id)
        if not entry:
            self.logger.error(f"TM entry {tm_id} not found")
            return False

        # Get target version from history
        stmt = select(TMEntryHistory).where(
            TMEntryHistory.tm_id == tm_id, TMEntryHistory.version == target_version
        )
        target_history = session.execute(stmt).scalar()

        if not target_history:
            self.logger.error(f"Version {target_version} not found for TM entry {tm_id}")
            return False

        # Get next version number
        max_version_stmt = select(func.max(TMEntryHistory.version)).where(
            TMEntryHistory.tm_id == tm_id
        )
        max_version = session.execute(max_version_stmt).scalar() or 0
        next_version = max_version + 1

        # Create history record for current state (before revert)
        current_history = TMEntryHistory(
            tm_id=entry.tm_id,
            version=next_version,
            translation=entry.translation,
            notes=entry.notes,
            status=entry.status,
            origin=entry.origin,
            change_kind="revert",
        )
        session.add(current_history)

        # Revert entry to target version
        entry.translation = target_history.translation
        entry.status = target_history.status
        entry.origin = (
            "user_edit"  # P2 FIX: Use allowed origin (history tracks revert via change_kind)
        )
        entry.notes = target_history.notes or f"Reverted to v{target_version}"
        entry.updated_at = utc_now()

        session.commit()

        self.logger.info(f"TM entry {tm_id} reverted to version {target_version}")
        return True

    # ========================================================================
    # PATCH-P1-T03: MT Provider Chain Integration
    # ========================================================================

    def _translate_via_provider_chain(
        self,
        session: Session,
        src_text: str,
        src_lang: str,
        tgt_lang: str,
        glossary: Any | None = None,
        allow_fallback: bool = True,
        trace_id: str = "",
    ) -> TranslationResult:
        """
        Translate via MT provider chain with fallback logic.

        Args:
            session: Database session (for future cache writes)
            src_text: Source text to translate
            src_lang: Source language (ISO 639-1)
            tgt_lang: Target language (ISO 639-1)
            glossary: Provider-specific glossary payload
            allow_fallback: Allow fallback to next provider on error
            trace_id: Trace ID for logging (generated if empty)

        Returns:
            TranslationResult (service class)
        """
        # Get settings
        settings = SettingsService.get_instance()
        enabled = settings.get_bool("mt/providers/enabled", default=False)
        chain = settings.get_json("mt/providers/chain", default=[])

        # Feature-safe default: MT disabled or no providers configured
        if not enabled:
            return TranslationResult(
                source="none", notes="MT providers disabled (mt/providers/enabled=False)"
            )

        if not chain or not isinstance(chain, list):
            return TranslationResult(
                source="none", notes="No MT providers configured (mt/providers/chain is empty)"
            )

        # Generate trace_id if missing
        if not trace_id:
            trace_id = str(uuid.uuid4())

        # PATCH-P1-T05: Build canonical glossary from approved terms
        from app.services.glossary_builder_service import GlossaryBuilderService

        glossary_service = GlossaryBuilderService(session)
        canonical_glossary = glossary_service.build_canonical_glossary(
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            project_id=None,  # TODO: Get from context/args if needed
        )
        glossary_hash = canonical_glossary.glossary_hash

        logger.info(
            f"Built canonical glossary: {canonical_glossary.total_entries} entries, "
            f"hash={glossary_hash[:8]}..., truncated={canonical_glossary.truncated}"
        )

        # PATCH-09b/10: inject PPS options when local HY-MT is in chain.
        # load_pps_request_options() respects Advanced Mode override (PATCH-10).
        _pps_opts: dict = {}
        if any(pid.startswith("local_hymt") for pid in chain):
            try:
                from app.ui.provider_settings_dialog import load_pps_request_options

                _pps_opts = load_pps_request_options()
            except Exception:
                pass  # QSettings not available in headless / test environments

        # Build TranslationRequest (provider format)
        request = TranslationRequest(
            source_text=src_text,
            source_lang=src_lang,
            target_lang=tgt_lang,
            glossary=glossary,  # Will be replaced per-provider below
            glossary_hash=glossary_hash,
            trace_id=trace_id,
            allow_fallback=allow_fallback,
            options=_pps_opts,
        )

        # Get registry
        registry = ProvidersRegistry()
        total_latency_ms = 0
        last_result: ProviderTranslationResult | None = None

        # Iterate provider chain
        for index, provider_id in enumerate(chain, start=1):
            # Get provider
            provider = registry.get(provider_id)

            # Lazy initialization for local providers
            if not provider and provider_id.startswith("local_"):
                from app.infra.translators.local_providers_setup import initialize_provider_lazy

                logger.info(f"Attempting lazy initialization of {provider_id}")
                if initialize_provider_lazy(provider_id, session, project_id=None):
                    provider = registry.get(provider_id)
                    logger.info(f"Successfully initialized {provider_id} on-demand")
                else:
                    logger.warning(f"Lazy initialization failed for {provider_id}")

            if not provider:
                self._log_provider_attempt(
                    {
                        "trace_id": trace_id,
                        "provider_id": provider_id,
                        "attempt_index": index,
                        "chain_total": len(chain),
                        "src_lang": src_lang,
                        "tgt_lang": tgt_lang,
                        "decision": "SKIP_MISSING",
                        "fallback_reason": "PROVIDER_NOT_REGISTERED",
                    }
                )
                continue

            # PATCH-P1-T04: Configure rate limiter for provider (if not already configured)
            requests_per_min = settings.get_int(
                f"mt/provider/{provider_id}/requests_per_min", default=60
            )
            max_wait_seconds = settings.get_int(
                f"mt/provider/{provider_id}/max_wait_seconds", default=5
            )
            if self._rate_limiter.get_status(provider_id)["capacity"] == 0.0:
                self._rate_limiter.configure_provider(provider_id, requests_per_min)

            # PATCH-P1-T04: Check circuit breaker
            if self._circuit_breaker and not self._circuit_breaker.is_request_allowed(provider_id):
                # Circuit breaker OPEN → skip provider
                breaker_state = self._circuit_breaker.get_state(provider_id)
                self._log_provider_attempt(
                    {
                        "trace_id": trace_id,
                        "provider_id": provider_id,
                        "display_name": provider.display_name,
                        "attempt_index": index,
                        "chain_total": len(chain),
                        "src_lang": src_lang,
                        "tgt_lang": tgt_lang,
                        "decision": "SKIP_CIRCUIT_BREAKER_OPEN",
                        "fallback_reason": f"CIRCUIT_BREAKER_{breaker_state.value.upper()}",
                        "circuit_breaker_state": breaker_state.value,
                    }
                )
                continue

            # PATCH-P1-T04: Check rate limiter
            if not self._rate_limiter.acquire(provider_id, max_wait_seconds=max_wait_seconds):
                # Rate limit exceeded → skip provider
                self._log_provider_attempt(
                    {
                        "trace_id": trace_id,
                        "provider_id": provider_id,
                        "display_name": provider.display_name,
                        "attempt_index": index,
                        "chain_total": len(chain),
                        "src_lang": src_lang,
                        "tgt_lang": tgt_lang,
                        "decision": "SKIP_RATE_LIMIT",
                        "fallback_reason": "RATE_LIMIT_EXCEEDED",
                    }
                )
                continue

            # PATCH-P1-T04: Check cache first (if enabled)
            cache_enabled = settings.get_bool("mt/cache_enabled", default=True)

            # PATCH-09: Get model version for cache keying
            model_version = (
                provider.get_model_version() if hasattr(provider, "get_model_version") else ""
            )

            if cache_enabled:
                cached_result = self._lookup_provider_cache(
                    session, request, provider_id, model_version
                )
                if cached_result:
                    # Cache hit!
                    self._log_provider_attempt(
                        {
                            "trace_id": trace_id,
                            "provider_id": provider_id,
                            "display_name": provider.display_name,
                            "attempt_index": index,
                            "chain_total": len(chain),
                            "src_lang": src_lang,
                            "tgt_lang": tgt_lang,
                            "latency_ms": 0,
                            "used_glossary": bool(request.glossary),
                            "glossary_hash_present": bool(request.glossary_hash),
                            "cache_hit": True,
                            "error_kind": None,
                            "error_message": None,
                            "decision": "STOP_SUCCESS",
                            "fallback_reason": None,
                        }
                    )
                    self._log_translation_completed(trace_id, index, 0, provider_id)
                    return self._map_provider_result_to_service(cached_result)

            # PATCH-P1-T05: Convert canonical glossary to provider-specific format
            if canonical_glossary.total_entries > 0:
                provider_glossary = glossary_service.to_provider_format(
                    canonical_glossary, provider_id=provider_id
                )
                if provider_glossary:
                    request.glossary = provider_glossary
                    logger.debug(
                        f"Provider {provider_id}: Using glossary with "
                        f"{canonical_glossary.total_entries} entries"
                    )
                else:
                    request.glossary = None
                    logger.debug(f"Provider {provider_id}: Glossary not supported")
            else:
                request.glossary = None
                logger.debug("No approved terms for glossary")

            # Measure latency
            start = time.perf_counter()
            result = provider.translate(request)
            latency_ms = int((time.perf_counter() - start) * 1000)
            total_latency_ms += latency_ms

            # PATCH-P1-T04: Store successful result in cache
            # PATCH-09: Include model_version for cache isolation
            if cache_enabled and result.is_success:
                self._store_in_cache(
                    session, request, result, project_id=None, model_version=model_version
                )

            # PATCH-P1-T04: Record result in circuit breaker
            if self._circuit_breaker:
                if result.is_success:
                    self._circuit_breaker.record_success(provider_id)
                else:
                    self._circuit_breaker.record_failure(provider_id)

            # Determine decision
            if result.is_success:
                decision = "STOP_SUCCESS"
                fallback_reason = None
            elif not allow_fallback:
                decision = "STOP_FAIL"
                fallback_reason = "ALLOW_FALLBACK_FALSE"
            else:
                decision = "CONTINUE_FALLBACK"
                fallback_reason = result.error_kind.value if result.error_kind else "UNKNOWN"

            # Log attempt
            self._log_provider_attempt(
                {
                    "trace_id": trace_id,
                    "provider_id": provider_id,
                    "display_name": provider.display_name,
                    "attempt_index": index,
                    "chain_total": len(chain),
                    "src_lang": src_lang,
                    "tgt_lang": tgt_lang,
                    "latency_ms": latency_ms,
                    "used_glossary": result.used_glossary,
                    "glossary_hash_present": bool(request.glossary_hash),
                    "cache_hit": result.cache_hit,
                    "error_kind": result.error_kind.value if result.error_kind else None,
                    "error_message": result.error_message,
                    "decision": decision,
                    "fallback_reason": fallback_reason,
                }
            )

            # Success → return immediately
            if result.is_success:
                self._log_translation_completed(trace_id, index, total_latency_ms, provider_id)
                return self._map_provider_result_to_service(result)

            # Store last result for error reporting
            last_result = result

            # Failure → apply fallback policy
            if not allow_fallback:
                self._log_translation_failed(trace_id, index, "ALLOW_FALLBACK_FALSE")
                return self._map_provider_result_to_service(result)

            # Continue to next provider

        # All providers failed
        self._log_translation_failed(trace_id, len(chain), "NO_MORE_PROVIDERS")

        # Return last error or generic failure
        if last_result:
            return self._map_provider_result_to_service(last_result)
        else:
            return TranslationResult(source="none", notes="All MT providers failed or unavailable")

    def _map_provider_result_to_service(
        self, provider_result: ProviderTranslationResult
    ) -> TranslationResult:
        """
        Map provider TranslationResult to service TranslationResult.

        Args:
            provider_result: Result from MT provider

        Returns:
            TranslationResult (service class)
        """
        return TranslationResult(
            translation=provider_result.translated_text or None,
            source="mt" if provider_result.is_success else "none",
            confidence=0.8 if provider_result.is_success else None,
            provider=provider_result.provider_id,
            matched_on="mt_chain",
            notes=provider_result.error_message if provider_result.is_error else None,
        )

    def _log_provider_attempt(self, event: dict[str, Any]) -> None:
        """
        Log provider attempt event (structured logging).

        Args:
            event: Event dictionary with fields (trace_id, provider_id, etc.)
        """
        # PATCH-P1-T03: Basic logging (structured format in P1-T04)
        trace_id = event.get("trace_id", "")
        provider_id = event.get("provider_id", "")
        attempt_index = event.get("attempt_index", 0)
        decision = event.get("decision", "")
        fallback_reason = event.get("fallback_reason", "")
        error_kind = event.get("error_kind")
        latency_ms = event.get("latency_ms", 0)

        # Log at appropriate level
        if error_kind in ("auth", "invalid_request", "AUTH", "INVALID_REQUEST"):
            log_level = logging.ERROR
            msg = f"MT provider_attempt trace_id={trace_id} provider={provider_id} attempt={attempt_index} decision={decision} error={error_kind} reason={fallback_reason} latency_ms={latency_ms} [CONFIG_ISSUE]"
        elif error_kind in ("rate_limit", "quota", "unknown", "RATE_LIMIT", "QUOTA", "UNKNOWN"):
            log_level = logging.WARNING
            msg = f"MT provider_attempt trace_id={trace_id} provider={provider_id} attempt={attempt_index} decision={decision} error={error_kind} reason={fallback_reason} latency_ms={latency_ms}"
        else:
            log_level = logging.INFO
            msg = f"MT provider_attempt trace_id={trace_id} provider={provider_id} attempt={attempt_index} decision={decision} error={error_kind} reason={fallback_reason} latency_ms={latency_ms}"

        self.logger.log(log_level, msg)

    def _log_translation_completed(
        self, trace_id: str, total_attempts: int, total_latency_ms: int, final_provider: str
    ) -> None:
        """
        Log translation completed event.

        Args:
            trace_id: Trace ID
            total_attempts: Number of attempts made
            total_latency_ms: Total latency (sum of all attempts)
            final_provider: Provider that succeeded
        """
        self.logger.info(
            f"MT translation_completed trace_id={trace_id} attempts={total_attempts} "
            f"provider={final_provider} total_latency_ms={total_latency_ms}"
        )

    def _log_translation_failed(
        self, trace_id: str, total_attempts: int, failure_reason: str
    ) -> None:
        """
        Log translation failed event.

        Args:
            trace_id: Trace ID
            total_attempts: Number of attempts made
            failure_reason: Why translation failed
        """
        self.logger.warning(
            f"MT translation_failed trace_id={trace_id} attempts={total_attempts} "
            f"reason={failure_reason}"
        )

    # ========================================================================
    # PATCH-P1-T04: MT Cache Integration
    # ========================================================================

    def _lookup_provider_cache(
        self,
        session: Session,
        request: TranslationRequest,
        provider_id: str,
        model_version: str = "",
    ) -> ProviderTranslationResult | None:
        """
        Lookup MT cache for given request.

        Args:
            session: Database session
            request: Translation request
            provider_id: Provider ID
            model_version: Model version from provider (PATCH-09)

        Returns:
            Cached TranslationResult or None if cache miss/expired
        """
        # PATCH-09: Feature-safe - catch cache errors, don't break translation
        try:
            # Build cache key (PATCH-09: include model_version)
            cache_key = self._build_cache_key(request, provider_id, model_version)

            # Query mt_cache table
            stmt = select(MTCache).where(
                MTCache.provider == provider_id,
                MTCache.src_lang == request.source_lang,
                MTCache.tgt_lang == request.target_lang,
                MTCache.request_key == cache_key,
            )

            entry = session.execute(stmt).scalar_one_or_none()

            if not entry:
                return None  # Cache miss

            # Check expiration
            if entry.expires_at:
                try:
                    expires_at = datetime.fromisoformat(entry.expires_at.replace("Z", "+00:00"))
                    if datetime.now(UTC) > expires_at:
                        return None  # Expired
                except (ValueError, AttributeError):
                    # Invalid expires_at format → treat as expired
                    return None

            # Cache hit!
            return ProviderTranslationResult(
                translated_text=entry.translation,
                provider_id=provider_id,
                cache_hit=True,
                latency_ms=0,  # Cache = instant
            )

        except Exception as e:
            # PATCH-09: Cache error → log and continue (feature-safe)
            logger.warning(f"Cache lookup error (continuing with provider): {e}")
            return None  # Treat as cache miss

    def _store_in_cache(
        self,
        session: Session,
        request: TranslationRequest,
        result: ProviderTranslationResult,
        project_id: int | None = None,
        model_version: str = "",
    ) -> None:
        """
        Store successful translation in cache.

        Args:
            session: Database session
            request: Translation request
            result: Translation result from provider
            project_id: Project ID (for project-scoped cache)
            model_version: Model version from provider (PATCH-09)
        """
        if not result.is_success:
            return  # Don't cache errors

        # PATCH-09: Feature-safe - catch cache store errors, don't break translation
        try:
            # Get settings
            settings = SettingsService.get_instance()
            ttl_days = settings.get_int("mt/cache_ttl_days", default=7)

            # Calculate expiration
            expires_at = (datetime.now(UTC) + timedelta(days=ttl_days)).isoformat()

            # Build cache key (PATCH-09: include model_version)
            cache_key = self._build_cache_key(request, result.provider_id, model_version)

            # Check if entry already exists (upsert logic)
            stmt = select(MTCache).where(
                MTCache.provider == result.provider_id,
                MTCache.src_lang == request.source_lang,
                MTCache.tgt_lang == request.target_lang,
                MTCache.request_key == cache_key,
            )
            existing = session.execute(stmt).scalar_one_or_none()

            if existing:
                # Update existing entry
                existing.translation = result.translated_text
                existing.confidence = result.meta.get("confidence", 0.8)
                existing.expires_at = expires_at
                existing.created_at = utc_now()
            else:
                # Create new entry
                cache_entry = MTCache(
                    project_id=project_id,
                    provider=result.provider_id,
                    src_lang=request.source_lang,
                    tgt_lang=request.target_lang,
                    request_key=cache_key,
                    src_text=request.source_text,
                    src_norm=self._normalize_for_cache(request.source_text),
                    glossary_hash=request.glossary_hash or "",
                    translation=result.translated_text,
                    confidence=result.meta.get("confidence", 0.8),
                    created_at=utc_now(),
                    expires_at=expires_at,
                )
                session.add(cache_entry)

            session.flush()

        except Exception as e:
            # PATCH-09: Cache store error → log and continue (feature-safe)
            logger.warning(f"Cache store error (translation still succeeded): {e}")

    def _build_cache_key(
        self,
        request: TranslationRequest,
        provider_id: str,
        model_version: str = "",
    ) -> str:
        """
        Build cache key from request parameters.

        Formula:
            sha256(src_text + "|" + src_lang + "|" + tgt_lang + "|" + provider_id + "|" + glossary_hash + "|" + model_version)

        Args:
            request: Translation request
            provider_id: Provider ID
            model_version: Model version from provider.get_model_version() (PATCH-09)

        Returns:
            SHA256 hex digest (cache key)
        """
        # Normalize source text for consistent caching
        normalized_text = self._normalize_for_cache(request.source_text)

        # Build key components (PATCH-09: added model_version)
        components = [
            normalized_text,
            request.source_lang,
            request.target_lang,
            provider_id,
            request.glossary_hash or "",
            model_version,  # PATCH-09: Include model version for cache isolation
        ]

        # Join and hash
        key_string = "|".join(components)
        return hashlib.sha256(key_string.encode("utf-8")).hexdigest()

    def _normalize_for_cache(self, text: str) -> str:
        """
        Normalize text for cache key (consistent formatting).

        Args:
            text: Source text

        Returns:
            Normalized text (strip whitespace, lowercase)
        """
        # Simple normalization: strip and collapse whitespace
        return " ".join(text.strip().split())
