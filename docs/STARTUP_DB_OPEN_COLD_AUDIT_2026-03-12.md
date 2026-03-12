# Startup DB-Open Cold Audit (2026-03-12)

## Why this document exists

This is the first task-specific use of the canonical cold-audit framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

The goal of this wave is narrow:

- apply the framework to one real startup scenario;
- produce bounded evidence;
- decide whether a startup patch branch should open now.

This wave does **not**:

- change runtime behavior;
- reopen heavy validation;
- make reference-scale claims;
- claim full UI first-usable-state coverage.

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `S1` | CLI-selected startup DB-open probe | `J:\Project_Vibe\V_book\hdle_premium.db` | Smallest bounded live probe for Level 2/3/6 evidence | Completed |
| `S2` | Deferred startup on huge legacy settings DB | code + tests only | Confirms degraded/fallback startup contract remains honest | Completed |
| `S3` | UI first-render / first-usable-state after startup | not probed in this wave | Needed only if startup becomes a real blocker | Intentionally deferred |

## Evidence artifacts

- `build/logs/cold_audit/startup_db_open/startup_db_open_before.json`
- `build/logs/cold_audit/startup_db_open/startup_db_open_repeat.json`
- `build/logs/cold_audit/startup_db_open/startup_db_open_summary.json`
- `docs/DATABASE_SELECTION.md`
- `docs/PREMIUM_HEAVY_DB_STARTUP_AND_RELEASE_PLAN.md`
- `app/main.py`
- `app/infra/db_path_resolver.py`
- `tests/test_db_path_resolver.py`
- `tests/test_main_self_check_helpers.py`

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Startup DB-open and deferred-startup fallback were explicitly chosen as the current startup scenarios. | Completed |
| `2. Cold vs warm measurement` | Fresh-process `db_open` self-check on the repo-local DB measured `82 ms` first probe and `66 ms` repeat probe. | Completed |
| `3. Step-by-step cold breakdown` | The measured path is narrow: DB path resolution -> SQLite read-only open -> first project row -> first document row -> close. | Completed |
| `4. SQL-level timing / query audit` | No material SQL offender was exposed in this probe. The path uses only two bounded first-row reads. | Completed for this scenario |
| `5. Service/process timing` | `--self-check db_open` intentionally bypasses GUI import and most service initialization. This wave isolates DB-open, not full application startup. | Completed with bounded scope |
| `6. Filesystem / OS / DB-open audit` | The target DB exists, is `2,594,488,320` bytes, reports schema `41`, and the app supports schema `42`. No inspect error was reported. | Completed |
| `7. UI first-render / first-usable-state audit` | Not measured here. No UI startup timing claim is made from this wave. | Deferred behind new evidence gate |
| `8. Degraded / fallback mode audit` | Startup defer contract remains consistent: only `SETTINGS` may defer, while explicit `CLI` and `ENV` choices remain authoritative. | Completed |
| `9. Dataset-tier analysis` | Evidence in this wave is limited to the repo-local development DB. No approved reference-scale promotion is claimed. | Completed with explicit boundary |
| `10. Repeatability protocol` | Commands and artifacts below are sufficient to reproduce this bounded wave on the same local target. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `S1` and `S2` were explicitly named before interpretation. | Prevented ad hoc startup claims. |
| `B. Bounded live probes` | Two fresh-process `db_open` probes were collected on the local repo DB. | Enough evidence to clear DB-open on this target. |
| `C. SQL top offenders log` | No top-offender log was needed; the probe path is too small and did not reveal a dominant SQL layer. | SQL is not the active blocker here. |
| `D. UI responsiveness probes` | Not run in this wave. | UI startup remains a separate decision-gated layer. |
| `E. Service initialization audit` | The self-check path intentionally isolates DB-open from heavier startup work. | No service-init bottleneck is claimed or cleared globally. |
| `F. Drift / fallback path audit` | Code, docs, and tests agree on the defer contract for huge legacy settings DBs. | No drift-driven startup fix is needed now. |
| `G. Before/after evidence protocol` | This is a before-only baseline. No after artifact exists because no patch was justified. | Correctly keeps the branch in triage mode. |

## Startup-specific findings

### Local DB-open probe

- Probe target: `J:\Project_Vibe\V_book\hdle_premium.db`
- Probe mode: `python -m app.main --self-check db_open --db-path ...`
- First probe: `82 ms`
- Repeat probe: `66 ms`
- Sample reads succeeded for `project_id=1` and `doc_id=1`

This clears the narrow DB-open layer for the local repo DB target. It does **not**
prove full GUI startup time, first usable state, or reference-scale startup cost.

### Deferred-startup fallback contract

The defer logic in `app/infra/db_path_resolver.py` remains bounded and honest:

- explicit `CLI` and `ENV` DB choices are never overridden;
- only `SETTINGS` may defer;
- defer requires both an older schema and a DB at or above the `4 GiB` threshold;
- the deferred original path and reason are persisted for later reconnect.

Existing regression coverage already locks this in:

- `tests/test_db_path_resolver.py`
- `tests/test_main_self_check_helpers.py`

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- the measured DB-open path on the local repo DB is sub-`100 ms`;
- no dominant SQL offender was identified in this narrow probe;
- no degraded-path drift was found;
- UI first-usable-state was not measured, so no UI startup claim is justified yet.

## Decision gate for any future startup branch

Do **not** open a startup patch branch from this wave alone.

Open a new startup branch only if a new evidence gate is crossed by one of these:

- Level 7 evidence showing a real first-usable-state delay on a user-visible startup path;
- approved reference-scale startup evidence showing materially worse DB-open or service-init behavior;
- new degraded/fallback drift showing that the documented startup contract is no longer honest.

Until then:

- current startup DB-open triage is closed;
- next startup-related work is decision-gate triage only;
- no heavy startup branch reopens automatically.

## Repeatability commands

```powershell
New-Item -ItemType Directory -Force build\logs\cold_audit\startup_db_open | Out-Null
.\.venv\Scripts\python.exe -m app.main --self-check db_open --db-path "J:\Project_Vibe\V_book\hdle_premium.db" --self-check-out build\logs\cold_audit\startup_db_open\startup_db_open_before.json
.\.venv\Scripts\python.exe -m app.main --self-check db_open --db-path "J:\Project_Vibe\V_book\hdle_premium.db" --self-check-out build\logs\cold_audit\startup_db_open\startup_db_open_repeat.json
.\.venv\Scripts\python.exe -m pytest tests\test_db_path_resolver.py tests\test_main_self_check_helpers.py -q
```
