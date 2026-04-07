# HY-MT Prompt Policy System — Production Architecture Spec

HDLE / CAT Desktop · He→Ru · v1.0 · 2026-04-07

> **STATUS:** Draft V2 — sections §1–§6.3 complete; §7–§15 pending merge from V1 spec.
> Full merged spec target: `docs/HY_MT_PROMPT_POLICY_SPEC.md`

---

## 1. Executive Summary

The current HDLE integration of HY-MT operates with a single hardcoded prompt policy embedded in
`worker_process.py`. This is technically functional but architecturally brittle: the policy is
invisible to users, non-auditable, content-kind-agnostic, and impossible to evolve without code
changes.

This specification defines a Prompt Policy System that treats HY-MT as a first-class LLM
translator with observable, profile-switchable, auditable instruction semantics — while keeping
model-specific technical details (special tokens, stop sequences, rendering glue) permanently
hidden from users and untouchable without engineering review.

**The central product claim:** the translation instruction policy is not magic. It is a named,
versioned, editable contract between the user and the model. The technical rendering of that
contract into model-specific tokens is an engineering concern, not a user concern.

**Scope:** He→Ru, desktop HDLE, HY-MT1.5 (1.8B baseline + 7B-GPTQ experimental). Architecture
is model-agnostic by design; it will accommodate future backends.

### Status: current implementation vs. this spec

| Current state | Target state |
|---------------|-------------|
| 1 hardcoded policy in `worker_process.py` | 6+ named, versioned profiles in DB/config |
| System prompt invisible to user | Role/task/output instructions visible in Advanced mode |
| No effective prompt preview | Preview dialog in Basic + Advanced mode |
| No audit trace | `EffectivePromptTrace` logged per translation |
| Content-kind-agnostic | lemma / term / sentence / formatted routing |
| Sampling params hardcoded per model | Named sampling profiles, model-constrained |

---

## 2. Design Principles

### P1 — Separation of concerns: policy vs. rendering

The semantic instruction policy (what you say to the model) is separated from the technical
rendering (how you encode it for a specific model). Users interact with policy. Engineers own
rendering.

```
[User] → PromptPolicy → PolicyRenderer → TechnicalPrompt → [Model]
                              ↑
                    hidden, model-specific
```

### P2 — Observability by default

Every translation in Advanced or Debug mode shows an effective prompt preview: the logical
assembly of role + task + output policy + glossary + context + source. This is the semantic
view, not the raw token-level view.

### P3 — Content-kind specialization is non-negotiable

A lemma, a technical term, and a sentence segment require fundamentally different instruction
profiles in a commercial HDLE system:

- A **lemma** needs canonical dictionary form output; context injection would distort the result.
- A **term** may require strict glossary enforcement with no creative deviation.
- A **sentence** needs meaning preservation with placeholder safety.
- A **formatted segment** requires strict structural fidelity over fluency.

Collapsing these into one universal prompt is a category error that produces inconsistent quality
across the dictionary/CAT workflow.

### P4 — The technical wrapper is permanently hidden

Model-specific special tokens (`<|startoftext|>`, `<｜hy_User｜>`, stop sequences, etc.) are
never exposed in any user-facing UI mode, including Debug mode. Debug mode shows the rendered
logical sections, not raw model bytes. The mapping from policy to tokens is a worker-layer
engineering invariant.

### P5 — Placeholder and formatting protection are invariants, not policies

`PlaceholderMode.protect_known_placeholders` is the minimum floor; it cannot be turned off in
any production profile. The system may offer a `strict_protect_all_tokens` escalation, but never
a disable.

### P6 — Sampling profiles are model-constrained, not freely user-editable

The 7B-GPTQ model has a hardware-derived constraint: greedy decoding only (`do_sample=False`),
`max_new_tokens ≤ 128`. Sampling profiles reference these constraints at the model level. A
profile that requests `temperature=0.7` on 7B-GPTQ is silently overridden to greedy with a
logged warning — never allowed to cause a timeout.

### P7 — Version and hash every policy

Every policy object carries a `version` string and a computed `policy_hash`. Every translation
logs the active `policy_hash` + `glossary_hash` + `context_hash`. This enables full reproduction
of any translation result.

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        HDLE APPLICATION                         │
│                                                                 │
│  ┌──────────────┐    ┌─────────────────────────────────────┐   │
│  │   UI Layer   │    │         Policy Layer                 │   │
│  │              │    │                                      │   │
│  │ ProfileChip  │───▶│  PromptPolicyRegistry                │   │
│  │ PolicyPanel  │    │    - list_profiles()                 │   │
│  │ PreviewDialog│    │    - get_policy(id)                  │   │
│  │ AuditPanel   │◀───│    - validate_policy(p)             │   │
│  └──────────────┘    └────────────┬────────────────────────┘   │
│                                   │                             │
│                      ┌────────────▼────────────────────────┐   │
│                      │      PolicyRenderer                  │   │
│                      │                                      │   │
│                      │  render_effective_preview(...)       │   │
│                      │  render_glossary_block(...)          │   │
│                      │  render_context_block(...)           │   │
│                      │  emit_trace(...)                     │   │
│                      └────────────┬────────────────────────┘   │
│                                   │                             │
│                      ┌────────────▼────────────────────────┐   │
│                      │   TranslationRouter                  │   │
│                      │                                      │   │
│                      │  route(content_kind, request)        │   │
│                      │  select_profile(...)                 │   │
│                      │  apply_fallback_rules(...)           │   │
│                      └────────────┬────────────────────────┘   │
└──────────────────────────────────┬──────────────────────────────┘
                                   │ TranslationRequest + policy_id
                    ┌──────────────▼──────────────────┐
                    │   LocalHYMTProvider              │
                    │                                  │
                    │  translate(request)              │
                    │    → apply placeholder protect   │
                    │    → build user_content          │
                    │    → call worker                 │
                    │    → restore placeholders        │
                    │    → apply_glossary postprocess  │
                    └──────────────┬──────────────────┘
                                   │ WorkerRequest
                    ┌──────────────▼──────────────────┐
                    │   worker_process.py              │
                    │   (subprocess, IPC)              │
                    │                                  │
                    │  _translate_transformers_causal()│
                    │                                  │
                    │  HIDDEN LAYER:                   │
                    │  - model-specific tokens         │
                    │  - stop sequences                │
                    │  - template wrapping             │
                    │  - sanitation / truncation       │
                    └──────────────────────────────────┘
```

**Key architectural boundary:** everything above `LocalHYMTProvider` is policy-visible. Everything
inside the worker subprocess is permanently hidden.

`LocalHYMTProvider` receives a `policy_id` (or resolved `PromptPolicy` object) alongside the
`TranslationRequest`. It maps the policy's semantic layers into `user_content` (the string passed
to the worker) and IPC `WorkerRequest`. The worker only ever sees user-content text — never raw
policy objects.

---

## 4. Domain Model

### 4.1 ContentKind

```python
class ContentKind(str, Enum):
    LEMMA                 = "lemma"
    TERM                  = "term"
    SENTENCE              = "sentence"
    SENTENCE_WITH_CONTEXT = "sentence_with_context"
    SENTENCE_FORMATTED    = "sentence_formatted"
    UI_STRING             = "ui_string"
    BATCH_MIXED           = "batch_mixed"
```

| Kind | Distinguishing property | Incorrect profile consequence |
|------|------------------------|-------------------------------|
| `lemma` | Dictionary canonical form expected | Sampling adds inflection variants |
| `term` | Technical precision required | Glossary miss = terminology inconsistency |
| `sentence` | Natural fluency + placeholder safety | Too strict = stilted output |
| `sentence_with_context` | Disambiguation via adjacent segments | Context injected where not needed → distortion |
| `sentence_formatted` | Structural preservation overrides fluency | Dropped placeholders = broken downstream |
| `ui_string` | Extremely short, UI-context bound | Regular sentence profile = verbose output |
| `batch_mixed` | Heterogeneous; requires per-item routing | Single policy = systematic mismatch |

### 4.2 TerminologyMode

```python
class TerminologyMode(str, Enum):
    OFF                 = "off"
    SOFT_GLOSSARY       = "soft_glossary"
    STRICT_GLOSSARY     = "strict_glossary"
    APPROVED_TERMS_ONLY = "approved_terms_only"
```

| Mode | Behavior |
|------|----------|
| `off` | No glossary injected. No postprocess. |
| `soft_glossary` | Glossary injected in prompt as suggestion. `apply_glossary()` postprocess with tolerance. |
| `strict_glossary` | Glossary injected as mandatory mapping. Postprocess enforces exact term replacement. |
| `approved_terms_only` | Only DB-approved TM pairs used. Unknown terms: no substitution. |

### 4.3 ContextMode

```python
class ContextMode(str, Enum):
    OFF                   = "off"
    PREVIOUS_SENTENCE     = "previous_sentence"
    SURROUNDING_SENTENCES = "surrounding_sentences"
    PARAGRAPH             = "paragraph"
    CUSTOM_CONTEXT_BLOCK  = "custom_context_block"
```

### 4.4 FormattingMode

```python
class FormattingMode(str, Enum):
    PLAIN_TEXT             = "plain_text"
    PRESERVE_NUMBERS_NAMES = "preserve_numbers_names"
    PRESERVE_PLACEHOLDERS  = "preserve_placeholders"
    PRESERVE_INLINE_TAGS   = "preserve_inline_tags"
    PRESERVE_FULL_MARKUP   = "preserve_full_markup"
```

> Note: `PRESERVE_FULL_MARKUP` triggers `PlaceholderMode.strict_protect_all_tokens` automatically.

### 4.5 PlaceholderMode

```python
class PlaceholderMode(str, Enum):
    PROTECT_KNOWN_PLACEHOLDERS = "protect_known_placeholders"  # minimum floor
    STRICT_PROTECT_ALL_TOKENS  = "strict_protect_all_tokens"   # escalated
    RESTORE_AFTER_GENERATION   = "restore_after_generation"    # always true
```

> `OFF` is not a valid production value. The system rejects any policy with `placeholder_mode=off`.

### 4.6 PromptPolicy

```python
@dataclass
class PromptPolicy:
    # Identity
    policy_id: str                    # e.g. "sentence_ru_context_v1"
    name: str                         # "He→Ru Context-Aware Sentence"
    description: str
    enabled: bool
    version: str                      # semver: "1.0.0"
    policy_hash: str                  # SHA-256 of canonical JSON repr (computed)

    # Routing
    content_kind: ContentKind
    source_lang: str                  # ISO 639-1: "he"
    target_lang: str                  # ISO 639-1: "ru"

    # Semantic layers (user-visible in Advanced/Debug mode)
    role_instruction: str
    task_instruction: str
    output_policy: str

    # Modes
    terminology_mode: TerminologyMode
    context_mode: ContextMode
    formatting_mode: FormattingMode
    placeholder_mode: PlaceholderMode

    # Strategy selectors
    glossary_strategy: str            # "top_ranked_relevant" | "exact_match_first"
    context_strategy: str             # "nearest_N_segments" | "paragraph_boundary"

    # Linked profiles
    sampling_profile_id: str
    template_profile_id: str          # internal; maps to worker template variant

    # UX permissions
    allow_user_edit_role: bool        # True for advanced/power user
    allow_user_edit_task: bool
    allow_user_edit_output_policy: bool

    # Limits
    max_input_chars: int | None       # None = no limit beyond model context
    max_context_items: int | None
    max_glossary_items: int | None

    # Metadata
    is_builtin: bool                  # True = shipped with product; not deletable
    is_custom: bool                   # True = user-created copy
    created_at: datetime
    updated_at: datetime
```

### 4.7 SamplingProfile

```python
@dataclass
class SamplingProfile:
    sampling_profile_id: str
    name: str
    description: str

    # Core sampling (may be overridden by model-level constraints)
    temperature: float         # 0.0 = greedy; > 0.0 = stochastic
    top_k: int                 # 0 = disabled
    top_p: float               # 1.0 = disabled
    min_p: float               # 0.0 = disabled
    typical_p: float           # 1.0 = disabled
    repetition_penalty: float  # 1.0 = disabled
    repeat_last_n: int         # context window for penalty
    frequency_penalty: float
    presence_penalty: float
    mirostat_mode: int         # 0 = off; 1 = v1; 2 = v2
    seed: int                  # -1 = random

    # Length
    n_predict: int             # max new tokens

    # Constraint flags (applied at provider layer, not user-editable)
    force_greedy: bool = False            # True for 7B-GPTQ (hardware constraint)
    max_n_predict_cap: int | None = None  # hard cap; overrides n_predict if lower
```

> **Important:** `force_greedy` and `max_n_predict_cap` are set by the `TemplateProfile` based
> on model capabilities, not by the policy author. A `SamplingProfile` specifying
> `temperature=0.7` on a model where `force_greedy=True` produces a logged warning and is
> silently clamped to greedy.

### 4.8 TemplateProfile

```python
@dataclass
class TemplateProfile:
    template_profile_id: str
    name: str

    # Which semantic sections to render
    use_role_instruction: bool    = True
    use_task_instruction: bool    = True
    use_output_policy: bool       = True
    use_context_block: bool       = False
    use_glossary_block: bool      = False
    use_formatting_block: bool    = False
    use_placeholder_note: bool    = False  # explicit reminder to model

    # Model-level hardware constraints (set per backend, not per policy)
    target_backend: str           = "transformers_causal"
    force_greedy: bool            = False
    max_n_predict_cap: int | None = None

    # Internal rendering variant
    # "standard" | "glossary_heavy" | "context_aware" | "formatted_strict"
    render_variant: str           = "standard"
```

Built-in template profiles:

| ID | render_variant | use_context | use_glossary | force_greedy | cap |
|----|---------------|-------------|--------------|--------------|-----|
| `hy_mt_standard_observed` | standard | ❌ | soft | ❌ | 512 |
| `hy_mt_glossary_observed` | glossary_heavy | ❌ | strict | ❌ | 512 |
| `hy_mt_context_observed` | context_aware | ✅ | soft | ❌ | 512 |
| `hy_mt_formatted_observed` | formatted_strict | ❌ | soft | ❌ | 512 |
| `hy_mt_7b_standard` | standard | ❌ | soft | ✅ | 128 |
| `hy_mt_7b_glossary` | glossary_heavy | ❌ | strict | ✅ | 128 |

### 4.9 EffectivePromptTrace

```python
@dataclass
class EffectivePromptTrace:
    trace_id: str                         # UUID

    # Policy snapshot
    policy_id: str
    policy_version: str
    policy_hash: str
    template_profile_id: str
    sampling_profile_id: str
    content_kind: ContentKind
    source_lang: str
    target_lang: str

    # Model identity
    model_id: str                         # "tencent/HY-MT1.5-1.8B"
    model_quant_id: str | None            # "gptq-int4" | "bfloat16" | None
    provider_id: str                      # "local_hymt" | "local_hymt_7b_gptq"

    # Source
    source_text: str
    source_text_hash: str
    source_length_chars: int

    # Rendered sections (semantic view, not token-level)
    rendered_role_instruction: str
    rendered_task_instruction: str
    rendered_output_policy: str
    rendered_glossary_block: str | None
    rendered_context_block: str | None
    rendered_formatting_note: str | None
    rendered_user_payload: str            # full user content string sent to worker
    effective_prompt_preview: str         # visible-layer assembly

    # Input hashes
    glossary_hash: str | None
    context_hash: str | None

    # Applied constraints
    applied_sampling: dict                # actual values sent to model
    placeholder_tokens_protected: list[str]
    placeholder_tokens_restored: int

    # Output
    translated_text: str
    output_length_chars: int
    output_tokens_generated: int | None   # if available from worker

    # Performance
    latency_ms: int
    worker_latency_ms: int | None

    # Flags
    glossary_applied: bool
    context_applied: bool
    fallback_triggered: bool
    fallback_reason: str | None

    created_at: datetime
```

---

## 5. Policy Layering

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 0: Technical Wrapper                    [HIDDEN FOREVER]  │
│                                                                  │
│  Model-specific tokens, stop sequences, IPC serialization,       │
│  BOS/EOS placement, rendering glue.                              │
│  Owner: worker_process.py                                        │
│  Examples: <|startoftext|>, <｜hy_User｜>, [127960]             │
├─────────────────────────────────────────────────────────────────┤
│  Layer 1: Role Instruction              [VISIBLE: Advanced mode] │
│                                                                  │
│  Who the model is in the current operational mode.               │
│  Examples:                                                       │
│    "You are a lexical translation engine for dictionary entries."│
│    "You are a terminology-controlled translation engine."        │
│  Policy field: role_instruction                                  │
│  User-editable: allow_user_edit_role                             │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2: Task Instruction              [VISIBLE: Advanced mode] │
│                                                                  │
│  What to do with this specific input.                            │
│  Examples:                                                       │
│    "Translate the following Hebrew lemma into its canonical..."  │
│    "Translate the target segment using context for               │
│     disambiguation only."                                        │
│  Policy field: task_instruction                                  │
│  User-editable: allow_user_edit_task                             │
├─────────────────────────────────────────────────────────────────┤
│  Layer 3: Output Policy                 [VISIBLE: Advanced mode] │
│                                                                  │
│  What the output must look like.                                 │
│  Examples:                                                       │
│    "Output only the canonical Russian dictionary form."          │
│    "Preserve all placeholder tokens exactly as-is."              │
│  Policy field: output_policy                                     │
│  User-editable: allow_user_edit_output_policy                    │
├─────────────────────────────────────────────────────────────────┤
│  Layer 4: Constraints                   [VISIBLE: Advanced mode] │
│                                                                  │
│  Structured constraint blocks appended when applicable.          │
│  Sub-layers:                                                     │
│    4a. Glossary block (if terminology_mode != off)               │
│    4b. Context block (if context_mode != off)                    │
│    4c. Formatting note (if formatting_mode requires explicit     │
│        instruction beyond output_policy)                         │
│    4d. Placeholder note (if use_placeholder_note in template)    │
│  These are rendered by PolicyRenderer, not hand-written.         │
├─────────────────────────────────────────────────────────────────┤
│  Layer 5: User Payload                   [VISIBLE: Basic mode]   │
│                                                                  │
│  The actual source text — after placeholder protection,          │
│  normalization, and optional context/glossary injection.          │
│  This is what the user recognizes as "their content."            │
└─────────────────────────────────────────────────────────────────┘
```

**Effective prompt preview** (shown in UI) = Layers 1–5, rendered as readable labelled sections.
**Technical prompt** (sent to model) = Layer 0 wrapping all of the above as a model-specific token sequence.

---

## 6. UI/UX Surface

### 6.1 Basic Mode

Audience: translators, reviewers, end users.

```
┌─────────────────────────────────────────────────────┐
│  Translation Profile                                 │
│  ┌─────────────────────────────────────────────────┐│
│  │ [Lemma] [Term] [Term+Gloss] [Sentence] [Context]││
│  │ [Formatted]                     ← profile chips ││
│  └─────────────────────────────────────────────────┘│
│                                                      │
│  ☑ Use glossary    ☑ Use context    ☑ Preserve format│
│                                                      │
│  Sampling preset: [Precise Short ▾]                  │
│                                                      │
│  [▶ Effective Prompt Preview]                        │
└─────────────────────────────────────────────────────┘
```

Fields visible:
- Profile chip selector (content_kind quick-switch)
- Use glossary toggle (`terminology_mode`: off ↔ `soft_glossary`)
- Use context toggle (`context_mode`: off ↔ `surrounding_sentences`)
- Preserve formatting toggle (`formatting_mode` escalation)
- Sampling preset selector
- Effective Prompt Preview button (shows read-only preview)

### 6.2 Advanced Mode

Audience: power users, linguists, project managers.

```
┌─────────────────────────────────────────────────────────┐
│  Prompt Policy: [sentence_ru_context_v1 ▾]  [Edit] [+] │
│                                                          │
│  Role Instruction:                                       │
│  ┌───────────────────────────────────────────────────┐  │
│  │ You are a context-aware Hebrew-to-Russian         │  │
│  │ translation engine.                    [↺ Reset]  │  │
│  └───────────────────────────────────────────────────┘  │
│                                                          │
│  Task Instruction:                                       │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Translate the target segment into Russian using   │  │
│  │ context only for disambiguation.      [↺ Reset]   │  │
│  └───────────────────────────────────────────────────┘  │
│                                                          │
│  Output Policy:                                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Output only the Russian translation. Do not       │  │
│  │ translate context. No explanations.   [↺ Reset]   │  │
│  └───────────────────────────────────────────────────┘  │
│                                                          │
│  Terminology Mode: [Soft Glossary ▾]                     │
│  Context Mode:     [Surrounding Sentences ▾]             │
│  Formatting Mode:  [Preserve Numbers & Names ▾]          │
│  Placeholder Mode: [Protect Known ▾]                     │
│  Sampling Profile: [hy_mt_precise_sentence ▾]            │
│                                                          │
│  [Preview Effective Prompt]  [Save as Custom]  [Export] │
└─────────────────────────────────────────────────────────┘
```

Fields visible: all Basic fields + role/task/output text editors (when `allow_user_edit_*=True`)
+ all mode selectors + sampling profile selector.

### 6.3 Debug / Audit Mode

Audience: engineers, QA, release validation.

```
┌─────────────────────────────────────────────────────────────────┐
│  Effective Prompt Trace                                          │
│                                                                  │
│  ┌── [Role] ──────────────────────────────────────────────────┐ │
│  │ You are a context-aware Hebrew-to-Russian translation...   │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌── [Task] ──────────────────────────────────────────────────┐ │
│  │ Translate the target segment...                            │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌── [Output Policy] ─────────────────────────────────────────┐ │
│  │ Output only the Russian translation...                     │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌── [Glossary Block] ────────────────────────────────────────┐ │
│  │ Terminology: מחשב → компьютер, תוכנה → программное обесп. │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌── [Context Block] ─────────────────────────────────────────┐ │
│  │ Context: [prev] הוא פתח את המחשב. [next] הוא שמר אותו ... │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌── [Source] ────────────────────────────────────────────────┐ │
│  │ הוא הפעיל את התוכנה.                                       │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ── Metadata ─────────────────────────────────────────────────  │
│  Policy:    sentence_ru_context_v1  (hash: a3f7c...)            │
│  Model:     tencent/HY-MT1.5-1.8B  (bfloat16)                  │
│  Provider:  local_hymt                                           │
│  Sampling:  hy_mt_precise_sentence                               │
│    n_predict=512  temp=0.7  top_k=20  top_p=0.6  rep_pen=1.05  │
│  Glossary:  injected=2  applied=2  (hash: b9c2a...)             │
│  Context:   items=2  (hash: d4e1f...)                            │
│  Latency:   worker=4 320 ms  total=4 480 ms                     │
│  Placeholders: protected=2  restored=2  missing=0               │
│                                                                  │
│  ── Output ───────────────────────────────────────────────────  │
│  Raw:   Он активировал программное обеспечение.                 │
│  Final: Он активировал программное обеспечение.                 │
│                                                                  │
│  [Copy Trace JSON]  [Export to File]  [Compare with Previous]   │
└─────────────────────────────────────────────────────────────────┘
```

Debug mode fields (in addition to Advanced):
- Full effective prompt, colour-coded by layer, each in a labelled collapsible box
- Metadata panel: `policy_hash`, `model_quant_id`, sampling values actually sent, glossary hash,
  context hash, latency breakdown, placeholder accounting
- Output panel: raw model output vs final (post-process) side-by-side
- Actions: Copy Trace JSON, Export to File, Compare with Previous

> **Performance note.** `EffectivePromptTrace` is allocated only when `trace_id != ""` or debug
> mode is active. It is never instantiated on the normal production path. Debug mode warns if
> batch size > 200 (trace memory can reach ~10 MB for long sessions).

---

## 7–15  (pending merge)

> Sections §7 (Production Profiles), §8 (Rendering Rules), §9 (Sampling Profiles),
> §10 (Routing / Fallback), §11 (Observability), §12 (Examples), §13 (Defaults),
> §14 (Risks), §15 (DoD + Patch Series) are available in
> `docs/HY_MT_PROMPT_POLICY_SPEC.md` (V1) and will be merged into this document.

Key deltas between V2 (this file) and V1:

| Area | V1 | V2 (this file) |
|------|----|----------------|
| `TerminologyMode` | 4 values: OFF/PROMPT/POST/BOTH | 4 values: OFF/SOFT/STRICT/APPROVED (richer semantics) |
| `TemplateProfile` | Simple per-model selection | 6 named built-in profiles with capability table |
| `EffectivePromptTrace` | Basic fields | Extended: `policy_hash`, `glossary_hash`, `context_hash`, `model_quant_id`, `output_tokens_generated` |
| Architecture | Provider-centric diagram | Adds `PromptPolicyRegistry`, `PolicyRenderer`, `TranslationRouter` components |
| UI mockups | Text description only | Full ASCII mockups for all 3 modes |
| `ContentKind` rationale | Not documented | Table with "incorrect profile consequence" column |
| `SamplingProfile` | 3 named profiles | Full field set with `force_greedy`, `max_n_predict_cap`, `mirostat_mode` |
