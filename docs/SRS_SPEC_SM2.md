# SRS Spec (SM-2 Core)

## Purpose

Define deterministic SRS behavior for `User Dictionaries` review mode.

## Progress Storage

Global progress key:

- `canonical_hash = sha256(src_lang + dst_lang + kind + src_norm)`

Progress table: `study_progress`.

Per-item suspension is stored on `user_dictionary_item` and does not alter
global progress history.

## Ratings

Review buttons map to SM-2 quality:

- `Again = 1`
- `Hard = 3`
- `Good = 4`
- `Easy = 5`

## EF Update

Formula:

`EF' = EF + (0.1 - (5-q) * (0.08 + (5-q) * 0.02))`

Clamp:

- minimum EF is `1.3`

## Interval Rules

If `q < 3`:

- `review_count = 0`
- `interval_days = 1`
- `lapse_count += 1`

If `q >= 3`:

- if previous `review_count == 0` -> `interval_days = 1`
- if previous `review_count == 1` -> `interval_days = 6`
- else -> `interval_days = round(interval_days * EF')`
- then `review_count += 1`

In all cases:

- `last_quality = q`
- `last_review_at = now`
- `due_at = now + interval_days days`
- `updated_at = now`

## Computed Study State

`study_state` is computed from progress summary:

1. `suspended` if per-item suspension is enabled
2. `new` if `review_count == 0`
3. `due` if `due_at <= now`
4. `mastered` if long-interval threshold met
5. otherwise `learning`

Mastered threshold in code is explicit and test-covered.

## Queue Rules

Due queue must:

- include only due cards
- exclude suspended items
- keep deterministic order

