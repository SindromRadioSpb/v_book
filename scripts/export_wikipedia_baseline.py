"""Export Hebrew Wikipedia baseline database for distribution.

Creates a clean copy of the database with Wikipedia corpus for new users.

Usage:
    python scripts/export_wikipedia_baseline.py [--force]

Options:
    --force    Skip confirmation prompts
"""

import sqlite3
import shutil
from pathlib import Path
from datetime import datetime
import sys

def export_wikipedia_baseline(force=False):
    """Export Wikipedia baseline database."""

    # Source database (with processed lemmas)
    source_db = Path("J:/Project_Vibe/V_book/hdle_premium.db")

    # Output directory
    output_dir = Path("M:/V_book/HDLE/releases")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Output filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d")
    output_db = output_dir / f"hebrew_wikipedia_baseline_{timestamp}.db"

    print("=" * 60)
    print("Hebrew Wikipedia Baseline Export")
    print("=" * 60)
    print()

    # Check source exists
    if not source_db.exists():
        print(f"[ERROR] Source database not found: {source_db}")
        sys.exit(1)

    size_mb = source_db.stat().st_size / (1024 * 1024)
    print(f"Source: {source_db}")
    print(f"Size: {size_mb:.1f} MB")
    print()

    # Check if lemma processing is complete
    conn = sqlite3.connect(str(source_db))
    cur = conn.cursor()

    # Check document count
    cur.execute("SELECT COUNT(*) FROM source_document")
    doc_count = cur.fetchone()[0]
    print(f"Documents: {doc_count:,}")

    # Check processed documents
    cur.execute("SELECT COUNT(*) FROM source_document WHERE status = 'processed'")
    processed_count = cur.fetchone()[0]
    print(f"Processed: {processed_count:,}")

    if processed_count < doc_count:
        print()
        print(f"[WARNING] Not all documents processed ({processed_count}/{doc_count})")
        if not force:
            print("Continue anyway? (y/n): ", end="")
            if input().lower() != 'y':
                print("Export cancelled")
                sys.exit(0)
        else:
            print("Continuing anyway (--force)")
            print()

    # Check schema version
    cur.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'")
    schema_version = cur.fetchone()[0]
    print(f"Schema version: {schema_version}")

    if schema_version != '9':
        print(f"[WARNING] Expected schema v9, got v{schema_version}")

    conn.close()

    print()
    print(f"Output: {output_db}")
    print()

    # Copy using VACUUM INTO (compacts and optimizes)
    print("[1/3] Creating optimized copy with VACUUM INTO...")
    conn = sqlite3.connect(str(source_db))
    conn.execute(f"VACUUM INTO '{output_db}'")
    conn.close()

    output_size_mb = output_db.stat().st_size / (1024 * 1024)
    print(f"[OK] Created: {output_size_mb:.1f} MB")

    # Clear sensitive data (if any)
    print()
    print("[2/3] Clearing sensitive data...")
    conn = sqlite3.connect(str(output_db))
    cur = conn.cursor()

    # Clear credentials (users will add their own)
    cur.execute("DELETE FROM credentials")
    deleted_creds = cur.rowcount
    print(f"  - Cleared {deleted_creds} credentials")

    # Clear usage tracking (fresh start)
    cur.execute("DELETE FROM mt_usage")
    deleted_usage = cur.rowcount
    print(f"  - Cleared {deleted_usage} usage records")

    # Clear security audit log (privacy)
    cur.execute("DELETE FROM security_audit_log")
    deleted_audit = cur.rowcount
    print(f"  - Cleared {deleted_audit} audit log entries")

    conn.commit()
    conn.close()

    # Vacuum again to reclaim space
    print()
    print("[3/3] Final optimization...")
    conn = sqlite3.connect(str(output_db))
    conn.execute("VACUUM")
    conn.close()

    final_size_mb = output_db.stat().st_size / (1024 * 1024)
    print(f"[OK] Final size: {final_size_mb:.1f} MB")

    # Create README
    readme_path = output_dir / f"README_{timestamp}.txt"
    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write(f"""Hebrew Wikipedia Baseline Database
===================================

Export Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Schema Version: {schema_version}

Contents:
- Documents: {doc_count:,}
- Processed: {processed_count:,}
- Source: Hebrew Wikipedia

What's Included:
- Hebrew Wikipedia articles (full text)
- Processed lemmas and tokens
- NLP analysis results
- Concordance data
- Term extraction results

What's NOT Included:
- Credentials (you need to configure your own)
- Usage tracking (starts fresh)
- Audit logs (privacy)

Installation:
1. Install HDLE Premium (if not already installed)
2. Copy this database to: M:\\V_book\\HDLE\\
3. Rename to: hdle.db
4. Launch HDLE Premium
5. Verify: Hebrew Wikipedia Baseline project appears

Notes:
- Database is optimized (VACUUMed)
- All sensitive data cleared
- Ready for distribution
- Compatible with HDLE Premium v1.0.0+

File: {output_db.name}
Size: {final_size_mb:.1f} MB
Compressed: ~{final_size_mb * 0.35:.1f} MB (estimated with 7-Zip)
""")

    print()
    print("=" * 60)
    print("[SUCCESS] Export complete!")
    print("=" * 60)
    print()
    print(f"Database: {output_db}")
    print(f"README: {readme_path}")
    print()
    print("Next steps:")
    print("1. Test database on clean installation")
    print("2. Compress with 7-Zip (.7z or .zip)")
    print("3. Upload to release page")
    print(f"   Estimated compressed size: ~{final_size_mb * 0.35:.1f} MB")
    print()

if __name__ == "__main__":
    force = "--force" in sys.argv
    export_wikipedia_baseline(force=force)
