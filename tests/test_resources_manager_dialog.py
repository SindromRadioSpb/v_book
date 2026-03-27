from __future__ import annotations

from app.ui.resources_manager_dialog import ResourcesManagerDialog


class _FakeLabel:
    def __init__(self):
        self.value = ""

    def setText(self, value):
        self.value = value


class _FailingProbe:
    def probe_stanza(self, **kwargs):
        _ = kwargs
        raise OSError("WinError 1114")


def test_resources_manager_runtime_probe_failure_does_not_crash():
    dialog = ResourcesManagerDialog.__new__(ResourcesManagerDialog)
    dialog.nlp_probe = _FailingProbe()
    dialog.nlp_runtime_label = _FakeLabel()

    ResourcesManagerDialog._refresh_nlp_runtime_status(dialog)

    assert "runtime_probe_failed" in dialog.nlp_runtime_label.value
    assert "Stanza Hebrew unavailable" in dialog.nlp_runtime_label.value
