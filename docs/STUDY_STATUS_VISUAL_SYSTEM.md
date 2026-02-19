# Study Status Visual System

## Scope

This document defines a single visual/status contract for:

- `Projects > Dictionary`
- `Projects > Terms`
- `Term Card`
- `Translation Management`
- `User Dictionaries`

## Status Dimensions

Each study entity may expose up to five dimensions:

1. `origin`
2. `study`
3. `translation_tier`
4. `audio_status`
5. `noise`

## Enumerations

### Origin

- `project`
- `manual`
- `imported` (reserved)

### Study

- `new`
- `learning`
- `due`
- `mastered`
- `suspended`

### Translation Tier

- `missing`
- `mt`
- `user`
- `approved`
- `deprecated`

### Audio

- `missing`
- `ready`
- `generating` (reserved)
- `failed`

### Noise

- `is_noise = 0|1`

## Truth Owners

- Translation truth: `tm_global` (with Task19 propagation to `tm_entry`)
- Study truth: `study_progress` + per-item suspension in `user_dictionary_item`
- Audio truth: `audio_asset`
- Origin truth: `user_dictionary_item.origin_*`

`user_dictionary_item` does not store translation as truth.

## Visual Composition

- Origin marker: left stripe/token (or dedicated compact marker column)
- Study chip: icon + text label
- Status icons: translation tier + audio + noise in one status column
- Tooltips: full text explanation for each visual token
- Semantic color layer:
  - `new` neutral, `learning` blue, `due` amber, `mastered` green, `suspended` muted
  - Translation/audio/noise/origin use stable semantic colors
  - Cross-view UD marker is `*` and `*!` for `due`

Color is never the only signal.

## View Policy

- `User Dictionaries`: full study visuals (origin + study + status icons + tooltips)
- `Dictionary / Terms / Term Card / TM`: minimal non-intrusive study indicators
- `Hide noise`: default `ON` in all relevant views

## Accessibility / Responsiveness

- No fixed-height assumptions for content tables
- Scrollable lists/tables at all window sizes
- Keyboard focus/activation must remain functional
- Long operations use worker + V3 progress UX
