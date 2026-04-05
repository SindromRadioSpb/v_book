# LightBlueTTS Integration — Patch Plan

**Document type:** Implementation execution plan
**Status:** Pending — PATCH-00 blocked on license gate design; PATCH-01 blocked on API verification (see Preconditions)
**Date:** 2026-04-04
**Relates to:** `docs/audio/LIGHTBLUE_TTS_ENGINEERING_PREFLIGHT.md`, `docs/LOCAL_AUDIO_LICENSE_NOTES.md`

---

## Objective

Integrate `maxmelichov/Light-BlueTTS` as a new local audio provider `lightblue_tts`
into the existing HDLE Premium audio stack, following the canonical provider pattern
established by `mms_tts_local`.

The provider must:
- Register in `AudioProvidersRegistry` via `local_providers_setup.py`.
- Be opt-in only (not in DEFAULT_CHAIN).
- Require explicit license gate acceptance.
- Run synthesis off the UI thread.
- Degrade gracefully when dependencies or model assets are absent.
- Pass all required tests before merge.

---

## Non-Goals

The following are explicitly out of scope for this patch series:

- TensorRT or GPU-accelerated synthesis path.
- Bundling model weights in the installer.
- Auto-download of model weights.
- Voice style editor or `style_json` selection UI.
- Modifying `AudioGenerationService.DEFAULT_CHAIN`.
- Modifying any per-surface UI (Dictionary, Terms, User Dictionaries,
  Sentences, Translation Management) — surface parity is automatic via
  the shared `AudioGenerationService`.
- Refactoring any existing provider.
- Adding cloud TTS providers.
- Changing the `PhonikudAdapter` contract.

---

## Preconditions

The following must be verified before starting PATCH-01.
PATCH-00 (scaffold) can proceed without them.

### PC-1 (blocks PATCH-01): Python package name verified

```powershell
pip install light-blue-tts   # or git+ URL if not on PyPI
python -c "import light_blue_tts; print('OK')"   # adjust name if different
```

Record the exact importable module name.

### PC-2 (blocks PATCH-01): `LightBlueTTS` class signature confirmed

```powershell
python -c @"
import inspect, light_blue_tts as lbt
print('__init__:', inspect.signature(lbt.LightBlueTTS.__init__))
print('create:  ', inspect.signature(lbt.LightBlueTTS.create))
"@
```

Record: constructor parameters (model_path, use_gpu, etc.), `create()` input type,
`create()` return type and shape, output sample rate source.

### PC-3 (blocks PATCH-01): `phonikud.phonemize()` confirmed present

```powershell
python -c "import phonikud; print(hasattr(phonikud, 'phonemize'))"
```

If absent, phonemization strategy must be revised before proceeding.

### PC-4 (blocks PATCH-01): `phonikud_onnx.Phonikud` signature confirmed

```powershell
python -c @"
import inspect, phonikud_onnx
print(inspect.signature(phonikud_onnx.Phonikud.__init__))
print(inspect.signature(phonikud_onnx.Phonikud.add_niqqud))
"@
```

### PC-5 (blocks release): License of `notmax123/LightBlue` weights reviewed

This is a release blocker, not a code blocker.
Implementation may proceed in `experimental` mode without this verification.
The provider must not be marked stable until this is closed.
See `docs/audio/LIGHTBLUE_TTS_ENGINEERING_PREFLIGHT.md §8 — Release Blockers`.

---

## Confirmed Constraints

These are facts confirmed by repo audit, not assumptions.

- All five product surfaces (Dictionary, Terms, User Dictionaries, Sentences,
  Translation Management) route audio generation through the single
  `AudioGenerationService`. No per-surface changes are required.
- `AudioProviderSettingsDialog.PROVIDERS` is a hardcoded dict. New providers
  must be added explicitly; the registry is not auto-discovered by the dialog.
- `DEFAULT_CHAIN` must not be modified. `lightblue_tts` is opt-in only.
- `mms_tts_local` is the canonical template for this provider type.
- `phonikud` and `phonikud_onnx` are already in the dependency stack and
  declared in `hdle_premium_installer.spec` hiddenimports.
- `AudioGenerationService._provider_supports_ssml()` hardcodes the SSML-
  capable providers. `lightblue_tts` does not use SSML; no change needed.
- Worker-thread safety: `generate()` is called from a worker thread.
  All UI updates are handled by the existing worker/signal infrastructure.
  The provider must not interact with UI.

---

## Patch Series Overview

| Patch | Scope | Preconditions |
|-------|-------|---------------|
| PATCH-00 | Scaffold: provider skeleton + license gate dialog | None |
| PATCH-01 | Synthesis pipeline (`_synthesize()`) | PC-1, PC-2, PC-3, PC-4 |
| PATCH-02 | UI/config wiring: settings dialog + health check | PATCH-01 merged |
| PATCH-03 | Packaging, docs, tests | PATCH-02 merged |

Each patch must be independently buildable and passable through the smoke
check `python -c "import app; print('OK')"`.

---

## PATCH-00: Scaffold + License Gate Dialog

**Goal:** Establish the provider structure with a working license gate.
No synthesis is implemented in this patch. `generate()` returns
`UNSUPPORTED` until PATCH-01 completes.

### Files

| File | Action | Notes |
|------|--------|-------|
| `app/ui/dialogs/lightblue_license_gate_dialog.py` | Create | License gate dialog modelled on `mms_license_gate_dialog.py` |
| `app/infra/audio/providers/lightblue_tts_local_provider.py` | Create | Provider skeleton |
| `app/infra/audio/providers/__init__.py` | Edit | Add `LightBlueTTSLocalProvider` export |
| `app/infra/audio/local_providers_setup.py` | Edit | Add `LightBlueTTSLocalProvider` to registration loop |

### `lightblue_license_gate_dialog.py` contract

```python
LIGHTBLUE_LICENSE_ACCEPTED_KEY = "audio/providers/lightblue_tts/license_accepted"

def ensure_lightblue_license_accepted(*, parent=None) -> bool:
    """Prompt for license gate. Returns True when accepted."""
    # Dialog text must include:
    # "LightBlueTTS model weights (notmax123/LightBlue) license has not been
    #  verified for commercial use. Enable only after your own legal review."
```

### `LightBlueTTSLocalProvider` skeleton contract (PATCH-00)

```python
class LightBlueTTSLocalProvider(BaseAudioProvider):
    provider_id  = "lightblue_tts"
    display_name = "LightBlueTTS Hebrew (Local, Experimental)"
    is_local     = True
    LICENSE_GATE_KEY = LIGHTBLUE_LICENSE_ACCEPTED_KEY

    def generate(self, request) -> AudioGenerationResult:
        # 1. Check license gate → UNSUPPORTED if not accepted
        # 2. Check config.enabled → UNSUPPORTED if disabled
        # 3. Check source_text empty → INVALID_REQUEST
        # 4. Return UNSUPPORTED("model assets not configured — see setup docs")
        #    [placeholder until PATCH-01]
```

### Commit message

```
feat(audio): scaffold LightBlueTTS provider with license gate
```

---

## PATCH-01: Runtime Synthesis Pipeline

**Goal:** Implement `_synthesize()` with the full pipeline.
**Requires:** PC-1, PC-2, PC-3, PC-4 completed.

### Files

| File | Action | Notes |
|------|--------|-------|
| `app/infra/audio/providers/lightblue_tts_local_provider.py` | Edit | Implement `_synthesize()` |

### `_synthesize()` implementation contract

```python
_cache_lock = Lock()   # guards model/tokenizer loading
_synth_lock = Lock()   # gates concurrent synthesis calls
_model_cache: dict[str, tuple] = {}

def _synthesize(
    self,
    *,
    text: str,
    model_path: str | None,
    speed: float,
) -> tuple[bytes, int]:
    """Returns (wav_bytes, sample_rate). Must not raise."""
```

Pipeline steps:
1. **Lazy import** `light_blue_tts` (exact name from PC-1).
   `ImportError` → raise with message "LightBlueTTS dependencies missing: {exc}".
2. **Lazy import** `phonikud_onnx`.
   `ImportError` → raise with message "phonikud_onnx missing: {exc}".
3. **Lazy import** `phonikud`; verify `phonemize` attr (PC-3).
   Missing attr → raise `ImportError("phonikud.phonemize not available")`.
4. **Model path resolution:**
   - Use `config.model_path` if set.
   - Fall back to `ResourcePaths.resolve_data_root() / "models" / "lightblue_tts"`.
   - If resolved path does not exist: raise `FileNotFoundError(f"LightBlueTTS model not found: {path}")`.
5. **Model load** (under `_cache_lock`, keyed by model path):
   - `phonikud_onnx.Phonikud(model_path=...)` — nikud model.
   - `LightBlueTTS(model_path=..., use_gpu=False)` — synthesis model.
   - Cache both.
6. **Diacritization** (under `_synth_lock`):
   `niqqud_text = phonikud_instance.add_niqqud(text)`.
7. **Phonemization:**
   `phonemes = phonikud.phonemize(niqqud_text)`.
8. **Synthesis:**
   `audio_data = tts_instance.create(phonemes)`.
   `audio_data` type and sample rate from PC-2 / PC-5.
9. **Speed adjustment** (if speed != 1.0):
   Linear interpolation via numpy — same pattern as `mms_tts_local_provider._synthesize()`.
10. **WAV serialization:**
    numpy float32 → int16 PCM → `io.BytesIO` + `wave.open` — same as MMS provider.
11. Return `(wav_bytes, sample_rate)`.

### Error handling in `generate()`

| Exception | `AudioErrorKind` | Message |
|-----------|-----------------|---------|
| `ImportError` | `UNSUPPORTED` | "LightBlueTTS dependencies missing: {exc}" |
| `FileNotFoundError` | `INVALID_REQUEST` | exact path in message |
| Any other | `UNKNOWN` | `str(exc)`, logged at ERROR |

### Timeout policy

Default `timeout_seconds=60.0` via `AudioProviderConfig`.
The generation service enforces the timeout at the caller level.
No additional timeout wrapper needed inside `_synthesize()`.

### Commit message

```
feat(audio): implement LightBlueTTS synthesis pipeline (CPU-only, ONNX)
```

---

## PATCH-02: UI / Config / Health Check Wiring

**Goal:** Make the provider visible and configurable in the settings dialog;
add health check item.

### Files

| File | Action | Notes |
|------|--------|-------|
| `app/ui/audio_provider_settings_dialog.py` | Edit | Add `lightblue_tts` to `PROVIDERS` dict |
| `app/services/health_check_service.py` | Edit | Add `_check_lightblue_tts()` + call in `run_all()` |
| `app/ui/audio_provider_settings_dialog.py` | Edit | Import and invoke license gate on enable |

### `PROVIDERS` dict entry

```python
"lightblue_tts": {
    "name": "LightBlueTTS Hebrew (Local, Experimental)",
    "default_rate_limit": 600,
    "default_enabled": False,
    "supports_advanced": True,
},
```

### `_check_lightblue_tts()` contract

```python
def _check_lightblue_tts(self) -> HealthCheckItem:
    """Check LightBlueTTS provider readiness."""
    check_id = "bootstrap:lightblue_tts"
    title    = "Local Audio: LightBlueTTS (Experimental)"

    # 1. Try import of light_blue_tts → UNSUPPORTED if missing
    # 2. Try import of phonikud_onnx → UNSUPPORTED if missing
    # 3. Verify phonikud.phonemize attr → warn if missing
    # 4. Resolve model path; check existence → warn if missing
    # 5. Return HealthCheckItem with check_id, title, status, message, remediation
```

Status levels:
- `ok` — all deps and model path present.
- `warn` — deps present, model path missing (user action needed).
- `error` — required dependency missing.
- `optional` — provider is disabled in settings (no check performed).

`run_all()` change: add `items.append(self._check_lightblue_tts())` after
the `_check_cloud_providers()` block.

### Commit message

```
feat(audio): wire LightBlueTTS into settings dialog and health check
```

---

## PATCH-03: Packaging + Docs + Tests

**Goal:** Freeze the integration with tests, packaging, and documentation.

### Files

| File | Action | Notes |
|------|--------|-------|
| `hdle_premium_installer.spec` | Edit | Add hiddenimports |
| `tests/test_lightblue_tts_provider.py` | Create | Full test suite (see §Tests) |
| `docs/audio/LIGHTBLUE_TTS_ENGINEERING_PREFLIGHT.md` | Update | Close any open BS items resolved by PC-1..PC-4 |

### Hiddenimports to add in spec

```python
# LightBlueTTS provider
'app.infra.audio.providers.lightblue_tts_local_provider',
'app.ui.dialogs.lightblue_license_gate_dialog',
'<exact_package_name>',   # from PC-1 verification
# phonikud_onnx already present; verify it is in the list
```

### Commit message

```
chore(audio): packaging, docs, and tests for LightBlueTTS provider
```

---

## Files to Change

| File | Patch | Action |
|------|-------|--------|
| `app/infra/audio/providers/lightblue_tts_local_provider.py` | 00, 01 | Create |
| `app/infra/audio/providers/__init__.py` | 00 | Add export |
| `app/infra/audio/local_providers_setup.py` | 00 | Add to registration loop |
| `app/ui/dialogs/lightblue_license_gate_dialog.py` | 00 | Create |
| `app/ui/audio_provider_settings_dialog.py` | 02 | Add to PROVIDERS dict |
| `app/services/health_check_service.py` | 02 | Add `_check_lightblue_tts()` |
| `hdle_premium_installer.spec` | 03 | Add hiddenimports |
| `tests/test_lightblue_tts_provider.py` | 03 | Create |

**Files not touched:**
- `app/services/audio_generation_service.py`
- Any UI surface file (dictionary_view, terms_view, etc.)
- `app/infra/pronunciation/phonikud_adapter.py`
- `app/infra/audio/base_provider.py`
- `app/infra/audio/providers_registry.py`
- `app/infra/audio/audio_provider_config.py`

---

## Tests

File: `tests/test_lightblue_tts_provider.py`

Each test must call `AudioProvidersRegistry.reset()` in setup or via fixture
to prevent state leak between tests.

### T1 — Registry registration

```python
def test_lightblue_tts_registers_correctly():
    # register_default_audio_providers()
    # provider = registry.get("lightblue_tts")
    # assert provider is not None
    # assert provider.is_local is True
    # assert provider.provider_id == "lightblue_tts"
```

### T2 — License gate blocks synthesis

```python
def test_generate_blocked_without_license_accepted(monkeypatch):
    # settings: license_accepted = False
    # result = provider.generate(request)
    # assert not result.is_success
    # assert result.error_kind == AudioErrorKind.UNSUPPORTED
    # assert "license" in result.error_message.lower()
```

### T3 — Disabled provider path

```python
def test_generate_blocked_when_disabled(monkeypatch):
    # settings: license_accepted = True, enabled = False
    # assert not result.is_success
    # assert result.error_kind == AudioErrorKind.UNSUPPORTED
```

### T4 — Missing dependency path

```python
def test_generate_fails_on_missing_deps(monkeypatch):
    # monkeypatch builtins.__import__ to raise ImportError for lightblue_tts
    # settings: license_accepted = True, enabled = True
    # assert result.error_kind == AudioErrorKind.UNSUPPORTED
    # assert "dependencies missing" in result.error_message
```

### T5 — Missing model path

```python
def test_generate_fails_on_missing_model(monkeypatch, tmp_path):
    # license_accepted = True, enabled = True
    # config.model_path = str(tmp_path / "does_not_exist")
    # assert result.error_kind in {AudioErrorKind.INVALID_REQUEST, AudioErrorKind.UNSUPPORTED}
    # assert "model" in result.error_message.lower()
```

### T6 — Happy path (mocked synthesis)

```python
def test_generate_returns_valid_wav(monkeypatch, tmp_path):
    # Create fake model directory
    # Mock LightBlueTTS.__init__ and .create() → numpy zeros array, 22050 Hz
    # Mock phonikud_onnx.Phonikud.add_niqqud() → passthrough
    # Mock phonikud.phonemize() → "S\\e.lOM"
    # result.is_success is True
    # assert result.audio_bytes[:4] == b"RIFF"
    # assert result.provider_id == "lightblue_tts"
    # assert result.mime_type == "audio/wav"
    # assert result.meta.get("sample_rate", 0) > 0
```

### T7 — Empty input guard

```python
def test_generate_empty_text_returns_invalid_request():
    # request.source_text = ""
    # assert result.error_kind == AudioErrorKind.INVALID_REQUEST
```

### T8 — Speed parameter smoke

```python
def test_speed_adjustment_does_not_crash(monkeypatch, tmp_path):
    # Mocked synthesis, speed=0.5 → is_success True
    # Mocked synthesis, speed=2.0 → is_success True
```

### T9 — Existing provider regression

```python
def test_mock_local_audio_unaffected_after_lightblue_registration():
    # register_default_audio_providers()
    # provider = registry.get("mock_local_audio")
    # result = provider.generate(minimal_request)
    # assert result.is_success
```

### T10 — Health check item structure

```python
def test_health_check_lightblue_missing_deps(monkeypatch):
    # Mock import failure for light_blue_tts
    # item = HealthCheckService()._check_lightblue_tts()
    # assert item.check_id == "bootstrap:lightblue_tts"
    # assert item.status in {"warn", "error"}
    # assert item.remediation != ""
```

### T11 — Config persistence

```python
def test_config_persisted_and_loaded(tmp_path):
    # Use isolated QSettings or dict-backed stub
    # Save config with enabled=True, model_path=str(tmp_path / "model")
    # loaded = config_manager.load_config("lightblue_tts")
    # assert loaded.enabled is True
    # assert loaded.model_path == str(tmp_path / "model")
```

---

## Smoke Plan

Run after each patch in order.

```powershell
cd E:\projects\Project_Vibe\V_book
.\.venv\Scripts\Activate.ps1

# After PATCH-00
python -c "import app; print('import smoke: OK')"
python -c @"
from app.infra.audio.providers.lightblue_tts_local_provider import LightBlueTTSLocalProvider
p = LightBlueTTSLocalProvider()
print('provider_id:', p.provider_id)
print('is_local:   ', p.is_local)
"@
python -c @"
from app.infra.audio.local_providers_setup import register_default_audio_providers
from app.infra.audio.providers_registry import AudioProvidersRegistry
AudioProvidersRegistry.reset()
register_default_audio_providers()
ids = AudioProvidersRegistry().list_provider_ids()
assert 'lightblue_tts' in ids, f'not registered: {ids}'
print('PASS: registered')
"@

# After PATCH-01 (requires PC-1..PC-4 done and model assets present)
python -c @"
from app.infra.audio.base_provider import AudioGenerationRequest
from app.infra.audio.providers.lightblue_tts_local_provider import LightBlueTTSLocalProvider
req = AudioGenerationRequest(source_text='שלום', source_lang='he', source_norm='shalom')
p = LightBlueTTSLocalProvider()
r = p.generate(req)
print('is_success:', r.is_success)
print('error_kind:', r.error_kind)
print('audio len:', len(r.audio_bytes))
"@

# After PATCH-02
python -c @"
from app.services.health_check_service import HealthCheckService
item = HealthCheckService()._check_lightblue_tts()
print('check_id:', item.check_id)
print('status:  ', item.status)
print('message: ', item.message)
"@

# After PATCH-03: full regression suite
python -m pytest tests/test_lightblue_tts_provider.py -v
python -m pytest tests/test_audio_provider_chain_fallback.py -v
python -m pytest tests/test_audio_generation_service.py -v
python -m pytest tests/test_audio_provider_config_manager.py -v
python -m pytest -v --tb=short
```

---

## Definition of Done

- [ ] Repo audit completed and documented in `LIGHTBLUE_TTS_ENGINEERING_PREFLIGHT.md`
- [ ] PC-1 through PC-4 verified and recorded before PATCH-01 starts
- [ ] RELEASE BLOCKER RB-1 (weight license) documented with explicit provider `experimental` status
- [ ] License gate dialog implemented; provider does not activate without acceptance
- [ ] `lightblue_tts` NOT in `DEFAULT_CHAIN`
- [ ] Provider disabled by default (`enabled=False`)
- [ ] `generate()` does not block the UI thread (called from existing worker infrastructure)
- [ ] `ImportError` → `UNSUPPORTED` with actionable message; no crash
- [ ] `FileNotFoundError` → `INVALID_REQUEST` with exact path in message
- [ ] Thread locks in place (`_cache_lock`, `_synth_lock`)
- [ ] WAV output: int16 PCM, mono, correct sample rate in `wave` header
- [ ] `AudioProviderSettingsDialog.PROVIDERS` updated
- [ ] `HealthCheckService._check_lightblue_tts()` added and called from `run_all()`
- [ ] `hdle_premium_installer.spec` hiddenimports updated
- [ ] All T1–T11 tests written and passing
- [ ] Existing provider regression tests passing (mock_local_audio, provider chain)
- [ ] Full test suite passing: `python -m pytest -v`
- [ ] `docs/audio/LIGHTBLUE_TTS_ENGINEERING_PREFLIGHT.md` open questions updated with PC-1..PC-4 findings
- [ ] Smoke plan executed and all steps passed

---

## Regression Guardrails

The following must remain unchanged throughout this patch series:

1. **`AudioGenerationService` contract is unchanged.** No modifications to
   `generate_one()`, `_resolve_provider_chain()`, `DEFAULT_CHAIN`, or any
   other method in `audio_generation_service.py`.

2. **`DEFAULT_CHAIN` is unchanged.** `lightblue_tts` is not added.

3. **Existing providers are unaffected.** `google_cloud_tts`, `azure_speech_tts`,
   `mms_tts_local`, `mock_local_audio`, `mock_online_audio` must pass their
   existing tests unchanged after each patch.

4. **No mandatory GPU dependency.** `onnxruntime-gpu` and TensorRT must not
   become required for the application to start or for existing functionality
   to work.

5. **No model weights bundled in installer.** `hdle_premium_installer.spec`
   `datas` must not include LightBlueTTS model files.

6. **`AudioProvidersRegistry` singleton isolation in tests.** Every test that
   registers providers must call `AudioProvidersRegistry.reset()` to avoid
   cross-test state pollution.

7. **No UI code in providers or synthesis path.** Workers emit signals;
   providers have no knowledge of UI widgets or signals.

---

## Release Notes / Rollout Notes

### For release notes (v1.x.x)

```
## New Feature: LightBlueTTS Hebrew TTS Provider (Experimental)

A new local TTS provider based on LightBlueTTS (ONNX, CPU) is available
for Hebrew synthesis.

Status: EXPERIMENTAL. Model weights license has not been verified for
commercial use. The provider is disabled by default and requires:
  1. Explicit license gate acceptance in Audio Provider Settings.
  2. Manually supplied model assets placed in:
     %LOCALAPPDATA%\HDLE\models\lightblue_tts\

The provider is not included in the default generation chain.
To enable, add it to the provider chain in Tools → Translation →
Audio Provider Settings.

GPU/TensorRT acceleration is not supported in this release.
```

### Rollout gates

- [ ] License verification for `notmax123/LightBlue` weights closed before
  removing `(Experimental)` label.
- [ ] Installer bundle of model weights only after explicit license review
  and installer size budget approval.
- [ ] GPU path only in a dedicated subsequent iteration with separate testing.
