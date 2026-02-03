# Definition of Done - HDLE Premium

This document defines the quality gates and testing requirements that must be met before:
- Merging feature branches to main
- Creating releases
- Deploying to production
- Making significant architectural changes

## Testing Requirements

### 1. All Automated Tests Must Pass

All tests must pass without errors or failures. Run the complete test suite:

```bash
# M7 Core Tests
python test_m7.py

# M7 UI Integration Tests
python test_m7_ui_integration.py

# M7 Normalization Tests
python test_m7_normalization.py

# P1 Unit Tests
python test_p1_verification.py

# P1 E2E Tests (Real Term Clusters)
python test_p1_e2e_termclusters.py

# P2 Service Tests
python test_p2_translation_admin_service.py
python test_p2_coverage_service.py

# P2 Model Tests
python test_p2_translation_management_model.py

# P2 UI Smoke Tests
python test_p2_ui_smoke.py
```

**Windows (PowerShell):**
```powershell
.\scripts\ci_run_tests.ps1
```

**Linux/macOS (Bash):**
```bash
./scripts/ci_run_tests.sh
```

### 2. P1 Production Verification

Run P1 Scenario 7 verification on a production-like database to ensure TM persistence:

```bash
python -m app.tools.p1_verify --db <path_to_db> --project-id <project_id>
```

**Requirements:**
- Status must be `PASS` or `PARTIAL` (never `FAIL`)
- All three phases must complete:
  - pre_extraction: 100% success rate
  - post_extraction: 100% success rate
  - post_restart: 100% success rate
- JSON report must be generated and saved

**Expected Output:**
```
Status: PASS
Duration: <duration> ms
Report: runtime/verifications/p1/<timestamp>/P1_SCENARIO_7_REPORT.json
```

### 3. P2 Premium Workflow Quality Gates

P2 adds Translation Management and QA/Coverage features. All tests must pass:

```bash
# P2 Service Tests (13 tests)
python test_p2_translation_admin_service.py  # 7 tests: CRUD, status workflow, revert
python test_p2_coverage_service.py           # 6 tests: metrics, query count guards

# P2 Model Tests (12 tests)
python test_p2_translation_management_model.py  # Qt model, inline editing

# P2 UI Smoke Tests (6 tests)
python test_p2_ui_smoke.py  # Panel instantiation, imports
```

**P2 Critical Contracts:**
- **Revert contract**: `origin="revert"` (NOT "user_edit")
- **Change_kind mapping**: `approved → "approve"`, `rejected → "reject"`, `deprecated → "deprecate"`
- **Query count ceilings**:
  - Coverage computation: ≤ 3 queries
  - Untranslated lists: ≤ 5 queries
- **Status workflow**: Approve sets `approved_at`/`approved_by`, Reject/Deprecate clears them
- **Worker cleanup**: Cancel buttons functional, `closeEvent` stops workers

**P2 Test Requirements:**
- All 31 P2 tests PASS
- Query counters verify no N+1 queries
- Headless Qt tests compatible (QT_QPA_PLATFORM=offscreen)
- No runtime DB files committed

**Schema Requirements:**
- Schema version ≥ 6 (includes P2 migration 006_p2_add_revert_origin.sql)
- `tm_entry.origin` CHECK constraint includes 'revert'
- `tm_entry_history.change_kind` CHECK constraint includes 'revert'

### 4. Artifact Requirements

The following artifacts must be generated and preserved:

#### P1 Verification Reports
- **Location:** `runtime/verifications/p1/<timestamp>/`
- **Files:**
  - `P1_SCENARIO_7_REPORT.json` - Machine-readable verification report
  - `P1_SCENARIO_7_REPORT.md` - Human-readable verification report (optional)

#### Report Contents
JSON report must include:
- `timestamp`: Verification timestamp
- `source_db_path`: Original database path
- `snapshot_sha256`: Snapshot integrity hash
- `project_id`: Project ID tested
- `test_items`: List of items tested (term_cluster, lemma)
- `seeded_tm_entries`: TM entries created
- `phases`: Results for all three phases
  - `pre_extraction`
  - `post_extraction`
  - `post_restart`
- `status`: Overall status (PASS/PARTIAL/SKIPPED/FAIL)
- `total_duration_ms`: Total execution time
- `error_summary`: Any errors encountered (null if none)

**Example Report Structure:**
```json
{
  "timestamp": "20260203_063022",
  "status": "PASS",
  "total_duration_ms": 197.96,
  "phases": {
    "pre_extraction": {
      "items_checked": 3,
      "items_passed": 3,
      "items_failed": 0,
      "success_rate": 100.0
    },
    "post_extraction": {
      "items_checked": 3,
      "items_passed": 3,
      "items_failed": 0,
      "success_rate": 100.0
    },
    "post_restart": {
      "items_checked": 3,
      "items_passed": 3,
      "items_failed": 0,
      "success_rate": 100.0
    }
  }
}
```

### 5. Schema Verification

Before running tests, verify database schema is up to date:

```bash
# Check schema version (must be >= 6 for P2 support, >= 5 for M7)
sqlite3 hdle.db "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1;"
```

**Required Tables:**
- `tm_entry` - Translation Memory entries (M7)
- `tm_entry_history` - TM version history (M7)
- `dict_source` - Dictionary sources (M7)
- `dict_entry` - Dictionary entries (M7)
- `mt_cache` - Machine Translation cache (M7)

**Required Migrations:**
- `004_m7_translation_memory.sql` - M7 base schema
- `005_m7_add_revert_origin.sql` - Add 'revert' to tm_entry_history.origin
- `006_p2_add_revert_origin.sql` - Add 'revert' to tm_entry.origin (P2)

### 6. Code Quality Standards

- No linter errors (`pylint`, `flake8`)
- No type errors (`mypy` if type hints are used)
- All imports resolve correctly
- No deprecated API usage
- Proper error handling (no bare `except:`)

### 7. Documentation Updates

When adding new features or changing behavior:
- Update relevant documentation files
- Add usage examples to M7_SMOKE_CHECK.md if user-facing
- Update docstrings for modified functions
- Document any new configuration options
- P2: Update docs/P2_PREMIUM_WORKFLOW.md and docs/P2_TESTS.md

### 7. Git Standards

- Meaningful commit messages following conventional commits format
- No merge conflicts
- No uncommitted changes
- Branch up to date with main/develop

**Commit Message Format:**
```
<type>(<scope>): <subject>

<body>

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `test`: Test additions or modifications
- `docs`: Documentation changes
- `refactor`: Code refactoring
- `chore`: Maintenance tasks

## Release Checklist

Before creating a release:

- [ ] All automated tests pass (M7 + P1 unit + P1 E2E)
- [ ] P1 verification completes with PASS status on production-like data
- [ ] JSON verification report saved to artifacts
- [ ] Schema version verified (>= 5)
- [ ] Documentation updated
- [ ] CHANGELOG.md updated with release notes
- [ ] Version number incremented appropriately
- [ ] No known critical bugs
- [ ] Manual smoke testing completed (see M7_SMOKE_CHECK.md)
- [ ] All CI checks passing on GitHub Actions

## CI/CD Integration

The GitHub Actions workflow (`.github/workflows/ci.yml`) enforces these requirements automatically:

- Runs on: `push` to main/develop, `pull_request` to main
- Tests on: Ubuntu + Windows
- Python versions: 3.11, 3.12
- Headless UI testing: `QT_QPA_PLATFORM=offscreen`

**Gate Policy:**
- Pipeline fails if ANY test fails
- Pull requests cannot be merged if CI is red
- All checks must pass before release

## Emergency Hotfix Exception

In emergency situations (critical production bugs), the following minimal requirements apply:

- [ ] Hotfix addresses only the critical issue
- [ ] Core tests pass: `test_m7.py`, `test_p1_verification.py`
- [ ] P1 verification on affected functionality shows PASS
- [ ] Full test suite run after deployment
- [ ] Full DoD applied to follow-up stabilization PR

## Verification History

Keep verification reports for compliance and debugging:

```bash
# List recent verifications
ls -la runtime/verifications/p1/

# Archive old reports (keep last 30 days)
find runtime/verifications/p1/ -type d -mtime +30 -exec rm -rf {} \;
```

## Feature-Specific Requirements

### Database Migrations

When adding/modifying database schema:

- [ ] Migration script created in `schema/` directory
- [ ] Migration is idempotent (can run multiple times safely)
- [ ] Rollback script provided (if applicable)
- [ ] Schema version incremented correctly
- [ ] Migration tested on copy of production data
- [ ] Data integrity verified after migration
- [ ] Foreign key constraints validated
- [ ] Indexes added for performance-critical queries

**Migration Naming Convention:**
```
<version>_<milestone>_<description>.sql
Example: 004_m7_translation_memory.sql
```

**Migration Template:**
```sql
-- Migration: <description>
-- Version: <version>
-- Date: <date>

PRAGMA foreign_keys = ON;

BEGIN TRANSACTION;

-- Schema changes here
CREATE TABLE IF NOT EXISTS new_table (...);

-- Data migration (if needed)
INSERT INTO new_table SELECT ... FROM old_table;

-- Update schema version
INSERT INTO schema_version (version, applied_at, description)
VALUES (<version>, datetime('now'), '<description>');

COMMIT;
```

### Translation Memory (TM) Changes

When modifying TM functionality:

- [ ] All P1 tests pass (unit + E2E)
- [ ] Normalization tests pass (test_m7_normalization.py)
- [ ] Verify backwards compatibility with existing TM entries
- [ ] Test with Hebrew, Russian, and English text
- [ ] Verify term_cluster canonical_key compatibility
- [ ] Test multiword expressions
- [ ] Test special characters and Unicode
- [ ] Verify strict vs. lenient normalization modes

### UI Changes

When modifying PyQt6 interface:

- [ ] UI integration tests pass (test_m7_ui_integration.py)
- [ ] Manual testing on Windows
- [ ] Tab navigation works correctly
- [ ] Keyboard shortcuts documented
- [ ] Accessibility features maintained
- [ ] No memory leaks (QThread workers properly cleaned up)
- [ ] Responsive UI (no freezing during long operations)
- [ ] Error messages are user-friendly
- [ ] Progress indicators for long-running tasks

### API/Service Changes

When modifying service layer:

- [ ] All dependent tests updated
- [ ] Service contracts (inputs/outputs) documented
- [ ] Error handling covers edge cases
- [ ] Logging added for debugging
- [ ] Session management correct (no leaked sessions)
- [ ] Transaction boundaries clearly defined
- [ ] Rollback on errors

## Performance Requirements

### P1 Verification Performance

- **Execution time:** < 5 seconds for databases up to 50MB
- **Execution time:** < 30 seconds for databases up to 500MB
- **Memory usage:** < 500MB peak during verification
- **Snapshot creation:** < 10 seconds for databases up to 100MB

If performance degrades:
- Profile with `cProfile` or `py-spy`
- Check database query efficiency
- Verify proper indexing
- Consider batch processing for large datasets

### Database Query Performance

- No queries > 1 second on production-sized data
- Use `EXPLAIN QUERY PLAN` for complex queries
- Add indexes for frequently filtered columns
- Avoid N+1 query patterns

## Security Requirements

### Data Safety

- [ ] No production database modification without user consent
- [ ] Snapshot-by-default for all verification/testing
- [ ] Sensitive data (credentials, API keys) not logged
- [ ] User data encrypted at rest (if applicable)
- [ ] No SQL injection vulnerabilities
- [ ] No command injection vulnerabilities

### Input Validation

- [ ] All user inputs validated
- [ ] File paths sanitized
- [ ] Database queries parameterized (no string concatenation)
- [ ] File upload size limits enforced
- [ ] File type validation for document ingestion

### Secrets Management

- [ ] No hardcoded credentials
- [ ] API keys stored in environment variables or secure config
- [ ] `.env` files in `.gitignore`
- [ ] Sample config files use placeholder values

## Backwards Compatibility

### Database Schema

When modifying schema:
- [ ] Existing data can be migrated automatically
- [ ] Old clients can read new schema (if multi-version support required)
- [ ] Migration path documented

### TM Canonical Keys

Critical for term_cluster compatibility:
- [ ] New normalization preserves existing canonical_key format
- [ ] M5 canonical keys remain valid
- [ ] Test migration of old TM entries to new format

### Configuration Files

- [ ] New config options have sensible defaults
- [ ] Old config files continue to work
- [ ] Deprecated options show warnings (not errors)

## Rollback Procedures

### Database Rollback

If migration fails in production:

```bash
# 1. Stop application
# 2. Restore from backup
cp hdle.db.backup hdle.db

# 3. Verify schema version
sqlite3 hdle.db "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1;"

# 4. Restart application
```

### Code Rollback

If release causes critical issues:

```bash
# 1. Identify last stable commit
git log --oneline

# 2. Create hotfix branch
git checkout -b hotfix/revert-<feature>

# 3. Revert problematic commits
git revert <commit-hash>

# 4. Run minimal test suite
python test_m7.py
python test_p1_verification.py

# 5. Deploy hotfix
```

## Monitoring and Observability

### Logging Requirements

- [ ] Errors logged with full traceback
- [ ] Info logs for major operations (verification start/end)
- [ ] Debug logs for troubleshooting (can be toggled)
- [ ] No sensitive data in logs
- [ ] Log rotation configured for long-running processes

**Log Levels:**
- `ERROR`: Failures that require intervention
- `WARNING`: Unexpected but handled situations
- `INFO`: Major operations and milestones
- `DEBUG`: Detailed troubleshooting information

### Health Checks

For production deployments:

```python
# Database connectivity
def check_db_health():
    try:
        with DBService.get_session() as session:
            session.execute("SELECT 1")
        return True
    except Exception as e:
        logger.error(f"DB health check failed: {e}")
        return False

# Schema version
def check_schema_version():
    with DBService.get_session() as session:
        result = session.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        version = result.scalar()
        return version >= 5  # M7 requirement
```

## User Acceptance

### User-Facing Features

- [ ] Feature works as described in requirements
- [ ] Error messages are clear and actionable
- [ ] Help documentation updated
- [ ] User workflow tested end-to-end
- [ ] Edge cases handled gracefully
- [ ] No data loss scenarios

### P1 Verification Panel (UI)

Specific acceptance criteria:

- [ ] Database path auto-populated with production DB
- [ ] Browse button works correctly
- [ ] Project dropdown shows all projects + "Global" option
- [ ] Run button disabled during execution
- [ ] Cancel button stops verification immediately
- [ ] Progress bar updates in real-time
- [ ] Log output shows execution steps
- [ ] Status badge reflects correct state (PASS/PARTIAL/FAIL)
- [ ] "Open Report" button opens JSON file in default editor
- [ ] "Copy Summary" copies formatted text to clipboard
- [ ] Back button returns to dashboard
- [ ] No UI freeze during verification

## Continuous Improvement

### Test Coverage

Target coverage levels:
- **Critical paths:** 100% (TM resolution, normalization)
- **Service layer:** > 80%
- **UI layer:** > 60%
- **Overall:** > 70%

### Technical Debt

Before each release:
- [ ] Review and prioritize technical debt backlog
- [ ] Address critical debt items
- [ ] Refactor code with TODO/FIXME comments
- [ ] Update deprecated dependencies

### Performance Benchmarks

Maintain performance benchmark history:

```bash
# Run benchmarks before release
python -m pytest benchmarks/ --benchmark-only

# Compare with previous release
python -m pytest benchmarks/ --benchmark-compare=<previous_release>
```

## Documentation Requirements

### Code Documentation

- [ ] All public functions have docstrings
- [ ] Complex algorithms explained with comments
- [ ] Type hints for function parameters
- [ ] Example usage in docstrings

**Docstring Template:**
```python
def verify_tm_persistence(session: Session, items: List[TestItem]) -> VerificationResult:
    """Verify that TM entries persist through re-extraction and restart.

    Args:
        session: Active database session
        items: List of test items to verify

    Returns:
        VerificationResult with pass/fail status for each item

    Raises:
        ValueError: If items list is empty
        DBError: If database connection fails

    Example:
        >>> items = [TestItem(kind="lemma", src_text="בית", ...)]
        >>> result = verify_tm_persistence(session, items)
        >>> assert result.status == "PASS"
    """
```

### User Documentation

- [ ] README.md up to date with setup instructions
- [ ] M7_SMOKE_CHECK.md includes new features
- [ ] Screenshots updated for UI changes
- [ ] Known issues documented
- [ ] Troubleshooting guide updated

### Release Notes

Include in CHANGELOG.md:
- **Added:** New features
- **Changed:** Modifications to existing features
- **Deprecated:** Features marked for removal
- **Removed:** Deleted features
- **Fixed:** Bug fixes
- **Security:** Security improvements

**Release Note Template:**
```markdown
## [Version X.Y.Z] - YYYY-MM-DD

### Added
- P1 Premium UI Panel for Scenario 7 verification
- Automated CI gate with GitHub Actions

### Changed
- TM normalization now uses strict mode by default

### Fixed
- UNIQUE constraint error when running P1 verification multiple times
- Windows console encoding for Unicode output

### Security
- Database snapshot now prevents accidental production modification
```

## Sign-Off Requirements

### Before Merging PR

Required approvals:
- [ ] Code review by at least one team member
- [ ] All CI checks passing (green)
- [ ] No merge conflicts
- [ ] All review comments addressed

### Before Release

Required sign-offs:
- [ ] Lead developer approves technical implementation
- [ ] QA approves test results
- [ ] Product owner approves functionality
- [ ] Release notes reviewed and approved

## Questions?

For questions about this DoD or testing procedures, see:
- **User Guide:** M7_SMOKE_CHECK.md
- **Developer Guide:** docs/ARCHITECTURE.md (if exists)
- **CI Scripts:** scripts/ci_run_tests.ps1, scripts/ci_run_tests.sh
- **Issues:** GitHub Issues for bug reports and feature requests

## Revision History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-02-03 | Initial Definition of Done | Claude Sonnet 4.5 |

**Last Updated:** 2026-02-03
