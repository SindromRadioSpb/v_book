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


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    use_gpu = os.getenv("HDLE_STANZA_WORKER_MODE", "cpu").strip().lower() == "gpu"

    try:
        engine = StanzaEngine(use_gpu=use_gpu)
    except Exception as exc:
        _emit({"ok": False, "error": str(exc)})
        return 1

    _emit({"ok": True, "name": engine.get_name(), "version": engine.get_version()})

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
                _emit({"ok": True, "name": engine.get_name(), "version": engine.get_version()})
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
