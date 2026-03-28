# Optional Installer Resources

This folder is intentionally empty in the default repository state.

You can pre-stage optional installer payloads before running `rebuild.ps1`:

- `installer/resources/local_models/` - local model files (for `localmodels` component)
- `installer/resources/baseline/` - `.hdleproj` baseline bundles (for `baseline` component)
- `installer/resources/local_models/stanza_hebrew/` - staged bundled Hebrew payload for the managed Stanza runtime

If files are absent, installer components still exist, and users can install resources later from in-app `Resources Manager`.

## Bundled Hebrew payload

The staged Hebrew payload is a directory-based runtime resource, not a single installer file.

Canonical staging layout:

- `installer/resources/local_models/stanza_hebrew/payload_manifest.json`
- `installer/resources/local_models/stanza_hebrew/stanza_resources/resources.json`
- `installer/resources/local_models/stanza_hebrew/stanza_resources/he/...`

`rebuild.ps1` now stages this payload automatically via:

- `python scripts/stage_stanza_hebrew_payload.py`

Preferred source override:

- `HDLE_REQUIRED_STANZA_HEBREW_SOURCE`

The packaged app bundles this staged payload under:

- `_internal/resources/nlp_runtime/stanza_payload/...`

Managed bootstrap then treats that packaged payload as the primary source for the managed Hebrew runtime resource.

## Clarification: installer baseline vs DB quick-pick

- Installer `baseline` component consumes only:
  - `installer/resources/baseline/*.hdleproj`
- Setup Wizard / Switch DB baseline quick-pick is a separate runtime DB path from:
  - `app/infra/db_path_resolver.py`
  - `DEV_HEWIKI_BASELINE_DB_PATH`
- Replacing the dev baseline DB for quick-pick does not replace installer `.hdleproj` bundles, and vice versa.
