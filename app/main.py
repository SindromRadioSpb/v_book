"""HDLE Premium - Main entry point."""
from __future__ import annotations

import sys
import json
import time
import sqlite3
import logging
import argparse
import importlib
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.build_meta import format_build_meta_line, get_build_meta

logger = logging.getLogger(__name__)

_PHONIKUD_SUBPROCESS_SENTINELS = (
    "phonikud_onnx",
    "Phonikud",
    "add_diacritics",
    "json.loads",
    "outputs",
)
_BRIDGE_DLL_HANDLES: list[Any] = []
_BRIDGE_DLL_KEYS: set[str] = set()
_ONNX_PROBE_EXE_NAME = "HDLE_ONNX_Probe.exe"
_APP_INSTANCE_LOCK_NAME = "app_instance.lock"
_FROZEN_ONNX_PROBE_TIMEOUT_MS = 3000
_FROZEN_ONNX_PROBE_RETRY_TIMEOUT_MS = 8000


def resolve_db_path(cli_db_path: str | None, *, settings=None):
    from app.infra.db_path_resolver import resolve_db_path as _resolve_db_path_impl

    return _resolve_db_path_impl(cli_db_path, settings=settings)


def choose_startup_db_path(cli_db_path: str | None, *, settings=None):
    from app.infra.db_path_resolver import choose_startup_db_path as _choose_startup_db_path_impl

    return _choose_startup_db_path_impl(cli_db_path, settings=settings)


def get_default_db_path(*, settings=None) -> Path:
    from app.infra.db_path_resolver import get_default_db_path as _get_default_db_path_impl

    return _get_default_db_path_impl(settings=settings)


def get_app_dir() -> Path:
    r"""Get the application data directory.

    Default locations:
    - Windows: %LOCALAPPDATA%\HDLE
    - macOS: ~/Library/Application Support/HDLE
    - Linux: ~/.local/share/hdle
    """
    from app.infra.resource_paths import ResourcePaths

    return ResourcePaths.resolve_data_root(create=True)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _attach_build_meta(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    data["build"] = get_build_meta()
    return data


def _redact_value(value: str, *, keep_prefix: int = 3, keep_suffix: int = 2) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) <= (keep_prefix + keep_suffix):
        return "*" * len(text)
    return f"{text[:keep_prefix]}***{text[-keep_suffix:]}"


def _emit_self_check(payload: dict[str, Any], out_path: str | None = None) -> None:
    file_payload = json.dumps(payload, ensure_ascii=False, indent=2)
    if out_path:
        out_file = Path(out_path).expanduser().resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(file_payload + "\n", encoding="utf-8")
    console_payload = json.dumps(payload, ensure_ascii=True, indent=2)
    print(console_payload)


def _is_phonikud_subprocess_script(script: str) -> bool:
    snippet = (script or "").strip()
    if not snippet:
        return False
    lowered = snippet.lower()
    return all(token.lower() in lowered for token in _PHONIKUD_SUBPROCESS_SENTINELS)


def _register_bridge_dll_directory(path: Path) -> None:
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return
    try:
        resolved = str(path.resolve())
    except Exception:
        resolved = str(path)
    key = resolved.lower()
    if key in _BRIDGE_DLL_KEYS:
        return
    if not Path(resolved).exists():
        return
    try:
        handle = os.add_dll_directory(resolved)
    except Exception:
        return
    _BRIDGE_DLL_HANDLES.append(handle)
    _BRIDGE_DLL_KEYS.add(key)


def _prepare_onnxruntime_dll_paths_for_bridge() -> None:
    candidates: list[Path] = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        meipass_root = Path(str(meipass))
        candidates.append(meipass_root / "onnxruntime" / "capi")
        candidates.append(meipass_root / "_internal" / "onnxruntime" / "capi")

    try:
        exe_root = Path(sys.executable).resolve().parent
        candidates.append(exe_root / "onnxruntime" / "capi")
        candidates.append(exe_root / "_internal" / "onnxruntime" / "capi")
    except Exception:
        pass

    try:
        spec = importlib.util.find_spec("onnxruntime")
        origin = getattr(spec, "origin", None)
        if origin:
            package_root = Path(origin).resolve().parent
            candidates.append(package_root / "capi")
    except Exception:
        pass

    existing_path = os.environ.get("PATH", "")
    normalized_path = existing_path.lower()
    prefix_parts: list[str] = []
    for candidate in candidates:
        try:
            resolved = str(candidate.resolve())
        except Exception:
            resolved = str(candidate)
        if not Path(resolved).exists():
            continue
        _register_bridge_dll_directory(Path(resolved))
        if resolved.lower() not in normalized_path and resolved not in prefix_parts:
            prefix_parts.append(resolved)
    if prefix_parts:
        os.environ["PATH"] = ";".join(prefix_parts + [existing_path]) if existing_path else ";".join(prefix_parts)


def _resolve_frozen_onnx_probe_executable() -> Path | None:
    if not (os.name == "nt" and bool(getattr(sys, "frozen", False))):
        return None
    try:
        exe_root = Path(sys.executable).resolve().parent
    except Exception:
        return None
    candidates = (
        exe_root / _ONNX_PROBE_EXE_NAME,
        exe_root / "_internal" / _ONNX_PROBE_EXE_NAME,
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _acquire_app_instance_lock(
    app_data_root: Path,
    *,
    timeout_seconds: int = 1,
) -> tuple[Any | None, str]:
    from app.infra.process_lock import ProcessLock

    lock_path = Path(app_data_root).resolve() / _APP_INSTANCE_LOCK_NAME
    lock = ProcessLock(lock_path, timeout_seconds=timeout_seconds)
    try:
        lock.__enter__()
        return lock, ""
    except Exception as exc:
        return None, str(exc)


def _release_app_instance_lock(lock: Any | None) -> None:
    if lock is None:
        return
    try:
        lock.__exit__(None, None, None)
    except Exception as exc:
        logger.warning("Failed to release app instance lock: %s", exc)


def _is_probe_timeout_payload(payload: dict[str, Any]) -> bool:
    if bool(payload.get("timed_out", False)):
        return True
    text = str(payload.get("error") or "").lower()
    return "timed out" in text or "timeout" in text


def _run_frozen_onnx_probe_helper(
    *,
    mode: str,
    model_path: str = "",
    timeout_ms: int = 3000,
) -> tuple[int, dict[str, Any]]:
    helper_path = _resolve_frozen_onnx_probe_executable()
    if helper_path is None:
        return 1, {
            "ok": False,
            "stage": "import",
            "mode": mode,
            "error": f"Frozen ONNX helper not found: {_ONNX_PROBE_EXE_NAME}",
            "helper_path": "",
            "exit_code": 1,
        }

    cmd = [
        str(helper_path),
        "--mode",
        mode,
        "--timeout-ms",
        str(int(timeout_ms)),
    ]
    cleaned_model_path = str(model_path or "").strip()
    if cleaned_model_path:
        cmd.extend(["--model-path", cleaned_model_path])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(3, int(timeout_ms / 1000) + 2),
        )
    except subprocess.TimeoutExpired as exc:
        return 1, {
            "ok": False,
            "stage": "import",
            "mode": mode,
            "error": str(exc),
            "helper_path": str(helper_path),
            "exit_code": 1,
            "timed_out": True,
            "timeout_ms": int(timeout_ms),
        }
    except Exception as exc:
        return 1, {
            "ok": False,
            "stage": "import",
            "mode": mode,
            "error": str(exc),
            "helper_path": str(helper_path),
            "exit_code": 1,
            "timeout_ms": int(timeout_ms),
        }

    try:
        payload = json.loads(proc.stdout or "{}")
        if not isinstance(payload, dict):
            payload = {}
    except Exception as exc:
        payload = {
            "ok": False,
            "stage": "import",
            "mode": mode,
            "error": f"Helper returned invalid JSON: {exc}",
        }

    payload["helper_path"] = str(helper_path)
    payload["exit_code"] = int(proc.returncode)
    payload["timeout_ms"] = int(timeout_ms)
    if proc.returncode != 0 and not str(payload.get("error") or "").strip():
        payload["error"] = (proc.stderr or proc.stdout or "").strip() or f"Helper exited with code {proc.returncode}"

    return proc.returncode, payload


def _run_phonikud_subprocess_bridge() -> int:
    try:
        raw_bytes = b""
        stdin_buffer = getattr(sys.stdin, "buffer", None)
        if stdin_buffer is not None and hasattr(stdin_buffer, "read"):
            raw_bytes = stdin_buffer.read() or b""
        if raw_bytes:
            raw = raw_bytes.decode("utf-8", errors="replace")
        else:
            raw = sys.stdin.read() or "{}"
        data = json.loads(raw)
        model_path = str(data.get("model_path") or "")
        texts = [str(text or "") for text in (data.get("texts") or [])]
    except Exception as exc:
        print(f"phonikud_subprocess_bridge payload error: {exc}", file=sys.stderr)
        return 1

    try:
        try:
            _prepare_onnxruntime_dll_paths_for_bridge()
            import phonikud as phonikud_shim

            prepare_runtime_dll_paths = getattr(phonikud_shim, "prepare_runtime_dll_paths", None)
            if callable(prepare_runtime_dll_paths):
                prepare_runtime_dll_paths()
            ensure_hf_home = getattr(phonikud_shim, "_ensure_hf_home", None)
            if callable(ensure_hf_home):
                ensure_hf_home()
        except Exception as exc:
            print(f"phonikud_subprocess_bridge bootstrap warning: {exc}", file=sys.stderr)

        from phonikud_onnx import Phonikud

        model = Phonikud(model_path)
        outputs: list[str] = []
        for normalized in texts:
            try:
                rendered = str(model.add_diacritics(normalized) or "").strip()
            except Exception:
                rendered = ""
            outputs.append(rendered or normalized)
    except Exception as exc:
        diag_parts: list[str] = []
        try:
            spec = importlib.util.find_spec("onnxruntime")
            origin = getattr(spec, "origin", None)
            diag_parts.append(f"onnxruntime_origin={origin}")
            if origin:
                package_root = Path(origin).resolve().parent
                capi_dir = package_root / "capi"
                pybind_file = capi_dir / "onnxruntime_pybind11_state.pyd"
                runtime_dll = capi_dir / "onnxruntime.dll"
                shared_dll = capi_dir / "onnxruntime_providers_shared.dll"
                diag_parts.append(f"capi_dir_exists={capi_dir.exists()}")
                diag_parts.append(f"pybind_exists={pybind_file.exists()}")
                diag_parts.append(f"onnxruntime_dll_exists={runtime_dll.exists()}")
                diag_parts.append(f"providers_shared_exists={shared_dll.exists()}")
        except Exception as diag_exc:
            diag_parts.append(f"diag_error={diag_exc}")
        diag_suffix = f" [{' ; '.join(diag_parts)}]" if diag_parts else ""
        print(
            f"phonikud_subprocess_bridge backend unavailable, identity fallback: {exc}{diag_suffix}",
            file=sys.stderr,
        )
        outputs = texts

    try:
        # Use ASCII-safe JSON to avoid code-page issues across spawned runtimes.
        sys.stdout.write(json.dumps({"outputs": outputs}, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"phonikud_subprocess_bridge emit error: {exc}", file=sys.stderr)
        return 1


def _handle_embedded_python_compat(argv: list[str]) -> int | None:
    if len(argv) < 3 or argv[1] != "-c":
        return None
    inline_script = argv[2]
    if _is_phonikud_subprocess_script(inline_script):
        return _run_phonikud_subprocess_bridge()
    return None


def _run_import_self_check(settings: SettingsService) -> tuple[int, dict[str, Any]]:
    from app.infra.resource_paths import ResourcePaths
    from app.services.resources import ResourceRegistry

    paths = ResourcePaths.build(settings=settings, create=True)
    payload: dict[str, Any] = {
        "mode": "import",
        "timestamp_utc": _utc_now_iso(),
        "checks": {},
    }

    phonikud_error = ""
    try:
        mod = importlib.import_module("phonikud")
        payload["checks"]["phonikud_import"] = {
            "ok": True,
            "module": getattr(mod, "__name__", "phonikud"),
            "version": getattr(mod, "__version__", "unknown"),
        }
    except Exception as exc:
        phonikud_error = str(exc)
        payload["checks"]["phonikud_import"] = {
            "ok": False,
            "error": phonikud_error,
        }

    if os.name == "nt" and bool(getattr(sys, "frozen", False)):
        model_path = settings.get_string("pronunciation/phonikud/model_path", "")
        helper_code, helper_payload = _run_frozen_onnx_probe_helper(
            mode="import",
            model_path=model_path,
            timeout_ms=_FROZEN_ONNX_PROBE_TIMEOUT_MS,
        )
        payload["checks"]["onnxruntime_import"] = {
            "ok": helper_code == 0 and bool(helper_payload.get("ok", False)),
            "module": "onnxruntime",
            "origin": str(helper_payload.get("onnxruntime_origin") or ""),
            "stage": str(helper_payload.get("stage") or ""),
            "error": str(helper_payload.get("error") or ""),
            "helper_path": str(helper_payload.get("helper_path") or ""),
            "helper_exit_code": int(helper_payload.get("exit_code") or 0),
        }
    else:
        try:
            ort_module = importlib.import_module("onnxruntime")
            ort_origin = str(getattr(ort_module, "__file__", "") or "")
            capi_dir = Path(ort_origin).resolve().parent / "capi" if ort_origin else None
            payload["checks"]["onnxruntime_import"] = {
                "ok": True,
                "module": getattr(ort_module, "__name__", "onnxruntime"),
                "origin": ort_origin,
                "capi_dir_exists": bool(capi_dir and capi_dir.exists()),
                "pybind_exists": bool(capi_dir and (capi_dir / "onnxruntime_pybind11_state.pyd").exists()),
                "runtime_dll_exists": bool(capi_dir and (capi_dir / "onnxruntime.dll").exists()),
            }
        except Exception as exc:
            payload["checks"]["onnxruntime_import"] = {
                "ok": False,
                "error": str(exc),
            }

    payload["checks"]["resource_paths"] = {
        "data_root": str(paths.data_root),
        "models_root": str(paths.models_root),
        "datasets_root": str(paths.datasets_root),
        "logs_root": str(paths.logs_root),
        "all_exist": all(
            p.exists()
            for p in (
                paths.data_root,
                paths.models_root,
                paths.datasets_root,
                paths.logs_root,
            )
        ),
    }

    required_resources = []
    try:
        registry = ResourceRegistry(settings=settings)
        for entry in registry.list_entries():
            if not entry.required:
                continue
            status = registry.get_status(entry.id)
            required_resources.append(
                {
                    "id": entry.id,
                    "name": entry.display_name,
                    "state": status.state,
                    "message": status.message,
                }
            )
    except Exception as exc:
        required_resources.append(
            {
                "id": "resource_registry",
                "name": "Resource Registry",
                "state": "error",
                "message": str(exc),
            }
        )
    payload["checks"]["required_resources"] = required_resources

    ok = bool(payload["checks"]["phonikud_import"]["ok"] and payload["checks"]["onnxruntime_import"]["ok"])
    return (0 if ok else 1), payload


def _run_db_open_self_check(settings: SettingsService, db_path_arg: str | None) -> tuple[int, dict[str, Any]]:
    from app.infra.db_path_resolver import classify_db_profile, inspect_db_path

    resolved_db = resolve_db_path(db_path_arg, settings=settings)
    db_path = Path(resolved_db.path).resolve()
    db_info = inspect_db_path(db_path)
    payload: dict[str, Any] = {
        "mode": "db_open",
        "timestamp_utc": _utc_now_iso(),
        "db_path": str(db_path),
        "db_source": resolved_db.source,
        "db_profile": classify_db_profile(db_path, settings=settings),
        "db_exists": bool(db_info.exists),
        "db_size_bytes": int(db_info.size_bytes),
        "schema_version": db_info.schema_version,
        "supported_schema_version": int(db_info.supported_schema_version),
    }
    if db_info.error:
        payload["inspect_error"] = db_info.error

    started = time.perf_counter()
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT project_id FROM dict_project ORDER BY project_id ASC LIMIT 1").fetchone()
            doc_row = conn.execute("SELECT doc_id FROM source_document ORDER BY doc_id ASC LIMIT 1").fetchone()
        finally:
            conn.close()
    except Exception as exc:
        payload["ok"] = False
        payload["error"] = str(exc)
        payload["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return 1, payload

    payload["ok"] = True
    payload["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    payload["sample_project_id"] = int(row[0]) if row else None
    payload["sample_doc_id"] = int(doc_row[0]) if doc_row else None
    return 0, payload


def _run_health_self_check(settings: SettingsService, db_path_arg: str | None) -> tuple[int, dict[str, Any]]:
    from app.services.health_check_service import HealthCheckService

    resolved_db = resolve_db_path(db_path_arg, settings=settings)
    db_path = Path(resolved_db.path).resolve()
    payload: dict[str, Any] = {
        "mode": "health",
        "timestamp_utc": _utc_now_iso(),
        "db_path": str(db_path),
        "db_source": resolved_db.source,
    }

    started = time.perf_counter()
    try:
        service = HealthCheckService(settings=settings)
        items = []
        items.extend([item.to_dict() for item in service._check_required_resources()])
        items.append(service._check_pronunciation_bootstrap().to_dict())
        items.append(service._check_sentence_niqqud_bootstrap().to_dict())
        items.extend([item.to_dict() for item in service._check_cloud_providers()])

        baseline_item = service._check_baseline_reference().to_dict()
        items.append(baseline_item)

        if os.name == "nt" and bool(getattr(sys, "frozen", False)):
            model_path = settings.get_string("pronunciation/phonikud/model_path", "")
            probe_code, probe_payload = _run_frozen_onnx_probe_helper(
                mode="probe",
                model_path=model_path,
                timeout_ms=_FROZEN_ONNX_PROBE_TIMEOUT_MS,
            )
            probe_payload["retry_attempted"] = False
            onnx_probe_attempts = [probe_payload]
            if probe_code != 0 and _is_probe_timeout_payload(probe_payload):
                retry_code, retry_payload = _run_frozen_onnx_probe_helper(
                    mode="probe",
                    model_path=model_path,
                    timeout_ms=_FROZEN_ONNX_PROBE_RETRY_TIMEOUT_MS,
                )
                retry_payload["retry_attempted"] = True
                retry_payload["retry_reason"] = "timeout"
                retry_payload["retry_from_timeout_ms"] = _FROZEN_ONNX_PROBE_TIMEOUT_MS
                retry_payload["retry_timeout_ms"] = _FROZEN_ONNX_PROBE_RETRY_TIMEOUT_MS
                probe_code = retry_code
                probe_payload = retry_payload
                onnx_probe_attempts.append(retry_payload)
            elif probe_code == 0:
                probe_payload["retry_attempted"] = False
            payload["onnx_probe"] = probe_payload
            payload["onnx_probe_attempts"] = onnx_probe_attempts
            probe_ok = probe_code == 0 and bool(probe_payload.get("ok", False))
            probe_error = str(probe_payload.get("error") or "").strip()
            items.append(
                {
                    "id": "frozen_onnx_probe",
                    "name": "Frozen ONNX Probe",
                    "status": "ok" if probe_ok else "error",
                    "message": "ONNX helper probe passed" if probe_ok else (probe_error or "ONNX helper probe failed"),
                    "remediation": "Reinstall runtime dependencies and verify HDLE_ONNX_Probe.exe packaging."
                    if not probe_ok
                    else "",
                }
            )

        status_rank = {"ok": 0, "optional": 0, "warn": 1, "error": 2}
        overall = "ok"
        for item in items:
            item_status = str(item.get("status", "error"))
            if status_rank.get(item_status, 2) > status_rank.get(overall, 0):
                overall = item_status

        report = {
            "overall": overall,
            "items": items,
        }
        payload["ok"] = True
        payload["report"] = report
        payload["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return 0, payload
    except Exception as exc:
        payload["ok"] = False
        payload["error"] = str(exc)
        payload["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return 1, payload


def _load_service_account_file(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"invalid_json:{exc}"

    if not isinstance(data, dict):
        return None, "invalid_json:not_object"
    if str(data.get("type") or "").strip() != "service_account":
        return None, "invalid_json:not_service_account"
    if not str(data.get("project_id") or "").strip():
        return None, "invalid_json:missing_project_id"
    return data, "ok"


def _load_service_account_from_env_key(env_key: str) -> tuple[dict[str, Any] | None, str]:
    env_path = (os.environ.get(env_key) or "").strip()
    if not env_path:
        return None, "not_set"

    candidate = Path(env_path).expanduser()
    if not candidate.exists():
        return None, f"{env_key} (path missing)"

    sa, status = _load_service_account_file(candidate)
    if sa:
        return sa, f"env:{env_key}"
    return None, f"env:{env_key} ({status})"


def _load_service_account_info_from_env_or_paths(
    settings: SettingsService,
) -> tuple[dict[str, Any] | None, str]:
    sa_env, src_env = _load_service_account_from_env_key("HDLE_GCP_SA_JSON_PATH")
    if sa_env is not None:
        return sa_env, src_env
    if src_env != "not_set":
        return None, src_env

    try:
        from app.infra.translators.provider_config_manager import ProviderConfigManager

        mt_cfg = ProviderConfigManager(settings=settings)
        mt_provider_cfg = mt_cfg.load_config("google_cloud_translate")
        mt_path = str(mt_provider_cfg.auth.service_account_path or "").strip()
        if mt_path:
            candidate = Path(mt_path).expanduser()
            if candidate.exists():
                sa, status = _load_service_account_file(candidate)
                if sa:
                    return sa, "settings_path:google_cloud_translate"
                return None, f"settings_path:google_cloud_translate ({status})"
    except Exception:
        pass

    try:
        from app.infra.audio.audio_provider_config_manager import AudioProviderConfigManager

        audio_cfg = AudioProviderConfigManager(settings=settings)
        tts_cfg = audio_cfg.load_config("google_cloud_tts")
        tts_path = str(tts_cfg.service_account_path or "").strip()
        if tts_path:
            candidate = Path(tts_path).expanduser()
            if candidate.exists():
                sa, status = _load_service_account_file(candidate)
                if sa:
                    return sa, "settings_path:google_cloud_tts"
                return None, f"settings_path:google_cloud_tts ({status})"
    except Exception:
        pass

    return None, "none"


def _load_service_account_info_from_credential_store(
    settings: SettingsService,
) -> tuple[dict[str, Any] | None, str]:
    try:
        from app.infra.translators.provider_config_manager import ProviderConfigManager

        mt_cfg = ProviderConfigManager(settings=settings)
        mt_provider_cfg = mt_cfg.load_config("google_cloud_translate")
        cred_id = mt_provider_cfg.auth.service_account_credential_id
        if cred_id:
            raw = mt_cfg.get_credential(cred_id)
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data, "credential_store:google_cloud_translate"
    except Exception:
        pass

    try:
        from app.infra.audio.audio_provider_config_manager import AudioProviderConfigManager

        audio_cfg = AudioProviderConfigManager(settings=settings)
        tts_cfg = audio_cfg.load_config("google_cloud_tts")
        cred_id = tts_cfg.service_account_credential_id
        if cred_id:
            raw = audio_cfg.get_credential(cred_id)
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data, "credential_store:google_cloud_tts"
    except Exception:
        pass

    return None, "none"


def _candidate_db_paths_for_credentials(
    settings: SettingsService,
    db_path_arg: str | None,
) -> list[Path]:
    candidates: list[Path] = []
    if db_path_arg:
        resolved = resolve_db_path(db_path_arg, settings=settings).path
        candidates.append(Path(resolved).resolve())
    else:
        default_db = get_default_db_path(settings=settings)
        candidates.append(Path(default_db).resolve())
        active_db = resolve_db_path(None, settings=settings).path
        active_db = Path(active_db).resolve()
        if active_db not in candidates:
            candidates.append(active_db)
    return candidates


def _run_cloud_tests_self_check(
    settings: SettingsService,
    db_path_arg: str | None,
) -> tuple[int, dict[str, Any]]:
    from app.services.db_service import DBService

    payload: dict[str, Any] = {
        "mode": "cloud_tests",
        "timestamp_utc": _utc_now_iso(),
        "tests": {},
    }

    translate_sa, translate_source = _load_service_account_from_env_key(
        "HDLE_GCP_TRANSLATE_SA_JSON_PATH"
    )
    tts_sa, tts_source = _load_service_account_from_env_key(
        "HDLE_GCP_TTS_SA_JSON_PATH"
    )
    shared_sa, shared_source = _load_service_account_info_from_env_or_paths(settings)

    if translate_sa is None:
        translate_sa = shared_sa
        if translate_source == "not_set":
            translate_source = shared_source
    if tts_sa is None:
        tts_sa = shared_sa
        if tts_source == "not_set":
            tts_source = shared_source

    payload["credential_sources"] = {
        "translate": translate_source,
        "tts": tts_source,
        "shared": shared_source,
    }

    if not translate_sa or not tts_sa:
        attempts: list[dict[str, str]] = []
        for db_candidate in _candidate_db_paths_for_credentials(settings, db_path_arg):
            db_initialized = False
            attempt: dict[str, str] = {"db_path": str(db_candidate)}
            try:
                DBService.initialize(db_candidate)
                db_initialized = True
                attempt["db_init"] = "ok"

                store_sa, credential_source = _load_service_account_info_from_credential_store(settings)
                attempt["credential_source"] = credential_source
                if store_sa:
                    if translate_sa is None:
                        translate_sa = store_sa
                    if tts_sa is None:
                        tts_sa = store_sa
                    payload["credential_db_path"] = str(db_candidate)
                    attempts.append(attempt)
                    if translate_sa and tts_sa:
                        break
                attempt["result"] = "no_credentials"
            except Exception as exc:
                attempt["db_init"] = "error"
                attempt["error"] = str(exc)
            finally:
                if db_initialized:
                    try:
                        DBService.shutdown()
                    except Exception:
                        pass
            attempts.append(attempt)
        payload["credential_db_attempts"] = attempts

    if not translate_sa or not tts_sa:
        payload["ok"] = False
        payload["error"] = (
            "Google Cloud service account credentials not found. "
            "Provide HDLE_GCP_SA_JSON_PATH (or provider-specific "
            "HDLE_GCP_TRANSLATE_SA_JSON_PATH / HDLE_GCP_TTS_SA_JSON_PATH) "
            "pointing to Service Account JSON "
            "(API keys are not supported for this cloud self-check) or configure CredentialStore."
        )
        return 1, payload

    payload["credential_meta"] = {
        "translate_project_id": _redact_value(str(translate_sa.get("project_id", ""))),
        "translate_client_email": _redact_value(str(translate_sa.get("client_email", ""))),
        "tts_project_id": _redact_value(str(tts_sa.get("project_id", ""))),
        "tts_client_email": _redact_value(str(tts_sa.get("client_email", ""))),
    }

    from app.infra.translators.base_provider import TranslationRequest
    from app.infra.translators.provider_config import (
        ProviderAuthConfig,
        ProviderAuthMode,
        ProviderConfig,
    )
    from app.infra.translators.providers.google_cloud_translate_provider import (
        GoogleCloudTranslateProvider,
    )
    from app.infra.audio.audio_provider_config import (
        AudioProviderAuthMode,
        AudioProviderConfig,
    )
    from app.infra.audio.providers.google_cloud_tts_provider import GoogleCloudTTSProvider

    class _InlineTranslateConfig:
        def __init__(self, inline_sa: dict[str, Any]):
            self._inline_sa = inline_sa

        def load_config(self, provider_id: str):
            return ProviderConfig(
                provider_id=provider_id,
                auth=ProviderAuthConfig(
                    mode=ProviderAuthMode.SERVICE_ACCOUNT_JSON,
                    service_account_credential_id="self_check:gcp_sa",
                ),
            )

        def get_credential(self, credential_id: str):
            return json.dumps(self._inline_sa)

    class _InlineAudioConfig:
        def __init__(self, inline_sa: dict[str, Any]):
            self._inline_sa = inline_sa

        def load_config(self, provider_id: str):
            return AudioProviderConfig(
                provider_id=provider_id,
                enabled=True,
                auth_mode=AudioProviderAuthMode.SERVICE_ACCOUNT_JSON,
                timeout_seconds=10.0,
                retry_max_attempts=1,
            )

        def get_service_account_info(self, cfg):
            return self._inline_sa

    translate_ok = False
    try:
        tr_provider = GoogleCloudTranslateProvider(
            config_manager=_InlineTranslateConfig(translate_sa)
        )
        health_ok = tr_provider.healthcheck()
        tr_result = tr_provider.translate(
            TranslationRequest(
                source_text="שלום",
                source_lang="he",
                target_lang="en",
                trace_id="self-check-cloud-translate",
            )
        )
        translate_ok = bool(getattr(tr_result, "is_success", False))
        error_message = str(getattr(tr_result, "error_message", "") or "")
        if (not translate_ok) and (not error_message) and (not health_ok):
            error_message = "Provider healthcheck failed."
        payload["tests"]["google_cloud_translate"] = {
            "ok": translate_ok,
            "health_ok": bool(health_ok),
            "error_kind": getattr(tr_result, "error_kind", None),
            "error_message": error_message,
            "translated_preview": (
                str(getattr(tr_result, "translated_text", ""))[:48] if translate_ok else ""
            ),
        }
    except Exception as exc:
        payload["tests"]["google_cloud_translate"] = {
            "ok": False,
            "error_message": str(exc),
        }

    tts_ok = False
    try:
        tts_provider = GoogleCloudTTSProvider(config_manager=_InlineAudioConfig(tts_sa))
        voices, err = tts_provider.list_voices(language_code="he-IL")
        tts_ok = err is None
        payload["tests"]["google_cloud_tts"] = {
            "ok": tts_ok,
            "error_message": err or "",
            "voices_count": len(voices or []),
        }
    except Exception as exc:
        payload["tests"]["google_cloud_tts"] = {
            "ok": False,
            "error_message": str(exc),
        }

    payload["ok"] = bool(translate_ok and tts_ok)
    return (0 if payload["ok"] else 1), payload

def run_self_check(mode: str, *, db_path_arg: str | None) -> tuple[int, dict[str, Any]]:
    from app.infra.settings import SettingsService

    settings = SettingsService.get_instance()
    if mode == "import":
        exit_code, payload = _run_import_self_check(settings)
    elif mode == "db_open":
        exit_code, payload = _run_db_open_self_check(settings, db_path_arg)
    elif mode == "health":
        exit_code, payload = _run_health_self_check(settings, db_path_arg)
    elif mode == "cloud_tests":
        exit_code, payload = _run_cloud_tests_self_check(settings, db_path_arg)
    else:
        exit_code, payload = 1, {
            "mode": mode,
            "timestamp_utc": _utc_now_iso(),
            "ok": False,
            "error": f"Unknown self-check mode: {mode}",
        }
    return exit_code, _attach_build_meta(payload)


def main():
    """Main application entry point."""
    compat_exit = _handle_embedded_python_compat(sys.argv)
    if compat_exit is not None:
        return compat_exit

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="HDLE Premium - Terminology Extraction Tool")
    parser.add_argument(
        "--db-path",
        type=str,
        help="Path to database file (default: $LOCALAPPDATA/HDLE/hdle.db)",
    )
    parser.add_argument(
        "--open-resources-manager",
        action="store_true",
        help="Open Resources Manager on startup",
    )
    parser.add_argument(
        "--run-health-check",
        action="store_true",
        help="Run unified health check on startup",
    )
    parser.add_argument(
        "--self-check",
        choices=["import", "db_open", "health", "cloud_tests"],
        help="Run headless self-check mode and print JSON result",
    )
    parser.add_argument(
        "--self-check-out",
        type=str,
        help="Optional path to write self-check JSON payload",
    )
    args = parser.parse_args()

    if args.self_check:
        logging.disable(logging.CRITICAL)
        exit_code, payload = run_self_check(args.self_check, db_path_arg=args.db_path)
        _emit_self_check(payload, out_path=args.self_check_out)
        return exit_code

    # Import heavy Qt/UI modules only for normal app startup.
    # Keep self-check and subprocess bridge paths independent from GUI imports.
    from PyQt6.QtWidgets import QApplication
    from app.infra.resource_paths import ResourcePaths
    from app.infra.settings import SettingsService
    from app.infra.util.logging import setup_logging
    from app.services.db_service import DBService
    from app.infra.translators.local_providers_setup import (
        register_google_translate,
        register_google_cloud_translate,
    )
    from app.ui.app_window import AppWindow

    settings = SettingsService.get_instance()

    # Setup directories
    app_paths = ResourcePaths.build(settings=settings, create=True)
    app_dir = app_paths.data_root
    log_dir = app_paths.logs_root

    # Resolve database path with deterministic precedence:
    # CLI --db-path > ENV HDLE_DB_PATH (existing file) > settings > default.
    startup_db = choose_startup_db_path(
        args.db_path,
        settings=settings,
    )
    resolved_db = startup_db.resolved
    db_path = Path(resolved_db.path).resolve()

    # Setup logging
    setup_logging(log_dir, level=logging.INFO)
    logger.info("=" * 60)
    logger.info("HDLE Premium starting")
    logger.info(format_build_meta_line())
    logger.info(f"App directory: {app_dir}")
    logger.info(f"Database: {db_path}")
    logger.info(f"Database source: {resolved_db.source}")
    if startup_db.deferred_original_path is not None:
        logger.warning(
            "Startup DB deferred: opening default DB instead of legacy settings DB %s. Reason: %s",
            startup_db.deferred_original_path,
            startup_db.deferred_reason,
        )
    logger.info("=" * 60)

    app_lock = None
    try:
        app_lock, lock_error = _acquire_app_instance_lock(app_dir, timeout_seconds=1)
        if app_lock is None:
            logger.error("Application instance lock acquisition failed: %s", lock_error)
            print("Another HDLE Premium instance is already running.", file=sys.stderr)
            return 2

        # Initialize database
        DBService.initialize(db_path)
        logger.info("Database initialized")

        # Crash recovery (mark unfinished runs as failed)
        db_service = DBService.get_instance()
        recovered_count = db_service.recover_from_crash()
        if recovered_count > 0:
            logger.warning(f"Crash recovery: marked {recovered_count} runs as failed")

        # PERF-SCALE PATCH-A: mount read-only reference DBs.
        # Scan dict_project for is_reference=1 rows and attach each ref_db_path
        # as a ReadOnlyDatabaseManager so get_ref_session() works throughout the session.
        try:
            from sqlalchemy import text as _sa_text
            with db_service.get_session() as _s:
                _ref_rows = _s.execute(
                    _sa_text(
                        "SELECT project_id, ref_db_path FROM dict_project "
                        "WHERE is_reference=1 AND ref_db_path IS NOT NULL"
                    )
                ).fetchall()
            for _pid, _rpath in _ref_rows:
                try:
                    DBService.attach_reference(_pid, _rpath)
                    logger.info(
                        "Reference DB attached: project %d → %s", _pid, _rpath
                    )
                except FileNotFoundError:
                    logger.warning(
                        "Reference DB file not found for project %d (path: %s); "
                        "project will remain read-only in UI but physical RO mount skipped.",
                        _pid, _rpath,
                    )
        except Exception as _ref_err:
            logger.warning("Reference DB attach scan failed (non-fatal): %s", _ref_err)

        # Initialize local MT providers (lazy - on first use)
        # NOTE: Providers are initialized when first needed to avoid blocking app startup
        # Model loading can take 30-60 seconds, so we defer it until actual translation request
        logger.info("Local MT providers will be initialized on first use (lazy loading)")

        # Register Google Translate (always available, no model needed)
        register_google_translate()
        logger.info("Google Translate provider registered")

        # Register Google Cloud Translate (Official API v3)
        # Note: Provider creates DB sessions as needed for usage tracking
        register_google_cloud_translate()
        logger.info("Google Cloud Translate provider registered")

        # Create Qt application
        app = QApplication(sys.argv)
        app.setOrganizationName("HDLE_Premium")
        app.setApplicationName("HDLE_Premium")

        # Create and show main window
        startup_actions = []
        if args.open_resources_manager:
            startup_actions.append("open_resources")
        if args.run_health_check:
            startup_actions.append("run_health_check")

        window = AppWindow(startup_actions=startup_actions)
        window.show()

        logger.info("Application window shown")

        # Run event loop
        exit_code = app.exec()

        # Cleanup
        DBService.shutdown()
        logger.info(f"Application exiting with code {exit_code}")

        return exit_code

    except Exception as e:
        logger.exception("Fatal error")
        print(f"Fatal error: {e}", file=sys.stderr)
        return 1
    finally:
        _release_app_instance_lock(app_lock)


if __name__ == "__main__":
    sys.exit(main())
