from __future__ import annotations

from app.ui.first_run_wizard import FirstRunWizardDialog


class _Signal:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in list(self._callbacks):
            callback(*args)


class _FakeHealthWorker:
    created = []

    def __init__(self) -> None:
        self.finished = _Signal()
        self.error = _Signal()
        self._running = False
        self.deleted = False
        _FakeHealthWorker.created.append(self)

    def setParent(self, _parent) -> None:
        return None

    def start(self) -> None:
        self._running = True

    def isRunning(self) -> bool:
        return self._running

    def deleteLater(self, *_args) -> None:
        self.deleted = True


def test_first_run_wizard_starts_health_summary_in_background(monkeypatch, qtbot):
    _FakeHealthWorker.created = []
    monkeypatch.setattr("app.ui.first_run_wizard.UnifiedHealthCheckWorker", _FakeHealthWorker)

    dialog = FirstRunWizardDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(20)

    assert len(_FakeHealthWorker.created) == 1
    assert _FakeHealthWorker.created[0].isRunning() is True
    assert dialog.refresh_health_btn.isEnabled() is False
    assert "background" in dialog.health_status_label.text().lower()
    assert "checking health summary" in dialog.health_text.toPlainText().lower()


def test_first_run_wizard_queues_health_refresh_until_current_run_finishes(monkeypatch, qtbot):
    _FakeHealthWorker.created = []
    monkeypatch.setattr("app.ui.first_run_wizard.UnifiedHealthCheckWorker", _FakeHealthWorker)

    dialog = FirstRunWizardDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(20)

    first_worker = _FakeHealthWorker.created[0]
    dialog._refresh_health_summary()

    assert dialog._health_refresh_pending is True
    assert len(_FakeHealthWorker.created) == 1
    assert "queued" in dialog.health_status_label.text().lower()

    first_worker._running = False
    first_worker.finished.emit({"overall": "warn", "items": []})
    qtbot.wait(20)

    assert len(_FakeHealthWorker.created) == 2
    assert dialog._health_refresh_pending is False
    assert dialog._health_worker is _FakeHealthWorker.created[1]

    second_worker = _FakeHealthWorker.created[1]
    second_worker._running = False
    second_worker.finished.emit(
        {
            "overall": "ok",
            "items": [
                {
                    "title": "Pronunciation Bootstrap",
                    "status": "ok",
                    "message": "Ready.",
                    "remediation": "",
                }
            ],
        }
    )

    assert dialog._health_worker is None
    assert dialog.refresh_health_btn.isEnabled() is True
    assert "health summary ready (ok)" in dialog.health_status_label.text().lower()
    assert "pronunciation bootstrap" in dialog.health_text.toPlainText().lower()
