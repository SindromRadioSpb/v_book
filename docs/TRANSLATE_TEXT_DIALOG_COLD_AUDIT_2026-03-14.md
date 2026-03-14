# Translate Text Dialog Cold Audit (2026-03-14)

## Why this document exists

This is the twenty-fourth task-specific use of the canonical cold-audit
framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- `TranslateTextDialog` cold open / first usable state

This wave does **not**:

- open a runtime repair branch;
- reinterpret actual translation execution as open-time cost;
- audit MT provider latency or cache lookup performance;
- audit translation-result UX after worker completion;
- open heavy validation.

## Scope

In scope:

- `TranslateTextDialog` cold open with representative initial text and default
  language selection
- eager `TranslationService()` construction in the dialog constructor
- language-combo population and initial widget state
- blocker vs not-blocker classification

Out of scope:

- `on_translate()`
- `SingleTextTranslateWorker` execution time
- provider/network latency
- translation semantics, caching, or glossary behavior

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `TTD1` | Remaining dialog-surface candidate selection | prior bounded sweep evidence | Confirms why this is the next narrow wave after pronunciation bootstrap dialog | Completed |
| `TTD2` | Full `TranslateTextDialog()` cold open | representative initial text + current repo code | Measures the actual visible constructor/open contract | Completed |
| `TTD3` | Language-combo and widget-state restore | representative initial text + current repo code | Confirms first usable state without translation execution | Completed |
| `TTD4` | Eager service-construction audit | `TranslationService.__init__()` contract | Separates open cost from provider runtime work | Completed |
| `TTD5` | Worker presence on open | current repo code | Confirms whether translation starts before explicit user action | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/translate_text_dialog.py`
- `app/services/translation_service.py`
- `app/ui/workers.py`

Current smoke/regression entry points:

- `tests/test_translate_text_dialog_lifecycle.py`

Evidence artifacts:

- `build/logs/cold_audit/candidate_sweep/remaining_dialog_surfaces_2026-03-13.json`
- `build/logs/cold_audit/translate_text_dialog/translate_text_dialog_probe.json`
- `build/logs/cold_audit/translate_text_dialog/translate_text_dialog_cold_audit_summary.json`

## Current UI/workflow contract

Current `TranslateTextDialog` open path:

- `TranslateTextDialog.__init__()` performs:
  - eager `TranslationService()` construction
  - request-sequence state initialization
  - `init_ui()`
- `TranslationService.__init__()` performs:
  - `SettingsService.get_instance()`
  - circuit-breaker setup
  - rate-limiter setup
- `init_ui()` performs:
  - language-combo population for `12` source languages and `12` target languages
  - input/output/editor widget construction
  - translate/progress/cancel/metadata widget initialization

Engineering meaning:

- the dialog does some real constructor work on open;
- that work is still local and bounded;
- no translation worker starts on open.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Translate-text dialog open was separated from actual MT execution. | Completed |
| `2. Cold vs warm measurement` | Fresh offscreen probe used representative initial text and current repo code. | Completed |
| `3. Step-by-step cold breakdown` | Full init and initial widget state were isolated together. | Completed |
| `4. SQL-level timing / query audit` | Open path exposes no DB-heavy query layer. | Completed |
| `5. Service/process timing` | Eager `TranslationService()` construction is part of open but remains bounded. | Completed |
| `6. Filesystem / OS / DB-open audit` | Open path does not perform provider/network/DB work. | Completed |
| `7. UI first-render / first-usable-state audit` | Dialog is usable immediately on open. | Completed |
| `8. Degraded / fallback mode audit` | Dialog degrades to idle metadata state before any translation is requested. | Completed |
| `9. Dataset-tier analysis` | Open cost does not depend on corpus scale. | Completed |
| `10. Repeatability protocol` | Commands below reproduce the same bounded result. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `TTD1`-`TTD5` were fixed before interpretation. | Prevented mixing dialog open with MT runtime cost. |
| `B. Bounded live probes` | Dedicated representative probe captured the real constructor/open contract. | Current evidence, not assumption. |
| `C. SQL top offenders log` | No SQL exists on open. | This is not a DB-latency branch. |
| `D. UI responsiveness probes` | Full dialog init is `0.198s`. | Open is already bounded. |
| `E. Service initialization audit` | Eager `TranslationService()` construction is the meaningful open-time dependency. | Still not a blocker. |
| `F. Drift / fallback path audit` | The original sweep undercounted this path; the dedicated probe corrected it. | Prevented under-reporting the real open contract. |
| `G. Before/after evidence protocol` | This is an audit-only wave. | No repair branch is opened. |

## Current findings

### Candidate-selection context

From `remaining_dialog_surfaces_2026-03-13.json`:

- `translate_text_dialog`: `0.006s`

Engineering meaning:

- after the pronunciation-bootstrap wave, `TranslateTextDialog` was the last
  remaining dialog candidate from that bounded sweep;
- the dedicated follow-up was required because the coarse sweep undercounted the
  real open contract;
- the dedicated probe then confirmed that the dialog is still not a blocker.

### Dedicated open timings

From `translate_text_dialog_probe.json`:

- full `TranslateTextDialog` init: `0.198s`
- source-language count: `12`
- target-language count: `12`
- representative initial text length: `9`
- selected source language: `he`
- selected target language: `en`
- `Translate` enabled: `true`
- `Copy to Clipboard` enabled: `false`
- progress visible on open: `false`
- cancel visible on open: `false`
- metadata label on open:
  - `No translation yet`
- `has_worker_on_open = false`

Engineering meaning:

- the dialog shell is already bounded and usable immediately;
- eager service construction and language-combo population are still cheap;
- no hidden translation worker starts before explicit user action.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- full cold open is only `0.198s`;
- no worker or provider test starts on open;
- there is no corpus-scale or DB dependency on open;
- no UX evidence justifies a repair branch.

## Reopen gate

Keep the `TranslateTextDialog` cold-open branch closed.

Reopen only if a new evidence gate confirms one of:

- provider/network preflight work is moved into constructor/open path;
- eager service construction becomes materially slower on real operator targets;
- open begins depending on DB-backed capability discovery.

Do not reopen this as a generic MT-provider latency branch without separate
evidence.

What remains closed:

- startup cold-path branch
- picker cold-path branch
- Sentences filtered-tail branch
- Dictionary search/FTS branch
- Terms cold-path branch
- Concordance dependency-health branch
- TM residual count-tail branch
- Coverage lemma-count residual-tail branch
- Audio Add-All branch
- generic Documents branch
- ProjectView branch
- standalone `Term Cards` branch
- `VerificationPanel` branch
- `UserDictionariesView` branch
- `DatabaseSwitchDialog` branch
- MT `ProviderSettingsDialog` branch
- `ResourcesManagerDialog` branch
- `ImportWizard` branch
- generic first-run branch
- `AudioProviderSettingsDialog` branch
- `SentenceNiqqudBootstrapDialog` branch
- `CommandPaletteDialog` branch
- `PronunciationBootstrapDialog` branch
