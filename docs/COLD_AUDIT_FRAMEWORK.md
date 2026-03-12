# Cold Audit Framework

Status date: `2026-03-12`

## Purpose

This document is the canonical repository contract for **cold-audit** work in
HDLE Premium / V_book.

Use it to:

- define cold-audit terminology once;
- standardize how cold evidence is collected and compared;
- decide which cold bottlenecks deserve a bounded engineering patch;
- keep heavy branches closed until a real evidence gate is crossed.

Non-goals of this document:

- it does not approve a new runtime patch by itself;
- it does not reopen deferred heavy validation;
- it does not replace task-specific implementation plans or operator runbooks.

## Current repository context

The following performance/safety waves are already closed for the current
branch:

- snapshot readiness / governance acceleration;
- narrow governance lemma patch;
- telemetry retention apply validation;
- disposable-clone housekeeping and roadmap handoff.

The next active layer is **not** a new runtime patch. The next active layer is
evidence-first cold-audit triage using the framework below.

## Canonical document roles

- `docs/COLD_AUDIT_FRAMEWORK.md`
  - canonical cold-audit terminology, levels, research matrix, prioritization,
    and repo contract.
- `docs/ENGINEERING_CONTROL_OPTIMIZATION_ROADMAP_2026-03-11.md`
  - current engineering roadmap, active layer, and closure / handoff state.
- `docs/PROJECT_DATA_CACHE_LIFECYCLE_CONTRACT.md`
  - lifecycle and operator-safety contract for project-owned heavy data.
- `docs/TASK30_IMPLEMENTATION_PLAN_2026-03-09.md`
  - task-specific historical implementation and evidence ledger for the current
    branch.
- `docs/REFERENCE_PROJECT_GUIDE.md`
  - operator guidance for reference-project workflows.
- `docs/NLP_SNAPSHOT_BACKFILL_DECISION_GATE.md`
  - dedicated example of a heavy-branch decision gate.

The following documents remain useful evidence and historical context, but they
are **not** the canonical framework source:

- `docs/PERF_IMPLEMENTATION_AUDIT.md`
- `docs/PERF_SCALE_AUDIT_HEWIKI_2026-03-07.md`
- `docs/PERF_HARNESS.md`

## Glossary

| Term | Meaning |
|---|---|
| `cold governance` | The first governance summary/load for a surface after process start or fresh DB attach, before service reuse or warmed state helps. |
| `cold-path` | The first execution path of a scenario before relevant caches, initialized services, or warmed DB state are reused. |
| `cold bottleneck` | The dominant cold-path cost component that materially delays a real user-visible or operator-visible scenario. |
| `cold bottleneck layer` | A structural layer where a dominant cold cost can sit: DB-open, SQL/query, service init, UI first render, filesystem/OS, degraded path, or fallback path. |
| `cold breakdown` | A measured stage-by-stage attribution of one cold scenario into named sub-steps with timings and evidence artifacts. |
| `cold readiness` | The first readiness summary or readiness surface load with no warmed per-process state. |
| `cold load` | The first user-visible load of a view, dialog, service, or workflow on a fresh process or fresh target DB. |
| `cold-tail` | Residual cold-only latency left after the dominant blocker is removed. Track it, but do not auto-promote it to a new patch. |
| `warm path` | A repeated execution in the same process after relevant state is already initialized, cached, or otherwise reused. |
| `degraded mode` | An explicit reduced-contract state where the preferred fast/full path is unavailable but the surface remains usable and honest. |
| `fallback path` | A deliberate alternative path used when the preferred path is unavailable, too risky, or outside the current contract. |
| `decision gate` | An explicit evidence-backed checkpoint that must be crossed before opening a heavy, risky, or previously deferred branch. |
| `evidence-first patch` | A bounded patch opened only after measured evidence identifies a real bottleneck, shows its layer, and justifies scope. |
| `blocker vs not blocker` | A blocker materially harms a current real workflow or breaches an accepted budget/decision gate. Not-blocker means the cost is real but currently acceptable, secondary, or deferred. |

## Cold-Audit Program Levels

Run the lowest sufficient level set first. Do not jump to high-cost or heavy
validation levels if Levels 1-4 already show that the current branch is not a
blocker.

| Level | Goal | What to measure | Evidence / logs | Risks caught | Mandatory when / Optional when |
|---|---|---|---|---|---|
| `1. Inventory user-visible cold scenarios` | Define what "cold" means for the current branch. | First open, first summary, first search, first dialog, first DB attach, first operator command. | Scenario list in roadmap/task doc, with exact target DB/profile. | Solving a non-scenario, mixing operator-only and user-critical paths, vague scope. | Mandatory for every new cold branch. Never optional. |
| `2. Cold vs warm measurement` | Separate true cold cost from repeat-call cost. | Cold run, warm run, repeated run deltas. | Before/after JSON timings, harness output, manual timestamps if no harness exists. | Mistaking warm reuse wins for cold fixes; over-scoping speculative work. | Mandatory before opening a performance patch. Optional only for docs-only historical alignment. |
| `3. Step-by-step cold breakdown` | Find the dominant sub-step inside one cold scenario. | Named stages and elapsed time per stage. | Breakdown JSON/MD, stage logs, per-step timings. | Patching the wrong layer, hiding the real dominant offender. | Mandatory when Level 2 shows material cold cost. Optional for tiny tails. |
| `4. SQL-level timing / query audit` | Prove or clear the SQL/query layer. | Query timings, counts, plan quality, repeat offenders. | Query-plan audit, SQL timing log, top-offender list. | Blaming UI/service layers for DB scan/sort issues; missing full-table counts or temp b-tree costs. | Mandatory for DB-backed cold scenarios. Optional for pure UI/service init cases. |
| `5. Service/process timing` | Attribute non-SQL cost in service construction and orchestration. | Service init time, helper creation, DTO build, mapping, aggregation overhead. | Service timing log, breakdown stage notes. | Hidden service-layer waste after SQL is fixed; repeated initialization churn. | Mandatory when SQL is not the dominant offender. Optional if Level 4 already proves the blocker. |
| `6. Filesystem / OS / DB-open audit` | Measure cold costs before normal service work starts. | DB open, SQLite health probe, WAL state, file access, process start, path resolution. | DB-open self-check JSON, startup/open logs, filesystem notes. | Misclassifying open/probe cost as application logic; path/profile mistakes. | Mandatory for startup/open/attach scenarios. Optional for already-open in-process flows. |
| `7. UI first-render / first-usable-state audit` | Measure what the user actually waits for. | First paint, first usable state, stale-data hold, background refresh completion. | UI smoke notes, manual probe timestamps, screenshots if needed. | "Backend fixed" while UI still feels frozen; first-usable-state hidden by staged work. | Mandatory for dialogs/views. Optional for CLI-only or non-visual paths. |
| `8. Degraded / fallback mode audit` | Verify how the product behaves when the preferred path is unavailable or intentionally deferred. | Triggered degraded state, fallback path cost, user-visible messaging, honesty of the contract. | Degraded/fallback evidence note, operator screenshots/logs, branch docs. | Silent contract drift, misleading UX, accidental reopening of deferred paths. | Mandatory if degraded/fallback behavior exists. Optional only when there is no alternative path. |
| `9. Dataset-tier analysis` | Check whether the cold issue is structural across sizes or specific to one scale tier. | Small/dev, approved dev/test, reference-scale, disposable clone tiers. | Tier comparison table, evidence pack per tier. | Overfitting to one DB copy, missing scale breakpoints, unsafe generalization. | Mandatory before promoting a fix from local/dev evidence to reference-scale claims. Optional for clearly local-only tooling. |
| `10. Repeatability protocol` | Ensure the finding is reproducible and comparable over time. | Same command, same target, same scenario, same artifact naming, same decision note. | Re-runnable command block, summary artifact, closure/open marker. | One-off measurements, irreproducible claims, impossible before/after comparisons. | Mandatory for any evidence used in roadmap prioritization or decision-gate work. Never optional once a branch becomes official. |

## Test and Research Matrix A-G

| Block | Why it exists | Inputs / expected artifacts | Engineering-significant result | How prioritization uses it |
|---|---|---|---|---|
| `A. Scenario matrix` | Keeps cold work tied to real user/operator scenarios instead of generic "performance". | Scenario list, target DB/profile, current budget or no-budget note. | One clear scenario is confirmed as current focus and is reproducible. | Decides whether there is a real branch to open at all. |
| `B. Bounded live probes` | Produces safe real-world evidence without jumping into heavy/full-volume validation. | Safe target, bounded command, probe JSON/MD, run notes. | Real-db evidence exists without widening the branch or mutating protected targets. | Promotes a local suspicion into a repo-level finding. |
| `C. SQL top offenders log` | Makes dominant DB/query costs explicit. | Query timing list, plan notes, row counts, exact SQL if needed. | One or two offenders dominate instead of diffuse noise. | Determines whether the next patch is SQL/index/aggregation work or not. |
| `D. UI responsiveness probes` | Keeps first-usable-state honest. | Manual timestamps, UI smoke notes, screenshots only if needed. | The user-visible wait point is known and matches or disproves backend timings. | Prevents backend-only prioritization mistakes. |
| `E. Service initialization audit` | Exposes non-query cold work hidden in service/process setup. | Service timing logs, init sequence notes, object creation timings. | Service init is either cleared or confirmed as a structural layer. | Avoids over-investing in SQL fixes when the remaining cost is elsewhere. |
| `F. Drift / fallback path audit` | Checks that the documented contract still matches real runtime behavior. | Degraded/fallback notes, hold-state docs, operator guidance, current evidence. | Deferred branches stay closed and fallback/degraded behavior remains explicit. | Decides whether a new evidence gate is required before any branch reopens. |
| `G. Before/after evidence protocol` | Makes patch effect comparable and reviewable. | Before artifact, after artifact, unchanged target note, summary artifact. | A claimed improvement or closure is backed by like-for-like evidence. | Required to close one layer and promote the next layer. |

## Prioritization Model

### Inputs

Rank cold findings with these inputs together, not by raw milliseconds alone:

| Input | Question |
|---|---|
| `user impact` | Does the cold cost block a real user-visible or operator-critical workflow? |
| `absolute cold cost` | How much wall time does the cold scenario cost before the surface becomes usable or trustworthy? |
| `structural nature` | Is the cause structural and likely to recur across datasets, or is it isolated/noisy? |
| `fix risk / complexity` | Can the branch stay bounded and operator-safe, or would it reopen a risky/heavy branch? |

### Recommended ranking model

Use this decision order:

1. Confirm there is a real scenario and a reproducible cold cost.
2. Identify the dominant cold bottleneck layer.
3. Classify whether it is a current blocker, residual tail, polish item, or deferred track.
4. Open a bounded patch only if the branch can stay evidence-first and operator-safe.

### Priority classes

| Class | Meaning | Typical action |
|---|---|---|
| `P0` | Current blocker. Real workflow harm, accepted budget breach, or decision-gate blocker with a bounded fix path. | Open a bounded patch next. |
| `P1` | High-value but not blocking. Material cold cost with strong evidence and moderate fix risk. | Queue after current blocker closes. |
| `P2` | Residual tail. Visible but secondary after dominant blocker removal, or occasional operator cost. | Track only if it stays material after P0/P1 work. |
| `P3` | Polish or deferred. Small tail, speculative improvement, or high-risk branch without evidence. | Do not open now. Keep documented only. |

### Blocker logic

A finding is a **blocker** only if at least one of these is true:

- it materially harms a current user-visible or operator-visible workflow;
- it breaches an existing accepted SLO/budget;
- it blocks an approved decision gate or safe operator action;
- it is the dominant cold bottleneck in the current active layer.

A finding is **not a blocker** if:

- it is only a residual cold-tail after the main blocker is removed;
- it affects an occasional operator path that remains acceptable;
- it is only warm-path noise;
- the evidence is incomplete or not yet repeatable.

### Residual tail vs polish vs deferred

- `residual tail`
  - real cold cost remains, but the dominant blocker is already removed.
- `polish`
  - measurable but low-impact improvement with no current workflow harm.
- `deferred`
  - structurally interesting, but the branch is risky, heavy, or outside the
    current decision gate.

### Decision logic

Open a new patch only when all of the following are true:

- a reproducible cold scenario exists;
- the dominant layer is identified;
- before evidence exists;
- the branch can stay bounded;
- the patch does not reopen a closed heavy branch without a new decision gate.

Do **not** touch the problem when:

- current evidence only shows residual tail or polish;
- the fix would be broader than the proven problem;
- historical evidence is being re-litigated without a new scenario;
- the branch would reopen protected/heavy work without approval.

A **new evidence gate** is required when:

- a deferred heavy branch may be reopened;
- a protected target may be written;
- a full-volume validation is being considered;
- a change alters write semantics, resume semantics, or safety contracts.

Heavy branches remain closed when:

- the current layer is not a blocker;
- safe bounded evidence already answered the current question;
- the remaining uncertainty belongs to a future sign-off decision, not to
  current operator use.

## Repo Integration Contract

### Evidence storage

- Preferred generic root for new cold-audit evidence:
  - `build/logs/cold_audit/<scenario_slug>/`
- Existing task-specific evidence roots remain valid and should not be renamed:
  - `build/logs/telemetry_retention/`
  - `build/logs/picker_p003/`
  - `build/logs/nlp_redesign_validation/`
  - similar already-established folders

### Evidence naming

Use stable, comparable names where possible:

- `<scenario>_before.json`
- `<scenario>_after.json`
- `<scenario>_summary.json`
- `<scenario>_breakdown.json`
- `<scenario>_sql_top.json` or `.jsonl`
- `<scenario>_ui_probe.md` when manual UI notes are required

### Before / after contract

Each official cold-audit branch should have:

- one before artifact;
- one after artifact, if a patch is applied;
- one summary artifact that states:
  - target DB/profile;
  - scenario;
  - cold vs warm context if relevant;
  - invariants and safety notes;
  - whether the layer is now closed or still open.

### How to document a new cold bottleneck

Record all of the following:

- exact scenario;
- target DB/profile;
- dominant layer;
- evidence artifact path;
- blocker vs not-blocker decision;
- recommended priority class;
- whether a new decision gate is required.

### How to record a decision gate

When a branch is heavy, protected, or deferred:

- put the gate in a dedicated gate or roadmap section;
- name the trigger conditions;
- name the required preflight/evidence package;
- state explicitly what remains closed until the gate is crossed.

### How to connect findings to roadmap and task docs

- `roadmap`
  - current active layer, closure markers, and next open layer.
- `lifecycle contract`
  - operator-safe meaning of the current data/maintenance state.
- `task plan`
  - detailed historical evidence and patch ledger for the branch.

Do not duplicate the full framework into those documents. Link back here.

### Closure / handoff markers

Use explicit wording:

- `current layer closed`
- `next layer open`
- `decision-gate triage only`
- `do not reopen without new evidence gate`

Avoid vague wording such as:

- `future performance work`
- `ad hoc follow-up`
- `maybe optimize later`

unless the exact gate and scope are also named.

## Documentation Alignment Rules

- Put the full cold-audit framework here and keep it current.
- Keep roadmap, lifecycle, and task-plan docs as short status and linkage
  surfaces.
- Keep historical perf/audit docs intact as evidence context unless their
  wording becomes actively misleading.
- If a historical doc conflicts with current branch status, resolve the conflict
  by:
  - adding a current-status cross-reference in roadmap/lifecycle/task docs;
  - not rewriting historical evidence into a second canonical framework.

## Current branch handoff

For the current repository state:

- telemetry retention apply validation is closed;
- housekeeping is closed;
- no active operator write slice is open on this branch;
- future heavy validation remains decision-gated;
- future cold work should start from this framework, not from ad hoc branch
  reopening.
