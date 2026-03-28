"""Machine-readable readiness probes for NLP runtimes."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .dto import NlpRuntimeStatus
from .managed_runtime import ManagedStanzaRuntime


class NlpRuntimeProbe:
    """Best-effort runtime diagnostics for the current machine/environment."""

    STANZA_MODEL_ID = "he/tokenize,pos,lemma"
    _PROBE_TIMEOUT_SECONDS = 45

    def __init__(self):
        self.runtime = ManagedStanzaRuntime()

    def probe_stanza(self, *, use_gpu: bool = False, run_smoke: bool = True) -> NlpRuntimeStatus:
        runtime_mode = "gpu" if use_gpu else "cpu"
        payload = self._run_subprocess_probe(use_gpu=use_gpu, run_smoke=run_smoke)
        return self._status_from_payload(payload, runtime_mode=runtime_mode)

    def is_packaged_runtime(self) -> bool:
        return self.runtime.is_packaged_runtime()

    def build_setup_steps(self, status: NlpRuntimeStatus | None) -> list[str]:
        mode = "packaged" if self.is_packaged_runtime() else "development"
        steps = [
            f"Environment mode: {mode}.",
            "Persisted processing will not silently switch to Mock. Fix the runtime or explicitly confirm Mock fallback.",
            "Use Install / Repair NLP Runtime to bootstrap the product-owned runtime and managed Hebrew model path.",
        ]

        if status is None:
            steps.append("Run the isolated NLP probe again to capture the current runtime truth.")
            return steps

        if status.managed_runtime_source_kind:
            steps.append(
                "Managed Hebrew payload ownership: "
                f"{status.managed_runtime_source_kind}."
            )
        if status.managed_runtime_bundled_payload_root:
            steps.append(
                "Bundled payload root: "
                f"{status.managed_runtime_bundled_payload_root}"
            )

        if status.model_path:
            steps.append(f"Detected Hebrew model path: {status.model_path}")
        else:
            steps.append("No Hebrew model path is currently detected.")

        error_code = status.error_code or ""
        if error_code == "package_missing":
            if self.is_packaged_runtime():
                steps.append("This packaged build cannot repair Python packages in place; repair or reinstall the product-owned runtime payload.")
            else:
                steps.append("Verify the active interpreter/venv for the development app runtime and install `stanza` into that exact environment.")
        elif error_code == "hostile_torch_state":
            steps.append("Torch DLL initialization failed inside the isolated probe; check the product-owned runtime payload, VC++ runtime, driver compatibility, and local Torch build.")
        elif error_code == "runtime_import_failed":
            steps.append("The package exists but runtime import failed; inspect the managed runtime executable, PATH, and Torch/Stanza dependency chain.")
        elif error_code == "model_missing":
            steps.append("Run Install / Repair NLP Runtime to restore the managed Hebrew resources into the product-owned runtime path.")
        elif error_code == "pipeline_init_failed":
            steps.append("The Hebrew resources were found, but pipeline initialization failed; verify managed resource integrity and compatible package versions.")
        elif error_code == "smoke_failed":
            steps.append("The pipeline initialized but failed the smoke sentence; rerun Install / Repair NLP Runtime and then re-run diagnostics.")
        elif error_code == "probe_timeout":
            steps.append("The isolated probe timed out; retry diagnostics and inspect slow or blocking runtime initialization.")
        elif error_code == "probe_subprocess_failed":
            steps.append("The isolated probe could not complete; inspect local environment restrictions and retry diagnostics.")
        elif error_code == "probe_invalid_output":
            steps.append("The isolated probe returned invalid output; inspect stderr/log output and retry diagnostics.")

        if status.remediation:
            steps.append(f"Remediation summary: {status.remediation}")
        return steps

    def classify_repair_route(self, status: NlpRuntimeStatus | None) -> str:
        if status is None:
            return "runtime"
        if status.stanza_ready:
            return "ready"
        error_code = str(status.error_code or "").strip().lower()
        if error_code in {
            "package_missing",
            "runtime_import_failed",
            "hostile_torch_state",
            "probe_timeout",
            "probe_subprocess_failed",
            "probe_invalid_output",
        }:
            return "runtime"
        if error_code in {"model_missing", "pipeline_init_failed", "smoke_failed"}:
            return "resource"
        if status.model_path:
            return "resource"
        return "runtime"

    def build_guided_repair_plan(self, status: NlpRuntimeStatus | None) -> dict[str, object]:
        route = self.classify_repair_route(status)
        if route == "ready":
            return {
                "route": "ready",
                "title": "Runtime ready",
                "next_action": "No repair is required. Persisted processing can use Stanza directly.",
                "steps": [
                    "Run Health Check only if you want to verify the current environment again.",
                    "Open Resources Manager if you want to inspect the bundled payload ownership or managed Hebrew model files manually.",
                ],
            }

        if route == "resource":
            return {
                "route": "resource",
                "title": "Repair the managed Hebrew resource",
                "next_action": "Start in Resources Manager and inspect the Managed Hebrew Resource section before retrying processing.",
                "steps": [
                    "Open Resources Manager from Documents or Tools.",
                    "Run Install / Repair NLP Runtime to restore the product-owned Hebrew model path.",
                    "Inspect the Managed Hebrew Resource section for the detected model path and source ownership.",
                    "Open the model folder if you need to verify or replace the local files manually.",
                    "Re-run the isolated NLP probe after the managed model files are repaired.",
                    "Run Health Check if you need a consolidated report before retrying persisted processing.",
                ],
            }

        return {
            "route": "runtime",
            "title": "Repair the external runtime dependency",
            "next_action": "Start with Health Check, then inspect the external runtime dependency in Resources Manager before retrying processing.",
            "steps": [
                "Run Health Check to confirm the current reason code and remediation summary.",
                "Open Resources Manager and inspect the External Runtime Dependency section.",
                "Run Install / Repair NLP Runtime to refresh the product-owned runtime manifest and managed resources.",
                "Fix the active interpreter, stanza package, torch state, or packaged runtime issue.",
                "Re-run the isolated NLP probe after the runtime dependency is repaired.",
                "Retry persisted processing only after the runtime reports ready or after explicit Mock fallback confirmation.",
            ],
        }

    @staticmethod
    def build_mock_status(
        *,
        configured_engine_id: str = "mock",
        fallback_used: bool = False,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> NlpRuntimeStatus:
        return NlpRuntimeStatus(
            configured_engine_id=configured_engine_id,
            effective_engine_id="mock",
            package_installed=True,
            model_present=False,
            pipeline_init_ok=True,
            smoke_ok=True,
            cuda_available=False,
            runtime_mode="cpu",
            fallback_used=fallback_used,
            error_code=error_code,
            error_detail=error_detail,
            remediation="Mock runtime is active only for diagnostic/demo or explicit fallback use.",
            engine_version="1.0.0",
            model_id=None,
            model_path=None,
        )

    def _run_subprocess_probe(self, *, use_gpu: bool, run_smoke: bool) -> dict[str, object]:
        bootstrap = self.runtime.bootstrap_runtime(force_repair=False)
        cmd = self.runtime.build_probe_command()
        env = self.runtime.build_runtime_env(use_gpu=use_gpu, run_smoke=run_smoke)

        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self._PROBE_TIMEOUT_SECONDS,
                cwd=Path(__file__).resolve().parents[3],
                env=env,
            )
        except subprocess.TimeoutExpired:
            return {
                "error_code": "probe_timeout",
                "error_detail": f"Subprocess probe timed out after {self._PROBE_TIMEOUT_SECONDS} seconds.",
                "package_installed": False,
                "model_present": bool(bootstrap.model_present),
                "pipeline_init_ok": False,
                "smoke_ok": False,
                "cuda_available": False,
                "model_path": str(bootstrap.model_path),
                "smoke_requested": bool(run_smoke),
                "managed_runtime": bootstrap.to_dict(),
            }
        except Exception as exc:
            return {
                "error_code": "probe_subprocess_failed",
                "error_detail": str(exc),
                "package_installed": False,
                "model_present": bool(bootstrap.model_present),
                "pipeline_init_ok": False,
                "smoke_ok": False,
                "cuda_available": False,
                "model_path": str(bootstrap.model_path),
                "smoke_requested": bool(run_smoke),
                "managed_runtime": bootstrap.to_dict(),
            }

        first_line = ""
        for line in completed.stdout.splitlines():
            if line.strip():
                first_line = line.strip()
                break

        if not first_line:
            return {
                "error_code": "probe_subprocess_failed",
                "error_detail": completed.stderr.strip() or f"Probe exited with code {completed.returncode}",
                "package_installed": False,
                "model_present": bool(bootstrap.model_present),
                "pipeline_init_ok": False,
                "smoke_ok": False,
                "cuda_available": False,
                "model_path": str(bootstrap.model_path),
                "smoke_requested": bool(run_smoke),
                "managed_runtime": bootstrap.to_dict(),
            }

        try:
            payload = json.loads(first_line)
        except json.JSONDecodeError as exc:
            return {
                "error_code": "probe_invalid_output",
                "error_detail": str(exc),
                "package_installed": False,
                "model_present": bool(bootstrap.model_present),
                "pipeline_init_ok": False,
                "smoke_ok": False,
                "cuda_available": False,
                "model_path": str(bootstrap.model_path),
                "smoke_requested": bool(run_smoke),
                "managed_runtime": bootstrap.to_dict(),
            }

        if not payload.get("model_path"):
            payload["model_path"] = str(bootstrap.model_path)
        if "smoke_requested" not in payload:
            payload["smoke_requested"] = bool(run_smoke)
        if "managed_runtime" not in payload:
            payload["managed_runtime"] = bootstrap.to_dict()
        return payload

    def _status_from_payload(
        self,
        payload: dict[str, object],
        *,
        runtime_mode: str,
    ) -> NlpRuntimeStatus:
        error_code = self._normalize_error_code(payload.get("error_code"))
        package_installed = bool(payload.get("package_installed"))
        model_present = bool(payload.get("model_present"))
        pipeline_init_ok = bool(payload.get("pipeline_init_ok"))
        smoke_requested = bool(payload.get("smoke_requested", True))
        smoke_ok = bool(payload.get("smoke_ok")) if smoke_requested else True
        cuda_available = bool(payload.get("cuda_available"))
        model_path = str(payload.get("model_path") or "") or self.runtime.detect_best_model_path()
        engine_version = str(payload.get("engine_version") or "") or None
        error_detail = str(payload.get("error_detail") or "").strip() or None
        managed_runtime = payload.get("managed_runtime") if isinstance(payload.get("managed_runtime"), dict) else {}
        source_kind = str(managed_runtime.get("source_kind") or "") or None
        source_path = str(managed_runtime.get("source_path") or "") or None
        ownership = str(managed_runtime.get("ownership") or "") or None
        bundled_payload_root = str(managed_runtime.get("bundled_payload_root") or "") or None

        effective_engine_id = None
        if not error_code and package_installed and pipeline_init_ok and smoke_ok:
            effective_engine_id = "stanza"

        return NlpRuntimeStatus(
            configured_engine_id="stanza",
            effective_engine_id=effective_engine_id,
            package_installed=package_installed,
            model_present=model_present,
            pipeline_init_ok=pipeline_init_ok,
            smoke_ok=smoke_ok,
            cuda_available=cuda_available,
            runtime_mode=runtime_mode,
            fallback_used=False,
            error_code=error_code,
            error_detail=error_detail,
            remediation=self._build_remediation(
                error_code,
                model_path=model_path,
                source_kind=source_kind,
            ),
            engine_version=engine_version,
            model_id=self.STANZA_MODEL_ID,
            model_path=model_path,
            managed_runtime_source_kind=source_kind,
            managed_runtime_source_path=source_path,
            managed_runtime_ownership=ownership,
            managed_runtime_bundled_payload_root=bundled_payload_root,
        )

    @staticmethod
    def _normalize_error_code(error_code: object) -> str | None:
        text = str(error_code or "").strip().lower()
        return text or None

    def _build_remediation(
        self,
        error_code: str | None,
        *,
        model_path: str | None,
        source_kind: str | None,
    ) -> str:
        model_hint = f" Model path: {model_path}." if model_path else ""
        ownership_hint = f" Managed source ownership: {source_kind}." if source_kind else ""
        if self.is_packaged_runtime():
            package_help = (
                "Packaged mode detected. This build cannot repair Python packages in place. "
                "Use Install / Repair NLP Runtime, reinstall the app, or switch to a development environment."
            )
        else:
            package_help = (
                "Development mode detected. Use Install / Repair NLP Runtime first, then verify the active interpreter/venv if package import is still failing."
            )

        remediation_map = {
            "package_missing": f"{package_help} Expected package: stanza.{ownership_hint}{model_hint}",
            "runtime_import_failed": f"The Python package exists but failed during runtime import. Check the managed runtime executable and Torch/CUDA environment.{ownership_hint}{model_hint}",
            "hostile_torch_state": f"Torch failed during DLL initialization inside the probe subprocess. Check the managed runtime payload, VC++ runtime, and local driver compatibility.{ownership_hint}{model_hint}",
            "model_missing": f"Run Install / Repair NLP Runtime to restore the managed Hebrew model resources. Use Resources Manager for model paths and offline guidance.{ownership_hint}{model_hint}",
            "pipeline_init_failed": f"Stanza package is present, but pipeline initialization failed. Verify managed model files, cache paths, and runtime compatibility.{ownership_hint}{model_hint}",
            "smoke_failed": f"The pipeline initialized but the smoke sentence failed. Reinstall the managed model resources and inspect runtime logs.{ownership_hint}{model_hint}",
            "probe_timeout": "The isolated probe timed out. Retry diagnostics in CPU mode and inspect startup cost or blocking dependencies.",
            "probe_subprocess_failed": "The isolated probe process could not complete. Retry diagnostics and inspect local runtime dependencies.",
            "probe_invalid_output": "The isolated probe returned invalid output. Retry diagnostics and inspect stderr/log output.",
        }
        return remediation_map.get(
            error_code or "",
            f"Runtime status is unavailable. Retry diagnostics and inspect the active environment.{ownership_hint}{model_hint}",
        )
