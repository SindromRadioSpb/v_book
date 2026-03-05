# Release Gate Stabilization Backlog

## Current Status

- Release GO: NO-GO
- Variant A PATCH/scaling development: GO (independent track)
- Reason: full release gate still has non-green categories that require dedicated stabilization patches.

## Failure Classification Model

Each release-gate failure must be classified into exactly one category:

1. `functional`
- incorrect behavior or assertion mismatch in application logic/tests

2. `schema`
- migration drift, fixture/schema mismatch, missing/extra columns/tables

3. `native`
- crashes/instability in native stacks (for example torch/stanza/onnxruntime access violations)

4. `env`
- machine/runtime isolation issues (permissions/temp paths/AppData leakage)
- target state: minimized or eliminated by deterministic scripts

5. `flaky`
- intermittent failures with no deterministic trigger yet

## Workflow (Deterministic)

1. Run release diagnostic:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_release_gate_diagnostic.ps1
```

2. Review artifacts:
- `build\logs\release_gate_latest.txt`
- `build\logs\release_gate_inventory.md`

3. Classify each `FAILED/ERROR` item into one category.
4. Create small stabilization patches (`PATCH-R01`, `PATCH-R02`, ...), each tied to one category cluster.
5. Re-run release diagnostic after every stabilization patch and record delta.

## Backlog Board

| ID | Category | Scope | Owner | Status | Exit Criteria |
|---|---|---|---|---|---|
| R01 | schema | Migration + fixture drift | TBD | open | No schema-related `FAILED/ERROR` lines in release inventory |
| R02 | functional | Assertion mismatches in full pytest | TBD | open | All functional failures resolved or converted to deterministic env markers with rationale |
| R03 | native | torch/stanza/onnxruntime instability | TBD | open | No native crashes in release diagnostic + packaged smoke |
| R04 | env | Temp/permissions/AppData leakage | TBD | open | No env-only failures with deterministic temp isolation enabled |
| R05 | flaky | Intermittent tests | TBD | open | Repro steps documented; either fixed or quarantined with expiration criteria |

## Acceptance Criteria for Release GO

Release GO may be declared only when all criteria below are true:

1. Release Core Gate is green:
- `powershell -ExecutionPolicy Bypass -File scripts\run_release_gate_diagnostic.ps1` exits `0`.

2. Packaged Smoke Gate is green:
- packaged executable smoke checks pass on target environment.

3. Build traceability is green:
- app runtime/log/self-check expose identical `version`, `commit`, `dirty`, `built_at_utc`.
- release evidence records these values and matches expected release commit.

4. Remaining quarantines (if any) have explicit expiration criteria and owner.

## Non-Blocking Rule for Variant A

- Release stabilization is a separate track.
- Red release gate does not block PATCH/scaling work while Fast Gate remains green.
