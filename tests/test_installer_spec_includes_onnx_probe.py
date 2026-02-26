from pathlib import Path


def test_installer_spec_declares_onnx_probe_executable():
    spec_path = Path(__file__).resolve().parents[1] / "hdle_premium_installer.spec"
    content = spec_path.read_text(encoding="utf-8")

    assert "str(project_root / 'app' / 'tools' / 'onnx_probe.py')" in content
    assert "name='HDLE_ONNX_Probe'" in content
    assert "probe_a = Analysis(" in content
    assert "probe_a.scripts" in content
