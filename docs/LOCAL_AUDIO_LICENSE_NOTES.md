# Local Audio License Notes (MMS TTS)

Document purpose:

- Operational compliance notes for optional local audio provider `mms_tts_local`.
- This document is informational and not legal advice.

## Policy contract (product)

- `mms_tts_local` is disabled by default.
- Provider can be enabled only after explicit license gate confirmation in UI.
- Acceptance is stored as an explicit user action flag.
- Without acceptance, provider must not appear as active generation option.

## Distribution policy

- Base installer does not bundle MMS model weights by default.
- Local provider uses external model path configured by user/admin.
- If a bundled/offline pack is introduced later, it needs separate legal review and release note.

## Runtime safety requirements

- Lazy-load model only when provider is selected.
- Concurrency for local synthesis is limited to avoid device overload.
- On license-gate rejection, fail closed with clear message.

## Release checklist

- Verify license gate dialog text is present and linked from provider settings.
- Verify default provider chain excludes `mms_tts_local`.
- Verify docs mention explicit acceptance + external model path requirement.
- Verify packaging spec does not silently include model weights.
