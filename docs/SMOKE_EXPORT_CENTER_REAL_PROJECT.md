# Export Center Real-Project Smoke Test

Automated end-to-end smoke testing of all export formats and UI options on a real project database.

## Overview

This smoke test validates the Export Center functionality by testing all export formats with their various options against a real project database. It performs 11 export scenarios covering CSV, JSON, XLSX, TBX, and TMX formats.

## What It Tests

### Export Matrix (11 Scenarios Total)

1. **CSV (1 variant)**: TM export to CSV format
2. **JSON (1 variant)**: TM export to JSON array format
3. **XLSX (1 variant)**: Multi-sheet Excel workbook (Dictionary + Statistics)
4. **TBX (4 variants)**: TermBase eXchange XML format
   - `approved_only=False, include_pinned=False`
   - `approved_only=False, include_pinned=True`
   - `approved_only=True, include_pinned=False`
   - `approved_only=True, include_pinned=True`
5. **TMX (4 variants)**: Translation Memory eXchange XML format
   - `include_draft=False, include_pinned=False`
   - `include_draft=False, include_pinned=True`
   - `include_draft=True, include_pinned=False`
   - `include_draft=True, include_pinned=True`

### Validation Criteria

For each export, the test validates:

- **File Creation**: Output file exists and has non-zero size
- **Format Validity**:
  - CSV: Header row present, valid CSV structure, no parse errors
  - JSON: Valid JSON array, expected entry count
  - XLSX: Valid workbook, "Dictionary" and "Statistics" sheets present, header cells populated
  - TBX: Valid XML, correct root element, proper TBX structure (text/body/termEntry)
  - TMX: Valid XML, correct root element, proper TMX structure (header/body/tu)
- **No Exceptions**: Export and validation complete without errors

### Coverage Warnings

The test accepts empty results (0 entries) as valid for smoke testing, but issues **coverage warnings** when:

- No approved terms exist (affects TBX with `approved_only=True`)
- No TM entries exist (affects CSV, JSON, TMX)
- No dictionary entries exist (affects XLSX)

These warnings indicate limited test coverage due to sparse project data, but are **not failures** for smoke testing purposes.

## Usage

### Prerequisites

1. Python virtual environment with dependencies:
   ```bash
   source .venv/Scripts/activate  # On Windows (Git Bash)
   # or
   .venv\Scripts\activate.bat     # On Windows (CMD)
   # or
   source .venv/bin/activate      # On Linux/macOS
   ```

2. Real project database (read-only access required)
3. Set QT platform for headless operation:
   ```bash
   export QT_QPA_PLATFORM=offscreen  # On Git Bash/Linux
   # or
   set QT_QPA_PLATFORM=offscreen     # On Windows CMD
   ```

### Running the Test

**Basic usage** (default project name):
```bash
python -m app.tools.smoke_export_center \
    --db "C:/Users/YourUser/AppData/Local/HDLE/hdle.db" \
    --project-name "ТЕСТ М8,М9"
```

**With custom output directory**:
```bash
python -m app.tools.smoke_export_center \
    --db /path/to/hdle.db \
    --project-name "My Project" \
    --outdir "custom/output/dir"
```

**Keep artifacts** (don't delete export files):
```bash
python -m app.tools.smoke_export_center \
    --db /path/to/hdle.db \
    --keep-artifacts
```

### Command-Line Options

- `--db <path>` (required): Path to the database file
- `--project-name <name>` (optional): Project name to test (default: "ТЕСТ М8,М9")
- `--outdir <path>` (optional): Output directory for artifacts (default: `runtime/smoke/export_center/<timestamp>`)
- `--keep-artifacts` (optional): Keep export files after test completion

## Output and Artifacts

### Exit Codes

- **0**: All tests PASS
- **Non-zero**: One or more tests FAIL

### Console Output

The test produces detailed console output including:

1. **Progress**: Real-time status of each export test
2. **Summary Table**: Results for all 11 scenarios with:
   - Pass/Fail status
   - Format name
   - Options used
   - File size
   - Entry count
   - File name
3. **Coverage Warnings**: List of scenarios with limited data coverage
4. **Final Result**: Overall PASS/FAIL verdict

Example summary:
```
======================================================================
SUMMARY
======================================================================
✅ PASS | CSV    | default                        |     1740 bytes |     9 entries | export_csv.csv
✅ PASS | JSON   | default                        |     5373 bytes |     9 entries | export_json.json
✅ PASS | XLSX   | default                        |     6618 bytes |    17 entries | export_xlsx.xlsx
...
======================================================================
Results: 11 PASS, 0 FAIL
Output directory: runtime\smoke\export_center\20260204_225444
======================================================================
```

### Artifact Files

All export files are saved to the output directory with deterministic names:

- `export_csv.csv`
- `export_json.json`
- `export_xlsx.xlsx`
- `export_tbx_approved0_pinned0.tbx`
- `export_tbx_approved0_pinned1.tbx`
- `export_tbx_approved1_pinned0.tbx`
- `export_tbx_approved1_pinned1.tbx`
- `export_tmx_draft0_pinned0.tmx`
- `export_tmx_draft0_pinned1.tmx`
- `export_tmx_draft1_pinned0.tmx`
- `export_tmx_draft1_pinned1.tmx`

Default location: `runtime/smoke/export_center/<timestamp>/`

## Interpreting Results

### PASS Criteria

A test PASSES when:
1. Export completes without exceptions
2. Output file is created
3. File has valid format structure
4. No validation errors occur

**Note**: `entries_count=0` is acceptable and generates a coverage warning, not a failure.

### FAIL Criteria

A test FAILS when:
1. Export throws an exception
2. Output file is not created
3. File has invalid format (parse errors, missing required elements)
4. Validation raises an error

### Coverage Warnings

Coverage warnings indicate test scenarios with limited data:

```
⚠️  TBX (approved_only=True, include_pinned=False): 0 term entries (no approved terms in project)
⚠️  TBX (approved_only=True, include_pinned=True): 0 term entries (no approved terms in project)
```

**Interpretation**:
- These are **informational**, not errors
- They indicate which export branches have limited test coverage
- Expected for sparse or test projects
- Can be addressed by populating the project with more diverse data (approved terms, draft entries, pinned translations)

### Common Issues

**Issue**: "Project 'XYZ' not found"
- **Solution**: Verify project name matches exactly (case-sensitive, Cyrillic characters)
- **Check**: Run `python -c "from app.services.project_service import ProjectService; from app.services.db_service import DBService; DBService.initialize('your.db'); with DBService.get_instance().get_session() as s: print([p.name for p in ProjectService().list_projects(s)])"` to list available projects

**Issue**: "Database locked" or permission errors
- **Solution**: Ensure the database is not open in another application
- **Solution**: Run with read-only permissions if needed

**Issue**: XML parse errors in TBX/TMX
- **Solution**: Check for special characters or encoding issues in project data
- **Mitigation**: Review export service XML sanitization logic

## Safety and Best Practices

1. **Read-Only Operation**: The smoke test only reads from the database and exports data. It does not modify project data.

2. **Production Safety**: Safe to run on production databases (read-only exports)

3. **Performance**: Test duration depends on project size (typically < 1 minute for small projects)

4. **Headless Mode**: Always set `QT_QPA_PLATFORM=offscreen` to avoid UI dependencies

5. **Artifact Cleanup**: Use `--keep-artifacts` only when debugging; otherwise artifacts are kept in timestamped directories

## Integration with CI/CD

The smoke test can be integrated into continuous integration pipelines:

```bash
#!/bin/bash
# CI smoke test script

export QT_QPA_PLATFORM=offscreen
source .venv/Scripts/activate

# Run smoke test on test database
python -m app.tools.smoke_export_center \
    --db "$TEST_DB_PATH" \
    --project-name "$TEST_PROJECT_NAME"

# Exit code propagates to CI
exit $?
```

Environment variables:
- `TEST_DB_PATH`: Path to test database
- `TEST_PROJECT_NAME`: Project name for testing

## Maintenance

### Updating Test Matrix

To add new export formats or options:

1. Edit `app/tools/smoke_export_center.py`
2. Add new test case in `build_test_matrix()` method
3. Implement validator function if needed
4. Update this documentation

### Troubleshooting Validator Failures

If a validator fails but the export appears correct:

1. Check the exported file manually
2. Review validator logic in `smoke_export_center.py`
3. Ensure validator accepts valid edge cases (e.g., empty entries)
4. Update validator if export format has changed

## Related Documentation

- [Export Service Implementation](../app/services/export_service.py)
- [M9 Export Center Tests](../test_m9.py)
- [Iteration 1 Report](ITERATION_1_REPORT.md)

## Version History

- **2026-02-04**: Initial implementation
  - 11 export scenarios (CSV, JSON, XLSX, TBX×4, TMX×4)
  - Format validators for all export types
  - Coverage warning system for sparse data
  - CLI interface with configurable database and project
