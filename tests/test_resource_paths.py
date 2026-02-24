"""Tests for deterministic resource path resolution."""

from pathlib import Path

from app.infra.resource_paths import ResourcePaths
from app.infra.settings import SettingsService


def test_resource_paths_resolution_is_deterministic(monkeypatch, tmp_path):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.sync()

    data_root = tmp_path / "hdle_data"
    monkeypatch.setenv("HDLE_DATA_ROOT", str(data_root))

    path_one = ResourcePaths.build(settings=settings, create=True)
    path_two = ResourcePaths.build(settings=settings, create=True)

    assert path_one.data_root == path_two.data_root == data_root
    assert path_one.models_root == data_root / "models"
    assert path_one.datasets_root == data_root / "datasets"
    assert path_one.temp_root == data_root / "tmp"
    assert path_one.logs_root == data_root / "logs"
    assert path_one.backups_root == data_root / "backups"
    assert path_one.models_root.exists()
    assert path_one.datasets_root.exists()

