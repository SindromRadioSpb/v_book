"""Subprocess worker for Stanza NLP runtime.

Runs a real in-process Stanza pipeline in a clean Python process and exposes
it over a tiny JSON-lines protocol. This avoids hostile DLL/import state in
the main Qt process while preserving the same NLP contract.
"""

from __future__ import annotations

import json
import os
import sys

from app.infra.nlp_engines.stanza_engine import StanzaEngine
from app.services.nlp_runtime.managed_runtime import ManagedStanzaRuntime


def _configure_stdio_for_json_protocol() -> None:
    """Force UTF-8 JSON lines across worker pipes on Windows and packaged runs."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    _configure_stdio_for_json_protocol()
    use_gpu = os.getenv("HDLE_STANZA_WORKER_MODE", "cpu").strip().lower() == "gpu"
    runtime = ManagedStanzaRuntime()
    bootstrap = runtime.bootstrap_runtime(force_repair=False)
    os.environ["STANZA_RESOURCES_DIR"] = str(bootstrap.resources_root)

    try:
        engine = StanzaEngine(use_gpu=use_gpu)
    except Exception as exc:
        _emit({"ok": False, "error": str(exc)})
        return 1

    _emit(
        {
            "ok": True,
            "name": engine.get_name(),
            "version": engine.get_version(),
            "model_path": str(bootstrap.model_path),
        }
    )

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
            command = str(request.get("command") or "").strip().lower()
        except Exception as exc:
            _emit({"ok": False, "error": f"Invalid request: {exc}"})
            continue

        try:
            if command == "shutdown":
                _emit({"ok": True, "status": "bye"})
                return 0

            if command == "metadata":
                _emit(
                    {
                        "ok": True,
                        "name": engine.get_name(),
                        "version": engine.get_version(),
                        "model_path": str(bootstrap.model_path),
                    }
                )
                continue

            if command == "process":
                sentences = engine.process(str(request.get("text") or ""))
                _emit(
                    {
                        "ok": True,
                        "sentences": [
                            {
                                "text": sentence.text,
                                "tokens": [
                                    {
                                        "text": token.text,
                                        "lemma": token.lemma,
                                        "pos": token.pos,
                                        "morph": token.morph,
                                    }
                                    for token in sentence.tokens
                                ],
                            }
                            for sentence in sentences
                        ],
                    }
                )
                continue

            _emit({"ok": False, "error": f"Unknown command: {command}"})
        except Exception as exc:
            _emit({"ok": False, "error": str(exc)})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
