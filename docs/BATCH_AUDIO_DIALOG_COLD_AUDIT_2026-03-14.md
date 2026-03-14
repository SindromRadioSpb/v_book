# Batch Audio Dialog Cold Audit (2026-03-14)

## Why this document exists

This is the thirtieth task-specific use of the canonical cold-audit
framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- `BatchAudioDialog` cold open / first usable state

This wave does **not**:

- open a runtime repair branch;
- reinterpret batch audio worker execution as dialog open cost;
- audit `BatchGenerateAudioWorker` throughput;
- audit audio-provider runtime latency;
- open heavy validation.

## Scope

In scope:

- `BatchAudioDialog` cold open with representative saved settings
- scope-group rendering when `scope_enabled=True`
- synchronous `list_available_audio_providers()` work on open
- persisted provider/write-mode restore from `SettingsService`
- blocker vs not-blocker classification

Out of scope:

- `BatchGenerateAudioWorker`
- audio asset generation/write throughput
- `show_audio_provider_settings()`
- `ensure_mms_license_accepted()` acceptance flow after user submit

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `BAD1` | Remaining cold-candidate selection | current repo entry points | Confirms why this is the next narrow wave after batch translate dialog | Completed |
| `BAD2` | Full `BatchAudioDialog()` cold open | representative saved settings + scope enabled | Measures the actual user-visible constructor/open contract | Completed |
| `BAD3` | Audio-provider list hydration | `list_available_audio_providers()` + current repo code | Confirms whether provider registration creates hidden open-time cost | Completed |
| `BAD4` | Persisted settings restore | `SettingsService` + current repo code | Confirms whether open hides synchronous config hydration | Completed |
| `BAD5` | Hidden worker/service startup check | current repo code | Confirms whether generation starts before explicit user action | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/dialogs/batch_audio_dialog.py`
- `app/services/audio_generation_service.py`
- `app/infra/settings.py`

Current smoke/regression entry points:

- `tests/test_batch_audio_dialog.py`
- `tests/test_mms_license_gate.py`

Evidence artifacts:

- `build/logs/cold_audit/batch_audio_dialog/batch_audio_dialog_probe.json`
- `build/logs/cold_audit/batch_audio_dialog/batch_audio_dialog_cold_audit_summary.json`

## Current UI/workflow contract

Current `BatchAudioDialog` open path:

- `BatchAudioDialog.__init__()` performs:
  - `SettingsService.get_instance()`
  - `_init_ui()`
  - `_load_settings()`
- `_init_ui()` performs:
  - local widget construction only
  - optional scope-group construction when `scope_enabled=True`
  - `list_available_audio_providers()` for provider combo population
- `_load_settings()` performs:
  - `QSettings` reads for provider mode
  - `QSettings` reads for write mode
  - `QSettings` read for remember-choice state

Engineering meaning:

- the dialog open path is local and synchronous;
- provider-list hydration is registry-based, not DB-backed;
- audio generation still begins only after explicit acceptance.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Batch-audio dialog open was separated from batch audio execution. | Completed |
| `2. Cold vs warm measurement` | Dedicated representative probe used current saved settings and current repo code. | Completed |
| `3. Step-by-step cold breakdown` | Constructor, UI build, provider-list hydration, and settings restore were isolated together. | Completed |
| `4. SQL-level timing / query audit` | Open path exposes no SQL layer. | Completed |
| `5. Service/process timing` | Only provider-registry hydration plus `QSettings` restore occurs on open. | Completed |
| `6. Filesystem / OS / DB-open audit` | Open path does not depend on DB open, network, or worker startup. | Completed |
| `7. UI first-render / first-usable-state audit` | Dialog is usable immediately on open. | Completed |
| `8. Degraded / fallback mode audit` | Empty provider registry degrades to `mock_local_audio`, not blocked open. | Completed |
| `9. Dataset-tier analysis` | Open cost does not depend on corpus scale. | Completed |
| `10. Repeatability protocol` | Commands below reproduce the same bounded result. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `BAD1`-`BAD5` were fixed before interpretation. | Prevented mixing dialog open with audio-generation runtime work. |
| `B. Bounded live probes` | Representative settings-enabled probe captured the real open contract. | Current evidence, not assumption. |
| `C. SQL top offenders log` | No SQL exists on open. | This is not a DB-latency branch. |
| `D. UI responsiveness probes` | Full dialog init is `0.187s`. | Open is already bounded. |
| `E. Service initialization audit` | Provider-registry listing and settings restore remain cheap. | No hidden provider bootstrap exists on open. |
| `F. Drift / fallback path audit` | Representative saved settings were restored correctly. | Prevented auditing only the default-empty state. |
| `G. Before/after evidence protocol` | This is an audit-only wave. | No repair branch is opened. |

## Current findings

### Dedicated open timings

From `batch_audio_dialog_probe.json`:

- full `BatchAudioDialog` init: `0.187s`
- representative selected rows: `25`
- representative filtered count: `387,639`
- scope enabled: `true`
- window title:
  - `Batch Generate Source Audio`
- restored provider mode:
  - `force:google_cloud_tts`
- restored write mode:
  - `REGENERATE_ALL`
- initial scope:
  - `current_page`
- remember choices:
  - `true`
- provider combo enabled:
  - `true`
- provider combo current text:
  - `google_cloud_tts`
- provider count:
  - `5`
- `has_worker_on_open = false`

Engineering meaning:

- the dialog shell is already bounded and usable immediately;
- provider-list hydration does not create a hidden cold blocker;
- no generation worker or provider preflight starts on open.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- full representative cold open is only `0.187s`;
- there is no DB, worker, or network dependency on open;
- open work is limited to local widget construction, provider-registry listing,
  and `QSettings` restore;
- no UX evidence justifies a repair branch.

## Reopen gate

Keep the `BatchAudioDialog` cold-open branch closed.

Reopen only if a new evidence gate confirms one of:

- provider discovery on open becomes materially slower on real targets;
- credential/license/provider preflight is moved into dialog constructor/open
  path;
- dialog open begins depending on DB-backed scope/count resolution or worker
  startup.

Do not reopen this as a generic audio-generation throughput branch without
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
- `BatchAudioDialog` cold-open branch
