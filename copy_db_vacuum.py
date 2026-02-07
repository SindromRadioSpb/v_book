"""Copy dev database to production using VACUUM INTO."""
import sqlite3
from pathlib import Path

source_db = Path("hdle_premium.db")
target_db = Path(r"M:\V_book\HDLE\hdle_production_new.db")

print(f"Source: {source_db}")
print(f"Target: {target_db}")

# Remove target if exists
if target_db.exists():
    print(f"Removing existing target...")
    target_db.unlink()

# Use VACUUM INTO to create a clean copy
print("Creating copy with VACUUM INTO...")
conn = sqlite3.connect(str(source_db))
conn.execute(f"VACUUM INTO '{target_db}'")
conn.close()

print(f"[OK] Database copied successfully")
print(f"[OK] Size: {target_db.stat().st_size / (1024**3):.2f} GB")
