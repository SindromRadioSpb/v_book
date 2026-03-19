"""Tests for Batch Audio dialog actions."""

from __future__ import annotations

from app.ui.dialogs.batch_audio_dialog import BatchAudioDialog


def test_settings_button_reloads_provider_list_after_save(monkeypatch, qtbot):
    provider_lists = [
        ["mock_local_audio", "mock_online_audio"],
        ["google_cloud_tts", "mock_local_audio"],
    ]

    def _next_provider_list():
        if len(provider_lists) > 1:
            return provider_lists.pop(0)
        return provider_lists[0]

    monkeypatch.setattr(
        "app.ui.dialogs.batch_audio_dialog.list_available_audio_providers",
        _next_provider_list,
    )
    monkeypatch.setattr(
        "app.ui.audio_provider_settings_dialog.show_audio_provider_settings",
        lambda parent=None: True,
    )

    dialog = BatchAudioDialog(selected_count=3)
    qtbot.addWidget(dialog)

    assert dialog.provider_combo.count() == 2
    assert dialog.provider_combo.itemText(0) == "mock_local_audio"

    dialog._open_audio_settings()

    assert dialog.provider_combo.count() == 2
    assert dialog.provider_combo.itemText(0) == "google_cloud_tts"
