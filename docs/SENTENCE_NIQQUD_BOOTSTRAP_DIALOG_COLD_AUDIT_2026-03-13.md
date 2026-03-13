# Sentence Niqqud Bootstrap Dialog Cold Audit (2026-03-13)

## Why this document exists

This is the twenty-first task-specific use of the canonical cold-audit
framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- `SentenceNiqqudBootstrapDialog` cold open / first usable state

This wave does **not**:

- open a runtime repair branch;
- reinterpret explicit health-check execution as open-time cost;
- audit the lexical `PronunciationBootstrapDialog`;
- audit the bootstrap write path itself;
- open heavy validation.

## Scope

In scope:

- `SentenceNiqqudBootstrapDialog` cold open with bounded sample ids
- sync constructor path and cached settings restore
- distinction between cached health-state rendering and active health-check work
- blocker vs not-blocker classification

Out of scope:

- `_run_health_check()`
- `_on_run()`
- `PhonikudHealthCheckWorker` execution time after an explicit user click
- sentence niqqud DB write throughput

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `SNB1` | Remaining dialog-surface candidate selection | current machine + bounded sweep evidence | Confirms why this is the next narrow wave after audio provider settings | Completed |
| `SNB2` | Full `SentenceNiqqudBootstrapDialog()` cold open | bounded ids + current saved settings | Measures the actual visible constructor/open contract | Completed |
| `SNB3` | Settings restore breakdown | bounded ids + current saved settings | Confirms whether `_load_settings()` adds meaningful sync cost | Completed |
| `SNB4` | Default-scope selection on open | bounded ids | Confirms open-time usability and scope defaults | Completed |
| `SNB5` | Worker presence on open | bounded ids + current repo code | Confirms whether background/bootstrap work starts before user action | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/dialogs/sentence_niqqud_bootstrap_dialog.py`
- `app/ui/dialogs/pronunciation_bootstrap_dialog.py`
- `app/ui/workers.py`

Current smoke/regression entry points:

- `tests/test_audio_player_go_to_source.py`
- `tests/test_user_dictionaries_context_menu.py`

Evidence artifacts:

- `build/logs/cold_audit/candidate_sweep/remaining_dialog_surfaces_2026-03-13.json`
- `build/logs/cold_audit/sentence_niqqud_bootstrap_dialog/sentence_niqqud_bootstrap_dialog_probe.json`
- `build/logs/cold_audit/sentence_niqqud_bootstrap_dialog/sentence_niqqud_bootstrap_dialog_cold_audit_summary.json`

## Current UI/workflow contract

Current `SentenceNiqqudBootstrapDialog` open path:

- `SentenceNiqqudBootstrapDialog.__init__()` performs:
  - `_init_ui()`
  - `_load_settings()`
- `_load_settings()` performs:
  - cached enable/model-path restore
  - cached last health result render when present
- no worker starts on open:
  - `_run_health_check()` starts only after explicit `Health Check`
  - `_on_run()` starts only after explicit `Run Bootstrap`

Engineering meaning:

- the dialog shell is already first-usable immediately on open;
- cached health labels are cheap and do not imply a live probe;
- open-time latency is not driven by phonikud inference/bootstrap work.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Sentence niqqud dialog open was separated from explicit health-check and run flows. | Completed |
| `2. Cold vs warm measurement` | Fresh offscreen probe used current saved settings and current repo code. | Completed |
| `3. Step-by-step cold breakdown` | Full init and `_load_settings()` were isolated together. | Completed |
| `4. SQL-level timing / query audit` | Open path exposes no DB-heavy query layer. | Completed |
| `5. Service/process timing` | No background process/service is started on open. | Completed |
| `6. Filesystem / OS / DB-open audit` | Open path stays within settings/cached-state work. | Completed |
| `7. UI first-render / first-usable-state audit` | Dialog is usable immediately on open. | Completed |
| `8. Degraded / fallback mode audit` | Cached health state degrades to static labels if no fresh check is run. | Completed |
| `9. Dataset-tier analysis` | Bounded ids are enough because open cost does not scale with sentence volume. | Completed |
| `10. Repeatability protocol` | Commands below reproduce the same bounded result. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `SNB1`-`SNB5` were fixed before interpretation. | Prevented mixing dialog open with bootstrap execution. |
| `B. Bounded live probes` | Dedicated offscreen probe captured the real constructor/open contract. | Current evidence, not assumption. |
| `C. SQL top offenders log` | No meaningful SQL work exists on open. | This is not a DB-latency branch. |
| `D. UI responsiveness probes` | Full dialog init is only `0.020s`. | Open is already bounded. |
| `E. Service initialization audit` | `_load_settings()` is `0.000s`. | Settings restore is negligible. |
| `F. Drift / fallback path audit` | Health labels come from cached last result and no worker starts on open. | Cached health state is not a hidden live-probe path. |
| `G. Before/after evidence protocol` | This is an audit-only wave. | No repair branch is opened. |

## Current findings

### Candidate-selection context

From `remaining_dialog_surfaces_2026-03-13.json`:

- `sentence_niqqud_bootstrap_dialog`: `0.039s`
- `command_palette_dialog`: `0.021s`
- `pronunciation_bootstrap_dialog`: `0.011s`
- `translate_text_dialog`: `0.006s`

Engineering meaning:

- after the audio-provider-settings wave, the bounded remaining-dialog sweep
  still pointed to `SentenceNiqqudBootstrapDialog` as the largest untriaged
  dialog surface;
- the dedicated probe then confirmed that this surface is still not a blocker.

### Dedicated open timings

From `sentence_niqqud_bootstrap_dialog_probe.json`:

- full `SentenceNiqqudBootstrapDialog` init: `0.020s`
- `_load_settings()`: `0.000s`
- `selected_ids`: `1`
- `page_ids`: `2`
- `all_ids`: `3`
- default scope on open: `selected`
- `Run Bootstrap` enabled: `true`
- health mode label after cached restore:
  - `Mode: real_inference (ok)`
- health details label after cached restore:
  - `Local ONNX probe passed. | latency=0ms`

Open-time worker state:

- `has_worker_on_open`: `false`
- `has_health_worker_on_open`: `false`

Engineering meaning:

- the dialog shell is already bounded and usable immediately;
- cached health-state rendering is cheap;
- no hidden bootstrap or health-check worker is started before explicit user
  action.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- full cold open is only `0.020s`;
- `_load_settings()` is effectively `0.000s`;
- no worker or bootstrap process starts on open;
- no UX evidence justifies a repair branch.

## Reopen gate

Keep the `SentenceNiqqudBootstrapDialog` cold-open branch closed.

Reopen only if a new evidence gate confirms one of:

- active health-check work is moved into constructor/open path;
- bootstrap preflight or row-collection work starts automatically on open;
- new dialog-open dependencies materially increase first usable state time.

Do not reopen this as a generic sentence-niqqud throughput or write-path branch
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
