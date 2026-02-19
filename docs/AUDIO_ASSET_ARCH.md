# Audio Asset Architecture

## Scope and invariants

Hard rules:

- Audio is generated only from source payload (`src_text`, canonical `src_norm`, `src_lang`).
- Translation value is never used to synthesize audio.
- Long operations run in workers with `BatchProgressDialogV3`; no UI-thread generation.

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

## Pronunciation layer contract

Pronunciation enrichment is applied before synthesis:

- Provider with SSML phoneme support: build SSML/phoneme payload.
- Other providers: token-level niqqud substitution fallback.

Precedence:

- `manual override` entries always win over `auto` entries.

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
- `Edit Pronunciation...` (manual override dialog for source norm)
- `Play Audio Selected (N rows)`

Write modes:

- `MISSING_ONLY`
- `REGENERATE_ALL`

Provider settings entrypoint:

- `Tools -> Translation -> Audio Provider Settings...`
