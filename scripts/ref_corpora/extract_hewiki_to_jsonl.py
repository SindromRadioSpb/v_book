#!/usr/bin/env python3
"""
Extract Hebrew Wikipedia dump to sharded JSONL files with manifest.

Robust extraction pipeline:
- CLI arguments for all paths and options
- BZ2 signature detection (handles misnamed files)
- JSONL sharding with configurable limits
- SHA256 verification for each shard
- Extraction run manifest with full metadata
- UTF-8 encoding safety
- Progress reporting

Usage:
    python scripts/ref_corpora/extract_hewiki_to_jsonl.py \\
        --dump "J:\\...\\hewiki-20260201-pages-articles.xml.bz2" \\
        --out_dir "J:\\...\\ref_corpora\\hewiki\\jsonl" \\
        --limit_docs 200 \\
        --overwrite
"""

import argparse
import bz2
import hashlib
import importlib.util
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

# Default paths (relative to repo root)
DEFAULT_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_WX_PATH = DEFAULT_REPO_ROOT / "tools" / "Wikiextractor-V2"
DEFAULT_OUT_DIR = DEFAULT_REPO_ROOT / "ref_corpora" / "hewiki" / "jsonl"
DEFAULT_MANIFEST_DIR = DEFAULT_REPO_ROOT / "ref_corpora" / "hewiki" / "manifests"
DEFAULT_TEMPLATES_CACHE = DEFAULT_REPO_ROOT / "ref_corpora" / "hewiki" / "raw" / "templates-he.pkl"

# Sharding defaults
DEFAULT_SHARD_MAX_LINES = 200_000
DEFAULT_SHARD_MAX_BYTES = 512 * 1024 * 1024  # 512 MB


class WikiExtractorNotFoundError(Exception):
    """Wikiextractor-V2 module not found or not importable."""


class ShardWriter:
    """Manages JSONL shard files with automatic rotation."""

    def __init__(
        self,
        out_dir: Path,
        prefix: str,
        max_lines: int = DEFAULT_SHARD_MAX_LINES,
        max_bytes: int = DEFAULT_SHARD_MAX_BYTES,
    ):
        self.out_dir = out_dir
        self.prefix = prefix
        self.max_lines = max_lines
        self.max_bytes = max_bytes

        self.current_shard = 0
        self.current_lines = 0
        self.current_bytes = 0
        self.current_file = None
        self.current_path = None

        self.shards: List[Dict[str, Any]] = []
        self.total_docs = 0
        self.total_bytes = 0

        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _open_next_shard(self) -> None:
        """Open next shard file for writing."""
        if self.current_file:
            self._close_current_shard()

        shard_name = f"{self.prefix}_{self.current_shard:05d}.jsonl"
        self.current_path = self.out_dir / shard_name
        # Use binary mode with UTF-8 to preserve exact line endings (LF not CRLF)
        self.current_file = open(self.current_path, "wb")
        self.current_lines = 0
        self.current_bytes = 0

        logging.info(f"Opened shard: {shard_name}")

    def _close_current_shard(self) -> None:
        """Close current shard and compute SHA256."""
        if not self.current_file or not self.current_path:
            return

        self.current_file.close()
        self.current_file = None  # Reset to allow next shard to open

        # Compute SHA256
        sha256 = hashlib.sha256()
        with open(self.current_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)

        file_size = self.current_path.stat().st_size

        self.shards.append({
            "filename": self.current_path.name,
            "lines": self.current_lines,
            "bytes": file_size,
            "sha256": sha256.hexdigest(),
        })

        logging.info(
            f"Closed shard: {self.current_path.name} "
            f"({self.current_lines} lines, {file_size:,} bytes)"
        )

        self.current_shard += 1

    def write(self, line: str) -> None:
        """Write a JSONL line, rotating shard if needed."""
        line_bytes = line.encode("utf-8")
        line_size = len(line_bytes)

        # Check if we need to rotate
        if self.current_file and (
            self.current_lines >= self.max_lines or
            self.current_bytes + line_size > self.max_bytes
        ):
            self._close_current_shard()

        # Open first shard or next shard after rotation
        if not self.current_file:
            self._open_next_shard()

        # Write bytes (file opened in binary mode to preserve exact LF line endings)
        self.current_file.write(line_bytes)
        self.current_lines += 1
        self.current_bytes += line_size
        self.total_docs += 1
        self.total_bytes += line_size

    def close(self) -> Dict[str, Any]:
        """Close all shards and return summary."""
        if self.current_file:
            self._close_current_shard()

        return {
            "shards": self.shards,
            "total_docs": self.total_docs,
            "total_bytes": self.total_bytes,
            "num_shards": len(self.shards),
        }


def detect_bz2_signature(file_path: Path) -> bool:
    """
    Detect if file is actually BZ2 compressed by checking magic bytes.

    BZ2 files start with: b'BZh' (0x42 0x5A 0x68)
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(3)
            return header == b"BZh"
    except Exception as e:
        logging.warning(f"Failed to read file header: {e}")
        return False


def load_wikiextractor_module(wx_path: Path) -> Tuple[Any, str]:
    """
    Load Wikiextractor-V2 module robustly.

    Returns:
        (main_function, module_path)

    Raises:
        WikiExtractorNotFoundError: If module cannot be loaded
    """
    if not wx_path.exists():
        raise WikiExtractorNotFoundError(
            f"Wikiextractor-V2 path does not exist: {wx_path}"
        )

    # Add to sys.path
    if str(wx_path) not in sys.path:
        sys.path.insert(0, str(wx_path))

    # Try package import first
    try:
        mod = importlib.import_module("wikiextractor.WikiExtractor")
        main_fn = getattr(mod, "main", None)
        if callable(main_fn):
            module_file = getattr(mod, "__file__", "wikiextractor.WikiExtractor")
            logging.info(f"Loaded WikiExtractor via package import: {module_file}")
            return main_fn, module_file
    except Exception as e:
        logging.debug(f"Package import failed: {e}")

    # Fallback: direct file load
    candidates = [
        wx_path / "wikiextractor" / "WikiExtractor.py",
        wx_path / "WikiExtractor.py",
    ]

    for candidate in candidates:
        if candidate.is_file():
            try:
                spec = importlib.util.spec_from_file_location(
                    "wikiextractor_WikiExtractor", str(candidate)
                )
                if not spec or not spec.loader:
                    continue

                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)

                main_fn = getattr(mod, "main", None)
                if callable(main_fn):
                    logging.info(f"Loaded WikiExtractor via file import: {candidate}")
                    return main_fn, str(candidate)
            except Exception as e:
                logging.debug(f"Failed to load {candidate}: {e}")

    raise WikiExtractorNotFoundError(
        f"Cannot load WikiExtractor main() from {wx_path}. "
        f"Checked: {', '.join(str(c) for c in candidates)}"
    )


def get_git_commit(repo_path: Path) -> Optional[str]:
    """Get current git commit hash from repository."""
    git_head = repo_path / ".git" / "HEAD"
    if not git_head.exists():
        return None

    try:
        with open(git_head, "r") as f:
            head_content = f.read().strip()

        if head_content.startswith("ref: "):
            ref_path = head_content[5:]
            ref_file = repo_path / ".git" / ref_path
            if ref_file.exists():
                with open(ref_file, "r") as f:
                    return f.read().strip()

        # Detached HEAD
        if len(head_content) == 40:
            return head_content

        return None
    except Exception as e:
        logging.debug(f"Failed to get git commit: {e}")
        return None


def compute_file_sha256(file_path: Path) -> str:
    """Compute SHA256 hash of file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def extract_to_jsonl(
    dump_path: Path,
    out_dir: Path,
    wx_main: Any,
    wx_path: str,
    templates_cache: Optional[Path] = None,
    namespaces: str = "0",
    limit_docs: int = 0,
    shard_max_lines: int = DEFAULT_SHARD_MAX_LINES,
    shard_max_bytes: int = DEFAULT_SHARD_MAX_BYTES,
    discard_sections: bool = True,
    discard_templates: bool = True,
    ignore_templates: bool = True,
) -> Dict[str, Any]:
    """
    Extract Wikipedia dump to sharded JSONL files.

    Returns:
        Extraction metadata dictionary
    """
    # Prepare WikiExtractor arguments
    wx_args = [
        str(dump_path),
        "--generator",
        "--json",
        "-ns", namespaces,
    ]

    if discard_sections:
        wx_args.append("--discard_sections")
    if discard_templates:
        wx_args.append("--discard_templates")
    if ignore_templates:
        wx_args.append("--ignore_templates")

    wx_kwargs = {}
    if templates_cache and templates_cache.exists():
        wx_kwargs["--templates"] = str(templates_cache)
        logging.info(f"Using templates cache: {templates_cache}")

    # Determine shard prefix from dump filename
    dump_name = dump_path.stem
    if dump_name.endswith(".xml"):
        dump_name = dump_name[:-4]
    shard_prefix = f"{dump_name}_articles"

    # Initialize shard writer
    writer = ShardWriter(
        out_dir=out_dir,
        prefix=shard_prefix,
        max_lines=shard_max_lines,
        max_bytes=shard_max_bytes,
    )

    # Extract
    started_at = datetime.now(timezone.utc)
    extracted_at_iso = started_at.isoformat(timespec="seconds").replace("+00:00", "Z")

    logging.info("Starting extraction...")
    logging.info(f"Dump: {dump_path}")
    logging.info(f"Output: {out_dir}")
    logging.info(f"Limit: {limit_docs if limit_docs > 0 else 'unlimited'}")

    try:
        for item in wx_main(*wx_args, **wx_kwargs):
            # Parse WikiExtractor output (dict or tuple)
            if isinstance(item, dict):
                doc_id = item.get("doc_id") or item.get("id") or ""
                title = item.get("title") or ""
                url = item.get("url") or ""
                language = item.get("language") or ""
                text = item.get("text") or ""
            else:
                doc_id, title, url, language, text = item

            # Normalize
            doc_id = str(doc_id) if doc_id else ""
            title = str(title) if title else ""
            if not doc_id:
                doc_id = title

            # Create JSONL record
            record = {
                "doc_id": doc_id,
                "title": title,
                "url": str(url),
                "language": str(language),
                "text": str(text),
                "source": "hewiki",
                "dump": dump_path.name,
                "extracted_at": extracted_at_iso,
            }

            writer.write(json.dumps(record, ensure_ascii=False) + "\n")

            # Progress
            if writer.total_docs % 10000 == 0:
                logging.info(f"Extracted {writer.total_docs:,} documents...")

            # Check limit
            if limit_docs > 0 and writer.total_docs >= limit_docs:
                logging.info(f"Reached limit of {limit_docs} documents, stopping.")
                break

    finally:
        summary = writer.close()

    ended_at = datetime.now(timezone.utc)
    duration_ms = int((ended_at - started_at).total_seconds() * 1000)

    logging.info(f"Extraction complete: {summary['total_docs']:,} documents in {summary['num_shards']} shards")

    # Build metadata
    metadata = {
        "started_at": started_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "ended_at": ended_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "duration_ms": duration_ms,
        "dump_file": dump_path.name,
        "dump_path": str(dump_path),
        "wikiextractor_path": wx_path,
        "wikiextractor_commit": get_git_commit(Path(wx_path).parent.parent) if ".git" in str(wx_path) else None,
        "args": {
            "namespaces": namespaces,
            "limit_docs": limit_docs,
            "shard_max_lines": shard_max_lines,
            "shard_max_bytes": shard_max_bytes,
            "discard_sections": discard_sections,
            "discard_templates": discard_templates,
            "ignore_templates": ignore_templates,
            "templates_cache": str(templates_cache) if templates_cache else None,
        },
        "output": {
            "directory": str(out_dir),
            "shards": summary["shards"],
            "total_docs": summary["total_docs"],
            "total_bytes": summary["total_bytes"],
            "num_shards": summary["num_shards"],
        }
    }

    return metadata


def save_manifest(metadata: Dict[str, Any], manifest_dir: Path) -> Path:
    """Save extraction run manifest."""
    manifest_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest_name = f"extract_run_{timestamp}.json"
    manifest_path = manifest_dir / manifest_name

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    logging.info(f"Manifest saved: {manifest_path}")
    return manifest_path


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Extract Hebrew Wikipedia dump to sharded JSONL files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--dump",
        type=Path,
        required=True,
        help="Path to Wikipedia dump file (e.g., hewiki-20260201-pages-articles.xml.bz2)",
    )
    parser.add_argument(
        "--out_dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Output directory for JSONL shards (default: {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--manifest_dir",
        type=Path,
        default=DEFAULT_MANIFEST_DIR,
        help=f"Directory for extraction manifests (default: {DEFAULT_MANIFEST_DIR})",
    )
    parser.add_argument(
        "--wx_path",
        type=Path,
        default=DEFAULT_WX_PATH,
        help=f"Path to Wikiextractor-V2 (default: {DEFAULT_WX_PATH})",
    )
    parser.add_argument(
        "--templates_cache",
        type=Path,
        default=DEFAULT_TEMPLATES_CACHE,
        help=f"Templates cache file (default: {DEFAULT_TEMPLATES_CACHE})",
    )
    parser.add_argument(
        "--namespaces",
        default="0",
        help="Wikipedia namespaces to extract (default: 0 = articles only)",
    )
    parser.add_argument(
        "--limit_docs",
        type=int,
        default=0,
        help="Limit number of documents (0 = no limit)",
    )
    parser.add_argument(
        "--shard_max_lines",
        type=int,
        default=DEFAULT_SHARD_MAX_LINES,
        help=f"Max lines per shard (default: {DEFAULT_SHARD_MAX_LINES:,})",
    )
    parser.add_argument(
        "--shard_max_bytes",
        type=int,
        default=DEFAULT_SHARD_MAX_BYTES,
        help=f"Max bytes per shard (default: {DEFAULT_SHARD_MAX_BYTES:,})",
    )
    parser.add_argument(
        "--no_discard_sections",
        action="store_true",
        help="Do NOT discard Wikipedia sections (keep all)",
    )
    parser.add_argument(
        "--no_discard_templates",
        action="store_true",
        help="Do NOT discard templates",
    )
    parser.add_argument(
        "--no_ignore_templates",
        action="store_true",
        help="Do NOT ignore templates during extraction",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output directory",
    )
    parser.add_argument(
        "--log_level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="[%(asctime)s][%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Validate dump file
    if not args.dump.exists():
        logging.error(f"Dump file not found: {args.dump}")
        return 1

    # Check if BZ2 (by signature, not extension)
    is_bz2 = detect_bz2_signature(args.dump)
    logging.info(f"BZ2 signature detected: {is_bz2}")

    # Check output directory
    if args.out_dir.exists() and not args.overwrite:
        logging.error(
            f"Output directory already exists: {args.out_dir}\n"
            "Use --overwrite to overwrite"
        )
        return 1

    # Load WikiExtractor
    try:
        wx_main, wx_path = load_wikiextractor_module(args.wx_path)
    except WikiExtractorNotFoundError as e:
        logging.error(str(e))
        return 1

    # Extract
    try:
        metadata = extract_to_jsonl(
            dump_path=args.dump,
            out_dir=args.out_dir,
            wx_main=wx_main,
            wx_path=wx_path,
            templates_cache=args.templates_cache if args.templates_cache.exists() else None,
            namespaces=args.namespaces,
            limit_docs=args.limit_docs,
            shard_max_lines=args.shard_max_lines,
            shard_max_bytes=args.shard_max_bytes,
            discard_sections=not args.no_discard_sections,
            discard_templates=not args.no_discard_templates,
            ignore_templates=not args.no_ignore_templates,
        )
    except Exception as e:
        logging.error(f"Extraction failed: {e}", exc_info=True)
        return 1

    # Save manifest
    try:
        manifest_path = save_manifest(metadata, args.manifest_dir)
        logging.info(f"✓ Extraction complete")
        logging.info(f"✓ Total documents: {metadata['output']['total_docs']:,}")
        logging.info(f"✓ Total shards: {metadata['output']['num_shards']}")
        logging.info(f"✓ Manifest: {manifest_path}")
    except Exception as e:
        logging.error(f"Failed to save manifest: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
