# Pronunciation Bootstrap Dialog Cold Audit (2026-03-14)

## Why this document exists

This is the twenty-third task-specific use of the canonical cold-audit
framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- `PronunciationBootstrapDialog` cold open / first usable state

This wave does **not**:

- open a runtime repair branch;
- reinterpret explicit health-check or bootstrap execution as open-time cost;
- audit bootstrap write throughput;
- reopen sentence-niqqud dialog work;
- open heavy validation.

## Scope

In scope:

- `PronunciationBootstrapDialog` cold open with a representative selected-items
  contract
- sync constructor path and cached settings restore
- source-group toggle restoration from selected items
- distinction between cached health-state rendering and active worker execution
- blocker vs not-blocker classification

Out of scope:

- `_run_health_check()`
- `_run_bootstrap()`
- `PhonikudHealthCheckWorker` execution time after explicit user action
- `PronunciationBootstrapWorker` throughput and write behavior

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `PBD1` | Remaining dialog-surface candidate selection | prior bounded sweep evidence | Confirms why this is the next narrow wave after command palette | Completed |
| `PBD2` | Full `PronunciationBootstrapDialog()` cold open | representative selected-items contract + current saved settings | Measures the actual visible constructor/open contract | Completed |
| `PBD3` | Settings restore breakdown | representative selected-items contract + current saved settings | Confirms whether `_load_settings()` adds meaningful sync cost | Completed |
| `PBD4` | Selection-scope and source toggle restore | representative selected-items contract | Confirms immediate usability and default source-state correctness | Completed |
| `PBD5` | Worker presence on open | current repo code | Confirms whether health/bootstrap work starts before user action | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/dialogs/pronunciation_bootstrap_dialog.py`
- `app/ui/workers.py`

Current smoke/regression entry points:

- `tests/test_pronunciation_bootstrap_ui_wiring.py`
- `tests/test_user_dictionaries_context_menu.py`
- `tests/test_dictionary_audio_context_menu.py`

Evidence artifacts:

- `build/logs/cold_audit/candidate_sweep/remaining_dialog_surfaces_2026-03-13.json`
- `build/logs/cold_audit/pronunciation_bootstrap_dialog/pronunciation_bootstrap_dialog_probe.json`
- `build/logs/cold_audit/pronunciation_bootstrap_dialog/pronunciation_bootstrap_dialog_cold_audit_summary.json`

## Current UI/workflow contract

Current `PronunciationBootstrapDialog` open path:

- `PronunciationBootstrapDialog.__init__()` performs:
  - selected-items normalization
  - `_init_ui()`
  - `_load_settings()`
- `_init_ui()` performs:
  - shell/widget construction
  - optional selection-scope label render
  - initial source-checkbox state derived from selected items
- `_load_settings()` performs:
  - cached enable/model-path restore
  - cached last health result render when present
- no worker starts on open:
  - `_run_health_check()` starts only after explicit `Health Check`
  - `_run_bootstrap()` starts only after explicit `Run Bootstrap`

Engineering meaning:

- the dialog shell is already first-usable immediately on open;
- cached health labels are cheap and do not imply a live probe;
- open-time latency is not driven by phonikud health/bootstrap work.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Pronunciation bootstrap dialog open was separated from explicit health-check and bootstrap runs. | Completed |
| `2. Cold vs warm measurement` | Fresh offscreen probe used current saved settings and representative selected items. | Completed |
| `3. Step-by-step cold breakdown` | Full init and `_load_settings()` were isolated together. | Completed |
| `4. SQL-level timing / query audit` | Open path exposes no DB-heavy query layer. | Completed |
| `5. Service/process timing` | No background process/service is started on open. | Completed |
| `6. Filesystem / OS / DB-open audit` | Open path stays within settings/cached-state and in-memory selection work. | Completed |
| `7. UI first-render / first-usable-state audit` | Dialog is usable immediately on open. | Completed |
| `8. Degraded / fallback mode audit` | Cached health state degrades to static labels if no fresh check is run. | Completed |
| `9. Dataset-tier analysis` | Representative selected items are enough because open cost does not scale with corpus volume. | Completed |
| `10. Repeatability protocol` | Commands below reproduce the same bounded result. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `PBD1`-`PBD5` were fixed before interpretation. | Prevented mixing dialog open with bootstrap execution. |
| `B. Bounded live probes` | Dedicated representative-selection probe captured the real constructor/open contract. | Current evidence, not assumption. |
| `C. SQL top offenders log` | No meaningful SQL work exists on open. | This is not a DB-latency branch. |
| `D. UI responsiveness probes` | Full dialog init is `0.115s`. | Open is already bounded. |
| `E. Service initialization audit` | `_load_settings()` is effectively `0.000s`. | Settings restore is negligible. |
| `F. Drift / fallback path audit` | Health labels come from cached last result and no worker starts on open. | Cached health state is not a hidden live-probe path. |
| `G. Before/after evidence protocol` | This is an audit-only wave. | No repair branch is opened. |

## Current findings

### Candidate-selection context

From `remaining_dialog_surfaces_2026-03-13.json`:

- `pronunciation_bootstrap_dialog`: `0.011s`
- `translate_text_dialog`: `0.006s`

Engineering meaning:

- after the command-palette wave, `PronunciationBootstrapDialog` remained the
  next largest untriaged dialog candidate from the bounded remaining-dialog
  sweep;
- the dedicated representative-selection probe then confirmed that this
  surface is still not a blocker.

### Dedicated open timings

From `pronunciation_bootstrap_dialog_probe.json`:

- full `PronunciationBootstrapDialog` init: `0.115s`
- `_load_settings()`: `0.000s`
- representative selected items: `3`
- selection scope text:
  - `Selection scope: 3 row(s) from current table.`
- source toggles on open:
  - `include_lemmas = true`
  - `include_terms = true`
  - `include_user_dictionary = true`
  - `include_sentences = false`
- `Run Bootstrap` enabled: `true`
- health mode label after cached restore:
  - `Mode: real_inference (ok)`
- health details label after cached restore:
  - `Local ONNX probe passed. | latency=0ms`

Open-time worker state:

- `has_health_worker_on_open = false`
- `has_bootstrap_worker_on_open = false`

Engineering meaning:

- the dialog shell is already bounded and usable immediately;
- representative selection-state restore is cheap;
- no hidden health or bootstrap worker is started before explicit user action.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- full cold open is only `0.115s`;
- `_load_settings()` is effectively `0.000s`;
- representative selection-state restore is bounded;
- no worker or bootstrap process starts on open;
- no UX evidence justifies a repair branch.

## Reopen gate

Keep the `PronunciationBootstrapDialog` cold-open branch closed.

Reopen only if a new evidence gate confirms one of:

- active health-check work is moved into constructor/open path;
- bootstrap preflight or selection materialization starts automatically on open;
- new dialog-open dependencies materially increase first usable state time.

Do not reopen this as a generic pronunciation throughput or write-path branch
without separate evidence.

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
