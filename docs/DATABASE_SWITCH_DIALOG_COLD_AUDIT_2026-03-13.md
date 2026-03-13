# Database Switch Dialog Cold Audit (2026-03-13)

## Why this document exists

This is the fifteenth task-specific use of the canonical cold-audit framework
in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- `DatabaseSwitchDialog` cold open / first usable state

This wave does **not**:

- audit backup execution time;
- audit restart flow or process relaunch behavior;
- reopen database migration, baseline selection, or operator write-path work;
- open heavy validation.

## Scope

In scope:

- `DatabaseSwitchDialog(current_db_path=approved target)` cold open
- sync metadata inspection on current and default DB paths
- blocker vs not-blocker classification

Out of scope:

- `_create_backup()` worker execution cost
- `_on_switch_and_restart()` warning/confirmation path
- migration execution after restart

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `DS1` | Full `DatabaseSwitchDialog()` cold open | approved hewiki test DB | Measures the real dialog-open contract | Completed |
| `DS2` | `inspect_db_path(current_db_path)` breakdown | approved hewiki test DB | Confirms current-profile metadata cost | Completed |
| `DS3` | `inspect_db_path(default_db_path)` breakdown | local default DB path | Confirms default-profile metadata cost | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/database_switch_dialog.py`
- `app/infra/db_path_resolver.py`
- `app/ui/app_window.py`

Current smoke/regression entry points:

- `tests/test_database_switch_dialog.py`

Evidence artifacts:

- `build/logs/cold_audit/candidate_sweep/candidate_sweep_2026-03-13.json`
- `build/logs/cold_audit/database_switch_dialog/database_switch_dialog_probe.json`
- `build/logs/cold_audit/database_switch_dialog/database_switch_dialog_cold_audit_summary.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- strict read-only inspection only

## Current UI/workflow contract

Current `DatabaseSwitchDialog` cold-open path:

- `DatabaseSwitchDialog.__init__()` performs:
  - `_init_ui()`
  - `_load_current_metadata()`
  - `_update_selected_state()`
- `_load_current_metadata()` calls:
  - `inspect_db_path(current_db_path)`
  - `classify_db_profile(current_db_path, ...)`
- `_update_selected_state()` calls:
  - `_selected_path()`
  - `inspect_db_path(selected)`
  - `classify_db_profile(selected, ...)`
- heavy work is not started on open:
  - backup runs only through `_DBBackupWorker` after explicit user action
  - restart and migration warnings run only through `_on_switch_and_restart()`

Engineering meaning:

- cold-open risk is limited to layout creation plus two small schema-meta
  reads;
- there is no long-running worker or backup path on first usable state.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Dialog open was separated from backup and restart actions. | Completed |
| `2. Cold vs warm measurement` | Fresh offscreen probe used current repo code. | Completed |
| `3. Step-by-step cold breakdown` | Current-path inspect, default-path inspect, and full init were timed separately. | Completed |
| `4. SQL-level timing / query audit` | Open uses only bounded `schema_meta` reads via `mode=ro`. | Completed |
| `5. Service/process timing` | No heavy service or worker path exists on dialog open. | Completed |
| `6. Filesystem / OS / DB-open audit` | Approved target remained unchanged under strict read-only inspection. | Completed |
| `7. UI first-render / first-usable-state audit` | Dialog becomes usable immediately after metadata labels populate. | Completed |
| `8. Degraded / fallback mode audit` | Missing/nonexistent paths are already represented as label text, not blocking work. | Completed |
| `9. Dataset-tier analysis` | Dataset scale is irrelevant; this is a metadata-only chooser path. | Completed |
| `10. Repeatability protocol` | Commands below reproduce the same bounded result. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `DS1`-`DS3` were fixed before interpretation. | Prevented mixing dialog-open cost with backup/restart work. |
| `B. Bounded live probes` | Strict read-only offscreen dialog probe captured the real open contract. | Current evidence, not intuition. |
| `C. SQL top offenders log` | `inspect_db_path()` on current/default paths stayed at `0.009s` and `0.014s`. | No metadata bottleneck exists here. |
| `D. UI responsiveness probes` | Full dialog init is `0.033s`. | Cold open is already comfortably bounded. |
| `E. Service initialization audit` | Default path inspection found schema `26`, but only as label metadata. | Migration warning is not an open-time blocker. |
| `F. Drift / fallback path audit` | Baseline quick-pick remains available; nonexistent/default states are already handled in labels. | No fallback regression found. |
| `G. Before/after evidence protocol` | This is an audit-only wave. | No repair branch is opened. |

## Current findings

### Approved-target timings

From `database_switch_dialog_probe.json`:

- `inspect_db_path(current_db_path)`: `0.009s`
- `inspect_db_path(default_db_path)`: `0.014s`
- full `DatabaseSwitchDialog` init: `0.033s`

Engineering meaning:

- the dialog is already bounded well below blocker range;
- metadata inspection is small and deterministic;
- there is no current cold-open problem in this subsystem.

### Current metadata state

From `database_switch_dialog_cold_audit_summary.json`:

- current profile: `Custom`
- current schema: `42`
- default DB exists: `true`
- default DB schema: `26`
- baseline quick-pick available: `true`
- selected profile on open: `Default`

Engineering meaning:

- the dialog is correctly surfacing profile/schema metadata without blocking;
- the older local default schema is only a future switch-warning concern, not a
  cold-open issue.

### Selection context

The bounded candidate sweep for still-untriaged surfaces recorded:

- `database_switch_dialog`: `0.128s`
- `provider_settings_dialog`: `0.119s`
- `resources_manager_dialog`: `0.035s`
- `import_wizard`: `0.007s`

Engineering meaning:

- `DatabaseSwitchDialog` was the next largest remaining visible candidate after
  `UserDictionariesView`;
- the dedicated probe then confirmed it is not a blocker.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- full cold open is `0.033s`;
- current/default metadata inspection stays under `0.014s` each;
- heavy backup/restart work is not on the cold-open path;
- no UX or operator-flow evidence justifies a repair branch.

## Reopen gate

Keep the `DatabaseSwitchDialog` branch closed.

Reopen only if a new evidence gate confirms one of:

- dialog open begins prevalidating multiple candidate DBs synchronously;
- backup or migration preflight is moved into constructor/open path;
- real operator evidence shows a materially slower open-time metadata path.

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

The next active engineering action is therefore:

- return to the canonical cold-audit framework for the next narrow subsystem
  wave, unless new approved-target evidence promotes a new blocker

## Verification notes

```powershell
New-Item -ItemType Directory -Force build\logs\cold_audit\database_switch_dialog | Out-Null

New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'

.\.venv\Scripts\python.exe -m pytest tests\test_database_switch_dialog.py -q

.\.venv\Scripts\python.exe -c "import app; from app.ui.database_switch_dialog import DatabaseSwitchDialog; print('OK')"
```

Approved-target evidence for this wave was collected through strict read-only
inspection only; no source/reference DB mutation was performed.
