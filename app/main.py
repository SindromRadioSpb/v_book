"""HDLE Premium - Main entry point."""
import sys
import logging
import argparse
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from app.infra.util.logging import setup_logging
from app.services.db_service import DBService
from app.infra.translators.local_providers_setup import initialize_local_providers
from app.ui.app_window import AppWindow

logger = logging.getLogger(__name__)


def get_app_dir() -> Path:
    r"""Get the application data directory.

    Default locations:
    - Windows: M:\V_book\HDLE
    - macOS: ~/Library/Application Support/HDLE
    - Linux: ~/.local/share/hdle
    """
    if sys.platform == "win32":
        # Use M:\V_book\HDLE to avoid filling up C: drive
        app_dir = Path(r"M:\V_book\HDLE")
    elif sys.platform == "darwin":
        app_dir = Path.home() / "Library" / "Application Support" / "HDLE"
    else:  # Linux
        app_dir = Path.home() / ".local" / "share" / "hdle"

    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def main():
    """Main application entry point."""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="HDLE Premium - Terminology Extraction Tool")
    parser.add_argument(
        "--db-path",
        type=str,
        help="Path to database file (default: M:/V_book/HDLE/hdle.db)",
    )
    args = parser.parse_args()

    # Setup directories
    app_dir = get_app_dir()
    log_dir = app_dir / "logs"

    # Use custom database path if provided, otherwise use default
    if args.db_path:
        db_path = Path(args.db_path).resolve()
        logger.info(f"Using custom database path: {db_path}")
    else:
        # Use hdle_production_new.db (contains Hebrew Wikipedia reference corpus)
        # TODO: Rename to hdle.db after system restart
        production_db = app_dir / "hdle_production_new.db"
        if production_db.exists():
            db_path = production_db
        else:
            db_path = app_dir / "hdle.db"

    # Setup logging
    setup_logging(log_dir, level=logging.INFO)
    logger.info("=" * 60)
    logger.info("HDLE Premium starting")
    logger.info(f"App directory: {app_dir}")
    logger.info(f"Database: {db_path}")
    logger.info("=" * 60)

    try:
        # Initialize database
        DBService.initialize(db_path)
        logger.info("Database initialized")

        # Crash recovery (mark unfinished runs as failed)
        db_service = DBService.get_instance()
        recovered_count = db_service.recover_from_crash()
        if recovered_count > 0:
            logger.warning(f"Crash recovery: marked {recovered_count} runs as failed")

        # Initialize local MT providers (lazy - on first use)
        # NOTE: Providers are initialized when first needed to avoid blocking app startup
        # Model loading can take 30-60 seconds, so we defer it until actual translation request
        logger.info("Local MT providers will be initialized on first use (lazy loading)")

        # Create Qt application
        app = QApplication(sys.argv)
        app.setOrganizationName("HDLE_Premium")
        app.setApplicationName("HDLE_Premium")

        # Create and show main window
        window = AppWindow()
        window.show()

        logger.info("Application window shown")

        # Run event loop
        exit_code = app.exec()

        # Cleanup
        DBService.shutdown()
        logger.info(f"Application exiting with code {exit_code}")

        return exit_code

    except Exception as e:
        logger.exception("Fatal error")
        print(f"Fatal error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
