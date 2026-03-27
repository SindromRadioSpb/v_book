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


class _FakeWorker:
    def __init__(self, *, running=True, wait_result=True):
        self._running = running
        self._wait_result = wait_result
        self.cancel_called = False
        self.terminate_called = False
        self.wait_calls = []

    def isRunning(self):
        return self._running

    def cancel(self):
        self.cancel_called = True

    def wait(self, timeout):
        self.wait_calls.append(timeout)
        if self._wait_result:
            self._running = False
        return self._wait_result

    def terminate(self):
        self.terminate_called = True
        self._running = False


class _FakeProgressDialog:
    def __init__(self):
        self.closed = False
        self.deleted = False

    def close(self):
        self.closed = True

    def deleteLater(self):
        self.deleted = True


class _FailingProbe:
    def probe_stanza(self, **kwargs):
        _ = kwargs
        raise OSError("WinError 1114")

    def is_packaged_runtime(self):
        return False

    def build_setup_steps(self, status):
        _ = status
        return ["Retry the isolated probe."]

    def build_guided_repair_plan(self, status):
        _ = status
        return {
            "route": "runtime",
            "title": "Repair the external runtime dependency",
            "next_action": "Start with Health Check, then inspect the external runtime dependency in Resources Manager before retrying processing.",
            "steps": ["Retry the isolated probe."],
        }


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

    def build_guided_repair_plan(self, status):
        assert status is self.status
        route = "resource" if status.error_code == "model_missing" else "runtime"
        title = (
            "Repair the managed Hebrew resource"
            if route == "resource"
            else "Repair the external runtime dependency"
        )
        next_action = (
            "Start in Resources Manager and inspect the Managed Hebrew Resource section before retrying processing."
            if route == "resource"
            else "Start with Health Check, then inspect the external runtime dependency in Resources Manager before retrying processing."
        )
        return {
            "route": route,
            "title": title,
            "next_action": next_action,
            "steps": self.build_setup_steps(status),
        }


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
    dialog.hebrew_resource_label = _FakeLabel()
    dialog.open_nlp_model_folder_btn = _FakeButton()
    dialog.show_nlp_guide_btn = _FakeButton()
    dialog._last_nlp_runtime_status = None
    dialog._last_nlp_runtime_message = ""
    dialog._download_worker = None
    dialog._import_worker = None
    dialog._health_worker = None
    dialog._progress_dialog = None
    return dialog


def test_resources_manager_runtime_probe_failure_does_not_crash():
    dialog = _build_dialog(_FailingProbe())

    ResourcesManagerDialog._refresh_nlp_runtime_status(dialog)

    assert "runtime_probe_failed" in dialog.nlp_runtime_label.value
    assert "External runtime dependency is unavailable" in dialog.nlp_runtime_label.value
    assert "does not ship a one-click Python package installer" in dialog.nlp_runtime_label.value
    assert dialog.open_nlp_model_folder_btn.enabled is False
    assert "Managed Hebrew resource is not detected" in dialog.hebrew_resource_label.value
    assert "No single installer file" in dialog.hebrew_resource_label.value


def test_resources_manager_ready_runtime_enables_model_folder_button():
    status = _make_status(ready=True, model_path="C:/models/he")
    dialog = _build_dialog(_StatusProbe(status))

    ResourcesManagerDialog._refresh_nlp_runtime_status(dialog)

    assert "External runtime dependency is ready" in dialog.nlp_runtime_label.value
    assert "No bundled installer file is managed in this dialog" in dialog.nlp_runtime_label.value
    assert dialog.open_nlp_model_folder_btn.enabled is True
    assert "C:/models/he" in dialog.open_nlp_model_folder_btn.tooltip
    assert "Managed Hebrew resource is present" in dialog.hebrew_resource_label.value
    assert "directory-based resource" in dialog.hebrew_resource_label.value


def test_resources_manager_setup_guide_is_packaging_aware():
    status = _make_status(ready=False, model_path=None, error_code="hostile_torch_state")
    dialog = _build_dialog(_StatusProbe(status, packaged=True))
    dialog._apply_nlp_runtime_ui_state(status, dialog._build_nlp_runtime_message(status))

    guide = dialog._build_nlp_setup_guide_text()

    assert "Packaged mode" in guide
    assert "External runtime dependency:" in guide
    assert "Managed Hebrew resource:" in guide
    assert "Recommended route: Repair the external runtime dependency" in guide
    assert "Next action: Start with Health Check" in guide
    assert "Repair steps:" in guide
    assert "1. Environment mode: packaged." in guide
    assert "Persisted processing will not silently switch to Mock." in guide


def test_resources_manager_shutdown_stops_owned_workers():
    dialog = _build_dialog(_FailingProbe())
    download_worker = _FakeWorker(running=True, wait_result=True)
    import_worker = _FakeWorker(running=True, wait_result=False)
    health_worker = _FakeWorker(running=True, wait_result=True)
    dialog._download_worker = download_worker
    dialog._import_worker = import_worker
    dialog._health_worker = health_worker
    dialog._progress_dialog = _FakeProgressDialog()

    ok = ResourcesManagerDialog._shutdown_background_workers(dialog)

    assert ok is True
    assert download_worker.cancel_called is True
    assert import_worker.cancel_called is True
    assert import_worker.terminate_called is True
    assert health_worker.cancel_called is False
    assert dialog._progress_dialog is None
