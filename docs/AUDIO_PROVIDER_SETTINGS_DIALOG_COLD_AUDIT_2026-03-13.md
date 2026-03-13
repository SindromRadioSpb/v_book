# Audio Provider Settings Dialog Cold Audit (2026-03-13)

## Why this document exists

This is the twentieth task-specific use of the canonical cold-audit framework
in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- `AudioProviderSettingsDialog` cold open / first usable state

This wave does **not**:

- open a runtime repair branch;
- reinterpret current-machine credential drift as a cold-latency blocker;
- audit provider connection tests or pronunciation bootstrap dialogs;
- reopen the already-closed MT `ProviderSettingsDialog` branch;
- open heavy validation.

## Scope

In scope:

- `AudioProviderSettingsDialog` cold open with current saved audio settings
- synchronous advanced-settings load path for `google_cloud_tts`
- usage-summary load for the initially selected advanced provider
- blocker vs not-blocker classification
- distinction between cold-open latency and credential-health drift

Out of scope:

- `_test_provider_connection()`
- credential repair / re-encryption workflows
- pronunciation bootstrap dialog flows
- audio generation or playback runtime behavior

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `APS1` | Remaining-surface candidate selection | current machine + prior bounded sweep evidence | Confirms why this is the next dialog wave after first-run repair | Completed |
| `APS2` | Full `AudioProviderSettingsDialog()` cold open | current settings + approved hewiki test DB via read-only wrapper | Measures the actual visible open contract | Completed |
| `APS3` | Advanced-settings load breakdown | current settings + approved hewiki test DB via read-only wrapper | Isolates sync preview/restore work | Completed |
| `APS4` | Current-usage label refresh on open | current settings + approved hewiki test DB via read-only wrapper | Confirms whether usage tracking is a gating layer | Completed |
| `APS5` | Warning-log capture during open | current settings + approved hewiki test DB via read-only wrapper | Distinguishes latency from credential-health drift | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/audio_provider_settings_dialog.py`
- `app/infra/audio/audio_provider_config_manager.py`
- `app/services/audio_usage_tracker.py`
- `app/ui/dialogs/mms_license_gate_dialog.py`

Current smoke/regression entry points:

- `tests/test_audio_provider_config_manager.py`
- `tests/test_audio_usage_tracker.py`
- `tests/test_mms_license_gate.py`

Evidence artifacts:

- `build/logs/cold_audit/candidate_sweep/remaining_visible_surfaces_2026-03-13.json`
- `build/logs/cold_audit/audio_provider_settings_dialog/audio_provider_settings_dialog_probe.json`
- `build/logs/cold_audit/audio_provider_settings_dialog/audio_provider_settings_dialog_cold_audit_summary.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- strict read-only wrapper used for credential-store and usage-summary reads

## Current UI/workflow contract

Current `AudioProviderSettingsDialog` cold-open path:

- `AudioProviderSettingsDialog.__init__()` performs:
  - `_init_ui()`
  - `_load_settings()`
- `_load_settings()` performs:
  - master/provider toggle restore from settings
  - chain restore from settings
  - `_load_google_advanced_settings()`
  - `_load_azure_advanced_settings()`
  - `_load_mms_advanced_settings()`
  - playback settings restore
  - `_on_advanced_provider_changed(...)`
- the initial advanced-provider change triggers `_refresh_usage(provider_id)`
  for the currently selected provider

Engineering meaning:

- the dialog does include synchronous config, credential-preview, and usage-label
  work on open;
- no provider connection test or pronunciation bootstrap action runs on open;
- any decrypt failure seen on open is a dependency-health issue, not by itself
  a latency blocker.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Audio provider settings open was separated from first-run wizard and provider connection tests. | Completed |
| `2. Cold vs warm measurement` | Fresh offscreen probe used current saved settings and current repo code. | Completed |
| `3. Step-by-step cold breakdown` | Full init, advanced-settings load, and usage refresh were isolated together. | Completed |
| `4. SQL-level timing / query audit` | Open path does not expose a heavy SQL layer. | Completed |
| `5. Service/process timing` | Sync credential preview load was identified as the dominant open-time substep. | Completed |
| `6. Filesystem / OS / DB-open audit` | Approved DB remained unchanged under read-only wrapper access. | Completed |
| `7. UI first-render / first-usable-state audit` | Dialog becomes usable immediately after a bounded open. | Completed |
| `8. Degraded / fallback mode audit` | Credential decrypt failure degrades into preview fallback plus warning log, not a blocked open. | Completed |
| `9. Dataset-tier analysis` | Dataset scale is irrelevant; this is settings/credential metadata work. | Completed |
| `10. Repeatability protocol` | Commands below reproduce the same bounded result. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `APS1`-`APS5` were fixed before interpretation. | Prevented mixing audio settings open with test-call flows. |
| `B. Bounded live probes` | Strict read-only offscreen probe captured the real open contract with current settings. | Current evidence, not assumption. |
| `C. SQL top offenders log` | Usage-summary load is only `0.001s`. | This is not a DB-latency branch. |
| `D. UI responsiveness probes` | Full dialog init is `0.138s`. | Cold open is already bounded. |
| `E. Service initialization audit` | `_load_google_advanced_settings()` is the dominant open-time substep at `0.104s`. | Even the slowest sync stage is still not a blocker. |
| `F. Drift / fallback path audit` | Current-machine credential decrypt fails and preview falls back to `No Service Account JSON configured`. | This is a separate credential-health gate, not a cold blocker. |
| `G. Before/after evidence protocol` | This is an audit-only wave. | No repair branch is opened. |

## Current findings

### Candidate-selection context

From `remaining_visible_surfaces_2026-03-13.json`:

- `audio_provider_settings`: `0.121s`
- `reference_setup_wizard`: `0.017s`
- `help_center`: `0.006s`

Engineering meaning:

- after first-run repair, `AudioProviderSettingsDialog` remained the next
  largest still-untriaged visible surface from the bounded sweep;
- the dedicated probe then confirmed that it is still not a blocker.

### Current-machine dedicated timings

From `audio_provider_settings_dialog_probe.json`:

- full `AudioProviderSettingsDialog` init: `0.138s`
- `_load_settings()`: `0.106s`
- `_load_google_advanced_settings()`: `0.104s`
- `_load_azure_advanced_settings()`: `0.001s`
- `_load_mms_advanced_settings()`: `0.000s`
- `_refresh_usage("google_cloud_tts")`: `0.001s`

Current bounded state after open:

- tab count: `4`
- chain rows: `5`
- master enabled: `true`
- advanced-provider rows: `3`
- initially selected advanced provider: `google_cloud_tts`

Engineering meaning:

- the open path is already bounded;
- Google credential preview dominates the dialog init cost, but only at
  `0.104s`;
- usage-summary load is negligible.

### Dependency-health drift observed during open

From `audio_provider_settings_dialog_probe.json`:

- Google preview after open:
  - `No Service Account JSON configured`
- Azure preview after open:
  - `No API key configured`
- MMS license state:
  - `Not accepted`
- open-time warning log:
  - `Failed to read credential audio_provider:google_cloud_tts:service_account_json: Failed to decrypt credential: Decryption failed: authentication tag invalid (data corrupted or tampered)`

Engineering meaning:

- there is a real current-machine audio credential-health issue;
- it is not a cold-open latency issue;
- any follow-up here should be a separate audio credential/decrypt-health gate,
  not a `AudioProviderSettingsDialog` performance branch.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- full cold open is `0.138s`;
- the slowest sync substep is still only `0.104s`;
- the real issue surfaced during open is credential-health drift, not latency;
- no cold-open UX evidence justifies a repair branch.

## Reopen gate

Keep the `AudioProviderSettingsDialog` cold-open branch closed.

Reopen only if a new evidence gate confirms one of:

- dialog open becomes materially slower on real operator targets;
- provider test/preflight work moves into constructor/open path;
- new sync credential or usage workflows are added to open.

Audio credential-health follow-up, if needed, must be opened separately and
only as:

- audio provider credential-store / decrypt-health investigation

not as a `AudioProviderSettingsDialog` cold-latency branch.

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
- `ReferenceSetupWizard` branch
- `HelpCenterDialog` branch
- generic first-run branch

The next active engineering action is therefore:

- return to the canonical cold-audit framework for the next narrow subsystem
  wave, unless new approved-target evidence promotes a new blocker

## Verification notes

```powershell
New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'

.\.venv\Scripts\python.exe -m pytest tests\test_audio_provider_config_manager.py tests\test_audio_usage_tracker.py tests\test_mms_license_gate.py -q

.\.venv\Scripts\python.exe -c "import app; from app.ui.audio_provider_settings_dialog import AudioProviderSettingsDialog; print('OK')"

rg -n "AUDIO_PROVIDER_SETTINGS_DIALOG_COLD_AUDIT_2026-03-13.md|0\\.138s|0\\.104s|priority = P3|audio credential-store / decrypt-health investigation" docs\AUDIO_PROVIDER_SETTINGS_DIALOG_COLD_AUDIT_2026-03-13.md docs\ENGINEERING_CONTROL_OPTIMIZATION_ROADMAP_2026-03-11.md
```

Expected bounded outcomes:

- `AudioProviderSettingsDialog` remains formally classified as `not blocker`;
- the real follow-up, if ever needed, stays a separate credential-health gate;
- approved DB evidence remains read-only.
