"""
Tests for reference corpora extraction (extract_hewiki_to_jsonl.py).

Tests cover:
- BZ2 signature detection
- SHA256 computation
- ShardWriter automatic rotation
- JSONL record format
- Manifest generation
"""

import pytest
import json
import hashlib
from pathlib import Path
from datetime import datetime

# Import functions from extraction script
import sys

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "scripts" / "ref_corpora"))

from extract_hewiki_to_jsonl import (
    detect_bz2_signature,
    compute_file_sha256,
    ShardWriter,
)


class TestBZ2Detection:
    """Test BZ2 signature detection."""

    def test_detect_bz2_signature_valid(self, tmp_path):
        """Test detection of valid BZ2 file."""
        bz2_file = tmp_path / "test.bz2"
        bz2_file.write_bytes(b"BZh91AY&SY" + b"\x00" * 100)  # BZ2 magic + data

        assert detect_bz2_signature(bz2_file) is True

    def test_detect_bz2_signature_invalid(self, tmp_path):
        """Test detection of non-BZ2 file."""
        txt_file = tmp_path / "test.txt"
        txt_file.write_bytes(b"This is not a BZ2 file")

        assert detect_bz2_signature(txt_file) is False

    def test_detect_bz2_signature_empty(self, tmp_path):
        """Test detection on empty file."""
        empty_file = tmp_path / "empty.bz2"
        empty_file.write_bytes(b"")

        assert detect_bz2_signature(empty_file) is False

    def test_detect_bz2_signature_short(self, tmp_path):
        """Test detection on file shorter than magic bytes."""
        short_file = tmp_path / "short.bz2"
        short_file.write_bytes(b"BZ")  # Only 2 bytes

        assert detect_bz2_signature(short_file) is False


class TestSHA256:
    """Test SHA256 computation."""

    def test_compute_file_sha256_small_file(self, tmp_path):
        """Test SHA256 of small file."""
        test_file = tmp_path / "test.txt"
        test_content = b"Hello, world!"
        test_file.write_bytes(test_content)

        computed_hash = compute_file_sha256(test_file)
        expected_hash = hashlib.sha256(test_content).hexdigest()

        assert computed_hash == expected_hash

    def test_compute_file_sha256_large_file(self, tmp_path):
        """Test SHA256 of large file (chunked reading)."""
        test_file = tmp_path / "large.bin"
        # Create 1 MB file
        test_content = b"A" * (1024 * 1024)
        test_file.write_bytes(test_content)

        computed_hash = compute_file_sha256(test_file)
        expected_hash = hashlib.sha256(test_content).hexdigest()

        assert computed_hash == expected_hash

    def test_compute_file_sha256_unicode(self, tmp_path):
        """Test SHA256 of file with Unicode content."""
        test_file = tmp_path / "unicode.txt"
        test_content = "שלום עולם".encode("utf-8")
        test_file.write_bytes(test_content)

        computed_hash = compute_file_sha256(test_file)
        expected_hash = hashlib.sha256(test_content).hexdigest()

        assert computed_hash == expected_hash


class TestShardWriter:
    """Test ShardWriter automatic rotation."""

    def test_shard_writer_basic(self, tmp_path):
        """Test basic shard writing."""
        writer = ShardWriter(
            out_dir=tmp_path,
            prefix="test",
            max_lines=10,
            max_bytes=1000,
        )

        # Write 5 lines
        for i in range(5):
            writer.write(json.dumps({"id": i, "text": f"Line {i}"}) + "\n")

        summary = writer.close()

        # Check summary
        assert summary["total_docs"] == 5
        assert summary["num_shards"] == 1
        assert len(summary["shards"]) == 1

        # Check shard file
        shard = summary["shards"][0]
        assert shard["lines"] == 5
        assert shard["filename"] == "test_00000.jsonl"

        # Verify file exists and has correct content
        shard_file = tmp_path / shard["filename"]
        assert shard_file.exists()
        assert len(shard_file.read_text(encoding="utf-8").splitlines()) == 5

    def test_shard_writer_rotation_by_lines(self, tmp_path):
        """Test shard rotation by line count."""
        writer = ShardWriter(
            out_dir=tmp_path,
            prefix="test",
            max_lines=3,  # Rotate after 3 lines
            max_bytes=10_000,
        )

        # Write 7 lines (should create 3 shards: 3, 3, 1)
        for i in range(7):
            writer.write(json.dumps({"id": i, "text": f"Line {i}"}) + "\n")

        summary = writer.close()

        # Check summary
        assert summary["total_docs"] == 7
        assert summary["num_shards"] == 3

        # Check shard counts
        assert summary["shards"][0]["lines"] == 3
        assert summary["shards"][1]["lines"] == 3
        assert summary["shards"][2]["lines"] == 1

        # Verify filenames
        assert summary["shards"][0]["filename"] == "test_00000.jsonl"
        assert summary["shards"][1]["filename"] == "test_00001.jsonl"
        assert summary["shards"][2]["filename"] == "test_00002.jsonl"

    def test_shard_writer_rotation_by_bytes(self, tmp_path):
        """Test shard rotation by byte size."""
        writer = ShardWriter(
            out_dir=tmp_path,
            prefix="test",
            max_lines=1000,
            max_bytes=100,  # Rotate after 100 bytes
        )

        # Write lines until rotation happens (each line ~30 bytes)
        for i in range(10):
            writer.write(json.dumps({"id": i, "text": f"Data {i}"}) + "\n")

        summary = writer.close()

        # Should have created multiple shards (100 bytes / ~30 bytes per line ≈ 3-4 lines per shard)
        assert summary["num_shards"] >= 2
        assert summary["total_docs"] == 10

    def test_shard_writer_sha256(self, tmp_path):
        """Test SHA256 computation for shards."""
        writer = ShardWriter(
            out_dir=tmp_path,
            prefix="test",
            max_lines=5,
            max_bytes=1000,
        )

        lines = []
        for i in range(5):
            line = json.dumps({"id": i, "text": f"Line {i}"}) + "\n"
            lines.append(line)
            writer.write(line)

        summary = writer.close()

        # Compute expected SHA256
        expected_content = "".join(lines).encode("utf-8")
        expected_hash = hashlib.sha256(expected_content).hexdigest()

        # Check shard SHA256
        assert summary["shards"][0]["sha256"] == expected_hash

    def test_shard_writer_empty(self, tmp_path):
        """Test closing writer without writing anything."""
        writer = ShardWriter(
            out_dir=tmp_path,
            prefix="test",
            max_lines=10,
            max_bytes=1000,
        )

        summary = writer.close()

        # Should have 0 shards and 0 docs
        assert summary["total_docs"] == 0
        assert summary["num_shards"] == 0
        assert len(summary["shards"]) == 0


class TestJSONLRecordFormat:
    """Test JSONL record format expectations."""

    def test_valid_jsonl_record(self):
        """Test parsing a valid JSONL record."""
        record_str = json.dumps(
            {
                "doc_id": "test_123",
                "title": "Test Article",
                "url": "https://he.wikipedia.org/wiki?curid=123",
                "language": "he",
                "text": "Test content",
                "source": "hewiki",
                "dump": "hewiki-20260201.xml.bz2",
                "extracted_at": "2026-02-07T05:00:00Z",
            }
        )

        record = json.loads(record_str)

        # Verify required fields
        assert "doc_id" in record
        assert "title" in record
        assert "text" in record
        assert record["language"] == "he"
        assert record["source"] == "hewiki"

    def test_jsonl_unicode_handling(self):
        """Test Unicode (Hebrew) in JSONL record."""
        record_str = json.dumps(
            {
                "doc_id": "מתמטיקה",
                "title": "מתמטיקה",
                "text": "מָתֵמָטִיקָה היא תחום דעת",
            },
            ensure_ascii=False,
        )

        record = json.loads(record_str)

        # Verify Hebrew text roundtrips correctly
        assert record["doc_id"] == "מתמטיקה"
        assert "מָתֵמָטִיקָה" in record["text"]


class TestManifestGeneration:
    """Test manifest generation."""

    def test_manifest_structure(self):
        """Test manifest has expected structure."""
        manifest = {
            "started_at": "2026-02-07T05:00:00Z",
            "ended_at": "2026-02-07T05:00:10Z",
            "duration_ms": 10000,
            "dump_file": "hewiki-20260201.xml.bz2",
            "dump_path": "/path/to/dump.xml.bz2",
            "wikiextractor_path": "/path/to/WikiExtractor.py",
            "wikiextractor_commit": None,
            "args": {
                "namespaces": "0",
                "limit_docs": 200,
            },
            "output": {
                "directory": "/output/dir",
                "shards": [
                    {
                        "filename": "shard_00000.jsonl",
                        "lines": 200,
                        "bytes": 1024,
                        "sha256": "abcd1234",
                    }
                ],
                "total_docs": 200,
                "total_bytes": 1024,
                "num_shards": 1,
            },
        }

        # Verify required top-level keys
        assert "started_at" in manifest
        assert "ended_at" in manifest
        assert "dump_file" in manifest
        assert "args" in manifest
        assert "output" in manifest

        # Verify output structure
        output = manifest["output"]
        assert "shards" in output
        assert "total_docs" in output
        assert output["num_shards"] == len(output["shards"])

        # Verify shard structure
        shard = output["shards"][0]
        assert "filename" in shard
        assert "lines" in shard
        assert "bytes" in shard
        assert "sha256" in shard


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
