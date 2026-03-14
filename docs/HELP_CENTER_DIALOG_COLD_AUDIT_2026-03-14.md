# Help Center Dialog Cold Audit (2026-03-14)

## Why this document exists

This is the twenty-sixth task-specific use of the canonical cold-audit
framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- `HelpCenterDialog` cold open / first usable state

This wave does **not**:

- open a runtime repair branch;
- reinterpret full app startup as help-center open cost;
- audit documentation content quality or completeness;
- audit external-link navigation;
- open heavy validation.

## Scope

In scope:

- `HelpCenterDialog` cold open with current repo docs on disk
- markdown-document read path for the initial tabs
- tab-shell construction and first usable state
- blocker vs not-blocker classification

Out of scope:

- `AppWindow` startup
- documentation authoring quality
- external-link behavior
- runtime navigation after the dialog is already open

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `HCD1` | Remaining visible-candidate selection | prior bounded sweep evidence | Confirms why this is the next narrow wave after reference setup wizard | Completed |
| `HCD2` | Full `HelpCenterDialog()` cold open | current repo docs on disk | Measures the actual visible constructor/open contract | Completed |
| `HCD3` | Markdown-read path audit | `HELP_CENTER.md`, `KEYBOARD_SHORTCUTS.md`, `KEYBOARD_INTERACTIONS.md` | Confirms open-time doc-loading shape | Completed |
| `HCD4` | Tab-shell audit | current repo docs on disk | Confirms immediate usability and tab count | Completed |
| `HCD5` | Current-machine docs presence check | current repo checkout | Confirms open is using real docs, not fallback empty state | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/help_center_dialog.py`
- `app/ui/app_window.py`

Current smoke/regression entry points:

- `tests/test_workspace_app_window_contract.py`
- `tests/test_p1_workspace.py`

Evidence artifacts:

- `build/logs/cold_audit/candidate_sweep/remaining_visible_surfaces_2026-03-13.json`
- `build/logs/cold_audit/help_center_dialog/help_center_dialog_probe.json`
- `build/logs/cold_audit/help_center_dialog/help_center_dialog_cold_audit_summary.json`

Current-machine docs used by open path:

- `docs/HELP_CENTER.md`
- `docs/KEYBOARD_SHORTCUTS.md`
- `docs/KEYBOARD_INTERACTIONS.md`

## Current UI/workflow contract

Current `HelpCenterDialog` open path:

- `HelpCenterDialog.__init__()` performs:
  - window-title/geometry setup
  - `_init_ui()`
- `_init_ui()` performs:
  - `QTabWidget` construction
  - synchronous `_read_doc(...)` calls for:
    - `docs/HELP_CENTER.md`
    - `docs/KEYBOARD_SHORTCUTS.md`
    - `docs/KEYBOARD_INTERACTIONS.md`
  - inline markdown construction for:
    - `Translation`
    - `Audio`
  - five `QTextBrowser` markdown views

Engineering meaning:

- the dialog does synchronous local doc reads on open;
- there is still no DB, worker, or network dependency on first usable state;
- open cost is dominated by lightweight markdown/tab construction only.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Help-center open was separated from app startup and docs authoring work. | Completed |
| `2. Cold vs warm measurement` | Fresh offscreen probe used current repo docs on disk and current repo code. | Completed |
| `3. Step-by-step cold breakdown` | Full init, tab construction, and markdown-read path were isolated together. | Completed |
| `4. SQL-level timing / query audit` | Open path exposes no SQL layer. | Completed |
| `5. Service/process timing` | No service/worker startup exists on open. | Completed |
| `6. Filesystem / OS / DB-open audit` | Open path performs local markdown reads only. | Completed |
| `7. UI first-render / first-usable-state audit` | Dialog is usable immediately after bounded tab construction. | Completed |
| `8. Degraded / fallback mode audit` | Missing docs would degrade to fallback markdown, not blocked open. | Completed |
| `9. Dataset-tier analysis` | Open cost is independent of corpus scale. | Completed |
| `10. Repeatability protocol` | Commands below reproduce the same bounded result. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `HCD1`-`HCD5` were fixed before interpretation. | Prevented mixing help-center open with app-start cost. |
| `B. Bounded live probes` | Dedicated current-docs probe captured the real constructor/open contract. | Current evidence, not assumption. |
| `C. SQL top offenders log` | No SQL exists on open. | This is not a DB-latency branch. |
| `D. UI responsiveness probes` | Full dialog init is `0.129s`. | Open is already bounded. |
| `E. Service initialization audit` | No services/workers start on open. | There is no hidden heavy stage here. |
| `F. Drift / fallback path audit` | The coarse sweep undercounted this path; the dedicated probe corrected it using real docs on disk. | Prevented under-reporting the real contract. |
| `G. Before/after evidence protocol` | This is an audit-only wave. | No repair branch is opened. |

## Current findings

### Candidate-selection context

From `remaining_visible_surfaces_2026-03-13.json`:

- `help_center`: `0.006s`

Engineering meaning:

- after the reference-setup wave, `HelpCenterDialog` was the last remaining
  visible candidate from that bounded sweep;
- the dedicated follow-up was required because the coarse sweep undercounted
  the real markdown/tab-construction cost;
- the dedicated probe then confirmed that the dialog is still not a blocker.

### Dedicated open timings

From `help_center_dialog_probe.json`:

- full `HelpCenterDialog` init: `0.129s`
- tab count: `5`
- tab titles:
  - `Overview`
  - `Shortcuts`
  - `Keyboard Flows`
  - `Translation`
  - `Audio`
- markdown views: `5`
- first tab text length: `165`
- window title:
  - `Help Center`

Engineering meaning:

- the dialog shell is already bounded and usable immediately;
- local markdown loads and tab construction are still cheap;
- help center open is not the next cold bottleneck.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- full cold open is only `0.129s`;
- there is no worker, DB, or network dependency on open;
- the open path is limited to lightweight local markdown reads and tab setup;
- no UX evidence justifies a repair branch.

## Reopen gate

Keep the `HelpCenterDialog` cold-open branch closed.

Reopen only if a new evidence gate confirms one of:

- heavy docs parsing/rendering work is added to constructor/open path;
- remote/help-search work is moved into initial open;
- first usable state regresses materially on operator targets.

Do not reopen this as a generic docs-quality or app-startup branch without
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
