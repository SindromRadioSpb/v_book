# Database Selection (Working DB Profiles)

## Mandatory behavior

HDLE Premium supports selecting the working database:

- on first run (Setup Wizard),
- and later at any time (`Tools -> Switch Database...`).

By default, HDLE uses the default AppData DB path:

- Windows: `%LOCALAPPDATA%\HDLE\hdle.db`

If the file does not exist yet, it is created on startup.

## Startup precedence (deterministic)

Database path resolution order is:

1. CLI: `--db-path`
2. Env: `HDLE_DB_PATH` (only if file exists)
3. Settings: `app/active_db_path` (only if file exists)
4. Default: `%LOCALAPPDATA%\HDLE\hdle.db`

The selected source is logged on startup (`CLI|ENV|SETTINGS|DEFAULT`).

## First-run wizard

Wizard step **Working database** provides:

- `Use default empty DB (recommended)`
- `Select existing DB file`
- `Use Hebrew Wikipedia Baseline (processed)` (only when available locally)

When database choice differs from the current runtime DB, wizard offers restart.

## In-app switching

Open:

- `Tools -> Switch Database...`

Dialog shows:

- current DB path/profile/size/schema,
- quick options (Default, Browse existing file, Baseline quick-pick when available),
- `Switch & Restart`,
- `Open DB Folder`, `Copy Path`, `Make Backup...`.

Schema safeguards:

- block switching to DB with newer schema than app supports,
- warn when selected DB schema is older and migrations may run.

## Hebrew Wikipedia baseline (processed)

Reference processed DB (internal/dev path):

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`

This path is **internal/dev** and is not guaranteed on end-user machines.

### Installer vs baseline quick-pick source (important)

- Baseline quick-pick in Setup Wizard / Switch DB dialog resolves from:
  - `app/infra/db_path_resolver.py`
  - constant: `DEV_HEWIKI_BASELINE_DB_PATH`
  - current value:
    `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`
- Installer optional `baseline` component does **not** read this `.db` directly.
  Installer picks optional `.hdleproj` bundles from:
  - `installer/resources/baseline/*.hdleproj`

### 2026-03-07 recovery note

- Recovered DB was placed into:
  `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`
  so baseline quick-pick now points to the recovered file.
- Archive backup created by operator:
  `J:\Project_Vibe\V_book\build\hewiki_gpu_processing.recovered_7.03.26.rar`

Release users should use:

- installer baseline component (if provided),
- or `Resources Manager` import/setup flow.

## CLI examples

```powershell
python -m app.main --db-path "J:\Project_Vibe\V_book\hdle_premium.db"
$env:HDLE_DB_PATH="C:\Data\hdle_custom.db"; python -m app.main
```
