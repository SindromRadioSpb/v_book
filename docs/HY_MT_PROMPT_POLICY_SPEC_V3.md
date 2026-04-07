# HY-MT Prompt Policy System — Production Architecture Spec

HDLE / CAT Desktop · He→Ru · v1.0 · 2026-04-07

> **Single source of truth.** This V3 document supersedes both
> `HY_MT_PROMPT_POLICY_SPEC.md` (V1) and `HY_MT_PROMPT_POLICY_SPEC_V2_DRAFT.md` (V2).
> V1 and V2 are retained in `docs/` as history; do not edit them.

---

## 1. Executive Summary

The current HDLE integration of HY-MT operates with a single hardcoded prompt policy embedded
in `worker_process.py`. This is technically functional but architecturally brittle: the policy
is invisible to users, non-auditable, content-kind-agnostic, and impossible to evolve without
code changes.

This specification defines a Prompt Policy System (PPS) that treats HY-MT as a first-class
LLM translator with observable, profile-switchable, auditable instruction semantics — while
keeping model-specific technical details (special tokens, stop sequences, rendering glue)
permanently hidden from users and untouchable without engineering review.

**The central product claim:** the translation instruction policy is not magic. It is a named,
versioned, editable contract between the user and the model. The technical rendering of that
contract into model-specific tokens is an engineering concern, not a user concern.

**Scope:** He→Ru, desktop HDLE, HY-MT1.5 (1.8B baseline + 7B-GPTQ experimental). Architecture
is model-agnostic by design; it will accommodate future backends.

### Status: current implementation vs. this spec

| Current state | Target state |
|---------------|-------------|
| 1 hardcoded policy in `worker_process.py` | 6+ named, versioned profiles in module-level registry |
| System prompt invisible to user | Role / task / output instructions visible in Advanced mode |
| No effective prompt preview | Preview dialog in Basic + Advanced + Debug modes |
| No audit trace | `EffectivePromptTrace` logged per translation when trace active |
| Content-kind-agnostic | lemma / term / sentence / formatted routing |
| Sampling params hardcoded per model | Named sampling profiles, model-constraint-aware |

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

### P3 — Content-kind specialisation is non-negotiable

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
a disable. The system rejects any policy with `placeholder_mode = off`.

### P6 — Sampling profiles are model-constrained, not freely user-editable

The 7B-GPTQ model has a hardware-derived constraint: greedy decoding only (`do_sample=False`),
`max_new_tokens ≤ 128`. A sampling profile that requests `temperature=0.7` on a
`force_greedy=True` template profile is silently clamped to greedy with a logged warning — never
allowed to cause a timeout.

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
│                      │  render_user_content(policy, ...)    │   │
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
                    │    → resolve policy              │
                    │    → protect placeholders        │
                    │    → fetch glossary terms        │
                    │    → PolicyRenderer.render_user_content()
                    │    → worker.translate()          │
                    │    → restore placeholders        │
                    │    → apply_glossary postprocess  │
                    │    → emit_trace (if active)      │
                    └──────────────┬──────────────────┘
                                   │ WorkerRequest.text = user_content
                    ┌──────────────▼──────────────────┐
                    │   worker_process.py              │
                    │   (subprocess, IPC)              │
                    │                                  │
                    │  _translate_transformers_causal()│
                    │                                  │
                    │  HIDDEN LAYER 0:                 │
                    │  - model-specific tokens         │
                    │  - system prompt                 │
                    │  - stop sequences                │
                    │  - template wrapping             │
                    │  - EOS / boundary truncation     │
                    └──────────────────────────────────┘
```

**Key architectural boundary:** everything above `LocalHYMTProvider` is policy-visible.
Everything inside the worker subprocess is permanently hidden.

`LocalHYMTProvider` receives a `policy_id` (resolved to a `PromptPolicy` object by the router)
alongside the `TranslationRequest`. It calls `PolicyRenderer` to construct `user_content` (the
string sent to the worker as `WorkerRequest.text`). The worker only ever sees user-content text
— never raw policy objects or model-specific tokens assembled at the provider level.

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

> **Migration note.** V1 used `BOTH / PROMPT / POST / OFF`. V3 canonical vocabulary is above.
> `BOTH` → `SOFT_GLOSSARY` (default). `PROMPT` → `SOFT_GLOSSARY` (with strict postprocess
> disabled). `BOTH` for strict enforcement → `STRICT_GLOSSARY`.

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
    RESTORE_AFTER_GENERATION   = "restore_after_generation"    # always active
```

`OFF` is not a valid production value. The system rejects any policy with `placeholder_mode=off`
at startup validation.

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
    policy_hash: str                  # SHA-256 of canonical JSON repr (computed at load)

    # Routing
    content_kind: ContentKind
    source_lang: str                  # ISO 639-1: "he"
    target_lang: str                  # ISO 639-1: "ru"

    # Semantic layers (user-visible in Advanced/Debug mode)
    role_instruction: str             # Layer 1: who the model is
    task_instruction: str             # Layer 2: what to do
    output_policy: str                # Layer 3: what the output must look like

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

    # UX permissions (which layers users may edit in Advanced mode)
    allow_user_edit_role: bool
    allow_user_edit_task: bool
    allow_user_edit_output_policy: bool

    # Limits (None = use profile or model defaults)
    max_input_chars: int | None
    max_context_items: int | None
    max_glossary_items: int | None    # default: 20 (current _fetch_glossary_terms limit)

    # Metadata
    is_builtin: bool                  # True = shipped with product; not deletable by user
    is_custom: bool                   # True = user-created copy of a built-in
    experimental: bool                # True = not shown in Basic mode
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

    # Core sampling (expresses user/author intent; may be overridden by model constraints)
    temperature: float         # 0.0 = greedy; > 0.0 = stochastic
    top_k: int                 # 0 = disabled
    top_p: float               # 1.0 = disabled
    min_p: float               # 0.0 = disabled
    typical_p: float           # 1.0 = disabled
    repetition_penalty: float  # 1.0 = disabled
    repeat_last_n: int         # context window for repetition penalty
    frequency_penalty: float   # 0.0 = disabled
    presence_penalty: float    # 0.0 = disabled
    mirostat_mode: int         # 0 = off; 1 = v1; 2 = v2
    seed: int                  # -1 = random

    # Length
    n_predict: int             # max new tokens (may be capped by max_n_predict_cap)

    # Model-layer constraint flags
    # These are NOT set by the policy author. They are set by TemplateProfile and
    # applied at the provider layer before dispatching to the worker.
    force_greedy: bool = False            # True for 7B-GPTQ (hardware constraint)
    max_n_predict_cap: int | None = None  # hard cap; overrides n_predict if lower
```

> **Constraint resolution order:**
> 1. `SamplingProfile.temperature`, `top_k`, etc. — author's intent.
> 2. `TemplateProfile.force_greedy` — if True, `temperature=0`, `do_sample=False`.
> 3. `TemplateProfile.max_n_predict_cap` — if set, `n_predict = min(n_predict, cap)`.
> 4. Result: `applied_sampling` dict logged in `EffectivePromptTrace`.

### 4.8 TemplateProfile

```python
@dataclass
class TemplateProfile:
    template_profile_id: str
    name: str

    # Which semantic sections to render in user_content
    use_role_instruction: bool    = True
    use_task_instruction: bool    = True
    use_output_policy: bool       = True
    use_context_block: bool       = False
    use_glossary_block: bool      = False
    use_formatting_block: bool    = False
    use_placeholder_note: bool    = False  # explicit reminder in user turn

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
    trace_id: str                         # UUID; absent when tracing not active

    # Policy snapshot
    policy_id: str
    policy_version: str
    policy_hash: str                      # SHA-256 of canonical policy JSON
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
    source_text_hash: str                 # SHA-256 of source (for deduplication)
    source_length_chars: int

    # Rendered sections — semantic view, labelled by policy layer
    rendered_role_instruction: str        # Layer 1 (may be empty)
    rendered_task_instruction: str        # Layer 2
    rendered_output_policy: str           # Layer 3 (may be empty)
    rendered_glossary_block: str | None   # Layer 4a (None if terminology_mode=off)
    rendered_context_block: str | None    # Layer 4b (None if context_mode=off)
    rendered_formatting_note: str | None  # Layer 4c (None if not required)
    rendered_user_payload: str            # Layer 5 (placeholder-protected source)
    effective_prompt_preview: str         # Layers 1–5 assembled: shown in UI

    # Input hashes
    glossary_hash: str | None             # SHA-256 of injected glossary block
    context_hash: str | None              # SHA-256 of context block

    # Applied constraints (what actually went to model.generate())
    applied_sampling: dict                # final resolved gen_kwargs
    placeholder_tokens_protected: list[str]
    placeholder_tokens_restored: int

    # Output
    raw_model_output: str                 # decoded output before post-process
    translated_text: str                  # final translation (after EOS strip + restore)
    output_length_chars: int
    output_tokens_generated: int | None   # available if worker reports it

    # Performance
    latency_ms: int                       # total provider latency
    worker_latency_ms: int | None         # worker inference only

    # Flags
    glossary_applied: bool
    context_applied: bool
    fallback_triggered: bool
    fallback_reason: str | None

    created_at: datetime
```

> **First implementation scope (PATCH-01..05):** `policy_hash`, `glossary_hash`,
> `context_hash`, `source_text_hash`, `output_tokens_generated`, and `model_quant_id`
> may be `None` in the first implementation. The remaining fields are required from PATCH-05.
> See §15.6 for phased DoD.

---

## 5. Policy Layering

The prompt sent to the model is assembled from six strictly ordered layers.
Layers are additive: each builds on the layer below.
Only Layer 0 is assembled in the worker process; Layers 1–5 are assembled by
`PolicyRenderer` in the provider process and arrive at the worker as `WorkerRequest.text`.

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 0: Technical Wrapper                    [HIDDEN FOREVER]  │
│                                                                  │
│  Model-specific tokens, stop sequences, IPC serialisation,       │
│  BOS/EOS placement, system prompt, rendering glue.               │
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
│  Structured constraint blocks, rendered by PolicyRenderer.       │
│  Sub-layers:                                                     │
│    4a. Glossary block (if terminology_mode != off)               │
│    4b. Context block (if context_mode != off)                    │
│    4c. Formatting note (if FormattingMode or use_placeholder_note│
│        in TemplateProfile requires an explicit instruction)      │
│  Not hand-written by users; generated from mode selections.      │
├─────────────────────────────────────────────────────────────────┤
│  Layer 5: User Payload                   [VISIBLE: Basic mode]   │
│                                                                  │
│  The actual source text — after placeholder protection,          │
│  normalisation, and RTL-mark stripping.                          │
│  This is what the user recognises as "their content."            │
└─────────────────────────────────────────────────────────────────┘
```

**Effective prompt preview** (shown in UI) = Layers 1–5, rendered as readable labelled sections.
**Technical prompt** (sent to model) = Layer 0 wrapping all of the above as a model-specific
token sequence.

### Layer 0 — Technical Wrapper (detail)

**Owner:** `worker_process._translate_transformers_causal`
**Visibility:** Never shown to users. Available in `EffectivePromptTrace` fields for audit only
when debug mode is active.
**Contents:**
- Model-family-specific BOS/SEP/TURN_END tokens (selected by `is_gptq`)
- `_HYMT_SYSTEM_PROMPT` — the global system prompt (persona + placeholder rule + format contract)
- `role_instruction` from the active policy, appended to system prompt before SEP (passed via
  sentinel — see §8.4)

**Inviolable rule:** The placeholder protection instruction ("Preserve all placeholder tokens
HDLE_PH_N exactly as-is") lives in the system prompt and cannot be suppressed or overridden by
any policy, user setting, or debug option.

### Layer 4 — Runtime Constraints (sub-layer detail)

**4a Glossary block** — rendered only if `terminology_mode != OFF`:
```
Terminology: מחשב → компьютер, קובץ → файл.
```

**4b Context block** — rendered only if `context_mode != OFF`:
```
Context:
[Previous] {prev_segment}
[Next] {next_segment}
```

**4c Formatting note** — rendered if `use_placeholder_note=True` in TemplateProfile, or if
`FormattingMode = PRESERVE_FULL_MARKUP`:
```
All placeholder tokens (HDLE_PH_1, HDLE_PH_2, …) must appear in your
output in the same relative order.
```

---

## 6. UI/UX Surface

Three UI modes, orthogonal to provider selection.

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
│  Sampling preset: [Precise Sentence ▾]               │
│                                                      │
│  [▶ Effective Prompt Preview]                        │
└─────────────────────────────────────────────────────┘
```

Fields visible:
- Profile chip selector (`content_kind` quick-switch)
- Use glossary toggle (`terminology_mode`: off ↔ `soft_glossary`)
- Use context toggle (`context_mode`: off ↔ `surrounding_sentences`)
- Preserve formatting toggle (`formatting_mode` escalation)
- Sampling preset selector
- Effective Prompt Preview button (read-only modal, shows Layers 1–5)

Profiles with `experimental=True` are not shown in Basic mode. If the active profile is
experimental, a fallback chip is shown and a warning is displayed.

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
│  Task Instruction:                                       │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Translate the target segment into Russian using   │  │
│  │ context only for disambiguation.      [↺ Reset]   │  │
│  └───────────────────────────────────────────────────┘  │
│  Output Policy:                                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Output only the Russian translation. Do not       │  │
│  │ translate context. No explanations.   [↺ Reset]   │  │
│  └───────────────────────────────────────────────────┘  │
│  Terminology Mode: [Soft Glossary ▾]                     │
│  Context Mode:     [Surrounding Sentences ▾]             │
│  Formatting Mode:  [Preserve Numbers & Names ▾]          │
│  Placeholder Mode: [Protect Known ▾]                     │
│  Sampling Profile: [Precise Sentence ▾]                  │
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
│  ┌── [Role Instruction] ──────────────────────────────────────┐ │
│  │ You are a context-aware Hebrew-to-Russian translation...   │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌── [Task Instruction] ──────────────────────────────────────┐ │
│  │ Translate the target segment...                            │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌── [Output Policy] ─────────────────────────────────────────┐ │
│  │ Output only the Russian translation...                     │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌── [Glossary Block — Layer 4a] ─────────────────────────────┐ │
│  │ Terminology: מחשב → компьютер, תוכנה → программное обесп. │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌── [Context Block — Layer 4b] ──────────────────────────────┐ │
│  │ Context: [prev] הוא פתח את המחשב. [next] הוא שמר אותו ... │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌── [Source — Layer 5] ──────────────────────────────────────┐ │
│  │ הוא הפעיל את התוכנה.                                       │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ── Metadata ─────────────────────────────────────────────────  │
│  Policy:    sentence_ru_context_v1  (hash: a3f7c2d...)          │
│  Model:     tencent/HY-MT1.5-1.8B  (bfloat16)                  │
│  Provider:  local_hymt                                           │
│  Template:  hy_mt_context_observed                               │
│  Sampling:  hy_mt_precise_sentence                               │
│    n_predict=512  temp=0.7  top_k=20  top_p=0.6  rep_pen=1.05  │
│  Glossary:  injected=2  applied=2  (hash: b9c2a1e...)           │
│  Context:   items=2  (hash: d4e1f3a...)                          │
│  Latency:   worker=4 320 ms  total=4 480 ms                     │
│  Placeholders: protected=0  restored=0  missing=0               │
│                                                                  │
│  ── Output ───────────────────────────────────────────────────  │
│  Raw:   Он активировал программное обеспечение.                 │
│  Final: Он активировал программное обеспечение.                 │
│                                                                  │
│  [Copy Trace JSON]  [Export to File]  [Compare with Previous]   │
└─────────────────────────────────────────────────────────────────┘
```

Debug mode controls (in addition to Advanced):
- Full effective prompt preview, colour-coded by layer (L1=blue, L2=green, L3=yellow,
  L4=orange, L5=white), each in a labelled collapsible box
- Metadata panel: `policy_hash`, `glossary_hash`, `context_hash`, `model_quant_id`,
  applied sampling values, latency breakdown, placeholder accounting
- Output panel: raw decoded vs final (post-process) side-by-side
- Actions: Copy Trace JSON, Export to File, Compare with Previous

> **Performance note.** `EffectivePromptTrace` is allocated only when `trace_id != ""` or
> debug mode is active. It is never instantiated on the normal production path.
> Debug mode warns if batch size > 200 (trace memory can reach ~10 MB).

---

## 7. Production Profiles

Six named profiles cover all current and near-future content kinds for He→Ru translation.

### `sentence_ru` (default)

```yaml
policy_id:            sentence_ru
name:                 Standard Translation
content_kind:         sentence
role_instruction:     ""
task_instruction:     "Translate the following segment into Russian,
                      without additional explanation."
output_policy:        ""
terminology_mode:     soft_glossary
context_mode:         off
formatting_mode:      preserve_placeholders
placeholder_mode:     protect_known_placeholders
sampling_profile_id:  hy_mt_precise_sentence
template_profile_id:  hy_mt_standard_observed   # 7B → hy_mt_7b_standard
experimental:         false
allow_user_edit_role: false
allow_user_edit_task: false
description: >
  General-purpose translation for plain CAT segments.
  Matches current production behaviour exactly.
  This is the default profile and the regression baseline.
```

### `sentence_ru_context`

```yaml
policy_id:            sentence_ru_context
name:                 Contextual Translation
content_kind:         sentence_with_context
role_instruction:     ""
task_instruction:     "Translate the following segment into Russian,
                      without additional explanation.
                      Use the surrounding context to resolve ambiguity.
                      Do not translate the context — translate only the segment."
output_policy:        "Output only the Russian translation of the segment."
terminology_mode:     soft_glossary
context_mode:         surrounding_sentences
formatting_mode:      preserve_placeholders
sampling_profile_id:  hy_mt_precise_sentence
template_profile_id:  hy_mt_context_observed
experimental:         true
allow_user_edit_role: false
allow_user_edit_task: true
description: >
  Includes ±2 surrounding segments as context.
  Improves pronoun resolution and discourse cohesion.
  Experimental: validate on test corpus before enabling in Basic mode.
```

### `sentence_ru_formatted`

```yaml
policy_id:            sentence_ru_formatted
name:                 Formatted Text Translation
content_kind:         sentence_formatted
role_instruction:     ""
task_instruction:     "Translate the following segment into Russian,
                      without additional explanation."
output_policy:        ""
terminology_mode:     soft_glossary
context_mode:         off
formatting_mode:      preserve_placeholders
placeholder_mode:     protect_known_placeholders
sampling_profile_id:  hy_mt_precise_formatted
template_profile_id:  hy_mt_formatted_observed  # has use_placeholder_note=True
experimental:         false
allow_user_edit_role: false
allow_user_edit_task: false
description: >
  For segments containing inline markup or HDLE_PH_N format tokens.
  TemplateProfile forces use_placeholder_note=True, injecting an explicit
  placeholder-order reminder into Layer 4c.
```

### `lemma_ru`

```yaml
policy_id:            lemma_ru
name:                 Lemma / Dictionary Entry
content_kind:         lemma
role_instruction:     "You are a bilingual Hebrew–Russian lexicographer.
                      Output only the single most natural Russian equivalent
                      for the given Hebrew lemma."
task_instruction:     "Translate the following Hebrew lemma into Russian."
output_policy:        "Output a single word or short phrase only.
                      No grammatical commentary, no example sentences."
terminology_mode:     off
context_mode:         off
formatting_mode:      plain_text
sampling_profile_id:  hy_mt_precise_short
template_profile_id:  hy_mt_standard_observed   # 7B → hy_mt_7b_standard
experimental:         false
allow_user_edit_role: false
allow_user_edit_task: false
description: >
  Optimised for single dictionary headwords (1–3 Hebrew words).
  Greedy decoding, max 32 tokens (1.8B) / 16 tokens (7B-GPTQ).
  Glossary explicitly disabled: lemma output is itself the term.
```

### `term_ru`

```yaml
policy_id:            term_ru
name:                 Technical Term
content_kind:         term
role_instruction:     "You are a technical translator specialised in Hebrew.
                      Output only the most established Russian equivalent."
task_instruction:     "Translate the following Hebrew technical term into Russian."
output_policy:        "Output a single noun phrase only. No article, no explanation."
terminology_mode:     soft_glossary
context_mode:         off
formatting_mode:      plain_text
sampling_profile_id:  hy_mt_precise_short
template_profile_id:  hy_mt_glossary_observed   # 7B → hy_mt_7b_glossary
experimental:         false
allow_user_edit_role: false
allow_user_edit_task: false
description: >
  For multi-word technical terms. Glossary injected in prompt as a reference;
  soft postprocess applied. Term output is the result, not a downstream segment.
```

### `term_ru_strict_glossary`

```yaml
policy_id:            term_ru_strict_glossary
name:                 Technical Term (Strict Glossary)
content_kind:         term
role_instruction:     "You are a technical translator specialised in Hebrew.
                      Always use the exact approved Russian term from the provided
                      terminology list. Do not paraphrase."
task_instruction:     "Translate the following Hebrew technical term into Russian.
                      Use only the approved term from the Terminology list above."
output_policy:        "Output the approved term verbatim. No modification."
terminology_mode:     strict_glossary
context_mode:         off
formatting_mode:      plain_text
sampling_profile_id:  hy_mt_precise_short
template_profile_id:  hy_mt_glossary_observed   # 7B → hy_mt_7b_glossary
experimental:         false
allow_user_edit_role: false
allow_user_edit_task: false
description: >
  Strict glossary enforcement: model is instructed to copy the approved term.
  apply_glossary() postprocess applies as a safety net to guarantee the term
  even if the model deviates.
```

---

## 8. Rendering Rules

### 8.1 Visible Preview (Layers 1–5, rendered by PolicyRenderer)

`PolicyRenderer.render_user_content(policy, glossary_terms, context_items, source_text)` produces
the string sent to the worker as `WorkerRequest.text`. Concatenation order:

```
{role_instruction block}   ← omitted if role_instruction is empty
{task_instruction}
{output_policy}            ← omitted if empty
                           ← double newline separator
{glossary_block}           ← omitted if terminology_mode=off or no terms found
                           ← double newline if glossary_block present
{context_block}            ← omitted if context_mode=off
                           ← double newline if context_block present
{placeholder_note}         ← omitted unless use_placeholder_note=True in TemplateProfile
                           ← double newline if placeholder_note present
{protected_source_text}
```

This is the string shown in the **Effective Prompt Preview** (all visible layers assembled).

**Role instruction rendering.** The `role_instruction` is passed to the worker via a sentinel
header (see §8.4) so the worker can inject it into the system turn (Layer 0). From the
`effective_prompt_preview` perspective it appears as the first labelled block, making it visible
to the user — but the actual model encoding places it in the system turn.

### 8.2 Hidden Technical Render (Layer 0, worker-assembled)

**1.8B path:**
```
<｜hy_begin▁of▁sentence｜>{system_prompt}[{role_instruction}]<｜hy_place▁holder▁no▁3｜><｜hy_User｜>{user_content}<｜hy_Assistant｜>
```

**7B-GPTQ path:**
```
<|startoftext|>{system_prompt}[{role_instruction}]<|extra_4|>{user_content}<|extra_0|>
```

`{role_instruction}` is appended to the system prompt text (separated by a single newline)
only if non-empty. `{user_content}` is the result of `render_user_content()` minus the
sentinel header (which the worker strips before template assembly).

### 8.3 Render Invariants

1. `_HYMT_SYSTEM_PROMPT` is prepended to every full prompt, regardless of profile.
   It may never be replaced or omitted.
2. `role_instruction`, if present, is appended to the system prompt string **before** the SEP
   token. It is part of the system turn, not the user turn.
3. `task_instruction` is always the first user-turn line. It must be a complete sentence
   ending with a period.
4. `{protected_source_text}` always appears last in user content, after a mandatory
   double-newline separator.
5. Glossary block always precedes source text; context block always precedes glossary block
   if both are present.
6. The placeholder protection instruction in `_HYMT_SYSTEM_PROMPT` is not duplicated in
   `output_policy` unless the policy explicitly uses `use_placeholder_note=True`.

### 8.4 Role Instruction Passing Convention

Because the worker receives only `WorkerRequest.text`, the role instruction is conveyed as a
sentinel-prefixed block that the worker strips before template assembly:

```
\x00ROLE_INSTRUCTION_BEGIN\x00
{role_instruction_text}
\x00ROLE_INSTRUCTION_END\x00
{task_instruction}
{output_policy}

{source_text}
```

The worker:
1. Detects the sentinel block at the start of `user_content`.
2. Strips the block from `user_content`.
3. Appends `role_instruction_text` to `_HYMT_SYSTEM_PROMPT` (with a newline separator) before
   inserting into the model-specific template.
4. If no sentinel block is present, uses `_HYMT_SYSTEM_PROMPT` unchanged (backwards compatible
   with current callers that do not use PPS).

> **Backlog:** Replace sentinel approach with a new `role_instruction` field in `WorkerRequest`
> in a future IPC schema revision. The sentinel is a zero-migration workaround that avoids
> breaking the current IPC contract.

---

## 9. Sampling Profiles

Three named profiles replace the current two hard-coded `gen_kwargs` blocks in
`_translate_transformers_causal`. Each profile is expressed with the full `SamplingProfile`
field model; model-layer constraints are applied at the provider before dispatch.

### `hy_mt_precise_sentence`

General-purpose sentence translation. Current production parameters.

```yaml
sampling_profile_id:  hy_mt_precise_sentence
name:                 Precise (Sentence)
description: >
  Standard translation profile for full sentences.
  Sampling with moderate creativity and repetition penalty.
  Baseline for regression tests.

# Expressed intent (applied to 1.8B — sampling path)
temperature:          0.7
top_k:                20
top_p:                0.6
min_p:                0.0
typical_p:            1.0
repetition_penalty:   1.05
repeat_last_n:        64
frequency_penalty:    0.0
presence_penalty:     0.0
mirostat_mode:        0
seed:                 -1
n_predict:            512

# Model-layer constraints (set by TemplateProfile, not user-editable)
# For 7B-GPTQ (hy_mt_7b_standard / hy_mt_7b_glossary):
#   force_greedy=True overrides temperature/do_sample
#   max_n_predict_cap=128 overrides n_predict
# Applied values logged in EffectivePromptTrace.applied_sampling
```

### `hy_mt_precise_short`

Short outputs: lemmas, terms, UI strings.

```yaml
sampling_profile_id:  hy_mt_precise_short
name:                 Precise (Short Output)
description: >
  Greedy decoding for short deterministic outputs.
  Used for lemmas, technical terms, and UI strings where
  canonical form is required over creative variation.

temperature:          0.0          # greedy for both model families
top_k:                0
top_p:                1.0
min_p:                0.0
typical_p:            1.0
repetition_penalty:   1.0
repeat_last_n:        0
frequency_penalty:    0.0
presence_penalty:     0.0
mirostat_mode:        0
seed:                 -1
n_predict:            32           # 1.8B; 7B-GPTQ capped to 16 by TemplateProfile

# Model-layer constraints
# 7B-GPTQ TemplateProfile: max_n_predict_cap=16
```

### `hy_mt_precise_formatted`

Formatted text with placeholders. Conservative sampling to reduce hallucinated tokens.

```yaml
sampling_profile_id:  hy_mt_precise_formatted
name:                 Precise (Formatted)
description: >
  Lower temperature and tighter top_k for segments with inline markup.
  Reduces risk of generating spurious HDLE_PH_N tokens not present
  in the source. Stricter repetition penalty.

temperature:          0.5
top_k:                10
top_p:                0.5
min_p:                0.0
typical_p:            1.0
repetition_penalty:   1.1
repeat_last_n:        64
frequency_penalty:    0.0
presence_penalty:     0.0
mirostat_mode:        0
seed:                 -1
n_predict:            512

# 7B-GPTQ: force_greedy overrides; max_n_predict_cap=128
```

**Worker selection logic** (replaces current `if is_gptq` block in
`_translate_transformers_causal`):

```python
def _resolve_gen_kwargs(
    sampling_profile_id: str,
    template_profile: TemplateProfile,
) -> dict:
    profile = SAMPLING_PROFILES[sampling_profile_id]  # O(1) dict lookup

    kwargs: dict = {
        "max_new_tokens": profile.n_predict,
        "eos_token_id": stop_ids if stop_ids else None,
    }

    if template_profile.force_greedy or profile.temperature == 0.0:
        kwargs["do_sample"] = False
    else:
        kwargs.update({
            "do_sample": True,
            "temperature": profile.temperature,
            "top_k": profile.top_k,
            "top_p": profile.top_p,
            "repetition_penalty": profile.repetition_penalty,
        })

    if template_profile.max_n_predict_cap is not None:
        kwargs["max_new_tokens"] = min(
            kwargs["max_new_tokens"], template_profile.max_n_predict_cap
        )

    return kwargs
```

`SAMPLING_PROFILES` and `TEMPLATE_PROFILES` are module-level dicts, populated at import time.
No I/O; no configuration files required at runtime.

---

## 10. Routing and Fallback Rules

### 10.1 Profile Resolution Order

```
1. TranslationRequest.options["prompt_policy_id"]  → explicit override (Advanced/Debug UI)
2. ContentKind → default_profile table (below)     → automatic routing
3. "sentence_ru"                                   → global fallback
```

**ContentKind → default profile mapping:**

| ContentKind | Default Profile |
|-------------|-----------------|
| `LEMMA` | `lemma_ru` |
| `TERM` | `term_ru` |
| `SENTENCE` | `sentence_ru` |
| `SENTENCE_WITH_CONTEXT` | `sentence_ru_context` |
| `SENTENCE_FORMATTED` | `sentence_ru_formatted` |
| `UI_STRING` | `lemma_ru` (short output, greedy) |
| `BATCH_MIXED` | `sentence_ru` (safe default) |
| *(not set / None)* | `sentence_ru` |

### 10.2 Content Kind Inference (Basic Mode)

When the caller does not set `content_kind`, the `TranslationRouter` infers it:

| Condition | Inferred Kind |
|-----------|---------------|
| Source text matches `_PH_PATTERN` at least once | `SENTENCE_FORMATTED` |
| Source text has no whitespace (single token) | `LEMMA` |
| Source text word count ≤ 4 | `TERM` |
| Otherwise | `SENTENCE` |

This inference is a **heuristic** — callers that know the content kind must set it explicitly.
The heuristic fires only when `content_kind` is `None`.

### 10.3 Profile Fallback on Experimental

If the resolved profile has `experimental=True` and the UI mode is Basic, `TranslationRouter`
falls back to `sentence_ru` and logs a warning. The guard is enforced at the router layer (not
just in the UI) so that API callers also cannot bypass it silently.

### 10.4 Model-Family TemplateProfile Selection

`LocalHYMTProvider` selects the `template_profile_id` from the resolved policy and validates
that it matches the active provider family:

| Provider | Required template prefix |
|----------|--------------------------|
| `local_hymt` (1.8B) | `hy_mt_*_observed` |
| `local_hymt_7b_gptq` | `hy_mt_7b_*` |

If the policy specifies an incompatible template, the router selects the nearest equivalent
7B template and logs a warning.

### 10.5 Sampling Profile Fallback

If the resolved `sampling_profile_id` is not found in `SAMPLING_PROFILES`, fall back to
`hy_mt_precise_sentence` and emit a warning in `meta["prompt_policy"]["warnings"]`.

---

## 11. Observability / Audit Contract

### 11.1 TranslationResult.meta Extension

Every successful translation from a HY-MT provider must include:

```python
meta["prompt_policy"] = {
    "policy_id": str,              # e.g. "sentence_ru"
    "policy_hash": str | None,     # SHA-256 of policy (None in first impl)
    "sampling_profile_id": str,    # e.g. "hy_mt_precise_sentence"
    "template_profile_id": str,    # e.g. "hy_mt_standard_observed"
    "content_kind": str,           # e.g. "sentence"
    "terminology_mode": str,       # e.g. "soft_glossary"
    "injected_term_count": int,    # terms in prompt
    "applied_term_count": int,     # terms applied in postprocess
    "placeholder_count": int,      # protected HDLE_PH_N tokens
    "missing_placeholders": list[str],  # [] on full success
    "fallback_triggered": bool,    # True if router fell back to sentence_ru
    "fallback_reason": str | None,
    "warnings": list[str],         # policy resolution warnings
    "trace": EffectivePromptTrace | None,  # None unless trace active
}
```

Fields already present at the top level of `meta` (`inference_time_ms`, `applied_terms_count`,
`placeholder_count`, `missing_placeholders`, `model_id`, `backend`) are **preserved** for
backwards compatibility. They are also present inside `meta["prompt_policy"]` for structured
access. No breaking change to existing consumers.

### 11.2 Logging Contract

| Event | Level | Structured fields |
|-------|-------|-------------------|
| Profile resolved | DEBUG | `policy_id`, `content_kind`, `source` (explicit/inferred/fallback) |
| Experimental profile in Basic mode | WARNING | `policy_id` |
| Role instruction injected | DEBUG | `policy_id`, `role_len` |
| Sampling constraint override (force_greedy) | WARNING | `profile_id`, `original_temp`, `override` |
| Sampling profile fallback | WARNING | `requested_id`, `fallback_id` |
| Template profile mismatch | WARNING | `policy_id`, `specified`, `selected` |
| Placeholder lost in translation | WARNING | `token`, `original` (existing) |
| Trace built | DEBUG | `policy_id`, `trace_size_bytes` |

All log records include `provider_id` and `trace_id` (when set) as structured fields via
`logger.debug("...", extra={"provider_id": ..., "trace_id": ...})`.

### 11.3 QA Regression Invariants

The following must hold across any PPS implementation:

1. `sentence_ru` + `hy_mt_precise_sentence` + `hy_mt_standard_observed` reproduces the
   **current** `_translate_transformers_causal` output bit-for-bit when no role instruction is
   present and no context is used.
2. `meta["applied_terms_count"]` == `meta["prompt_policy"]["applied_term_count"]`.
3. `meta["prompt_policy"]["missing_placeholders"]` is `[]` on any segment where all HDLE_PH_N
   tokens survived.
4. Any profile with `terminology_mode=off` must result in `injected_term_count=0` and
   `applied_term_count=0`.
5. `EffectivePromptTrace` is `None` when `trace_id == ""` and debug mode is off.
6. `meta["prompt_policy"]["fallback_triggered"]` is `True` whenever `TranslationRouter`
   selects a profile other than the one initially resolved.

---

## 12. JSON / YAML Examples

### 12.1 TranslationRequest with explicit policy override

```json
{
  "source_text": "הוא שלח את HDLE_PH_1 לכתובת HDLE_PH_2.",
  "source_lang": "he",
  "target_lang": "ru",
  "content_kind": "sentence_formatted",
  "options": {
    "prompt_policy_id": "sentence_ru_formatted"
  },
  "trace_id": "seg-00492",
  "allow_fallback": true,
  "timeout_seconds": 130.0
}
```

### 12.2 TranslationResult.meta (production, tracing off)

```json
{
  "inference_time_ms": 4320.5,
  "applied_terms_count": 2,
  "placeholder_count": 2,
  "missing_placeholders": [],
  "model_id": "tencent/HY-MT1.5-7B-GPTQ-Int4",
  "backend": "transformers_causal",
  "prompt_policy": {
    "policy_id": "sentence_ru_formatted",
    "policy_hash": null,
    "sampling_profile_id": "hy_mt_precise_formatted",
    "template_profile_id": "hy_mt_7b_glossary",
    "content_kind": "sentence_formatted",
    "terminology_mode": "soft_glossary",
    "injected_term_count": 3,
    "applied_term_count": 2,
    "placeholder_count": 2,
    "missing_placeholders": [],
    "fallback_triggered": false,
    "fallback_reason": null,
    "warnings": [],
    "trace": null
  }
}
```

### 12.3 EffectivePromptTrace (debug mode, trace_id="seg-00492")

```json
{
  "trace_id": "seg-00492",
  "policy_id": "sentence_ru_formatted",
  "policy_version": "1.0.0",
  "policy_hash": null,
  "template_profile_id": "hy_mt_7b_glossary",
  "sampling_profile_id": "hy_mt_precise_formatted",
  "content_kind": "sentence_formatted",
  "source_lang": "he",
  "target_lang": "ru",
  "model_id": "tencent/HY-MT1.5-7B-GPTQ-Int4",
  "model_quant_id": "gptq-int4",
  "provider_id": "local_hymt_7b_gptq",
  "source_text": "הוא שלח את HDLE_PH_1 לכתובת HDLE_PH_2.",
  "source_text_hash": null,
  "source_length_chars": 42,
  "rendered_role_instruction": "",
  "rendered_task_instruction": "Translate the following segment into Russian, without additional explanation.",
  "rendered_output_policy": "",
  "rendered_glossary_block": "Terminology: מחשב → компьютер, קובץ → файл, שרת → сервер.",
  "rendered_context_block": null,
  "rendered_formatting_note": "All placeholder tokens (HDLE_PH_1, HDLE_PH_2, …) must appear in your output in the same relative order.",
  "rendered_user_payload": "הוא שלח את HDLE_PH_1 לכתובת HDLE_PH_2.",
  "effective_prompt_preview": "Translate the following segment into Russian, without additional explanation.\n\nTerminology: מחשב → компьютер, קובץ → файл, שרת → сервер.\n\nAll placeholder tokens (HDLE_PH_1, HDLE_PH_2, …) must appear in your output in the same relative order.\n\nהוא שלח את HDLE_PH_1 לכתובת HDLE_PH_2.",
  "glossary_hash": null,
  "context_hash": null,
  "applied_sampling": {
    "max_new_tokens": 128,
    "do_sample": false,
    "eos_token_id": [127960]
  },
  "placeholder_tokens_protected": ["HDLE_PH_1", "HDLE_PH_2"],
  "placeholder_tokens_restored": 2,
  "raw_model_output": "Он отправил HDLE_PH_1 на адрес HDLE_PH_2.",
  "translated_text": "Он отправил HDLE_PH_1 на адрес HDLE_PH_2.",
  "output_length_chars": 43,
  "output_tokens_generated": null,
  "latency_ms": 4480,
  "worker_latency_ms": 4321,
  "glossary_applied": true,
  "context_applied": false,
  "fallback_triggered": false,
  "fallback_reason": null,
  "created_at": "2026-04-07T14:32:01.553Z"
}
```

### 12.4 PromptPolicy registry (YAML, module-level data — partial)

```yaml
profiles:
  - policy_id: sentence_ru
    name: Standard Translation
    content_kind: sentence
    role_instruction: ""
    task_instruction: >
      Translate the following segment into Russian,
      without additional explanation.
    output_policy: ""
    terminology_mode: soft_glossary
    context_mode: off
    formatting_mode: preserve_placeholders
    placeholder_mode: protect_known_placeholders
    sampling_profile_id: hy_mt_precise_sentence
    template_profile_id: hy_mt_standard_observed
    experimental: false
    allow_user_edit_role: false
    allow_user_edit_task: false
    allow_user_edit_output_policy: false
    max_glossary_items: 20
    is_builtin: true
    is_custom: false

  - policy_id: lemma_ru
    name: Lemma / Dictionary Entry
    content_kind: lemma
    role_instruction: >
      You are a bilingual Hebrew–Russian lexicographer.
      Output only the single most natural Russian equivalent
      for the given Hebrew lemma.
    task_instruction: Translate the following Hebrew lemma into Russian.
    output_policy: >
      Output a single word or short phrase only.
      No grammatical commentary, no example sentences.
    terminology_mode: off
    context_mode: off
    sampling_profile_id: hy_mt_precise_short
    template_profile_id: hy_mt_standard_observed
    experimental: false
    allow_user_edit_role: false
    allow_user_edit_task: false
    is_builtin: true
    is_custom: false
```

---

## 13. Recommended Defaults

| Setting | Value | Rationale |
|---------|-------|-----------|
| Default profile (all contexts) | `sentence_ru` | Preserves current behaviour; zero regression risk |
| Default terminology mode | `soft_glossary` | Equivalent to current "both": inject + soft postprocess |
| Default sampling (1.8B) | `hy_mt_precise_sentence` | Current production parameters |
| Default sampling (7B-GPTQ) | `hy_mt_precise_sentence` + `hy_mt_7b_standard` constraints | Greedy, 128 tokens — tested, within 120 s timeout |
| Debug mode | off | Trace allocations are non-trivial; never on in production |
| Content kind (not set by caller) | `SENTENCE` | Conservative; heuristic inference disabled by default |
| Heuristic inference | disabled | Enable only when caller is confirmed to omit content_kind |
| Experimental profiles in Basic mode | blocked at router | Not just in UI — router enforces the guard |
| Role instruction max length | 512 chars | Prevent context-window pressure from long addenda |
| Terminology injection max terms | 20 | Current `_fetch_glossary_terms_for_prompt` limit |
| Layer 4c constraint (free text) | max 200 chars | Injection surface reduction |
| Trace history (UI) | last 100 segments | Prevents memory growth in long debug sessions |

---

## 14. Risks and Failure Modes

### R1: Role instruction sentinel collision
**Scenario:** Source text contains `\x00ROLE_INSTRUCTION_BEGIN\x00` literally.
**Impact:** Worker incorrectly strips a portion of source content as if it were a role
instruction block.
**Likelihood:** Very low (null-byte sequences do not appear in natural text).
**Mitigation:** Sentinel uses `\x00` (null byte) as outer delimiter, which is illegal in Hebrew /
Russian / Latin plain text. Add an assertion in worker that the sentinel block contains no
newlines or source-text-like content. Track IPC schema extension in backlog.

### R2: `sentence_ru` output regression if system prompt changes
**Scenario:** A future `_HYMT_SYSTEM_PROMPT` edit changes translation quality.
**Impact:** Existing MT cache hits silently return old translations for new model behaviour.
**Mitigation:** Include a content-hash of `_HYMT_SYSTEM_PROMPT` in `get_model_version()` return
value (alongside `model_id` and `backend`) so that cache keys are automatically invalidated on
any system prompt change.

### R3: Experimental profile activated in production via `options` override
**Scenario:** A caller injects `prompt_policy_id: sentence_ru_context` in `TranslationRequest.
options` without the UI setting it, bypassing the Basic mode guard.
**Impact:** Potentially lower quality or unexpected latency in batch translation.
**Mitigation:** Enforce experimental guard in `TranslationRouter` (not just in UI). Log a
`WARNING` if an experimental profile is invoked without `trace_id` set.

### R4: EffectivePromptTrace memory growth in Debug mode
**Scenario:** Debug mode left enabled in a long batch translation session.
**Impact:** Each `TranslationResult.meta["prompt_policy"]["trace"]` holds full string copies of
the prompt. At ~1 KB per trace × 10,000 segments ≈ ~10 MB retained in UI history.
**Mitigation:** Cap the UI-level trace history to the last 100 segments. Emit a `WARNING` in
Debug mode if batch size exceeds 200.

### R5: Sampling profile minimum token violation
**Scenario:** Provider resolves `hy_mt_precise_short` with `n_predict=16` on a model that
requires a minimum of 32 tokens.
**Impact:** `model.generate()` raises or returns empty output; `WorkerResult.error` is set.
**Mitigation:** Add `SamplingProfile.validate()` that checks parameter ranges against
model-family requirements at startup (module import), not per-request.

### R6: `rendered_full_prompt` reconstruction approximation
**Scenario:** Debug mode reconstructs the full prompt from known template constants; actual
worker prompt may diverge if worker logic is updated without updating the reconstruction.
**Impact:** Misleading debug information for engineers.
**Mitigation:** Add a `type: "render_prompt"` IPC message type that returns the exact assembled
prompt from the worker (for Debug mode only). Not required for first implementation; add in
PATCH-05 or later.

### R7: Sampling constraint silent override not surfaced to user
**Scenario:** Advanced mode user sets `temperature=0.9` via a custom sampling preset, but the
7B-GPTQ TemplateProfile overrides it to greedy. The user sees the custom value in the UI but
the model runs greedy.
**Impact:** User confusion; perception of "policy not applied".
**Mitigation:** Show an inline warning in Advanced mode when the active TemplateProfile will
override sampling parameters. Add `applied_sampling` to the Debug metadata panel so the actual
values are always visible.

---

## 15. Definition of Done

### 15.1 Functional Acceptance Criteria

- [ ] All six production profiles are defined and loadable without I/O at import time.
- [ ] `sentence_ru` + `hy_mt_precise_sentence` produces **identical output** to the current
      implementation for all existing test fixtures (zero delta against MT cache).
- [ ] `lemma_ru` produces single-word output for ≥ 90% of test lemma inputs (measured on
      `tests/fixtures/lemma_he_ru_sample.jsonl` — to be created).
- [ ] `sentence_ru_formatted` preserves all HDLE_PH_N placeholders in correct order on all
      existing `test_local_hymt_7b_gptq_provider.py` test cases.
- [ ] Content kind inference correctly classifies ≥ 95% of inputs in
      `tests/fixtures/content_kind_sample.jsonl` (to be created).
- [ ] `EffectivePromptTrace` is `None` for all calls with `trace_id=""` and debug mode off.
- [ ] `EffectivePromptTrace` is populated with required fields for all calls with `trace_id != ""`.
- [ ] `meta["prompt_policy"]["policy_id"]` is present on every successful `TranslationResult`.
- [ ] Experimental profile blocked at `TranslationRouter` level in Basic mode.
- [ ] Role instruction sentinel roundtrip works correctly for all six profiles.
- [ ] Sampling constraint override (P6) produces a logged WARNING and correct `applied_sampling`.

### 15.2 Regression Criteria

- [ ] All 35 existing `test_local_hymt_7b_gptq_provider.py` tests pass unchanged.
- [ ] All existing provider tests pass (`tests/test_providers_setup.py` or equivalent).
- [ ] `python -m pytest -v` exits 0.
- [ ] `python -c "from app.infra.translators.providers.local_hymt_provider import LocalHYMTProvider; print('OK')"` succeeds.

### 15.3 Performance Criteria

- [ ] Profile resolution adds < 0.1 ms to `translate()` critical path (`timeit`, no I/O).
- [ ] `PolicyRenderer.render_user_content()` adds < 0.5 ms to the critical path.
- [ ] `EffectivePromptTrace` construction adds < 1 ms when trace is active.
- [ ] No additional worker IPC round-trips introduced in the normal (non-debug) path.

### 15.4 Safety Criteria

- [ ] `_HYMT_SYSTEM_PROMPT` placeholder protection instruction appears in 100% of assembled
      prompts regardless of profile, UI mode, or debug state.
- [ ] Layer 4 free-text input (if any) is sanitised before inclusion in any prompt.
- [ ] No user-supplied string can appear before Layer 0 in the assembled prompt.
- [ ] The system rejects `PromptPolicy` with `placeholder_mode=off` at registry load time.

### 15.5 Docs Criteria

- [ ] `AUDIT_HY-MT-provider.md` §3 (Architecture) updated to reference PPS and layer model.
- [ ] `docs/HY_MT_PROMPT_POLICY_SPEC_V3.md` (this document) committed and linked from AUDIT index.
- [ ] Inline docstrings on `PromptPolicy`, `SamplingProfile`, `TemplateProfile`,
      `PolicyRenderer`, `TranslationRouter`.
- [ ] Debug mode UI panel documented in user-facing help text.

### 15.6 Patch Series

```
PATCH-01: Domain model + registry (PromptPolicy, SamplingProfile, TemplateProfile, enums)
          Files:  app/infra/translators/prompt_policy.py  (new)
          Tests:  tests/test_prompt_policy_registry.py    (new)
          DoD:    All six profiles and three sampling profiles load at import.
                  sentence_ru is default. No I/O at import.
                  SamplingProfile.validate() passes for all built-in profiles.

PATCH-02: PolicyRenderer + role instruction sentinel passing
          Files:  app/infra/translators/prompt_policy.py  (render_user_content, etc.)
                  worker_process._translate_transformers_causal (sentinel parsing)
          Tests:  tests/test_prompt_renderer.py  (new, source inspection — no torch)
          DoD:    sentence_ru renders identically to current code (zero diff).
                  lemma_ru role instruction roundtrip verified.
                  Sentinel not present → backwards compatible with current callers.

PATCH-03: TranslationRouter + LocalHYMTProvider integration
          Files:  app/infra/translators/prompt_policy.py  (TranslationRouter)
                  app/infra/translators/providers/local_hymt_provider.py
                  local_hymt_7b_gptq_provider.py (inherits, no change)
          Tests:  tests/test_local_hymt_provider_policy.py  (new)
                  Extend tests/test_local_hymt_7b_gptq_provider.py
          DoD:    meta["prompt_policy"] present on all success results.
                  Experimental guard enforced at router.
                  All existing regression tests pass.

PATCH-04: Worker sampling profile lookup (replaces hard-coded gen_kwargs)
          Files:  worker_process.py  (SAMPLING_PROFILES dict, _resolve_gen_kwargs)
          Tests:  Source inspection tests (no torch import required)
          DoD:    hy_mt_precise_sentence produces identical gen_kwargs to current code.
                  force_greedy override produces WARNING log + correct applied_sampling.

PATCH-05: EffectivePromptTrace + Debug mode UI
          Files:  app/infra/translators/prompt_policy.py  (EffectivePromptTrace)
                  UI: provider settings panel or dedicated audit panel
          Tests:  tests/test_effective_prompt_trace.py  (new, no torch)
          DoD:    Trace is None when trace_id="" and debug off.
                  Trace populated with all required fields when trace active.
                  UI Debug panel shows colour-coded layers + metadata.
                  Trace history capped at 100 segments in UI.

--- POST-VALIDATION (PATCH-06+, scheduled after QA sign-off on PATCH-01..05) ---

PATCH-06: policy_hash, glossary_hash, context_hash, source_text_hash computation
          Files:  prompt_policy.py (hash computation at registry load + render time)
          DoD:    EffectivePromptTrace hashes populated.
                  get_model_version() includes system prompt hash for cache invalidation.

PATCH-07: TemplateProfile full routing (auto-select 7B vs 1.8B template)
          Files:  TranslationRouter (template_profile selection logic)
          DoD:    1.8B provider auto-selects hy_mt_*_observed; 7B auto-selects hy_mt_7b_*.
                  Mismatch warning logged and nearest equivalent selected.
```

> **Spec vs implementation scope.** This V3 spec is the authoritative architecture.
> PATCH-01..05 implement the core PPS. PATCH-06..07 implement the V2-origin additions
> (hashing, full template routing). The spec intentionally reaches slightly ahead of the
> first implementation to prevent architectural drift in future patches.

---

*End of Specification*
