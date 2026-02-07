"""HDLE Premium - Main entry point."""
import sys
import logging
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from app.infra.util.logging import setup_logging
from app.services.db_service import DBService
from app.ui.app_window import AppWindow

logger = logging.getLogger(__name__)


def get_app_dir() -> Path:
    """Get the application data directory."""
    if sys.platform == "win32":
        app_dir = Path.home() / "AppData" / "Local" / "HDLE"
    elif sys.platform == "darwin":
        app_dir = Path.home() / "Library" / "Application Support" / "HDLE"
    else:  # Linux
        app_dir = Path.home() / ".local" / "share" / "hdle"

    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def main():
    """Main application entry point."""
    # Setup directories
    app_dir = get_app_dir()
    log_dir = app_dir / "logs"
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
