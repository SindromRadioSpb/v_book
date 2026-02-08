#!/usr/bin/env python3
"""Prepare final release database with SHA256 and metadata."""

import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone


def calculate_sha256(file_path: Path, chunk_size: int = 8192) -> str:
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()

    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            sha256_hash.update(chunk)

    return sha256_hash.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Prepare release database")
    parser.add_argument("--db-path", type=str, required=True, help="Path to processed database")
    parser.add_argument("--version", type=str, default=datetime.now(timezone.utc).strftime("%Y%m%d"),
                       help="Version tag (default: YYYYMMDD)")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"[ERROR] Database not found: {db_path}")
        return 1

    print(f"Preparing release for: {db_path}")
    print(f"Version: {args.version}")

    # Calculate SHA256
    print("\nCalculating SHA256...")
    sha256 = calculate_sha256(db_path)
    print(f"SHA256: {sha256}")

    # Get file size
    size_bytes = db_path.stat().st_size
    size_mb = size_bytes / (1024**2)
    size_gb = size_bytes / (1024**3)
    print(f"Size: {size_bytes:,} bytes ({size_mb:.1f} MB / {size_gb:.2f} GB)")

    # Create release filename
    release_name = f"hewiki_ref_processed_v{args.version}.db"
    release_path = db_path.parent / release_name

    # Copy to release name (if different)
    if db_path != release_path:
        print(f"\nCopying to release name: {release_name}")
        import shutil
        shutil.copy2(db_path, release_path)
        print("[OK] Copied")

    # Write SHA256 file
    sha256_file = release_path.with_suffix('.db.sha256')
    with open(sha256_file, 'w') as f:
        f.write(f"{sha256}  {release_name}\n")
    print(f"[OK] SHA256 written to: {sha256_file}")

    # Write metadata JSON
    metadata = {
        "name": "hewiki_ref_baseline",
        "version": args.version,
        "filename": release_name,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "description": "Hebrew Wikipedia Baseline (387,639 documents, fully processed)",
        "compression": "none"
    }

    metadata_file = release_path.with_suffix('.db.json')
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"[OK] Metadata written to: {metadata_file}")

    # Print manifest entry
    print("\n" + "="*80)
    print("MANIFEST ENTRY (copy to app/services/reference_setup/manifest.py):")
    print("="*80)
    print(f"""
    "hewiki_ref_baseline": ManifestEntry(
        name="hewiki_ref_baseline",
        version="{args.version}",
        url="https://github.com/YOUR_ORG/YOUR_REPO/releases/download/v{args.version}/{release_name}",
        sha256="{sha256}",
        size_bytes={size_bytes},
        compression="none",
        created_at="{metadata['created_at']}",
        description="Hebrew Wikipedia Baseline (387,639 documents, fully processed)",
    )
""")
    print("="*80)

    print("\nRelease files ready:")
    print(f"  - {release_path}")
    print(f"  - {sha256_file}")
    print(f"  - {metadata_file}")
    print("\nNext steps:")
    print("  1. Upload to GitHub Release")
    print("  2. Update manifest.py with the entry above")
    print("  3. Update the URL with actual release URL")

    return 0


if __name__ == "__main__":
    exit(main())
