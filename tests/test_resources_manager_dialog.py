from __future__ import annotations

from app.services.nlp_runtime.dto import NlpRuntimeStatus
from app.ui.resources_manager_dialog import ResourcesManagerDialog


class _FakeLabel:
    def __init__(self):
        self.value = ""
        self.tooltip = ""

    def setText(self, value):
        self.value = value

    def setToolTip(self, value):
        self.tooltip = value


class _FakeButton:
    def __init__(self):
        self.enabled = True
        self.tooltip = ""

    def setEnabled(self, value):
        self.enabled = bool(value)

    def setToolTip(self, value):
        self.tooltip = value


class _FailingProbe:
    def probe_stanza(self, **kwargs):
        _ = kwargs
        raise OSError("WinError 1114")

    def is_packaged_runtime(self):
        return False

    def build_setup_steps(self, status):
        _ = status
        return ["Retry the isolated probe."]


class _StatusProbe:
    def __init__(self, status: NlpRuntimeStatus, *, packaged: bool = False):
        self.status = status
        self.packaged = packaged

    def probe_stanza(self, **kwargs):
        _ = kwargs
        return self.status

    def is_packaged_runtime(self):
        return self.packaged

    def build_setup_steps(self, status):
        assert status is self.status
        mode = "packaged" if self.packaged else "development"
        return [
            f"Environment mode: {mode}.",
            "Persisted processing will not silently switch to Mock.",
        ]


def _make_status(*, ready: bool, model_path: str | None, error_code: str | None = None) -> NlpRuntimeStatus:
    return NlpRuntimeStatus(
        configured_engine_id="stanza",
        effective_engine_id="stanza" if ready else None,
        package_installed=ready or error_code != "package_missing",
        model_present=bool(model_path),
        pipeline_init_ok=ready,
        smoke_ok=ready,
        cuda_available=False,
        runtime_mode="cpu",
        fallback_used=False,
        error_code=error_code,
        error_detail="WinError 1114" if error_code else None,
        remediation="Inspect the local runtime.",
        engine_version="1.11.1" if ready else None,
        model_id="he/tokenize,pos,lemma",
        model_path=model_path,
    )


def _build_dialog(probe) -> ResourcesManagerDialog:
    dialog = ResourcesManagerDialog.__new__(ResourcesManagerDialog)
    dialog.nlp_probe = probe
    dialog.nlp_runtime_label = _FakeLabel()
    dialog.open_nlp_model_folder_btn = _FakeButton()
    dialog.show_nlp_guide_btn = _FakeButton()
    dialog._last_nlp_runtime_status = None
    dialog._last_nlp_runtime_message = ""
    return dialog


def test_resources_manager_runtime_probe_failure_does_not_crash():
    dialog = _build_dialog(_FailingProbe())

    ResourcesManagerDialog._refresh_nlp_runtime_status(dialog)

    assert "runtime_probe_failed" in dialog.nlp_runtime_label.value
    assert "Stanza Hebrew unavailable" in dialog.nlp_runtime_label.value
    assert dialog.open_nlp_model_folder_btn.enabled is False


def test_resources_manager_ready_runtime_enables_model_folder_button():
    status = _make_status(ready=True, model_path="C:/models/he")
    dialog = _build_dialog(_StatusProbe(status))

    ResourcesManagerDialog._refresh_nlp_runtime_status(dialog)

    assert "Stanza Hebrew ready" in dialog.nlp_runtime_label.value
    assert dialog.open_nlp_model_folder_btn.enabled is True
    assert "C:/models/he" in dialog.open_nlp_model_folder_btn.tooltip


def test_resources_manager_setup_guide_is_packaging_aware():
    status = _make_status(ready=False, model_path=None, error_code="hostile_torch_state")
    dialog = _build_dialog(_StatusProbe(status, packaged=True))
    dialog._apply_nlp_runtime_ui_state(status, dialog._build_nlp_runtime_message(status))

    guide = dialog._build_nlp_setup_guide_text()

    assert "Packaged mode" in guide
    assert "Repair steps:" in guide
    assert "1. Environment mode: packaged." in guide
    assert "Persisted processing will not silently switch to Mock." in guide
