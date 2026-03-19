"""Tests for deterministic resource path resolution."""

import sys
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


def test_resolve_bundled_resources_root_prefers_internal_resources_in_frozen_runtime(
    monkeypatch, tmp_path
):
    exe_root = tmp_path / "HDLE_Premium"
    internal_resources = exe_root / "_internal" / "resources"
    internal_resources.mkdir(parents=True)

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_root / "HDLE_Premium.exe"))

    assert ResourcePaths.resolve_bundled_resources_root() == internal_resources
