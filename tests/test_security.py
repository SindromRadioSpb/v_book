"""Security attack tests for P0 Security Hardening.

Tests that security mitigations prevent common attacks:
- FTS5 injection (operators, wildcards, syntax stress)
- SQL injection attempts
- CSV formula injection
- Path traversal (UNC, symlinks, system dirs)
- Log injection
- File size DoS
- Credential tampering
"""

import pytest
import tempfile
from pathlib import Path

from app.infra.security import (
    sanitize_fts5_query,
    sanitize_csv_cell,
    sanitize_for_log,
    sanitize_filename,
    validate_file_size,
    validate_path_security,
    validate_query_complexity,
    is_unc_path,
    is_system_path,
    QueryComplexityError,
    PathSecurityError,
    ValidationError,
    CredentialStore,
    encrypt,
    decrypt,
    generate_key,
)


class TestFTS5Injection:
    """Test FTS5 query injection attacks."""

    def test_operator_injection_blocked(self):
        """Test that FTS5 operators are blocked in strict mode."""
        malicious_queries = [
            "test AND attack",
            "foo OR bar",
            "NOT sensitive",
            "data NEAR attack",
            "test AND (foo OR bar)",
        ]

        for query in malicious_queries:
            with pytest.raises(QueryComplexityError) as exc_info:
                sanitize_fts5_query(query, strict=True)
            assert exc_info.value.reason == "OPERATOR_BLOCKED"

    def test_wildcard_explosion_limited(self):
        """Test that excessive wildcards are blocked."""
        # 6 wildcards exceeds MAX_FTS5_WILDCARDS (5)
        attack_query = "* * * * * *"

        with pytest.raises(QueryComplexityError) as exc_info:
            validate_query_complexity(attack_query)
        assert exc_info.value.reason == "WILDCARD_LIMIT"

    def test_parentheses_depth_limited(self):
        """Test that excessive nesting is blocked."""
        # 12 levels of nesting exceeds MAX_FTS5_PARENTHESES (10)
        attack_query = "((((((((((((test))))))))))))"

        with pytest.raises(QueryComplexityError) as exc_info:
            validate_query_complexity(attack_query)
        assert exc_info.value.reason == "PARENTHESES_DEPTH"

    def test_unbalanced_parentheses_rejected(self):
        """Test that unbalanced parentheses are rejected."""
        with pytest.raises(QueryComplexityError) as exc_info:
            validate_query_complexity("test ((foo)")
        assert exc_info.value.reason == "UNBALANCED_PARENTHESES"

    def test_special_chars_escaped(self):
        """Test that special FTS5 characters are escaped."""
        # Double quotes should be doubled, other special chars removed
        result = sanitize_fts5_query('test"quote', strict=False)
        assert '""' in result  # Doubled quotes

    def test_length_limit_enforced(self):
        """Test that overly long queries are rejected."""
        attack_query = "a" * 600  # Exceeds MAX_QUERY_LENGTH (500)

        with pytest.raises(QueryComplexityError) as exc_info:
            validate_query_complexity(attack_query)
        assert exc_info.value.reason == "LENGTH_EXCEEDED"

    def test_empty_query_handled(self):
        """Test that empty queries return safe default."""
        result = sanitize_fts5_query("", strict=True)
        assert result == '""'  # Empty quoted string

    def test_hebrew_text_preserved(self):
        """Test that legitimate Hebrew text passes through."""
        hebrew = "שלום עולם"
        result = sanitize_fts5_query(hebrew, strict=True)
        assert hebrew in result  # Hebrew preserved

    def test_operator_in_word_allowed(self):
        """Test that operators as substrings are allowed (word boundary check)."""
        # "world" contains "OR" but it's not a whole word
        result = sanitize_fts5_query("hello world", strict=True)
        assert "world" in result  # Should NOT be blocked


class TestCSVInjection:
    """Test CSV formula injection attacks."""

    def test_formula_prefix_neutralized(self):
        """Test that dangerous formula prefixes are neutralized."""
        dangerous_inputs = [
            "=SUM(A1:A10)",
            "+2+2",
            "-5",
            "@SUM(1,2)",
            "=1+1",
        ]

        for inp in dangerous_inputs:
            result = sanitize_csv_cell(inp)
            assert result.startswith("'"), f"Failed to neutralize: {inp}"
            assert result == "'" + inp

    def test_safe_content_unchanged(self):
        """Test that safe content passes through."""
        safe_inputs = [
            "normal text",
            "123",
            "test@example.com",
            "חשבון",  # Hebrew
        ]

        for inp in safe_inputs:
            result = sanitize_csv_cell(inp)
            assert result == inp, f"Safe input modified: {inp}"

    def test_empty_string_handled(self):
        """Test that empty strings are handled."""
        assert sanitize_csv_cell("") == ""
        assert sanitize_csv_cell(None) == None


class TestLogInjection:
    """Test log injection/forging attacks."""

    def test_crlf_replaced(self):
        """Test that CRLF is replaced to prevent log forging."""
        attack = "legit\r\nFAKE LOG ENTRY: unauthorized access"
        result = sanitize_for_log(attack)

        assert "\r" not in result
        assert "\n" not in result
        assert "_" in result  # CRLF replaced with underscores

    def test_tab_replaced(self):
        """Test that tabs are replaced."""
        attack = "col1\tcol2\tcol3"
        result = sanitize_for_log(attack)
        assert "\t" not in result

    def test_non_printable_removed(self):
        """Test that non-printable characters are removed."""
        attack = "test\x00\x01\x02hidden"
        result = sanitize_for_log(attack)
        # Non-printable chars should be replaced with '.'
        assert "\x00" not in result
        assert "\x01" not in result

    def test_truncation(self):
        """Test that overly long input is truncated."""
        attack = "a" * 200
        result = sanitize_for_log(attack, max_length=50)
        assert len(result) <= 53  # 50 + "..."
        assert result.endswith("...")


class TestPathTraversal:
    """Test path traversal and path security attacks."""

    def test_unc_path_detected(self):
        """Test that UNC paths are detected."""
        unc_paths = [
            Path("\\\\server\\share\\file.txt"),
            Path("//server/share/file.txt"),
        ]

        for path in unc_paths:
            assert is_unc_path(path), f"Failed to detect UNC: {path}"

    def test_unc_path_blocked(self):
        """Test that UNC paths are blocked by validation."""
        unc_path = Path("\\\\attacker\\share\\malware.exe")

        with pytest.raises(PathSecurityError) as exc_info:
            validate_path_security(unc_path)
        assert exc_info.value.reason == "UNC_PATH"

    def test_system_directory_detected(self):
        """Test that system directories are detected."""
        # Test Windows system dirs (if on Windows)
        import sys

        if sys.platform == "win32":
            system_paths = [
                Path("C:/Windows/System32/cmd.exe"),
                Path("C:/Program Files/test.exe"),
            ]

            for path in system_paths:
                assert is_system_path(path), f"Failed to detect system path: {path}"

    def test_system_directory_blocked(self):
        """Test that system directory access is blocked."""
        import sys

        if sys.platform == "win32":
            system_path = Path("C:/Windows/System32/config/SAM")

            with pytest.raises(PathSecurityError) as exc_info:
                validate_path_security(system_path)
            assert exc_info.value.reason == "SYSTEM_DIRECTORY"

    def test_path_traversal_neutralized(self):
        """Test that path traversal attempts are neutralized in filenames."""
        malicious_filenames = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "test/../../secret.txt",
        ]

        for filename in malicious_filenames:
            result = sanitize_filename(filename)
            assert "/" not in result  # Slashes replaced
            assert "\\" not in result  # Backslashes replaced

    def test_null_byte_removed(self):
        """Test that null bytes are removed from filenames."""
        attack = "normal.txt\x00malicious.exe"
        result = sanitize_filename(attack)
        assert "\x00" not in result


class TestFileSizeDoS:
    """Test file size DoS protection."""

    def test_large_file_rejected(self):
        """Test that oversized files are rejected."""
        # Create a temp file larger than MAX_DOCUMENT_SIZE
        with tempfile.NamedTemporaryFile(delete=False) as f:
            # Write 101 MB (exceeds 100 MB limit)
            f.write(b"0" * (101 * 1024 * 1024))
            temp_path = Path(f.name)

        try:
            with pytest.raises(ValidationError) as exc_info:
                from app.infra.security import MAX_DOCUMENT_SIZE

                validate_file_size(temp_path, MAX_DOCUMENT_SIZE)

            assert "too large" in str(exc_info.value).lower()
        finally:
            temp_path.unlink()

    def test_normal_file_accepted(self):
        """Test that normal-sized files pass validation."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"normal content")
            temp_path = Path(f.name)

        try:
            # Should not raise
            from app.infra.security import MAX_DOCUMENT_SIZE

            validate_file_size(temp_path, MAX_DOCUMENT_SIZE)
        finally:
            temp_path.unlink()


class TestCredentialSecurity:
    """Test credential storage security."""

    def test_encryption_roundtrip(self):
        """Test that encryption and decryption work correctly."""
        key = generate_key()
        plaintext = b"secret_api_key_12345"

        ciphertext = encrypt(plaintext, key)
        assert ciphertext != plaintext  # Actually encrypted

        decrypted = decrypt(ciphertext, key)
        assert decrypted == plaintext  # Correct decryption

    def test_tampered_ciphertext_rejected(self):
        """Test that tampered ciphertext is rejected."""
        from app.infra.security.errors import CredentialStoreError

        key = generate_key()
        plaintext = b"secret"

        ciphertext = encrypt(plaintext, key)

        # Tamper with ciphertext
        tampered = bytearray(ciphertext)
        tampered[-1] ^= 0xFF  # Flip last byte (tag corruption)

        with pytest.raises(CredentialStoreError) as exc_info:
            decrypt(bytes(tampered), key)

        assert "authentication tag invalid" in str(exc_info.value).lower()

    def test_wrong_key_rejected(self):
        """Test that wrong decryption key is rejected."""
        from app.infra.security.errors import CredentialStoreError

        key1 = generate_key()
        key2 = generate_key()
        plaintext = b"secret"

        ciphertext = encrypt(plaintext, key1)

        with pytest.raises(CredentialStoreError):
            decrypt(ciphertext, key2)  # Wrong key

    def test_credential_store_in_memory(self):
        """Test credential store with in-memory storage."""
        store = CredentialStore()
        storage = {}

        # Store credential
        store.set_credential("api_key", "secret_123", storage=storage)

        # Verify encrypted
        assert "api_key" in storage
        assert storage["api_key"] != "secret_123"  # Encrypted, not plaintext

        # Retrieve credential
        retrieved = store.get_credential("api_key", storage=storage)
        assert retrieved == "secret_123"  # Correct decryption

        # Delete credential
        deleted = store.delete_credential("api_key", storage=storage)
        assert deleted is True
        assert store.get_credential("api_key", storage=storage) is None

    def test_credential_value_size_limit(self):
        """Test that oversized credential values are rejected."""
        store = CredentialStore()
        storage = {}

        # Credential larger than CREDENTIAL_VALUE_MAX_LENGTH (4096)
        huge_value = "x" * 5000

        with pytest.raises(ValidationError) as exc_info:
            store.set_credential("test", huge_value, storage=storage)

        assert "too large" in str(exc_info.value).lower()


class TestSQLInjection:
    """Test that SQL injection is prevented (baseline verification)."""

    def test_parameterized_queries_used(self):
        """Verify that services use parameterized queries (code audit)."""
        # This is more of a code review check, but we can verify
        # that the sanitizers don't attempt SQL escaping
        # (which would indicate manual query building)

        # FTS5 sanitizer should NOT do SQL escaping
        result = sanitize_fts5_query("test'; DROP TABLE users; --", strict=True)

        # Should be treated as literal text, wrapped in quotes
        assert "DROP" in result  # Not escaped, just quoted
        assert result.startswith('"')
        assert result.endswith('"')

        # The query is safe because FTS5 MATCH uses parameterized binding


class TestEdgeCases:
    """Test edge cases and corner cases."""

    def test_unicode_handling(self):
        """Test that Unicode text is handled correctly."""
        hebrew = "שלום עולם"
        emoji = "🔒🔐"
        mixed = "test שלום 🔒"

        # Should all pass without errors
        assert sanitize_for_log(hebrew)
        assert sanitize_for_log(emoji)
        assert sanitize_for_log(mixed)

    def test_empty_inputs(self):
        """Test that empty inputs are handled gracefully."""
        assert sanitize_for_log("") == ""
        assert sanitize_for_log(None) == ""
        assert sanitize_csv_cell("") == ""

    def test_whitespace_only(self):
        """Test that whitespace-only inputs are handled."""
        result = sanitize_fts5_query("   ", strict=True)
        assert result == '""'  # Empty query


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
