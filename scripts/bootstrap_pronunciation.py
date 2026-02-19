"""Offline bootstrap for pronunciation dictionary.

Usage:
    python scripts/bootstrap_pronunciation.py --db-path "J:\\Project_Vibe\\V_book\\hdle_premium.db"
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from app.services.db_service import DBService
from app.services.pronunciation_bootstrap_service import (
    NoopPronunciationGenerator,
    PhonikudPronunciationGenerator,
    PronunciationBootstrapService,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _build_generator(name: str, strict_generator: bool):
    key = (name or "").strip().lower()
    if key == "phonikud":
        return PhonikudPronunciationGenerator(strict=strict_generator)
    return NoopPronunciationGenerator()


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap local pronunciation entries")
    parser.add_argument("--db-path", required=True, help="Path to SQLite DB")
    parser.add_argument("--lang", default="he", help="Source language (default: he)")
    parser.add_argument("--chunk-size", type=int, default=500, help="Chunk size for processing")
    parser.add_argument("--generator", choices=["phonikud", "noop"], default="phonikud")
    parser.add_argument("--strict-generator", action="store_true", help="Fail if selected generator is unavailable")
    parser.add_argument("--rebuild-auto", action="store_true", help="Allow overwrite of existing auto rows")
    parser.add_argument("--skip-lemmas", action="store_true")
    parser.add_argument("--skip-terms", action="store_true")
    parser.add_argument("--skip-user-dictionary", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db_path).expanduser().resolve()
    if not db_path.exists():
        logger.error("DB path does not exist: %s", db_path)
        return 1

    DBService._instance = None
    db_service = DBService.initialize(str(db_path))
    generator = _build_generator(args.generator, args.strict_generator)
    bootstrap = PronunciationBootstrapService(generator=generator)

    try:
        with db_service.get_session() as session:
            result = bootstrap.bootstrap(
                session,
                lang=args.lang,
                chunk_size=max(1, int(args.chunk_size)),
                rebuild_auto=bool(args.rebuild_auto),
                include_lemmas=not args.skip_lemmas,
                include_terms=not args.skip_terms,
                include_user_dictionary=not args.skip_user_dictionary,
                progress_callback=lambda processed, total: logger.info(
                    "bootstrap progress: %s/%s", processed, total
                ),
            )
            session.commit()

        logger.info("Pronunciation bootstrap completed")
        logger.info("  total candidates: %s", result.total_candidates)
        logger.info("  generated candidates: %s", result.generated_candidates)
        logger.info("  updated: %s", result.updated)
        logger.info("  skipped: %s", result.skipped)
        logger.info("  failed: %s", result.failed)
        logger.info("  cancelled: %s", result.cancelled)
        return 0
    except Exception as exc:
        logger.exception("Pronunciation bootstrap failed: %s", exc)
        return 1
    finally:
        DBService.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
