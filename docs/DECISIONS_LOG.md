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

## D-031 — Runtime provenance promotion stays dual-write and migration-safe
- Status: accepted and implemented
- Decision:
  - promote runtime provenance for new `ProcessorRun` rows into dedicated schema fields while preserving the existing nested `runtime` envelope in `ProcessorRun.note` as a compatibility layer.
  - read/debug paths should prefer schema-backed fields and fall back to `note` for legacy rows created before the promotion.
- Rationale:
  - this turns runtime provenance into SQL/audit-friendly data without reopening packaged runtime work or breaking historical rows that only have the additive note contract.

## D-032 — Project bundle export must stage to a temporary artifact before publish
- Status: accepted and implemented
- Decision:
  - heavy `.hdleproj` export should write into a temporary `*.partial` bundle first and only rename it to the final output path after the ZIP is complete.
  - export progress must expose the post-payload finalization phases explicitly instead of leaving one silent “Creating bundle...” step.
- Rationale:
  - the confirmed user-facing failure chain was: long final export phase looked hung, the run was interrupted, and a non-ZIP partial file was left behind under the final `.hdleproj` name, causing the later import failure.

## D-033 — Project export success must require stage completion and artifact validation
- Status: accepted and implemented
- Decision:
  - `ProjectExportEngine` should treat export as a stage-based product pipeline, not just a best-effort sequence of SQL and ZIP operations.
  - export success now requires all of the following:
    - payload finalization completed without bounded-stage failure
    - `.hdleproj` bundle was built
    - bundle structure/checksums validated through `read_bundle()`
    - extracted payload passed `PRAGMA quick_check(1)`
  - schema-backed import compatibility remains a release gate for export results, so the export/import contract must remap `document_sentence.corpus_id` for schema `31+` payloads.
- Rationale:
  - the live `Mishneh Torah` repro showed that fixing one visible hang was not enough; export must only report success after the artifact is verifiably complete and structurally importable.

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

## D-023 — Release smoke must use a document-scoped DB clone, not a full DB copy
- Status: accepted and implemented
- Decision:
  - the DB reprocess smoke path should clone only the minimum base rows required for one document and let `reprocess_document()` rebuild derived NLP state from there.
- Rationale:
  - full source DB copies and even project-scoped exports remained too expensive for the real Windows source database; the release gate must validate runtime behavior, not disk throughput on a 35GB file.

## D-024 — Packaged Hebrew payload must be release-owned and staged before freezing
- Status: accepted and implemented
- Decision:
  - the packaged Windows release must stage a directory-based Hebrew Stanza payload under `installer/resources/local_models/stanza_hebrew/` and bundle it into the frozen app under `_internal/resources/nlp_runtime/stanza_payload/`.
- Rationale:
  - the product already owns a managed runtime/bootstrap contract; the missing piece was a release-owned bundled payload source that does not depend on a legacy local Stanza cache at install time.

## D-025 — Managed bootstrap must record source ownership, not only current managed path
- Status: accepted and implemented
- Decision:
  - the runtime manifest and probe status must distinguish `bundled_packaged`, `bundled_dev`, `legacy_cache`, and `repaired_managed` instead of collapsing everything into a generic bundled/legacy flag.
- Rationale:
  - packaged release sign-off depends on proving that Stanza processing succeeded from the bundled release-owned Hebrew payload rather than by accidentally reusing a legacy local cache.

## D-026 — Bundled payload ownership must be visible on all runtime surfaces
- Status: accepted and implemented
- Decision:
  - Resources Manager, Health Check, Documents tooltips, and release smoke must all expose the same bundled payload ownership truth from the managed runtime manifest.
- Rationale:
  - the release gate is only honest when the UI and smoke path can prove whether Stanza is using a bundled packaged/dev payload or falling back to legacy cache semantics.

## D-027 — Obsolete managed ownership must be upgraded to current bundled truth
- Status: accepted and implemented
- Decision:
  - if an existing healthy managed copy still carries obsolete ownership labels like `managed_existing`, bootstrap must rebind it to the current bundled source when a valid bundled payload is present.
- Rationale:
  - otherwise release smoke can report a false non-bundled source even though the release-owned bundled payload is available and should be authoritative.


## D-028 — Bundled payload delivery and frozen Torch runtime are separate release gates
- Status: accepted and implemented
- Decision:
  - treat packaged Hebrew payload ownership and packaged Torch/Stanza import readiness as separate release checks.
- Rationale:
  - the rebuilt packaged artifact now proves `bundled_packaged` ownership correctly, but the frozen `--stanza-probe` / `--stanza-worker` path can still fail later on `torch\lib\c10.dll`; ownership success alone is not sufficient for release sign-off.

## D-029 — Frozen Torch DLL bootstrap must run before user-code imports
- Status: accepted and implemented
- Decision:
  - packaged Windows Torch bootstrap for the managed Stanza runtime must run from a PyInstaller runtime hook, not only from app-level probe/worker code.
  - the frozen bootstrap must register `_internal`, `_internal\torch`, `_internal\torch\lib` and preflight the critical `c10.dll` chain before the first user-code import path touches `torch/stanza`.
- Rationale:
  - app-level `prepare_torch_runtime_paths()` was already correct in principle, but it executed too late for the frozen packaged process; moving the bootstrap into a runtime hook is what closed the packaged `WinError 1114` failure while preserving the existing managed ownership contract.

## D-030 — Frozen ONNX helper must not block on inherited HF cache writability probes
- Status: accepted and implemented
- Decision:
  - the packaged ONNX helper may inherit a configured `HF_HOME`, but it must not treat startup writability probing of that path as part of the frozen import gate.
  - if the configured `HF_HOME` already exists, the helper should accept it as the read-first cache root; only missing or unusable paths should fall back to a local writable cache.
- Rationale:
  - the packaged `HDLE_ONNX_Probe.exe` timeout was traced to `_ensure_hf_home()` blocking before `import onnxruntime`, which made `--self-check import` fail even though the actual ONNX runtime/backend imports were healthy once startup moved past that cache-path check.

