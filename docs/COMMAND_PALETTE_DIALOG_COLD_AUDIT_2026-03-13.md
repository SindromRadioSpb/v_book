# Command Palette Dialog Cold Audit (2026-03-13)

## Why this document exists

This is the twenty-second task-specific use of the canonical cold-audit
framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- `CommandPaletteDialog` cold open / first usable state

This wave does **not**:

- open a runtime repair branch;
- reinterpret full app startup as command-palette open cost;
- audit action callback execution;
- audit fuzzy-search quality beyond bounded open/search timing;
- open heavy validation.

## Scope

In scope:

- `CommandPaletteDialog` cold open with the representative real action-set
  contract from `AppWindow._register_actions()`
- initial `_perform_search("")` path on open
- lightweight in-memory filter path for one representative query
- blocker vs not-blocker classification

Out of scope:

- full `AppWindow` startup cost
- action callback side effects
- hidden action enable/disable drift outside the palette itself
- command-palette keyboard UX redesign

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `CP1` | Remaining dialog-surface candidate selection | current machine + bounded sweep evidence | Confirms why this is the next narrow wave after sentence niqqud dialog | Completed |
| `CP2` | Full `CommandPaletteDialog()` cold open | representative `AppWindow` action registry contract | Measures the actual visible open contract | Completed |
| `CP3` | Initial empty-query population | representative `AppWindow` action registry contract | Confirms whether open is gated by initial results build | Completed |
| `CP4` | Representative search filter | representative `AppWindow` action registry contract | Confirms whether live query filtering is a meaningful cold layer | Completed |
| `CP5` | Registry shape confirmation | `AppWindow._register_actions()` contract | Prevents auditing an empty/artificial palette state | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/command_palette.py`
- `app/ui/app_window.py`

Current smoke/regression entry points:

- `tests/test_p1_command_palette.py`

Evidence artifacts:

- `build/logs/cold_audit/candidate_sweep/remaining_dialog_surfaces_2026-03-13.json`
- `build/logs/cold_audit/command_palette_dialog/command_palette_dialog_probe.json`
- `build/logs/cold_audit/command_palette_dialog/command_palette_dialog_cold_audit_summary.json`

Current representative action-set contract:

- `AppWindow._register_actions()` currently registers `16` actions
- categories represented:
  - `Tools`
  - `Premium`
  - `Help`
  - `View`
  - `Navigate`

## Current UI/workflow contract

Current `CommandPaletteDialog` open path:

- `CommandPaletteDialog.__init__()` performs:
  - singleton registry lookup
  - `init_ui()`
- `init_ui()` performs:
  - search input creation
  - results list creation
  - status label creation
  - immediate `_perform_search("")`
- `_perform_search("")` performs:
  - `registry.search("")`
  - result-list rebuild
  - first-row auto-selection

Engineering meaning:

- the palette open path is fully in-memory and synchronous;
- no DB, worker, or filesystem work exists on open;
- the real open contract depends on the registry size/shape from `AppWindow`,
  not on a blank test harness.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Command palette open was separated from app startup and action callbacks. | Completed |
| `2. Cold vs warm measurement` | Dedicated representative-action-set probe used current repo code. | Completed |
| `3. Step-by-step cold breakdown` | Full init, initial population, and one representative filter pass were isolated. | Completed |
| `4. SQL-level timing / query audit` | No SQL layer exists on open. | Completed |
| `5. Service/process timing` | No service/worker startup exists on open. | Completed |
| `6. Filesystem / OS / DB-open audit` | Open path does not depend on DB or filesystem I/O. | Completed |
| `7. UI first-render / first-usable-state audit` | Palette becomes usable immediately after bounded in-memory population. | Completed |
| `8. Degraded / fallback mode audit` | Empty or smaller registries degrade to fewer results, not blocked open. | Completed |
| `9. Dataset-tier analysis` | Registry size is small and bounded by application actions, not corpus scale. | Completed |
| `10. Repeatability protocol` | Commands below reproduce the same bounded result. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `CP1`-`CP5` were fixed before interpretation. | Prevented mixing palette open with app-start costs. |
| `B. Bounded live probes` | Representative 16-action probe captured the real open/search contract. | Current evidence, not assumption. |
| `C. SQL top offenders log` | No SQL exists on open. | This is not a DB-latency branch. |
| `D. UI responsiveness probes` | Full dialog init is `0.128s`. | Open is already bounded. |
| `E. Service initialization audit` | Initial empty-query population for `16` actions is still tiny. | No hidden startup dependency. |
| `F. Drift / fallback path audit` | Initial sweep used an empty registry; this wave corrected that with the real registry contract. | Prevented under/over-claiming from an artificial state. |
| `G. Before/after evidence protocol` | This is an audit-only wave. | No repair branch is opened. |

## Current findings

### Candidate-selection context

From `remaining_dialog_surfaces_2026-03-13.json`:

- `command_palette_dialog`: `0.021s`
- `pronunciation_bootstrap_dialog`: `0.011s`
- `translate_text_dialog`: `0.006s`

Engineering meaning:

- after the sentence-niqqud wave, `CommandPaletteDialog` remained the largest
  untriaged dialog candidate from the bounded remaining-dialog sweep;
- the original sweep used an empty registry and therefore needed a dedicated
  representative-action-set follow-up;
- the dedicated probe then confirmed that the real palette contract is still
  not a blocker.

### Representative-action-set timings

From `command_palette_dialog_probe.json`:

- full `CommandPaletteDialog` init: `0.128s`
- registry actions: `16`
- initial results count: `16`
- initial status label:
  - `16 action(s)`
- representative search query:
  - `audio`
- search filter time: `0.001s`
- search results count: `2`
- search status label:
  - `2 action(s)`
- top filtered result:
  - `Audio Provider Settings (Ctrl+Alt+A) — Tools`

Engineering meaning:

- initial population on open is already bounded;
- representative live filtering is effectively instant;
- command palette open/search is not the next cold bottleneck.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- full cold open is `0.128s` with the real 16-action contract;
- representative filtering is `0.001s`;
- there is no DB, worker, or large-scale corpus dependency on open;
- no UX evidence justifies a repair branch.

## Reopen gate

Keep the `CommandPaletteDialog` cold-open branch closed.

Reopen only if a new evidence gate confirms one of:

- the registered action set grows materially and open/search cost regresses;
- synchronous callback preflight work is moved into palette open;
- palette open begins depending on DB or filesystem-backed action discovery.

Do not reopen this as a generic app-startup branch without separate evidence.

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
