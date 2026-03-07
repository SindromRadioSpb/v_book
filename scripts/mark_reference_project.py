"""PERF-SCALE PATCH-A utility: mark/unmark a project as a reference project.

Usage examples
--------------
Mark project 1 as reference, pointing to an external DB:
    python scripts/mark_reference_project.py \\
        --db-path hdle_premium.db \\
        --project-id 1 \\
        --ref-db-path "J:/Project_Vibe/hewiki_gpu_processing.db"

Unmark project 1 (back to normal writable project):
    python scripts/mark_reference_project.py \\
        --db-path hdle_premium.db \\
        --project-id 1 \\
        --unmark

List all reference projects in the DB:
    python scripts/mark_reference_project.py \\
        --db-path hdle_premium.db \\
        --list
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def _open(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def cmd_mark(conn: sqlite3.Connection, project_id: int, ref_db_path: str) -> None:
    ref_path = Path(ref_db_path)
    if not ref_path.exists():
        print(f"WARNING: ref-db-path does not exist yet: {ref_path}", file=sys.stderr)

    cur = conn.execute(
        "SELECT project_id, name FROM dict_project WHERE project_id = ?", (project_id,)
    )
    row = cur.fetchone()
    if not row:
        print(f"ERROR: project {project_id} not found.", file=sys.stderr)
        sys.exit(1)

    conn.execute(
        "UPDATE dict_project SET is_reference = 1, ref_db_path = ? "
        "WHERE project_id = ?",
        (str(ref_path), project_id),
    )
    conn.commit()
    print(f"[OK] Project {project_id} '{row[1]}' marked as reference.")
    print(f"     ref_db_path = {ref_path}")


def cmd_unmark(conn: sqlite3.Connection, project_id: int) -> None:
    cur = conn.execute(
        "SELECT project_id, name FROM dict_project WHERE project_id = ?", (project_id,)
    )
    row = cur.fetchone()
    if not row:
        print(f"ERROR: project {project_id} not found.", file=sys.stderr)
        sys.exit(1)

    conn.execute(
        "UPDATE dict_project SET is_reference = 0, ref_db_path = NULL "
        "WHERE project_id = ?",
        (project_id,),
    )
    conn.commit()
    print(f"[OK] Project {project_id} '{row[1]}' unmarked (back to normal writable project).")


def cmd_list(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT project_id, name, is_reference, ref_db_path "
        "FROM dict_project ORDER BY project_id"
    ).fetchall()
    if not rows:
        print("No projects found.")
        return

    ref_count = sum(1 for r in rows if r[2])
    print(f"{'ID':>6}  {'is_ref':>6}  {'name':<40}  ref_db_path")
    print("-" * 90)
    for pid, name, is_ref, ref_path in rows:
        flag = "YES" if is_ref else "-"
        ref_disp = ref_path or ""
        print(f"{pid:>6}  {flag:>6}  {name:<40}  {ref_disp}")
    print(f"\n{len(rows)} project(s), {ref_count} reference project(s).")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mark/unmark reference projects (PERF-SCALE PATCH-A)"
    )
    parser.add_argument(
        "--db-path",
        required=True,
        help="Path to the main HDLE Premium SQLite database",
    )
    parser.add_argument("--project-id", type=int, help="Project ID to modify")
    parser.add_argument(
        "--ref-db-path",
        help="Absolute path to the external read-only reference DB file",
    )
    parser.add_argument(
        "--unmark",
        action="store_true",
        help="Remove reference flag from the project",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all projects and their reference status",
    )
    args = parser.parse_args()

    db = Path(args.db_path)
    if not db.exists():
        print(f"ERROR: database not found: {db}", file=sys.stderr)
        sys.exit(1)

    conn = _open(str(db))
    try:
        if args.list:
            cmd_list(conn)
        elif args.unmark:
            if not args.project_id:
                print("ERROR: --project-id required with --unmark", file=sys.stderr)
                sys.exit(1)
            cmd_unmark(conn, args.project_id)
        elif args.project_id and args.ref_db_path:
            cmd_mark(conn, args.project_id, args.ref_db_path)
        else:
            parser.print_help()
            sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
