## Premium Heavy-DB Startup and Release Plan

### Why this document exists

HDLE Premium can work with very large SQLite databases. In this cycle, the installed
application started against an old `18.5 GB` runtime DB from saved settings and tried
to run backup + migration before the main window appeared. That created a poor premium
startup experience and made packaging issues harder to distinguish from runtime DB
readiness issues.

### Typical premium patterns for desktop apps with heavy local DBs

Common safe patterns:

1. Installer deploys binaries and opens the app quickly on first run.
2. Heavy legacy DB upgrade is explicit, observable, and not forced before UI appears.
3. App starts on a light writable local DB if the previous DB is unsafe to auto-open.
4. Legacy or external DBs are connected/imported after startup via explicit user action.
5. Build smoke checks validate both packaged binaries and the active runtime DB path.

### Current HDLE risks before this patch

1. Startup precedence allowed `SETTINGS` DB to be opened before any UI appeared.
2. A huge legacy DB could trigger full backup + migration on startup.
3. Failure looked like "installer/app does not open", even when binaries were healthy.
4. First-run wizard existed, but was shown too late because DB initialization happened first.

### Target premium behavior

1. Explicit `CLI` and `ENV` DB choices remain authoritative.
2. A huge legacy DB from `SETTINGS` must not block first visible startup.
3. If a saved DB is both:
   - older than app schema
   - and above the heavy-DB threshold
   then startup is deferred to the default local DB.
4. The deferred DB path is preserved as a reconnect candidate.
5. After UI opens, the user receives one explicit reconnect prompt and can:
   - open `Tools -> Switch Database...`
   - choose the migrated baseline DB
   - continue on the default DB

### Implemented in this iteration

1. Startup guard for huge legacy settings DBs.
2. Deferred DB state persisted in settings:
   - `app/deferred_startup_db_path`
   - `app/deferred_startup_db_reason`
3. App opens on default local DB instead of blocking on heavy legacy DB migration.
4. `AppWindow` offers reconnect through the existing Switch Database flow.
5. First-run wizard and Switch Database dialog clear deferred state after explicit DB selection.

### Current operational recommendation

For release/install smoke:

1. Start the installed app without auto-opening a huge old DB from saved settings.
2. Prefer explicit connection to the already migrated baseline DB:
   - `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`
3. Treat large runtime DB migration as a separate readiness workflow, not as installer health.

### Follow-up opportunities

1. Add a dedicated non-modal startup banner instead of a single prompt.
2. Add offline migration tooling for huge runtime DBs before first launch.
3. Add pre-launch DB readiness diagnostics to installer smoke automation.
