# LightBlueTTS — Quality Engineering Notes

## Problem Statement

LightBlueTTS quality is good for full sentences (~8/10 cases) but degrades for
single isolated words. Reported failure modes:
- Only the last letter/consonant is audible
- Wrong phonetic reading (e.g., "yarut" instead of "mehirut")
- Initial consonant(s) dropped (e.g., "asher" instead of "kasher")

**Root cause:** Hebrew words without vowel marks (niqqud) go through G2P
diacritization. When phonikud diacritizes a word in isolation (no surrounding
context), accuracy drops vs. the same word inside a sentence. Degraded niqqud
→ consonant-only IPA → LightBlueTTS diffusion model produces partial/wrong audio.

---

## Pipeline (single word)

```
text (no niqqud)
  │
  ▼ sanitize_tts_text()  ← NFC, strip bidi/cantillation
  │
  ▼ context-wrap if single word: "המילה {word}."
  │
  ▼ _apply_g2p()  ← phonikud_onnx.add_diacritics()
  │     branch: phonikud.add_niqqud → phonikud_onnx → raw_text (fallback)
  │
  ▼ extract word from wrapped G2P result
  │
  ▼ phonemize_fn()  ← phonikud.phonemize or hebrew_to_ipa
  │     hebrew_to_ipa: WITH niqqud → IPA with vowels ✓
  │                  WITHOUT niqqud → consonants only ✗
  │
  ▼ LightBlueTTS.create(phonemes)
      steps / cfg_scale selected adaptively by estimated phoneme count
```

---

## Quality Mitigations (v1.0.2)

### M1 — Context wrapping for single words
**Constant:** `_ENABLE_CONTEXT_WRAP = True` (toggleable)

Before G2P, single-word inputs are wrapped:
```
"המילה {word}."
```
This provides a Hebrew definite article context. Phonikud models trained on
full sentences produce better niqqud when the input has grammatical structure.

After G2P: the wrapper is stripped, recovering only the diacritized target word.

**When disabled:** set `_ENABLE_CONTEXT_WRAP = False` in
`app/infra/audio/providers/lightblue_tts_local_provider.py`.

### M2 — Consonant-only IPA detection
After phonemization, if the IPA string has no vowels (a/e/i/o/u) and fewer
than 6 phonemes, a WARNING is logged. This surfaces the degraded-quality case
explicitly rather than silently producing bad audio.

### M3 — Short phoneme count guard
If the IPA phoneme count is below `_MIN_PHONEME_THRESHOLD` (default: 5), a
WARNING is logged with the full text and count.

### M4 — Adaptive diffusion parameters
LightBlueTTS diffusion steps and classifier-free guidance scale are selected
based on estimated phoneme count (derived from Hebrew letter count × 1.5):

| Estimated phonemes | steps | cfg_scale | Use case |
|---|---|---|---|
| < 8 | 48 | 4.5 | Short words (≤ 5 Hebrew letters) |
| 8–15 | 40 | 3.5 | Medium words (6–10 letters) |
| ≥ 16 | 32 | 3.0 | Long words / sentences |

Each (model_dir, style_path, speed, steps, cfg_scale) combination is cached
separately. First call for a new combination loads a new model instance.

---

## G2P Fallback Chain

1. `phonikud.add_nikud / add_niqqud / add_diacritics` — installed phonikud package
2. `phonikud_onnx.Phonikud.add_diacritics` — ONNX runtime (bundled)
3. `raw_text` — original text, no niqqud (degraded quality, logged as WARNING)

Phonemization:
1. `phonikud.phonemize` — from site-packages (if available)
2. `hebrew_to_ipa` — rule-based fallback (`_he_ipa.py`)

`hebrew_to_ipa` requires niqqud for quality output. Without niqqud it produces
consonant-only IPA (known limitation, tested in T18).

---

## Diagnostic Logging

All INFO and WARNING logs are in logger:
`app.infra.audio.providers.lightblue_tts_local_provider`

Key log lines after each synthesis:

```
INFO  G2P branch=phonikud_onnx wrapped=True niqqud='מְהִירוּת'
INFO  phonemize_path=hebrew_to_ipa phonemes='mehirut' count=7
```

Warning cases:
```
WARNING  all G2P branches failed — synthesizing raw text (len=6)
WARNING  short phoneme sequence (count=3 < threshold=5) text='רבות'
WARNING  consonant-only IPA detected (no vowels, count=3) — quality may be degraded
```

---

## Diagnostic Script

```powershell
# Requires: PHONIKUD_MODEL_PATH env var set (optional, for live G2P)
python scripts/tts_spot_check.py --text "מהירות"
python scripts/tts_spot_check.py --text "כאשר" --no-wrap
python scripts/tts_spot_check.py --file corpus.txt
```

Outputs pipeline trace without synthesizing audio. Use to verify that:
- Context-wrap is applied
- Niqqud is added correctly
- IPA has vowels
- Adaptive params are correct

---

## Test Corpus (Acceptance)

### A. User-reported problematic words (should produce vowel-containing IPA with niqqud)
| Word | Niqqud form | Expected IPA vowels |
|---|---|---|
| רבות | רַבּוֹת | ✓ |
| מהירות | מְהִירוּת | ✓ |
| כאשר | כַּאֲשֶׁר | ✓ |

### B. User-confirmed working words (non-regression)
| Word | Niqqud form |
|---|---|
| עצוב | עָצוּב |
| חיצוני | חִיצוֹנִי |
| ינש | יָנוּשׁ |

### C. Without niqqud → consonant-only IPA (known degraded path)
- רבות, מהירות, כאשר without niqqud → no vowels in IPA (expected, documented)
- Fix: ensure G2P adds niqqud before phonemization

### D. Sentences (must not degrade)
- סגסוגת זו מורכבת מברזל ופחמן → steps=DEFAULT or MID
- התהליך כולל חימום לטמפרטורה מבוקרת ולאחר מכן קירור מהיר → steps=DEFAULT
- באחוזים מדויקים → steps=MID or DEFAULT

---

## Known Open Issues

| ID | Issue | Status |
|---|---|---|
| OI-1 | Phonikud accuracy for single words without context — context-wrap is a heuristic, not guaranteed | Mitigated by M1 |
| OI-2 | If G2P falls to raw_text, consonant-only IPA is still synthesized (degraded) | Logged as WARNING; no auto-retry |
| OI-3 | Adaptive params use text-length heuristic, not actual phoneme count | Acceptable for first iteration |
| OI-4 | Model license (notmax123/LightBlue) not verified for commercial use | Provider marked EXPERIMENTAL |
| OI-5 | GPU/TensorRT acceleration not implemented (use_gpu=False) | Deferred |

---

## Tuning Parameters (in `lightblue_tts_local_provider.py`)

| Constant | Default | Effect |
|---|---|---|
| `_ENABLE_CONTEXT_WRAP` | `True` | Toggle single-word context wrapping |
| `_CONTEXT_WRAP_PREFIX` | `"המילה "` | Hebrew prefix for context |
| `_MIN_PHONEME_THRESHOLD` | `5` | Warn below this phoneme count |
| `_PHONEME_SHORT_THRESHOLD` | `8` | Below → steps=48, cfg=4.5 |
| `_PHONEME_MID_THRESHOLD` | `16` | Below → steps=40, cfg=3.5 |
| `_STEPS_SHORT / MID / DEFAULT` | `48 / 40 / 32` | Diffusion steps |
| `_CFG_SHORT / MID / DEFAULT` | `4.5 / 3.5 / 3.0` | Guidance scale |
