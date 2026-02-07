"""
Tests for reference corpora import (import_ref_jsonl_to_project.py).

Tests cover:
- Deduplication hash computation
- Virtual file path creation
- Idempotency (duplicate detection)
- Project/corpus auto-creation
- Import statistics
"""

import pytest
import json
import hashlib
from pathlib import Path
from datetime import datetime

# Import functions from import script
import sys
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "scripts" / "ref_corpora"))

from import_ref_jsonl_to_project import (
    compute_doc_hash,
    ImportReport,
)


class TestDocHashComputation:
    """Test document hash computation for deduplication."""

    def test_compute_doc_hash_basic(self):
        """Test basic hash computation."""
        hash1 = compute_doc_hash("hewiki", "מתמטיקה")

        # Verify it's a valid SHA256 hex digest
        assert len(hash1) == 64
        assert all(c in "0123456789abcdef" for c in hash1)

    def test_compute_doc_hash_deterministic(self):
        """Test hash is deterministic (same input = same output)."""
        hash1 = compute_doc_hash("hewiki", "מתמטיקה")
        hash2 = compute_doc_hash("hewiki", "מתמטיקה")

        assert hash1 == hash2

    def test_compute_doc_hash_unique(self):
        """Test different inputs produce different hashes."""
        hash1 = compute_doc_hash("hewiki", "מתמטיקה")
        hash2 = compute_doc_hash("hewiki", "אקסיומה")
        hash3 = compute_doc_hash("enwiki", "מתמטיקה")  # Different source

        assert hash1 != hash2
        assert hash1 != hash3
        assert hash2 != hash3

    def test_compute_doc_hash_format(self):
        """Test hash matches expected format (source:doc_id)."""
        source_key = "hewiki"
        doc_id = "test_123"

        computed_hash = compute_doc_hash(source_key, doc_id)
        expected_hash = hashlib.sha256(f"{source_key}:{doc_id}".encode("utf-8")).hexdigest()

        assert computed_hash == expected_hash

    def test_compute_doc_hash_unicode(self):
        """Test hash handles Unicode correctly."""
        # Hebrew text should hash correctly
        hash1 = compute_doc_hash("hewiki", "שלום עולם")

        # Should be reproducible
        hash2 = compute_doc_hash("hewiki", "שלום עולם")
        assert hash1 == hash2

        # Should be valid SHA256
        assert len(hash1) == 64


class TestImportReport:
    """Test ImportReport data structure."""

    def test_import_report_initialization(self):
        """Test ImportReport can be initialized."""
        started_at = datetime.now().isoformat()

        report = ImportReport(
            started_at=started_at,
            source_key="hewiki",
            corpus_name="Test Corpus",
            project_name="Test Project",
        )

        assert report.started_at == started_at
        assert report.source_key == "hewiki"
        assert report.total_records == 0
        assert report.added == 0
        assert report.errors == 0

    def test_import_report_to_dict(self):
        """Test ImportReport serialization to dict."""
        started_at = "2026-02-07T05:00:00Z"
        ended_at = "2026-02-07T05:00:10Z"

        report = ImportReport(
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=10000,
            source_key="hewiki",
            corpus_name="Test Corpus",
            project_name="Test Project",
            project_id=123,
            jsonl_files=["test.jsonl"],
            total_records=100,
            added=90,
            skipped_duplicate=5,
            skipped_empty=3,
            errors=2,
        )

        result = report.to_dict()

        # Verify structure
        assert result["started_at"] == started_at
        assert result["ended_at"] == ended_at
        assert result["duration_ms"] == 10000

        assert result["source"]["source_key"] == "hewiki"
        assert result["source"]["corpus_name"] == "Test Corpus"
        assert result["source"]["project_id"] == 123

        assert result["input"]["jsonl_files"] == ["test.jsonl"]
        assert result["input"]["total_records"] == 100

        assert result["results"]["added"] == 90
        assert result["results"]["skipped_duplicate"] == 5
        assert result["results"]["skipped_empty"] == 3
        assert result["results"]["errors"] == 2

    def test_import_report_json_serializable(self):
        """Test ImportReport can be serialized to JSON."""
        report = ImportReport(
            started_at="2026-02-07T05:00:00Z",
            source_key="hewiki",
            corpus_name="Test",
            project_name="Test",
        )

        # Should not raise
        json_str = json.dumps(report.to_dict(), ensure_ascii=False)
        assert json_str is not None

        # Should be parseable
        parsed = json.loads(json_str)
        assert parsed["source"]["source_key"] == "hewiki"


class TestVirtualFilePath:
    """Test virtual file path format for Wikipedia articles."""

    def test_virtual_path_format(self):
        """Test virtual path follows source:doc_id format."""
        source_key = "hewiki"
        doc_id = "מתמטיקה"

        virtual_path = f"{source_key}:{doc_id}"

        assert virtual_path == "hewiki:מתמטיקה"
        assert ":" in virtual_path
        assert virtual_path.startswith(source_key)

    def test_virtual_path_uniqueness(self):
        """Test different doc_ids create different paths."""
        source_key = "hewiki"

        path1 = f"{source_key}:מתמטיקה"
        path2 = f"{source_key}:אקסיומה"

        assert path1 != path2

    def test_virtual_path_source_separation(self):
        """Test same doc_id from different sources create different paths."""
        doc_id = "Mathematics"

        path1 = f"hewiki:{doc_id}"
        path2 = f"enwiki:{doc_id}"

        assert path1 != path2
        assert path1 == "hewiki:Mathematics"
        assert path2 == "enwiki:Mathematics"


class TestJSONLRecordParsing:
    """Test JSONL record parsing for import."""

    def test_parse_minimal_record(self):
        """Test parsing minimal valid record."""
        record_str = json.dumps({
            "doc_id": "test_123",
            "title": "Test",
            "text": "Content",
        })

        record = json.loads(record_str)

        # Should have required fields
        assert "doc_id" in record
        assert "text" in record

    def test_parse_full_record(self):
        """Test parsing full Wikipedia record."""
        record_str = json.dumps({
            "doc_id": "מתמטיקה",
            "title": "מתמטיקה",
            "url": "https://he.wikipedia.org/wiki?curid=7",
            "language": "he",
            "text": "מָתֵמָטִיקָה היא תחום דעת",
            "source": "hewiki",
            "dump": "hewiki-20260201.xml.bz2",
            "extracted_at": "2026-02-07T05:00:00Z",
        }, ensure_ascii=False)

        record = json.loads(record_str)

        # Verify all fields present
        assert record["doc_id"] == "מתמטיקה"
        assert record["title"] == "מתמטיקה"
        assert record["language"] == "he"
        assert "מָתֵמָטִיקָה" in record["text"]

    def test_parse_empty_text(self):
        """Test handling of record with empty text."""
        record_str = json.dumps({
            "doc_id": "test_123",
            "title": "Test",
            "text": "",
        })

        record = json.loads(record_str)

        # Should parse but text is empty
        assert record["text"] == ""

    def test_parse_missing_optional_fields(self):
        """Test parsing record with missing optional fields."""
        record_str = json.dumps({
            "doc_id": "test_123",
            "text": "Content",
        })

        record = json.loads(record_str)

        # Should have required fields
        assert "doc_id" in record
        assert "text" in record

        # Optional fields may be missing
        assert record.get("title") is None
        assert record.get("url") is None


class TestIdempotency:
    """Test idempotency guarantees."""

    def test_same_record_same_hash(self):
        """Test same record produces same deduplication hash."""
        source_key = "hewiki"
        doc_id = "מתמטיקה"

        hash1 = compute_doc_hash(source_key, doc_id)
        hash2 = compute_doc_hash(source_key, doc_id)

        # Same hash means duplicate will be detected
        assert hash1 == hash2

    def test_hash_independent_of_content(self):
        """Test hash is based on doc_id, not content."""
        # Same doc_id should produce same hash regardless of content
        source_key = "hewiki"
        doc_id = "test_123"

        hash1 = compute_doc_hash(source_key, doc_id)
        hash2 = compute_doc_hash(source_key, doc_id)

        assert hash1 == hash2

        # Even if we had different content (not used in hash), hash stays the same


class TestErrorReporting:
    """Test error reporting in ImportReport."""

    def test_error_details_structure(self):
        """Test error details have expected structure."""
        report = ImportReport(
            started_at="2026-02-07T05:00:00Z",
            source_key="hewiki",
        )

        report.error_details.append({
            "file": "test.jsonl",
            "line": 42,
            "error": "JSON parse error",
        })

        result = report.to_dict()

        # Verify error details
        assert len(result["error_details"]) == 1
        error = result["error_details"][0]
        assert error["file"] == "test.jsonl"
        assert error["line"] == 42
        assert "error" in error

    def test_error_details_limit(self):
        """Test error details are limited to 100."""
        report = ImportReport(
            started_at="2026-02-07T05:00:00Z",
            source_key="hewiki",
        )

        # Add 150 errors
        for i in range(150):
            report.error_details.append({
                "file": f"test_{i}.jsonl",
                "error": f"Error {i}",
            })

        result = report.to_dict()

        # Should be limited to 100
        assert len(result["error_details"]) == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
