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

## Sentences Document Picker (Large Projects)

For large projects, Sentences uses a searchable document picker instead of loading all documents into a single dropdown.

- Entry point: `Sentences -> Document -> Select...`
- Supports:
  - title search,
  - numeric document ID search,
  - tag search,
  - server-side paging.
- Quick actions:
  - `Select` to apply document filter,
  - `All Documents` to clear document scope.
- Keyboard:
  - `Up/Down` navigate rows,
  - `Enter` apply selected row,
  - `Esc` close dialog.

## Resources and First-Run Setup

Resource-related entrypoints:

- `Tools -> Resources Manager...`
- `Tools -> Run Health Check...`
- `Tools -> Switch Database...`

What Resources Manager provides:

- status matrix for required/optional resources,
- model/dataset download or manual import,
- checksum verification and repair,
- baseline `.hdleproj` import,
- open data/resource folders.

First-run wizard:

- appears when `setup/first_run_completed` is not set;
- guides through data-root selection, working DB selection, local model readiness, baseline option, and health summary;
- skip is allowed; setup remains accessible from Tools.

Working DB selection:

- startup precedence: `--db-path` -> `HDLE_DB_PATH` -> `app/active_db_path` -> default `%LOCALAPPDATA%\HDLE\hdle.db`;
- switch dialog supports default DB, existing DB file, and local baseline quick-pick when available;
- switching DB requires restart.

## Database Busy Handling

Write operations use retry/backoff for transient SQLite lock windows.

- During retry, UI shows inline status (`Database is busy, retrying ...`) instead of modal spam.
- If retries are exhausted, operation fails with a single user-facing error and safe rollback.
- Recommended recovery if busy persists:
  - wait for long-running operation to finish,
  - cancel active export/import/batch tasks,
  - retry the action.
