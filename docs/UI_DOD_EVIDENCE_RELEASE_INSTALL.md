# UI DoD Evidence: Release and Installer Hardening

## Scope

This evidence covers:

- deterministic resource paths,
- installer component flow (`Core / Local Models / Baseline`),
- in-app Resources Manager,
- first-run wizard,
- unified health check remediation.

## Manual smoke matrix (clean machine)

1. Install `Core Application` only.
2. Start app and verify first-run wizard opens.
3. In wizard Step 1, keep default data folder and continue.
4. In wizard Step 2, verify required model checks show missing state.
5. In wizard Step 3, skip baseline installation.
6. In wizard Step 5, run health summary and verify pronunciation + sentence niqqud checks show actionable remediation.
7. Open `Tools -> Resources Manager...`.
8. Verify table contains:
   - `Phonikud Pronunciation Model`,
   - `Sentence Niqqud Model`,
   - `Hebrew Wikipedia Baseline`.
9. Select pronunciation model and run `Import from File...` with ONNX payload.
10. Verify status changes to `installed` (or checksum-corrupted if payload does not match manifest checksum).
11. Select baseline row and import `.hdleproj` bundle.
12. Verify import worker progress runs without UI freeze and baseline project appears in dashboard.
13. Click `Run Health Check` from Resources Manager and verify updated report.
14. Restart app; verify `resources/data_root` and installed statuses persist.
15. Run app with CLI flag:
    - `python -m app.main --open-resources-manager`
    - verify manager opens on startup.
16. Run app with CLI flag:
    - `python -m app.main --run-health-check`
    - verify health dialog appears and reports checks.
17. Install with optional installer components (`Local Models`, `Baseline`) when available in installer payload and verify files are placed under `%LOCALAPPDATA%\HDLE`.
18. Uninstall app and verify user data folder preservation policy works as documented.

### DB Selection smoke matrix

- `DBSEL-01`: First-run wizard -> choose `Use Hebrew Wikipedia Baseline (processed)` -> finish -> restart -> selected baseline DB is active.
- `DBSEL-02`: `Tools -> Switch Database...` -> choose `Default DB (AppData)` -> `Switch & Restart` -> default DB is active.
- `DBSEL-03`: `Tools -> Switch Database...` -> choose invalid/missing path -> clear non-crashing error -> no switch applied.

## Non-functional checks

- No hardcoded dev path (`M:\...`) is used in runtime resource resolution.
- No long-running resource operation runs in UI thread.
- Downloads/imports run in worker with progress and cancel.
- Checksum mismatch does not activate corrupted payload.
- Resource writes happen only under user-writable data root.

## Regression evidence commands

```powershell
python -m pytest tests/test_resource_paths.py tests/test_resource_registry.py tests/test_health_check_service.py tests/test_resource_download_worker.py -q
python -m pytest tests/test_workspace_app_window_contract.py tests/test_phonikud_adapter_modes.py tests/test_pronunciation_bootstrap_ui_wiring.py tests/test_project_exchange_bundle_extras.py -q
```

Expected:

- all tests pass,
- no new warnings/errors in touched release/resource modules.

## Artifacts checklist

- Screenshot: Installer component selection page.
- Screenshot: First-run wizard Step 2/5 (local models status).
- Screenshot: Resources Manager with status table.
- Screenshot: Health Check report with remediation.
- Screenshot: Baseline import completion message.
- Screenshot: First-run wizard DB step (default/existing/baseline options).
- Screenshot: Switch Database dialog with current DB metadata + restart CTA.
- Screenshot: DBSEL-03 invalid path warning (single error, app alive).
