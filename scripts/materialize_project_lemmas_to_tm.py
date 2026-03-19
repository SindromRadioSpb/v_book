"""Materialize missing lemma rows into tm_entry for one project.

Usage:
  python scripts/materialize_project_lemmas_to_tm.py --db-path "X:\\path\\db.db" --project-id 1
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services.translation_admin_service import TranslationAdminService


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize missing lemma->tm_entry anchors for a project.",
    )
    parser.add_argument("--db-path", required=True, help="SQLite DB path")
    parser.add_argument("--project-id", type=int, required=True, help="dict_project.project_id")
    parser.add_argument(
        "--chunk-size", type=int, default=10000, help="Rows per commit chunk (default: 10000)"
    )
    parser.add_argument(
        "--source-ref",
        default="lemma_materialize_full",
        help="source_ref for created tm_entry rows",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print stats only; do not write")
    parser.add_argument(
        "--progress-every-chunks",
        type=int,
        default=5,
        help="Print progress every N chunks (default: 5)",
    )
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    db_path = Path(args.db_path).expanduser()
    if not db_path.exists():
        print(f"[FAIL] DB not found: {db_path}")
        return 2
    if args.chunk_size <= 0:
        print("[FAIL] chunk-size must be > 0")
        return 2

    engine = create_engine(f"sqlite:///{db_path}")
    service = TranslationAdminService()

    try:
        with Session(engine) as session:
            session.execute(text("PRAGMA busy_timeout = 60000"))

            def _on_progress(info: dict) -> None:
                every = max(1, int(args.progress_every_chunks))
                chunk_no = int(info.get("processed_chunks", 0))
                if chunk_no % every != 0:
                    return
                attempted = int(info.get("attempted", 0))
                total_missing = int(info.get("initial_missing_lemma_links", 0))
                pct = (attempted * 100.0 / total_missing) if total_missing > 0 else 100.0
                print(
                    f"[progress] chunks={chunk_no} attempted={attempted:,}/{total_missing:,} "
                    f"({pct:.2f}%) last_lemma_id={int(info.get('last_lemma_id', 0))}"
                )

            stats = service.materialize_project_lemmas_to_tm(
                session,
                project_id=int(args.project_id),
                chunk_size=int(args.chunk_size),
                source_ref=str(args.source_ref),
                dry_run=bool(args.dry_run),
                progress_cb=_on_progress,
            )

            print(
                "[OK] materialize stats | "
                f"project_id={stats['project_id']} "
                f"lemmas={stats['total_lemmas']:,} "
                f"tm_before={stats['initial_tm_lemmas']:,} "
                f"missing_before={stats['initial_missing_lemma_links']:,} "
                f"attempted={stats['attempted']:,} "
                f"inserted={stats['inserted']:,} "
                f"tm_after={stats['final_tm_lemmas']:,} "
                f"missing_after={stats['final_missing_lemma_links']:,} "
                f"chunks={stats['processed_chunks']:,}"
            )
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        msg = msg.encode("ascii", "backslashreplace").decode("ascii")
        print(f"[FAIL] materialization failed: {msg}")
        return 1
    finally:
        engine.dispose()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
