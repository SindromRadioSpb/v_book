"""Fast contract checks for PyInstaller spec wiring (no real build)."""

from __future__ import annotations

from pathlib import Path


def test_installer_spec_uses_script_collections_for_exe_calls():
    spec_path = Path(__file__).resolve().parents[1] / "hdle_premium_installer.spec"
    source = spec_path.read_text(encoding="utf-8-sig")

    exe_script_args: list[object] = []

    class _FakeAnalysis:
        def __init__(self, scripts, **_kwargs):
            self.scripts = [("script", str(script), "PYSOURCE", "extra") for script in scripts]
            self.pure = []
            self.zipped_data = []
            self.binaries = []
            self.zipfiles = []
            self.datas = []

    class _FakePYZ:
        def __init__(self, *_args, **_kwargs):
            pass

    class _FakeEXE:
        def __init__(self, *args, **_kwargs):
            # Contract: EXE should receive an iterable collection of script entries
            # (a.scripts / probe_a.scripts), not a single tuple element.
            exe_script_args.append(args[1] if len(args) > 1 else None)

    class _FakeCOLLECT:
        def __init__(self, *_args, **_kwargs):
            pass

    namespace = {
        "__name__": "__spec_test__",
        "__file__": str(spec_path),
        "Analysis": _FakeAnalysis,
        "PYZ": _FakePYZ,
        "EXE": _FakeEXE,
        "COLLECT": _FakeCOLLECT,
    }
    exec(compile(source, str(spec_path), "exec"), namespace)

    assert len(exe_script_args) >= 2
    for value in exe_script_args:
        assert isinstance(
            value, list
        ), "Spec must pass script collection (e.g. a.scripts), not single tuple"


def test_installer_spec_bundles_phonikud_onnx_model():
    spec_path = Path(__file__).resolve().parents[1] / "hdle_premium_installer.spec"
    source = spec_path.read_text(encoding="utf-8-sig")

    assert "installer' / 'resources' / 'local_models' / 'phonikud' / '*.onnx" in source
    assert "'resources/models/phonikud/'" in source
