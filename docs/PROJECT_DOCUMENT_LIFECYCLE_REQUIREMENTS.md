# Project/Document Lifecycle Requirements (Premium)

## Context

Observed production bug: after deleting projects and creating new ones, reopening a reused `project_id` showed stale project title and stale document list from a previously deleted project.

Root cause confirmed in code:

- `AppWindow` kept cached `ProjectView` instances keyed only by `project_id`.
- SQLite can reuse numeric IDs after deletions (no `AUTOINCREMENT` contract in current schema).
- Reopening the same numeric ID reused stale in-memory UI state.

## Scope

- Project lifecycle in runtime UI: create, open, delete, reopen, recreate with reused ID.
- Document lifecycle visibility inside project tabs after project deletion/recreation.
- Runtime context consistency: current project, recent projects, workspace-bound widgets.

Out of scope:

- Schema migration to force monotonic never-reused IDs.
- Cross-process synchronization (external DB mutations while app is running).

## Functional Requirements

### FR-01: DB is Source of Truth

- Project identity in UI must be validated against DB before reusing cached project-scoped widgets.
- Identity key: `(project_id, created_at)`.

### FR-02: Safe Cache Reuse

- Reuse cached `ProjectView` only when `created_at` matches current DB row for the same `project_id`.
- On mismatch, cached project-scoped runtime widgets must be discarded and recreated.

### FR-03: Delete Invalidation Contract

- On successful project deletion, UI must emit a deletion event with deleted `project_id`.
- App runtime must invalidate all open widgets bound to this `project_id` (project view and other project-scoped workspaces).

### FR-04: Context Cleanup

- When a project is deleted, current project context for this ID must be cleared.
- Deleted project ID must be removed from recent-projects state.

### FR-05: Reopen Correctness

- Reopening a recreated project with the same numeric ID must display current DB name and current DB documents only.
- No stale project title, no stale document table rows from deleted entity.

### FR-06: Dashboard Contract

- `ProjectDashboard` must provide deterministic lifecycle signal:
  - `project_deleted(project_id)` on successful deletion.

## Non-Functional Requirements

- UI responsiveness: invalidation and reopen operations run in UI-safe lightweight code paths.
- WAL safety unchanged: no long DB write transactions introduced by this fix.
- Regression safety: targeted UI-contract tests must cover deletion signal and stale cache invalidation.

## Preconditions Checklist

- DB path resolution is deterministic (`--db-path`, env, settings, default) per `docs/DATABASE_SELECTION.md`.
- Project deletion path is `ProjectDashboard -> ProjectDeleteWorker -> ProjectService.delete_project`.
- Document deletion path remains `DocumentsView -> IngestService` (unchanged in this patch).
- Existing tests for workspace navigation and delete flow are executable in CI/local pytest.

## Test Plan (Required)

Automated:

1. `tests/test_project_delete_flow.py`
   - Ensure successful delete refreshes dashboard.
   - Ensure `project_deleted` signal is emitted with deleted ID.
2. `tests/test_workspace_app_window_contract.py`
   - Ensure stale cached `ProjectView` is recreated when identity token changes.
   - Ensure deletion invalidates runtime state and recent-project list.

Manual smoke:

1. Start app with target DB:
   - `python -m app.main --db-path "<path-to-db>"`
2. Create project A (ID N), import one document, open project, confirm title/docs.
3. Delete project A from dashboard.
4. Create project B that receives same ID N.
5. Open project B:
   - Expected: title = project B name.
   - Expected: documents list reflects project B only.

## Definition of Done

- No stale UI state when `project_id` is reused.
- Deletion event clears runtime caches/context for deleted ID.
- Targeted regression tests pass.
- No schema migration required.
- No changes to WAL/retry policy behavior.

