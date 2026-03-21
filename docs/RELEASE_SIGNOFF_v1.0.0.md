# Release Sign-off — HDLE Premium v1.0.0

**Date:** 2026-03-21
**Status:** SIGNED OFF ✅

---

## Build Identity

| Field | Value |
|-------|-------|
| Version | 1.0.0 |
| Git tag | `v1.0.0` |
| Commit | `ba252361b13fd52b812f663176338ddcbd9dcf03` |
| dirty | 0 (clean build from tag) |
| built_at | 2026-03-21T16:32:51Z |
| Schema | v42 |

---

## Evidence Summary

### Automated gates

| Gate | Result |
|------|--------|
| pytest suite | 1549 passed, 0 failed, 30 skipped |
| ONNX probe (frozen) | ok — real_inference, ~1.7s |
| Import self-check | all sub-checks ok |
| Health self-check | ok (warn: Google TTS credentials — expected) |
| DB open (hewiki test, 37 GB) | ok — schema 42/42, 1ms |
| Frozen self-check: PASS | `verify_frozen_health.ps1` — PASS |

### Manual smoke — dev machine

| Check | Result |
|-------|--------|
| Installer (`C:\Program Files\HDLE`) | ✅ |
| First-run wizard | ✅ |
| Start Menu shortcut | ✅ |
| AppData created (`%LOCALAPPDATA%\HDLE\`) | ✅ |
| DB switch (hewiki test.db) | ✅ |
| Documents view — first page load | ✅ |
| Dictionary search | ✅ |
| System Health — pronunciation/niqqud ok | ✅ |
| Clean exit (code 0) | ✅ |
| Uninstall — app removed, AppData preserved | ✅ |

### Manual smoke — clean VM

| Check | Result |
|-------|--------|
| Install on Windows without Python/dev-tools | ✅ |
| App starts from installed location | ✅ |
| Core functionality verified | ✅ |

---

## Artifacts

| Artifact | Location |
|----------|----------|
| Installer (split) | GitHub Release v1.0.0 — `HDLE_Premium_Setup_v1.0.0.7z.001/002` |
| dist EXE | `dist\HDLE_Premium\HDLE_Premium.exe` |
| Frozen health summary | `build\verify_dist\frozen_health_summary.json` |
| PyInstaller log | `build\logs\pyinstaller_20260321_183252.log` |
| Inno Setup log | `build\logs\inno_20260321_184400.log` |
| GitHub Release | https://github.com/SindromRadioSpb/v_book/releases/tag/v1.0.0 |

---

## Scope — What v1.0.0 Delivers

- **M1–M11 complete:** Ingestion, NLP (Stanza Hebrew), Lemmatization, MWE extraction,
  Term clustering, Term curation, Translation Memory v1+v2, Batch Translation,
  Export Center (XLSX/CSV/JSON/TBX/TMX), Project Exchange, PyInstaller + Inno Setup installer
- **P0 Security:** FTS5 injection, CSV injection, log injection, path traversal,
  credential encryption (AES-256-GCM + OS keyring), security audit log
- **Translation providers:** Google Translate (free), Google Cloud Translate v3
- **Audio:** Phonikud ONNX offline pronunciation, TTS pipeline
- **Reference corpus:** Hebrew Wikipedia support, read-only reference DB mount
- **UI Pro Workspace:** multi-panel layout, command palette, keyboard shortcuts,
  workspace presets, operations center
- **Engineering baseline:** WAL safety, write-governance, staged progress UX,
  cold-audit framework (33 subsystems covered), ship gate pipeline

---

## Known Limitations (not blockers)

| Item | Notes |
|------|-------|
| `import.ok: false` in summary JSON | Cosmetic — top-level `ok` field absent in import self-check format; all sub-checks pass |
| Google TTS credentials warn | Expected on fresh install; user configures via Audio Provider Settings |
| `process_lock` unlock warning on exit | Windows file-lock race at shutdown; no data impact |

---

## Next Development Cycle

**Epic 4: Term Extraction Pro** — see `docs/ROADMAP_PREMIUM_PRO.md`

- Advanced termhood algorithms: PMI, Dice, LLR, Keyness, Weirdness
- Reference corpus selection UI
- Extraction config persistence (reproducibility)
- Estimated effort: 2 weeks
