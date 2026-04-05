# LightBlueTTS — phonikud.phonemize via Subprocess (Variant 1)

## Problem

The project root contains `phonikud.py` (a compatibility shim that provides `add_niqqud` /
`batch_add_niqqud` via ONNX inference or Torch model).  Because Python adds the running
script's directory to `sys.path[0]`, **the shim shadows the installed
`phonikud` package** in site-packages.

The installed `phonikud` package (site-packages) provides `phonemize(text) -> str` — a full
Hebrew G2P-to-IPA pipeline that the LightBlueTTS model was trained on.  Its internal modules
(`phonemize.py`, `hebrew.py`, `lexicon.py`, `variants.py`) use `from phonikud import ...`
style imports.  When the shim is in `sys.modules["phonikud"]`, those imports resolve to the
shim, which does not export `lexicon`, `variants`, etc. → `ImportError`.

The provider's `_load_phonemize()` has a workaround (load via
`importlib.util.spec_from_file_location`, temporarily replacing `sys.modules["phonikud"]`),
which works in dev mode but is fragile:

- Replaces the shim in `sys.modules` in-process, risking confusion for other callers.
- Not guaranteed to work in frozen / packaged builds where path discovery differs.

## Solution — Variant 1: subprocess delegation

Add `phonemize(text: str) -> str` to the shim itself.  The function runs the real
`phonikud.phonemize` in a subprocess where the shim's directory is stripped from `sys.path`,
so the installed package is found instead.

```
provider._load_phonemize()
  → sys.modules["phonikud"] has phonemize? YES (after Variant 1)
  → return shim.phonemize, "phonikud.phonemize"

shim.phonemize(niqqud_text)
  → _run_phonemize_subprocess([niqqud_text])
    → subprocess: sys.path stripped of shim dir
    → from phonikud import phonemize  # site-packages, clean
    → phonemize(niqqud_text)          # returns IPA string
  → IPA string returned to provider
```

## Observed phonikud.phonemize output format

| Input (with niqqud) | Output IPA |
|---------------------|-----------|
| שָׁלוֹם | `ʃalˈom` |
| חוֹמֶר  | `χˈmeʁ` |
| מְהִירוּת | `mhiʁˈut` |
| כָּאֲשֶׁר | `kaʔaʃˈeʁ` |
| עָל / עַל | `ʔˈal` |
| שֶׁל | `ʃˈel` |
| לְאוֹרֶךְ | `lʔoʁˈeχ` |
| הוּסִיף | `husˈif` |

All characters are within the LightBlueTTS vocabulary.  Stress marker `ˈ` is supported.

## What changes

| File | Change |
|------|--------|
| `phonikud.py` | Add `_run_phonemize_subprocess(texts)` + `phonemize(text) -> str` |
| `tests/test_lightblue_tts_provider.py` | Add tests for shim.phonemize and subprocess path |
| This document | Updated after implementation |

**No changes** to `lightblue_tts_local_provider.py` — `_load_phonemize()` already checks
`callable(getattr(sys.modules["phonikud"], "phonemize", None))` and returns it if found.

## Fallback behavior

- Subprocess failure → shim.phonemize returns `""` (empty string).
- Provider sees empty phoneme string → WARNING logged, synthesis continues (silent or
  degraded quality).
- In frozen builds: `phonikud.py` shim is not bundled (dev-only file); the installed
  `phonikud` package is imported directly without subprocess — Variant 1 subprocess adds
  no overhead in that case.

## Risks

| Risk | Mitigation |
|------|-----------|
| Subprocess latency (~200–400 ms Python startup) | Acceptable: synthesis itself takes 2–10 s |
| Subprocess fails in frozen build | Shim not present in frozen build; direct import used |
| Empty IPA from phonemize on short words | Already handled by `_MIN_PHONEME_THRESHOLD` warning + existing fallbacks |
| `sys.executable -c` not available in frozen build | Shim not active in frozen build; no subprocess needed |

## Acceptance criteria

- [ ] `phonemize` callable present in `phonikud` module at runtime.
- [ ] `phonikud.phonemize(שֶׁל)` returns IPA string containing at least one vowel (`e`).
- [ ] `_load_phonemize()` selects `phonikud.phonemize` path (label = "phonikud.phonemize").
- [ ] Subprocess correctly isolates from shim (no `phonikud.lexicon` ImportError).
- [ ] All 90 existing tests pass without regression.
- [ ] New tests (shim.phonemize unit + provider integration) pass.

---

## Implementation notes (post-implementation)

### Changes made

**`phonikud.py`** — added two functions:

```python
_SHIM_DIR: str = str(Path(__file__).resolve().parent)   # module-level constant

def _run_phonemize_subprocess(texts: list[str]) -> list[str]: ...
def phonemize(text: str) -> str: ...
```

`_run_phonemize_subprocess` strips `_SHIM_DIR` from `sys.path` inside the subprocess
via `os.path.normcase` comparison so that the match is case-insensitive on Windows.

`phonemize` is the public function; it calls `_run_phonemize_subprocess([source])` and
returns the first result, or `""` on any exception.

No changes were needed to `lightblue_tts_local_provider.py` — `_load_phonemize()` already
short-circuits on `callable(getattr(sys.modules["phonikud"], "phonemize", None))`.

### Tests added

`tests/test_lightblue_tts_provider.py` — 14 new tests in 3 classes:

| Class | Tests | What is verified |
|-------|-------|-----------------|
| `TestShimPhonemize` (T25) | 9 | `phonemize` present in shim; returns IPA with correct vowels for 7 niqqud words; empty input → empty output |
| `TestLoadPhonemizerPicksShim` (T26) | 2 | `_load_phonemize()` returns label `"phonikud.phonemize"`; the fn returns `e` for שֶׁל |
| `TestPhonemizerSubprocessIsolation` (T27) | 3 | subprocess returns list of correct length; `[]` → `[]`; subprocess can import `phonikud.lexicon` without shim interference |

Total test count: **104** (was 90).

### Acceptance criteria status

- [x] `phonemize` callable present in `phonikud` module at runtime.
- [x] `phonikud.phonemize(שֶׁל)` returns IPA string containing vowel `e` (`ʃˈel`).
- [x] `_load_phonemize()` selects `phonikud.phonemize` path (label = `"phonikud.phonemize"`).
- [x] Subprocess correctly isolates from shim (no `phonikud.lexicon` ImportError).
- [x] All 90 prior tests pass without regression (104/104 total passing).
- [x] New tests (T25–T27) pass.

*Status: IMPLEMENTED — 2026-04-05*
