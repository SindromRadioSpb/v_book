r"""Initialize production database at M:\V_book\HDLE\hdle.db"""

import logging
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.infra.util.logging import setup_logging
from app.services.db_service import DBService


def main():
    """Create production database."""
    # Windows production path
    if sys.platform == "win32":
        app_dir = Path(r"M:\V_book\HDLE")
    elif sys.platform == "darwin":
        app_dir = Path.home() / "Library" / "Application Support" / "HDLE"
    else:  # Linux
        app_dir = Path.home() / ".local" / "share" / "hdle"

    app_dir.mkdir(parents=True, exist_ok=True)
    db_path = app_dir / "hdle.db"
    log_dir = app_dir / "logs"

    print(f"Initializing production database at: {db_path}")

    # Setup logging
    setup_logging(log_dir, level=logging.INFO)

    # Initialize database
    DBService.initialize(db_path)
    print("[OK] Database initialized successfully")

    # Verify schema version
    db_service = DBService.get_instance()
    with db_service.get_session() as session:
        result = session.execute("SELECT schema_version FROM schema_meta")
        version = result.scalar()
        print(f"[OK] Schema version: {version}")

    # Cleanup
    DBService.shutdown()
    print(f"\n[OK] Production database ready at: {db_path}")


if __name__ == "__main__":
    main()
