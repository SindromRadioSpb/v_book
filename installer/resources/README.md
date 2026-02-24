# Optional Installer Resources

This folder is intentionally empty in the default repository state.

You can pre-stage optional installer payloads before running `rebuild.ps1`:

- `installer/resources/local_models/` - local model files (for `localmodels` component)
- `installer/resources/baseline/` - `.hdleproj` baseline bundles (for `baseline` component)

If files are absent, installer components still exist, and users can install resources later from in-app `Resources Manager`.

