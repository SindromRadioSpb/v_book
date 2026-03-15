# Release / Ship Gate Phase 2 (2026-03-15)

## Goal

Add machine-readable release evidence aggregation to the existing prebuild
validation flow without widening the validation scope or redesigning the
release pipeline.

## Implemented in this wave

- added `--report-json-out` to `scripts/prebuild_validate.py`
- added a canonical JSON report payload with:
  - final status
  - selected DB path
  - DB size
  - profile / skip flags
  - per-check status + details
  - build metadata (`version`, `commit`, `dirty`, `built_at_utc`)
- documented the artifact path in:
  - `docs/QA_PREBUILD_CHECKLIST.md`
  - `docs/RELEASE_CHECKLIST_WINDOWS.md`

## Why this matters now

Phase 1 made the ship gate stricter and more honest.

Phase 2 makes the result easier to preserve and compare:

- operators no longer need to reconstruct release evidence from console logs
- build/release handoff can point to one JSON artifact
- failed and skipped checks retain their exact remediation details

## Files

- `scripts/prebuild_validate.py`
- `tests/test_prebuild_validate_report_json.py`
- `docs/QA_PREBUILD_CHECKLIST.md`
- `docs/RELEASE_CHECKLIST_WINDOWS.md`
- `docs/ENGINEERING_CONTROL_OPTIMIZATION_ROADMAP_2026-03-11.md`

## Out of scope

- new validation checks
- installer/dist self-check redesign
- CI pipeline redesign
- bundled artifact signing or publishing flow

## Decision gate after this wave

If release-facing work continues from here, the next bounded choice should be
one of:

- installed/dist self-check contract hardening
- release-candidate DB selection discipline
- or stop release-facing expansion here and preserve the ship-gate/reporting
  contract as-is.
