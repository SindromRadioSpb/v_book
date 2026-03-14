# Add To User Dictionary Dialog Cold Audit (2026-03-14)

## Why this document exists

This is the thirty-first task-specific use of the canonical cold-audit
framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- `AddToUserDictionaryDialog` cold open / first usable state

This wave does **not**:

- open a runtime repair branch;
- reinterpret bulk-add execution as dialog open cost;
- audit `create_dictionary()` submit flow;
- audit user-dictionary item import/add throughput;
- open heavy validation.

## Scope

In scope:

- `AddToUserDictionaryDialog` cold open with representative selected-count
- synchronous dictionary-list load on open
- default dictionary preselection and option-checkbox defaults
- blocker vs not-blocker classification

Out of scope:

- `show_add_to_user_dictionary_dialog()` acceptance flow after open
- `_on_create_dictionary()`
- bulk-add write path
- user-dictionary study/review workflows

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `AUD1` | Remaining cold-candidate selection | current repo entry points | Confirms why this is the next narrow wave after batch audio dialog | Completed |
| `AUD2` | Full `AddToUserDictionaryDialog()` cold open | representative selected-count + approved-target DB | Measures the actual visible constructor/open contract | Completed |
| `AUD3` | Synchronous dictionary-list load | `UserDictionaryService.list_dictionaries()` | Confirms whether DB-backed list hydration creates a hidden blocker | Completed |
| `AUD4` | Default option/widget state restore | current repo code | Confirms first usable state after dictionary load | Completed |
| `AUD5` | Hidden worker startup check | current repo code | Confirms whether any background work starts before explicit user action | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/dialogs/add_to_user_dictionary_dialog.py`
- `app/services/user_dictionary_service.py`
- `app/services/db_service.py`

Current smoke/regression entry points:

- `tests/test_add_to_user_dictionary_dialog.py`

Evidence artifacts:

- `build/logs/cold_audit/add_to_user_dictionary_dialog/add_to_user_dictionary_dialog_probe.json`
- `build/logs/cold_audit/add_to_user_dictionary_dialog/add_to_user_dictionary_dialog_cold_audit_summary.json`

## Current UI/workflow contract

Current `AddToUserDictionaryDialog` open path:

- `AddToUserDictionaryDialog.__init__()` performs:
  - `DBService.get_instance()`
  - `UserDictionaryService()` construction
  - `_load_dictionaries()`
  - `_init_ui()`
- `_load_dictionaries()` performs:
  - one synchronous `list_dictionaries()` query
- `_init_ui()` performs:
  - local widget construction
  - combo population from the loaded dictionary DTOs
  - default-checkbox initialization

Engineering meaning:

- the dialog is not purely local: it performs one DB-backed read on open;
- that read is still bounded on the approved target;
- no worker or bulk-add operation starts on open.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Dialog open was separated from add/bulk-create execution. | Completed |
| `2. Cold vs warm measurement` | Dedicated approved-target probe used current repo code with a read-only DB wrapper. | Completed |
| `3. Step-by-step cold breakdown` | Constructor, dictionary-list load, and UI build were isolated together. | Completed |
| `4. SQL-level timing / query audit` | Open path contains one bounded dictionary-list query. | Completed |
| `5. Service/process timing` | `UserDictionaryService.list_dictionaries()` dominates the open path and remains cheap. | Completed |
| `6. Filesystem / OS / DB-open audit` | Probe used strict read-only access and kept DB `mtime` unchanged. | Completed |
| `7. UI first-render / first-usable-state audit` | Dialog is usable immediately after the small dictionary read completes. | Completed |
| `8. Degraded / fallback mode audit` | Empty dictionary list degrades to combo-empty state, not hidden background work. | Completed |
| `9. Dataset-tier analysis` | Approved target has only `1` dictionary and is not scale-viable for a major user-dictionary cold claim. | Completed |
| `10. Repeatability protocol` | Commands below reproduce the same bounded result. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `AUD1`-`AUD5` were fixed before interpretation. | Prevented mixing dialog open with bulk-add write cost. |
| `B. Bounded live probes` | Approved-target read-only probe captured the real constructor/open contract. | Current evidence, not assumption. |
| `C. SQL top offenders log` | One synchronous dictionary-list query exists on open. | This is the only DB-backed cold layer here. |
| `D. UI responsiveness probes` | Full dialog init is `0.180s`. | Open is already bounded. |
| `E. Service initialization audit` | `list_dictionaries()` is `0.069s` on the approved target. | DB-backed open work is still cheap. |
| `F. Drift / fallback path audit` | Default dictionary selection and option defaults were confirmed explicitly. | Prevented auditing only shell creation. |
| `G. Before/after evidence protocol` | This is an audit-only wave. | No repair branch is opened. |

## Current findings

### Dedicated open timings

From `add_to_user_dictionary_dialog_probe.json`:

- full `AddToUserDictionaryDialog` init: `0.180s`
- `list_dictionaries()`: `0.069s`
- representative selected rows: `25`
- dictionary count: `1`
- combo count: `1`
- default selected dictionary id:
  - `1`
- `skip_duplicates`: `true`
- `include_noise`: `false`
- `preserve_origin_refs`: `true`
- `has_worker_on_open = false`
- `db_mtime_unchanged = true`

Engineering meaning:

- the dialog shell is already bounded and usable immediately;
- the only DB-backed open read is small on the approved target;
- no hidden worker or bulk-add step starts on open.

### Dataset-tier caveat

Approved-target dictionary scale:

- dictionaries: `1`
- total `user_dictionary_item` rows on the approved target were already known to
  be very small from the earlier `UserDictionariesView` audit

Engineering meaning:

- this wave is sufficient to classify the open contract;
- it is not sufficient to make any large-scale claim about user-dictionary
  growth pressure without new evidence.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- full representative cold open is only `0.180s`;
- the only DB-backed read on open is `0.069s`;
- there is no worker, write path, or network dependency on open;
- no UX evidence justifies a repair branch.

## Reopen gate

Keep the `AddToUserDictionaryDialog` cold-open branch closed.

Reopen only if a new evidence gate confirms one of:

- dictionary-list growth makes synchronous open materially slower on real
  operator targets;
- DB-backed enrichment beyond the list query is moved into constructor/open;
- open begins starting background work or bulk-add preflight before user
  confirmation.

Do not reopen this as a generic user-dictionary throughput branch without
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
- `AddToUserDictionaryDialog` cold-open branch
