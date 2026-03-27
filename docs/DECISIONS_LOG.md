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
