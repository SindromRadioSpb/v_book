#!/usr/bin/env python3
"""Deterministic checker for pipeline stage budget contract (PATCH-06)."""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_REPORT_PATH = REPO_ROOT / "build" / "logs" / "pipeline_budget_report_latest.md"
DEFAULT_SCAN_DIR = REPO_ROOT / "build" / "logs"
DEFAULT_GLOB = "pipeline_bench_metrics_*.json"
DEFAULT_TAKE = 20

FILENAME_RE = re.compile(r"^pipeline_bench_metrics_(\d{8}_\d{6})\.json$")


class BudgetCheckError(RuntimeError):
    """Raised when checker input/parsing is invalid."""


def _ms(seconds: float) -> float:
    return float(seconds) * 1000.0


BASELINE = {
    "extract_terms": {
        "duration_ms": _ms(100.075),
        "throughput": 106.73,
        "processed": 10681,
    },
    "niqqud_bootstrap": {
        "duration_ms": _ms(120.565),
        "throughput": 16.59,
        "processed": 2000,
    },
    "translate_bootstrap": {
        "duration_ms": _ms(975.312),
        "throughput": 0.06,
        "processed": 60,
    },
    "tts_bootstrap": {
        "deferred": True,
        "reason": "Baseline deferred by operator (cost-risk); stage is not evaluated by default.",
    },
}


def _duration_limits(stage: str) -> tuple[float, float]:
    base = float(BASELINE[stage]["duration_ms"])
    return base * 1.30, base * 1.60


def _throughput_limits(stage: str) -> tuple[float, float]:
    base = float(BASELINE[stage]["throughput"])
    return base * 0.80, base * 0.60


def _processed_limits(stage: str) -> tuple[float, float]:
    base = float(BASELINE[stage]["processed"])
    return base * 0.90, base * 0.70


def _parse_timestamp_from_name(path: Path) -> dt.datetime:
    match = FILENAME_RE.match(path.name)
    if not match:
        raise BudgetCheckError(f"Filename does not match expected pattern: {path.name}")
    token = match.group(1)
    try:
        return dt.datetime.strptime(token, "%Y%m%d_%H%M%S")
    except ValueError as exc:
        raise BudgetCheckError(f"Filename timestamp parse failed for {path.name}: {exc}") from exc


def _sort_artifacts(paths: list[Path]) -> list[Path]:
    return sorted(paths, key=lambda p: (_parse_timestamp_from_name(p), p.name))


def _discover_artifacts(args: argparse.Namespace) -> list[Path]:
    if args.artifacts:
        candidates = [Path(x).expanduser().resolve() for x in args.artifacts]
    elif args.glob:
        candidates = [Path(x).resolve() for x in glob.glob(args.glob)]
    else:
        scan_dir = Path(args.dir).expanduser().resolve()
        candidates = list(scan_dir.glob(DEFAULT_GLOB))

    if not candidates:
        raise BudgetCheckError("No artifacts found for pipeline stage budget check.")

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


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return default


def _safe_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return default


def _sum_rows(rows: dict[str, Any] | None) -> int:
    if not isinstance(rows, dict):
        return 0
    total = 0
    for value in rows.values():
        total += max(0, _safe_int(value))
    return total


def _success_count(stage: dict[str, Any], processed_count: int, errors_count: int) -> int:
    details = stage.get("details")
    if isinstance(details, dict):
        succeeded_total = 0
        has_succeeded_field = False
        for block in details.values():
            if isinstance(block, dict) and "succeeded" in block:
                has_succeeded_field = True
                succeeded_total += max(0, _safe_int(block.get("succeeded")))
        if has_succeeded_field:
            return succeeded_total
    return max(0, processed_count - errors_count)


def _extract_stage_snapshot(payload: dict[str, Any], artifact: Path) -> dict[str, Any]:
    stages = payload.get("stages")
    if not isinstance(stages, list) or not stages:
        raise BudgetCheckError(f"Missing stages in {artifact}")
    stage = stages[0]
    if not isinstance(stage, dict):
        raise BudgetCheckError(f"Invalid stage payload in {artifact}")

    stage_name = str(stage.get("name") or "").strip()
    if not stage_name:
        raise BudgetCheckError(f"Missing stage name in {artifact}")

    duration_sec = _safe_float(stage.get("duration_sec"))
    duration_ms = _ms(duration_sec)
    rows_processed = (
        stage.get("rows_processed") if isinstance(stage.get("rows_processed"), dict) else {}
    )
    processed_count = _sum_rows(rows_processed)
    errors_count = max(0, _safe_int(stage.get("errors_count")))
    success_count = _success_count(stage, processed_count, errors_count)
    throughput = (processed_count / duration_sec) if duration_sec > 0 else 0.0
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    overwrite = _safe_int(
        stage.get("overwrite"), default=_safe_int(config.get("overwrite"), default=0)
    )

    details = stage.get("details") if isinstance(stage.get("details"), dict) else {}
    retry_count = 0
    rate_limit_hits = 0
    api_calls_count = 0
    avg_items_per_request = 0.0

    if stage_name == "translate_bootstrap":
        for scope in ("lemma", "term", "sentence"):
            block = details.get(scope)
            if isinstance(block, dict):
                retry_count += max(0, _safe_int(block.get("retry_count")))
                rate_limit_hits += max(0, _safe_int(block.get("rate_limit_hits")))
                api_calls_count += max(
                    0,
                    _safe_int(block.get("api_calls_count"), default=_safe_int(block.get("total"))),
                )

    gate_trace = payload.get("gate_trace") if isinstance(payload.get("gate_trace"), dict) else {}
    write_gate_overall_max_hold_ms = (
        _safe_float(gate_trace.get("max_hold_ms"), default=0.0) if gate_trace else None
    )
    write_gate_overall_p95_hold_ms = (
        _safe_float(gate_trace.get("p95_hold_ms"), default=0.0) if gate_trace else None
    )
    write_gate_wait_ms = (
        _safe_float(gate_trace.get("total_wait_ms"), default=0.0) if gate_trace else None
    )

    db_info = payload.get("db") if isinstance(payload.get("db"), dict) else {}
    db_paths = {
        "source_db": str(db_info.get("source_db") or ""),
        "base_sandbox_db": str(db_info.get("base_sandbox_db") or ""),
        "working_db": str(db_info.get("working_db") or ""),
    }

    error_samples = stage.get("error_samples")
    if not isinstance(error_samples, list):
        error_samples = []
    error_samples = error_samples[:5]

    return {
        "stage_name": stage_name,
        "artifact": str(artifact),
        "duration_ms": duration_ms,
        "throughput_rows_per_sec": throughput,
        "processed_count": processed_count,
        "success_count": success_count,
        "error_count": errors_count,
        "overwrite_mode": overwrite,
        "rows_processed": rows_processed,
        "chunk_size": _safe_int(config.get("pron_chunk_size"), default=0)
        or _safe_int(config.get("sentence_chunk_size"), default=0),
        "batch_size": _safe_int(config.get("tts_commit_chunk"), default=0),
        "retry_count": retry_count,
        "rate_limit_hits": rate_limit_hits,
        "api_calls_count": api_calls_count,
        "avg_items_per_request": avg_items_per_request,
        "write_gate_overall_max_hold_ms": write_gate_overall_max_hold_ms,
        "write_gate_overall_p95_hold_ms": write_gate_overall_p95_hold_ms,
        "write_gate_wait_ms": write_gate_wait_ms,
        "error_samples": error_samples,
        "db_paths": db_paths,
        "stage_status_raw": str(stage.get("status") or ""),
        "overall_status_raw": str(payload.get("overall_status") or ""),
    }


def _classify_upper_is_bad(value: float, pass_limit: float, warn_limit: float) -> str:
    if value <= pass_limit:
        return "PASS"
    if value <= warn_limit:
        return "WARN"
    return "FAIL"


def _classify_lower_is_bad(value: float, pass_floor: float, warn_floor: float) -> str:
    if value >= pass_floor:
        return "PASS"
    if value >= warn_floor:
        return "WARN"
    return "FAIL"


def _worst_status(statuses: list[str]) -> str:
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    return "PASS"


def _evaluate_required_stage(stage_name: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    pass_duration, warn_duration = _duration_limits(stage_name)
    pass_throughput, warn_throughput = _throughput_limits(stage_name)
    pass_processed, warn_processed = _processed_limits(stage_name)

    checks: list[dict[str, Any]] = []
    checks.append(
        {
            "metric": "total_duration_ms",
            "observed": float(snapshot["duration_ms"]),
            "pass_threshold": pass_duration,
            "warn_threshold": warn_duration,
            "status": _classify_upper_is_bad(
                float(snapshot["duration_ms"]), pass_duration, warn_duration
            ),
        }
    )
    checks.append(
        {
            "metric": "throughput_rows_per_sec",
            "observed": float(snapshot["throughput_rows_per_sec"]),
            "pass_threshold": pass_throughput,
            "warn_threshold": warn_throughput,
            "status": _classify_lower_is_bad(
                float(snapshot["throughput_rows_per_sec"]), pass_throughput, warn_throughput
            ),
        }
    )
    checks.append(
        {
            "metric": "processed_count",
            "observed": int(snapshot["processed_count"]),
            "pass_threshold": pass_processed,
            "warn_threshold": warn_processed,
            "status": _classify_lower_is_bad(
                float(snapshot["processed_count"]), pass_processed, warn_processed
            ),
        }
    )
    checks.append(
        {
            "metric": "error_count",
            "observed": int(snapshot["error_count"]),
            "pass_threshold": 0,
            "warn_threshold": 0,
            "status": "PASS" if int(snapshot["error_count"]) == 0 else "FAIL",
        }
    )

    raw_statuses = [
        "PASS" if snapshot["stage_status_raw"] == "ok" else "FAIL",
        "PASS" if snapshot["overall_status_raw"] == "pass" else "FAIL",
    ]
    if any(path.upper().startswith("M:\\") for path in snapshot["db_paths"].values() if path):
        raw_statuses.append("FAIL")

    check_statuses = [str(item["status"]) for item in checks] + raw_statuses
    stage_status = _worst_status(check_statuses)

    return {
        "stage_name": stage_name,
        "status": stage_status,
        "checks": checks,
        "snapshot": snapshot,
        "deferred": False,
        "reason": "",
    }


def _evaluate_deferred_stage(stage_name: str, snapshot: dict[str, Any] | None) -> dict[str, Any]:
    reason = str(BASELINE[stage_name].get("reason") or "Deferred stage.")
    return {
        "stage_name": stage_name,
        "status": "DEFERRED",
        "checks": [],
        "snapshot": snapshot,
        "deferred": True,
        "reason": reason,
    }


def _evaluate_pipeline(
    artifacts: list[Path], payloads: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str, list[Path]]:
    snapshots = [
        _extract_stage_snapshot(payload, artifact)
        for payload, artifact in zip(payloads, artifacts, strict=True)
    ]

    latest_by_stage: dict[str, dict[str, Any]] = {}
    for snap in snapshots:
        latest_by_stage[snap["stage_name"]] = snap

    evaluated_rows: list[dict[str, Any]] = []
    used_artifacts: list[Path] = []

    required_stages = ("extract_terms", "niqqud_bootstrap", "translate_bootstrap")
    for stage_name in required_stages:
        if stage_name not in latest_by_stage:
            row = {
                "stage_name": stage_name,
                "status": "FAIL",
                "checks": [],
                "snapshot": None,
                "deferred": False,
                "reason": "Required stage artifact not found in selected set.",
            }
            evaluated_rows.append(row)
            continue
        snap = latest_by_stage[stage_name]
        used_artifacts.append(Path(snap["artifact"]))
        evaluated_rows.append(_evaluate_required_stage(stage_name, snap))

    deferred_stage = "tts_bootstrap"
    deferred_snapshot = latest_by_stage.get(deferred_stage)
    if deferred_snapshot is not None:
        used_artifacts.append(Path(deferred_snapshot["artifact"]))
    evaluated_rows.append(_evaluate_deferred_stage(deferred_stage, deferred_snapshot))

    overall = "PASS"
    for row in evaluated_rows:
        if row["deferred"]:
            continue
        if row["status"] == "FAIL":
            overall = "FAIL"
            break
        if row["status"] == "WARN" and overall != "FAIL":
            overall = "WARN"
    return evaluated_rows, overall, _sort_artifacts(list({p.resolve() for p in used_artifacts}))


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
    selected_artifacts: list[Path],
    stage_rows: list[dict[str, Any]],
    overall_status: str,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    meta = _load_build_meta()
    now_utc = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")

    lines: list[str] = []
    lines.append("# Pipeline Stage Budget Report")
    lines.append("")
    lines.append(f"- Timestamp (UTC): `{now_utc}`")
    lines.append(f"- Overall status: **{overall_status}**")
    lines.append(
        f"- Build meta: version=`{meta['version']}` commit=`{meta['commit']}` dirty=`{meta['dirty']}` built_at=`{meta['built_at_utc']}`"
    )
    lines.append("")
    lines.append("## Artifacts Considered")
    for path in selected_artifacts:
        lines.append(f"- `{path}`")
    lines.append("")
    lines.append("## Stage Results")
    lines.append("")
    for row in stage_rows:
        stage_name = row["stage_name"]
        lines.append(f"### `{stage_name}`")
        lines.append("")
        lines.append(f"- Status: **{row['status']}**")
        if row["deferred"]:
            lines.append(f"- Reason: {row['reason']}")
            lines.append("")
            continue

        snapshot = row["snapshot"] or {}
        lines.append(f"- Artifact: `{snapshot.get('artifact', '')}`")
        lines.append(f"- Processed: `{snapshot.get('processed_count', 0)}`")
        lines.append(f"- Success: `{snapshot.get('success_count', 0)}`")
        lines.append(f"- Errors: `{snapshot.get('error_count', 0)}`")
        lines.append(f"- Overwrite mode: `{snapshot.get('overwrite_mode', 0)}`")
        lines.append(
            f"- Throughput rows/sec: `{float(snapshot.get('throughput_rows_per_sec', 0.0)):.4f}`"
        )
        lines.append(f"- Duration ms: `{float(snapshot.get('duration_ms', 0.0)):.3f}`")
        lines.append("")
        lines.append("| Metric | Observed | PASS | WARN | Status |")
        lines.append("|---|---:|---:|---:|---|")
        for check in row["checks"]:
            lines.append(
                f"| `{check['metric']}` | {float(check['observed']):.4f} | "
                f"{float(check['pass_threshold']):.4f} | {float(check['warn_threshold']):.4f} | **{check['status']}** |"
            )
        lines.append("")
        lines.append(
            f"- first_error_samples: `{json.dumps(snapshot.get('error_samples', [])[:5], ensure_ascii=False)}`"
        )
        lines.append("")

    lines.append("Exit code mapping: `0=PASS`, `2=WARN`, `1=FAIL`.")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _print_console_summary(
    *, stage_rows: list[dict[str, Any]], overall_status: str, report_path: Path
) -> None:
    print("Pipeline stage budget checker")
    for row in stage_rows:
        if row["deferred"]:
            print(f"  {row['stage_name']}: DEFERRED ({row['reason']})")
            continue
        snap = row["snapshot"] or {}
        print(
            f"  {row['stage_name']}: {row['status']} "
            f"(processed={snap.get('processed_count', 0)}, errors={snap.get('error_count', 0)}, "
            f"duration_ms={float(snap.get('duration_ms', 0.0)):.3f}, throughput={float(snap.get('throughput_rows_per_sec', 0.0)):.4f})"
        )
    print(f"Overall status: {overall_status}")
    print(f"Report: {report_path}")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", nargs="+", help="Explicit artifact paths.")
    parser.add_argument("--glob", dest="glob", default=None, help="Glob pattern for artifacts.")
    parser.add_argument("--dir", dest="dir", default=None, help="Directory to scan for artifacts.")
    parser.add_argument(
        "--take", type=int, default=DEFAULT_TAKE, help="Use N most recent artifacts after sorting."
    )
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
        stage_rows, overall_status, used_artifacts = _evaluate_pipeline(artifacts, payloads)
        _write_markdown_report(
            report_path=report_path,
            selected_artifacts=used_artifacts,
            stage_rows=stage_rows,
            overall_status=overall_status,
        )
        _print_console_summary(
            stage_rows=stage_rows, overall_status=overall_status, report_path=report_path
        )
        if overall_status == "PASS":
            return 0
        if overall_status == "WARN":
            return 2
        return 1
    except BudgetCheckError as exc:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            "# Pipeline Stage Budget Report\n\n"
            "- Overall status: **FAIL**\n"
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
