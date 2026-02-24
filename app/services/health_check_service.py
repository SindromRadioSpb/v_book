"""Unified health checks for resources, local models, and provider readiness."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

from sqlalchemy import text

from app.infra.audio.audio_provider_config_manager import AudioProviderConfigManager
from app.infra.pronunciation import PhonikudAdapter
from app.infra.settings import SettingsService
from app.infra.translators.provider_config_manager import ProviderConfigManager
from app.services.db_service import DBService
from app.services.resources import ResourceRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HealthCheckItem:
    check_id: str
    title: str
    status: str  # ok|warn|error|optional
    message: str
    remediation: str = ""

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


class HealthCheckService:
    """Centralized health checks with actionable remediation hints."""

    def __init__(self, *, settings: Optional[SettingsService] = None):
        self.settings = settings or SettingsService.get_instance()
        self.resources = ResourceRegistry(settings=self.settings)
        self.audio_cfg = AudioProviderConfigManager(settings=self.settings)
        self.mt_cfg = ProviderConfigManager(settings=self.settings)

    def run_all(self) -> Dict[str, object]:
        items: List[HealthCheckItem] = []
        items.extend(self._check_required_resources())
        items.append(self._check_pronunciation_bootstrap())
        items.append(self._check_sentence_niqqud_bootstrap())
        items.extend(self._check_cloud_providers())
        items.append(self._check_baseline_reference())

        status_rank = {"ok": 0, "optional": 0, "warn": 1, "error": 2}
        overall = "ok"
        for item in items:
            if status_rank.get(item.status, 2) > status_rank.get(overall, 0):
                overall = item.status
        return {
            "overall": overall,
            "items": [item.to_dict() for item in items],
        }

    def _check_required_resources(self) -> List[HealthCheckItem]:
        checks: List[HealthCheckItem] = []
        for entry in self.resources.list_entries():
            status = self.resources.get_status(entry.id)
            if not entry.required:
                continue
            if status.state == "installed":
                checks.append(
                    HealthCheckItem(
                        check_id=f"resource:{entry.id}",
                        title=f"Resource: {entry.display_name}",
                        status="ok",
                        message="Installed and verified.",
                    )
                )
                continue
            if status.state == "corrupted":
                checks.append(
                    HealthCheckItem(
                        check_id=f"resource:{entry.id}",
                        title=f"Resource: {entry.display_name}",
                        status="error",
                        message=status.message,
                        remediation="Open Resources Manager and run Repair.",
                    )
                )
                continue
            checks.append(
                HealthCheckItem(
                    check_id=f"resource:{entry.id}",
                    title=f"Resource: {entry.display_name}",
                    status="error",
                    message=status.message,
                    remediation="Open Resources Manager and install the missing resource.",
                )
            )
        return checks

    def _check_pronunciation_bootstrap(self) -> HealthCheckItem:
        model_path = self.settings.get_string("pronunciation/phonikud/model_path", "")
        enabled = self.settings.get_bool("pronunciation/phonikud/enabled", True)
        report = PhonikudAdapter(model_path=model_path, enabled=enabled).health_check(["שלום", "תחנה"])
        if report.status == "ok":
            return HealthCheckItem(
                check_id="bootstrap:pronunciation",
                title="Pronunciation Bootstrap",
                status="ok",
                message=f"Ready ({report.mode}, {report.latency_ms}ms).",
            )
        status = "warn" if report.status == "fallback" else "error"
        return HealthCheckItem(
            check_id="bootstrap:pronunciation",
            title="Pronunciation Bootstrap",
            status=status,
            message=f"{report.status}: {report.details}",
            remediation="Configure model path in Resources Manager and re-run Health Check.",
        )

    def _check_sentence_niqqud_bootstrap(self) -> HealthCheckItem:
        model_path = self.settings.get_string("pronunciation/phonikud/model_path", "")
        enabled = self.settings.get_bool("pronunciation/phonikud/enabled", True)
        report = PhonikudAdapter(model_path=model_path, enabled=enabled).health_check(["זה מבחן."])
        if report.status == "ok":
            return HealthCheckItem(
                check_id="bootstrap:sentence_niqqud",
                title="Sentence Niqqud Bootstrap",
                status="ok",
                message=f"Ready ({report.mode}, {report.latency_ms}ms).",
            )
        status = "warn" if report.status == "fallback" else "error"
        return HealthCheckItem(
            check_id="bootstrap:sentence_niqqud",
            title="Sentence Niqqud Bootstrap",
            status=status,
            message=f"{report.status}: {report.details}",
            remediation="Install local model resources and retry Health Check.",
        )

    def _check_cloud_providers(self) -> List[HealthCheckItem]:
        checks: List[HealthCheckItem] = []

        # Audio providers (optional readiness)
        for provider_id, title in (
            ("google_cloud_tts", "Cloud Audio: Google TTS"),
            ("azure_speech_tts", "Cloud Audio: Azure Speech"),
        ):
            try:
                cfg = self.audio_cfg.load_config(provider_id)
            except Exception as exc:
                checks.append(
                    HealthCheckItem(
                        check_id=f"cloud_audio:{provider_id}",
                        title=title,
                        status="warn",
                        message=f"Config load failed: {exc}",
                        remediation="Open Audio Provider Settings and reconfigure credentials.",
                    )
                )
                continue
            if not cfg.enabled:
                checks.append(
                    HealthCheckItem(
                        check_id=f"cloud_audio:{provider_id}",
                        title=title,
                        status="optional",
                        message="Provider is disabled.",
                        remediation="Enable provider in Audio Provider Settings if needed.",
                    )
                )
                continue
            configured = bool(
                self.audio_cfg.get_service_account_info(cfg)
                if provider_id == "google_cloud_tts"
                else self.audio_cfg.get_credential(cfg.api_key_credential_id)
            )
            checks.append(
                HealthCheckItem(
                    check_id=f"cloud_audio:{provider_id}",
                    title=title,
                    status="ok" if configured else "warn",
                    message="Configured." if configured else "Enabled but credentials are missing.",
                    remediation="Open Audio Provider Settings > Advanced and load credentials.",
                )
            )

        # MT provider (optional readiness)
        try:
            mt_cfg = self.mt_cfg.load_config("google_cloud_translate")
            configured = mt_cfg.auth.is_configured()
        except Exception:
            configured = False
        checks.append(
            HealthCheckItem(
                check_id="cloud_mt:google_cloud_translate",
                title="Cloud Translation: Google Cloud Translate",
                status="ok" if configured else "optional",
                message="Configured." if configured else "Not configured.",
                remediation="Open MT Provider Settings and configure service account JSON.",
            )
        )
        return checks

    def _check_baseline_reference(self) -> HealthCheckItem:
        status = self.resources.get_status("hewiki_baseline_processed_bundle")
        if status.state == "installed":
            return HealthCheckItem(
                check_id="baseline:bundle",
                title="Reference Baseline Bundle",
                status="ok",
                message="Bundle file is installed.",
            )

        # Baseline bundle is optional, but if project is already imported we verify DB counts.
        baseline_project_id = self.settings.get_int("resources/baseline_project_id", 0)
        if baseline_project_id > 0:
            try:
                with DBService.get_instance().get_session() as session:
                    row = session.execute(
                        text(
                            """
                            SELECT
                                (SELECT COUNT(*) FROM source_document d
                                  JOIN source_corpus c ON d.corpus_id = c.corpus_id
                                  WHERE c.project_id = :pid) AS docs,
                                (SELECT COUNT(*) FROM document_sentence ds
                                  JOIN source_document d ON ds.doc_id = d.doc_id
                                  JOIN source_corpus c ON d.corpus_id = c.corpus_id
                                  WHERE c.project_id = :pid) AS sentences,
                                (SELECT COUNT(*) FROM lemma WHERE project_id = :pid) AS lemmas
                            """
                        ),
                        {"pid": baseline_project_id},
                    ).fetchone()
            except Exception as exc:
                return HealthCheckItem(
                    check_id="baseline:project",
                    title="Reference Baseline Project",
                    status="warn",
                    message=f"Project health check failed: {exc}",
                    remediation="Open Resources Manager and run baseline import repair.",
                )
            docs = int(row.docs or 0)
            sentences = int(row.sentences or 0)
            lemmas = int(row.lemmas or 0)
            if docs > 0 and sentences > 0 and lemmas > 0:
                return HealthCheckItem(
                    check_id="baseline:project",
                    title="Reference Baseline Project",
                    status="ok",
                    message=f"Imported (docs={docs}, sentences={sentences}, lemmas={lemmas}).",
                )
            return HealthCheckItem(
                check_id="baseline:project",
                title="Reference Baseline Project",
                status="warn",
                message="Imported baseline project appears incomplete.",
                remediation="Re-import baseline bundle from Resources Manager.",
            )

        return HealthCheckItem(
            check_id="baseline:bundle",
            title="Reference Baseline Bundle",
            status="optional",
            message=status.message,
            remediation="Install/import baseline bundle from Resources Manager if needed.",
        )

