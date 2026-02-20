# Audio Asset Architecture

## Scope and invariants

Hard rules:

- Audio is generated only from source payload (`src_text`, canonical `src_norm`, `src_lang`).
- Translation value is never used to synthesize audio.
- Long operations run in workers with `BatchProgressDialogV3`; no UI-thread generation.
- Internal playback uses sanitized relative paths resolved from `audio_asset`.

## Storage contract

`audio_asset` canonical key:

- `(lang, norm_text, voice_id, speed, provider)` unique.

Persisted status contract in DB:

- `missing | ready | failed`.

Runtime-only stage contract:

- `generating` is shown only in progress UX and activity stream.
- `generating` is not persisted in `audio_asset.asset_status`.

Main fields:

- `asset_status`, `audio_rel_path`, `duration_ms`, `sha256`, `error_text`, timestamps.

## Provider chain contract

Default chain mode:

- `chain` tries providers in configured order.

Forced mode:

- `force:<provider_id>` runs only one provider.

Target professional chain:

- Primary: `google_cloud_tts`
- Secondary: `azure_speech_tts`
- Fallback/dev: `mock_local_audio`, `mock_online_audio`
- Optional local (not in default chain): `mms_tts_local` (license-gated, default disabled)

Master switch:

- `audio/providers/enabled` disables all audio providers when `False`.
- In this state, generation exits early with `No audio provider available`.

## Budget guards and usage tracking

Audio budget guards mirror MT settings per provider:

- `max_chars_per_request`
- `max_requests_per_minute`
- `max_chars_per_day`
- `max_chars_per_month`
- `max_requests_per_day`
- `fail_closed`

Usage is tracked in `audio_usage` table with minute/day/month buckets:

- table: `audio_usage`
- key: `(provider_id, period_type, period_key)` unique
- counters: `char_count`, `request_count`

Pipeline behavior:

- per-request limit is validated before provider call;
- when `fail_closed=true`, exceeding budget blocks provider call;
- successful generation records usage (`char_count=len(source_text)`).

## Pronunciation layer contract

Pronunciation enrichment is applied before synthesis:

- Provider with SSML phoneme support: build SSML/phoneme payload.
- Other providers: phrase/token-level text preprocessing fallback.

Precedence:

- `manual override` entries always win over `auto` entries.
- pronunciation entry key stays canonical (`lang + src_norm`), while spoken payload is surface-oriented.

`pronunciation_entry` v2 fields:

- key: `lang + src_norm` (global, cross-project)
- payload: `niqqud_text`, `ipa`, `reading_text`
- source: `manual | auto | auto_phonikud | import_csv | import_pls`
- confidence: optional `0..1` for auto/import quality hints

Apply strategy (deterministic):

1. exact canonical phrase (`src_norm`) if present,
2. phrase-first longest multiword match,
3. token fallback.

Replacement priority:

1. SSML `<phoneme>` when IPA exists and provider supports SSML,
2. `niqqud_text`,
3. `reading_text`.

Effective spoken payload safety contract:

- build spoken payload from surface source text (`src_text`) + pronunciation overlay;
- `effective_tts_text` is sanitized before provider call:
  - `_` -> space
  - `|` -> rejected in strict manual mode, auto-fixed to space in auto mode
  - repeated whitespace collapsed
- separators `_` and `|` must never reach provider request payload (plain text or SSML).

Bootstrap quality contract:

- bootstrap inference is run against deterministic preferred source text, not canonical `src_norm`.
- canonical key remains `(lang, src_norm)` for storage and lookup.

## MMS local provider contract (license-gate)

- Provider id: `mms_tts_local` (optional offline provider).
- Default: `OFF`.
- Must pass explicit license gate acceptance before provider can be enabled.
- Model weights are external-path based by default; not bundled into base installer.

## Security rules

- Store relative paths only.
- Reject absolute paths, drive paths, and parent traversal (`..`).
- Keep SQL parameterized and sort columns allowlisted.
- Credentials are loaded via `CredentialStore`; no plaintext secrets in QSettings or logs.

## Playback architecture contract

Default playback engine:

- Internal player (`QtMultimedia`) with queue and cadence.
- External OS player fallback remains optional; not default.

Playback cadence settings (persisted):

- `audio/playback/pre_roll_ms` (default `200`)
- `audio/playback/gap_ms` (default `550`)
- `audio/playback/post_roll_ms` (default `300`)
- `audio/playback/play_mode` (`interrupt|enqueue`, default `interrupt`)

Queue semantics:

- `interrupt`: clear queue + stop current track + play new request.
- `enqueue`: append request; if player is idle, start immediately.

Deterministic regenerate/playback contract:

- each `audio_asset` update refreshes `updated_at`;
- playback resolver chooses latest ready by `updated_at DESC, asset_id DESC`;
- provider switch sequence (`google -> mms -> google`) must play the final regenerate result.

Playback state machine:

- `IDLE -> PRE_ROLL -> PLAYING -> POST_ROLL -> GAP -> NEXT`
- No heavy processing in callbacks; transitions run from signal/timer handlers.

UI integration constraints:

- Table playback controls are implemented via `QStyledItemDelegate`.
- `setIndexWidget` per-row controls are forbidden (performance/regression risk).
- No per-row SQL queries during playback actions.

## UX surface (current)

Audio column and actions exist in:

- `User Dictionaries`
- `Dictionary`
- `Terms`
- `Term Cards`
- `Translation Management`

Supported actions:

- `Generate Audio...`
- `Generate Audio Selected (N rows)...`
- `Play Audio Selected (N rows)`
- `Mispronounced -> Add Pronunciation...` (manual override dialog for source norm)

Playback UX surface (target):

- Row-level play button via delegate in existing Audio column.
- Queue playback for selected rows (`Play Audio Selected`).
- Mini player panel/dock with now playing, queue, and pause/resume/stop.

Write modes:

- `MISSING_ONLY`
- `REGENERATE_ALL`

Provider settings entrypoint:

- `Tools -> Translation -> Audio Provider Settings...`

Audio Provider Settings tabs:

- `Rate Limits`
- `Provider Chain`
- `Advanced Settings`
- `Playback`

Advanced includes:

- credentials (`Load from File...` / `Clear` for Google Service Account JSON),
- Azure API key set/clear + region,
- provider voice selection + speech rate,
- voice refresh (`Google` / `Azure`) with local cache,
- budget guards,
- retry/timeout,
- current usage summary (minute/day/month),
- MMS license-gate + model path.

Pronunciation bootstrap gate:

- `Tools -> Translation -> Pronunciation Bootstrap...`
- persisted keys:
  - `pronunciation/phonikud/enabled`
  - `pronunciation/phonikud/model_path`
  - `pronunciation/phonikud/last_health_status`
  - `pronunciation/phonikud/last_health_mode`
  - `pronunciation/phonikud/last_health_report`
- health-check reports strict runtime mode:
  - `real_inference | fallback | error`

Playback tab includes:

- cadence controls (`pre_roll_ms`, `gap_ms`, `post_roll_ms`)
- queue mode (`interrupt` / `enqueue`)
- cadence presets (`Normal` / `Study` / `Fast`)

## Project Exchange policy for pronunciation

- Project bundle can optionally include `pronunciation_metadata.tsv` sidecar.
- Sidecar is metadata-only (no audio assets are embedded).
- Exported subset is intersection with project lexical norms.
- Import merge is safe: manual overrides remain authoritative.
