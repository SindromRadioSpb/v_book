"""Prompt Policy System for HY-MT local translation providers.

Defines the domain model (enums, dataclasses) and module-level registries for
PromptPolicy, SamplingProfile, and TemplateProfile objects.

All registries are populated at import time with no I/O.
No filesystem reads, no database queries. Pure Python data.

Refs: docs/HY_MT_PROMPT_POLICY_SPEC_V3.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

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
# Startup validation  (runs at import time, no I/O)
# ============================================================================


def _validate_registry() -> None:
    """Validate all built-in registry entries.

    Called once at module import. Raises on any misconfiguration so that
    errors are surfaced immediately rather than at the first translation request.

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


_validate_registry()
