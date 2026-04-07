"""Local HY-MT provider (Tencent Hunyuan) using transformers_causal worker.

Architecture:
- Decoder-only causal LM: AutoModelForCausalLM via transformers_causal backend
- Provider builds full prompt; worker does tokenize/generate/decode only
- Placeholder protection: MANDATORY on every translate() call
- Terminology mode: "both" (prompt injection + apply_glossary postprocess), hardcoded
- Language pairs: primarily he→ru, he→en; any pair in SUPPORTED_LANGS

Prompt pipeline:
1. protect_placeholders(source_text) → protected text + token mapping
2. Fetch approved glossary terms from TM (if db_session available)
3. Build full prompt (with terminology hints and placeholder instruction)
4. Worker inference → raw translation
5. restore_placeholders(translation, mapping) + validate no loss
6. apply_glossary() postprocess (replace MT with approved TM terms)
7. Return TranslationResult with full meta
"""

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.infra.local_mt import (
    _HYMT_SYSTEM_PROMPT_HASH,
    LocalMTWorker,
    WorkerError,
    WorkerRequest,
    start_worker,
)
from app.infra.translators.base_provider import (
    BaseProvider,
    TranslationErrorKind,
    TranslationRequest,
    TranslationResult,
)
from app.infra.translators.prompt_policy import (
    EffectivePromptTrace,
    PolicyRenderer,
    PromptPolicy,
    RouterResult,
    TerminologyMode,
    TranslationRouter,
    build_applied_sampling,
    compute_glossary_hash,
    compute_source_text_hash,
)
from app.services.local_models import ModelResourceManager
from app.services.local_mt import apply_glossary

logger = logging.getLogger(__name__)

# Module-level singletons — both classes are stateless; one instance is enough.
_ROUTER = TranslationRouter()
_RENDERER = PolicyRenderer()


# ============================================================================
# Constants
# ============================================================================

MODEL_ID = "tencent/HY-MT1.5-1.8B"
BACKEND = "transformers_causal"

# ISO → human-readable language names for prompt construction
_ISO_TO_LANG_NAME: dict[str, str] = {
    "he": "Hebrew",
    "iw": "Hebrew",
    "ru": "Russian",
    "en": "English",
    "ar": "Arabic",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "tr": "Turkish",
    "pl": "Polish",
    "uk": "Ukrainian",
}

# ISO → NLLB codes (for TM glossary queries which use NLLB format)
_ISO_TO_NLLB: dict[str, str] = {
    "he": "heb_Hebr",
    "iw": "heb_Hebr",
    "ru": "rus_Cyrl",
    "en": "eng_Latn",
    "ar": "arb_Arab",
    "es": "spa_Latn",
    "fr": "fra_Latn",
    "de": "deu_Latn",
    "it": "ita_Latn",
    "pt": "por_Latn",
    "zh": "zho_Hans",
    "ja": "jpn_Jpan",
    "ko": "kor_Hang",
    "tr": "tur_Latn",
    "pl": "pol_Latn",
    "uk": "ukr_Cyrl",
}

# Supported source/target ISO codes
SUPPORTED_LANGS: frozenset[str] = frozenset(_ISO_TO_LANG_NAME.keys())

# Unicode directional marks inserted by RTL/LTR mixing — strip before restore
_DIRECTIONAL_MARKS = re.compile(
    "[\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069]"
)

# Placeholder token pattern: HDLE_PH_N (ASCII-safe, immune to RTL marks)
_PH_PATTERN = re.compile(
    r"(?:"
    r"\{[^}]+\}"  # {name}, {filename}, {path}
    r"|%[sd%]"  # %s, %d, %%
    r"|<[^>]+>"  # <tag>, <tag attr="val"/>, </tag>
    r")"
)


# ============================================================================
# Placeholder protection
# ============================================================================


@dataclass
class _ProtectedText:
    """Result of placeholder protection."""

    text: str
    mapping: dict[str, str] = field(default_factory=dict)


def _protect_placeholders(text: str) -> _ProtectedText:
    """Replace format/markup tokens with ASCII-safe HDLE_PH_N placeholders.

    Args:
        text: Source text possibly containing {fmt}, %s/%d, or <tags>.

    Returns:
        _ProtectedText with substituted text and token→original mapping.
    """
    mapping: dict[str, str] = {}
    counter = [0]

    def replace(m: re.Match) -> str:
        counter[0] += 1
        token = f"HDLE_PH_{counter[0]}"
        mapping[token] = m.group(0)
        return token

    protected = _PH_PATTERN.sub(replace, text)
    return _ProtectedText(text=protected, mapping=mapping)


def _restore_placeholders(translated: str, mapping: dict[str, str]) -> tuple[str, list[str]]:
    """Restore original placeholder tokens in translated text.

    Strips Unicode directional marks before searching to handle RTL/LTR mixing
    artifacts that the model may insert around tokens.

    Args:
        translated: Model output text.
        mapping: Token → original string mapping from _protect_placeholders.

    Returns:
        (restored_text, missing_tokens) — missing_tokens is empty on full success.
    """
    if not mapping:
        return translated, []

    # Strip directional marks before processing
    normalized = _DIRECTIONAL_MARKS.sub("", translated)

    missing: list[str] = []
    result = normalized
    for token, original in mapping.items():
        if token in result:
            result = result.replace(token, original)
        else:
            missing.append(token)
            logger.warning(
                f"Placeholder not found in translation: {token} (original: {original!r})"
            )

    return result, missing


# ============================================================================
# Prompt builder
# ============================================================================


def _build_user_content(
    source_text: str,
    glossary_terms: list[tuple[str, str]] | None = None,
) -> str:
    """Build user-turn content for the HY-MT worker.

    The worker owns the full template (system prompt, role tokens, "Translate…"
    instruction).  This function produces only the *payload* that goes into the
    user turn: an optional terminology line followed by the source text.

    Args:
        source_text: Placeholder-protected source text.
        glossary_terms: Optional list of (source_term, target_term) pairs
            for terminology injection.

    Returns:
        User content string to pass as ``WorkerRequest.text``.
    """
    if glossary_terms:
        term_hints = ", ".join(f"{src} → {tgt}" for src, tgt in glossary_terms[:20])
        return f"Terminology: {term_hints}.\n\n{source_text}"

    return source_text


# ============================================================================
# Glossary term fetching for prompt injection
# ============================================================================


def _fetch_glossary_terms_for_prompt(
    db_session: Session,
    source_lang: str,
    target_lang: str,
    project_id: int | None,
    max_terms: int = 20,
) -> list[tuple[str, str]]:
    """Fetch approved TM terms for prompt-level terminology injection.

    Args:
        db_session: SQLAlchemy session.
        source_lang: ISO source code.
        target_lang: ISO target code.
        project_id: Optional project scope.
        max_terms: Maximum terms to inject (avoids prompt bloat).

    Returns:
        List of (src_text, translation) pairs, up to max_terms.
    """
    src_nllb = _ISO_TO_NLLB.get(source_lang.lower())
    tgt_nllb = _ISO_TO_NLLB.get(target_lang.lower())
    if not src_nllb or not tgt_nllb:
        return []

    try:
        from app.services.local_mt.glossary_postprocess import query_approved_terms

        term_dict = query_approved_terms(db_session, src_nllb, tgt_nllb, project_id)
        terms = [(norm, entry.translation) for norm, entry in term_dict.items()]
        return terms[:max_terms]
    except Exception as e:
        logger.warning(f"Failed to fetch glossary terms for prompt: {e}")
        return []


# ============================================================================
# LocalHYMTProvider
# ============================================================================


class LocalHYMTProvider(BaseProvider):
    """Local HY-MT 1.5 (1.8B) translation provider.

    Uses Tencent Hunyuan decoder-only causal LM via transformers_causal worker.
    Supports Hebrew→Russian and other language pairs with:
    - Mandatory placeholder protection (HDLE_PH_N tokens)
    - Terminology injection in prompt + apply_glossary postprocess (mode="both")
    - Mixed-language text handling (built-in model capability)
    - Contextual translation via full prompt construction

    PPS PATCH-05 hardware constraint attributes (override in subclasses):
        _FORCE_GREEDY: True when the model family forces greedy decoding (7B-GPTQ).
        _MAX_N_PREDICT_CAP: Hard token budget cap used by worker _resolve_gen_kwargs.
        _MODEL_QUANT_ID: Quantisation descriptor for EffectivePromptTrace metadata.
    """

    # PPS PATCH-05: hardware constraint class attributes
    # Overridden in LocalHYMT7BGPTQProvider for GPTQ-specific constraints.
    _FORCE_GREEDY: bool = False
    _MAX_N_PREDICT_CAP: int = 512
    _MODEL_QUANT_ID: str | None = None  # "gptq-int4" for 7B subclass

    def __init__(
        self,
        model_id: str = MODEL_ID,
        backend: str = BACKEND,
        db_session: Session | None = None,
        project_id: int | None = None,
        timeout: float = 60.0,
    ):
        """Initialize LocalHYMTProvider.

        Args:
            model_id: HuggingFace model ID (default: tencent/HY-MT1.5-1.8B).
            backend: Must be "transformers_causal".
            db_session: Optional DB session for glossary postprocessing.
            project_id: Optional project ID for TM scope.
            timeout: Worker request timeout in seconds (HY-MT is slower than NLLB).
        """
        self.model_id = model_id
        self.backend = backend
        self.db_session = db_session
        self.project_id = project_id
        self.timeout = timeout

        self.worker: LocalMTWorker | None = None
        self._model_manager = ModelResourceManager()

        self._init_worker()

    def _init_worker(self) -> None:
        """Start worker subprocess for HY-MT inference."""
        is_installed, reason = self._model_manager.is_installed(self.model_id, self.backend)
        if not is_installed:
            logger.error(f"HY-MT model not installed: {reason}")
            raise RuntimeError(
                f"HY-MT model not installed: {self.model_id}. "
                f"Install with: python scripts/install_local_mt_model.py "
                f"--model HY-MT1.5-1.8B --backend transformers_causal"
            )

        model_path = self._model_manager.model_dir(self.model_id, self.backend)
        try:
            self.worker = start_worker(
                model_path=model_path,
                backend=self.backend,
                model_id=self.model_id,
                timeout=self.timeout,
            )
            logger.info(f"LocalHYMTProvider initialized: {self.model_id}")
        except WorkerError as e:
            raise RuntimeError(f"Failed to start HY-MT worker: {e}") from e

    # ------------------------------------------------------------------
    # BaseProvider interface
    # ------------------------------------------------------------------

    @property
    def provider_id(self) -> str:
        return "local_hymt"

    @property
    def display_name(self) -> str:
        return "Local HY-MT 1.5 (Offline)"

    @property
    def supports_glossary(self) -> bool:
        return True

    @property
    def supports_batch(self) -> bool:
        return False

    def get_model_version(self) -> str:
        """Return version string for MT cache key isolation.

        Includes a 12-char SHA-256 prefix of the system prompt so that any
        change to the prompt automatically invalidates cached translations.
        """
        safe_id = self.model_id.replace("/", "_")
        return f"{safe_id}_{self.backend}_{_HYMT_SYSTEM_PROMPT_HASH}"

    def healthcheck(self) -> bool:
        """Ping worker subprocess."""
        if not self.worker:
            return False
        try:
            return self.worker.ping(timeout=5.0)
        except Exception as e:
            logger.warning(f"HY-MT healthcheck failed: {e}")
            return False

    def translate(self, request: TranslationRequest) -> TranslationResult:
        """Translate text using local HY-MT model.

        Pipeline:
        1. Validate worker + language pair
        2. protect_placeholders → HDLE_PH_N tokens
        3. Fetch glossary terms for prompt injection (if db_session)
        4. build_user_content → source text (+ optional terminology line)
           Worker owns the full template + system prompt
        5. Worker inference (WorkerRequest.text = user content)
        6. restore_placeholders + validate
        7. apply_glossary postprocess (terminology_mode="both")
        8. Return TranslationResult (never raises)

        Args:
            request: TranslationRequest with source text and language codes.

        Returns:
            TranslationResult — success or error, never raises.
        """
        start_time = time.time()

        if not self.worker:
            return TranslationResult(
                provider_id=self.provider_id,
                error_kind=TranslationErrorKind.SERVER,
                error_message="Worker not initialized",
                latency_ms=0,
            )

        # Validate language pair
        src = request.source_lang.lower()
        tgt = request.target_lang.lower()
        if src not in SUPPORTED_LANGS or tgt not in SUPPORTED_LANGS:
            unsupported = src if src not in SUPPORTED_LANGS else tgt
            return TranslationResult(
                provider_id=self.provider_id,
                error_kind=TranslationErrorKind.UNSUPPORTED,
                error_message=f"Unsupported language: {unsupported}",
                latency_ms=int((time.time() - start_time) * 1000),
            )

        if not request.source_text or not request.source_text.strip():
            return TranslationResult(
                translated_text="",
                provider_id=self.provider_id,
                latency_ms=int((time.time() - start_time) * 1000),
                meta={"segment_count": 0},
            )

        # Step 0: Resolve prompt policy via TranslationRouter
        # allow_experimental: trace_id present → debug/advanced mode → experimental allowed
        allow_experimental = bool(request.trace_id)
        router_result = _ROUTER.route(request.options, allow_experimental=allow_experimental)
        policy = router_result.policy
        logger.debug(
            f"HY-MT policy resolved: {policy.policy_id!r} "
            f"(source={router_result.source}, provider={self.provider_id})"
        )

        # Step 1: Placeholder protection (MANDATORY)
        protected = _protect_placeholders(request.source_text)

        # Step 2: Fetch glossary terms — only when policy allows glossary
        glossary_terms: list[tuple[str, str]] = []
        if self.db_session and policy.terminology_mode != TerminologyMode.OFF:
            glossary_terms = _fetch_glossary_terms_for_prompt(
                self.db_session, src, tgt, self.project_id
            )

        injected_term_count = len(glossary_terms)

        # Step 3: Build PPS sentinel payload (worker parses role + user_content)
        user_content = _RENDERER.render_sentinel_payload(
            policy=policy,
            source_text=protected.text,
            glossary_terms=glossary_terms if glossary_terms else None,
            context_items=None,  # PATCH-03: context not yet wired; PATCH-05 scope
        )

        # Step 4: Worker inference
        try:
            worker_request = WorkerRequest(
                text=user_content,
                source_lang=src,
                target_lang=tgt,
                request_id=request.trace_id,
                sampling_profile_id=policy.sampling_profile_id,
            )
            worker_result = self.worker.translate(worker_request)
        except WorkerError as e:
            logger.error(f"HY-MT worker error: {e}")
            return TranslationResult(
                provider_id=self.provider_id,
                error_kind=TranslationErrorKind.SERVER,
                error_message=f"Worker error: {e}",
                latency_ms=int((time.time() - start_time) * 1000),
            )
        except Exception as e:
            logger.error(f"HY-MT unexpected error: {e}")
            return TranslationResult(
                provider_id=self.provider_id,
                error_kind=TranslationErrorKind.UNKNOWN,
                error_message=f"Unexpected error: {e}",
                latency_ms=int((time.time() - start_time) * 1000),
            )

        if worker_result.error:
            return TranslationResult(
                provider_id=self.provider_id,
                error_kind=TranslationErrorKind.SERVER,
                error_message=f"Inference failed: {worker_result.error}",
                latency_ms=int((time.time() - start_time) * 1000),
            )

        raw_translation = worker_result.text

        # Step 5: Restore placeholders
        restored, missing = _restore_placeholders(raw_translation, protected.mapping)
        if missing:
            logger.warning(f"HY-MT: {len(missing)} placeholder(s) lost in translation: {missing}")

        # Step 6: apply_glossary postprocess — only when policy allows glossary
        applied_terms_count = 0
        used_glossary = False
        final_translation = restored

        if self.db_session and policy.terminology_mode != TerminologyMode.OFF:
            src_nllb = _ISO_TO_NLLB.get(src)
            tgt_nllb = _ISO_TO_NLLB.get(tgt)
            if src_nllb and tgt_nllb:
                try:
                    postprocess_result = apply_glossary(
                        self.db_session,
                        source_segments=[request.source_text],
                        target_segments=[restored],
                        src_lang=src_nllb,
                        tgt_lang=tgt_nllb,
                        project_id=self.project_id,
                    )
                    final_translation = postprocess_result.translations[0]
                    applied_terms_count = postprocess_result.match_count
                    used_glossary = applied_terms_count > 0
                    if used_glossary:
                        logger.debug(f"HY-MT: applied {applied_terms_count} glossary term(s)")
                except Exception as e:
                    logger.warning(f"HY-MT glossary postprocess failed: {e} (using MT output)")

        latency_ms = int((time.time() - start_time) * 1000)

        # Step 7: Build EffectivePromptTrace — only when trace is active (PATCH-05)
        trace: EffectivePromptTrace | None = None
        if request.trace_id:
            trace = self._build_trace(
                request=request,
                policy=policy,
                router_result=router_result,
                protected=protected,
                glossary_terms=glossary_terms,
                raw_model_output=raw_translation,
                final_translation=final_translation,
                missing=missing,
                used_glossary=used_glossary,
                applied_terms_count=applied_terms_count,
                latency_ms=latency_ms,
                worker_latency_ms=int(worker_result.inference_time_ms),
            )

        return TranslationResult(
            translated_text=final_translation,
            provider_id=self.provider_id,
            used_glossary=used_glossary,
            cache_hit=False,
            latency_ms=latency_ms,
            meta={
                # Existing top-level fields preserved for backwards compatibility
                "inference_time_ms": worker_result.inference_time_ms,
                "applied_terms_count": applied_terms_count,
                "placeholder_count": len(protected.mapping),
                "missing_placeholders": missing,
                "model_id": self.model_id,
                "backend": self.backend,
                # PPS structured meta (spec §11.1)
                "prompt_policy": {
                    "policy_id": policy.policy_id,
                    "policy_hash": policy.policy_hash,
                    "sampling_profile_id": policy.sampling_profile_id,
                    "template_profile_id": policy.template_profile_id,
                    "content_kind": str(policy.content_kind),
                    "terminology_mode": str(policy.terminology_mode),
                    "injected_term_count": injected_term_count,
                    "applied_term_count": applied_terms_count,
                    "placeholder_count": len(protected.mapping),
                    "missing_placeholders": missing,
                    "fallback_triggered": router_result.fallback_triggered,
                    "fallback_reason": router_result.fallback_reason,
                    "warnings": router_result.warnings,
                    "trace": trace,  # EffectivePromptTrace | None (PATCH-05)
                },
            },
        )

    def _build_trace(
        self,
        request: TranslationRequest,
        policy: PromptPolicy,
        router_result: RouterResult,
        protected: _ProtectedText,
        glossary_terms: list[tuple[str, str]],
        raw_model_output: str,
        final_translation: str,
        missing: list[str],
        used_glossary: bool,
        applied_terms_count: int,
        latency_ms: int,
        worker_latency_ms: int,
    ) -> EffectivePromptTrace:
        """Build EffectivePromptTrace for the current translation request.

        Called only when ``request.trace_id != ""``.  All inputs are already
        computed — no extra I/O or worker round-trip is performed.

        Args:
            request: Original translation request (source_text, trace_id, etc.).
            policy: Resolved PromptPolicy from TranslationRouter.
            router_result: RouterResult with fallback flags.
            protected: Placeholder-protected source (_ProtectedText).
            glossary_terms: Injected glossary (src, tgt) pairs.
            raw_model_output: Worker output before postprocessing.
            final_translation: Final output after restore + glossary.
            missing: Placeholder tokens not found in model output.
            used_glossary: Whether apply_glossary changed the output.
            applied_terms_count: Count of glossary terms applied in postprocess.
            latency_ms: Total provider latency.
            worker_latency_ms: Worker inference latency.

        Returns:
            Populated EffectivePromptTrace.
        """
        # Rendered glossary block (Layer 4a) — re-render using same inputs as prompt
        rendered_glossary: str | None = None
        if glossary_terms and policy.terminology_mode != TerminologyMode.OFF:
            rendered_glossary = _RENDERER._render_glossary_block(glossary_terms, policy)

        # Effective prompt preview (Layers 1–5 assembled for UI)
        preview = _RENDERER.render_effective_preview(
            policy=policy,
            source_text=protected.text,
            glossary_terms=glossary_terms if glossary_terms else None,
            context_items=None,
        )

        return EffectivePromptTrace(
            trace_id=request.trace_id,
            # Policy snapshot
            policy_id=policy.policy_id,
            policy_version=policy.version,
            policy_hash=policy.policy_hash,
            template_profile_id=policy.template_profile_id,
            sampling_profile_id=policy.sampling_profile_id,
            content_kind=policy.content_kind,
            source_lang=request.source_lang.lower(),
            target_lang=request.target_lang.lower(),
            # Model identity
            model_id=self.model_id,
            model_quant_id=self._MODEL_QUANT_ID,
            provider_id=self.provider_id,
            # Source
            source_text=request.source_text,
            source_text_hash=compute_source_text_hash(request.source_text),
            source_length_chars=len(request.source_text),
            # Rendered layers (1–5)
            rendered_role_instruction=policy.role_instruction,
            rendered_task_instruction=policy.task_instruction,
            rendered_output_policy=policy.output_policy,
            rendered_glossary_block=rendered_glossary,
            rendered_context_block=None,  # PATCH-07
            rendered_formatting_note=None,
            rendered_user_payload=protected.text,
            effective_prompt_preview=preview,
            # Input hashes
            glossary_hash=compute_glossary_hash(rendered_glossary) if rendered_glossary else None,
            context_hash=None,  # PATCH-07
            # Applied constraints
            applied_sampling=build_applied_sampling(
                policy, self._FORCE_GREEDY, self._MAX_N_PREDICT_CAP
            ),
            placeholder_tokens_protected=list(protected.mapping.keys()),
            placeholder_tokens_restored=len(protected.mapping) - len(missing),
            # Output
            raw_model_output=raw_model_output,
            translated_text=final_translation,
            output_length_chars=len(final_translation),
            output_tokens_generated=None,  # PATCH-06
            # Performance
            latency_ms=latency_ms,
            worker_latency_ms=worker_latency_ms,
            # Flags
            glossary_applied=used_glossary,
            context_applied=False,
            fallback_triggered=router_result.fallback_triggered,
            fallback_reason=router_result.fallback_reason,
            created_at=datetime.now(UTC),
        )

    def shutdown(self) -> None:
        """Shutdown worker subprocess."""
        if self.worker:
            try:
                self.worker.shutdown()
                logger.info("LocalHYMTProvider worker shut down")
            except Exception as e:
                logger.warning(f"Error shutting down HY-MT worker: {e}")
            finally:
                self.worker = None

    def __del__(self) -> None:
        """Cleanup on deletion."""
        try:
            if hasattr(self, "worker") and self.worker:
                self.shutdown()
        except Exception:
            pass
