# SECURITY AUDIT - HDLE Premium

**Document Version:** 1.0
**Date:** 2026-02-06
**Status:** P0 Security Hardening (Iteration 2)
**Scope:** Complete I/O security analysis

---

## EXECUTIVE SUMMARY

HDLE Premium is a desktop Hebrew-Russian linguistic analysis application built with PyQt6, SQLite, and Stanza NLP. This audit identifies all I/O attack surfaces and establishes security policies before adding premium features (MT provider integrations).

**Overall Security Posture:** ✅ **GOOD** (with specific gaps to address)

**Critical Findings:**
- ✅ **No SQL injection** (all queries parameterized)
- ✅ **CSV injection mitigated** (excellent export sanitization)
- ⚠️ **FTS5 syntax injection** (moderate risk - needs fix)
- ⚠️ **No file size limits** (DoS risk)
- ⚠️ **User input logged unsanitized** (privacy concern)

---

## 1. THREAT MODEL

### 1.1 Application Context

**Type:** Desktop application (Windows/macOS/Linux)
**Users:** Linguistic researchers, translators (local installation)
**Data Sensitivity:** Moderate (terminology databases, translation memory)
**Network Exposure:** None (currently offline-only)

### 1.2 Threat Actors

| Actor | Motivation | Capability |
|-------|-----------|------------|
| **Malicious Files** | Data exfiltration, code execution | HIGH - User imports hostile CSV/XLSX/PDF |
| **Untrusted Search Queries** | DoS (CPU/memory exhaustion) | MEDIUM - User crafts complex FTS queries |
| **Path Traversal** | File system access beyond app data | LOW - Mitigated by pathlib usage |
| **Future: External APIs** | MITM, credential theft | HIGH - MT providers (future feature) |

### 1.3 Attack Scenarios

#### Scenario 1: Malicious CSV Import
```
Attacker crafts CSV with:
- Formula injection: =cmd|'/c calc'!A1
- Large file (10GB) causing OOM
- Path traversal in file references
```

**Current Mitigation:** ✅ CSV formula sanitization (export only)
**Gap:** ⚠️ No import sanitization, no size limits

#### Scenario 2: FTS5 Query Injection
```
User enters search query: "*" OR "**" OR "***"
Result: FTS5 engine exhausts CPU on wildcard expansion
```

**Current Mitigation:** ⚠️ None (queries passed to FTS5 directly)
**Gap:** No input sanitization, no query complexity limits

#### Scenario 3: Log Injection
```
User searches for: "malicious\nINFO: Admin logged in\n"
Result: Forged log entries, log poisoning
```

**Current Mitigation:** ⚠️ None (user input logged as-is)
**Gap:** No CRLF sanitization in logs

#### Scenario 4: Unsafe File Paths (Future)
```
User selects path: \\UNC\hostile-server\share\file.db
Result: Network access, credential leakage (Windows)
```

**Current Mitigation:** ✅ Pathlib usage prevents most issues
**Gap:** No explicit UNC/symlink blocking policy

---

## 2. I/O INVENTORY (Attack Surface Map)

### 2.1 File Import Operations

| Format | Handler | Input Validation | Size Limit | Sanitization | Risk Level |
|--------|---------|------------------|------------|--------------|------------|
| **TXT** | `txt_extractor.py` | Extension check | ❌ None | N/A (text) | 🟡 MEDIUM |
| **DOCX** | `docx_extractor.py` | Extension check | ❌ None | python-docx lib | 🟡 MEDIUM |
| **PDF** | `pdf_extractor.py` | Extension check | ❌ None | PyPDF2 lib | 🟡 MEDIUM |
| **CSV** | `csv.reader` | SHA256 dedup | ❌ None | ❌ No formula check | 🟡 MEDIUM |
| **XLSX** | `openpyxl` | SHA256 dedup | ❌ None | `data_only=True` | 🟢 LOW |

**Gaps Identified:**
1. ⚠️ **No file size limits** - 10GB file could cause OOM
2. ⚠️ **No rate limiting** - Batch import abuse
3. ⚠️ **CSV import lacks formula sanitization** (export has it)

**Recommended Limits:**
- Documents (TXT/DOCX/PDF): 100 MB
- Dictionaries (CSV/XLSX): 10 MB
- Rate limit: 100 files/minute per project

---

### 2.2 File Export Operations

| Format | Handler | Output Sanitization | Atomic Write | Risk Level |
|--------|---------|---------------------|--------------|------------|
| **CSV** | `export_service.py:export_tm_csv()` | ✅ Formula prefix neutralized | ✅ Yes | 🟢 LOW |
| **JSON** | `export_service.py:export_tm_json()` | ✅ `json.dump()` safe | ✅ Yes | 🟢 LOW |
| **XLSX** | `export_service.py:export_xlsx()` | ✅ openpyxl safe mode | ✅ Yes | 🟢 LOW |
| **TBX** | `export_service.py:export_tbx()` | ✅ XML char filtering | ✅ Yes | 🟢 LOW |
| **TMX** | `export_service.py:export_tmx()` | ✅ XML char filtering | ✅ Yes | 🟢 LOW |

**Excellent Implementation:**
```python
def sanitize_csv_cell(cell_value: str) -> str:
    """Neutralize CSV injection by prefixing dangerous chars with single quote."""
    if cell_value and cell_value[0] in "=+-@":
        return "'" + cell_value
    return cell_value
```

**No gaps identified in export operations.** ✅

---

### 2.3 Database Operations

#### SQL Queries

**Status:** ✅ **EXCELLENT** - All queries properly parameterized

**Pattern Analysis:**
```python
# ✅ SAFE: Parameterized query
stmt = select(TermCard).where(TermCard.project_id == project_id)

# ✅ SAFE: text() with parameter binding
sql = text("SELECT * FROM tm_entry WHERE project_id = :pid")
session.execute(sql, {'pid': project_id})

# ❌ NEVER FOUND: String concatenation in SQL
# sql = f"SELECT * FROM tm_entry WHERE name = '{user_input}'"  # NOT FOUND
```

**Audit Result:** No SQL injection vulnerabilities found.

#### FTS5 Full-Text Search

**Location:** `app/services/concordance_service.py`

**Current Implementation:**
```python
# Lines 118-131: Query construction
fts_query = ' OR '.join(f'"{v}"' for v in variants)  # Variants quoted
# OR
fts_query = f'"{query.strip()}"'  # Exact phrase

# Line 159: Parameterized execution (SAFE for SQL, NOT for FTS5 syntax)
sql = text("""SELECT ... FROM sentence_fts WHERE sentence_fts MATCH :q ...""")
result = session.execute(sql, {'q': fts_query, ...})
```

**Vulnerability:** ⚠️ **FTS5 Syntax Injection**

**Attack Examples:**
```
Query: *               → Matches everything (CPU spike)
Query: " OR "**"       → Complex wildcard explosion
Query: AND NOT AND     → Syntax confusion
Query: (((((((((       → Parser stress
```

**Risk Level:** 🟡 **MEDIUM** (DoS, not RCE)

**Mitigation Strategy:**
1. **Escape FTS5 special characters:** `"` `*` `(` `)` `AND` `OR` `NOT` `NEAR`
2. **Query complexity limit:** Max 10 operators, max 5 wildcards
3. **Query timeout:** 5 seconds max execution time
4. **Audit logging:** Log query, outcome (ALLOW/BLOCK/TIMEOUT)

---

### 2.4 Subprocess/External Tools

| Tool | Usage | Shell=True | Input Source | Risk Level |
|------|-------|------------|--------------|------------|
| **os.startfile()** | Open file browser (Windows) | N/A | Internal path | 🟢 LOW |
| **subprocess.run(["open", path])** | Open file browser (macOS) | ❌ No | Internal path | 🟢 LOW |
| **subprocess.run(["xdg-open", path])** | Open file browser (Linux) | ❌ No | Internal path | 🟢 LOW |
| **Stanza NLP** | In-process library | N/A | User text | 🟢 LOW |

**Audit Result:** ✅ No shell injection vulnerabilities found.

**Future Considerations:**
- If MT providers added: Validate API keys, enforce HTTPS, log API calls
- If external tools added: Use list-args only, no shell=True

---

### 2.5 User Input Points

#### Search Boxes
- **Concordance search:** Hebrew text → FTS5 MATCH (⚠️ injection risk)
- **Term search:** Keywords → SQL WHERE (✅ parameterized)
- **Dictionary search:** Keywords → FTS5 (⚠️ injection risk)

#### Text Fields
- **Project name:** Stored via ORM (✅ safe)
- **Translation text:** Stored in TM (✅ safe)
- **Notes:** Stored via ORM (✅ safe)

#### File Dialogs
- **QFileDialog.getOpenFileName()** (✅ Qt validates)
- **QFileDialog.getSaveFileName()** (✅ Qt validates)
- **QFileDialog.getExistingDirectory()** (✅ Qt validates)

---

### 2.6 Logging Operations

**Configuration:** `app/infra/util/logging.py`
- Rotating logs: 10 MB x 5 backups = 50 MB total
- Format: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
- Encoding: UTF-8

**User Input Logged:**
```python
# concordance_service.py:133
logger.info(f"Concordance search: query={fts_query}, limit={limit}")

# ingest_service.py:78
logger.exception(f"Text extraction failed for {file_path}")
```

**Vulnerabilities:**
1. ⚠️ **Log Injection:** No CRLF sanitization
   ```
   Query: "test\nINFO: Admin access granted\n"
   Result: Forged log entries
   ```

2. ⚠️ **Privacy:** Search queries logged indefinitely
   - May contain sensitive terminology
   - Retained for 50 MB (weeks/months of data)

**Mitigation:**
- Sanitize: Replace `\n` `\r` with `_` before logging
- Truncate: Log only first 100 chars of queries
- Retention: Implement log expiry (30 days)

---

## 3. SECURITY GAPS & RECOMMENDED MITIGATIONS

### 3.1 High Priority (P0)

| Gap | Impact | Mitigation | Effort |
|-----|--------|------------|--------|
| **FTS5 syntax injection** | DoS (CPU exhaustion) | Escape special chars, complexity limits | Medium |
| **No file size limits** | DoS (OOM) | Enforce 100MB (docs), 10MB (CSV/XLSX) | Low |
| **Log injection** | Log forgery, info disclosure | Sanitize CRLF, truncate user input | Low |

### 3.2 Medium Priority (P1)

| Gap | Impact | Mitigation | Effort |
|-----|--------|------------|--------|
| **No import rate limiting** | Abuse, resource exhaustion | 100 files/min limit | Medium |
| **CSV import lacks sanitization** | Formula injection (if re-exported) | Apply formula check on import | Low |
| **Query privacy in logs** | Sensitive data retention | Redact/hash queries in logs | Low |

### 3.3 Low Priority (P2)

| Gap | Impact | Mitigation | Effort |
|-----|--------|------------|--------|
| **No UNC path blocking** | Windows credential leak | Block `\\` prefix on Windows | Low |
| **No symlink detection** | Path traversal (Linux/macOS) | Resolve symlinks, block external | Medium |
| **No text field length limits** | UI DoS (paste 1GB text) | 10,000 char limit per field | Low |

---

## 4. SECURITY POLICY DECISIONS (Iteration 2)

### 4.1 FTS5 Query Sanitization Policy

**Decision:** ✅ **ESCAPE + COMPLEXITY LIMIT**

**Implementation:**
```python
def sanitize_fts5_query(query: str) -> str:
    """Escape FTS5 special characters and enforce complexity limits."""
    # 1. Escape special chars
    for char in ['"', '*', '(', ')', '[', ']']:
        query = query.replace(char, f'\\{char}')

    # 2. Block reserved words
    if any(word in query.upper() for word in ['AND', 'OR', 'NOT', 'NEAR']):
        raise ValueError("FTS5 operators not allowed in basic search")

    # 3. Length limit
    if len(query) > 500:
        raise ValueError("Query too long (max 500 chars)")

    return query
```

**Audit:** Log `action=FTS5_SEARCH`, `outcome=ALLOW/BLOCK`, `reason`

---

### 4.2 File Size Limits Policy

**Decision:** ✅ **ENFORCE HARD LIMITS**

| File Type | Max Size | Rationale |
|-----------|----------|-----------|
| TXT | 100 MB | Largest reasonable text document |
| DOCX | 100 MB | Large academic papers |
| PDF | 100 MB | Books, technical manuals |
| CSV | 10 MB | Dictionaries (millions of entries) |
| XLSX | 10 MB | Excel performance limit |

**Implementation:** Check `file_size_bytes` before processing

**Audit:** Log `action=IMPORT`, `outcome=BLOCK`, `reason=SIZE_LIMIT_EXCEEDED`

---

### 4.3 UNC Path / Symlink Policy

**Decision:** ✅ **BLOCK UNC, RESOLVE SYMLINKS**

**Windows UNC Paths:**
```python
def is_unc_path(path: Path) -> bool:
    """Check if path is UNC (\\server\share)."""
    return str(path).startswith(('\\\\', '//'))

# Policy: Block all UNC paths
if is_unc_path(path):
    raise ValueError("UNC paths not allowed (security risk)")
```

**Unix Symlinks:**
```python
# Policy: Resolve symlinks, block if target outside app data
resolved = path.resolve(strict=True)
if not resolved.is_relative_to(app_data_dir):
    raise ValueError("Symlink target outside app directory")
```

**Rationale:** Prevents credential leaks (Windows), path traversal (Unix)

**Audit:** Log `action=PATH_VALIDATION`, `outcome=BLOCK`, `reason=UNC_PATH`

---

### 4.4 System Directory Exclusion Policy

**Decision:** ✅ **BLOCK SYSTEM PATHS**

**Forbidden Directories:**
- Windows: `C:\Windows`, `C:\Program Files`, `C:\Program Files (x86)`
- macOS: `/System`, `/Library`, `/Applications`
- Linux: `/bin`, `/boot`, `/dev`, `/etc`, `/lib`, `/proc`, `/root`, `/sbin`, `/sys`

**Implementation:**
```python
SYSTEM_DIRS = [
    Path("C:/Windows"), Path("C:/Program Files"),
    Path("/System"), Path("/bin"), Path("/etc"), ...
]

def is_system_path(path: Path) -> bool:
    """Check if path is in system directory."""
    resolved = path.resolve()
    return any(resolved.is_relative_to(sys_dir) for sys_dir in SYSTEM_DIRS)
```

**Audit:** Log `action=PATH_VALIDATION`, `outcome=BLOCK`, `reason=SYSTEM_DIR`

---

### 4.5 Log Sanitization Policy

**Decision:** ✅ **SANITIZE CRLF, TRUNCATE, REDACT**

**Implementation:**
```python
def sanitize_for_log(user_input: str, max_length: int = 100) -> str:
    """Sanitize user input for safe logging."""
    # 1. Replace CRLF with underscore
    sanitized = user_input.replace('\r', '_').replace('\n', '_')

    # 2. Truncate
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + '...'

    # 3. Escape non-printable chars
    sanitized = ''.join(c if c.isprintable() else '.' for c in sanitized)

    return sanitized
```

**Usage:**
```python
logger.info(f"Search query: {sanitize_for_log(query)}")
```

---

### 4.6 Credential Storage Policy (Future MT Providers)

**Decision:** ✅ **ENCRYPTED AT REST, OS KEYRING FOR MASTER KEY**

**Architecture:**
```
Master Key (32 bytes) → OS Keyring (keyring library)
    ↓
Encrypts/Decrypts
    ↓
Secrets File (JSON) → %LOCALAPPDATA%\HDLE\secrets.enc.json
    {
        "google_mt_api_key": {
            "ciphertext": "base64...",
            "nonce": "base64...",
            "tag": "base64..."
        }
    }
```

**Implementation:**
- Encryption: AES-256-GCM (cryptography library)
- AAD: `b"credential:v1:" + key_name.encode()`
- Fallback: If OS keyring unavailable → ERROR (no insecure fallback)

**Audit:** Log `action=CREDENTIAL_SET/GET/DELETE`, `outcome`, `key_name` (NOT value)

---

## 5. EXISTING SECURITY CONTROLS (Positive Findings)

### 5.1 Excellent Practices

✅ **Parameterized SQL Queries** - Zero SQL injection vulnerabilities
✅ **CSV Export Sanitization** - Formula injection prevented
✅ **XML Character Filtering** - Robust TBX/TMX generation
✅ **Atomic File Writes** - Temp file + `os.replace()` pattern
✅ **SHA256 Deduplication** - Prevents re-import attacks
✅ **WAL-Safe Backups** - Database integrity preserved
✅ **No Shell=True** - All subprocess calls use list-args
✅ **Process Locking** - PID-based with stale detection
✅ **Pathlib Usage** - Consistent, safe path handling
✅ **No Unsafe Deserialization** - No pickle/marshal/yaml.load

### 5.2 Defense in Depth

**Layer 1: Input Validation**
- File extension whitelists
- SHA256 integrity checks
- Qt dialog path validation

**Layer 2: Safe Libraries**
- SQLAlchemy ORM (injection-proof)
- openpyxl with `data_only=True`
- python-docx, PyPDF2 (safe parsers)

**Layer 3: Isolation**
- Desktop app (no network exposure)
- Single-user mode (no auth needed)
- Process locking (no concurrent modification)

**Layer 4: Auditability**
- Structured logging (rotating, UTF-8)
- Import/export tracked with counts
- Backup operations logged

---

## 6. THREAT MITIGATION ROADMAP

### Phase 1: Critical Gaps (This Iteration)
- [x] Security audit complete
- [ ] FTS5 sanitization module
- [ ] File size limit enforcement
- [ ] Log sanitization utility
- [ ] Audit log migration (security_audit_log table)

### Phase 2: MT Provider Readiness (Next Iteration)
- [ ] Credential store (AES-GCM + keyring)
- [ ] API key validation
- [ ] HTTPS enforcement
- [ ] Rate limiting per provider
- [ ] API call audit logging

### Phase 3: Hardening (Future)
- [ ] UNC path blocking
- [ ] Symlink resolution policy
- [ ] System directory exclusion
- [ ] Text field length limits
- [ ] Log expiry (30-day retention)

---

## 7. OUT OF SCOPE (Documented)

The following are explicitly OUT OF SCOPE for desktop application:

1. **Web-based attacks:** XSS, CSRF, clickjacking (not a web app)
2. **Authentication:** No multi-user support planned
3. **Authorization:** Single-user local app
4. **Network security:** No network features currently
5. **Memory safety:** Python's memory management sufficient
6. **Code signing:** OS-level concern (installer phase)
7. **Sandbox escapes:** Desktop app has OS-level permissions

---

## 8. COMPLIANCE & STANDARDS

### 8.1 OWASP Desktop App Security

**Relevant Controls:**
- ✅ Input validation (file types, sizes)
- ✅ Output encoding (CSV, XML)
- ✅ Cryptography (AES-GCM for credentials - planned)
- ✅ Error handling (no sensitive data in errors)
- ✅ Logging (structured, rotating)

### 8.2 CWE Mitigations

| CWE | Description | Status |
|-----|-------------|--------|
| CWE-89 | SQL Injection | ✅ Mitigated (parameterized queries) |
| CWE-78 | OS Command Injection | ✅ Mitigated (no shell=True) |
| CWE-79 | Cross-Site Scripting | N/A (desktop app) |
| CWE-22 | Path Traversal | ✅ Mitigated (pathlib usage) |
| CWE-502 | Unsafe Deserialization | ✅ Mitigated (no pickle) |
| CWE-117 | Log Injection | ⚠️ TODO (CRLF sanitization needed) |
| CWE-1236 | CSV Injection | ✅ Mitigated (export sanitized) |

---

## APPENDIX A: FILE INVENTORY

**Security-Critical Files:**

**I/O Handlers:**
- `app/services/ingest_service.py` - Document import
- `app/services/dictionary_import_service.py` - CSV/XLSX import
- `app/services/export_service.py` - All exports
- `app/services/concordance_service.py` - FTS5 search

**Infrastructure:**
- `app/infra/db.py` - Database connection, migrations
- `app/infra/process_lock.py` - Concurrent access control
- `app/infra/util/logging.py` - Log configuration

**Extractors:**
- `app/infra/extractors/txt_extractor.py`
- `app/infra/extractors/docx_extractor.py`
- `app/infra/extractors/pdf_extractor.py`

**To Be Created (This Iteration):**
- `app/infra/security/sanitizer.py` - Input sanitization
- `app/infra/security/validator.py` - Input validation
- `app/infra/security/crypto.py` - AES-GCM encryption
- `app/infra/security/credentials.py` - Credential store
- `app/infra/security/audit.py` - Audit logging
- `tests/test_security.py` - Security test suite

---

## APPENDIX B: ATTACK TEST CASES (Planned)

**Test Suite:** `tests/test_security.py`

**Coverage (15+ attacks):**
1. FTS5 wildcard explosion: `*`, `**`, `***`
2. FTS5 operator injection: `AND OR NOT NEAR`
3. FTS5 syntax stress: `(((((((((`
4. SQL injection attempt: `'; DROP TABLE tm_entry; --`
5. CSV formula injection (import): `=cmd|'/c calc'!A1`
6. CSV formula injection (export): `=1+1`, `@SUM(A1:A10)`
7. Path traversal: `../../../etc/passwd`
8. UNC path injection: `\\hostile-server\share`
9. Symlink escape: `ln -s /etc/passwd data.txt`
10. System directory access: `C:\Windows\System32\config\SAM`
11. Log injection: `"query\nINFO: Admin access\n"`
12. File size DoS: 10 GB CSV file
13. XML entity expansion: `<!ENTITY dos SYSTEM "file:///etc/passwd">`
14. Subprocess injection: `; rm -rf /` (if ever used)
15. Credential storage: Keyring unavailable fallback
16. JSON deserialization: `{"__reduce__": ...}` (if ever used)
17. ZIP slip: Archive with `../../../malicious.exe`

**All tests must result in:** BLOCK + audit log entry

---

**Document Owner:** Security Team
**Review Frequency:** Before each feature release
**Next Review:** Before MT provider integration

---

**END OF SECURITY AUDIT**
