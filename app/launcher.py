"""HDLE Premium Launcher

Handles first-time setup:
- Initializes application directories
- Launches main application

This script is the entry point for PyInstaller builds.
"""

import sys

from app.infra.db_path_resolver import get_default_db_path
from app.infra.resource_paths import ResourcePaths


def get_app_data_dir():
    """Get application data directory."""
    return ResourcePaths.resolve_data_root(create=True)


def setup_first_run():
    """Setup on first run."""

    print("HDLE Premium - First Run Setup")
    print("=" * 60)

    # Get application directory
    app_paths = ResourcePaths.build(create=True)
    app_data_dir = app_paths.data_root

    print(f"Application directory: {app_data_dir}")

    # Check if default DB already exists
    db_path = get_default_db_path()

    if db_path.exists():
        size_mb = db_path.stat().st_size / (1024 * 1024)
        print(f"Existing default database found: {size_mb:.1f} MB")
        print("Default database profile is ready")
    else:
        print("Default database is not present yet.")
        print("A clean default DB will be created on first application startup.")
        print("You can switch to an existing/baseline DB from Setup Wizard or Tools menu.")

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
