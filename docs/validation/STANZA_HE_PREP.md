# Stanza Hebrew Model — Setup Guide (PowerShell)

> This guide covers installing Stanza and preparing the Hebrew model for C02 validation tests.
> All commands are PowerShell-only (Windows 11).

---

## 1. Check if stanza is already installed

```powershell
cd E:\projects\Project_Vibe\V_book
.\.venv\Scripts\python.exe -c "import stanza; print('stanza version:', stanza.__version__)"
```

Expected: `stanza version: 1.11.1` (or newer).
If ImportError: proceed to step 2. If already installed: skip to step 3.

---

## 2. Install stanza (if missing)

stanza is listed as a core dependency in `pyproject.toml`. Install via:

```powershell
cd E:\projects\Project_Vibe\V_book
.\.venv\Scripts\pip.exe install "stanza>=1.7.0"
```

---

## 3. Download the Hebrew model

The model is **~700 MB** and is downloaded once to the user cache.

```powershell
cd E:\projects\Project_Vibe\V_book
.\.venv\Scripts\python.exe -c "import stanza; stanza.download('he')"
```

Default model cache location (Windows):
```
%LOCALAPPDATA%\StanfordNLP\stanza\Cache\<version>\resources\he\
```

Typical path:
```
C:\Users\<user>\AppData\Local\StanfordNLP\stanza\Cache\1.11.0\resources\he\
```

Override with environment variable:
```powershell
$env:STANZA_HOME = "F:\stanza_models"
.\.venv\Scripts\python.exe -c "import stanza; stanza.download('he')"
```

---

## 4. Preflight check — verify model is available

```powershell
cd E:\projects\Project_Vibe\V_book
.\.venv\Scripts\python.exe -c "
from tests.validation.conftest import _stanza_he_model_available
print('stanza + he model available:', _stanza_he_model_available())
"
```

Expected: `stanza + he model available: True`

---

## 5. Run C02 tests (requires stanza + he model)

```powershell
cd E:\projects\Project_Vibe\V_book
# Wave 6a — infra smoke (10 tests)
.\.venv\Scripts\python.exe -m pytest tests/validation/test_v02_token_morph.py -v
# Wave 6b — morphology contract (30 tests)
.\.venv\Scripts\python.exe -m pytest tests/validation/test_v02v2_token_morph.py -v
# Both waves together (40 tests)
.\.venv\Scripts\python.exe -m pytest tests/validation/test_v02_token_morph.py tests/validation/test_v02v2_token_morph.py -v
```

Expected: `10 passed` (Wave 6a), `30 passed` (Wave 6b), `40 passed` (combined).

---

## 6. Run all stanza-dependent validation tests

```powershell
cd E:\projects\Project_Vibe\V_book
.\.venv\Scripts\python.exe -m pytest tests/validation/ -v -m requires_stanza
```

Expected: `40 passed` when stanza + he model available; `40 skipped` otherwise.

---

## 7. Run non-stanza validation (unchanged baseline)

```powershell
cd E:\projects\Project_Vibe\V_book
.\.venv\Scripts\python.exe -m pytest tests/validation/ -q -k "not v02 and not stanza"
```

Expected: `247 passed` (Wave 5b baseline).

---

## 8. Run full validation suite (non-Stanza + C02)

```powershell
cd E:\projects\Project_Vibe\V_book
.\.venv\Scripts\python.exe -m pytest tests/validation/ -v
```

Expected (stanza + model available): `287 passed` (247 non-Stanza + 40 C02).
Expected (stanza not available): `247 passed, 40 skipped`.

---

## 9. Environment caveats

| Situation | Behaviour |
|-----------|-----------|
| stanza not installed | All C02 tests skip (`requires_stanza` marker) |
| stanza installed, `he/` model dir missing | All C02 tests skip (`_stanza_he_model_available()` returns False) |
| stanza installed, model dir present, pipeline load fails | Tests using `stanza_engine` fixture skip via `pytest.skip()` |
| STANZA_HOME set but model not re-downloaded there | `he/` dir absent → tests skip |

**Important:** The `requires_stanza` marker is evaluated at import time using a cheap filesystem
check (`he/` directory existence). It does NOT load the pipeline. The `stanza_engine` fixture
is the authoritative gate for actual pipeline availability.

**CI environments:** C02 tests are expected to skip in CI without model download. Do NOT treat
C02 skips as failures in CI. The non-Stanza baseline (247 tests) must always pass.

**Model size:** ~700 MB. Do NOT include in repo or Docker image. Download once per dev machine.

**Model version pinning:** Gold cases in `c02_token_morph.json` are calibrated against
`stanza 1.11.1`. If output changes across Stanza versions, check `stanza_version_calibrated`
field in the gold file and re-run calibration if needed.

---

## 10. Quick reference — defect codes

| Code | Symptom | Fix |
|------|---------|-----|
| D05 | `pytest.skip("stanza not installed or Hebrew 'he' model directory not found")` | Steps 1–4 above |
| D05 | `pytest.skip("Stanza Hebrew model unavailable: ...")` | Model present but corrupt → re-download: step 3 |
| D01 | Smoke test fails after Stanza upgrade | Re-calibrate gold; see `stanza_version_calibrated` in JSON |
