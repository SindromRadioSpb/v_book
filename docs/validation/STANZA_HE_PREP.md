# Stanza Hebrew Model — Setup Guide (PowerShell)

> This guide covers installing Stanza and preparing the Hebrew model for C02/C10 validation tests.
> All commands are PowerShell-only (Windows 11).

---

## 0. Validated runtime environment (pinned 2026-03-27)

This is the environment against which all gold cases are calibrated.
**Do not upgrade stanza or torch without re-running calibration on affected gold files.**

| Component | Version / Path |
|-----------|----------------|
| Python venv | `E:\projects\Project_Vibe\V_book\.venv\Scripts\python.exe` |
| stanza | **1.11.1** — `E:\projects\Project_Vibe\V_book\.venv\Lib\site-packages\stanza\` |
| torch | **2.10.0+cu128** — same venv |
| CUDA | **12.8** (NVIDIA GeForce RTX 3070, 8 GB VRAM) |
| Stanza model cache | `C:\Users\lletp\AppData\Local\StanfordNLP\stanza\Cache\1.11.0\resources\` |
| Hebrew model dir | `…\Cache\1.11.0\resources\he\` (exists, `default.zip` ~328 MB) |
| `he/` subdirs | `tokenize/`, `pos/`, `lemma/`, `depparse/`, `mwt/`, `ner/`, `pretrain/`, `forward_charlm/`, `backward_charlm/` |

**Stanza inference device:** GPU (CUDA 12.8) when available; CPU fallback transparent.

**Gold version pin:** `stanza_version_calibrated: "1.11.1"` in all C02 gold files.
If stanza is upgraded, run the preflight calibration script (§4) and diff output before trusting existing gold.

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

Expected: `10 passed` (Wave 6a), `30 passed` (Wave 6b), `40 passed` (combined 6a+6b).

```powershell
# Wave 6c — verb tense contract (53 tests)
.\.venv\Scripts\python.exe -m pytest tests/validation/test_v02v3_token_morph.py -v
```

Expected: `53 passed` (Wave 6c).

---

## 6. Run all stanza-dependent validation tests

```powershell
cd E:\projects\Project_Vibe\V_book
.\.venv\Scripts\python.exe -m pytest tests/validation/ -v -m requires_stanza
```

Expected: `98 passed` (93 C02 + 5 C10) when stanza + he model available; `98 skipped` otherwise.

---

## 7. Run non-stanza validation (unchanged baseline)

```powershell
cd E:\projects\Project_Vibe\V_book
.\.venv\Scripts\python.exe -m pytest tests/validation/ -q -m "not requires_stanza"
```

Expected: `249 passed` (247 prior baseline + 2 TM v3 headless tests).

---

## 8. Run full validation suite (non-Stanza + C02)

```powershell
cd E:\projects\Project_Vibe\V_book
.\.venv\Scripts\python.exe -m pytest tests/validation/ -v
```

Expected (stanza + model available): `347 passed` (249 non-Stanza + 93 C02 + 5 C10).
Expected (stanza not available): `249 passed, 98 skipped`.

## 8a. Run C10 round-trip validation only

```powershell
cd E:\projects\Project_Vibe\V_book
.\.venv\Scripts\python.exe -m pytest tests/validation/test_v10_pipeline_roundtrip.py -v
```

Expected: `5 passed` when stanza + model available; `5 skipped` otherwise.

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

**CI environments:** C02 and C10 tests are expected to skip in CI without model download. Do NOT treat
these skips as failures in CI. The non-Stanza baseline (249 tests) must always pass.

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
