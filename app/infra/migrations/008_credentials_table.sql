-- Migration 008: Encrypted Credentials Storage
-- Purpose: Store encrypted credentials in database with AES-256-GCM
-- Dependencies: None (standalone table)

-- Credentials table (encrypted at rest)
CREATE TABLE IF NOT EXISTS credentials (
    credential_id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Key identifier (plaintext)
    key TEXT NOT NULL UNIQUE,

    -- Encrypted value (base64-encoded AES-256-GCM ciphertext)
    -- Format: nonce (12 bytes) || ciphertext || tag (16 bytes)
    encrypted_value TEXT NOT NULL,

    -- Metadata
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),

    -- Optional: key rotation tracking
    encryption_version INTEGER NOT NULL DEFAULT 1
);

-- Index for fast key lookup
CREATE INDEX IF NOT EXISTS idx_credentials_key ON credentials(key);

-- Trigger to update updated_at timestamp
CREATE TRIGGER IF NOT EXISTS trg_credentials_updated
AFTER UPDATE ON credentials
FOR EACH ROW
BEGIN
    UPDATE credentials SET updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')
    WHERE credential_id = NEW.credential_id;
END;

-- Update schema version
UPDATE schema_meta SET value = '8' WHERE key = 'schema_version';
