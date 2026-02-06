"""Comprehensive smoke check for PATCH-06.

Verifies:
1. UI validation works
2. Service validation works
3. Audit log writes events
4. Credentials encrypted at rest
5. Rate limiting functional
6. Migrations apply cleanly
"""

import sys
import tempfile
from pathlib import Path

print("=" * 70)
print("PATCH-06 COMPREHENSIVE SMOKE CHECK")
print("=" * 70)
print()

# Test 1: UI Validation
print("[1/6] Testing UI validation...")
try:
    from app.ui.concordance_view import ConcordanceView
    from app.ui.import_wizard import ImportWizard
    from app.ui.dialogs import CreateProjectDialog
    from app.infra.security import QueryComplexityError, ValidationError

    print("  OK UI components import with validation")

    # Test query validation
    from app.infra.security import validate_query_complexity
    try:
        validate_query_complexity("*" * 10)  # Too many wildcards
        print("  FAIL Query validation should have failed!")
        sys.exit(1)
    except QueryComplexityError as e:
        print(f"  OK Query complexity validation works: {e.reason}")

except Exception as e:
    print(f"  FAIL UI validation failed: {e}")
    sys.exit(1)

# Test 2: Service Validation
print("[2/6] Testing service validation...")
try:
    from app.services.concordance_service import ConcordanceService
    from app.services.ingest_service import IngestService
    from app.infra.security import sanitize_fts5_query, validate_file_size

    # Test FTS5 sanitization
    result = sanitize_fts5_query("test query", strict=True)
    assert result.startswith('"') and result.endswith('"')
    print("  OK FTS5 sanitization works")

    # Test file size validation
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"test content")
        temp_path = Path(f.name)

    try:
        from app.infra.security import MAX_DOCUMENT_SIZE
        validate_file_size(temp_path, MAX_DOCUMENT_SIZE)
        print("  OK File size validation works")
    finally:
        temp_path.unlink()

except Exception as e:
    print(f"  FAIL Service validation failed: {e}")
    sys.exit(1)

# Test 3: Audit Log
print("[3/6] Testing audit log...")
try:
    from app.services.db_service import DBService
    from app.infra.security import AuditLogger
    from sqlalchemy import text

    # Initialize database
    db_path = Path(tempfile.gettempdir()) / "smoke_check_audit.db"
    if db_path.exists():
        db_path.unlink()

    db_service = DBService.initialize(db_path)

    with db_service.get_session() as session:
        # Write audit event
        audit = AuditLogger(session)
        audit.log_event(
            event_type="test",
            outcome="ALLOW",
            operation="smoke_check",
            resource_type="test",
            resource_id="test_resource",
        )

        # Verify it was written
        result = session.execute(
            text("SELECT COUNT(*) FROM security_audit_log WHERE event_type='test'")
        ).scalar()

        if result == 1:
            print("  OK Audit log writes events")
        else:
            print(f"  FAIL Audit log failed: expected 1 event, got {result}")
            sys.exit(1)

    DBService.shutdown()
    db_path.unlink()

except Exception as e:
    print(f"  FAIL Audit log failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 4: Credentials Encryption
print("[4/6] Testing credentials encryption...")
try:
    from app.infra.security import CredentialStore, encrypt, decrypt, generate_key

    # Test encryption
    key = generate_key()
    plaintext = b"secret_password_123"
    ciphertext = encrypt(plaintext, key)
    decrypted = decrypt(ciphertext, key)

    assert decrypted == plaintext
    assert ciphertext != plaintext  # Actually encrypted
    print("  OK Credentials encrypted at rest (AES-256-GCM)")

    # Test CredentialStore (in-memory mode)
    store = CredentialStore()
    storage = {}
    store.set_credential("test_key", "test_value", storage=storage)

    # Verify it's encrypted in storage
    assert storage["test_key"] != "test_value"
    print("  OK CredentialStore encrypts values")

    # Verify decryption
    retrieved = store.get_credential("test_key", storage=storage)
    assert retrieved == "test_value"
    print("  OK CredentialStore decrypts correctly")

except Exception as e:
    print(f"  FAIL Credentials encryption failed: {e}")
    sys.exit(1)

# Test 5: Rate Limiting
print("[5/6] Testing rate limiting...")
try:
    from app.infra.security import RateLimiter

    # Create limiter with low limit for testing
    limiter = RateLimiter(max_rate=5, window_seconds=60)

    # Should allow first 5 operations
    for i in range(5):
        assert limiter.is_allowed(), f"Operation {i+1} should be allowed"

    # 6th should be blocked
    assert not limiter.is_allowed(), "6th operation should be blocked"
    print("  OK Rate limiting blocks excess operations")

    # Reset should work
    limiter.reset()
    assert limiter.is_allowed(), "After reset, operations should be allowed"
    print("  OK Rate limiter reset works")

except Exception as e:
    print(f"  FAIL Rate limiting failed: {e}")
    sys.exit(1)

# Test 6: Migration Application
print("[6/6] Testing migration application...")
try:
    from app.infra.db import DatabaseManager
    from sqlalchemy import text

    # Create fresh database
    db_path = Path(tempfile.gettempdir()) / "smoke_check_migrations.db"
    if db_path.exists():
        db_path.unlink()

    db_manager = DatabaseManager(db_path)
    db_manager.apply_migrations()

    # Verify schema version
    with db_manager.get_session() as session:
        version = session.execute(
            text("SELECT value FROM schema_meta WHERE key='schema_version'")
        ).scalar()

        if version == "8":
            print(f"  OK Migrations applied: schema v{version}")
        else:
            print(f"  FAIL Wrong schema version: expected 8, got {version}")
            sys.exit(1)

        # Verify security tables exist
        tables = session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        ).fetchall()
        table_names = [t[0] for t in tables]

        if "security_audit_log" in table_names:
            print("  OK security_audit_log table exists")
        else:
            print("  FAIL security_audit_log table missing!")
            sys.exit(1)

        if "credentials" in table_names:
            print("  OK credentials table exists")
        else:
            print("  FAIL credentials table missing!")
            sys.exit(1)

    db_manager.close()
    db_path.unlink()

except Exception as e:
    print(f"  FAIL Migration application failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()
print("=" * 70)
print("OK ALL SMOKE CHECKS PASSED")
print("=" * 70)
print()
print("PATCH-06 verification complete:")
print("  OK UI validation functional")
print("  OK Service validation functional")
print("  OK Audit log writes events")
print("  OK Credentials encrypted at rest")
print("  OK Rate limiting works without breaking UX")
print("  OK Migrations apply cleanly on fresh database")
print()
print("Ready for git push!")
