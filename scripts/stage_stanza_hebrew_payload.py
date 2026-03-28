from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from app.services.nlp_runtime.managed_runtime import ManagedStanzaRuntime


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _resolve_candidate_roots() -> list[Path]:
    candidates: list[Path] = []

    env_source = os.getenv("HDLE_REQUIRED_STANZA_HEBREW_SOURCE", "").strip()
    if env_source:
        candidates.append(Path(env_source).expanduser())

    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        cache_root = Path(local_app_data) / "StanfordNLP" / "stanza" / "Cache"
        if cache_root.exists():
            for version_dir in sorted(cache_root.iterdir(), reverse=True):
                if version_dir.is_dir():
                    candidates.append(version_dir / "resources")

    candidates.append(Path.home() / "stanza_resources")
    candidates.append(
        Path("installer/resources/local_models/stanza_hebrew/stanza_resources").resolve()
    )
    return candidates


def _normalize_source(source: Path) -> tuple[Path, Path] | None:
    source = source.expanduser().resolve()
    if source.is_file():
        return None

    if source.name == "he":
        resources_root = source.parent
        model_path = source
    elif (source / "he").exists():
        resources_root = source
        model_path = source / "he"
    elif (source / "resources" / "he").exists():
        resources_root = source / "resources"
        model_path = resources_root / "he"
    else:
        return None

    if not (resources_root / "resources.json").exists():
        return None

    missing = [
        entry
        for entry in ManagedStanzaRuntime._REQUIRED_MODEL_ENTRIES
        if not (model_path / entry).exists()
    ]
    if missing:
        return None

    return resources_root, model_path


def _stage_payload(*, source_resources_root: Path, source_model_path: Path, target_root: Path) -> dict[str, object]:
    target_root.mkdir(parents=True, exist_ok=True)
    payload_root = target_root / "stanza_resources"
    target_model_path = payload_root / "he"

    if payload_root.exists():
        shutil.rmtree(payload_root, ignore_errors=True)

    payload_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_resources_root / "resources.json", payload_root / "resources.json")
    shutil.copytree(source_model_path, target_model_path)

    payload_manifest = {
        "schema_version": 1,
        "payload_kind": "stanza_hebrew_bundled_payload",
        "layout_version": 1,
        "model_lang": "he",
        "required_entries": list(ManagedStanzaRuntime._REQUIRED_MODEL_ENTRIES),
        "resources_root_relative": "stanza_resources",
        "model_path_relative": "stanza_resources/he",
        "staged_at_utc": _utc_now_iso(),
        "source_resources_root": str(source_resources_root),
        "source_model_path": str(source_model_path),
    }
    payload_manifest_path = target_root / "payload_manifest.json"
    payload_manifest_path.write_text(
        json.dumps(payload_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "target_root": str(target_root),
        "payload_manifest": str(payload_manifest_path),
        "payload_model_path": str(target_model_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage bundled Hebrew Stanza payload for release builds.")
    parser.add_argument(
        "--target-root",
        type=Path,
        default=Path("installer/resources/local_models/stanza_hebrew"),
        help="Target staging directory for the bundled Hebrew payload.",
    )
    args = parser.parse_args()

    selected: tuple[Path, Path] | None = None
    selected_source: Path | None = None
    for candidate in _resolve_candidate_roots():
        normalized = _normalize_source(candidate)
        if normalized is not None:
            selected = normalized
            selected_source = candidate.expanduser().resolve()
            break

    if selected is None or selected_source is None:
        raise SystemExit(
            "No valid Hebrew Stanza payload source found. "
            "Set HDLE_REQUIRED_STANZA_HEBREW_SOURCE or provide a valid local cache."
        )

    source_resources_root, source_model_path = selected
    staged = _stage_payload(
        source_resources_root=source_resources_root,
        source_model_path=source_model_path,
        target_root=args.target_root.resolve(),
    )
    result = {
        "ok": True,
        "source_root": str(selected_source),
        "source_resources_root": str(source_resources_root),
        "source_model_path": str(source_model_path),
        **staged,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
