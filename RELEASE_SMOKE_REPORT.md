# RELEASE SMOKE REPORT

Date: 2026-02-25  
Scope: HDLE Premium Release Candidate build + validation (no source-code edits)

## 1) Repo state

- Branch: `main`
- Ahead/behind vs `origin/main`: `ahead 4`, `behind 0`
- Working tree: clean except untracked `.claude/*`

Last 5 commits:

1. `2acfff5` fix(prebuild): make export/import validation collision-proof and always cleanup
2. `92b299c` docs(release): add install/resources guide and release DoD smoke evidence
3. `8fc149e` test(resources): cover path resolution, registry status, download checksum, health checks, and first-run wizard
4. `c5c7f6b` feat(resources): add deterministic paths, resource registry, manager UI, and installer wiring
5. `831bc42` docs(documents): add DoD evidence for large-project documents paging

Commit range for RC:

- `origin/main..HEAD`
- Included commits:
  - `c5c7f6b`
  - `8fc149e`
  - `92b299c`
  - `2acfff5`

## 2) Validation runs

| Command | Exit | Result summary |
|---|---:|---|
| `python scripts/prebuild_validate.py --db-path "J:\Project_Vibe\V_book\hdle_premium.db"` | `0` | PASS, all checks passed. |
| `python -m pytest tests/test_resource_paths.py tests/test_resource_registry.py tests/test_health_check_service.py tests/test_resource_download_worker.py tests/test_first_run_wizard.py tests/test_workspace_app_window_contract.py tests/test_pronunciation_bootstrap_ui_wiring.py tests/test_project_exchange_bundle_extras.py -q` | `0` | `17 passed in 3.69s` |

Prebuild summary (4-line check block):

```text
FTS Presence............................ [OK] PASSED
Project Lifecycle....................... [OK] PASSED
Export/Import........................... [OK] PASSED
Database Integrity...................... [OK] PASSED
```

## 3) Build runs

| Command | Exit | Result summary |
|---|---:|---|
| `powershell -ExecutionPolicy Bypass -File rebuild.ps1` | `0` | SUCCESS, canonical rebuild completed (prebuild + PyInstaller + Inno Setup). |

## 4) Artifacts

| Artifact | Path | Size (bytes) | Size (approx) |
|---|---|---:|---:|
| Onedir EXE | `J:\\Project_Vibe\\V_book\\dist\\HDLE_Premium\\HDLE_Premium.exe` | `68,957,276` | `65.77 MB` |
| Onedir folder | `J:\\Project_Vibe\\V_book\\dist\\HDLE_Premium` | `5,072,035,281` | `4.72 GB` |
| Installer EXE | `J:\\Project_Vibe\\V_book\\installer\\output\\HDLE_Premium_Setup.exe` | `2,186,613,747` | `2.04 GB` |

Installer SHA256:

- `B8A62B8DF34113B451C6D3A6B001D42CDDF0B526E5506BFF216FA4240A0DE5F2`

## 5) Clean-profile install smoke plan (guided, exact)

Use a fresh Windows profile/VM and fill PASS/FAIL during execution.

### Scenario A: Core + Local Models

| Case | Action | Expected | PASS | FAIL | Evidence |
|---|---|---|:---:|:---:|---|
| A1 | Install with `Core Application` + `Local Models` | Install completes | [ ] | [ ] | screenshot |
| A2 | Run `Tools -> Run Health Check...` | `Pronunciation Bootstrap` = `ok` | [ ] | [ ] | screenshot |
| A3 | Same health report | `Sentence Niqqud Bootstrap` = `ok` | [ ] | [ ] | screenshot |

### Scenario B: Core only + remediation

| Case | Action | Expected | PASS | FAIL | Evidence |
|---|---|---|:---:|:---:|---|
| B1 | Install with `Core Application` only | Install completes | [ ] | [ ] | screenshot |
| B2 | Run health check | Model checks show `missing/warn` + remediation | [ ] | [ ] | screenshot |
| B3 | Open `Resources Manager`, import/download model, refresh | Model status becomes `installed` | [ ] | [ ] | screenshot |
| B4 | Re-run health check | Missing model warnings cleared | [ ] | [ ] | screenshot |

### Scenario C: Cloud providers

| Case | Action | Expected | PASS | FAIL | Evidence |
|---|---|---|:---:|:---:|---|
| C1 | Load Google service-account JSON in MT Provider Settings | Credentials accepted | [ ] | [ ] | screenshot |
| C2 | Run `Test API connection` (Google Cloud Translate) | PASS | [ ] | [ ] | screenshot |
| C3 | Load Google service-account JSON in Audio Provider Settings | Credentials accepted | [ ] | [ ] | screenshot |
| C4 | Run `Test API connection` (Google Cloud TTS) | PASS | [ ] | [ ] | screenshot |

### Scenario D: Hebrew Wikipedia Baseline

| Case | Action | Expected | PASS | FAIL | Evidence |
|---|---|---|:---:|:---:|---|
| D1 | Install/import baseline `.hdleproj` | Import completes | [ ] | [ ] | screenshot |
| D2 | Open Projects dashboard | Baseline project visible | [ ] | [ ] | screenshot |
| D3 | Open baseline `Dictionary` and `Sentences` | Data is present in both views | [ ] | [ ] | screenshot |

Required screenshot list:

1. Installer component selection (`Core/Local Models/Baseline`).
2. Health Check PASS for pronunciation + sentence niqqud (Scenario A).
3. Health Check missing-model remediation state (Scenario B, before import).
4. Resources Manager showing installed model after remediation (Scenario B, after import).
5. MT Provider Settings with successful Google Translate test (Scenario C).
6. Audio Provider Settings with successful Google TTS test (Scenario C).
7. Baseline import completion (Scenario D).
8. Baseline project visible in Projects dashboard (Scenario D).
9. Baseline Dictionary and Sentences populated (Scenario D).

## 6) RC verdict

- Build artifacts: `PASS` (PyInstaller onedir + Inno installer generated)
- Targeted pytest suite: `PASS` (`17 passed`)
- Prebuild validation: `PASS` (all 4 checks passed)

Release candidate is buildable and prebuild validation passes on the validated DB.
