# Help Center

This in-app Help Center is the entrypoint for user guidance in HDLE Premium.

## Topics

1. Workspaces and navigation
2. Keyboard shortcuts
3. Keyboard interaction patterns
4. Translation workflows
5. Audio and pronunciation workflows
6. Resources and first-run setup

## Workspace Navigation (Primary Navigation)

- Projects
- Translation Management
- User Dictionaries
- Audio Player

Current Project card behavior:

- Shows project name, project id, and scope indicator.
- Deep links:
  - Documents
  - Sentences
  - Dictionary
  - Terms
  - Term Cards
  - Export
- If current project is not set:
  - card remains in disabled-link mode;
  - `Open Project...` sends user to Projects dashboard.

## Scope Chips

Translation Management and User Dictionaries use the same scope semantics:

- `Current Project`
- `All`

Scope state is persisted between sessions for each workspace independently.

## User Dictionaries

- Items are study entities (translation truth is resolved through TM global layer).
- Table supports:
  - inline translation edit
  - audio actions
  - pronunciation actions
  - column visibility via gear button
- Added metadata columns:
  - Project ID
  - Project Name

## Sentences -> User Dictionaries

Sentence rows can be added to User Dictionaries directly from Sentences view:

- Action row button: `Add to User Dictionary...`
- Context menu action: `Add Selected to User Dictionary (N)...`

The flow uses the same dialog and worker path as Lemma/Term add operations.

## Resources and First-Run Setup

Resource-related entrypoints:

- `Tools -> Resources Manager...`
- `Tools -> Run Health Check...`

What Resources Manager provides:

- status matrix for required/optional resources,
- model/dataset download or manual import,
- checksum verification and repair,
- baseline `.hdleproj` import,
- open data/resource folders.

First-run wizard:

- appears when `setup/first_run_completed` is not set;
- guides through data-root selection, local model readiness, baseline option, and health summary;
- skip is allowed; setup remains accessible from Tools.
