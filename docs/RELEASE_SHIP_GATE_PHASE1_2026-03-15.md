# Release / Ship Gate Phase 1 (2026-03-15)

## Goal

Turn the existing prebuild validation path into a more trustworthy release gate
for real operator builds, without opening a broad release redesign.

## Implemented in this wave

- added a bounded DB corruption probe to `scripts/prebuild_validate.py`
- moved the corruption probe ahead of write-heavy prebuild checks
- made downstream checks skip cleanly when the DB is already known corrupt
- surfaced explicit repair guidance:
  - `python scripts/repair_db_corruption.py --db-path "<db-path>"`

## Immediate operational outcome

Live validation on `2026-03-15` showed that the new gate is not theoretical:

- `hewiki_gpu_processing test.db` fails the corruption probe
- `hewiki_gpu_processing.db` also fails the corruption probe

Meaning:

- the ship gate is working as intended;
- current heavy hewiki reference artifacts should not be treated as release-ready
  just because older lower-layer notes had closed narrower FTS-specific branches;
- release readiness is now explicitly blocked until the selected release-candidate
  DB passes the new prebuild corruption gate.

## Why this matters now

After the import/export product wave and the live malformed-export incident,
release confidence depends on catching unhealthy DB artifacts before:

- export/import roundtrip attempts
- project lifecycle write probes
- misleading late failures during build validation

## Files

- `scripts/prebuild_validate.py`
- `tests/test_prebuild_validate_corruption_gate.py`
- `tests/test_prebuild_validate_reference_ro.py`
- `docs/QA_PREBUILD_CHECKLIST.md`
- `docs/RELEASE_CHECKLIST_WINDOWS.md`

## Out of scope

- full CI/release pipeline redesign
- installer/build script refactor
- packaged runtime self-check redesign
- broad DB health tooling changes outside prebuild validation

## Decision gate after this wave

If release-facing work continues, the next bounded choice should be one of:

- machine-readable release evidence aggregation
- installed/dist self-check contract hardening
- or stop here and move to Dictionary search correctness rollout
