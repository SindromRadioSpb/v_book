# Product Priority Selection (2026-03-14)

## Context

The generic cold-hunt is complete.

Closed and not to be reopened by default:

- proven UI cold `P0` blockers
- broad `P3` dialog/action sweeps
- lower-layer `sentence_fts` recovery on the two large hewiki DBs
- Concordance as a cold/runtime branch
- a second Sentences runtime patch without new product intent

This means the next wave must be selected from product-facing workflow value,
not from more cold/perf hunting.

## Shortlist

1. Import and project-exchange UX completion
2. Release-facing production readiness / ship gate
3. Dictionary search correctness rollout
4. Coverage / QA reporting surface
5. Guided onboarding and reconnect health UX

## Chosen next wave

`Import and project-exchange UX completion`

Why it wins now:

- the exchange/import backend is stronger than its current user-facing review
  flow;
- it improves a real operator workflow directly;
- it increases release value without reopening cold or lower-layer work;
- the work can stay bounded to existing project import paths.

## Bounded Phase 1 scope

Focus only on the existing `.hdleproj` import path.

In scope:

- real read-only import preflight against the current host DB before import
- clearer preview of host/bundle compatibility and name-conflict handling
- visible import completion summary
- make `Go to Project` actually open the imported project

Out of scope:

- broad import redesign
- incremental import
- side-by-side conflict resolution
- import history
- new schema work
- generic performance work

## Decision gate after Phase 1

After this bounded wave, reassess whether the next highest-value direction is:

- release-facing validation hardening
- Dictionary search correctness rollout
- or stopping implementation expansion and preserving the shortlist as-is
