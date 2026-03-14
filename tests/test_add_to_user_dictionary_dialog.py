from __future__ import annotations

from app.domain.dto import UserDictionaryDTO
from app.ui.dialogs.add_to_user_dictionary_dialog import AddToUserDictionaryDialog


def test_add_to_user_dictionary_dialog_loads_dictionary_list_on_open(monkeypatch, qtbot):
    dictionaries = [
        UserDictionaryDTO(
            dictionary_id=7,
            name="Review Deck",
            description=None,
            is_pinned=1,
            sort_order=0,
            created_at="2026-03-14T00:00:00.000000Z",
            updated_at="2026-03-14T00:00:00.000000Z",
            item_count=18,
        )
    ]

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _FakeDBService:
        def get_session(self):
            return _FakeSession()

    class _FakeUserDictionaryService:
        def list_dictionaries(self, _session):
            return dictionaries

    monkeypatch.setattr(
        "app.ui.dialogs.add_to_user_dictionary_dialog.DBService.get_instance",
        lambda: _FakeDBService(),
    )
    monkeypatch.setattr(
        "app.ui.dialogs.add_to_user_dictionary_dialog.UserDictionaryService",
        _FakeUserDictionaryService,
    )

    dialog = AddToUserDictionaryDialog(selected_count=25, default_dictionary_id=7)
    qtbot.addWidget(dialog)

    assert dialog.dictionary_combo.count() == 1
    assert dialog.selected_dictionary_id() == 7
    assert dialog.skip_duplicates_checkbox.isChecked() is True
    assert dialog.include_noise_checkbox.isChecked() is False
    assert dialog.preserve_origin_checkbox.isChecked() is True
