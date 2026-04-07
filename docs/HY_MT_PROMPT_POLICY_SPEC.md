# HY-MT Prompt Policy System — Design Specification

**Product:** HDLE Premium (V_book)
**Scope:** `LocalHYMTProvider` (1.8B) + `LocalHYMT7BGPTQProvider` (7B-GPTQ)
**Status:** Design (implementation pending)
**Last updated:** 2026-04-07
**Author:** Architecture / AI Systems

---

## 1. Executive Summary

The Prompt Policy System (PPS) formalises how HDLE constructs, governs, and observes
the prompts it sends to on-device HY-MT inference.

**Problem today.** The current system has a single hard-coded system prompt and a
single hard-coded task instruction ("Translate the following segment into Russian,
without additional explanation.").  There is no mechanism for the application to signal
what *kind* of content it is translating (a lemma, a CAT segment, a formatted
UI string), so the model applies uniform behaviour regardless of context.  There is
no user control, no rendering preview, and no structured observability beyond the raw
`meta` dict in `TranslationResult`.

**What PPS adds.**

1. **Content-kind routing** — the provider selects a named *profile* based on the
   content kind of the segment (lemma, term, sentence, formatted text, …).  Each
   profile encodes a task instruction, a sampling strategy, and output constraints
   that are appropriate for that content kind.
2. **Layered prompt architecture** — a mandatory hidden Layer 0 (technical wrapper:
   placeholder rule, format contract) is always injected at the worker level and is
   never visible to users.  Layers 1–5 are user-facing or configurable and compose
   on top of Layer 0.
3. **Rendering contract** — the provider can produce an `EffectivePromptTrace`
   that shows exactly what was sent to the model, which layer contributed what, and
   what was generated.  This is the basis for a Debug mode in the UI.
4. **Sampling profiles** — three named generation-parameter bundles replace the
   current two hard-coded `gen_kwargs` blocks.  Profiles are model-family-aware
   (1.8B vs 7B-GPTQ).
5. **Observability** — every `TranslationResult.meta` is extended with a structured
   `prompt_policy` sub-dict, enabling audit, QA, and regression detection.

**Design constraint: minimal blast radius.** PPS is additive.  The existing
`_HYMT_SYSTEM_PROMPT`, template constants, and `_translate_transformers_causal`
function are not replaced — they are reclassified as the defaults of the
`sentence_ru` profile and the `transformers_causal` template profile.  No existing
test must break.

---

## 2. Design Principles

| # | Principle | Rationale |
|---|-----------|-----------|
| P1 | **Hidden wrapper is inviolable** | Placeholder protection and output format contract must never be suppressible, even in Debug mode.  Safety over flexibility. |
| P2 | **Content kind drives profile selection** | The caller knows what it is translating; the policy system must not guess from the text. |
| P3 | **Profile = unit of change** | A profile change (task instruction edit, sampling tweak) must not require a code change.  Profiles are data. |
| P4 | **Observability without overhead** | Trace data is computed eagerly but stored only if the caller opts in (trace_id present or debug mode active).  Normal path has no extra latency. |
| P5 | **Model-family isolation** | 1.8B and 7B-GPTQ have incompatible token vocabularies.  Template selection is an internal concern of the worker; profiles declare *intent*, not tokens. |
| P6 | **No prompt injection from UI** | Free-text user instructions are rendered in Layer 4 (Constraints) and sanitised before injection.  They are never prepended to Layer 0. |
| P7 | **Defaults must match current behaviour** | The `sentence_ru` profile with `hy_mt_precise_sentence` sampling must reproduce the current output exactly so that existing MT cache hits remain valid. |

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Caller (TranslationCoordinator / SegmentTranslationService)        │
│                                                                     │
│   TranslationRequest                                                │
│     .source_text    — placeholder-protected by provider             │
│     .content_kind   — NEW: ContentKind enum                         │
│     .options        — NEW: {"prompt_policy_id": "lemma_ru"}         │
└────────────────────────┬────────────────────────────────────────────┘
                         │ translate(request)
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LocalHYMTProvider / LocalHYMT7BGPTQProvider                        │
│                                                                     │
│  1. Resolve PromptPolicy (content_kind → profile id)                │
│  2. _protect_placeholders(source_text)                              │
│  3. Fetch glossary terms (if db_session)                            │
│  4. Build user_content = PromptRenderer.render_user_turn(policy,    │
│       glossary_terms, protected_text)                               │
│  5. worker.translate(WorkerRequest(text=user_content))              │
│  6. _restore_placeholders + apply_glossary                          │
│  7. Build EffectivePromptTrace (if tracing enabled)                 │
│  8. Return TranslationResult (meta includes prompt_policy sub-dict) │
└────────────────────────┬────────────────────────────────────────────┘
                         │ WorkerRequest.text = user_content
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  worker_process._translate_transformers_causal(model_dict, prompt)  │
│                                                                     │
│  Layer 0 (HIDDEN — assembled here, never leaves this function):     │
│    {BOS}{_HYMT_SYSTEM_PROMPT}{SEP}                                  │
│    {task_instruction}\n\n{user_content}{TURN_END}                   │
│                                                                     │
│  model.generate(**sampling_profile_kwargs)                          │
│  post-process (EOS strip, boundary truncation)                      │
└─────────────────────────────────────────────────────────────────────┘
```

**Key architectural split.**

- **Provider** (Python process): policy resolution, user-content construction, glossary,
  placeholder protect/restore, observability.
- **Worker subprocess**: Layer 0 assembly (BOS/SEP/EOS tokens), tokenisation,
  `model.generate()`, decoding, EOS post-process.

This split is intentional: the worker owns the model-specific token vocabulary; the
provider owns the application-level prompt policy.  The worker receives only
`user_content` (Layer 2–5 payload) and knows nothing about profile IDs.

---

## 4. Domain Model

### 4.1 Enumerations

```python
from enum import Enum

class ContentKind(str, Enum):
    """Semantic kind of the content being translated.

    Callers must set this so the policy router can select the correct profile.
    Default is SENTENCE for backwards compatibility.
    """
    LEMMA                = "lemma"               # Dictionary headword (1–3 words)
    TERM                 = "term"                # Technical term / multi-word unit
    SENTENCE             = "sentence"            # Plain CAT segment, no formatting
    SENTENCE_WITH_CONTEXT = "sentence_context"   # CAT segment + surrounding context
    SENTENCE_FORMATTED   = "sentence_formatted"  # Segment with inline markup / placeholders
    UI_STRING            = "ui_string"           # Short UI label (buttons, menus)
    BATCH_MIXED          = "batch_mixed"         # Heterogeneous batch — use safe defaults


class TerminologyMode(str, Enum):
    """How glossary terms are injected and applied."""
    OFF    = "off"     # No glossary — skip fetch, skip postprocess
    PROMPT = "prompt"  # Inject into user turn only; no postprocess
    POST   = "post"    # Postprocess only; no prompt injection
    BOTH   = "both"    # Prompt injection + postprocess (current default)


class ContextMode(str, Enum):
    """Whether surrounding segment context is included in the prompt."""
    NONE     = "none"     # Source text only
    WINDOW   = "window"   # ±N segments around the current segment (future)


class FormattingMode(str, Enum):
    """How inline formatting / placeholders are handled."""
    PLACEHOLDERS = "placeholders"  # HDLE_PH_N protection (always active, non-suppressible)
    STRIP        = "strip"         # Strip all inline markup before translation (future)


class PlaceholderMode(str, Enum):
    """Instruction verbosity for placeholder tokens in the user turn."""
    SILENT    = "silent"    # No explicit instruction (system prompt covers it)
    BRIEF     = "brief"     # One-line reminder in user turn
    EXPLICIT  = "explicit"  # Full rule restated (for complex multi-placeholder segments)
```

### 4.2 PromptPolicy

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class PromptPolicy:
    """Named, immutable policy governing one translation profile.

    A policy is a pure value object: it carries no state, holds no references
    to models or sessions, and is safe to cache globally.
    """
    policy_id: str                  # Machine key, e.g. "lemma_ru"
    display_name: str               # Human label shown in UI Advanced mode
    content_kind: ContentKind

    # --- Layer 1 (Role) ---
    # Injected into the *system* prompt to specialise the model persona.
    # Empty string = use the global system prompt unchanged.
    role_addendum: str = ""

    # --- Layer 2 (Task instruction) ---
    # The "Translate …" sentence in the user turn.  Must end without a period
    # so the source text can follow on the next line.
    task_instruction: str = (
        "Translate the following segment into Russian, "
        "without additional explanation."
    )

    # --- Layer 3 (Output policy) ---
    # Appended after the task instruction as a reminder of output constraints.
    # Example: "Output a single word only." for lemma profiles.
    output_policy: str = ""

    # --- Layer 4 (Constraints) ---
    # Per-request runtime constraints (e.g., "Max 10 words.").
    # Populated at render time from request options, not stored in profile.
    # Listed here for documentation only — not part of profile definition.

    # --- Sampling strategy ---
    sampling_profile_id: str = "hy_mt_precise_sentence"

    # --- Feature flags ---
    terminology_mode: TerminologyMode = TerminologyMode.BOTH
    context_mode: ContextMode = ContextMode.NONE
    placeholder_mode: PlaceholderMode = PlaceholderMode.SILENT

    # --- Metadata ---
    description: str = ""          # Shown in Debug mode tooltip
    experimental: bool = False     # If True, shown only in Advanced/Debug UI
```

### 4.3 SamplingProfile

```python
@dataclass(frozen=True)
class SamplingProfile:
    """Generation hyperparameters for model.generate().

    A profile is model-family-aware: the worker selects the appropriate
    parameter set based on is_gptq (see §9).
    """
    profile_id: str
    display_name: str

    # Parameters for 1.8B (decoder, sampling path)
    params_1b8: dict

    # Parameters for 7B-GPTQ (greedy, latency-constrained)
    params_7b_gptq: dict

    description: str = ""
```

### 4.4 TemplateProfile

```python
@dataclass(frozen=True)
class TemplateProfile:
    """Model-family-specific chat template constants.

    Template profiles are internal and not exposed to users.
    Selection is automatic: worker detects is_gptq from model_id.
    """
    profile_id: str    # "hymt_1b8" | "hymt_7b_gptq"
    bos: str
    sep: str           # System→user separator
    user_end: str      # End of user turn (triggers assistant generation)
    eos: str           # Expected end-of-generation token
    stop2: str = ""    # Secondary stop string (1.8B only)
```

### 4.5 EffectivePromptTrace

```python
@dataclass
class EffectivePromptTrace:
    """Full audit record of what was sent to the model and what came back.

    Stored in TranslationResult.meta["prompt_policy"]["trace"] when tracing
    is active (trace_id present or debug mode enabled).
    Never stored in production paths where trace_id is empty.
    """
    policy_id: str
    sampling_profile_id: str
    content_kind: str

    # Layered prompt breakdown
    layer0_system_prompt: str      # Full system prompt (hidden, for audit)
    layer1_role_addendum: str      # Role addendum (may be empty)
    layer2_task_instruction: str   # Task instruction sent in user turn
    layer3_output_policy: str      # Output policy (may be empty)
    layer4_constraints: str        # Runtime constraints (may be empty)
    layer5_user_payload: str       # Source text (placeholder-protected)

    # Full rendered strings (what the worker actually received)
    rendered_user_content: str     # Concatenation of L2–L5 sent as WorkerRequest.text
    rendered_full_prompt: str      # Full chat string assembled by worker (reconstructed)

    # Output
    raw_model_output: str          # Decoded output before post-process
    final_translation: str         # After EOS strip + boundary truncation

    # Timing
    inference_time_ms: float
    total_latency_ms: float

    # Glossary
    injected_term_count: int
    applied_term_count: int
```

---

## 5. Policy Layering

The prompt sent to the model is assembled from six strictly ordered layers.
Layers are additive: each layer appends to the output of the layer below.
Only Layer 0 is assembled in the worker process; Layers 1–5 are assembled
in the provider process and arrive at the worker as `WorkerRequest.text`.

```
┌─────────────────────────────────────────────────────────┐
│ Layer 0 — Technical Wrapper (HIDDEN, worker-assembled)   │
│                                                         │
│  {BOS}                                                  │
│  {system_prompt}[{role_addendum}]                       │
│  {SEP}                                                  │
│  {task_instruction}                                     │
│  {output_policy}                                        │
│  {constraints}                                          │
│  \n\n                                                   │
│  {user_payload}                                         │
│  {TURN_END}                                             │
│                                  ← model generates here │
└─────────────────────────────────────────────────────────┘
```

### Layer 0 — Technical Wrapper
**Owner:** `worker_process._translate_transformers_causal`
**Visibility:** Never shown to users. Included in `EffectivePromptTrace.layer0_system_prompt`
only when debug tracing is active.
**Contents:**
- Model-family-specific BOS/SEP/TURN_END tokens (selected by `is_gptq`)
- `_HYMT_SYSTEM_PROMPT` — the global system prompt (persona + placeholder rule +
  output format contract)
- Optional `role_addendum` from the active policy (appended after system prompt,
  before SEP)

**Inviolable rule:** The placeholder protection instruction ("Preserve all placeholder
tokens HDLE_PH_N exactly as-is") lives in the system prompt and cannot be suppressed
or overridden by any policy, user setting, or debug option.

### Layer 1 — Role Addendum
**Owner:** `PromptPolicy.role_addendum`
**Purpose:** Specialise the model's persona for the content kind.
**Examples:**

| Profile | Role Addendum |
|---------|--------------|
| `lemma_ru` | `"You are a bilingual lexicographer. Output only the single most natural Russian equivalent."` |
| `term_ru_strict_glossary` | `"You are a technical translator. Prefer established terminology over novel equivalents."` |
| `sentence_ru` | *(empty — global system prompt is sufficient)* |

### Layer 2 — Task Instruction
**Owner:** `PromptPolicy.task_instruction`
**Purpose:** The "Translate …" directive in the user turn.
**Rendering position:** First line of `WorkerRequest.text`.
**Current default (all profiles unless overridden):**
```
Translate the following segment into Russian, without additional explanation.
```

### Layer 3 — Output Policy
**Owner:** `PromptPolicy.output_policy`
**Purpose:** Constrain the output format beyond what the system prompt specifies.
**Examples:**

| Profile | Output Policy |
|---------|--------------|
| `lemma_ru` | `"Output a single word or short phrase only. No explanation."` |
| `ui_string` | `"Output a single short string. No punctuation added unless present in the source."` |
| `sentence_ru` | *(empty)* |

### Layer 4 — Runtime Constraints
**Owner:** Populated at render time from `TranslationRequest.options`.
**Purpose:** Per-request constraints that cannot be profile-static.
**Sanitisation:** Free-text is stripped of newlines, truncated to 200 chars,
and may not contain `{`, `}`, `<`, `>` characters (injection prevention).
**Examples:**
- `"Max 5 words."`
- `"Output must begin with a capital letter."`

### Layer 5 — User Payload
**Owner:** Source text after placeholder protection + optional terminology line.
**Format (with glossary):**
```
Terminology: מחשב → компьютер, קובץ → файл.

{placeholder-protected source text}
```
**Format (no glossary):**
```
{placeholder-protected source text}
```

---

## 6. UI/UX Surface

The PPS exposes three UI modes.  Modes are orthogonal to provider selection
(a user can run either provider in any mode).

### Basic Mode (default)
- No PPS controls visible.
- Content kind is inferred automatically (see §10 Routing Rules).
- Sampling profile is fixed to profile default.
- Status bar shows: provider display name + latency.
- No prompt preview.

### Advanced Mode
- Dropdown: **Translation style** — shows `display_name` of available policies
  (excludes `experimental=True` policies).
- Info tooltip per policy: shows `description`.
- Status bar: adds `policy_id` + `terminology_mode` indicator.
- No raw prompt preview.

### Debug Mode
- All Advanced controls, plus:
- **Effective Prompt** panel (read-only, monospaced):
  - Shows `EffectivePromptTrace.rendered_user_content` (Layers 2–5).
  - Shows `EffectivePromptTrace.rendered_full_prompt` (all layers including L0),
    collapsed by default behind a "Show hidden wrapper" disclosure.
  - Colour-coded by layer: L0=grey, L1=blue, L2=green, L3=yellow, L4=orange, L5=white.
- **Model output** panel: raw decoded output before post-process.
- **Timing breakdown**: `inference_time_ms` vs `total_latency_ms`.
- **Glossary**: injected terms count + applied terms count.
- Debug mode is persisted in QSettings per provider and is off by default.

**Implementation note.** Debug mode populates `EffectivePromptTrace` — a significant
string allocation.  This is acceptable because Debug mode is never active in production
paths; the provider checks `trace_id != ""` or a debug flag before building the trace.

---

## 7. Production Profiles

Six named profiles cover all current and near-future content kinds for
Hebrew→Russian translation in HDLE.

### `sentence_ru` (default)
```
policy_id:           sentence_ru
display_name:        Standard Translation
content_kind:        SENTENCE
role_addendum:       ""
task_instruction:    "Translate the following segment into Russian,
                     without additional explanation."
output_policy:       ""
sampling_profile_id: hy_mt_precise_sentence
terminology_mode:    BOTH
experimental:        false
description:         "General-purpose translation for plain CAT segments.
                     Matches current production behaviour exactly."
```

### `sentence_ru_context`
```
policy_id:           sentence_ru_context
display_name:        Contextual Translation
content_kind:        SENTENCE_WITH_CONTEXT
role_addendum:       ""
task_instruction:    "Translate the following segment into Russian,
                     without additional explanation.
                     Use the surrounding context to resolve ambiguity."
output_policy:       ""
sampling_profile_id: hy_mt_precise_sentence
terminology_mode:    BOTH
experimental:        true
description:         "Includes ±2 surrounding segments as context.
                     Improves pronoun resolution and discourse cohesion."
```

### `sentence_ru_formatted`
```
policy_id:           sentence_ru_formatted
display_name:        Formatted Text Translation
content_kind:        SENTENCE_FORMATTED
role_addendum:       ""
task_instruction:    "Translate the following segment into Russian,
                     without additional explanation.
                     All placeholder tokens (HDLE_PH_1, HDLE_PH_2, …) must
                     appear in your output in the same relative order."
output_policy:       ""
sampling_profile_id: hy_mt_precise_formatted
terminology_mode:    BOTH
experimental:        false
description:         "For segments containing inline markup or format tokens.
                     Reinforces placeholder preservation in the task instruction."
```

### `lemma_ru`
```
policy_id:           lemma_ru
display_name:        Lemma / Dictionary Entry
content_kind:        LEMMA
role_addendum:       "You are a bilingual Hebrew–Russian lexicographer.
                     Output only the single most natural Russian equivalent
                     for the given Hebrew lemma."
task_instruction:    "Translate the following Hebrew lemma into Russian."
output_policy:       "Output a single word or short phrase only.
                     No grammatical commentary, no example sentences."
sampling_profile_id: hy_mt_precise_short
terminology_mode:    OFF
experimental:        false
description:         "Optimised for single dictionary headwords (1–3 Hebrew words).
                     Greedy decoding, max 16 tokens."
```

### `term_ru`
```
policy_id:           term_ru
display_name:        Technical Term
content_kind:        TERM
role_addendum:       "You are a technical translator specialised in Hebrew.
                     Output only the most established Russian equivalent."
task_instruction:    "Translate the following Hebrew technical term into Russian."
output_policy:       "Output a single noun phrase only. No article, no explanation."
sampling_profile_id: hy_mt_precise_short
terminology_mode:    PROMPT
experimental:        false
description:         "For multi-word technical terms. Glossary prompt injection
                     but no postprocess (term output is the result, not a segment)."
```

### `term_ru_strict_glossary`
```
policy_id:           term_ru_strict_glossary
display_name:        Technical Term (Strict Glossary)
content_kind:        TERM
role_addendum:       "You are a technical translator specialised in Hebrew.
                     Always use the exact approved Russian term from the provided
                     terminology list. Do not paraphrase."
task_instruction:    "Translate the following Hebrew technical term into Russian.
                     Use only the approved term from the Terminology list above."
output_policy:       "Output the approved term verbatim. No modification."
sampling_profile_id: hy_mt_precise_short
terminology_mode:    BOTH
experimental:        false
description:         "Strict glossary enforcement: model is instructed to copy
                     the approved term. Postprocess applies as safety net."
```

---

## 8. Rendering Rules

### 8.1 Visible Preview (Layers 2–5)
The provider renders `WorkerRequest.text` by concatenating:

```
{task_instruction}
{output_policy}          ← omitted if empty
{constraints}            ← omitted if empty
\n\n
{terminology_line}       ← omitted if no glossary terms
\n\n                     ← omitted if no terminology_line
{protected_source_text}
```

This is the string shown in the **Effective Prompt** panel (Debug mode, white region).

### 8.2 Hidden Technical Render (Layer 0, worker-assembled)
The worker assembles the full prompt from the received `user_content`:

**1.8B path:**
```
<｜hy_begin▁of▁sentence｜>{system_prompt}{role_addendum}<｜hy_place▁holder▁no▁3｜><｜hy_User｜>{user_content}<｜hy_Assistant｜>
```

**7B-GPTQ path:**
```
<|startoftext|>{system_prompt}{role_addendum}<|extra_4|>{user_content}<|extra_0|>
```

The `role_addendum` is passed from the provider as a prefix to `user_content`,
separated by a sentinel that the worker strips before template assembly.
(See §10 for the passing convention.)

### 8.3 Render Invariants

1. `_HYMT_SYSTEM_PROMPT` is prepended to every full prompt, regardless of profile.
   It may never be replaced or omitted.
2. The `role_addendum`, if present, is appended to the system prompt string
   before the SEP token.  It is part of the system turn, not the user turn.
3. The `task_instruction` is the first line of the user turn.  It must be a complete
   sentence ending with a period.
4. `{protected_source_text}` always appears last in the user content, after a
   mandatory double-newline separator from the task instruction block.
5. Glossary terminology line always precedes the source text and is separated from
   it by a double newline.

### 8.4 Role Addendum Passing Convention

Because the worker receives only `WorkerRequest.text`, the role addendum must be
conveyed as part of that string using an unambiguous sentinel header:

```
[ROLE_ADDENDUM]
{role_addendum_text}
[/ROLE_ADDENDUM]
{task_instruction}
...
{source_text}
```

The worker strips the `[ROLE_ADDENDUM]…[/ROLE_ADDENDUM]` block from `user_content`
and appends `role_addendum_text` to the system prompt before SEP.  If the block is
absent, no role addendum is injected (backwards compatible with current callers).

This sentinel approach avoids protocol-breaking changes to `WorkerRequest` and does
not require IPC schema migration.

---

## 9. Sampling Profiles

Three named profiles replace the current two hard-coded `gen_kwargs` blocks in
`_translate_transformers_causal`.

### `hy_mt_precise_sentence`
General-purpose sentence translation.  Current production defaults.

```yaml
profile_id: hy_mt_precise_sentence
display_name: Precise (Sentence)

params_1b8:
  max_new_tokens: 512
  do_sample: true
  top_k: 20
  top_p: 0.6
  temperature: 0.7
  repetition_penalty: 1.05

params_7b_gptq:
  max_new_tokens: 128
  do_sample: false
  # Rationale: ~0.6 s/token on RTX 3070; 128 × 0.6 = 76.8 s < 120 s timeout.
  # Greedy decoding is ~25% faster than sampling and appropriate for translation.
```

### `hy_mt_precise_short`
Short outputs: lemmas, terms, UI strings.  Tight token budget, greedy for both families.

```yaml
profile_id: hy_mt_precise_short
display_name: Precise (Short Output)

params_1b8:
  max_new_tokens: 32
  do_sample: false
  # Short content: greedy is deterministic and faster.

params_7b_gptq:
  max_new_tokens: 16
  do_sample: false
  # Lemmas rarely exceed 4 tokens; 16 is a safe upper bound.
```

### `hy_mt_precise_formatted`
Formatted text with placeholders.  Slightly lower temperature to reduce hallucination
of extra placeholder tokens.

```yaml
profile_id: hy_mt_precise_formatted
display_name: Precise (Formatted)

params_1b8:
  max_new_tokens: 512
  do_sample: true
  top_k: 10
  top_p: 0.5
  temperature: 0.5
  repetition_penalty: 1.1
  # Lower temperature + top_k → less creative, more conservative.
  # Reduces risk of generating spurious HDLE_PH tokens.

params_7b_gptq:
  max_new_tokens: 128
  do_sample: false
```

**Worker selection logic (replaces current `if is_gptq` block):**

```python
def _resolve_gen_kwargs(sampling_profile_id: str, is_gptq: bool) -> dict:
    profile = SAMPLING_PROFILES[sampling_profile_id]  # dict lookup, O(1)
    return profile.params_7b_gptq if is_gptq else profile.params_1b8
```

`SAMPLING_PROFILES` is a module-level dict, populated at import time from the
dataclass definitions above.  No I/O, no configuration files.

---

## 10. Routing and Fallback Rules

### 10.1 Profile Resolution Order

```
1. TranslationRequest.options["prompt_policy_id"]   → explicit override (Advanced/Debug UI)
2. ContentKind → default_profile table (below)      → automatic routing
3. "sentence_ru"                                    → global fallback
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

When the caller does not set `content_kind`, the provider infers it:

| Condition | Inferred Kind |
|-----------|---------------|
| Source text matches `_PH_PATTERN` at least once | `SENTENCE_FORMATTED` |
| Source text has no whitespace (single token) | `LEMMA` |
| Source text word count ≤ 4 | `TERM` |
| Otherwise | `SENTENCE` |

This inference is a **heuristic** — callers that know the content kind must set it
explicitly.  The heuristic fires only when `content_kind` is `None`.

### 10.3 Profile Fallback on Experimental

If the resolved profile has `experimental=True` and the UI mode is Basic, fall back
to `sentence_ru`.  Log a warning.

### 10.4 Model-Family Sampling Fallback

If the resolved `sampling_profile_id` is not found in `SAMPLING_PROFILES`, fall back
to `hy_mt_precise_sentence` and emit a warning in `meta["prompt_policy"]["warnings"]`.

---

## 11. Observability / Audit Contract

### 11.1 TranslationResult.meta Extension

Every successful translation from a HY-MT provider must include:

```python
meta["prompt_policy"] = {
    "policy_id": str,            # e.g. "sentence_ru"
    "sampling_profile_id": str,  # e.g. "hy_mt_precise_sentence"
    "content_kind": str,         # e.g. "sentence"
    "terminology_mode": str,     # e.g. "both"
    "injected_term_count": int,  # Terms in prompt
    "applied_term_count": int,   # Terms applied in postprocess
    "placeholder_count": int,    # Protected HDLE_PH_N tokens
    "missing_placeholders": list[str],  # [] on full success
    "warnings": list[str],       # Any policy resolution warnings
    "trace": EffectivePromptTrace | None,  # Only if tracing active
}
```

Fields already present in `meta` at the top level (`inference_time_ms`,
`applied_terms_count`, `placeholder_count`, `missing_placeholders`, `model_id`,
`backend`) are **preserved** for backwards compatibility and also duplicated inside
`meta["prompt_policy"]` for structured access.  No breaking change.

### 11.2 Logging Contract

| Event | Level | Fields |
|-------|-------|--------|
| Profile resolved | DEBUG | `policy_id`, `content_kind`, `source` (explicit/inferred/fallback) |
| Experimental profile in Basic mode | WARNING | `policy_id` |
| Role addendum injected | DEBUG | `policy_id`, `addendum_len` |
| Sampling profile fallback | WARNING | `requested_id`, `fallback_id` |
| Placeholder lost in translation | WARNING | `token`, `original` (existing) |
| Trace built | DEBUG | `policy_id`, `trace_size_bytes` |

All log records include `provider_id` and `trace_id` (when set) as structured fields
via `logger.debug("...", extra={"provider_id": ..., "trace_id": ...})`.

### 11.3 QA Regression Invariants

The following must hold across any PPS implementation:

1. `sentence_ru` + `hy_mt_precise_sentence` reproduces the **current** `_translate_transformers_causal` output bit-for-bit when no role addendum is present.
2. `meta["applied_terms_count"]` == `meta["prompt_policy"]["applied_term_count"]` (redundancy, not contradiction).
3. `meta["prompt_policy"]["missing_placeholders"]` is `[]` on any segment where all HDLE_PH_N tokens survived.
4. Any profile with `terminology_mode=OFF` must result in `injected_term_count=0` and `applied_term_count=0`.
5. `EffectivePromptTrace` is `None` when `trace_id == ""` and debug mode is off.

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
    "sampling_profile_id": "hy_mt_precise_formatted",
    "content_kind": "sentence_formatted",
    "terminology_mode": "both",
    "injected_term_count": 3,
    "applied_term_count": 2,
    "placeholder_count": 2,
    "missing_placeholders": [],
    "warnings": [],
    "trace": null
  }
}
```

### 12.3 EffectivePromptTrace (debug mode, trace_id="seg-00492")

```json
{
  "policy_id": "sentence_ru_formatted",
  "sampling_profile_id": "hy_mt_precise_formatted",
  "content_kind": "sentence_formatted",
  "layer0_system_prompt": "You are a translation engine specialized in Hebrew-to-Russian translation. Translate from Hebrew into Russian accurately and naturally. Preserve meaning, names, numbers, and formatting. Preserve all placeholder tokens (HDLE_PH_1, HDLE_PH_2, etc.) exactly as-is without any modification. Output only the Russian translation without explanations, comments, or extra text.",
  "layer1_role_addendum": "",
  "layer2_task_instruction": "Translate the following segment into Russian, without additional explanation. All placeholder tokens (HDLE_PH_1, HDLE_PH_2, …) must appear in your output in the same relative order.",
  "layer3_output_policy": "",
  "layer4_constraints": "",
  "layer5_user_payload": "Terminology: מחשב → компьютер, קובץ → файл, שרת → сервер.\n\nהוא שלח את HDLE_PH_1 לכתובת HDLE_PH_2.",
  "rendered_user_content": "Translate the following segment into Russian, without additional explanation. All placeholder tokens (HDLE_PH_1, HDLE_PH_2, …) must appear in your output in the same relative order.\n\nTerminology: מחשב → компьютер, קובץ → файл, שרת → сервер.\n\nהוא שלח את HDLE_PH_1 לכתובת HDLE_PH_2.",
  "rendered_full_prompt": "<|startoftext|>You are a translation engine…<|extra_4|>Translate the following segment…HDLE_PH_2.<|extra_0|>",
  "raw_model_output": "Он отправил HDLE_PH_1 на адрес HDLE_PH_2.",
  "final_translation": "Он отправил HDLE_PH_1 на адрес HDLE_PH_2.",
  "inference_time_ms": 4320.5,
  "total_latency_ms": 4480.0,
  "injected_term_count": 3,
  "applied_term_count": 2
}
```

### 12.4 PromptPolicy registry (YAML, stored as module-level data)

```yaml
profiles:
  - policy_id: sentence_ru
    display_name: Standard Translation
    content_kind: sentence
    role_addendum: ""
    task_instruction: >
      Translate the following segment into Russian,
      without additional explanation.
    output_policy: ""
    sampling_profile_id: hy_mt_precise_sentence
    terminology_mode: both
    experimental: false

  - policy_id: lemma_ru
    display_name: Lemma / Dictionary Entry
    content_kind: lemma
    role_addendum: >
      You are a bilingual Hebrew–Russian lexicographer.
      Output only the single most natural Russian equivalent
      for the given Hebrew lemma.
    task_instruction: Translate the following Hebrew lemma into Russian.
    output_policy: >
      Output a single word or short phrase only.
      No grammatical commentary, no example sentences.
    sampling_profile_id: hy_mt_precise_short
    terminology_mode: off
    experimental: false
```

---

## 13. Recommended Defaults

| Setting | Value | Rationale |
|---------|-------|-----------|
| Default profile (all contexts) | `sentence_ru` | Preserves current behaviour; zero regression risk |
| Default terminology mode | `BOTH` | Current production setting |
| Default sampling (1.8B) | `hy_mt_precise_sentence` | Current production parameters |
| Default sampling (7B-GPTQ) | `hy_mt_precise_sentence` | Greedy, 128 tokens — tested, within timeout |
| Debug mode | off | Performance; trace allocations are non-trivial |
| Content kind (not set by caller) | `SENTENCE` | Conservative; no heuristic inference by default |
| Heuristic inference | disabled by default | Enable only when caller is known to omit content_kind |
| Experimental profiles in Basic mode | blocked | Prevents accidental activation of unvalidated profiles |
| Role addendum max length | 512 chars | Prevent context-window pressure from very long addenda |
| Terminology injection max terms | 20 | Current `_fetch_glossary_terms_for_prompt` limit — preserved |
| Layer 4 constraint max length | 200 chars | Injection surface reduction |

---

## 14. Risks and Failure Modes

### R1: Role addendum sentinel collision
**Scenario:** Source text contains `[ROLE_ADDENDUM]` or `[/ROLE_ADDENDUM]` literally.
**Impact:** Worker strips legitimate source content.
**Mitigation:** Use a longer, improbable sentinel (e.g., `\x00ROLE_ADDENDUM\x00`) or
pass the role addendum as a separate field in `WorkerRequest` via a future IPC schema
extension.  The sentinel approach is a short-term workaround; the right fix is an IPC
extension.  Track in backlog.

### R2: `sentence_ru` regression if system prompt changes
**Scenario:** A future system prompt edit changes translation quality for the default profile.
**Impact:** Existing MT cache hits are invalidated silently (same cache key, different output).
**Mitigation:** Include a content-hash of `_HYMT_SYSTEM_PROMPT` in `get_model_version()`
return value so that cache keys are invalidated automatically on system prompt change.

### R3: Experimental profile activated in production via `options` override
**Scenario:** A caller injects `prompt_policy_id: sentence_ru_context` without the UI
setting it, bypassing the experimental guard.
**Impact:** Potentially lower quality or unexpected behaviour in batch translation.
**Mitigation:** Enforce experimental guard in the policy resolver (not just the UI).
Log a warning if an experimental profile is invoked without `trace_id` set.

### R4: `EffectivePromptTrace` memory growth in Debug mode
**Scenario:** Debug mode left enabled in a long batch translation session.
**Impact:** Each `TranslationResult.meta["prompt_policy"]["trace"]` holds full string copies
of the prompt.  At 1 KB per trace × 10,000 segments = ~10 MB retained in UI history.
**Mitigation:** Cap the UI-level trace history to the last 100 segments.  Emit a warning
in Debug mode if batch size exceeds 200.

### R5: Sampling profile mismatch between provider and worker
**Scenario:** Provider resolves `hy_mt_precise_short` but `max_new_tokens=16` is rejected
by the model (minimum not met).
**Impact:** Generation error, `WorkerResult.error` set.
**Mitigation:** Add a `validate()` method to `SamplingProfile` that checks parameter
ranges before the first use.  Called at startup (module import), not per-request.

### R6: `rendered_full_prompt` reconstruction is approximate
**Scenario:** Debug mode reconstructs the full prompt from known constants; actual
worker prompt may differ if worker logic diverges from documented template.
**Impact:** Misleading debug information.
**Mitigation:** Add a `--self-check` option to the worker that accepts a user_content
string and returns the full assembled prompt (as a special `type: "render_prompt"`
IPC message).  Used only in Debug mode to get the exact string from the worker.
Not needed for first implementation.

---

## 15. Definition of Done

### 15.1 Functional Acceptance Criteria

- [ ] All six production profiles are defined and loadable without I/O at import time.
- [ ] `sentence_ru` + `hy_mt_precise_sentence` produces **identical output** to the
      current implementation for all existing test fixtures (zero delta against MT cache).
- [ ] `lemma_ru` produces single-word output for ≥ 90% of test lemma inputs (measured
      on `tests/fixtures/lemma_he_ru_sample.jsonl` — to be created).
- [ ] `sentence_ru_formatted` preserves all HDLE_PH_N placeholders in correct order
      on all existing `test_local_hymt_7b_gptq_provider.py` test cases.
- [ ] Content kind inference correctly classifies ≥ 95% of inputs in `tests/fixtures/content_kind_sample.jsonl` (to be created).
- [ ] `EffectivePromptTrace` is `None` for all calls with `trace_id=""`.
- [ ] `EffectivePromptTrace` is populated for all calls with `trace_id != ""`.
- [ ] `meta["prompt_policy"]["policy_id"]` is present on every successful `TranslationResult`.
- [ ] Experimental profile blocked in Basic mode (policy resolver, not just UI).
- [ ] Role addendum sentinel roundtrip works correctly for all six profile definitions.

### 15.2 Regression Criteria

- [ ] All 35 existing `test_local_hymt_7b_gptq_provider.py` tests pass unchanged.
- [ ] All existing provider tests pass (`tests/test_providers_setup.py` or equivalent).
- [ ] `python -m pytest -v` exits 0.
- [ ] `python -c "from app.infra.translators.providers.local_hymt_provider import LocalHYMTProvider; print('OK')"` succeeds.

### 15.3 Performance Criteria

- [ ] Profile resolution adds < 0.1 ms to `translate()` critical path (measured with `timeit`, no I/O).
- [ ] `EffectivePromptTrace` construction adds < 1 ms when trace is active.
- [ ] No additional worker IPC round-trips introduced in the normal (non-debug) path.

### 15.4 Safety Criteria

- [ ] `_HYMT_SYSTEM_PROMPT` placeholder protection instruction appears in 100% of assembled prompts regardless of profile, UI mode, or debug state.
- [ ] Layer 4 constraint input is sanitised (newlines stripped, length capped, injection chars rejected) before inclusion in any prompt.
- [ ] No user-supplied string can appear before Layer 0 in the assembled prompt.

### 15.5 Docs Criteria

- [ ] `AUDIT_HY-MT-provider.md` §3 (Architecture) updated to reference PPS layers.
- [ ] `docs/HY_MT_PROMPT_POLICY_SPEC.md` (this document) committed and linked from AUDIT index.
- [ ] Inline docstrings on `PromptPolicy`, `SamplingProfile`, `PromptRenderer` classes.
- [ ] Debug mode UI documented in user-facing help text.

### 15.6 Patch Series

```
PATCH-01: Domain model + registry (PromptPolicy, SamplingProfile, enums)
          Files: app/infra/translators/prompt_policy.py (new)
          Tests: tests/test_prompt_policy_registry.py (new)
          DoD:   All six profiles load; sentence_ru is default; no I/O at import.

PATCH-02: PromptRenderer + role addendum passing
          Files: app/infra/translators/prompt_policy.py (render methods)
                 worker_process._translate_transformers_causal (sentinel parsing)
          Tests: tests/test_prompt_renderer.py (new, source inspection)
          DoD:   sentence_ru renders identically to current code; role addendum
                 roundtrip verified for lemma_ru.

PATCH-03: Provider integration (content kind routing, meta extension)
          Files: local_hymt_provider.translate() (policy resolution + meta)
                 local_hymt_7b_gptq_provider (inherits, no change)
          Tests: Extend test_local_hymt_7b_gptq_provider.py; add
                 test_local_hymt_provider_policy.py
          DoD:   meta["prompt_policy"] present; all regression tests pass.

PATCH-04: Worker sampling profile lookup (replaces hard-coded gen_kwargs)
          Files: worker_process._translate_transformers_causal
                 worker_process.SAMPLING_PROFILES (new module-level dict)
          Tests: Source inspection tests (no torch import)
          DoD:   hy_mt_precise_sentence produces identical gen_kwargs to current code.

PATCH-05: EffectivePromptTrace + Debug mode UI
          Files: app/infra/translators/prompt_policy.py (EffectivePromptTrace)
                 UI: provider settings dialog or dedicated debug panel
          Tests: tests/test_effective_prompt_trace.py (no torch)
          DoD:   Trace is None when trace_id=""; populated with correct fields otherwise.
```

---

*End of Specification*
