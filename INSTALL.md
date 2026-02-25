# HDLE Premium - Installation and First-Run Guide

## Runtime data location

HDLE stores writable runtime data in a deterministic user folder, not in `Program Files`.

Default data root:

- Windows: `%LOCALAPPDATA%\HDLE`
- macOS: `~/Library/Application Support/HDLE`
- Linux: `~/.local/share/hdle`

Subfolders:

- `models/` - local model resources
- `datasets/` - optional baseline bundles
- `logs/` - runtime logs
- `tmp/` - temporary files
- `backups/` - backups

Override options:

- env: `HDLE_DATA_ROOT`
- settings key: `resources/data_root`

## Windows installer components

Installer supports component-based setup:

- `Core Application` (required)
- `Local Models` (recommended)
- `Hebrew Wikipedia Baseline` (optional, large)

The installer writes binaries to `Program Files` and keeps mutable data under `%LOCALAPPDATA%\HDLE`.

## First run flow

On first run, HDLE opens setup wizard (unless already completed):

1. Choose data folder.
2. Choose working database profile (default / existing / baseline when available).
3. Check local models (pronunciation + sentence niqqud).
4. Optional baseline bundle decision.
5. Optional cloud provider setup.
6. Run Health Check summary.

You can skip and configure later.

## Working database selection

Database path precedence on startup:

1. CLI `--db-path`
2. Env `HDLE_DB_PATH` (if file exists)
3. Settings `app/active_db_path` (if file exists)
4. Default `%LOCALAPPDATA%\HDLE\hdle.db`

Switch later any time:

- `Tools -> Switch Database...`

The dialog supports:

- default AppData DB,
- browse existing DB file,
- quick-pick for local Hebrew Wikipedia processed baseline DB (when available),
- `Switch & Restart`.

Reference dev baseline path (internal only):

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`

For release/end-user setups, prefer installer baseline component or Resources Manager flow.

## Resources Manager

Open from:

- `Tools -> Resources Manager...`
- shortcut: `Ctrl+Alt+R`

Capabilities:

- View status per resource (`Installed / Missing / Corrupted / Not configured`)
- Download (for downloadable resources)
- Import from file (manual payloads)
- Verify / Repair
- Open resource folder
- Import baseline `.hdleproj`
- Run unified Health Check

Download/import is worker-based with progress, cancel, and checksum verification.

## Health Check

Open from:

- `Tools -> Run Health Check...`
- command line: `python -m app.main --run-health-check`

Checks include:

- required local resources installed and loadable,
- pronunciation bootstrap readiness,
- sentence niqqud bootstrap readiness,
- cloud provider credential readiness (optional),
- optional baseline bundle/project state.

## Startup command-line options

```powershell
python -m app.main --open-resources-manager
python -m app.main --run-health-check
python -m app.main --db-path "J:\Project_Vibe\V_book\hdle_premium.db"
$env:HDLE_DB_PATH="C:\Data\hdle_custom.db"; python -m app.main
```

## Troubleshooting

### Local model is missing

Symptom:

- Pronunciation/Sentence Niqqud health status is `error` or `fallback`.

Fix:

1. Open `Tools -> Resources Manager`.
2. Import model file or download resource.
3. Re-run `Health Check`.

### Checksum mismatch

Symptom:

- resource status `Corrupted`.

Fix:

1. Use `Repair` in Resources Manager.
2. Re-import/re-download payload.

### Baseline not visible in dashboard

Fix:

1. In Resources Manager click `Import Baseline Bundle`.
2. Ensure bundle extension is `.hdleproj`.
3. Wait for import completion and reopen dashboard.

### Database locked

HDLE uses SQLite WAL and short transactions. If lock warnings appear:

1. Close second running instance.
2. Retry operation.
3. Check `%LOCALAPPDATA%\HDLE\logs\hdle.log`.
