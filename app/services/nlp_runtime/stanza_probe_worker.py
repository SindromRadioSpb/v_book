"""Headless subprocess probe for the managed Stanza runtime."""

from __future__ import annotations

import json
import os
import sys

from app.services.nlp_runtime.managed_runtime import ManagedStanzaRuntime


def _emit(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    runtime = ManagedStanzaRuntime()
    bootstrap = runtime.bootstrap_runtime(force_repair=False)
    mode = os.getenv("HDLE_STANZA_PROBE_MODE", "cpu").strip().lower() or "cpu"
    smoke = os.getenv("HDLE_STANZA_PROBE_SMOKE", "0") == "1"

    payload: dict[str, object] = {
        "package_installed": False,
        "model_present": bool(bootstrap.model_present),
        "pipeline_init_ok": False,
        "smoke_ok": False,
        "cuda_available": False,
        "engine_version": None,
        "torch_version": None,
        "torch_cuda_version": None,
        "model_path": str(bootstrap.model_path),
        "smoke_requested": smoke,
        "error_code": None,
        "error_detail": None,
        "managed_runtime": bootstrap.to_dict(),
    }

    try:
        import stanza
    except ImportError as exc:
        payload["error_code"] = "package_missing"
        payload["error_detail"] = str(exc)
        _emit(payload)
        return 0
    except OSError as exc:
        payload["package_installed"] = True
        payload["error_code"] = "hostile_torch_state"
        payload["error_detail"] = str(exc)
        _emit(payload)
        return 0
    except Exception as exc:
        payload["package_installed"] = True
        payload["error_code"] = "runtime_import_failed"
        payload["error_detail"] = str(exc)
        _emit(payload)
        return 0

    payload["package_installed"] = True
    payload["engine_version"] = getattr(stanza, "__version__", None)

    try:
        import torch

        payload["cuda_available"] = bool(torch.cuda.is_available())
        payload["torch_version"] = getattr(torch, "__version__", None)
        payload["torch_cuda_version"] = getattr(getattr(torch, "version", None), "cuda", None)
    except OSError as exc:
        payload["error_code"] = "hostile_torch_state"
        payload["error_detail"] = str(exc)
        _emit(payload)
        return 0
    except Exception:
        payload["cuda_available"] = False

    if not bootstrap.model_present:
        payload["error_code"] = "model_missing"
        payload["error_detail"] = bootstrap.message
        _emit(payload)
        return 0

    try:
        pipeline = stanza.Pipeline(
            lang="he",
            processors="tokenize,pos,lemma",
            use_gpu=(mode == "gpu"),
            verbose=False,
            download_method=None,
        )
        payload["pipeline_init_ok"] = True
    except Exception as exc:
        payload["error_code"] = "pipeline_init_failed"
        payload["error_detail"] = str(exc)
        _emit(payload)
        return 0

    if not smoke:
        payload["smoke_ok"] = True
        _emit(payload)
        return 0

    try:
        doc = pipeline("הילד הגדול קורא ספר חדש.")
        payload["smoke_ok"] = bool(doc.sentences)
        if not payload["smoke_ok"]:
            payload["error_code"] = "smoke_failed"
            payload["error_detail"] = "Stanza returned no sentences for the smoke sample."
    except Exception as exc:
        payload["smoke_ok"] = False
        payload["error_code"] = "smoke_failed"
        payload["error_detail"] = str(exc)

    _emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
