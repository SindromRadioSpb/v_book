"""Clean-DB validation runner — PATCH-04.

Runs the full NLP validation suite against gold corpora without a populated
production database. Outputs a machine-readable JSON report.

Usage:
    python tools/run_clean_db_validation.py [--report-path PATH] [--no-stanza]

Exit codes:
    0 — all tests passed
    1 — one or more tests failed
    2 — configuration/import error

PowerShell:
    .\.venv\Scripts\python.exe tools\run_clean_db_validation.py
    .\.venv\Scripts\python.exe tools\run_clean_db_validation.py --report-path reports\validation_$(Get-Date -Format yyyyMMdd_HHmmss).json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

# Non-Stanza tests that must pass in every environment
FAST_TEST_FILTER = "not v02 and not stanza"


def _run_pytest(extra_args: list[str]) -> tuple[int, str]:
    """Run pytest and return (returncode, stdout+stderr)."""
    cmd = [
        PYTHON,
        "-m",
        "pytest",
        "tests/validation/",
        "--tb=short",
        "-q",
        *extra_args,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
    )
    return result.returncode, result.stdout + result.stderr


def _parse_pytest_output(output: str) -> dict:
    """Extract pass/fail counts from pytest summary line."""
    for line in reversed(output.splitlines()):
        line = line.strip()
        if "passed" in line or "failed" in line or "error" in line:
            return {"summary": line}
    return {"summary": "unknown"}


def main() -> int:
    parser = argparse.ArgumentParser(description="NLP validation runner")
    parser.add_argument(
        "--report-path",
        default=None,
        help="Write JSON report to this path (default: reports/validation_<timestamp>.json)",
    )
    parser.add_argument(
        "--no-stanza",
        action="store_true",
        default=True,
        help="Skip Stanza-dependent tests (default: True)",
    )
    parser.add_argument(
        "--include-stanza",
        action="store_true",
        default=False,
        help="Include Stanza-dependent tests (requires model download)",
    )
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if args.report_path:
        report_path = Path(args.report_path)
    else:
        reports_dir = REPO_ROOT / "reports"
        reports_dir.mkdir(exist_ok=True)
        report_path = reports_dir / f"validation_{timestamp}.json"

    print(f"[{timestamp}] Running NLP validation suite...")
    print(f"  Root: {REPO_ROOT}")
    print(f"  Report: {report_path}")

    results: list[dict] = []
    all_passed = True

    # --- Fast suite (no Stanza required) ---
    print("\n[1/2] Fast tests (no Stanza)...")
    fast_args = ["-k", FAST_TEST_FILTER, "--tb=short"]
    rc, output = _run_pytest(fast_args)
    parsed = _parse_pytest_output(output)
    fast_result = {
        "suite": "fast",
        "filter": FAST_TEST_FILTER,
        "returncode": rc,
        "passed": rc == 0,
        **parsed,
        "output_tail": output[-3000:],  # last 3000 chars for report
    }
    results.append(fast_result)
    if rc != 0:
        all_passed = False
        print(f"  FAILED (rc={rc}): {parsed.get('summary', '')}")
    else:
        print(f"  PASSED: {parsed.get('summary', '')}")

    # --- Stanza suite (optional) ---
    if args.include_stanza:
        print("\n[2/2] Stanza tests...")
        stanza_args = ["-m", "requires_stanza"]
        rc, output = _run_pytest(stanza_args)
        parsed = _parse_pytest_output(output)
        stanza_result = {
            "suite": "stanza",
            "filter": "requires_stanza",
            "returncode": rc,
            "passed": rc == 0,
            **parsed,
            "output_tail": output[-3000:],
        }
        results.append(stanza_result)
        if rc != 0:
            all_passed = False
            print(f"  FAILED (rc={rc}): {parsed.get('summary', '')}")
        else:
            print(f"  PASSED: {parsed.get('summary', '')}")
    else:
        print("\n[2/2] Stanza tests skipped (use --include-stanza to enable)")
        results.append({"suite": "stanza", "passed": None, "skipped": True})

    # --- Write report ---
    report = {
        "timestamp": timestamp,
        "all_passed": all_passed,
        "python": PYTHON,
        "repo_root": str(REPO_ROOT),
        "suites": results,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport written: {report_path}")

    final = "ALL PASSED" if all_passed else "FAILURES DETECTED"
    print(f"\n{'='*50}")
    print(f"  Result: {final}")
    print(f"{'='*50}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
