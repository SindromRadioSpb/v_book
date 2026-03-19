"""Runtime verification script for packaged build.

Verifies:
1. Database initialization (migrations to schema v8)
2. Security tables exist (security_audit_log, credentials)
3. Import smoke test (cryptography, keyring modules)
"""

import sys
import tempfile
from pathlib import Path

print("=" * 70)
print("PACKAGED BUILD - RUNTIME VERIFICATION")
print("=" * 70)
print()

# Test 1: Import smoke test
print("[1/3] Import smoke test (cryptography, keyring)...")
try:
    import cryptography
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    print(f"  OK cryptography {cryptography.__version__}")

    import keyring

    try:
        version = keyring.__version__
    except AttributeError:
        import importlib.metadata

        version = importlib.metadata.version("keyring")
    print(f"  OK keyring {version}")

    # Test actual encryption (use simple key generation for test)
    import os

    key = os.urandom(32)  # AES-256 key

    aesgcm = AESGCM(key)
    nonce = b"test_nonce_12345"[:12]
    ciphertext = aesgcm.encrypt(nonce, b"test plaintext", None)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)

    assert plaintext == b"test plaintext", "Encryption roundtrip failed!"
    print("  OK AES-256-GCM encryption roundtrip successful")

except Exception as e:
    print(f"  FAIL Import smoke test failed: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

print()

# Test 2: Database initialization
print("[2/3] Database initialization (migrations to v8)...")
try:
    from app.services.db_service import DBService
    from sqlalchemy import text

    # Create temporary database
    db_path = Path(tempfile.gettempdir()) / "verify_packaged_build.db"
    if db_path.exists():
        db_path.unlink()

    # Initialize database (applies migrations)
    db_service = DBService.initialize(db_path)

    with db_service.get_session() as session:
        # Check schema version
        version = session.execute(
            text("SELECT value FROM schema_meta WHERE key='schema_version'")
        ).scalar()

        if version == "8":
            print(f"  OK Schema version: v{version} (expected v8)")
        else:
            print(f"  FAIL Wrong schema version: v{version} (expected v8)")
            sys.exit(1)

        # List all tables
        tables = session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        ).fetchall()
        table_names = [t[0] for t in tables]

        print(f"  OK Total tables: {len(table_names)}")

    DBService.shutdown()
    db_path.unlink()

except Exception as e:
    print(f"  FAIL Database initialization failed: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

print()

# Test 3: Security tables
print("[3/3] Security tables verification...")
try:
    from app.services.db_service import DBService
    from sqlalchemy import text

    # Create temporary database
    db_path = Path(tempfile.gettempdir()) / "verify_security_tables.db"
    if db_path.exists():
        db_path.unlink()

    db_service = DBService.initialize(db_path)

    with db_service.get_session() as session:
        # Check security_audit_log table
        result = session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='security_audit_log'")
        ).scalar()

        if result:
            print("  OK security_audit_log table exists")

            # Check columns
            columns = session.execute(text("PRAGMA table_info(security_audit_log)")).fetchall()
            column_names = [c[1] for c in columns]

            required_columns = [
                "log_id",
                "event_timestamp",
                "event_type",
                "outcome",
                "operation",
                "resource_type",
                "resource_id",
                "reason",
            ]
            missing = [c for c in required_columns if c not in column_names]

            if missing:
                print(f"  FAIL Missing columns: {missing}")
                sys.exit(1)
            else:
                print(
                    f"  OK security_audit_log has all required columns ({len(column_names)} total)"
                )
        else:
            print("  FAIL security_audit_log table missing!")
            sys.exit(1)

        # Check credentials table
        result = session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='credentials'")
        ).scalar()

        if result:
            print("  OK credentials table exists")

            # Check columns
            columns = session.execute(text("PRAGMA table_info(credentials)")).fetchall()
            column_names = [c[1] for c in columns]

            required_columns = [
                "credential_id",
                "key",
                "encrypted_value",
                "created_at",
                "updated_at",
                "encryption_version",
            ]
            missing = [c for c in required_columns if c not in column_names]

            if missing:
                print(f"  FAIL Missing columns: {missing}")
                sys.exit(1)
            else:
                print(
                    f"  OK credentials table has all required columns ({len(column_names)} total)"
                )
        else:
            print("  FAIL credentials table missing!")
            sys.exit(1)

    DBService.shutdown()
    db_path.unlink()

except Exception as e:
    print(f"  FAIL Security tables verification failed: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

print()
print("=" * 70)
print("OK ALL RUNTIME VERIFICATIONS PASSED")
print("=" * 70)
print()
print("Results:")
print("  OK Cryptography + keyring imports work")
print("  OK AES-256-GCM encryption functional")
print("  OK Database initializes to schema v8")
print("  OK Security tables present with correct schema")
print()
print("Packaged build is ready for deployment!")
