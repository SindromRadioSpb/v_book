#!/usr/bin/env python3
"""Deterministic checker for write-gate benchmark budget contract."""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import statistics
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_REPORT_PATH = REPO_ROOT / "build" / "logs" / "write_gate_budget_report_latest.md"
DEFAULT_SCAN_DIR = REPO_ROOT / "build" / "logs"
DEFAULT_GLOB = "import_concurrent_save_metrics_*.json"
DEFAULT_TAKE = 3


class BudgetCheckError(RuntimeError):
    """Raised when checker input/parsing is invalid."""


BASELINE_AFTER_MS = {
    "overall_hold_p95": 278.947,
    "overall_hold_max": 278.947,
    "lemma_hold_p95": 278.947,
    "lemma_hold_max": 278.947,
    "save_p95": 190.623,
    "save_max": 297.981,
}

PASS_THRESHOLDS_MS = {
    "overall_hold_p95_ms": BASELINE_AFTER_MS["overall_hold_p95"] + 20.0,
    "overall_hold_max_ms": BASELINE_AFTER_MS["overall_hold_max"] + 40.0,
    "lemma_hold_p95_ms": BASELINE_AFTER_MS["lemma_hold_p95"] + 20.0,
    "lemma_hold_max_ms": BASELINE_AFTER_MS["lemma_hold_max"] + 40.0,
    "save_p95_ms": BASELINE_AFTER_MS["save_p95"] + 25.0,
    "save_max_ms": BASELINE_AFTER_MS["save_max"] + 40.0,
}


def _warn_limit(pass_limit: float) -> float:
    return pass_limit + max(30.0, pass_limit * 0.10)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(round((pct / 100.0) * (len(ordered) - 1)))
    return ordered[idx]


def _parse_timestamp_from_name(path: Path) -> dt.datetime:
    """Parse timestamp from import metrics filename. Raises if missing/invalid."""
    stem = path.stem
    # Expected: import_concurrent_save_metrics_YYYYMMDD_HHMMSS
    prefix = "import_concurrent_save_metrics_"
    if not stem.startswith(prefix):
        raise BudgetCheckError(f"Filename does not match expected pattern: {path.name}")
    ts = stem[len(prefix):]
    try:
        return dt.datetime.strptime(ts, "%Y%m%d_%H%M%S")
    except ValueError as exc:
        raise BudgetCheckError(f"Filename timestamp parse failed for {path.name}: {exc}") from exc


def _sort_artifacts(paths: list[Path]) -> list[Path]:
    return sorted(paths, key=lambda p: (_parse_timestamp_from_name(p), p.name))


def _discover_artifacts(args: argparse.Namespace) -> list[Path]:
    candidates: list[Path]
    if args.artifacts:
        candidates = [Path(x).expanduser().resolve() for x in args.artifacts]
    elif args.glob:
        candidates = [Path(x).resolve() for x in glob.glob(args.glob)]
    else:
        scan_dir = Path(args.dir).expanduser().resolve()
        candidates = list(scan_dir.glob(DEFAULT_GLOB))

    if not candidates:
        raise BudgetCheckError("No artifacts found for budget check.")

    for path in candidates:
        if not path.exists():
            raise BudgetCheckError(f"Artifact not found: {path}")
        if not path.is_file():
            raise BudgetCheckError(f"Artifact is not a file: {path}")

    ordered = _sort_artifacts(candidates)
    take_n = max(1, int(args.take))
    if len(ordered) > take_n:
        ordered = ordered[-take_n:]
    return ordered


def _load_artifact(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        raise BudgetCheckError(f"Failed to read artifact {path}: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BudgetCheckError(f"Malformed JSON in {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise BudgetCheckError(f"JSON payload must be an object: {path}")
    return payload


def _extract_lemma_phase_max(payload: dict[str, Any], *, artifact: Path) -> float:
    gate_trace = payload.get("gate_trace")
    if not isinstance(gate_trace, dict):
        raise BudgetCheckError(f"Missing gate_trace object in {artifact}")

    top_phase = gate_trace.get("top_phase_max_holds")
    if not isinstance(top_phase, list):
        raise BudgetCheckError(f"Missing top_phase_max_holds in {artifact}")

    for item in top_phase:
        if isinstance(item, dict) and item.get("phase") == "import.table.lemma":
            try:
                return float(item["max_hold_ms"])
            except Exception as exc:  # noqa: BLE001
                raise BudgetCheckError(f"Invalid lemma max_hold_ms in {artifact}: {exc}") from exc

    raise BudgetCheckError(f"Lemma phase max hold not found in {artifact}")


def _extract_run_metrics(payload: dict[str, Any], *, artifact: Path) -> dict[str, float]:
    try:
        overall_max_hold = float(payload["gate_trace"]["max_hold_ms"])
        save_p95 = float(payload["save_ops"]["latency_ms"]["p95"])
        save_max = float(payload["save_ops"]["latency_ms"]["max"])
    except Exception as exc:  # noqa: BLE001
        raise BudgetCheckError(f"Missing required metric fields in {artifact}: {exc}") from exc

    lemma_max_hold = _extract_lemma_phase_max(payload, artifact=artifact)
    return {
        "overall_max_hold_ms": overall_max_hold,
        "lemma_phase_max_hold_ms": lemma_max_hold,
        "save_p95_ms": save_p95,
        "save_max_ms": save_max,
    }


def _aggregate(run_metrics: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    keys = ("overall_max_hold_ms", "lemma_phase_max_hold_ms", "save_p95_ms", "save_max_ms")
    out: dict[str, dict[str, float]] = {}
    for key in keys:
        values = [float(row[key]) for row in run_metrics]
        out[key] = {
            "mean": float(statistics.mean(values)),
            "p95": float(_percentile(values, 95.0)),
            "max": float(max(values)),
        }
    return out


def _classify(value: float, pass_limit: float) -> tuple[str, float]:
    warn_limit = _warn_limit(pass_limit)
    if value <= pass_limit:
        return "PASS", warn_limit
    if value <= warn_limit:
        return "WARN", warn_limit
    return "FAIL", warn_limit


def _evaluate_budget(aggregates: dict[str, dict[str, float]]) -> tuple[list[dict[str, Any]], str]:
    checks = [
        ("overall_hold_p95_ms", aggregates["overall_max_hold_ms"]["p95"]),
        ("overall_hold_max_ms", aggregates["overall_max_hold_ms"]["max"]),
        ("lemma_hold_p95_ms", aggregates["lemma_phase_max_hold_ms"]["p95"]),
        ("lemma_hold_max_ms", aggregates["lemma_phase_max_hold_ms"]["max"]),
        ("save_p95_ms", aggregates["save_p95_ms"]["p95"]),
        ("save_max_ms", aggregates["save_max_ms"]["max"]),
    ]

    rows: list[dict[str, Any]] = []
    overall = "PASS"
    for key, value in checks:
        pass_limit = float(PASS_THRESHOLDS_MS[key])
        status, warn_limit = _classify(value, pass_limit)
        rows.append(
            {
                "check": key,
                "value_ms": float(value),
                "pass_limit_ms": pass_limit,
                "warn_limit_ms": float(warn_limit),
                "status": status,
            }
        )
        if status == "FAIL":
            overall = "FAIL"
        elif status == "WARN" and overall != "FAIL":
            overall = "WARN"
    return rows, overall


def _load_build_meta() -> dict[str, Any]:
    try:
        from app import build_meta

        meta = build_meta.get_build_meta()
        return {
            "version": str(meta.get("version", "unknown")),
            "commit": str(meta.get("commit", "unknown")),
            "dirty": int(meta.get("dirty", 0)),
            "built_at_utc": str(meta.get("built_at_utc", "unknown")),
        }
    except Exception:
        return {
            "version": "unknown",
            "commit": "unknown",
            "dirty": 0,
            "built_at_utc": "unknown",
        }


def _write_markdown_report(
    *,
    report_path: Path,
    artifacts: list[Path],
    aggregates: dict[str, dict[str, float]],
    budget_rows: list[dict[str, Any]],
    overall_status: str,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    meta = _load_build_meta()
    now_utc = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")

    lines: list[str] = []
    lines.append("# Write-Gate Budget Report")
    lines.append("")
    lines.append(f"- Timestamp (UTC): `{now_utc}`")
    lines.append(f"- Overall status: **{overall_status}**")
    lines.append(
        f"- Build meta: version=`{meta['version']}` commit=`{meta['commit']}` dirty=`{meta['dirty']}` built_at=`{meta['built_at_utc']}`"
    )
    lines.append("")
    lines.append("## Artifacts Used")
    for path in artifacts:
        lines.append(f"- `{path}`")
    lines.append("")
    lines.append("## Aggregate Metrics (across selected runs)")
    lines.append("| Metric | Mean (ms) | p95 (ms) | Max (ms) |")
    lines.append("|---|---:|---:|---:|")
    for key in ("overall_max_hold_ms", "lemma_phase_max_hold_ms", "save_p95_ms", "save_max_ms"):
        agg = aggregates[key]
        lines.append(f"| `{key}` | {agg['mean']:.3f} | {agg['p95']:.3f} | {agg['max']:.3f} |")
    lines.append("")
    lines.append("## Budget Checks")
    lines.append("| Check | Value (ms) | PASS <= | WARN <= | Status |")
    lines.append("|---|---:|---:|---:|---|")
    for row in budget_rows:
        lines.append(
            f"| `{row['check']}` | {row['value_ms']:.3f} | {row['pass_limit_ms']:.3f} | {row['warn_limit_ms']:.3f} | **{row['status']}** |"
        )
    lines.append("")
    lines.append("Exit code mapping: `0=PASS`, `2=WARN`, `1=FAIL`.")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _print_console_summary(
    *,
    artifacts: list[Path],
    aggregates: dict[str, dict[str, float]],
    budget_rows: list[dict[str, Any]],
    overall_status: str,
) -> None:
    print("Write-gate budget checker")
    print(f"Selected artifacts ({len(artifacts)}):")
    for path in artifacts:
        print(f"  - {path}")

    print("Aggregate metrics (ms):")
    for key in ("overall_max_hold_ms", "lemma_phase_max_hold_ms", "save_p95_ms", "save_max_ms"):
        agg = aggregates[key]
        print(f"  {key}: mean={agg['mean']:.3f} p95={agg['p95']:.3f} max={agg['max']:.3f}")

    print("Budget checks:")
    for row in budget_rows:
        print(
            f"  {row['check']}: value={row['value_ms']:.3f} "
            f"pass<={row['pass_limit_ms']:.3f} warn<={row['warn_limit_ms']:.3f} => {row['status']}"
        )
    print(f"Overall status: {overall_status}")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", nargs="+", help="Explicit artifact paths.")
    parser.add_argument("--glob", dest="glob", default=None, help="Glob pattern for artifacts.")
    parser.add_argument("--dir", dest="dir", default=None, help="Directory to scan for artifacts.")
    parser.add_argument("--take", type=int, default=DEFAULT_TAKE, help="Use N most recent artifacts after sorting.")
    parser.add_argument(
        "--report-path",
        default=str(DEFAULT_REPORT_PATH),
        help=f"Markdown report output path (default: {DEFAULT_REPORT_PATH}).",
    )
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.glob is None and args.dir is None and not args.artifacts:
        args.dir = str(DEFAULT_SCAN_DIR)

    report_path = Path(args.report_path).expanduser().resolve()
    try:
        artifacts = _discover_artifacts(args)
        payloads = [_load_artifact(path) for path in artifacts]
        runs = [_extract_run_metrics(payload, artifact=path) for payload, path in zip(payloads, artifacts, strict=True)]
        aggregates = _aggregate(runs)
        budget_rows, overall_status = _evaluate_budget(aggregates)
        _write_markdown_report(
            report_path=report_path,
            artifacts=artifacts,
            aggregates=aggregates,
            budget_rows=budget_rows,
            overall_status=overall_status,
        )
        _print_console_summary(
            artifacts=artifacts,
            aggregates=aggregates,
            budget_rows=budget_rows,
            overall_status=overall_status,
        )
        print(f"Report: {report_path}")
        if overall_status == "PASS":
            return 0
        if overall_status == "WARN":
            return 2
        return 1
    except BudgetCheckError as exc:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            "# Write-Gate Budget Report\n\n"
            f"- Overall status: **FAIL**\n"
            f"- Error: `{exc}`\n",
            encoding="utf-8",
        )
        print(f"FAIL: {exc}", file=sys.stderr)
        print(f"Report: {report_path}", file=sys.stderr)
        return 1


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
