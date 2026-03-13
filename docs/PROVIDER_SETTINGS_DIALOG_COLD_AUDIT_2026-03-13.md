# Provider Settings Dialog Cold Audit (2026-03-13)

## Why this document exists

This is the sixteenth task-specific use of the canonical cold-audit framework
in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- `ProviderSettingsDialog` cold open / first usable state

This wave does **not**:

- open a runtime repair branch;
- reinterpret provider credential-health drift as a cold-latency blocker;
- audit provider API test calls;
- open heavy validation.

## Scope

In scope:

- `ProviderSettingsDialog` cold open with current saved provider settings
- sync advanced-settings load path for `google_cloud_translate`
- blocker vs not-blocker classification
- distinction between cold-open latency and credential-health drift

Out of scope:

- `_test_gcp_connection()`
- credential repair / re-encryption workflows
- audio provider settings dialog

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `PS1` | Full `ProviderSettingsDialog()` cold open | current settings + approved hewiki test DB via read-only wrapper | Measures the actual visible open contract | Completed |
| `PS2` | GCP advanced settings load | current settings + approved hewiki test DB via read-only wrapper | Confirms whether credential preview is the gating open layer | Completed |
| `PS3` | Warning-log capture during open | current settings + approved hewiki test DB via read-only wrapper | Distinguishes cold latency from credential-health drift | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/provider_settings_dialog.py`
- `app/infra/translators/provider_config_manager.py`
- `app/infra/security/credentials.py`

Current smoke/regression entry points:

- `tests/test_provider_settings_dialog.py`
- `tests/test_provider_config.py`

Evidence artifacts:

- `build/logs/cold_audit/candidate_sweep/candidate_sweep_2026-03-13.json`
- `build/logs/cold_audit/provider_settings_dialog/provider_settings_dialog_probe.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- strict read-only wrapper used for credential-store reads during the probe

## Current UI/workflow contract

Current `ProviderSettingsDialog` cold-open path:

- `ProviderSettingsDialog.__init__()` performs:
  - `_init_ui()`
  - `_load_settings()`
- `_load_settings()` performs:
  - master/provider toggle restore from settings
  - chain restore from settings
  - `_load_gcp_advanced_settings()`
- `_load_gcp_advanced_settings()` performs:
  - sync limits/retry UI restore
  - sync credential preview load through `ProviderConfigManager.get_credential()`

Engineering meaning:

- the open path does include one synchronous credential-preview check;
- that check is not materially expensive in current evidence;
- any decrypt failure seen on open is a dependency-health issue, not a cold
  latency blocker.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Dialog open was separated from provider test-call workflows. | Completed |
| `2. Cold vs warm measurement` | Fresh offscreen probe used current saved settings and current repo code. | Completed |
| `3. Step-by-step cold breakdown` | Full init and advanced-settings credential preview were isolated together. | Completed |
| `4. SQL-level timing / query audit` | Open path does not expose a heavy SQL layer. | Completed |
| `5. Service/process timing` | Sync credential preview stayed bounded. | Completed |
| `6. Filesystem / OS / DB-open audit` | Approved DB remained unchanged under read-only wrapper access. | Completed |
| `7. UI first-render / first-usable-state audit` | Dialog becomes usable immediately after a bounded open. | Completed |
| `8. Degraded / fallback mode audit` | Decrypt failure degrades into preview text plus warning log, not a blocked open. | Completed |
| `9. Dataset-tier analysis` | Dataset scale is irrelevant; this is settings + credential metadata work. | Completed |
| `10. Repeatability protocol` | Commands below reproduce the same bounded result. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `PS1`-`PS3` were fixed before interpretation. | Prevented mixing dialog open with provider API tests. |
| `B. Bounded live probes` | Strict read-only offscreen probe captured the real open contract with current settings. | Current evidence, not assumption. |
| `C. SQL top offenders log` | No meaningful DB-heavy offender appeared during open. | This is not a DB-latency branch. |
| `D. UI responsiveness probes` | Full dialog init is `0.117s`. | Cold open is already bounded. |
| `E. Service initialization audit` | Current settings resolve `auth_mode=service_account_json` with a configured credential ID. | The only visible drift is credential health, not UI open time. |
| `F. Drift / fallback path audit` | Credential decrypt fails and preview falls back to `No Service Account JSON configured`. | This is a separate health gate, not a cold blocker. |
| `G. Before/after evidence protocol` | This is an audit-only wave. | No repair branch is opened. |

## Current findings

### Approved-target timings

From `provider_settings_dialog_probe.json`:

- full `ProviderSettingsDialog` init: `0.117s`
- chain rows after init: `7`
- master enabled state: `true`

Engineering meaning:

- cold open is already bounded well below blocker range;
- the dialog does not justify a latency repair branch.

### Credential-health drift observed during open

From `provider_settings_dialog_probe.json`:

- current settings auth mode: `service_account_json`
- current settings credential ID:
  - `mt_provider:google_cloud_translate:service_account_json`
- preview text after open:
  - `No Service Account JSON configured`
- warning log emitted during open:
  - `Failed to get credential mt_provider:google_cloud_translate:service_account_json: Failed to decrypt credential: Decryption failed: authentication tag invalid (data corrupted or tampered)`

Engineering meaning:

- there is a real provider credential-health issue in the current environment;
- it is not a cold-open latency issue;
- any follow-up here should be a separate provider-credential health decision
  gate, not a performance repair branch.

### Selection context

The bounded candidate sweep for still-untriaged surfaces recorded:

- `provider_settings_dialog`: `0.119s`
- `resources_manager_dialog`: `0.035s`
- `import_wizard`: `0.007s`

Engineering meaning:

- `ProviderSettingsDialog` was the next remaining visible candidate after
  `DatabaseSwitchDialog`;
- the dedicated probe then confirmed it is not a blocker.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- full cold open is `0.117s`;
- current sync credential-preview check is bounded;
- the real issue surfaced during open is credential-health drift, not latency;
- no cold-open UX evidence justifies a repair branch.

## Reopen gate

Keep the `ProviderSettingsDialog` cold-open branch closed.

Reopen only if a new evidence gate confirms one of:

- dialog open becomes materially slower on real operator targets;
- provider test/preflight work is moved into constructor/open path;
- additional sync credential/network checks are added to open.

Credential-health follow-up, if needed, must be opened separately and only as:

- provider credential-store / decrypt-health investigation

not as a `ProviderSettingsDialog` cold-latency branch.

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
- Documents view branch
- ProjectView branch
- standalone `Term Cards` branch
- `VerificationPanel` branch
- `UserDictionariesView` branch
- `DatabaseSwitchDialog` branch

The next active engineering action is therefore:

- return to the canonical cold-audit framework for the next narrow subsystem
  wave, unless new approved-target evidence promotes a new blocker

## Verification notes

```powershell
New-Item -ItemType Directory -Force build\logs\cold_audit\provider_settings_dialog | Out-Null

New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'

.\.venv\Scripts\python.exe -m pytest tests\test_provider_settings_dialog.py tests\test_provider_config.py -q

.\.venv\Scripts\python.exe -c "import app; from app.ui.provider_settings_dialog import ProviderSettingsDialog; print('OK')"
```

Approved-target evidence for this wave was collected through strict read-only
wrappers only; no source/reference DB mutation was performed.
