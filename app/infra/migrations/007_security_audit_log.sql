-- Migration 007: Security Audit Log
-- Purpose: Track security events (ALLOW, BLOCK, FAIL) for compliance and threat detection
-- Dependencies: None (standalone table)

-- Security audit log table
CREATE TABLE IF NOT EXISTS security_audit_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Event metadata
    event_timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    event_type TEXT NOT NULL, -- 'fts5_query', 'file_import', 'path_access', 'credential_access', etc.
    outcome TEXT NOT NULL CHECK(outcome IN ('ALLOW', 'BLOCK', 'FAIL')),

    -- Actor/context
    project_id INTEGER NULL, -- NULL for global operations
    user_context TEXT NULL, -- Future: user ID or session ID

    -- Event details
    operation TEXT NOT NULL, -- 'search', 'import_document', 'import_dictionary', 'read_file', etc.
    resource_type TEXT NULL, -- 'query', 'file', 'path', 'credential', etc.
    resource_id TEXT NULL, -- File path, query string (sanitized), credential key, etc.

    -- Security details
    reason TEXT NULL, -- Block/fail reason: 'FTS5_OPERATOR_BLOCKED', 'FILE_TOO_LARGE', 'UNC_PATH', etc.
    details TEXT NULL, -- JSON blob with additional context

    -- Performance
    duration_ms REAL NULL -- Operation duration in milliseconds
);

-- Indexes for audit queries
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON security_audit_log(event_timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_outcome ON security_audit_log(outcome);
CREATE INDEX IF NOT EXISTS idx_audit_event_type ON security_audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_project ON security_audit_log(project_id);

-- Update schema version
UPDATE schema_meta SET value = '7' WHERE key = 'schema_version';
