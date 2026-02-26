"""Console helper for deterministic ONNX runtime probing/inference in frozen builds."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_NIKUD_RE = re.compile(r"[\u0591-\u05c7]")
_DEFAULT_SAMPLE_TEXT = "\u05d1\u05d9\u05ea \u05e1\u05e4\u05e8"
_DLL_DIR_HANDLES: list[object] = []
_DLL_DIR_KEYS: set[str] = set()


def _sanitize_model_path(raw_value: str) -> str:
    value = (raw_value or "").strip()
    if not value:
        return ""
    return value.strip("\"'").rstrip(" .")


def _register_dll_directory(path: Path) -> None:
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return
    try:
        resolved = str(path.resolve())
    except Exception:
        resolved = str(path)
    key = resolved.lower()
    if key in _DLL_DIR_KEYS:
        return
    if not Path(resolved).exists():
        return
    try:
        handle = os.add_dll_directory(resolved)
    except Exception:
        return
    _DLL_DIR_HANDLES.append(handle)
    _DLL_DIR_KEYS.add(key)


def _prepare_runtime_dll_paths() -> None:
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
        _register_dll_directory(Path(resolved))
        if resolved.lower() not in normalized_path and resolved not in prefix_parts:
            prefix_parts.append(resolved)
    if prefix_parts:
        os.environ["PATH"] = ";".join(prefix_parts + [existing_path]) if existing_path else ";".join(prefix_parts)


def _contains_niqqud(text: str) -> bool:
    return bool(_NIKUD_RE.search(str(text or "")))


def _read_infer_payload() -> list[str]:
    try:
        raw = sys.stdin.read() or "{}"
        data = json.loads(raw)
        if not isinstance(data, dict):
            return []
        texts = data.get("texts") or []
        if not isinstance(texts, list):
            return []
        return [str(item or "") for item in texts]
    except Exception:
        return []


def _discover_default_model_path() -> Path | None:
    try:
        from app.infra.resource_paths import ResourcePaths

        models_root = ResourcePaths.build(create=False).models_root
        phonikud_dir = models_root / "phonikud"
        if phonikud_dir.exists():
            preferred = sorted(phonikud_dir.glob("*int8.onnx"))
            if preferred:
                return preferred[0]
            regular = sorted(phonikud_dir.glob("*.onnx"))
            if regular:
                return regular[0]
    except Exception:
        pass
    return None


def _ensure_hf_home() -> None:
    configured = (os.getenv("HF_HOME") or "").strip()
    if configured:
        configured_path = Path(configured)
        try:
            configured_path.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=str(configured_path), prefix="hf_write_test_", delete=True):
                pass
            return
        except Exception:
            pass

    candidates = [
        Path.cwd() / "build" / "hf_cache",
        Path(__file__).resolve().parent.parent.parent / "build" / "hf_cache",
    ]
    local_app_data = (os.getenv("LOCALAPPDATA") or "").strip()
    if local_app_data:
        candidates.append(Path(local_app_data) / "HDLE" / "hf_cache")

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=str(candidate), prefix="hf_write_test_", delete=True):
                pass
            os.environ["HF_HOME"] = str(candidate)
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            return
        except Exception:
            continue


def _resolve_model_path(model_path_arg: str) -> Path | None:
    direct = _sanitize_model_path(model_path_arg)
    if not direct:
        direct = _sanitize_model_path(os.getenv("PHONIKUD_MODEL_PATH") or "")

    if direct:
        path = Path(direct).expanduser()
        if path.is_file() and path.suffix.lower() == ".onnx":
            return path
        if path.is_dir():
            preferred = sorted(path.glob("*int8.onnx"))
            if preferred:
                return preferred[0]
            regular = sorted(path.glob("*.onnx"))
            if regular:
                return regular[0]
        if path.suffix.lower() != ".onnx":
            candidate = Path(str(path) + ".onnx")
            if candidate.is_file():
                return candidate
            parent = path.parent
            if parent.exists() and parent.is_dir():
                matches = sorted(parent.glob(f"{path.name}*.onnx"))
                if matches:
                    return matches[0]
        if path.suffix.lower() == ".onnx":
            return path
        return None

    return _discover_default_model_path()


def _base_report(mode: str) -> dict[str, Any]:
    return {
        "ok": False,
        "mode": mode,
        "stage": "import",
        "error": "",
        "details": "",
        "elapsed_ms": 0,
        "model_path": "",
        "sample_input": "",
        "sample_output": "",
        "has_niqqud": False,
        "outputs": [],
        "onnxruntime_origin": "",
    }


def run(mode: str, *, model_path_arg: str, sample_text: str) -> tuple[int, dict[str, Any]]:
    started = time.perf_counter()
    report = _base_report(mode)

    _prepare_runtime_dll_paths()
    _ensure_hf_home()

    try:
        ort_module = importlib.import_module("onnxruntime")
        report["onnxruntime_origin"] = str(getattr(ort_module, "__file__", "") or "")
        phonikud_onnx = importlib.import_module("phonikud_onnx")
        phonikud_cls = getattr(phonikud_onnx, "Phonikud", None)
        if phonikud_cls is None:
            raise RuntimeError("phonikud_onnx.Phonikud not found")
    except Exception as exc:
        report["stage"] = "import"
        report["error"] = str(exc)
        report["details"] = "Failed to import ONNX runtime backend."
        report["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return 1, report

    if mode == "import":
        report["ok"] = True
        report["stage"] = "import"
        report["details"] = "onnxruntime and phonikud_onnx imports succeeded"
        report["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return 0, report

    model_path = _resolve_model_path(model_path_arg)
    if model_path is None:
        report["stage"] = "model_load"
        report["error"] = "Phonikud ONNX model path is not configured or not found."
        report["details"] = "Configure pronunciation/phonikud/model_path or install local phonikud model resources."
        report["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return 1, report

    report["model_path"] = str(model_path)

    try:
        model = phonikud_cls(str(model_path))
    except Exception as exc:
        report["stage"] = "model_load"
        report["error"] = str(exc)
        report["details"] = "Failed to initialize phonikud ONNX model."
        report["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return 1, report

    if mode == "infer":
        report["stage"] = "infer"
        texts = _read_infer_payload()
        outputs: list[str] = []
        for text in texts:
            source = str(text or "")
            try:
                rendered = str(model.add_diacritics(source) or "").strip()
            except Exception:
                rendered = ""
            outputs.append(rendered or source)
        report["outputs"] = outputs
        report["ok"] = True
        report["details"] = "inference completed"
        report["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return 0, report

    report["stage"] = "infer"
    report["sample_input"] = str(sample_text or _DEFAULT_SAMPLE_TEXT)
    try:
        sample_output = str(model.add_diacritics(report["sample_input"]) or "").strip()
    except Exception as exc:
        report["error"] = str(exc)
        report["details"] = "Failed to run ONNX sample inference."
        report["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return 1, report

    report["sample_output"] = sample_output
    report["has_niqqud"] = _contains_niqqud(sample_output)
    if not report["has_niqqud"]:
        report["error"] = "Sample inference returned output without niqqud marks."
        report["details"] = "Probe detected fallback/identity-like output."
        report["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return 1, report

    report["ok"] = True
    report["details"] = "real_inference"
    report["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    return 0, report


def _emit_report(report: dict[str, Any], out_path: str) -> None:
    # Keep output ASCII-safe for Windows console code pages in frozen runtime.
    text_payload = json.dumps(report, ensure_ascii=True, indent=2)
    if out_path:
        out_file = Path(out_path).expanduser().resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(text_payload + "\n", encoding="utf-8")
    print(text_payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="HDLE frozen ONNX runtime probe helper")
    parser.add_argument("--mode", choices=["import", "probe", "infer"], default="probe")
    parser.add_argument("--model-path", type=str, default="")
    parser.add_argument("--sample-text", type=str, default=_DEFAULT_SAMPLE_TEXT)
    parser.add_argument("--timeout-ms", type=int, default=3000)
    parser.add_argument("--out", type=str, default="")
    args = parser.parse_args()

    # Timeout is enforced by caller; keep flag for explicit IO contract stability.
    _ = args.timeout_ms

    exit_code, payload = run(
        args.mode,
        model_path_arg=args.model_path,
        sample_text=args.sample_text,
    )
    _emit_report(payload, out_path=args.out)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
