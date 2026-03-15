# Guided Onboarding / Reconnect UX Phase 1 (2026-03-15)

## Goal

Add a bounded guidance layer to the existing first-run health page so operators
can see what to do next without reading the raw health report line-by-line.

## Why this wave exists

The first-run wizard already had:

- staged/background health loading;
- direct access to Resources Manager;
- direct access to MT Provider Settings;
- direct access to Audio Provider Settings.

But the final health page still behaved mostly like a raw diagnostic dump:

- it showed the full health report text;
- it did not summarize severity counts;
- it did not highlight the next recommended fix;
- it did not enable context actions based on the actual report.

## Implemented in this wave

- added severity summary counts to the wizard health page
- added a recommended-next-step label
- added contextual fix actions on the health page:
  - `Fix Local Resources`
  - `Fix MT Providers`
  - `Fix Audio Providers`
- contextual buttons stay disabled while health is still loading
- buttons enable only for actionable `warn` / `error` categories found in the
  current health report
- the recommendation prefers local resources first, then MT, then audio

## Files

- `app/ui/first_run_wizard.py`
- `tests/test_first_run_wizard_staged_health.py`
- `docs/GUIDED_ONBOARDING_RECONNECT_PHASE1_2026-03-15.md`
- `docs/ENGINEERING_CONTROL_OPTIMIZATION_ROADMAP_2026-03-11.md`

## Out of scope

- changes to `HealthCheckService` semantics
- new health checks
- reconnect flow redesign
- baseline/resource import redesign
- provider configuration redesign
- installer flow changes

## Decision gate after this wave

If product-facing work continues from here, the next bounded choice should be
one of:

- richer reconnect-path guidance around heavy DB selection/restart
- stronger release/readiness evidence aggregation
- or stop here and preserve onboarding/reconnect guidance at this level.
