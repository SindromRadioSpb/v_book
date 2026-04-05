"""LightBlueTTS quality spot-check: full synthesis with artifact saving.

Usage (from project root, venv activated):
    python scripts/tts_spot_check.py --text "מהירות"
    python scripts/tts_spot_check.py --text "כאשר" --text "רבות" --text "עצוב"
    python scripts/tts_spot_check.py --file corpus.txt   # one word/phrase per line
    python scripts/tts_spot_check.py --text "מהירות" --no-wrap  # disable context-wrap
    python scripts/tts_spot_check.py --text "מהירות" --out-dir reports/my_check

Artifacts saved to: reports/tts_spot_check/<timestamp>/<slug>.wav
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

# Allow running from project root without package install.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("tts_spot_check")

# -----------------------------------------------------------------------
# Auto-discover model paths
# -----------------------------------------------------------------------

_LOCAL_APP_DATA = os.getenv("LOCALAPPDATA", "")
_HDLE_MODELS = Path(_LOCAL_APP_DATA) / "HDLE" / "models" if _LOCAL_APP_DATA else None

_DEFAULT_LB_MODEL = str(_HDLE_MODELS / "lightblue_tts") if _HDLE_MODELS else ""
_DEFAULT_PHONIKUD = (
    str(next(iter(sorted(
        (_HDLE_MODELS / "phonikud").glob("*.onnx"),
        key=lambda p: (0 if "int8" in p.name else 1, p.name),
    )), None) or "")
    if _HDLE_MODELS and (_HDLE_MODELS / "phonikud").exists()
    else ""
)


# -----------------------------------------------------------------------
# Core per-text check
# -----------------------------------------------------------------------

def _slug(text: str) -> str:
    """Filesystem-safe slug for the text (first 24 chars, hex tail)."""
    h = hashlib.sha1(text.encode()).hexdigest()[:6]
    safe = re.sub(r"[^\w\u05D0-\u05EA]", "_", text)[:24].strip("_")
    return f"{safe}_{h}" if safe else f"text_{h}"


def check_text(
    text: str,
    *,
    lb_model_dir: str,
    phonikud_model_path: str,
    enable_wrap: bool,
    out_dir: Path,
    voice: str = "female1.json",
    speed: float = 1.0,
) -> dict:
    """Run full synthesis pipeline for one text. Returns result dict."""
    from app.infra.audio.providers.lightblue_tts_local_provider import (
        _CONTEXT_WRAP_PREFIX,
        _CONTEXT_WRAP_SUFFIX,
        _adaptive_synth_params,
        _count_ipa_phonemes,
        _extract_g2p_word,
        _has_vowels,
        _is_single_word,
        LightBlueTTSLocalProvider,
    )
    from app.infra.audio.providers._he_ipa import hebrew_to_ipa

    result: dict = {
        "text": text,
        "single_word": _is_single_word(text),
        "was_wrapped": False,
        "g2p_branch": None,
        "niqqud_text": None,
        "phonemize_path": None,
        "phonemes": None,
        "phoneme_count": None,
        "has_vowels": None,
        "steps": None,
        "cfg_scale": None,
        "wav_path": None,
        "error": None,
    }

    steps, cfg_scale = _adaptive_synth_params(text)
    result["steps"] = steps
    result["cfg_scale"] = cfg_scale

    single = _is_single_word(text)
    was_wrapped = enable_wrap and single
    result["was_wrapped"] = was_wrapped

    g2p_input = (
        _CONTEXT_WRAP_PREFIX + text.strip() + _CONTEXT_WRAP_SUFFIX
        if was_wrapped
        else text
    )

    # ----- G2P via phonikud_onnx -----
    try:
        from phonikud_onnx import Phonikud  # type: ignore[import]
        pk = Phonikud(phonikud_model_path)
        niqqud_raw = pk.add_diacritics(g2p_input)
        g2p_branch = "phonikud_onnx"
        niqqud_text = (
            _extract_g2p_word(niqqud_raw, text)
            if was_wrapped and niqqud_raw
            else niqqud_raw
        ) or text
    except Exception as exc:
        niqqud_raw = text
        niqqud_text = text
        g2p_branch = f"raw_text ({exc})"

    result["g2p_branch"] = g2p_branch
    result["niqqud_text"] = niqqud_text

    # ----- Phonemize -----
    phonemes = hebrew_to_ipa(niqqud_text)
    phoneme_count = _count_ipa_phonemes(phonemes)
    result["phonemes"] = phonemes
    result["phoneme_count"] = phoneme_count
    result["has_vowels"] = _has_vowels(phonemes)
    result["phonemize_path"] = "hebrew_to_ipa"

    # ----- Synthesis -----
    try:
        from lightblue_onnx import LightBlueTTS  # type: ignore[import]
        model_dir = Path(lb_model_dir)
        style_path = model_dir / "voices" / voice

        tts = LightBlueTTS(
            onnx_dir=str(model_dir),
            style_json=str(style_path),
            steps=steps,
            cfg_scale=cfg_scale,
            speed=speed,
            seed=42,
            use_gpu=False,
            chunk_len=150,
            silence_sec=0.15,
            fade_duration=0.02,
        )

        import numpy as np
        audio_arr, sample_rate = tts.create(phonemes)
        arr = np.asarray(audio_arr, dtype=np.float32)

        # Padding (same as provider)
        pad = int(sample_rate * 0.12)
        silence = np.zeros(pad, dtype=np.float32)
        arr = np.concatenate([silence, arr, silence])

        # Loudness normalization
        arr = LightBlueTTSLocalProvider._normalize_audio_loudness(arr)
        pcm = (arr * 32767.0).astype(np.int16)

        wav_path = out_dir / f"{_slug(text)}.wav"
        import io
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm.tobytes())
        wav_path.write_bytes(buf.getvalue())
        result["wav_path"] = str(wav_path)
        result["sample_rate"] = sample_rate
        result["duration_ms"] = round(len(arr) / sample_rate * 1000)
        result["rms"] = round(float(np.sqrt(np.mean(np.square(arr, dtype=np.float64)))), 4)

    except Exception as exc:
        result["error"] = str(exc)

    return result


# -----------------------------------------------------------------------
# Report printer
# -----------------------------------------------------------------------

def print_result(r: dict) -> None:
    sep = "=" * 64
    warn = []

    print(f"\n{sep}")
    print(f"Text         : {r['text']!r}")
    print(f"Single word  : {r['single_word']}  |  Wrapped: {r['was_wrapped']}")
    print(f"Steps        : {r['steps']}  |  cfg_scale: {r['cfg_scale']}")
    print(f"G2P branch   : {r['g2p_branch']}")
    print(f"Niqqud       : {r['niqqud_text']!r}")
    print(f"Phonemize    : {r['phonemize_path']}")
    print(f"Phonemes     : {r['phonemes']!r}  (count={r['phoneme_count']})")
    print(f"Has vowels   : {r['has_vowels']}")

    if not r.get("has_vowels") and (r.get("phoneme_count") or 0) < 6:
        warn.append("WARN: consonant-only IPA — TTS quality will be degraded")
    if (r.get("phoneme_count") or 0) < 5:
        warn.append(f"WARN: short phoneme count ({r['phoneme_count']}) — risk of under-convergence")
    if "raw_text" in (r.get("g2p_branch") or ""):
        warn.append("WARN: G2P fell to raw_text — no niqqud added")

    if r.get("error"):
        print(f"ERROR        : {r['error']}")
    elif r.get("wav_path"):
        print(f"WAV saved    : {r['wav_path']}")
        print(f"Duration     : {r.get('duration_ms')} ms  |  RMS: {r.get('rms')}")

    for w in warn:
        print(f"  ⚠  {w}")

    print(sep)


# -----------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="LightBlueTTS quality spot-check with artifact saving"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", action="append", metavar="TEXT",
                       help="Text to synthesize (can repeat for multiple)")
    group.add_argument("--file", metavar="FILE",
                       help="Text file with one word/phrase per line")

    parser.add_argument("--lb-model", default=_DEFAULT_LB_MODEL,
                        help=f"LightBlueTTS model dir (default: {_DEFAULT_LB_MODEL})")
    parser.add_argument("--phonikud-model", default=_DEFAULT_PHONIKUD,
                        help=f"Phonikud ONNX path (default: {_DEFAULT_PHONIKUD})")
    parser.add_argument("--voice", default="female1.json",
                        help="Voice style file (default: female1.json)")
    parser.add_argument("--speed", type=float, default=1.0,
                        help="Speech rate (default: 1.0)")
    parser.add_argument("--no-wrap", action="store_true",
                        help="Disable single-word context wrapping")
    parser.add_argument("--out-dir", default="",
                        help="Output directory for WAV files (default: reports/tts_spot_check/<ts>)")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir) if args.out_dir else _ROOT / "reports" / "tts_spot_check" / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nOutput directory: {out_dir.resolve()}")

    if not args.lb_model or not Path(args.lb_model).exists():
        print(f"ERROR: LightBlueTTS model dir not found: {args.lb_model!r}")
        print("  Set --lb-model or place model at %LOCALAPPDATA%\\HDLE\\models\\lightblue_tts\\")
        sys.exit(1)
    if not args.phonikud_model or not Path(args.phonikud_model).exists():
        print(f"ERROR: Phonikud ONNX not found: {args.phonikud_model!r}")
        print("  Set --phonikud-model or place model at %LOCALAPPDATA%\\HDLE\\models\\phonikud\\")
        sys.exit(1)

    texts: list[str] = []
    if args.text:
        texts = args.text
    else:
        texts = [
            ln.strip()
            for ln in Path(args.file).read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")
        ]

    enable_wrap = not args.no_wrap
    results = []

    for text in texts:
        t0 = time.monotonic()
        print(f"\nSynthesizing: {text!r}  ...", end="", flush=True)
        r = check_text(
            text,
            lb_model_dir=args.lb_model,
            phonikud_model_path=args.phonikud_model,
            enable_wrap=enable_wrap,
            out_dir=out_dir,
            voice=args.voice,
            speed=args.speed,
        )
        elapsed = round((time.monotonic() - t0) * 1000)
        print(f" {elapsed} ms")
        results.append(r)

    # Print all results
    for r in results:
        print_result(r)

    # Summary
    print(f"\n{'=' * 64}")
    print(f"Synthesized  : {len(results)} items")
    ok = [r for r in results if r.get("wav_path")]
    err = [r for r in results if r.get("error")]
    warn_items = [
        r for r in results
        if not r.get("has_vowels") or (r.get("phoneme_count") or 0) < 5
    ]
    print(f"OK           : {len(ok)}")
    print(f"Errors       : {len(err)}")
    print(f"Quality warns: {len(warn_items)}")
    if ok:
        print(f"\nWAV files in  : {out_dir.resolve()}")
        for r in ok:
            print(f"  {Path(r['wav_path']).name}  ← {r['text']!r}")
    print(f"{'=' * 64}\n")


if __name__ == "__main__":
    main()
