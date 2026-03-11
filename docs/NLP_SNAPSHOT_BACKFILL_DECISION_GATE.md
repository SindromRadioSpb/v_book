# NLP Snapshot Backfill Decision Gate

Status date: `2026-03-11`

## Current contract

Current status for legacy `sentence_nlp_snapshot` backfill on the approved
hewiki dev/test DB:

- accepted for bounded large-scale validation only
- not approved for full-scale production rollout
- not approved for execution on the main install DB
- not a basis yet for freshness/version hardening decisions

This is an intentional hold-state, not an unfinished TODO.

## What is already proven

The following is already supported by real-db evidence on
`hewiki_gpu_processing test.db`:

- the old direct-write path was unsafe at scale
- the staged redesign is materially safer than the old path
- the redesigned path completed real staged tiers at:
  - `10k` cumulative docs
  - `50k` cumulative docs
  - `120k` cumulative docs
- the approved dev/test DB remained healthy after those staged tiers

Primary evidence pack:

- `build/logs/nlp_redesign_validation/*`
- `build/logs/nlp_stage_next/*`
- `build/logs/nlp_stage_120k/*`

## What is not yet proven

The following are still open and must not be assumed:

- full `387639`-doc production readiness of the new staged path
- safety of running the backfill on the main install DB
- absence of long-tail storage-level failures on late full-scale ranges
- whether freshness/version hardening is needed after a safe full-scale run

## Controlled hold-state

Until an explicit decision gate is triggered:

- do not run full-volume snapshot backfill on the working `test.db`
- do not run snapshot backfill on the main install DB
- do not treat `120k` bounded validation as production approval
- do not start freshness/version hardening work
- do not add speculative storage patches without new evidence

## Decision gate checklist

Heavy validation may resume only if at least one of these triggers is true:

- a safe backfill on the main install DB is being considered
- a final sign-off is needed for full coverage uplift on `ID=1`
- a new storage-level patch changes backfill write semantics
- snapshot/checkpoint/version semantics change in a way that affects resume or
  correctness
- bounded tiers show degradation after restart, resume, or later ranges

If none of these triggers is true, keep the backfill track in hold-state.

## Next heavy options

### Option A: intermediate confidence tier

Use this when more confidence is needed, but a final production-style verdict is
not yet required.

Recommended shape:

- target: `250k` cumulative docs on the approved dev/test DB
- keep:
  - staged writes
  - bounded merge
  - bounded segment verification
  - integrity checkpoint mode `none`

Use this option to measure late-tier behavior without committing to a full
production-style run.

### Option B: final validation tier

Use this only when a real rollout/sign-off decision is required.

Recommended shape:

- target: full-volume run
- environment: disposable clone of the approved dev/test DB
- do not use the working `test.db`
- do not use the main install DB

This option is the correct path for a final engineering verdict.

## Future heavy-run package

When the decision gate is triggered, prepare the run package before execution.

### Pre-run gates

- confirm `db_open` is healthy
- record current coverage with `--coverage-only`
- confirm target DB path explicitly
- confirm whether the target is:
  - working dev/test DB
  - disposable clone
  - never main install DB unless separately approved
- confirm expected doc range and whether the goal is:
  - intermediate tier
  - final full-volume sign-off

### Required run contract

- stable slice selection
- explicit chunk size
- explicit merge batch size
- explicit segment quick-check timeout
- explicit integrity checkpoint mode
- explicit output artifact directory

### Abort conditions

Stop the run and preserve evidence if any of the following occurs:

- `db_open` fails after a completed segment
- probe output contains `probe_error`
- quick-check returns a non-timeout failure
- stage rows do not drain after merge
- the run lands in `failed_integrity`
- operator notices unexpected restart/resume mismatch

### Required post-run evidence

- `db_open` artifact
- latest `processor_run` summary
- probe JSONL
- probe summary JSON
- coverage-only output after the run
- note stating whether the run was:
  - bounded evidence only
  - final validation

## What to do now instead

Preferred adjacent work while heavy validation is paused:

- operator-facing coverage/reporting hardening
- docs and runbook hardening
- convergence work between `process with NLP` and `extract terms` that does not
  require mass backfill

## Readiness reporting surfaces

The application now exposes a read-only observability layer for this track:

- **Documents** shows a snapshot readiness card with:
  - doc coverage
  - sentence coverage
  - fully covered docs
  - remaining uncovered docs
  - latest snapshot backfill run summary
- **Terms** shows the last extraction source mix:
  - snapshot-backed rows used
  - reparsed sentences
  - reuse percentage

These UI surfaces are intentionally observational only:

- they do not start backfill
- they do not imply production approval
- they do not bypass the heavy-validation decision gate
- their `Copy Coverage CLI` action only emits the safe `--coverage-only` command

## Decision rule for freshness/version hardening

Do not resume freshness/version work until:

1. a safe full-scale validation path exists
2. a clean coverage-after result is available for the full decision target
3. the rollout question actually requires that decision
