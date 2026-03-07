# Help Center

This in-app Help Center is the entrypoint for user guidance in HDLE Premium.

## Topics

1. Workspaces and navigation
2. Keyboard shortcuts
3. Keyboard interaction patterns
4. Translation workflows
5. Audio and pronunciation workflows
6. Resources and first-run setup
7. Reference Projects (read-only corpora)

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

---

## Reference Projects

A **Reference Project** is a large read-only corpus (for example, Hebrew Wikipedia)
used as a statistical baseline for term scoring and translation lookup.
It is protected against accidental modification at both the database and UI level.

### What you will see

When you open a Reference Project, the **Documents** tab shows a blue banner:

> "This is a Reference Corpus (read-only documents).
> You can browse documents, extract terms, and manage translations,
> but cannot add or remove documents."

The following controls are **disabled**:

| Control | Reason |
|---------|--------|
| Add Files | Document import is not allowed on a reference corpus |
| Add Folder | Same |
| Delete | Deleting reference documents is not allowed |
| Process | Use the CLI script for large-scale NLP processing |
| Re-process | Same |

All other functionality remains available:

| What you can do | Where |
|-----------------|-------|
| Browse and search documents | Documents tab |
| Filter by tag, level, title | Documents tab |
| View and edit document metadata | Documents tab — right-click row |
| Extract terms | Terms tab |
| Manage translations | Translation Management panel |
| Generate audio | Sentences / Audio Player |
| Add sentences to User Dictionaries | Sentences tab |

### Why some operations are disabled

Reference corpora are large (typically hundreds of thousands of documents) and
backed by a pre-processed external database.  Allowing document import or deletion
through the UI would risk data corruption or accidental replacement of the baseline.
NLP processing of the full corpus takes several hours and must be run from the CLI
to avoid holding a database write lock that would freeze all other operations.

### Operation status bar

While any heavy operation (NLP processing, import, term extraction) is running,
the status bar at the bottom of the window shows an amber indicator:

```
  ⚙ 1 op active
```

Hover over it to see which operation is running.  Starting a second operation of
the same type while one is already active shows a warning dialog and the new
operation is not started — wait for the first to finish.

### FAQ

**Q: Can I translate sentences from a Reference Project?**
Yes.  Translation overlays are stored in your main database, not in the reference
corpus file.  Translation, audio, and pronunciation features work normally.

**Q: Can I extract terms from a Reference Project?**
Yes.  Term extraction writes to your main database and is always available.

**Q: Why is the Process button disabled?**
NLP processing for a large reference corpus must run via the CLI script
`scripts/process_reference_corpus.py` to ensure WAL-safe per-document transactions.
The UI button is intentionally blocked to prevent accidental multi-hour write locks.

**Q: How do I know if a project is a Reference Project?**
Open the project and go to the Documents tab.  A blue banner appears at the top if
the project is designated as a reference corpus.

**Q: Can I make a Reference Project writable again?**
Yes, but this is an administrator operation.  See `docs/REFERENCE_PROJECT_GUIDE.md`
for the full procedure.

**Q: The blue banner does not appear even though I expected it.**
Try closing the project tab and reopening it, or restart the application.
If the issue persists, contact your system administrator to verify the project flag
in the database.

### For administrators

Full setup and troubleshooting instructions are in:

```
docs/REFERENCE_PROJECT_GUIDE.md
```

Quick reference:

```powershell
# List all projects and their reference status
python scripts/mark_reference_project.py --db-path hdle_premium.db --list

# Mark project 1 as a reference project
python scripts/mark_reference_project.py `
    --db-path hdle_premium.db `
    --project-id 1 `
    --ref-db-path "J:\ref_corpora\hewiki_gpu_processing.db"

# Remove reference designation
python scripts/mark_reference_project.py `
    --db-path hdle_premium.db --project-id 1 --unmark
```

Restart the application after any change.
