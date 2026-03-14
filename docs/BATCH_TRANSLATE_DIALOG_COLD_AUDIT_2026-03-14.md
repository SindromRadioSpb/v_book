# Batch Translate Dialog Cold Audit (2026-03-14)

## Why this document exists

This is the twenty-ninth task-specific use of the canonical cold-audit
framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- `BatchTranslateDialog` cold open / first usable state

This wave does **not**:

- open a runtime repair branch;
- reinterpret batch translation worker execution as dialog open cost;
- audit `TranslateAllFilteredWorker` chunk execution;
- audit MT provider/network latency;
- open heavy validation.

## Scope

In scope:

- `BatchTranslateDialog` cold open with representative saved settings
- scope-group rendering when `scope_enabled=True`
- persisted provider/write-mode restore from `SettingsService`
- blocker vs not-blocker classification

Out of scope:

- `BatchTranslateWorker`
- `TranslateAllFilteredWorker`
- `open_settings()` and full provider-settings dialog work
- batch translation result UX after dialog acceptance

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `BTD1` | Remaining cold-candidate selection | current repo entry points | Confirms why this is the next narrow wave after the about-action wave | Completed |
| `BTD2` | Full `BatchTranslateDialog()` cold open | representative saved settings + scope enabled | Measures the actual user-visible constructor/open contract | Completed |
| `BTD3` | Persisted settings restore | `SettingsService` + current repo code | Confirms whether open hides synchronous config hydration | Completed |
| `BTD4` | Scope UI materialization | representative selected/filtered counts | Confirms whether all-filtered scope UI changes the cold-open profile | Completed |
| `BTD5` | Hidden worker/service startup check | current repo code | Confirms whether translation starts before explicit user action | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/dialogs/batch_translate_dialog.py`
- `app/infra/settings.py`

Current smoke/regression entry points:

- `tests/test_task15_translate_scope.py`
- `tests/test_translate_scope_ui_parity.py`
- `tests/test_tm_panel_translate_selected.py`

Evidence artifacts:

- `build/logs/cold_audit/batch_translate_dialog/batch_translate_dialog_probe.json`
- `build/logs/cold_audit/batch_translate_dialog/batch_translate_dialog_cold_audit_summary.json`

## Current UI/workflow contract

Current `BatchTranslateDialog` open path:

- `BatchTranslateDialog.__init__()` performs:
  - `SettingsService.get_instance()`
  - `init_ui()`
  - `load_settings()`
- `init_ui()` performs:
  - local widget construction only
  - optional scope-group construction when `scope_enabled=True`
  - static provider-combo population
- `load_settings()` performs:
  - `QSettings` reads for provider mode
  - `QSettings` reads for write mode
  - `QSettings` read for remember-choice state

Engineering meaning:

- the dialog open path is local and synchronous;
- there is no DB, worker, or network dependency on open;
- translation execution still begins only after explicit acceptance.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Batch-translate dialog open was separated from translation execution. | Completed |
| `2. Cold vs warm measurement` | Dedicated representative probe used current saved settings and current repo code. | Completed |
| `3. Step-by-step cold breakdown` | Constructor, UI build, and settings restore were isolated together. | Completed |
| `4. SQL-level timing / query audit` | Open path exposes no SQL layer. | Completed |
| `5. Service/process timing` | Only `SettingsService` / `QSettings` hydration occurs on open. | Completed |
| `6. Filesystem / OS / DB-open audit` | Open path does not depend on DB open, provider credentials, or workers. | Completed |
| `7. UI first-render / first-usable-state audit` | Dialog is usable immediately on open. | Completed |
| `8. Degraded / fallback mode audit` | Missing/unknown saved values degrade to defaults, not blocked open. | Completed |
| `9. Dataset-tier analysis` | Open cost does not depend on corpus scale. | Completed |
| `10. Repeatability protocol` | Commands below reproduce the same bounded result. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `BTD1`-`BTD5` were fixed before interpretation. | Prevented mixing dialog open with translation runtime work. |
| `B. Bounded live probes` | Representative settings-enabled probe captured the real open contract. | Current evidence, not assumption. |
| `C. SQL top offenders log` | No SQL exists on open. | This is not a DB-latency branch. |
| `D. UI responsiveness probes` | Full dialog init is `0.206s`. | Open is already bounded. |
| `E. Service initialization audit` | Settings restore and static combo population remain cheap. | No hidden provider bootstrap exists on open. |
| `F. Drift / fallback path audit` | Representative saved settings were restored correctly. | Prevented auditing only the default-empty state. |
| `G. Before/after evidence protocol` | This is an audit-only wave. | No repair branch is opened. |

## Current findings

### Dedicated open timings

From `batch_translate_dialog_probe.json`:

- full `BatchTranslateDialog` init: `0.206s`
- representative selected rows: `25`
- representative filtered count: `387,639`
- scope enabled: `true`
- window title:
  - `Batch Translate Selected Rows`
- restored provider mode:
  - `force:google_cloud_translate`
- restored write mode:
  - `OVERWRITE`
- initial scope:
  - `current_page`
- remember choices:
  - `true`
- provider combo enabled:
  - `true`
- provider combo current text:
  - `google_cloud_translate`
- `Translate` enabled:
  - `true`
- `has_worker_on_open = false`

Engineering meaning:

- the dialog shell is already bounded and usable immediately;
- saved-choice restoration does not create a hidden cold blocker;
- no translation worker or provider preflight starts on open.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- full representative cold open is only `0.206s`;
- there is no DB, worker, or network dependency on open;
- open work is limited to local widget construction and `QSettings` restore;
- no UX evidence justifies a repair branch.

## Reopen gate

Keep the `BatchTranslateDialog` cold-open branch closed.

Reopen only if a new evidence gate confirms one of:

- provider or credential preflight is moved into dialog constructor/open path;
- dynamic provider discovery on open becomes materially slower on real targets;
- dialog open begins depending on DB-backed count resolution or worker startup.

Do not reopen this as a generic batch-translation throughput branch without
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
- `ReferenceSetupWizard` branch
- `HelpCenterDialog` branch
- `System Health Check` trigger-path branch
- `About HDLE Premium` trigger-path branch
- `BatchTranslateDialog` cold-open branch
