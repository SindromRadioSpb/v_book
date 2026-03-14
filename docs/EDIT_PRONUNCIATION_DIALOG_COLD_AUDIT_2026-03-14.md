# Edit Pronunciation Dialog Cold Audit (2026-03-14)

## Why this document exists

This is the thirty-second task-specific use of the canonical cold-audit
framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- `EditPronunciationDialog` trigger path / cold open / first usable state

This wave does **not**:

- open a runtime repair branch;
- reinterpret pronunciation upsert/delete writes as dialog open cost;
- audit bootstrap generation;
- audit audio playback or cache invalidation paths;
- open heavy validation.

## Scope

In scope:

- `show_edit_pronunciation_dialog(...)` reject path with representative source
  payload
- synchronous `PronunciationService.get_entry()` lookup before dialog display
- dialog shell creation and preview initialization
- blocker vs not-blocker classification

Out of scope:

- submit/save path
- clear-entry path
- pronunciation write semantics
- cross-view refresh behavior after edit

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `EPD1` | Remaining cold-candidate selection | current repo entry points | Confirms why this is the next narrow wave after add-to-user-dictionary dialog | Completed |
| `EPD2` | Full helper trigger path | representative source payload + approved-target DB | Measures the actual user-visible open contract, not just the dialog constructor | Completed |
| `EPD3` | Synchronous existing-entry lookup | `PronunciationService.get_entry()` | Confirms whether the pre-open DB lookup creates a hidden blocker | Completed |
| `EPD4` | Dialog preview initialization | representative source payload + current repo code | Confirms first usable state after lookup | Completed |
| `EPD5` | Hidden worker startup check | current repo code | Confirms whether any background work starts before explicit user action | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/dialogs/edit_pronunciation_dialog.py`
- `app/services/pronunciation_service.py`
- `app/services/pronunciation_quality_service.py`
- `app/services/db_service.py`

Current smoke/regression entry points:

- `tests/test_edit_pronunciation_dialog.py`
- `tests/test_user_dictionaries_context_menu.py`
- `tests/test_dictionary_audio_context_menu.py`

Evidence artifacts:

- `build/logs/cold_audit/edit_pronunciation_dialog/edit_pronunciation_dialog_probe.json`
- `build/logs/cold_audit/edit_pronunciation_dialog/edit_pronunciation_dialog_cold_audit_summary.json`

## Current UI/workflow contract

Current `show_edit_pronunciation_dialog(...)` trigger path:

- validates `src_lang` / `src_norm`
- obtains `DBService.get_instance()`
- performs one synchronous `PronunciationService.get_entry()` lookup
- constructs `EditPronunciationDialog`
- dialog constructor performs:
  - local widget construction
  - preview/warning label initialization
  - synchronous `_refresh_preview()`

Engineering meaning:

- the user-visible open path includes one DB-backed read before the dialog is
  shown;
- the dialog shell itself remains local and synchronous;
- no worker or write path starts on open.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Trigger-path open was separated from submit/save execution. | Completed |
| `2. Cold vs warm measurement` | Dedicated approved-target reject-path probe used current repo code with a read-only DB wrapper. | Completed |
| `3. Step-by-step cold breakdown` | Existing-entry lookup and dialog-init timing were isolated together. | Completed |
| `4. SQL-level timing / query audit` | Open path contains one bounded `get_entry()` lookup. | Completed |
| `5. Service/process timing` | `PronunciationService.get_entry()` remains cheap on the approved target. | Completed |
| `6. Filesystem / OS / DB-open audit` | Probe used strict read-only access and kept DB `mtime` unchanged. | Completed |
| `7. UI first-render / first-usable-state audit` | Dialog becomes usable immediately after the small lookup completes. | Completed |
| `8. Degraded / fallback mode audit` | Missing entry degrades to editable empty fields, not blocked open. | Completed |
| `9. Dataset-tier analysis` | Open contract is classified honestly without claiming large-scale pronunciation-table pressure. | Completed |
| `10. Repeatability protocol` | Commands below reproduce the same bounded result. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `EPD1`-`EPD5` were fixed before interpretation. | Prevented mixing open with save/write work. |
| `B. Bounded live probes` | Approved-target read-only reject-path probe captured the real trigger contract. | Current evidence, not assumption. |
| `C. SQL top offenders log` | One synchronous `get_entry()` lookup exists on open. | This is the only DB-backed cold layer here. |
| `D. UI responsiveness probes` | Full trigger path is `0.170s`. | Open is already bounded. |
| `E. Service initialization audit` | `get_entry()` is `0.070s` on the approved target. | DB-backed open work is still cheap. |
| `F. Drift / fallback path audit` | Probe confirmed missing-entry fallback and preview initialization. | Prevented auditing only the constructor shell. |
| `G. Before/after evidence protocol` | This is an audit-only wave. | No repair branch is opened. |

## Current findings

### Dedicated trigger timings

From `edit_pronunciation_dialog_probe.json`:

- full reject-path trigger: `0.170s`
- `get_entry()`: `0.070s`
- dialog init: `0.169s`
- existing entry found:
  - `false`
- preview text initialized:
  - `<b>What will be spoken:</b> ????`
- warning text:
  - empty
- `changed = false`
- `db_mtime_unchanged = true`

Engineering meaning:

- the user-visible trigger path is already bounded;
- the only DB-backed open read is small on the approved target;
- no hidden worker or write path starts on open.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- full representative reject-path open is only `0.170s`;
- the only DB-backed read on open is `0.070s`;
- there is no worker, write path, or network dependency on open;
- no UX evidence justifies a repair branch.

## Reopen gate

Keep the `EditPronunciationDialog` cold-open branch closed.

Reopen only if a new evidence gate confirms one of:

- pronunciation lookup volume makes synchronous open materially slower on real
  operator targets;
- additional DB-backed enrichment is moved into trigger/open path;
- open begins starting background work or write preflight before user
  confirmation.

Do not reopen this as a generic pronunciation-write or bootstrap branch without
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
- `EditPronunciationDialog` cold-open branch
