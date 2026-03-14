# Reference Setup Wizard Cold Audit (2026-03-14)

## Why this document exists

This is the twenty-fifth task-specific use of the canonical cold-audit
framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- `ReferenceSetupWizard` cold open / first usable state

This wave does **not**:

- open a runtime repair branch;
- reinterpret background download/local-process execution as open-time cost;
- audit dataset download speed or local processing throughput;
- reopen first-run wizard work;
- open heavy validation.

## Scope

In scope:

- `ReferenceSetupWizard` cold open with representative `work_dir` / `db_path`
- shell/page construction
- default mode selection and initial button state
- worker presence on open
- blocker vs not-blocker classification

Out of scope:

- `_start_setup()`
- `SetupWorker.run()`
- `ReferenceDownloadService` runtime download path
- `LocalProcessingService.run_full_pipeline()` runtime behavior

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `RSW1` | Remaining visible-candidate selection | prior bounded sweep evidence | Confirms why this is the next narrow wave after the dialog sweep completed | Completed |
| `RSW2` | Full `ReferenceSetupWizard()` cold open | representative local `work_dir` / `db_path` | Measures the actual visible constructor/open contract | Completed |
| `RSW3` | Initial page/button state audit | representative local `work_dir` / `db_path` | Confirms immediate usability before any setup action | Completed |
| `RSW4` | Default mode audit | representative local `work_dir` / `db_path` | Confirms initial operator path on open | Completed |
| `RSW5` | Worker presence on open | current repo code | Confirms whether setup starts before explicit user action | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/reference_setup_wizard.py`
- `app/services/reference_setup/__init__.py`

Current smoke/regression entry points:

- `tests/test_reference_corpus_guards.py`
- `tests/test_reference_ro_mode.py`

Evidence artifacts:

- `build/logs/cold_audit/candidate_sweep/remaining_visible_surfaces_2026-03-13.json`
- `build/logs/cold_audit/reference_setup_wizard/reference_setup_wizard_probe.json`
- `build/logs/cold_audit/reference_setup_wizard/reference_setup_wizard_cold_audit_summary.json`

## Current UI/workflow contract

Current `ReferenceSetupWizard` open path:

- `ReferenceSetupWizard.__init__()` performs:
  - `work_dir` / `db_path` assignment
  - initial `selected_mode = "download"`
  - `_init_ui()`
- `_init_ui()` performs:
  - stacked page construction for:
    - welcome
    - progress
    - complete
  - button row construction
  - initial button-state wiring
- no worker starts on open:
  - `SetupWorker` is created only by `_start_setup()`
  - `_start_setup()` is reached only after explicit `Next`

Engineering meaning:

- the wizard shell is already first-usable immediately on open;
- no download or local-processing work starts before explicit user action;
- open-time latency is not driven by corpus setup runtime paths.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Wizard open was separated from actual setup execution. | Completed |
| `2. Cold vs warm measurement` | Fresh offscreen probe used representative local paths and current repo code. | Completed |
| `3. Step-by-step cold breakdown` | Full init and initial page/button state were isolated together. | Completed |
| `4. SQL-level timing / query audit` | Open path exposes no SQL layer. | Completed |
| `5. Service/process timing` | Download/local-process services are not started on open. | Completed |
| `6. Filesystem / OS / DB-open audit` | Open path uses local paths only as stored constructor inputs. | Completed |
| `7. UI first-render / first-usable-state audit` | Wizard is usable immediately on page `0`. | Completed |
| `8. Degraded / fallback mode audit` | Open degrades to a static shell if setup is never started. | Completed |
| `9. Dataset-tier analysis` | Open cost does not scale with corpus size because no setup work starts on open. | Completed |
| `10. Repeatability protocol` | Commands below reproduce the same bounded result. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `RSW1`-`RSW5` were fixed before interpretation. | Prevented mixing wizard open with long setup runtime. |
| `B. Bounded live probes` | Dedicated representative probe captured the real constructor/open contract. | Current evidence, not assumption. |
| `C. SQL top offenders log` | No SQL exists on open. | This is not a DB-latency branch. |
| `D. UI responsiveness probes` | Full wizard init is `0.224s`. | Open is already bounded. |
| `E. Service initialization audit` | Setup services are not instantiated into active runtime work on open. | No hidden heavy stage exists here. |
| `F. Drift / fallback path audit` | The original sweep undercounted this path; the dedicated probe corrected it. | Prevented under-reporting the real open contract. |
| `G. Before/after evidence protocol` | This is an audit-only wave. | No repair branch is opened. |

## Current findings

### Candidate-selection context

From `remaining_visible_surfaces_2026-03-13.json`:

- `reference_setup_wizard`: `0.017s`
- `help_center`: `0.006s`

Engineering meaning:

- after the bounded dialog sweep was exhausted, `ReferenceSetupWizard`
  remained the next largest unformalized visible candidate from the prior
  remaining-visible sweep;
- the dedicated follow-up was required because the coarse sweep undercounted
  the real shell-construction cost;
- the dedicated probe then confirmed that the wizard is still not a blocker.

### Dedicated open timings

From `reference_setup_wizard_probe.json`:

- full `ReferenceSetupWizard` init: `0.224s`
- page count: `3`
- current page on open: `0`
- selected mode on open: `download`
- `Next` enabled: `true`
- `Back` enabled: `false`
- `Cancel` enabled: `true`
- `has_worker_on_open = false`
- window title:
  - `Hebrew Wikipedia Setup`

Engineering meaning:

- the wizard shell is already bounded and usable immediately;
- open-time state is deterministic and lightweight;
- no hidden setup worker starts before explicit operator action.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- full cold open is only `0.224s`;
- no worker or setup runtime path starts on open;
- there is no DB or network dependency on first usable state;
- no UX evidence justifies a repair branch.

## Reopen gate

Keep the `ReferenceSetupWizard` cold-open branch closed.

Reopen only if a new evidence gate confirms one of:

- download/local-process preflight work moves into constructor/open path;
- open begins doing filesystem/network validation synchronously;
- first usable state regresses materially on real operator targets.

Do not reopen this as a generic reference-setup throughput branch without
separate evidence.

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
- `TranslateTextDialog` branch
