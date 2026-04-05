# LightBlueTTS Integration — Engineering Preflight

**Document type:** Architecture audit / integration decision record
**Status:** Active — pending license verification (see Release Blockers)
**Date:** 2026-04-04
**Relates to:** `docs/LOCAL_AUDIO_LICENSE_NOTES.md`, `docs/AUDIO_ASSET_ARCH.md`

---

## Purpose

This document records the pre-implementation engineering audit for integrating
`maxmelichov/Light-BlueTTS` (Hebrew ONNX-based TTS) as an additional audio
provider in HDLE Premium.

It serves as:
- a decision record for the integration strategy chosen;
- a reference for any future audio provider integration (see §14);
- a release-gate artifact documenting open license blockers.

---

## Scope

In scope:
- New local provider `lightblue_tts` in the existing audio provider stack.
- CPU-only ONNX inference path.
- Opt-in activation via license gate dialog + settings.
- Health check item in `HealthCheckService`.
- Packaging additions in PyInstaller spec.

Out of scope (first iteration):
- TensorRT / GPU-accelerated path.
- Bundling model weights in the installer.
- Download manager or auto-download of model assets.
- Voice style editor or style-json selection UI.
- Rewriting or refactoring any existing TTS subsystem.
- Cloud TTS additions.

---

## Repo Audit Findings

### Audio provider abstraction — confirmed facts

| Component | File | Contract |
|-----------|------|----------|
| Base class | `app/infra/audio/base_provider.py` | `BaseAudioProvider` ABC: `provider_id`, `display_name`, `is_local`, `generate(request) -> result` |
| Registry | `app/infra/audio/providers_registry.py` | Singleton `AudioProvidersRegistry`; `register()` raises on duplicate |
| Config schema | `app/infra/audio/audio_provider_config.py` | `AudioProviderConfig` dataclass; settings keys auto-derived from `provider_id` |
| Config manager | `app/infra/audio/audio_provider_config_manager.py` | `load_config(provider_id) -> AudioProviderConfig`; QSettings backend |
| Default registration | `app/infra/audio/local_providers_setup.py` | `register_default_audio_providers()` — sole registration entry point |
| Generation pipeline | `app/services/audio_generation_service.py` | Single canonical pipeline; pronunciation enrichment → provider chain → asset persistence |
| Playback | `app/services/audio_player_service.py` | QtMultimedia queue player; providers do not interact with playback directly |
| Settings persistence | `app/infra/settings.py` | QSettings INI; keys: `audio/providers/{provider_id}/{setting}` |
| License gate pattern | `app/ui/dialogs/mms_license_gate_dialog.py` | QMessageBox-based gate; acceptance stored in QSettings |
| Provider settings dialog | `app/ui/audio_provider_settings_dialog.py` | Hardcoded `PROVIDERS` dict (lines 53–80+); requires explicit new entry |
| Health checks | `app/services/health_check_service.py` | `HealthCheckService.run_all()` → list of `HealthCheckItem`; extensible |

### Generation service internals (confirmed)

`AudioGenerationService.generate_one()`:
1. Resolves provider chain from `audio/providers/chain` (QSettings JSON list).
2. Calls `_apply_token_pronunciation()` — replaces tokens with niqqud forms from pronunciation DB.
3. Builds SSML if provider supports it (only `google_cloud_tts` and `azure_speech_tts`).
4. Calls `provider.generate(AudioGenerationRequest)` for each provider in chain until success.
5. Writes audio bytes atomically to disk; persists `AudioAsset` record.

`DEFAULT_CHAIN` (line 48):
```python
DEFAULT_CHAIN = [
    "google_cloud_tts",
    "azure_speech_tts",
    "mock_local_audio",
    "mock_online_audio",
]
```
`mms_tts_local` is absent from DEFAULT_CHAIN. The same policy applies to `lightblue_tts`.

### Phonikud in the current stack (confirmed)

- `app/infra/pronunciation/phonikud_adapter.py` — `PhonikudAdapter` wraps optional
  `phonikud` (ONNX-based) module for niqqud inference.
- The adapter is used in the generation service for pronunciation enrichment.
- `phonikud` and `phonikud_onnx` are both declared as `hiddenimports` in
  `hdle_premium_installer.spec` (confirmed present in dependency stack).
- `PhonikudAdapter` callable discovery: `add_niqqud | phonikud | nekud | diacritize`.
  **`phonemize` is not part of the current adapter contract.**
  LightBlueTTS requires `phonikud.phonemize()` — this must be verified before PATCH-01.

### MMS local provider — canonical template for LightBlueTTS

`app/infra/audio/providers/mms_tts_local_provider.py` implements the full pattern:
- License gate check at `generate()` entry.
- `config.enabled` check.
- Lazy imports inside `_synthesize()` with `ImportError → UNSUPPORTED`.
- `FileNotFoundError → INVALID_REQUEST`.
- Thread locks: `_cache_lock`, `_synth_lock`.
- Model cache keyed by model path.
- WAV output: `io.BytesIO` + `wave.open`, int16 PCM.
- Speed via linear interpolation over numpy array.

LightBlueTTS provider must follow this pattern exactly.

---

## Existing Audio/TTS Architecture

```
All UI surfaces (Dictionary, Terms, User Dictionaries, Sentences, TM)
    │
    ▼  (via worker thread)
AudioGenerationService.generate_one()
    ├── PronunciationService.bulk_lookup()   ← niqqud enrichment from DB
    ├── AudioProvidersRegistry.get(id)       ← provider chain resolution
    ├── provider.generate(request)           ← synthesis (may be ONNX, REST, etc.)
    ├── _write_atomic(path, bytes)           ← atomic WAV write
    └── AudioAssetService.upsert()           ← DB persistence
    │
    ▼
AudioPlayerService (QtMultimedia)
    └── queue → track → playback
```

Audio assets are content-addressed by `(speech_hash, input_hash)`.
Provider ID is part of `input_hash` — switching providers does not reuse cached assets.
See `docs/AUDIO_ASSET_ARCH.md` for full storage contract.

---

## Surface Flow Map

All five product surfaces route through the single `AudioGenerationService`.
No surface-specific synthesis code exists. No per-surface provider selection.

| Surface | UI file | Worker entry | Service |
|---------|---------|--------------|---------|
| Dictionary | `app/ui/dictionary_view.py` | `on_generate_audio_selected()` | `AudioGenerationService` |
| Terms | `app/ui/terms_view.py` | audio action handlers | `AudioGenerationService` |
| User Dictionaries | `app/ui/user_dictionaries_view.py` | audio action handlers | `AudioGenerationService` |
| Sentences | `app/ui/sentences_view.py` | audio action handlers | `AudioGenerationService` |
| Translation Management | `app/ui/translation_management_panel.py` | batch audio ops | `AudioGenerationService` |

**Integration consequence:** registering `lightblue_tts` in the provider registry and
adding it to the user's chain automatically makes it available across all five surfaces.
No per-surface UI changes are required.

---

## Current Providers

| Provider ID | Type | Default enabled | Chain position | License gate |
|-------------|------|-----------------|----------------|--------------|
| `google_cloud_tts` | Online REST | No | 1 (default chain) | No |
| `azure_speech_tts` | Online REST | No | 2 (default chain) | No |
| `mms_tts_local` | Local ONNX (transformers) | No | Not in default chain | Yes |
| `mock_local_audio` | Local stub (tone) | Yes | 3 (default chain) | No |
| `mock_online_audio` | Online stub | Yes | 4 (default chain) | No |

SSML is supported only by `google_cloud_tts` and `azure_speech_tts`
(enforced in `AudioProviderConfig.supports_ssml`, line 46).

---

## LightBlueTTS Integration Constraints

### Runtime pipeline (upstream contract)

The upstream usage pattern requires:
1. Input: raw Hebrew text.
2. Diacritization: `phonikud_onnx.Phonikud(model_path=...).add_niqqud(text)`.
3. Phonemization: `phonikud.phonemize(niqqud_text)` — **requires `phonemize` in `phonikud`**.
4. Synthesis: `LightBlueTTS(model_path=..., use_gpu=False).create(phonemes)` → audio data.
5. Output: numpy array or bytes → WAV serialization.

The entire pipeline lives inside the provider's `_synthesize()` method.
The generation service passes `request.source_text` (may already contain partial niqqud
from the pronunciation enrichment step). The provider must handle both cases.

### Dependency constraints

| Package | Status | Notes |
|---------|--------|-------|
| `onnxruntime` | Already in stack (phonikud) | Version compatibility with lightblue_tts must be verified |
| `phonikud` | Already in stack | `phonemize` attr must be verified before PATCH-01 |
| `phonikud_onnx` | Already in stack | `Phonikud` class + `add_niqqud` must be verified |
| `numpy` | Already in stack | Required for WAV serialization |
| `soundfile` | Upstream lists as dep | Must verify if needed or if WAV bytes via `wave` module suffices |
| `light_blue_tts` (exact name TBD) | Not installed | Package name must be verified via `pip show` / import test |
| `onnxruntime-gpu` | Optional | Must not be a required dependency |

### Model assets

- Model weights (`notmax123/LightBlue`) are not bundled in the installer.
- Expected location: `%LOCALAPPDATA%\HDLE\models\lightblue_tts\`.
- Discovery order (consistent with MMS provider pattern):
  1. `config.model_path` from QSettings.
  2. Default data root: `ResourcePaths.resolve_data_root() / "models" / "lightblue_tts"`.
- Missing model → `AudioErrorKind.INVALID_REQUEST` with actionable message.

### GPU / TensorRT policy

- First iteration: CPU-only (`use_gpu=False` hardcoded in provider).
- `onnxruntime-gpu` and TensorRT are not required dependencies.
- GPU path deferred to a subsequent iteration with explicit opt-in config flag.

---

## Blind Spots / Open Questions

| ID | Description | Blocking | Resolution path |
|----|-------------|----------|-----------------|
| BS-1 | **License of `notmax123/LightBlue` model weights** — not confirmed for commercial/premium desktop use | Yes — RELEASE BLOCKER | Manual license review; see §8 |
| BS-2 | **Exact Python package name** for Light-BlueTTS (`light_blue_tts`? `lightblue_tts`?) | Blocks PATCH-01 | `pip install` + import test before PATCH-01 |
| BS-3 | **`phonikud.phonemize()` availability** in the currently installed version | Blocks PATCH-01 | `python -c "import phonikud; print(hasattr(phonikud, 'phonemize'))"` |
| BS-4 | **LightBlueTTS `create()` return type** — numpy array, bytes, or tuple? | Blocks PATCH-01 | `inspect.signature(LightBlueTTS.create)` after install |
| BS-5 | **Output sample rate** — 22050 Hz assumed from upstream examples; not confirmed | Blocks WAV header | Inspect model config or `create()` return metadata |
| BS-6 | **onnxruntime version conflict** between phonikud and lightblue_tts | Low risk | `pip check` after install |
| BS-7 | **`soundfile` requirement** — upstream lists it; may be needed for WAV output | Low risk | Verify if `wave` module output suffices |

---

## Release Blockers

### RB-1 — Model weights license not verified for commercial use

**Status:** OPEN
**Severity:** RELEASE BLOCKER

`notmax123/LightBlue` ONNX model weights are required for synthesis.
The license of these weights for use in a premium/commercial desktop product
has not been verified as of 2026-04-04.

**Policy until resolved:**
- Provider ships as `experimental` mode only.
- Installer does not bundle model weights.
- No silent auto-download of weights in production builds.
- License gate dialog (modelled on `mms_license_gate_dialog.py`) must be
  shown and accepted before the provider activates.
- License gate text must explicitly state: "Model weights license is not
  verified for commercial use. Enable only after your own review."
- Release notes must carry this blocker until the verification is closed.

**Closure condition:** explicit confirmation of license terms for
`notmax123/LightBlue` weights for use in commercial desktop software,
documented in `docs/LOCAL_AUDIO_LICENSE_NOTES.md` with date and source.

**Related:** `docs/LOCAL_AUDIO_LICENSE_NOTES.md` — same policy as MMS TTS.

---

## Risk Register

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|-----------|--------|------------|
| R1 | Model weights license prohibits commercial use | High | Blocks shipping | experimental mode + license gate; no bundling |
| R2 | `pip` package name differs from expected | Medium | Blocks PATCH-01 | Verify via install + import test before coding |
| R3 | `phonikud.phonemize()` absent in installed version | Medium | Blocks synthesis | `hasattr` check + `UNSUPPORTED` error with diagnostics |
| R4 | onnxruntime version conflict | Low | Import failure at runtime | `pip check` after install; pin compatible version |
| R5 | LightBlueTTS `create()` API diverges from upstream README | Medium | Synthesis failure | Verify signature before PATCH-01; wrap in structured error |
| R6 | Synthesis latency exceeds default 15s timeout | Medium | `UNKNOWN` errors in UI | Provider-specific `timeout_seconds=60` in config defaults |
| R7 | Long text causes OOM on CPU inference | Low | Worker crash | Enforce `max_chars_per_request` in config; document limit |
| R8 | Regression in existing providers after registration | Low | Breaks existing audio | Registry reset in tests; regression test suite required |

---

## PowerShell Verification Steps

Run before starting PATCH-01. All commands in the project venv.

```powershell
cd E:\projects\Project_Vibe\V_book
.\.venv\Scripts\Activate.ps1

# Step 1: Verify existing stack
pip show onnxruntime phonikud phonikud-onnx

# Step 2: Install Light-BlueTTS (try PyPI first, then GitHub)
pip install light-blue-tts
# If not found on PyPI:
# pip install "git+https://github.com/maxmelichov/Light-BlueTTS.git"

# Step 3: Verify import name (BS-2)
python -c @"
import importlib
for name in ['light_blue_tts', 'lightblue_tts', 'LightBlueTTS']:
    try:
        m = importlib.import_module(name)
        print('FOUND:', name)
        print('  attrs:', [x for x in dir(m) if not x.startswith('_')])
        break
    except ImportError:
        print('not found:', name)
"@

# Step 4: Verify class signature (BS-4, BS-5)
python -c @"
import inspect, light_blue_tts as lbt  # adjust name from Step 3
cls = lbt.LightBlueTTS
print('__init__:', inspect.signature(cls.__init__))
print('create:  ', inspect.signature(cls.create))
"@

# Step 5: Verify phonemize availability (BS-3)
python -c @"
import phonikud
print('has phonemize:', hasattr(phonikud, 'phonemize'))
print('phonikud attrs:', [x for x in dir(phonikud) if not x.startswith('_')])
"@

# Step 6: Verify phonikud_onnx.Phonikud (BS-4)
python -c @"
import inspect, phonikud_onnx
cls = phonikud_onnx.Phonikud
print('__init__:', inspect.signature(cls.__init__))
print('add_niqqud:', inspect.signature(cls.add_niqqud))
"@

# Step 7: Check for dependency conflicts
pip check

# Step 8: Record installed versions
pip show light-blue-tts onnxruntime phonikud phonikud-onnx numpy soundfile
```

Record the output of Steps 3–8 before proceeding to PATCH-01.

---

## Recommended Integration Strategy

### Decision: new provider following the MMS local provider pattern

**Rationale:** The existing `mms_tts_local` provider establishes the complete
pattern for a local, license-gated, ONNX-based provider. LightBlueTTS fits
this pattern exactly. Deviating from it would introduce parallel conventions
without justification.

**Key decisions:**

1. **Provider ID:** `lightblue_tts`
2. **Not in DEFAULT_CHAIN.** Opt-in only; user must explicitly add to chain in
   Audio Provider Settings.
3. **License gate required** (RB-1). Gate stored at
   `audio/providers/lightblue_tts/license_accepted`.
4. **Disabled by default** (`enabled=False` in config defaults).
5. **Synthesis pipeline lives entirely inside the provider.** The generation
   service is not modified. Text enrichment (partial niqqud) from the service
   layer is accepted as-is; the provider adds full niqqud + phonemizes
   internally.
6. **Timeout:** `timeout_seconds=60.0` default (vs. 15s for online providers).
7. **CPU-only first iteration.** `use_gpu=False` hardcoded; GPU config deferred.
8. **Thread locks** (`_cache_lock`, `_synth_lock`) required — same as MMS.
9. **WAV output:** 16-bit PCM, mono, sample rate from model config.
10. **Error taxonomy:** `ImportError → UNSUPPORTED`, `FileNotFoundError →
    INVALID_REQUEST`, synthesis failure → `UNKNOWN` with full message.

### Files to create or modify

| File | Action |
|------|--------|
| `app/infra/audio/providers/lightblue_tts_local_provider.py` | Create |
| `app/infra/audio/providers/__init__.py` | Add export |
| `app/infra/audio/local_providers_setup.py` | Add to registration loop |
| `app/ui/dialogs/lightblue_license_gate_dialog.py` | Create |
| `app/ui/audio_provider_settings_dialog.py` | Add to `PROVIDERS` dict |
| `app/services/health_check_service.py` | Add `_check_lightblue_tts()` |
| `hdle_premium_installer.spec` | Add hiddenimports |
| `tests/test_lightblue_tts_provider.py` | Create |
| `docs/audio/LIGHTBLUE_TTS_PATCH_PLAN.md` | Create |

---

## Notes for Future Audio Provider Integrations

This section generalises the lessons from this audit for use in subsequent
audio provider integrations.

### Checklist before any new audio provider

1. **Identify provider type:** online REST, local ONNX, local transformers,
   local executable. Pick the closest existing provider as the template.

2. **License gate required if:**
   - Provider uses model weights with unclear or restricted license.
   - Provider requires user agreement before activation.
   Use `mms_license_gate_dialog.py` or `lightblue_license_gate_dialog.py` as
   the pattern.

3. **Registry integration:**
   - Implement `BaseAudioProvider`.
   - Add to `local_providers_setup.register_default_audio_providers()`.
   - Export from `app/infra/audio/providers/__init__.py`.

4. **Settings dialog integration:**
   - Add explicit entry to `AudioProviderSettingsDialog.PROVIDERS` dict.
   - The dict is not auto-discovered from the registry.

5. **DEFAULT_CHAIN policy:**
   - Local providers requiring model setup must NOT be added to `DEFAULT_CHAIN`.
   - Online providers requiring credentials must NOT be added to `DEFAULT_CHAIN`.
   - Only stub/mock providers that work without configuration belong in
     `DEFAULT_CHAIN`.

6. **Surface parity is automatic.** All surfaces use `AudioGenerationService`.
   No per-surface changes are required.

7. **Timeout policy:**
   - Online REST: 15s default.
   - Local ONNX/transformers (small model): 30–45s default.
   - Local ONNX (large model or slow CPU inference): 60s default.

8. **Packaging:**
   - Add provider module to `hiddenimports` in `hdle_premium_installer.spec`.
   - Add license gate dialog module to `hiddenimports`.
   - Do not bundle model weights in the installer without explicit license
     review and installer size budget review.

9. **Health check:**
   - Add a `HealthCheckItem` in `HealthCheckService` for any provider with
     non-trivial readiness requirements (local model, external dependency).

10. **Test coverage required:**
    - Registry registration, license gate, disabled path, missing deps,
      missing model, happy path (mocked synthesis), speed smoke, regression
      on existing providers.
