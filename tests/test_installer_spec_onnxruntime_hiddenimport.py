from pathlib import Path


def test_installer_spec_includes_onnxruntime_pybind_hiddenimport():
    spec_path = Path(__file__).resolve().parents[1] / "hdle_premium_installer.spec"
    content = spec_path.read_text(encoding="utf-8")
    assert "'onnxruntime.capi.onnxruntime_pybind11_state'" in content
    assert "'onnxruntime': 'py'" in content
