# Decisions Log

## D-001 — Variant B is the product target
- Status: accepted
- Decision:
  - Product direction is `Premium Product Requirements` with staged delivery.
- Rationale:
  - The product needs a durable engine-management architecture, not a Stanza-only UX patch.

## D-002 — Safety-first rollout
- Status: accepted
- Decision:
  - Wave 1 starts with the persisted-processing safety invariant before premium orchestration.
- Rationale:
  - The highest current risk is silent degradation via Mock in persisted processing.

## D-003 — No silent mock fallback
- Status: accepted
- Decision:
  - Persisted processing must not silently fall back to Mock.
  - If Stanza is unavailable, the system must either block with an actionable error or require explicit user confirmation for a mock fallback policy.
- Rationale:
  - Silent fallback corrupts product trust and produces low-quality persisted NLP data.

## D-004 — Split configured vs effective engine
- Status: accepted
- Decision:
  - Runtime state must distinguish:
    - `configured_engine_id`
    - `effective_engine_id`
- Rationale:
  - Product truth requires recording what the user expected and what actually ran.

## D-005 — Mock reclassification
- Status: accepted
- Decision:
  - `mock` is not a peer production backend.
  - It is treated as `diagnostic/demo/explicit-fallback-only`.
- Rationale:
  - This aligns naming, UX, logs, tests, and future capability governance.

## D-006 — Layered runtime architecture
- Status: accepted
- Decision:
  - Keep installation/remediation logic out of `NLPEngine`.
  - Use separate layers:
    - `NLPEngine`
    - `RuntimeProbe`
    - `PolicyResolver`
    - `ResourceAdapter`
- Rationale:
  - Prevent backend classes from becoming mixed runtime/install/UX objects.

## D-007 — Resources Manager must not pretend to be a package manager
- Status: accepted
- Decision:
  - Resources UI may expose runtime status and model/resource status, but must distinguish external Python runtime dependencies from managed local model assets.
- Rationale:
  - GUI package installation is not trustworthy across dev and packaged modes.

## D-008 — Wave 1 provenance stays additive
- Status: accepted and implemented
- Decision:
  - Wave 1 stores configured/effective runtime provenance in `ProcessorRun.note` instead of introducing a schema migration immediately.
- Rationale:
  - This keeps the safety patch small, additive, and testable while preserving audit-grade run truth.

## D-009 — Probe isolation must be subprocess-based
- Status: accepted and implemented
- Decision:
  - `RuntimeProbe` must inspect `stanza/torch` from an isolated subprocess instead of importing them into the live UI process.
- Rationale:
  - hostile Torch DLL/import state must degrade to diagnostics, not destabilize Documents, Health Check, or Resources Manager.

## D-010 — Repair guidance must be packaging-aware
- Status: accepted and implemented
- Decision:
  - remediation text and repair steps must distinguish development-mode interpreter issues from packaged-app runtime limitations.
- Rationale:
  - the user needs honest next steps; packaged builds must not pretend they can repair Python packages in place.

## D-011 — Wave 2 is the stable runtime-management baseline
- Status: accepted and implemented
- Decision:
  - treat Wave 2 as the current stable checkpoint for subprocess probing, packaging-aware remediation, and guarded Resources Manager repair flow.
- Rationale:
  - this is no longer an exploratory midpoint; it is the baseline that future Wave 3 work must preserve.

## D-012 — UX must separate external runtime and managed Hebrew resource
- Status: accepted and implemented
- Decision:
  - the UI must distinguish external runtime dependency issues from managed Hebrew model/resource state.
- Rationale:
  - this reduces user confusion and preserves the rule that Resources Manager is not a pseudo package manager.

## D-013 — Structured provenance must be additive-first
- Status: accepted and implemented
- Decision:
  - structured runtime provenance is introduced as a backward-compatible envelope inside `ProcessorRun.note` before any schema migration is considered.
- Rationale:
  - this preserves historical compatibility while enabling filtering and audit on stable machine-readable fields.

## D-014 — Guided repair flow must reuse runtime taxonomy
- Status: accepted and implemented
- Decision:
  - Documents, Health Check, and Resources Manager must route the user through one shared guided repair plan derived from the runtime probe taxonomy.
- Rationale:
  - this strengthens self-service behavior without adding pseudo-package-manager semantics or duplicating routing logic in each surface.

## D-015 — UI owners must never outlive active QThreads
- Status: accepted and implemented
- Decision:
  - dialog/window owners of background QThreads must perform deterministic shutdown before destruction: cooperative stop, bounded wait, force terminate only during owner shutdown, and refuse close if the thread is still alive.
- Rationale:
  - the Windows runtime recovery path already uses more background orchestration; a leaked owner-bound QThread is now a P0 crash source (`QThread: Destroyed while thread is still running`).

## D-016 — Windows production Stanza uses an app-owned subprocess runtime
- Status: accepted and implemented
- Decision:
  - on Windows, production Stanza processing should prefer an application-controlled subprocess runtime launched via `app.main --stanza-worker`, with the probe using the sibling `app.main --stanza-probe` path.
- Rationale:
  - the Qt UI process must not be the critical path for successful `torch/stanza` imports; the product executable itself is the honest runtime owner in packaged mode.

## D-017 — Hebrew Stanza resources are bootstrap-managed into app data
- Status: accepted and implemented
- Decision:
  - the product-owned runtime bootstraps a managed `stanza_resources/he` tree under the app data root and records ownership/paths in a runtime manifest.
- Rationale:
  - this gives the product a stable resource root without pretending that a single install file exists for the Hebrew model.

## D-018 — One official setup action must be shared across UI surfaces
- Status: accepted and implemented
- Decision:
  - Documents, Health Check, and Resources Manager should all route runtime repair to one official action: `Install / Repair NLP Runtime`.
- Rationale:
  - once the product owns the managed runtime path, the user should not be left to infer which button or screen is the authoritative recovery path.

## D-019 — Managed runtime bootstrap must reject partial Hebrew payloads
- Status: accepted and implemented
- Decision:
  - the managed `stanza_resources/he` copy is considered valid only when `resources.json` and the required Hebrew model payload entries are present; otherwise bootstrap must repair from a valid bundled/legacy source.
- Rationale:
  - a partial managed copy produced a green manifest/probe path but failed real worker startup with missing `backward_charlm`, which is worse than an explicit missing-resource signal.

## D-020 — Windows subprocess runtime must pre-register Torch/CUDA DLL paths
- Status: accepted and implemented
- Decision:
  - before importing `stanza/torch` in the app-owned probe/worker runtime, register Torch `lib` and discovered CUDA `bin` directories via `os.add_dll_directory` and PATH prefixing.
- Rationale:
  - on the target Windows machine, this is the difference between a recoverable app-owned subprocess runtime and `WinError 1114` on `torch\lib\c10.dll`.

## D-021 — Release gate for managed runtime is app-like smoke, not unit tests only
- Status: accepted and implemented
- Decision:
  - the managed Windows Stanza runtime is not considered release-ready until it passes:
    - hostile in-process Qt smoke,
    - managed subprocess startup,
    - Hebrew sample processing,
    - DB-copy `Re-process` smoke.
- Rationale:
  - unit tests alone did not expose the incomplete managed payload and Windows DLL path behavior seen in the live application.

## D-022 — Business result signals must not mask `QThread.finished`
- Status: accepted and implemented
- Decision:
  - `ProcessWorker` must use a separate business-result signal (`result_ready`) and keep the base `QThread.finished` signal available for deterministic cleanup.
- Rationale:
  - emitting a custom `finished` payload from inside `run()` caused UI cleanup to happen before the thread had actually terminated, which is exactly how `QThread: Destroyed while thread is still running` escaped the earlier hardening pass.
