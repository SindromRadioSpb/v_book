"""HDLE Premium - Main entry point."""
import sys
import json
import time
import sqlite3
import logging
import argparse
import importlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PyQt6.QtWidgets import QApplication

from app.infra.db_path_resolver import get_default_db_path, resolve_db_path
from app.infra.resource_paths import ResourcePaths
from app.infra.settings import SettingsService
from app.infra.util.logging import setup_logging
from app.services.db_service import DBService
from app.services.health_check_service import HealthCheckService
from app.services.resources import ResourceRegistry
from app.infra.translators.local_providers_setup import (
    initialize_local_providers,
    register_google_translate,
    register_google_cloud_translate,
)
from app.ui.app_window import AppWindow

logger = logging.getLogger(__name__)

_PHONIKUD_SUBPROCESS_SENTINELS = (
    "phonikud_onnx",
    "Phonikud",
    "add_diacritics",
    "json.loads",
    "outputs",
)


def get_app_dir() -> Path:
    r"""Get the application data directory.

    Default locations:
    - Windows: %LOCALAPPDATA%\HDLE
    - macOS: ~/Library/Application Support/HDLE
    - Linux: ~/.local/share/hdle
    """
    return ResourcePaths.resolve_data_root(create=True)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact_value(value: str, *, keep_prefix: int = 3, keep_suffix: int = 2) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) <= (keep_prefix + keep_suffix):
        return "*" * len(text)
    return f"{text[:keep_prefix]}***{text[-keep_suffix:]}"


def _emit_self_check(payload: dict[str, Any], out_path: str | None = None) -> None:
    text_payload = json.dumps(payload, ensure_ascii=False, indent=2)
    if out_path:
        out_file = Path(out_path).expanduser().resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(text_payload + "\n", encoding="utf-8")
    print(text_payload)


def _is_phonikud_subprocess_script(script: str) -> bool:
    snippet = (script or "").strip()
    if not snippet:
        return False
    lowered = snippet.lower()
    return all(token.lower() in lowered for token in _PHONIKUD_SUBPROCESS_SENTINELS)


def _run_phonikud_subprocess_bridge() -> int:
    try:
        from phonikud_onnx import Phonikud
    except Exception as exc:
        print(f"phonikud_subprocess_bridge import error: {exc}", file=sys.stderr)
        return 1

    try:
        raw = sys.stdin.read() or "{}"
        data = json.loads(raw)
        model_path = str(data.get("model_path") or "")
        texts = data.get("texts") or []
        model = Phonikud(model_path)
        outputs: list[str] = []
        for text in texts:
            normalized = str(text or "")
            try:
                rendered = str(model.add_diacritics(normalized) or "").strip()
            except Exception:
                rendered = ""
            outputs.append(rendered or normalized)
        sys.stdout.write(json.dumps({"outputs": outputs}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"phonikud_subprocess_bridge runtime error: {exc}", file=sys.stderr)
        return 1


def _handle_embedded_python_compat(argv: list[str]) -> int | None:
    if len(argv) < 3 or argv[1] != "-c":
        return None
    inline_script = argv[2]
    if _is_phonikud_subprocess_script(inline_script):
        return _run_phonikud_subprocess_bridge()
    return None


def _run_import_self_check(settings: SettingsService) -> tuple[int, dict[str, Any]]:
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

    ok = bool(payload["checks"]["phonikud_import"]["ok"])
    return (0 if ok else 1), payload


def _run_db_open_self_check(settings: SettingsService, db_path_arg: str | None) -> tuple[int, dict[str, Any]]:
    resolved_db = resolve_db_path(db_path_arg, settings=settings)
    db_path = Path(resolved_db.path).resolve()
    payload: dict[str, Any] = {
        "mode": "db_open",
        "timestamp_utc": _utc_now_iso(),
        "db_path": str(db_path),
        "db_source": resolved_db.source,
    }

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


def _load_service_account_info_from_env_or_paths(
    settings: SettingsService,
) -> tuple[dict[str, Any] | None, str]:
    env_path = (os.environ.get("HDLE_GCP_SA_JSON_PATH") or "").strip()
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.exists():
            sa, status = _load_service_account_file(candidate)
            if sa:
                return sa, "env:HDLE_GCP_SA_JSON_PATH"
            return None, f"env:HDLE_GCP_SA_JSON_PATH ({status})"
        return None, "env:HDLE_GCP_SA_JSON_PATH (path missing)"

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
    payload: dict[str, Any] = {
        "mode": "cloud_tests",
        "timestamp_utc": _utc_now_iso(),
        "tests": {},
    }

    sa_info, credential_source = _load_service_account_info_from_env_or_paths(settings)
    payload["credential_source"] = credential_source

    if not sa_info:
        attempts: list[dict[str, str]] = []
        for db_candidate in _candidate_db_paths_for_credentials(settings, db_path_arg):
            db_initialized = False
            attempt: dict[str, str] = {"db_path": str(db_candidate)}
            try:
                DBService.initialize(db_candidate)
                db_initialized = True
                attempt["db_init"] = "ok"

                sa_info, credential_source = _load_service_account_info_from_credential_store(settings)
                attempt["credential_source"] = credential_source
                if sa_info:
                    payload["credential_source"] = credential_source
                    payload["credential_db_path"] = str(db_candidate)
                    attempts.append(attempt)
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

    if not sa_info:
        payload["ok"] = False
        payload["error"] = (
            "Google Cloud service account credentials not found. "
            "Provide HDLE_GCP_SA_JSON_PATH pointing to Service Account JSON "
            "(API keys are not supported for this cloud self-check) or configure CredentialStore."
        )
        return 1, payload

    payload["credential_meta"] = {
        "project_id": _redact_value(str(sa_info.get("project_id", ""))),
        "client_email": _redact_value(str(sa_info.get("client_email", ""))),
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
                enabled=True,
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
            config_manager=_InlineTranslateConfig(sa_info)
        )
        if tr_provider.healthcheck():
            tr_result = tr_provider.translate(
                TranslationRequest(
                    source_text="שלום",
                    source_lang="he",
                    target_lang="en",
                    trace_id="self-check-cloud-translate",
                )
            )
            translate_ok = bool(getattr(tr_result, "is_success", False))
            payload["tests"]["google_cloud_translate"] = {
                "ok": translate_ok,
                "error_kind": getattr(tr_result, "error_kind", None),
                "error_message": getattr(tr_result, "error_message", ""),
                "translated_preview": (
                    str(getattr(tr_result, "translated_text", ""))[:48] if translate_ok else ""
                ),
            }
        else:
            payload["tests"]["google_cloud_translate"] = {
                "ok": False,
                "error_message": "Provider healthcheck failed.",
            }
    except Exception as exc:
        payload["tests"]["google_cloud_translate"] = {
            "ok": False,
            "error_message": str(exc),
        }

    tts_ok = False
    try:
        tts_provider = GoogleCloudTTSProvider(config_manager=_InlineAudioConfig(sa_info))
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
    settings = SettingsService.get_instance()
    if mode == "import":
        return _run_import_self_check(settings)
    if mode == "db_open":
        return _run_db_open_self_check(settings, db_path_arg)
    if mode == "health":
        return _run_health_self_check(settings, db_path_arg)
    if mode == "cloud_tests":
        return _run_cloud_tests_self_check(settings, db_path_arg)
    return 1, {
        "mode": mode,
        "timestamp_utc": _utc_now_iso(),
        "ok": False,
        "error": f"Unknown self-check mode: {mode}",
    }


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

    settings = SettingsService.get_instance()

    # Setup directories
    app_paths = ResourcePaths.build(settings=settings, create=True)
    app_dir = app_paths.data_root
    log_dir = app_paths.logs_root

    # Resolve database path with deterministic precedence:
    # CLI --db-path > ENV HDLE_DB_PATH (existing file) > settings > default.
    resolved_db = resolve_db_path(
        args.db_path,
        settings=settings,
    )
    db_path = Path(resolved_db.path).resolve()

    # Setup logging
    setup_logging(log_dir, level=logging.INFO)
    logger.info("=" * 60)
    logger.info("HDLE Premium starting")
    logger.info(f"App directory: {app_dir}")
    logger.info(f"Database: {db_path}")
    logger.info(f"Database source: {resolved_db.source}")
    logger.info("=" * 60)

    try:
        # Initialize database
        DBService.initialize(db_path)
        logger.info("Database initialized")

        # Crash recovery (mark unfinished runs as failed)
        db_service = DBService.get_instance()
        recovered_count = db_service.recover_from_crash()
        if recovered_count > 0:
            logger.warning(f"Crash recovery: marked {recovered_count} runs as failed")

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


if __name__ == "__main__":
    sys.exit(main())

