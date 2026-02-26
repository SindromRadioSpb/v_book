# Frozen ONNX Verification Contract

## Goal

Guarantee deterministic ONNX runtime verification for frozen/installed builds without GUI bootloader side effects.

## Confirmed failure baseline

Current frozen failure signature:

- `--self-check import` fails at `checks.onnxruntime_import`.
- Error text:
  - `DLL load failed while importing onnxruntime_pybind11_state: ... DLL initialization routine failed`
- This failure must be surfaced as explicit `FAIL`, never silently converted to "identity fallback" success.

## Runtime contract

1. `HDLE_Premium.exe --self-check import`
   - Must fail (`exit=1`) if ONNX runtime import/probe fails.
   - Must include structured diagnostics under `checks.onnxruntime_import`.
2. `HDLE_Premium.exe --self-check health`
   - Pronunciation checks report `ok` only when real niqqud inference is confirmed.
   - Fallback is allowed only as explicit degraded state with a concrete cause.
3. Frozen ONNX probing must not rely on GUI bootloader execution path.

## Console helper contract

Helper executable:

- `HDLE_ONNX_Probe.exe`
- Console subsystem (`run.exe` bootloader), no Qt/UI imports.

CLI:

```powershell
HDLE_ONNX_Probe.exe --out "<json_path>" --timeout-ms 3000 [--model-path "<onnx_file_or_dir>"]
```

Output JSON schema:

```json
{
  "ok": true,
  "stage": "infer",
  "mode": "real_inference",
  "model_path": "C:\\...\\phonikud-1.0.int8.onnx",
  "sample_input": "\\u05d1\\u05d9\\u05ea \\u05e1\\u05e4\\u05e8",
  "sample_output": "\\u05d1\\u05bc\\u05b5\\u05d9\\u05ea \\u05e1\\u05b5\\u05ab\\u05e4\\u05b6\\u05e8",
  "has_niqqud": true,
  "error": "",
  "details": "",
  "elapsed_ms": 123
}
```

Stages:

- `import` (onnxruntime/phonikud import)
- `model_load` (model resolution + constructor)
- `infer` (inference + niqqud validation)

Exit codes:

- `0`: success (`ok=true`)
- `1`: functional failure (`ok=false`)
- `2`: timeout (optional caller-level contract)

## Dist/Installed verification flow

Before installer:

```powershell
Start-Process "J:\Project_Vibe\V_book\dist\HDLE_Premium\HDLE_ONNX_Probe.exe" -ArgumentList "--out `"J:\Project_Vibe\V_book\build\verify\probe_dist.json`"" -Wait
Start-Process "J:\Project_Vibe\V_book\dist\HDLE_Premium\HDLE_Premium.exe" -ArgumentList "--self-check import --self-check-out `"J:\Project_Vibe\V_book\build\verify\import_dist.json`"" -Wait
Start-Process "J:\Project_Vibe\V_book\dist\HDLE_Premium\HDLE_Premium.exe" -ArgumentList "--self-check health --db-path `"M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db`" --self-check-out `"J:\Project_Vibe\V_book\build\verify\health_dist.json`"" -Wait
```

After installer:

- Run the same three checks against installed paths.
- Release gate is green only when pronunciation bootstrap checks are `ok` (no fallback warning).
