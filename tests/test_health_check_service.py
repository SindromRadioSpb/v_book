"""Tests for unified health check remediation behavior."""

from app.infra.settings import SettingsService
from app.services.health_check_service import HealthCheckService


def _find_check(report: dict, check_id: str) -> dict:
    for row in report.get("items", []):
        if row.get("check_id") == check_id:
            return row
    return {}


def test_pronunciation_bootstrap_health_fails_with_clear_remediation_when_model_missing(tmp_path):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.set_value("resources/data_root", str(tmp_path / "data"))
    settings.set_value("pronunciation/phonikud/enabled", True)
    settings.set_value(
        "pronunciation/phonikud/model_path", str(tmp_path / "missing" / "model.onnx")
    )
    settings.sync()

    class _FakeAdapter:
        def __init__(self, *args, **kwargs):
            _ = args, kwargs

        class _Report:
            status = "error"
            mode = "error"
            latency_ms = 1
            details = "mock missing model"

        def health_check(self, *_args, **_kwargs):
            return self._Report()

    import app.services.health_check_service as module

    original = module.PhonikudAdapter
    module.PhonikudAdapter = _FakeAdapter
    try:
        report = HealthCheckService(settings=settings).run_all()
    finally:
        module.PhonikudAdapter = original
    check = _find_check(report, "bootstrap:pronunciation")
    assert check
    assert check["status"] in {"warn", "error"}
    assert "remediation" in check and check["remediation"]


def test_sentence_niqqud_bootstrap_health_same_behavior(tmp_path):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.set_value("resources/data_root", str(tmp_path / "data"))
    settings.set_value("pronunciation/phonikud/enabled", True)
    settings.set_value(
        "pronunciation/phonikud/model_path", str(tmp_path / "missing" / "model.onnx")
    )
    settings.sync()

    class _FakeAdapter:
        def __init__(self, *args, **kwargs):
            _ = args, kwargs

        class _Report:
            status = "fallback"
            mode = "fallback"
            latency_ms = 1
            details = "mock fallback"

        def health_check(self, *_args, **_kwargs):
            return self._Report()

    import app.services.health_check_service as module

    original = module.PhonikudAdapter
    module.PhonikudAdapter = _FakeAdapter
    try:
        report = HealthCheckService(settings=settings).run_all()
    finally:
        module.PhonikudAdapter = original
    check = _find_check(report, "bootstrap:sentence_niqqud")
    assert check
    assert check["status"] in {"warn", "error"}
    assert "remediation" in check and check["remediation"]


def test_mt_health_respects_master_switch(tmp_path):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.set_value("resources/data_root", str(tmp_path / "data"))
    settings.set_value("mt/providers/enabled", False)
    settings.set_value("mt/providers/chain", ["google_cloud_translate"])
    settings.set_value("mt/providers/google_cloud_translate/enabled", True)
    settings.sync()

    checks = HealthCheckService(settings=settings)._check_cloud_providers()
    cloud_mt = next(
        item.to_dict() for item in checks if item.check_id == "cloud_mt:google_cloud_translate"
    )
    assert cloud_mt["status"] == "optional"
    assert "master switch" in cloud_mt["message"].lower()


def test_mt_health_warns_when_enabled_in_chain_without_credentials(tmp_path):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.set_value("resources/data_root", str(tmp_path / "data"))
    settings.set_value("mt/providers/enabled", True)
    settings.set_value("mt/providers/chain", ["google_cloud_translate"])
    settings.set_value("mt/providers/google_cloud_translate/enabled", True)
    settings.set_value(
        "mt/providers/google_cloud_translate/auth_mode",
        "service_account_json",
    )
    settings.set_value(
        "mt/providers/google_cloud_translate/service_account_path",
        str(tmp_path / "missing-sa.json"),
    )
    settings.sync()

    checks = HealthCheckService(settings=settings)._check_cloud_providers()
    cloud_mt = next(
        item.to_dict() for item in checks if item.check_id == "cloud_mt:google_cloud_translate"
    )
    assert cloud_mt["status"] == "warn"
    assert "credentials are missing" in cloud_mt["message"].lower()
