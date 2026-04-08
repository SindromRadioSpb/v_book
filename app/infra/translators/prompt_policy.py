"""Prompt Policy System for HY-MT local translation providers.

Defines the domain model (enums, dataclasses) and module-level registries for
PromptPolicy, SamplingProfile, and TemplateProfile objects.

All registries are populated at import time with no I/O.
No filesystem reads, no database queries. Pure Python data.

Refs: docs/HY_MT_PROMPT_POLICY_SPEC_V3.md
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

_logger = logging.getLogger(__name__)

_SPEC_DATE = datetime(2026, 4, 7)


# ============================================================================
# Enumerations
# ============================================================================


class ContentKind(StrEnum):
    """Semantic kind of the content being translated.

    Callers must set this so TranslationRouter can select the correct profile.
    When not set, TranslationRouter defaults to SENTENCE.
    """

    LEMMA = "lemma"
    TERM = "term"
    SENTENCE = "sentence"
    SENTENCE_WITH_CONTEXT = "sentence_with_context"
    SENTENCE_FORMATTED = "sentence_formatted"
    UI_STRING = "ui_string"
    BATCH_MIXED = "batch_mixed"


class TerminologyMode(StrEnum):
    """How glossary terms are injected into the prompt and applied in post-process.

    V3 canonical vocabulary. Migration from V1:
        BOTH   -> SOFT_GLOSSARY   (inject as suggestion + soft postprocess)
        PROMPT -> SOFT_GLOSSARY   (inject; soft postprocess still applies)
        OFF    -> OFF             (unchanged)
        (strict enforcement now explicit: STRICT_GLOSSARY)
    """

    OFF = "off"
    SOFT_GLOSSARY = "soft_glossary"
    STRICT_GLOSSARY = "strict_glossary"
    APPROVED_TERMS_ONLY = "approved_terms_only"


class ContextMode(StrEnum):
    """Whether and how surrounding segment context is included in the prompt."""

    OFF = "off"
    PREVIOUS_SENTENCE = "previous_sentence"
    SURROUNDING_SENTENCES = "surrounding_sentences"
    PARAGRAPH = "paragraph"
    CUSTOM_CONTEXT_BLOCK = "custom_context_block"


class FormattingMode(StrEnum):
    """How inline formatting / placeholders are handled."""

    PLAIN_TEXT = "plain_text"
    PRESERVE_NUMBERS_NAMES = "preserve_numbers_names"
    PRESERVE_PLACEHOLDERS = "preserve_placeholders"
    PRESERVE_INLINE_TAGS = "preserve_inline_tags"
    PRESERVE_FULL_MARKUP = "preserve_full_markup"


class PlaceholderMode(StrEnum):
    """Placeholder protection level.

    OFF is intentionally absent — protection cannot be disabled in any
    production profile.  The system rejects any policy with placeholder_mode=off.
    """

    PROTECT_KNOWN_PLACEHOLDERS = "protect_known_placeholders"
    STRICT_PROTECT_ALL_TOKENS = "strict_protect_all_tokens"
    RESTORE_AFTER_GENERATION = "restore_after_generation"


# ============================================================================
# SamplingProfile
# ============================================================================


@dataclass
class SamplingProfile:
    """Generation hyperparameters for model.generate().

    Expresses the policy author's intent.  Model-layer constraints
    (from TemplateProfile.force_greedy / max_n_predict_cap) are applied by
    _resolve_gen_kwargs() and may override these values when the active model
    family cannot support stochastic decoding.
    """

    sampling_profile_id: str
    name: str
    description: str

    # Core sampling parameters
    temperature: float = 0.7
    top_k: int = 20
    top_p: float = 0.9
    min_p: float = 0.0
    typical_p: float = 1.0
    repetition_penalty: float = 1.0
    repeat_last_n: int = 64
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    mirostat_mode: int = 0
    seed: int = -1
    n_predict: int = 512

    def validate(self) -> list[str]:
        """Return list of validation error strings; empty list = valid.

        Called at module import time for all built-in profiles.
        """
        errors: list[str] = []
        if self.temperature < 0.0:
            errors.append(f"temperature must be >= 0.0, got {self.temperature}")
        if self.top_k < 0:
            errors.append(f"top_k must be >= 0, got {self.top_k}")
        if not 0.0 <= self.top_p <= 1.0:
            errors.append(f"top_p must be in [0.0, 1.0], got {self.top_p}")
        if self.n_predict < 1:
            errors.append(f"n_predict must be >= 1, got {self.n_predict}")
        if self.repetition_penalty < 0.0:
            errors.append(f"repetition_penalty must be >= 0.0, got {self.repetition_penalty}")
        if self.mirostat_mode not in (0, 1, 2):
            errors.append(f"mirostat_mode must be 0, 1, or 2, got {self.mirostat_mode}")
        return errors


# ============================================================================
# TemplateProfile
# ============================================================================


@dataclass
class TemplateProfile:
    """Model-family-specific rendering configuration.

    Template profiles are internal and not exposed to users.
    Selection is automatic:
      - 1.8B providers  -> hy_mt_*_observed profiles
      - 7B-GPTQ         -> hy_mt_7b_* profiles

    The force_greedy and max_n_predict_cap fields are hardware-derived
    constraints that override SamplingProfile when the model cannot support
    stochastic decoding (7B-GPTQ on Windows: ~0.6 s/token).
    """

    template_profile_id: str
    name: str

    # Which semantic sections to render in user_content
    use_role_instruction: bool = True
    use_task_instruction: bool = True
    use_output_policy: bool = True
    use_context_block: bool = False
    use_glossary_block: bool = False
    use_formatting_block: bool = False
    use_placeholder_note: bool = False  # explicit reminder to model in Layer 4c

    # Model-level hardware constraints (set per model family, not by policy author)
    target_backend: str = "transformers_causal"
    force_greedy: bool = False
    max_n_predict_cap: int | None = None

    # Internal rendering variant identifier
    render_variant: str = "standard"


# ============================================================================
# PromptPolicy
# ============================================================================


@dataclass
class PromptPolicy:
    """Named, versioned policy governing one translation profile.

    Each policy maps a content_kind to a specific combination of:
    - semantic instructions (role, task, output policy)  — Layers 1–3
    - modes (terminology, context, formatting, placeholder)
    - sampling and template profile references

    Built-in policies (is_builtin=True) are defined in PROMPT_POLICIES.
    User-created copies have is_custom=True and may have is_builtin=False.
    """

    # Required identity
    policy_id: str
    name: str
    content_kind: ContentKind
    source_lang: str  # ISO 639-1, e.g. "he"
    target_lang: str  # ISO 639-1, e.g. "ru"

    # Semantic layers visible in Advanced/Debug mode
    role_instruction: str  # Layer 1: who the model is (empty = use global system prompt only)
    task_instruction: str  # Layer 2: what to do
    output_policy: str  # Layer 3: what the output must look like (empty = no constraint)

    # Modes
    terminology_mode: TerminologyMode
    sampling_profile_id: str
    template_profile_id: str  # internal; maps to worker template variant

    # Optional fields with defaults
    description: str = ""
    enabled: bool = True
    version: str = "1.0.0"
    policy_hash: str = ""  # SHA-256 of canonical JSON; computed in PATCH-06

    context_mode: ContextMode = ContextMode.OFF
    formatting_mode: FormattingMode = FormattingMode.PRESERVE_PLACEHOLDERS
    placeholder_mode: PlaceholderMode = PlaceholderMode.PROTECT_KNOWN_PLACEHOLDERS

    glossary_strategy: str = "top_ranked_relevant"
    context_strategy: str = "nearest_N_segments"

    # UX permissions — which layers users may edit in Advanced mode
    allow_user_edit_role: bool = False
    allow_user_edit_task: bool = False
    allow_user_edit_output_policy: bool = False

    # Per-request limits (None = use profile or model defaults)
    max_input_chars: int | None = None
    max_context_items: int | None = None
    max_glossary_items: int | None = 20  # matches _fetch_glossary_terms_for_prompt limit

    # Metadata
    is_builtin: bool = True
    is_custom: bool = False
    experimental: bool = False
    created_at: datetime = field(default_factory=lambda: _SPEC_DATE)
    updated_at: datetime = field(default_factory=lambda: _SPEC_DATE)


# ============================================================================
# Registry — SamplingProfile  (3 built-in profiles)
# ============================================================================

SAMPLING_PROFILES: dict[str, SamplingProfile] = {
    p.sampling_profile_id: p
    for p in [
        # hy_mt_precise_sentence — general-purpose sentence translation.
        # These values MUST match the current hard-coded gen_kwargs in
        # worker_process._translate_transformers_causal for 1.8B to ensure
        # zero regression on the sentence_ru profile.
        SamplingProfile(
            sampling_profile_id="hy_mt_precise_sentence",
            name="Precise (Sentence)",
            description=(
                "Standard translation profile for full sentences. "
                "Sampling with moderate creativity and repetition penalty. "
                "Regression baseline — sentence_ru profile must produce identical "
                "output to the pre-PPS implementation."
            ),
            temperature=0.7,
            top_k=20,
            top_p=0.6,
            repetition_penalty=1.05,
            n_predict=512,
        ),
        # hy_mt_precise_short — greedy, tight token budget for lemmas and terms.
        SamplingProfile(
            sampling_profile_id="hy_mt_precise_short",
            name="Precise (Short Output)",
            description=(
                "Greedy decoding for short deterministic outputs. "
                "Used for lemmas, technical terms, and UI strings where "
                "canonical form is required over creative variation. "
                "7B-GPTQ TemplateProfile caps n_predict to 16."
            ),
            temperature=0.0,  # greedy by intent (not a hardware constraint)
            top_k=0,
            top_p=1.0,
            min_p=0.0,
            repetition_penalty=1.0,
            n_predict=32,  # 1.8B; 7B-GPTQ TemplateProfile caps to 16
        ),
        # hy_mt_precise_formatted — conservative sampling for segments with placeholders.
        SamplingProfile(
            sampling_profile_id="hy_mt_precise_formatted",
            name="Precise (Formatted)",
            description=(
                "Lower temperature and tighter top_k for segments with inline markup. "
                "Reduces risk of generating spurious HDLE_PH_N tokens not present "
                "in the source. Stricter repetition penalty."
            ),
            temperature=0.5,
            top_k=10,
            top_p=0.5,
            repetition_penalty=1.1,
            n_predict=512,
        ),
    ]
}


# ============================================================================
# Registry — TemplateProfile  (6 built-in profiles)
# ============================================================================

TEMPLATE_PROFILES: dict[str, TemplateProfile] = {
    t.template_profile_id: t
    for t in [
        TemplateProfile(
            template_profile_id="hy_mt_standard_observed",
            name="HY-MT 1.8B Standard",
            render_variant="standard",
            max_n_predict_cap=512,
        ),
        TemplateProfile(
            template_profile_id="hy_mt_glossary_observed",
            name="HY-MT 1.8B Glossary",
            use_glossary_block=True,
            render_variant="glossary_heavy",
            max_n_predict_cap=512,
        ),
        TemplateProfile(
            template_profile_id="hy_mt_context_observed",
            name="HY-MT 1.8B Context-Aware",
            use_context_block=True,
            render_variant="context_aware",
            max_n_predict_cap=512,
        ),
        TemplateProfile(
            template_profile_id="hy_mt_formatted_observed",
            name="HY-MT 1.8B Formatted",
            use_placeholder_note=True,  # injects explicit placeholder-order reminder (Layer 4c)
            render_variant="formatted_strict",
            max_n_predict_cap=512,
        ),
        TemplateProfile(
            template_profile_id="hy_mt_7b_standard",
            name="HY-MT 7B-GPTQ Standard",
            force_greedy=True,  # hardware constraint: ~0.6 s/token, no triton on Windows
            max_n_predict_cap=128,  # 128 x 0.6 = 76.8 s < 120 s provider timeout
            render_variant="standard",
        ),
        TemplateProfile(
            template_profile_id="hy_mt_7b_glossary",
            name="HY-MT 7B-GPTQ Glossary",
            use_glossary_block=True,
            force_greedy=True,
            max_n_predict_cap=128,
            render_variant="glossary_heavy",
        ),
    ]
}


# ============================================================================
# Registry — PromptPolicy  (6 built-in profiles)
# ============================================================================

PROMPT_POLICIES: dict[str, PromptPolicy] = {
    p.policy_id: p
    for p in [
        # ------------------------------------------------------------------
        # sentence_ru — default, regression baseline
        # ------------------------------------------------------------------
        PromptPolicy(
            policy_id="sentence_ru",
            name="Standard Translation",
            content_kind=ContentKind.SENTENCE,
            source_lang="he",
            target_lang="ru",
            role_instruction="",
            task_instruction=(
                "Translate the following segment into Russian, " "without additional explanation."
            ),
            output_policy="",
            terminology_mode=TerminologyMode.SOFT_GLOSSARY,
            sampling_profile_id="hy_mt_precise_sentence",
            template_profile_id="hy_mt_standard_observed",
            description=(
                "General-purpose translation for plain CAT segments. "
                "Matches current production behaviour exactly. "
                "Regression baseline."
            ),
        ),
        # ------------------------------------------------------------------
        # sentence_ru_context — context-aware, experimental
        # ------------------------------------------------------------------
        PromptPolicy(
            policy_id="sentence_ru_context",
            name="Contextual Translation",
            content_kind=ContentKind.SENTENCE_WITH_CONTEXT,
            source_lang="he",
            target_lang="ru",
            role_instruction="",
            task_instruction=(
                "Translate the following segment into Russian, "
                "without additional explanation. "
                "Use the surrounding context to resolve ambiguity. "
                "Do not translate the context \u2014 translate only the segment."
            ),
            output_policy="Output only the Russian translation of the segment.",
            terminology_mode=TerminologyMode.SOFT_GLOSSARY,
            context_mode=ContextMode.SURROUNDING_SENTENCES,
            sampling_profile_id="hy_mt_precise_sentence",
            template_profile_id="hy_mt_context_observed",
            experimental=True,
            allow_user_edit_task=True,
            description=(
                "Includes surrounding segments as context. "
                "Improves pronoun resolution and discourse cohesion. "
                "Validate on test corpus before enabling in Basic mode."
            ),
        ),
        # ------------------------------------------------------------------
        # sentence_ru_formatted — segments with HDLE_PH_N placeholders
        # ------------------------------------------------------------------
        PromptPolicy(
            policy_id="sentence_ru_formatted",
            name="Formatted Text Translation",
            content_kind=ContentKind.SENTENCE_FORMATTED,
            source_lang="he",
            target_lang="ru",
            role_instruction="",
            task_instruction=(
                "Translate the following segment into Russian, " "without additional explanation."
            ),
            output_policy="",
            terminology_mode=TerminologyMode.SOFT_GLOSSARY,
            formatting_mode=FormattingMode.PRESERVE_PLACEHOLDERS,
            sampling_profile_id="hy_mt_precise_formatted",
            template_profile_id="hy_mt_formatted_observed",  # use_placeholder_note=True
            description=(
                "For segments containing inline markup or HDLE_PH_N tokens. "
                "TemplateProfile injects explicit placeholder-order reminder (Layer 4c)."
            ),
        ),
        # ------------------------------------------------------------------
        # lemma_ru — single dictionary headwords
        # ------------------------------------------------------------------
        PromptPolicy(
            policy_id="lemma_ru",
            name="Lemma / Dictionary Entry",
            content_kind=ContentKind.LEMMA,
            source_lang="he",
            target_lang="ru",
            role_instruction=(
                "You are a bilingual Hebrew\u2013Russian lexicographer. "
                "Output only the single most natural Russian equivalent "
                "for the given Hebrew lemma."
            ),
            task_instruction="Translate the following Hebrew lemma into Russian.",
            output_policy=(
                "Output a single word or short phrase only. "
                "No grammatical commentary, no example sentences."
            ),
            terminology_mode=TerminologyMode.OFF,
            formatting_mode=FormattingMode.PLAIN_TEXT,
            sampling_profile_id="hy_mt_precise_short",
            template_profile_id="hy_mt_standard_observed",
            max_glossary_items=None,  # glossary disabled; field is informational only
            description=(
                "Optimised for single dictionary headwords (1\u20133 Hebrew words). "
                "Greedy decoding, max 32 tokens (1.8B) / 16 tokens (7B-GPTQ). "
                "Glossary explicitly disabled: lemma output is itself the term."
            ),
        ),
        # ------------------------------------------------------------------
        # term_ru — technical multi-word terms, soft glossary
        # ------------------------------------------------------------------
        PromptPolicy(
            policy_id="term_ru",
            name="Technical Term",
            content_kind=ContentKind.TERM,
            source_lang="he",
            target_lang="ru",
            role_instruction=(
                "You are a technical translator specialised in Hebrew. "
                "Output only the most established Russian equivalent."
            ),
            task_instruction="Translate the following Hebrew technical term into Russian.",
            output_policy="Output a single noun phrase only. No article, no explanation.",
            terminology_mode=TerminologyMode.SOFT_GLOSSARY,
            formatting_mode=FormattingMode.PLAIN_TEXT,
            sampling_profile_id="hy_mt_precise_short",
            template_profile_id="hy_mt_glossary_observed",
            description=(
                "For multi-word technical terms. Glossary injected as reference; "
                "soft postprocess applied as a safety net."
            ),
        ),
        # ------------------------------------------------------------------
        # term_ru_strict_glossary — strict enforcement of approved terms
        # ------------------------------------------------------------------
        PromptPolicy(
            policy_id="term_ru_strict_glossary",
            name="Technical Term (Strict Glossary)",
            content_kind=ContentKind.TERM,
            source_lang="he",
            target_lang="ru",
            role_instruction=(
                "You are a technical translator specialised in Hebrew. "
                "Always use the exact approved Russian term from the provided "
                "terminology list. Do not paraphrase."
            ),
            task_instruction=(
                "Translate the following Hebrew technical term into Russian. "
                "Use only the approved term from the Terminology list above."
            ),
            output_policy="Output the approved term verbatim. No modification.",
            terminology_mode=TerminologyMode.STRICT_GLOSSARY,
            formatting_mode=FormattingMode.PLAIN_TEXT,
            sampling_profile_id="hy_mt_precise_short",
            template_profile_id="hy_mt_glossary_observed",
            description=(
                "Strict glossary enforcement: model instructed to copy approved term. "
                "apply_glossary() postprocess applies as safety net."
            ),
        ),
    ]
}

#: Default policy used when no content_kind or policy_id is provided.
DEFAULT_POLICY_ID: str = "sentence_ru"


# ============================================================================
# Registry lookup helpers
# ============================================================================


def get_policy(policy_id: str) -> PromptPolicy:
    """Return policy by ID.

    Args:
        policy_id: Policy identifier (e.g. "sentence_ru").

    Returns:
        PromptPolicy instance from the module-level registry.

    Raises:
        KeyError: If policy_id is not registered.
    """
    return PROMPT_POLICIES[policy_id]


def list_profiles(*, include_experimental: bool = False) -> list[PromptPolicy]:
    """Return enabled profiles, optionally including experimental ones.

    Args:
        include_experimental: If False (default), exclude experimental profiles.

    Returns:
        List of PromptPolicy instances, sorted by policy_id.
    """
    return sorted(
        [
            p
            for p in PROMPT_POLICIES.values()
            if p.enabled and (include_experimental or not p.experimental)
        ],
        key=lambda p: p.policy_id,
    )


def get_sampling_profile(profile_id: str) -> SamplingProfile:
    """Return sampling profile by ID.

    Args:
        profile_id: Profile identifier (e.g. "hy_mt_precise_sentence").

    Raises:
        KeyError: If profile_id is not registered.
    """
    return SAMPLING_PROFILES[profile_id]


def get_template_profile(profile_id: str) -> TemplateProfile:
    """Return template profile by ID.

    Args:
        profile_id: Profile identifier (e.g. "hy_mt_standard_observed").

    Raises:
        KeyError: If profile_id is not registered.
    """
    return TEMPLATE_PROFILES[profile_id]


# ============================================================================
# PPS PATCH-06: Hash computation utilities
# ============================================================================

# Fields included in policy_hash canonical representation.
# Rules: include all fields that affect translation output semantics.
# Excluded: name, description, enabled, is_builtin, is_custom, experimental,
#   allow_user_edit_*, created_at, updated_at, policy_hash (circular).
# These exclusions are intentional and documented — they are operational/display
# attributes that do not change the model instruction sent to the worker.
_POLICY_HASH_FIELDS: tuple[str, ...] = (
    "policy_id",
    "version",
    "content_kind",
    "source_lang",
    "target_lang",
    "role_instruction",
    "task_instruction",
    "output_policy",
    "terminology_mode",
    "context_mode",
    "formatting_mode",
    "placeholder_mode",
    "sampling_profile_id",
    "template_profile_id",
    "glossary_strategy",
    "context_strategy",
    "max_glossary_items",
    "max_context_items",
    "max_input_chars",
)


def compute_policy_hash(policy: PromptPolicy) -> str:
    """Compute deterministic SHA-256 of a PromptPolicy's semantic fields.

    Canonical representation: JSON object with keys from ``_POLICY_HASH_FIELDS``,
    serialised with ``sort_keys=True, ensure_ascii=False``, UTF-8 encoded.

    Enum values are converted to their string representation via ``str()``.
    Non-semantic fields (display metadata, timestamps, access flags) are excluded.

    Args:
        policy: The PromptPolicy to hash.

    Returns:
        64-character lowercase hex digest (SHA-256).
    """
    canonical: dict = {}
    for field_name in _POLICY_HASH_FIELDS:
        value = getattr(policy, field_name)
        # Enum → str for deterministic serialisation; None → None (kept as-is)
        if isinstance(value, StrEnum):
            canonical[field_name] = str(value)
        else:
            canonical[field_name] = value
    serialized = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_source_text_hash(source_text: str) -> str:
    """Compute deterministic SHA-256 of source text for deduplication.

    Hashes the original (unprotected) source text — not the placeholder-protected
    payload — because the canonical input for deduplication is the human-readable
    source, and placeholder substitution is non-deterministic in slot numbering.

    Args:
        source_text: Original source text as provided in TranslationRequest.

    Returns:
        64-character lowercase hex digest (SHA-256).
    """
    return hashlib.sha256(source_text.encode("utf-8")).hexdigest()


def compute_glossary_hash(rendered_block: str) -> str:
    """Compute deterministic SHA-256 of the rendered glossary block.

    Hashes the actual glossary text injected into the prompt (already rendered by
    PolicyRenderer._render_glossary_block).  The rendered form captures term
    ordering, count limit, and header text — so it accurately represents what
    the model received.

    Args:
        rendered_block: The rendered glossary string (output of _render_glossary_block).

    Returns:
        64-character lowercase hex digest (SHA-256).
    """
    return hashlib.sha256(rendered_block.encode("utf-8")).hexdigest()


def compute_context_hash(rendered_block: str) -> str:
    """Compute deterministic SHA-256 of the rendered context block.

    Hashes the context text injected into the prompt (already rendered by
    PolicyRenderer._render_context_block).  The rendered form captures item
    count and ordering — so it accurately represents what the model received.

    Args:
        rendered_block: The rendered context string (output of _render_context_block).

    Returns:
        64-character lowercase hex digest (SHA-256).
    """
    return hashlib.sha256(rendered_block.encode("utf-8")).hexdigest()


# ============================================================================
# Startup validation  (runs at import time, no I/O)
# ============================================================================


def _validate_registry() -> None:
    """Validate all built-in registry entries and compute policy hashes.

    Called once at module import. Raises on any misconfiguration so that
    errors are surfaced immediately rather than at the first translation request.
    Also populates ``policy_hash`` on every built-in PromptPolicy after
    validation succeeds — this is the canonical PATCH-06 hook.

    Raises:
        ValueError: If a SamplingProfile fails parameter validation.
        KeyError: If a policy references an unregistered sampling/template profile.
    """
    for sp in SAMPLING_PROFILES.values():
        errors = sp.validate()
        if errors:
            raise ValueError(f"SamplingProfile '{sp.sampling_profile_id}' invalid: {errors}")

    for policy in PROMPT_POLICIES.values():
        if policy.sampling_profile_id not in SAMPLING_PROFILES:
            raise KeyError(
                f"Policy '{policy.policy_id}' references unknown sampling profile "
                f"'{policy.sampling_profile_id}'"
            )
        if policy.template_profile_id not in TEMPLATE_PROFILES:
            raise KeyError(
                f"Policy '{policy.policy_id}' references unknown template profile "
                f"'{policy.template_profile_id}'"
            )

    if DEFAULT_POLICY_ID not in PROMPT_POLICIES:
        raise KeyError(f"DEFAULT_POLICY_ID '{DEFAULT_POLICY_ID}' not in PROMPT_POLICIES")

    # PPS PATCH-06: compute and stamp policy_hash on all built-in policies.
    # Done after structural validation so we never hash a misconfigured policy.
    for policy in PROMPT_POLICIES.values():
        policy.policy_hash = compute_policy_hash(policy)
    _logger.debug(
        "policy_hashes_computed count=%d",
        len(PROMPT_POLICIES),
    )


_validate_registry()


# ============================================================================
# Sentinel constants  (duplicated in worker_process.py — keep in sync)
# ============================================================================

#: Prefix that marks a WorkerRequest.text as a PPS payload.
#: Uses null bytes so no natural source text can match accidentally.
_PPS_SENTINEL_START: str = "\x00PPS_PAYLOAD\x00"

#: Separator between role_instruction and user_content inside the payload.
_PPS_ROLE_SEP: str = "\x00ROLE\x00"


# ============================================================================
# PolicyRenderer
# ============================================================================


class PolicyRenderer:
    """Renders a PromptPolicy into ``WorkerRequest.text``.

    Two rendering modes:

    * :meth:`render_user_content` — plain user_content string (no sentinel).
      Used for providers that do not support PPS sentinel yet (legacy path).

    * :meth:`render_sentinel_payload` — PPS sentinel payload:
      ``_PPS_SENTINEL_START + role_instruction + _PPS_ROLE_SEP + user_content``.
      The worker parses this to build the model-specific chat template.

    ``user_content`` structure (Layers 2–5):

    1. task_instruction   (Layer 2 — what to do)
    2. output_policy      (Layer 3 — format constraint, if any)
    3. context_block      (Layer 4a — surrounding segments, if any)
    4. glossary_block     (Layer 4b — terminology, if any)
    5. source_text        (Layer 5)

    This order matches the current hardcoded template for ``sentence_ru`` so
    that the 1.8B regression baseline is preserved: no glossary, no context →
    ``"Translate the following segment into Russian, without additional
    explanation.\\n\\n{source_text}"`` (identical to pre-PPS code).
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render_user_content(
        self,
        policy: PromptPolicy,
        source_text: str,
        glossary_terms: list[tuple[str, str]] | None = None,
        context_items: list[str] | None = None,
    ) -> str:
        """Return plain user_content (no sentinel wrapper).

        Args:
            policy: Active PromptPolicy.
            source_text: Placeholder-protected source segment.
            glossary_terms: List of (source_term, target_term) pairs, pre-ranked.
            context_items: Surrounding segments for context-aware policies.

        Returns:
            User content string ready for the worker's chat template.
        """
        return self._render_visible_content(policy, source_text, glossary_terms, context_items)

    def render_sentinel_payload(
        self,
        policy: PromptPolicy,
        source_text: str,
        glossary_terms: list[tuple[str, str]] | None = None,
        context_items: list[str] | None = None,
    ) -> str:
        """Return PPS sentinel payload for ``WorkerRequest.text``.

        Format::

            \\x00PPS_PAYLOAD\\x00{role_instruction}\\x00ROLE\\x00{user_content}

        The worker detects the sentinel prefix and splits on ``_PPS_ROLE_SEP``
        to recover ``role_instruction`` and ``user_content`` before building
        the model-specific chat template.

        Args:
            policy: Active PromptPolicy.
            source_text: Placeholder-protected source segment.
            glossary_terms: List of (source_term, target_term) pairs, pre-ranked.
            context_items: Surrounding segments for context-aware policies.

        Returns:
            Sentinel-wrapped string for ``WorkerRequest.text``.
        """
        user_content = self._render_visible_content(
            policy, source_text, glossary_terms, context_items
        )
        return f"{_PPS_SENTINEL_START}{policy.role_instruction}{_PPS_ROLE_SEP}{user_content}"

    def render_effective_preview(
        self,
        policy: PromptPolicy,
        source_text: str,
        glossary_terms: list[tuple[str, str]] | None = None,
        context_items: list[str] | None = None,
    ) -> str:
        """Return human-readable all-layer preview for debug/advanced mode UI.

        Shows every layer as it would appear in the final prompt.
        Not passed to the model.

        Args:
            policy: Active PromptPolicy.
            source_text: Source segment (may be redacted in production logs).
            glossary_terms: Glossary pairs, pre-ranked.
            context_items: Surrounding segments.

        Returns:
            Formatted multi-section string for display.
        """
        parts: list[str] = []
        if policy.role_instruction:
            parts.append(f"[Role]\n{policy.role_instruction}")
        user_content = self._render_visible_content(
            policy, source_text, glossary_terms, context_items
        )
        parts.append(f"[User]\n{user_content}")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _render_visible_content(
        self,
        policy: PromptPolicy,
        source_text: str,
        glossary_terms: list[tuple[str, str]] | None,
        context_items: list[str] | None,
    ) -> str:
        """Assemble Layers 2–5 into user_content."""
        parts: list[str] = []

        # Layer 2: task instruction
        if policy.task_instruction:
            parts.append(policy.task_instruction)

        # Layer 3: output policy (format constraint)
        if policy.output_policy:
            parts.append(policy.output_policy)

        # Layer 4a: context block
        if context_items and policy.context_mode != ContextMode.OFF:
            parts.append(self._render_context_block(context_items))

        # Layer 4b: glossary block
        if glossary_terms and policy.terminology_mode != TerminologyMode.OFF:
            parts.append(self._render_glossary_block(glossary_terms, policy))

        # Layer 5: source text
        parts.append(source_text)

        return "\n\n".join(parts)

    def _render_glossary_block(
        self,
        glossary_terms: list[tuple[str, str]],
        policy: PromptPolicy,
    ) -> str:
        """Render glossary as a Terminology block."""
        if policy.terminology_mode == TerminologyMode.STRICT_GLOSSARY:
            header = "Approved Terminology (use exactly):"
        else:
            header = "Terminology:"
        limit = policy.max_glossary_items
        terms = glossary_terms[:limit] if limit is not None else glossary_terms
        lines = [header] + [f"{src}: {tgt}" for src, tgt in terms]
        return "\n".join(lines)

    def _render_context_block(self, context_items: list[str]) -> str:
        """Render surrounding context as a Context block."""
        lines = ["Context:"] + [f"  {item}" for item in context_items]
        return "\n".join(lines)


# ============================================================================
# PPS PATCH-07: Template profile family resolution
# ============================================================================

# Provider family tokens — matched against LocalHYMTProvider._PROVIDER_FAMILY
_TEMPLATE_FAMILY_OBSERVED: str = "observed"  # 1.8B: hy_mt_*_observed templates
_TEMPLATE_FAMILY_7B: str = "7b_gptq"  # 7B-GPTQ: hy_mt_7b_* templates

# Nearest-equivalent mapping: (specified_template_id, target_family) -> resolved_id
# Used when the policy's template_profile_id is incompatible with the active provider family.
_TEMPLATE_NEAREST: dict[tuple[str, str], str] = {
    # 7B template requested but 1.8B provider active
    ("hy_mt_7b_standard", _TEMPLATE_FAMILY_OBSERVED): "hy_mt_standard_observed",
    ("hy_mt_7b_glossary", _TEMPLATE_FAMILY_OBSERVED): "hy_mt_glossary_observed",
    # 1.8B template requested but 7B provider active
    ("hy_mt_standard_observed", _TEMPLATE_FAMILY_7B): "hy_mt_7b_standard",
    ("hy_mt_glossary_observed", _TEMPLATE_FAMILY_7B): "hy_mt_7b_glossary",
    (
        "hy_mt_context_observed",
        _TEMPLATE_FAMILY_7B,
    ): "hy_mt_7b_standard",  # no 7B context profile yet
    (
        "hy_mt_formatted_observed",
        _TEMPLATE_FAMILY_7B,
    ): "hy_mt_7b_standard",  # no 7B formatted profile yet
}

# Safe fallback per family when no nearest equivalent is found in _TEMPLATE_NEAREST
_TEMPLATE_FAMILY_DEFAULT: dict[str, str] = {
    _TEMPLATE_FAMILY_OBSERVED: "hy_mt_standard_observed",
    _TEMPLATE_FAMILY_7B: "hy_mt_7b_standard",
}


def resolve_template_profile(
    policy: PromptPolicy,
    provider_family: str,
) -> tuple[str, str | None]:
    """Resolve the effective template_profile_id for the given provider family.

    If ``policy.template_profile_id`` is compatible with ``provider_family``,
    it is returned unchanged and warning is ``None``.  Otherwise the nearest
    compatible equivalent is selected, a ``WARNING`` is logged, and a
    structured warning string is returned for inclusion in
    ``meta["prompt_policy"]["warnings"]``.

    Compatibility rules (spec §10.4):
    - ``"observed"`` family: template ID must end with ``"_observed"``
    - ``"7b_gptq"`` family:  template ID must start with ``"hy_mt_7b_"``

    Args:
        policy:          Active ``PromptPolicy`` after router resolution.
        provider_family: ``_TEMPLATE_FAMILY_OBSERVED`` or ``_TEMPLATE_FAMILY_7B``.

    Returns:
        ``(resolved_template_profile_id, warning_msg | None)``.
    """
    specified = policy.template_profile_id

    if provider_family == _TEMPLATE_FAMILY_OBSERVED:
        is_compatible = specified.endswith("_observed")
    elif provider_family == _TEMPLATE_FAMILY_7B:
        is_compatible = specified.startswith("hy_mt_7b_")
    else:
        # Unknown family — pass through unchanged, record warning
        return specified, (
            f"template_profile_unknown_family"
            f" policy_id={policy.policy_id!r}"
            f" provider_family={provider_family!r}"
            f" using_as_is={specified!r}"
        )

    if is_compatible:
        return specified, None

    resolved = _TEMPLATE_NEAREST.get(
        (specified, provider_family),
        _TEMPLATE_FAMILY_DEFAULT.get(provider_family, "hy_mt_standard_observed"),
    )
    warning = (
        f"template_profile_mismatch"
        f" policy_id={policy.policy_id!r}"
        f" specified={specified!r}"
        f" selected={resolved!r}"
        f" family={provider_family!r}"
    )
    _logger.warning(
        "template_profile_mismatch policy_id=%s specified=%s selected=%s family=%s",
        policy.policy_id,
        specified,
        resolved,
        provider_family,
    )
    return resolved, warning


# ============================================================================
# TranslationRouter
# ============================================================================


@dataclass
class RouterResult:
    """Structured outcome of a ``TranslationRouter.route()`` call.

    Carries everything the provider needs for policy application and
    ``meta["prompt_policy"]`` construction — without requiring the provider to
    re-derive any resolution logic.
    """

    policy: PromptPolicy
    #: Resolution source: "explicit" | "content_kind" | "fallback"
    source: str
    #: True when the router replaced the initially resolved policy due to an error
    #: or experimental guard.  False for the normal global-default path.
    fallback_triggered: bool
    fallback_reason: str | None
    warnings: list[str] = field(default_factory=list)


class TranslationRouter:
    """Routes a ``TranslationRequest.options`` dict to a ``PromptPolicy``.

    Resolution order (spec §10.1):
    1. ``options["prompt_policy_id"]`` — explicit override
    2. ``options["content_kind"]`` → built-in ContentKind→policy mapping
    3. Global default (``DEFAULT_POLICY_ID = "sentence_ru"``)

    Experimental guard (spec §10.3):
    If the resolved policy has ``experimental=True`` and ``allow_experimental``
    is False, the router falls back to ``sentence_ru`` and records a warning.

    The router is stateless; a single module-level instance is sufficient.
    """

    # Spec §10.1: ContentKind → default policy_id
    _KIND_TO_POLICY: dict[ContentKind, str] = {
        ContentKind.LEMMA: "lemma_ru",
        ContentKind.TERM: "term_ru",
        ContentKind.SENTENCE: "sentence_ru",
        ContentKind.SENTENCE_WITH_CONTEXT: "sentence_ru_context",
        ContentKind.SENTENCE_FORMATTED: "sentence_ru_formatted",
        ContentKind.UI_STRING: "lemma_ru",
        ContentKind.BATCH_MIXED: "sentence_ru",
    }

    def route(
        self,
        options: dict,
        allow_experimental: bool = False,
    ) -> RouterResult:
        """Resolve the active ``PromptPolicy`` from request options.

        Args:
            options: ``TranslationRequest.options`` dict.  Recognised keys:
                ``"prompt_policy_id"`` (str) — explicit policy ID override.
                ``"content_kind"`` (str) — ``ContentKind`` value for routing.
            allow_experimental: If False (default), experimental policies are
                blocked and the router falls back to ``sentence_ru`` with a
                warning.  Pass True when the caller has an active trace
                (debug / advanced mode).

        Returns:
            ``RouterResult`` with resolved policy, source, and any warnings.
        """
        warnings: list[str] = []
        fallback_triggered = False
        fallback_reason: str | None = None
        source: str

        explicit_id: str | None = options.get("prompt_policy_id")
        content_kind_raw: str | None = options.get("content_kind")

        # ---- Step 1: explicit prompt_policy_id override --------------------
        if explicit_id is not None:
            try:
                policy = get_policy(explicit_id)
                source = "explicit"
            except KeyError:
                msg = (
                    f"Unknown prompt_policy_id '{explicit_id}'; "
                    f"falling back to '{DEFAULT_POLICY_ID}'"
                )
                warnings.append(msg)
                _logger.warning(msg)
                policy = get_policy(DEFAULT_POLICY_ID)
                source = "fallback"
                fallback_triggered = True
                fallback_reason = f"unknown_policy_id:{explicit_id}"

        # ---- Step 2: content_kind → default profile mapping ----------------
        elif content_kind_raw is not None:
            resolved_default_id = DEFAULT_POLICY_ID
            try:
                ck = ContentKind(content_kind_raw)
                resolved_default_id = self._KIND_TO_POLICY.get(ck, DEFAULT_POLICY_ID)
            except ValueError:
                msg = f"Unknown content_kind '{content_kind_raw}'; using global fallback"
                warnings.append(msg)
                _logger.warning(msg)

            try:
                policy = get_policy(resolved_default_id)
                source = "content_kind"
            except KeyError:
                msg = (
                    f"Policy '{resolved_default_id}' for content_kind "
                    f"'{content_kind_raw}' not registered; falling back"
                )
                warnings.append(msg)
                _logger.warning(msg)
                policy = get_policy(DEFAULT_POLICY_ID)
                source = "fallback"
                fallback_triggered = True
                fallback_reason = f"content_kind_policy_not_found:{resolved_default_id}"

        # ---- Step 3: global default ----------------------------------------
        else:
            policy = get_policy(DEFAULT_POLICY_ID)
            source = "fallback"
            # fallback_triggered stays False: this is the normal default path,
            # not an error recovery.

        # ---- Experimental guard --------------------------------------------
        if policy.experimental and not allow_experimental:
            original_id = policy.policy_id
            msg = (
                f"Policy '{original_id}' is experimental; " f"falling back to '{DEFAULT_POLICY_ID}'"
            )
            warnings.append(msg)
            _logger.warning(
                "experimental_policy_blocked policy_id=%s",
                original_id,
            )
            fallback_triggered = True
            fallback_reason = f"experimental_blocked:{original_id}"
            source = "fallback"
            policy = get_policy(DEFAULT_POLICY_ID)

        _logger.debug(
            "policy_resolved policy_id=%s source=%s",
            policy.policy_id,
            source,
        )

        return RouterResult(
            policy=policy,
            source=source,
            fallback_triggered=fallback_triggered,
            fallback_reason=fallback_reason,
            warnings=warnings,
        )


# ============================================================================
# PPS PATCH-05: build_applied_sampling + EffectivePromptTrace
# ============================================================================


def build_applied_sampling(
    policy: PromptPolicy,
    force_greedy: bool,
    max_n_predict_cap: int | None,
) -> dict:
    """Compute effective model.generate() kwargs for trace/debug metadata.

    Mirrors the logic in ``worker_process._resolve_gen_kwargs()`` but:
    - operates on ``PromptPolicy`` (provider-layer object, already imported)
    - excludes ``eos_token_id`` (model-specific token, worker-owned)
    - intended for ``EffectivePromptTrace.applied_sampling`` only

    The result accurately reflects the actual kwargs minus the stop-token IDs.

    Args:
        policy: Active ``PromptPolicy`` with ``sampling_profile_id``.
        force_greedy: Hardware constraint — True for 7B-GPTQ.
        max_n_predict_cap: Token budget cap — 128 for 7B, 512 for 1.8B.

    Returns:
        Dict with keys matching model.generate() kwargs (no eos_token_id).
    """
    sp = SAMPLING_PROFILES.get(policy.sampling_profile_id)
    if sp is None:
        # Defensive: fall back to default profile values
        sp = SAMPLING_PROFILES["hy_mt_precise_sentence"]

    temperature: float = sp.temperature
    n_predict: int = sp.n_predict

    if max_n_predict_cap is not None:
        n_predict = min(n_predict, max_n_predict_cap)

    if force_greedy or temperature == 0.0:
        return {"max_new_tokens": n_predict, "do_sample": False}

    return {
        "max_new_tokens": n_predict,
        "do_sample": True,
        "top_k": sp.top_k,
        "top_p": sp.top_p,
        "temperature": sp.temperature,
        "repetition_penalty": sp.repetition_penalty,
    }


@dataclass
class EffectivePromptTrace:
    """Full audit record for one translation request.

    Created only when ``trace_id != ""`` (debug / advanced mode).
    Stored in ``meta["prompt_policy"]["trace"]`` of ``TranslationResult``.

    Fields marked None in PATCH-05 first implementation:
        policy_hash, source_text_hash, glossary_hash, context_hash,
        output_tokens_generated, model_quant_id  (completed in PATCH-06+)

    Spec ref: docs/HY_MT_PROMPT_POLICY_SPEC_V3.md §4.9
    """

    # Tracing identity
    trace_id: str  # caller-supplied; UUID recommended

    # Policy snapshot
    policy_id: str
    policy_version: str
    policy_hash: str | None  # PATCH-06: SHA-256 of canonical policy JSON
    template_profile_id: str
    sampling_profile_id: str
    content_kind: ContentKind
    source_lang: str
    target_lang: str

    # Model identity
    model_id: str  # e.g. "tencent/HY-MT1.5-1.8B"
    model_quant_id: str | None  # PATCH-06: "gptq-int4" | "bfloat16" | None
    provider_id: str  # e.g. "local_hymt" | "local_hymt_7b_gptq"

    # Source
    source_text: str
    source_text_hash: str | None  # PATCH-06: SHA-256 of source
    source_length_chars: int

    # Rendered semantic layers (Layers 1–5)
    rendered_role_instruction: str  # Layer 1 (may be empty str)
    rendered_task_instruction: str  # Layer 2
    rendered_output_policy: str  # Layer 3 (may be empty str)
    rendered_glossary_block: str | None  # Layer 4a (None if terminology_mode=off)
    rendered_context_block: str | None  # Layer 4b (None if context_mode=off; PATCH-07)
    rendered_formatting_note: str | None  # Layer 4c (None if not required)
    rendered_user_payload: str  # Layer 5 — placeholder-protected source text
    effective_prompt_preview: str  # Layers 1–5 assembled for UI display

    # Input hashes
    glossary_hash: str | None  # PATCH-06
    context_hash: str | None  # SHA-256 of rendered context block (None if context_mode=off)

    # Applied constraints — what actually went to model.generate()
    applied_sampling: dict  # effective gen_kwargs (without eos_token_id)
    placeholder_tokens_protected: list[str]  # HDLE_PH_N tokens inserted
    placeholder_tokens_restored: int  # count successfully restored

    # Output
    raw_model_output: str  # decoded model output before postprocessing
    translated_text: str  # final translation (after restore + glossary)
    output_length_chars: int
    output_tokens_generated: int | None  # PATCH-06: available if worker reports

    # Performance
    latency_ms: int  # total provider latency
    worker_latency_ms: int | None  # worker inference only

    # Flags
    glossary_applied: bool
    context_applied: bool
    fallback_triggered: bool
    fallback_reason: str | None

    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
