# Optional Installer Resources

This folder is intentionally empty in the default repository state.

You can pre-stage optional installer payloads before running `rebuild.ps1`:

- `installer/resources/local_models/` - local model files (for `localmodels` component)
- `installer/resources/baseline/` - `.hdleproj` baseline bundles (for `baseline` component)

If files are absent, installer components still exist, and users can install resources later from in-app `Resources Manager`.

## Clarification: installer baseline vs DB quick-pick

- Installer `baseline` component consumes only:
  - `installer/resources/baseline/*.hdleproj`
- Setup Wizard / Switch DB baseline quick-pick is a separate runtime DB path from:
  - `app/infra/db_path_resolver.py`
  - `DEV_HEWIKI_BASELINE_DB_PATH`
- Replacing the dev baseline DB for quick-pick does not replace installer `.hdleproj` bundles, and vice versa.
