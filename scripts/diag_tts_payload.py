"""Diagnostic tool for TTS payload and Unicode codepoints.

Usage examples:
  python scripts/diag_tts_payload.py --db-path "J:\\Project_Vibe\\V_book\\hdle_premium.db" --lang he --src-text "רכב"
  python scripts/diag_tts_payload.py --db-path "J:\\Project_Vibe\\V_book\\hdle_premium.db" --lang he --src-text "מהירות המותרת" --ssml
"""

from __future__ import annotations

import argparse
import html
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Iterable, List

from app.domain.normalization.normalizer import normalize_for_tm
from app.infra.db import DatabaseManager
from app.services.pronunciation_quality_service import PronunciationQualityService, RemovedCodepoint
from app.services.pronunciation_service import PronunciationService


def _configure_console_output() -> None:
    """Avoid Windows console crashes on non-UTF locales."""
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="backslashreplace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(errors="backslashreplace")
    except Exception:
        pass


def _codepoint_rows(text: str) -> List[dict]:
    rows: List[dict] = []
    for idx, char in enumerate(text):
        rows.append(
            {
                "index": idx,
                "char": repr(char)[1:-1],
                "hex": f"U+{ord(char):04X}",
                "name": unicodedata.name(char, "UNKNOWN"),
                "category": unicodedata.category(char),
                "combining": unicodedata.combining(char),
            }
        )
    return rows


def _print_rows(title: str, text: str) -> None:
    print(f"\n{title}: {text}")
    print(f"{title} length: {len(text)}")
    print("index\tchar\thex\tcategory\tcombining\tname")
    for row in _codepoint_rows(text):
        print(
            f"{row['index']}\t{row['char']}\t{row['hex']}\t{row['category']}\t"
            f"{row['combining']}\t{row['name']}"
        )


def _print_removed(removed: Iterable[RemovedCodepoint]) -> None:
    removed_list = list(removed)
    if not removed_list:
        print("\nremoved codepoints: none")
        return
    summary = Counter(item.reason for item in removed_list)
    print("\nremoved codepoints summary:")
    for reason, count in sorted(summary.items()):
        print(f"- {reason}: {count}")
    print("index\tchar\thex\tcategory\treason\tname")
    for item in removed_list:
        printable = repr(item.char)[1:-1]
        print(
            f"{item.index}\t{printable}\t{item.codepoint}\t{item.category}\t"
            f"{item.reason}\t{item.name}"
        )


def main() -> int:
    _configure_console_output()
    parser = argparse.ArgumentParser(
        description="Inspect exact TTS payload and Unicode codepoints."
    )
    parser.add_argument("--db-path", required=True, help="Path to SQLite DB.")
    parser.add_argument("--lang", default="he", help="Source language (default: he).")
    parser.add_argument("--src-text", help="Source text to inspect.")
    parser.add_argument(
        "--src-norm", help="Canonical source norm. If omitted, computed from src-text."
    )
    parser.add_argument(
        "--kind",
        default="surface",
        choices=["surface", "lemma", "term_cluster", "ngram"],
        help="Normalization kind when src-norm is not provided.",
    )
    parser.add_argument(
        "--provider", default="google_cloud_tts", help="Provider label for output only."
    )
    parser.add_argument(
        "--ssml", action="store_true", help="Also print final SSML payload candidate."
    )
    args = parser.parse_args()

    source_text = (args.src_text or "").strip() or (args.src_norm or "").strip()
    if not source_text:
        parser.error("Either --src-text or --src-norm must be provided.")

    source_norm = (args.src_norm or "").strip()
    if not source_norm:
        source_norm = normalize_for_tm(args.lang, source_text, args.kind).norm

    db = DatabaseManager(Path(args.db_path))
    service = PronunciationService()

    with db.get_session() as session:
        applied = service.apply_to_text(
            session=session,
            src_lang=args.lang,
            source_text=source_text,
            source_norm=source_norm,
        )

    effective_text = applied.token_text or source_text
    sanitized_text, removed = PronunciationQualityService.sanitize_tts_text_with_meta(
        effective_text
    )
    src_sanitized = PronunciationQualityService.sanitize_tts_text(source_text)
    if not sanitized_text:
        sanitized_text = src_sanitized
        print(
            "\nqc fallback: effective text became empty after sanitization; using sanitized source text"
        )

    print(f"provider: {args.provider}")
    print(f"mode: {applied.mode}")
    print(f"is_valid: {applied.is_valid}")
    print(f"qc_flag: {applied.qc_flag}")
    print(f"src_norm: {source_norm}")

    _print_rows("effective_tts_text", effective_text)
    _print_rows("sanitized_tts_text", sanitized_text)
    _print_removed(removed)

    if args.ssml:
        if applied.ssml and applied.is_valid:
            ssml_payload = applied.ssml
        else:
            ssml_payload = (
                f"<speak version='1.0'>{html.escape(sanitized_text, quote=False)}</speak>"
            )
        print(f"\nssml_payload: {ssml_payload}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
