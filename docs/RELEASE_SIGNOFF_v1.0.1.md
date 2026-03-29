# Release Sign-off — HDLE Premium v1.0.1

**Date:** 2026-03-29
**Status:** SIGNED OFF ✅

---

## Build Identity

| Field | Value |
|-------|-------|
| Version | 1.0.1 |
| Git release baseline | `v1.0.0` |
| Release notes commit | `2add5d60177fe702687987233a8b52dc0268be3f` |
| Built artifact commit | `2add5d60177fe702687987233a8b52dc0268be3f` |
| dirty | 0 |
| built_at | 2026-03-29T09:53:12Z |
| Schema | v52 |

---

## Comparison vs Previous Repository Release

Compared with repository release `v1.0.0` (`ba252361b13fd52b812f663176338ddcbd9dcf03`), `v1.0.1` is a release-hardening and workflow-trust release.

Primary release themes:

- packaged Hebrew Stanza payload delivery is now frozen-artifact owned and verified
- packaged Stanza/Torch runtime is now release-green
- packaged ONNX helper startup path is hardened
- runtime provenance moved into schema-backed `ProcessorRun` fields with legacy note compatibility
- project export is now stage-based and artifact-validated
- project import is now stage-based and verification-backed
- validation and semantic-contract coverage expanded substantially beyond the `v1.0.0` baseline

Reference diff:

- range: `v1.0.0..HEAD`
- scope snapshot: `203 files changed, 33213 insertions(+), 651 deletions(-)`

---

## Evidence Summary

### Build + packaging

| Gate | Result |
|------|--------|
| PyInstaller rebuild | ok |
| Inno Setup rebuild | ok |
| Installer artifact | `installer\output\HDLE_Premium_Setup.exe` created |
| Installer size | 3,872,498,943 bytes |

### Packaged self-checks

| Gate | Result |
|------|--------|
| `HDLE_Premium.exe --self-check import` | ok |
| `HDLE_Premium.exe --self-check health --db-path .\hdle_premium.db` | ok |
| Frozen ONNX helper | ok — `helper_exit_code=0`, `stage=import/infer` |
| Health summary | ok — pronunciation + sentence niqqud ready, cloud providers optional/disabled |

### Bundle workflow closure carried into release

| Gate | Result |
|------|--------|
| Export acceptance on reference DB (`project_id=6`, `Mishneh Torah`) | ok |
| Import acceptance on exported bundle into clean DB | ok |
| Import invalid archive failure path | stage-aware failure confirmed |

---

## Artifacts

| Artifact | Location |
|----------|----------|
| Installer | `installer\output\HDLE_Premium_Setup.exe` |
| dist EXE | `dist\HDLE_Premium\HDLE_Premium.exe` |
| PyInstaller log | `build\logs\pyinstaller_20260329_125313.log` |
| Inno Setup log | `build\logs\inno_20260329_130155.log` |
| Release notes | `docs\RELEASE_NOTES_v1.0.1.md` |

---

## Scope — What v1.0.1 Delivers

- bundled Hebrew payload path is packaged, visible, and smoke-verified
- packaged `stanza` probe/worker path is hardened through early frozen Torch DLL bootstrap
- packaged `HDLE_ONNX_Probe.exe` import/probe path is hardened and now completes truthfully
- runtime provenance is written into dedicated schema fields while preserving legacy `ProcessorRun.note`
- project export now reports stable stages, validates artifacts before success, and avoids misleading partial bundles
- project import now reports stable stages, validates bundle health before mutation, and verifies imported project usability before success
- governance docs, release notes, and handoff state now reflect the closed runtime/export/import tracks

---

## Known Non-Blockers

| Item | Notes |
|------|-------|
| Very large project export/import still takes noticeable time | Product-facing stages are now explicit and diagnosable |
| `--self-check-out` evidence path was not used for sign-off | Release sign-off relies on direct stdout JSON from packaged self-check runs |
| Local smoke artifacts remain outside git | `-info files/`, `reports/`, and staged local payload cache were intentionally excluded from commits |

---

## Release Verdict

`v1.0.1` is signed off for repository release publication on top of `v1.0.0`.

The release is accepted as:

- packaged runtime green
- project export product-closed for the proven path
- project import product-closed for the proven path
- installer rebuilt successfully
- release notes and sign-off evidence recorded
