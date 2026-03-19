"""Lifecycle regressions for TranslateTextDialog."""

from types import SimpleNamespace

from app.ui.translate_text_dialog import TranslateTextDialog


class _DummyTranslationService:
    pass


class _FakeWorker:
    def __init__(self, running=True, wait_returns=False):
        self._running = running
        self._wait_returns = wait_returns
        self.cancel_called = False

    def cancel(self):
        self.cancel_called = True

    def isRunning(self):
        return self._running

    def wait(self, _timeout):
        return self._wait_returns

    def deleteLater(self):
        pass


def test_translate_text_dialog_cancel_uses_cooperative_worker_cancel(monkeypatch, qtbot):
    monkeypatch.setattr("app.ui.translate_text_dialog.TranslationService", _DummyTranslationService)

    dialog = TranslateTextDialog()
    qtbot.addWidget(dialog)

    worker = _FakeWorker(running=True, wait_returns=False)
    dialog.translate_worker = worker
    dialog._active_translation_seq = 1

    dialog.on_cancel_translation()

    assert worker.cancel_called is True
    assert dialog.translate_worker is None
    assert dialog.metadata_label.text() == "Translation cancelled"


def test_translate_text_dialog_ignores_stale_result(monkeypatch, qtbot):
    monkeypatch.setattr("app.ui.translate_text_dialog.TranslationService", _DummyTranslationService)

    dialog = TranslateTextDialog()
    qtbot.addWidget(dialog)
    dialog.output_text.setPlainText("")
    dialog.metadata_label.setText("busy")
    dialog._active_translation_seq = 2

    result = SimpleNamespace(
        translation="translated",
        source="tm",
        provider=None,
    )

    dialog.on_translation_result(result, request_seq=1)

    assert dialog.output_text.toPlainText() == ""
    assert dialog.metadata_label.text() == "busy"


def test_translate_text_dialog_ignores_stale_error(monkeypatch, qtbot):
    monkeypatch.setattr("app.ui.translate_text_dialog.TranslationService", _DummyTranslationService)

    warnings = []
    monkeypatch.setattr(
        "app.ui.translate_text_dialog.QMessageBox.warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )

    dialog = TranslateTextDialog()
    qtbot.addWidget(dialog)
    dialog.metadata_label.setText("busy")
    dialog._active_translation_seq = 3

    dialog.on_translation_error("boom", request_seq=2)

    assert dialog.metadata_label.text() == "busy"
    assert warnings == []
