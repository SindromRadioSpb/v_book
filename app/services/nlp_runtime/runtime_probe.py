"""Machine-readable readiness probes for NLP runtimes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .dto import NlpRuntimeStatus


class NlpRuntimeProbe:
    """Best-effort runtime diagnostics for the current machine/environment."""

    STANZA_MODEL_ID = "he/tokenize,pos,lemma"
    _PROBE_TIMEOUT_SECONDS = 45

    def probe_stanza(self, *, use_gpu: bool = False, run_smoke: bool = True) -> NlpRuntimeStatus:
        runtime_mode = "gpu" if use_gpu else "cpu"
        payload = self._run_subprocess_probe(use_gpu=use_gpu, run_smoke=run_smoke)
        return self._status_from_payload(payload, runtime_mode=runtime_mode)

    def is_packaged_runtime(self) -> bool:
        return self._is_packaged_runtime()

    def build_setup_steps(self, status: NlpRuntimeStatus | None) -> list[str]:
        mode = "packaged" if self.is_packaged_runtime() else "development"
        steps = [
            f"Environment mode: {mode}.",
            "Persisted processing will not silently switch to Mock. Fix the runtime or explicitly confirm Mock fallback.",
        ]

        if status is None:
            steps.append("Run the isolated NLP probe again to capture the current runtime truth.")
            return steps

        if status.model_path:
            steps.append(f"Detected Hebrew model path: {status.model_path}")
        else:
            steps.append("No Hebrew model path is currently detected.")

        error_code = status.error_code or ""
        if error_code == "package_missing":
            if self.is_packaged_runtime():
                steps.append("This packaged build cannot repair Python packages in place; reinstall the app or use a dev environment.")
            else:
                steps.append("Verify the active interpreter/venv and install `stanza` into that exact environment.")
        elif error_code == "hostile_torch_state":
            steps.append("Torch DLL initialization failed inside the isolated probe; check CUDA, VC++ runtime, driver compatibility, and local Torch build.")
        elif error_code == "runtime_import_failed":
            steps.append("The package exists but runtime import failed; inspect the interpreter, PATH, and Torch/Stanza dependency chain.")
        elif error_code == "model_missing":
            steps.append("Import or copy the Hebrew Stanza resources into the detected cache path or point STANZA_RESOURCES_DIR to them.")
        elif error_code == "pipeline_init_failed":
            steps.append("The Hebrew resources were found, but pipeline initialization failed; verify resource integrity and compatible package versions.")
        elif error_code == "smoke_failed":
            steps.append("The pipeline initialized but failed the smoke sentence; rerun the probe after reinstalling the Hebrew resources.")
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
                    "Open Resources Manager only if you want to inspect the Hebrew model files manually.",
                ],
            }

        if route == "resource":
            return {
                "route": "resource",
                "title": "Repair the managed Hebrew resource",
                "next_action": "Start in Resources Manager and inspect the Managed Hebrew Resource section before retrying processing.",
                "steps": [
                    "Open Resources Manager from Documents or Tools.",
                    "Inspect the Managed Hebrew Resource section for the detected model path.",
                    "Open the model folder or import/copy the Hebrew model files into the expected location.",
                    "Re-run the isolated NLP probe after the model files are repaired.",
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
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["HDLE_STANZA_PROBE_MODE"] = "gpu" if use_gpu else "cpu"
        env["HDLE_STANZA_PROBE_SMOKE"] = "1" if run_smoke else "0"

        cmd = [sys.executable, "-u", "-c", self._build_probe_script()]
        model_path = self._detect_stanza_model_path()

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
                "model_present": bool(model_path),
                "pipeline_init_ok": False,
                "smoke_ok": False,
                "cuda_available": False,
                "model_path": model_path,
                "smoke_requested": bool(run_smoke),
            }
        except Exception as exc:
            return {
                "error_code": "probe_subprocess_failed",
                "error_detail": str(exc),
                "package_installed": False,
                "model_present": bool(model_path),
                "pipeline_init_ok": False,
                "smoke_ok": False,
                "cuda_available": False,
                "model_path": model_path,
                "smoke_requested": bool(run_smoke),
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
                "model_present": bool(model_path),
                "pipeline_init_ok": False,
                "smoke_ok": False,
                "cuda_available": False,
                "model_path": model_path,
                "smoke_requested": bool(run_smoke),
            }

        try:
            payload = json.loads(first_line)
        except json.JSONDecodeError as exc:
            return {
                "error_code": "probe_invalid_output",
                "error_detail": str(exc),
                "package_installed": False,
                "model_present": bool(model_path),
                "pipeline_init_ok": False,
                "smoke_ok": False,
                "cuda_available": False,
                "model_path": model_path,
                "smoke_requested": bool(run_smoke),
            }

        if not payload.get("model_path"):
            payload["model_path"] = model_path
        if "smoke_requested" not in payload:
            payload["smoke_requested"] = bool(run_smoke)
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
        model_path = str(payload.get("model_path") or "") or self._detect_stanza_model_path()
        engine_version = str(payload.get("engine_version") or "") or None
        error_detail = str(payload.get("error_detail") or "").strip() or None
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
            remediation=self._build_remediation(error_code, model_path=model_path),
            engine_version=engine_version,
            model_id=self.STANZA_MODEL_ID,
            model_path=model_path,
        )

    @staticmethod
    def _normalize_error_code(error_code: object) -> str | None:
        text = str(error_code or "").strip().lower()
        return text or None

    def _build_remediation(self, error_code: str | None, *, model_path: str | None) -> str:
        model_hint = f" Model path: {model_path}." if model_path else ""
        if self._is_packaged_runtime():
            package_help = (
                "Packaged mode detected. This build cannot repair Python packages in place. "
                "Use the bundled runtime, reinstall the app, or switch to a development environment."
            )
        else:
            package_help = (
                "Development mode detected. Verify the active interpreter/venv and install missing Python packages there."
            )

        remediation_map = {
            "package_missing": f"{package_help} Expected package: stanza.{model_hint}",
            "runtime_import_failed": f"The Python package exists but failed during runtime import. Check the local interpreter and Torch/CUDA environment.{model_hint}",
            "hostile_torch_state": f"Torch failed during DLL initialization inside the probe subprocess. Check CUDA, VC++ runtime, and local driver compatibility.{model_hint}",
            "model_missing": f"Install or import the Hebrew Stanza model resources. Use Resources Manager for model paths and offline import guidance.{model_hint}",
            "pipeline_init_failed": f"Stanza package is present, but pipeline initialization failed. Verify model files, cache paths, and runtime compatibility.{model_hint}",
            "smoke_failed": f"The pipeline initialized but the smoke sentence failed. Reinstall model resources and inspect runtime logs.{model_hint}",
            "probe_timeout": "The isolated probe timed out. Retry diagnostics in CPU mode and inspect startup cost or blocking dependencies.",
            "probe_subprocess_failed": "The isolated probe process could not complete. Retry diagnostics and inspect local runtime dependencies.",
            "probe_invalid_output": "The isolated probe returned invalid output. Retry diagnostics and inspect stderr/log output.",
        }
        return remediation_map.get(
            error_code or "",
            f"Runtime status is unavailable. Retry diagnostics and inspect the active environment.{model_hint}",
        )

    @staticmethod
    def _is_packaged_runtime() -> bool:
        return os.name == "nt" and bool(getattr(sys, "frozen", False))

    @staticmethod
    def _detect_stanza_model_path() -> str | None:
        candidates: list[Path] = []

        explicit = os.getenv("STANZA_RESOURCES_DIR", "").strip()
        if explicit:
            candidates.append(Path(explicit) / "he")
            candidates.append(Path(explicit))

        candidates.append(Path.home() / "stanza_resources" / "he")

        local_appdata = os.getenv("LOCALAPPDATA", "").strip()
        if local_appdata:
            cache_root = Path(local_appdata) / "StanfordNLP" / "stanza" / "Cache"
            if cache_root.exists():
                for version_dir in sorted(cache_root.iterdir(), reverse=True):
                    if version_dir.is_dir():
                        candidates.append(version_dir / "resources" / "he")

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return None

    @staticmethod
    def _build_probe_script() -> str:
        return r'''
import json
import os
from pathlib import Path


def _detect_stanza_model_path():
    candidates = []
    explicit = os.getenv("STANZA_RESOURCES_DIR", "").strip()
    if explicit:
        candidates.append(Path(explicit) / "he")
        candidates.append(Path(explicit))
    candidates.append(Path.home() / "stanza_resources" / "he")
    local_appdata = os.getenv("LOCALAPPDATA", "").strip()
    if local_appdata:
        cache_root = Path(local_appdata) / "StanfordNLP" / "stanza" / "Cache"
        if cache_root.exists():
            for version_dir in sorted(cache_root.iterdir(), reverse=True):
                if version_dir.is_dir():
                    candidates.append(version_dir / "resources" / "he")
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


mode = os.getenv("HDLE_STANZA_PROBE_MODE", "cpu").strip().lower() or "cpu"
smoke = os.getenv("HDLE_STANZA_PROBE_SMOKE", "0") == "1"
payload = {
    "package_installed": False,
    "model_present": bool(_detect_stanza_model_path()),
    "pipeline_init_ok": False,
    "smoke_ok": False,
    "cuda_available": False,
    "engine_version": None,
    "model_path": _detect_stanza_model_path(),
    "smoke_requested": smoke,
    "error_code": None,
    "error_detail": None,
}

try:
    import stanza
except ImportError as exc:
    payload["error_code"] = "package_missing"
    payload["error_detail"] = str(exc)
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(0)
except OSError as exc:
    payload["package_installed"] = True
    payload["error_code"] = "hostile_torch_state"
    payload["error_detail"] = str(exc)
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(0)
except Exception as exc:
    payload["package_installed"] = True
    payload["error_code"] = "runtime_import_failed"
    payload["error_detail"] = str(exc)
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(0)

payload["package_installed"] = True
payload["engine_version"] = getattr(stanza, "__version__", None)

try:
    import torch
    payload["cuda_available"] = bool(torch.cuda.is_available())
except OSError as exc:
    payload["error_code"] = "hostile_torch_state"
    payload["error_detail"] = str(exc)
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(0)
except Exception:
    payload["cuda_available"] = False

try:
    pipeline = stanza.Pipeline(
        lang="he",
        processors="tokenize,pos,lemma",
        use_gpu=(mode == "gpu"),
        download_method=None,
    )
except Exception as exc:
    payload["error_code"] = "model_missing" if any(token in str(exc).lower() for token in ("download", "model", "resource")) else "pipeline_init_failed"
    payload["error_detail"] = str(exc)
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(0)

payload["pipeline_init_ok"] = True

if not smoke:
    payload["smoke_ok"] = True
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(0)

try:
    pipeline("שלום עולם.")
except Exception as exc:
    payload["error_code"] = "smoke_failed"
    payload["error_detail"] = str(exc)
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(0)

payload["smoke_ok"] = True
print(json.dumps(payload, ensure_ascii=False))
'''


