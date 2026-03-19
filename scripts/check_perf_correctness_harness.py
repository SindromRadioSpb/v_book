#!/usr/bin/env python3
"""Fast correctness harness for perf patch regressions (PATCH-08)."""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import re
import sys
from pathlib import Path
from typing import Any

DEFAULT_SCAN_DIR = Path("build/logs")
DEFAULT_GLOB = "pipeline_bench_metrics_*.json"
DEFAULT_TAKE = 20
DEFAULT_REPORT_PATH = Path("build/logs/perf_correctness_report_latest.md")
FILENAME_RE = re.compile(r"^pipeline_bench_metrics_(\d{8}_\d{6})\.json$")


class HarnessError(RuntimeError):
    """Raised when artifact discovery/parsing is invalid."""


def _parse_timestamp(path: Path) -> dt.datetime:
    m = FILENAME_RE.match(path.name)
    if not m:
        raise HarnessError(f"Filename does not match expected pattern: {path.name}")
    return dt.datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")


def _sort(paths: list[Path]) -> list[Path]:
    return sorted(paths, key=lambda p: (_parse_timestamp(p), p.name))


def _discover(args: argparse.Namespace) -> list[Path]:
    if args.artifacts:
        candidates = [Path(x).expanduser().resolve() for x in args.artifacts]
    elif args.glob:
        candidates = [Path(x).resolve() for x in glob.glob(args.glob)]
    else:
        scan_dir = Path(args.dir).expanduser().resolve()
        candidates = list(scan_dir.glob(DEFAULT_GLOB))

    if not candidates:
        raise HarnessError("No pipeline artifacts found for correctness harness.")

    for path in candidates:
        if not path.exists() or not path.is_file():
            raise HarnessError(f"Invalid artifact path: {path}")

    ordered = _sort(candidates)
    take_n = max(1, int(args.take))
    if len(ordered) > take_n:
        ordered = ordered[-take_n:]
    return ordered


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HarnessError(f"Malformed JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise HarnessError(f"JSON payload must be an object: {path}")
    return payload


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return default


def _rows_total(rows: Any) -> int:
    if not isinstance(rows, dict):
        return 0
    return sum(max(0, _safe_int(v)) for v in rows.values())


def _snapshot(payload: dict[str, Any], artifact: Path) -> dict[str, Any]:
    stages = payload.get("stages")
    if not isinstance(stages, list) or not stages:
        raise HarnessError(f"Missing stages in {artifact}")
    stage = stages[0]
    if not isinstance(stage, dict):
        raise HarnessError(f"Invalid stage structure in {artifact}")
    name = str(stage.get("name") or "").strip()
    if not name:
        raise HarnessError(f"Missing stage name in {artifact}")

    db = payload.get("db") if isinstance(payload.get("db"), dict) else {}
    return {
        "artifact": str(artifact),
        "stage_name": name,
        "overall_status": str(payload.get("overall_status") or ""),
        "stage_status": str(stage.get("status") or ""),
        "errors_count": max(0, _safe_int(stage.get("errors_count"))),
        "overwrite_mode": _safe_int(
            stage.get("overwrite"), _safe_int((payload.get("config") or {}).get("overwrite"), 0)
        ),
        "rows": (
            stage.get("rows_processed") if isinstance(stage.get("rows_processed"), dict) else {}
        ),
        "rows_total": _rows_total(stage.get("rows_processed")),
        "details": stage.get("details") if isinstance(stage.get("details"), dict) else {},
        "db_paths": {
            "source_db": str(db.get("source_db") or ""),
            "base_sandbox_db": str(db.get("base_sandbox_db") or ""),
            "working_db": str(db.get("working_db") or ""),
        },
        "error_samples": (
            stage.get("error_samples") if isinstance(stage.get("error_samples"), list) else []
        )[:5],
    }


def _check_common(s: dict[str, Any]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    checks.append(
        {
            "name": "overall_status_pass",
            "status": "PASS" if s["overall_status"] == "pass" else "FAIL",
        }
    )
    checks.append(
        {"name": "stage_status_ok", "status": "PASS" if s["stage_status"] == "ok" else "FAIL"}
    )
    checks.append(
        {"name": "error_count_zero", "status": "PASS" if s["errors_count"] == 0 else "FAIL"}
    )
    checks.append(
        {"name": "overwrite_enabled", "status": "PASS" if s["overwrite_mode"] == 1 else "FAIL"}
    )
    checks.append(
        {"name": "rows_total_positive", "status": "PASS" if s["rows_total"] > 0 else "FAIL"}
    )
    has_m_path = any(path.upper().startswith("M:\\") for path in s["db_paths"].values() if path)
    checks.append({"name": "db_paths_not_m_drive", "status": "PASS" if not has_m_path else "FAIL"})
    return checks


def _check_extract_terms(s: dict[str, Any]) -> list[dict[str, str]]:
    rows = s["rows"]
    return [
        {
            "name": "extract_terms_lemma_positive",
            "status": "PASS" if _safe_int(rows.get("lemma")) > 0 else "FAIL",
        },
        {
            "name": "extract_terms_term_positive",
            "status": "PASS" if _safe_int(rows.get("term")) > 0 else "FAIL",
        },
        {
            "name": "extract_terms_sentence_positive",
            "status": "PASS" if _safe_int(rows.get("sentence")) > 0 else "FAIL",
        },
    ]


def _check_niqqud(s: dict[str, Any]) -> list[dict[str, str]]:
    rows = s["rows"]
    details = s["details"]
    lexical = details.get("lexical") if isinstance(details.get("lexical"), dict) else {}
    sentence = details.get("sentence") if isinstance(details.get("sentence"), dict) else {}
    checks = [
        {
            "name": "niqqud_lemma_positive",
            "status": "PASS" if _safe_int(rows.get("lemma")) > 0 else "FAIL",
        },
        {
            "name": "niqqud_sentence_positive",
            "status": "PASS" if _safe_int(rows.get("sentence")) > 0 else "FAIL",
        },
    ]
    if lexical:
        checks.append(
            {
                "name": "niqqud_lexical_failed_zero",
                "status": "PASS" if _safe_int(lexical.get("failed")) == 0 else "FAIL",
            }
        )
    else:
        checks.append({"name": "niqqud_lexical_details_present", "status": "WARN"})
    if sentence:
        checks.append(
            {
                "name": "niqqud_sentence_failed_zero",
                "status": "PASS" if _safe_int(sentence.get("failed")) == 0 else "FAIL",
            }
        )
    else:
        checks.append({"name": "niqqud_sentence_details_present", "status": "WARN"})
    return checks


def _check_translate(s: dict[str, Any]) -> list[dict[str, str]]:
    details = s["details"]
    checks: list[dict[str, str]] = []
    has_blocks = False
    for scope in ("lemma", "term", "sentence"):
        block = details.get(scope) if isinstance(details.get(scope), dict) else None
        if block is None:
            continue
        has_blocks = True
        total = _safe_int(block.get("total"))
        succ = _safe_int(block.get("succeeded"))
        skipped = _safe_int(block.get("skipped"))
        failed = _safe_int(block.get("failed"))
        checks.append(
            {
                "name": f"translate_{scope}_counter_consistency",
                "status": "PASS" if total == (succ + skipped + failed) else "FAIL",
            }
        )
        if total > 0:
            checks.append(
                {
                    "name": f"translate_{scope}_no_failures",
                    "status": "PASS" if failed == 0 else "FAIL",
                }
            )
    if not has_blocks:
        checks.append({"name": "translate_details_present", "status": "WARN"})
    return checks


def _worst(checks: list[dict[str, str]]) -> str:
    statuses = [c["status"] for c in checks]
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    return "PASS"


def _evaluate(
    artifacts: list[Path], payloads: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str]:
    snapshots = [
        _snapshot(payload, artifact) for payload, artifact in zip(payloads, artifacts, strict=True)
    ]
    latest_by_stage: dict[str, dict[str, Any]] = {}
    for snap in snapshots:
        latest_by_stage[snap["stage_name"]] = snap

    rows: list[dict[str, Any]] = []

    for stage_name in ("extract_terms", "niqqud_bootstrap", "translate_bootstrap"):
        snap = latest_by_stage.get(stage_name)
        if snap is None:
            rows.append(
                {
                    "stage_name": stage_name,
                    "status": "FAIL",
                    "checks": [{"name": "artifact_present", "status": "FAIL"}],
                    "snapshot": None,
                    "reason": "Required stage artifact missing.",
                    "deferred": False,
                }
            )
            continue
        checks = _check_common(snap)
        if stage_name == "extract_terms":
            checks.extend(_check_extract_terms(snap))
        elif stage_name == "niqqud_bootstrap":
            checks.extend(_check_niqqud(snap))
        elif stage_name == "translate_bootstrap":
            checks.extend(_check_translate(snap))
        rows.append(
            {
                "stage_name": stage_name,
                "status": _worst(checks),
                "checks": checks,
                "snapshot": snap,
                "reason": "",
                "deferred": False,
            }
        )

    tts_snap = latest_by_stage.get("tts_bootstrap")
    rows.append(
        {
            "stage_name": "tts_bootstrap",
            "status": "DEFERRED",
            "checks": [],
            "snapshot": tts_snap,
            "reason": "Deferred-safe stage: baseline and spend policy controlled separately.",
            "deferred": True,
        }
    )

    overall = "PASS"
    for row in rows:
        if row["deferred"]:
            continue
        if row["status"] == "FAIL":
            overall = "FAIL"
            break
        if row["status"] == "WARN" and overall != "FAIL":
            overall = "WARN"
    return rows, overall


def _write_report(
    path: Path, stage_rows: list[dict[str, Any]], overall: str, used: list[Path]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    now_utc = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    lines: list[str] = []
    lines.append("# Perf Correctness Harness Report")
    lines.append("")
    lines.append(f"- Timestamp (UTC): `{now_utc}`")
    lines.append(f"- Overall status: **{overall}**")
    lines.append("")
    lines.append("## Artifacts Used")
    for item in used:
        lines.append(f"- `{item}`")
    lines.append("")
    for row in stage_rows:
        lines.append(f"## `{row['stage_name']}`")
        lines.append(f"- Status: **{row['status']}**")
        if row["deferred"]:
            lines.append(f"- Reason: {row['reason']}")
            lines.append("")
            continue
        snap = row["snapshot"] or {}
        lines.append(f"- Artifact: `{snap.get('artifact', '')}`")
        lines.append(f"- Processed rows: `{snap.get('rows_total', 0)}`")
        lines.append(f"- Errors: `{snap.get('errors_count', 0)}`")
        lines.append(f"- Overwrite mode: `{snap.get('overwrite_mode', 0)}`")
        lines.append("| Check | Status |")
        lines.append("|---|---|")
        for check in row["checks"]:
            lines.append(f"| `{check['name']}` | **{check['status']}** |")
        lines.append("")
    lines.append("Exit code mapping: `0=PASS`, `2=WARN`, `1=FAIL`.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", nargs="+", help="Explicit artifact paths.")
    parser.add_argument("--glob", dest="glob", default=None, help="Glob pattern for artifacts.")
    parser.add_argument("--dir", dest="dir", default=None, help="Directory scan path.")
    parser.add_argument(
        "--take", type=int, default=DEFAULT_TAKE, help="Use N most recent artifacts."
    )
    parser.add_argument(
        "--report-path", default=str(DEFAULT_REPORT_PATH), help="Markdown report path."
    )
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.glob is None and args.dir is None and not args.artifacts:
        args.dir = str(DEFAULT_SCAN_DIR)

    report = Path(args.report_path).expanduser().resolve()
    try:
        artifacts = _discover(args)
        payloads = [_load(path) for path in artifacts]
        stage_rows, overall = _evaluate(artifacts, payloads)
        _write_report(report, stage_rows, overall, artifacts)
        print(f"Correctness harness overall status: {overall}")
        print(f"Report: {report}")
        if overall == "PASS":
            return 0
        if overall == "WARN":
            return 2
        return 1
    except HarnessError as exc:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            "# Perf Correctness Harness Report\n\n"
            "- Overall status: **FAIL**\n"
            f"- Error: `{exc}`\n",
            encoding="utf-8",
        )
        print(f"FAIL: {exc}", file=sys.stderr)
        print(f"Report: {report}", file=sys.stderr)
        return 1


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
