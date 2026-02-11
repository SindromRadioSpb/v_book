"""HDLE Premium Launcher

Handles first-time setup:
- Copies Wikipedia baseline database to user data directory
- Initializes application directories
- Launches main application

This script is the entry point for PyInstaller builds.
"""

import sys
import shutil
from pathlib import Path
import os


def get_app_data_dir():
    """Get application data directory."""
    if sys.platform == "win32":
        # Production path on M: drive (as configured in app/main.py)
        return Path(r"M:\V_book\HDLE")
    else:
        # Linux/Mac (not primary target)
        return Path.home() / ".local" / "share" / "HDLE"


def setup_first_run():
    """Setup on first run."""

    print("HDLE Premium - First Run Setup")
    print("=" * 60)

    # Get application directory
    app_data_dir = get_app_data_dir()

    # Create directories
    app_data_dir.mkdir(parents=True, exist_ok=True)
    (app_data_dir / "logs").mkdir(exist_ok=True)
    (app_data_dir / "backups").mkdir(exist_ok=True)

    print(f"Application directory: {app_data_dir}")

    # Check if database already exists
    db_path = app_data_dir / "hdle.db"

    if db_path.exists():
        size_mb = db_path.stat().st_size / (1024 * 1024)
        print(f"Existing database found: {size_mb:.1f} MB")
        print("Skipping database copy (already initialized)")
    else:
        # Copy database from installation directory
        if getattr(sys, 'frozen', False):
            # Running from PyInstaller bundle
            bundle_dir = Path(sys._MEIPASS)
            source_db = bundle_dir / "data" / "hdle_production_new.db"
        else:
            # Running from source (development)
            source_db = Path("M:/V_book/HDLE/hdle_production_new.db")

        if source_db.exists():
            print(f"Copying Wikipedia baseline database...")
            print(f"Source: {source_db}")
            print(f"Target: {db_path}")

            # Copy database
            shutil.copy2(source_db, db_path)

            size_mb = db_path.stat().st_size / (1024 * 1024)
            print(f"Database copied successfully: {size_mb:.1f} MB")
            print()
            print("Hebrew Wikipedia Baseline (387k documents) ready!")
        else:
            print(f"[WARNING] Source database not found: {source_db}")
            print("Application will start with empty database")

    print("=" * 60)
    print()


def main():
    """Main entry point."""

    # Setup on first run
    setup_first_run()

    # Import and run main application
    # Import here to avoid issues before setup
    from app.main import main as app_main

    # Run application
    sys.exit(app_main())


if __name__ == "__main__":
    main()
