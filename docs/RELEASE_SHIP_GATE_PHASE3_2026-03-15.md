# Release / Ship Gate Phase 3 (2026-03-15)

## Goal

Harden the installed/dist self-check contract so frozen verification proves both
runtime helper health and DB-open readiness on the selected target DB.

## Implemented in this wave

- `app.main` now exposes stronger `db_open` self-check metadata:
  - `db_profile`
  - `db_exists`
  - `db_size_bytes`
  - `schema_version`
  - `supported_schema_version`
- `scripts/verify_frozen_health.ps1` now verifies:
  - ONNX probe
  - import self-check
  - health self-check
  - db_open self-check
- frozen verification now writes a canonical summary artifact:
  - `frozen_health_summary.json`

## Why this matters now

Earlier release waves proved:

- corrupt candidate DBs must fail early;
- prebuild evidence should be machine-readable.

This wave closes the remaining installed/dist verification gap:

- frozen self-check now proves the target DB opens cleanly in the packaged app;
- schema/profile evidence is preserved with the same build metadata as import
  and health;
- release sign-off no longer depends on manually correlating several JSON files.

## Files

- `app/main.py`
- `scripts/verify_frozen_health.ps1`
- `tests/test_main_self_check_helpers.py`
- `docs/BUILD_WINDOWS_INSTALLER.md`
- `docs/RELEASE_CHECKLIST_WINDOWS.md`
- `docs/ENGINEERING_CONTROL_OPTIMIZATION_ROADMAP_2026-03-11.md`

## Out of scope

- new runtime health checks
- installer/build script redesign
- reconnect flow UX
- release-candidate DB selection policy

## Decision gate after this wave

If product-facing work continues from here, the next bounded choice should be:

- richer reconnect-path guidance around heavy DB selection/restart

not another broad release redesign wave.
