from __future__ import annotations

from PyQt6.QtWidgets import QDialog

from app.ui.dialogs.edit_pronunciation_dialog import show_edit_pronunciation_dialog


def test_show_edit_pronunciation_dialog_reject_path_uses_existing_payload(monkeypatch):
    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def commit(self):
            raise AssertionError("commit should not run on reject path")

        def rollback(self):
            raise AssertionError("rollback should not run on reject path")

    class _FakeDBService:
        def get_session(self):
            return _FakeSession()

    captured = {}

    class _FakePronService:
        def get_entry(self, _session, *, lang, src_norm):
            captured["lookup"] = (lang, src_norm)
            return None

    class _FakeDialog:
        def __init__(self, **kwargs):
            captured["dialog_kwargs"] = kwargs

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(
        "app.ui.dialogs.edit_pronunciation_dialog.DBService.get_instance",
        lambda: _FakeDBService(),
    )
    monkeypatch.setattr(
        "app.ui.dialogs.edit_pronunciation_dialog.PronunciationService",
        _FakePronService,
    )
    monkeypatch.setattr(
        "app.ui.dialogs.edit_pronunciation_dialog.EditPronunciationDialog",
        _FakeDialog,
    )

    changed = show_edit_pronunciation_dialog(
        parent=None,
        src_lang="he",
        src_norm="ויקי",
        src_text="ויקי",
    )

    assert changed is False
    assert captured["lookup"] == ("he", "ויקי")
    assert captured["dialog_kwargs"]["src_text"] == "ויקי"
    assert captured["dialog_kwargs"]["is_override"] is True
