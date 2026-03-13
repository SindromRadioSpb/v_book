# Resources Manager Dialog Cold Audit (2026-03-13)

## Why this document exists

This is the seventeenth task-specific use of the canonical cold-audit framework
in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- `ResourcesManagerDialog` cold open / first usable state

This wave does **not**:

- audit download throughput;
- audit baseline import execution time;
- reopen model-install or health-check worker branches;
- open heavy validation.

## Scope

In scope:

- `ResourcesManagerDialog()` cold open on the current machine state
- `ResourceRegistry.list_entries()` + `get_status()` breakdown
- blocker vs not-blocker classification

Out of scope:

- `ResourceDownloadWorker`
- `ProjectImportWorker`
- `UnifiedHealthCheckWorker`
- network transfer, checksum-heavy large downloads, or baseline import workflows

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `RM1` | Full `ResourcesManagerDialog()` cold open | current local resource state | Measures the actual visible dialog-open contract | Completed |
| `RM2` | `ResourceRegistry.list_entries()` breakdown | current local resource state | Confirms manifest parsing cost | Completed |
| `RM3` | Per-entry `get_status()` breakdown | current local resource state | Confirms whether status resolution hides a filesystem tail | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/resources_manager_dialog.py`
- `app/services/resources/resource_registry.py`
- `app/ui/app_window.py`

Current smoke/regression entry points:

- `tests/test_resource_registry.py`

Evidence artifacts:

- `build/logs/cold_audit/candidate_sweep/candidate_sweep_2026-03-13.json`
- `build/logs/cold_audit/resources_manager_dialog/resources_manager_dialog_probe.json`
- `build/logs/cold_audit/resources_manager_dialog/resources_manager_registry_probe.json`

Target state:

- current local data-root and manifest state
- no approved DB dependency is involved in this open path

## Current UI/workflow contract

Current `ResourcesManagerDialog` cold-open path:

- `ResourcesManagerDialog.__init__()` performs:
  - `_init_ui()`
  - `_load_data_root()`
  - `refresh_resources()`
- `refresh_resources()` performs:
  - `registry.list_entries()`
  - `registry.get_status(entry.id)` for each manifest row
  - sync table population
- heavy operations are not started on open:
  - downloads run only through `ResourceDownloadWorker`
  - baseline import runs only through `ProjectImportWorker`
  - health checks run only through `UnifiedHealthCheckWorker`

Engineering meaning:

- open risk is limited to local manifest parsing and lightweight filesystem
  status checks;
- worker-backed operations are already off the cold-open path.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Dialog open was separated from download/import/health worker execution. | Completed |
| `2. Cold vs warm measurement` | Fresh offscreen probe used current repo code and current local resource state. | Completed |
| `3. Step-by-step cold breakdown` | Full init, manifest listing, and per-entry status checks were timed separately. | Completed |
| `4. SQL-level timing / query audit` | No DB path is involved in this open contract. | Completed |
| `5. Service/process timing` | `ResourceRegistry` work stayed bounded and local. | Completed |
| `6. Filesystem / OS / DB-open audit` | Open path touched only local manifest/settings/resource folders. | Completed |
| `7. UI first-render / first-usable-state audit` | Dialog becomes usable immediately after one bounded refresh. | Completed |
| `8. Degraded / fallback mode audit` | Missing optional baseline bundle degrades to a table status row, not a blocked open. | Completed |
| `9. Dataset-tier analysis` | Resource manifest currently has only `3` entries. | Completed |
| `10. Repeatability protocol` | Commands below reproduce the same bounded result. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `RM1`-`RM3` were fixed before interpretation. | Prevented mixing dialog open with worker-backed actions. |
| `B. Bounded live probes` | Offscreen dialog probe captured the real open contract. | Current evidence, not intuition. |
| `C. SQL top offenders log` | No SQL layer exists in this open path. | This is not a DB-latency branch. |
| `D. UI responsiveness probes` | Full dialog init is `0.025s`. | Cold open is already comfortably bounded. |
| `E. Service initialization audit` | `list_entries()` is `0.010s`; each `get_status()` is `0.001s`. | No hidden service tail exists here. |
| `F. Drift / fallback path audit` | One optional baseline bundle is missing. | This is a content/state fact, not an open-time blocker. |
| `G. Before/after evidence protocol` | This is an audit-only wave. | No repair branch is opened. |

## Current findings

### Current-machine timings

From `resources_manager_dialog_probe.json` and `resources_manager_registry_probe.json`:

- full `ResourcesManagerDialog` init: `0.025s`
- table rows after open: `3`
- `ResourceRegistry.list_entries()`: `0.010s`
- per-entry `get_status()`:
  - `nikud_pronunciation_model`: `0.001s`
  - `sentence_niqqud_model`: `0.001s`
  - `hewiki_baseline_processed_bundle`: `0.001s`

Engineering meaning:

- cold open is already bounded well below blocker range;
- manifest parsing and status resolution are not meaningful bottlenecks.

### Current resource state

From `resources_manager_registry_probe.json`:

- installed required resources: `2`
  - `nikud_pronunciation_model`
  - `sentence_niqqud_model`
- missing optional resource: `1`
  - `hewiki_baseline_processed_bundle`
- state distribution:
  - `installed`: `2`
  - `missing`: `1`

Engineering meaning:

- required local model resources are already present;
- the only missing row is the optional baseline dataset bundle;
- this does not justify a cold-open branch.

### Selection context

The bounded candidate sweep for still-untriaged surfaces recorded:

- `resources_manager_dialog`: `0.035s`
- `import_wizard`: `0.007s`

Engineering meaning:

- `ResourcesManagerDialog` was the next visible candidate after
  `ProviderSettingsDialog`;
- the dedicated probe confirmed it is not a blocker.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- full cold open is `0.025s`;
- manifest listing and status resolution are tiny;
- heavy operations already live behind explicit worker-triggered actions;
- no UX or operator-flow evidence justifies a repair branch.

## Reopen gate

Keep the `ResourcesManagerDialog` branch closed.

Reopen only if a new evidence gate confirms one of:

- resource manifest grows materially and synchronous status resolution becomes
  expensive;
- checksum/hash validation is moved into the constructor/open path;
- download/import/health preflights are added to open.

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
- `ProviderSettingsDialog` branch

The next active engineering action is therefore:

- return to the canonical cold-audit framework for the next narrow subsystem
  wave, unless new approved-target evidence promotes a new blocker

## Verification notes

```powershell
New-Item -ItemType Directory -Force build\logs\cold_audit\resources_manager_dialog | Out-Null

New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'

.\.venv\Scripts\python.exe -m pytest tests\test_resource_registry.py -q

.\.venv\Scripts\python.exe -c "import app; from app.ui.resources_manager_dialog import ResourcesManagerDialog; print('OK')"
```

Evidence for this wave was collected against the current local resource state;
no source/reference DB mutation was involved.
