"""License gate confirmation for local MMS TTS provider."""

from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox

from app.infra.settings import SettingsService

MMS_LICENSE_ACCEPTED_KEY = "audio/providers/mms_tts_local/license_accepted"


def ensure_mms_license_accepted(*, parent=None) -> bool:
    """Prompt for explicit license acceptance. Returns True when accepted."""
    settings = SettingsService.get_instance()
    if settings.get_bool(MMS_LICENSE_ACCEPTED_KEY, False):
        return True

    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setWindowTitle("Meta MMS-TTS License Gate")
    msg.setText(
        "mms_tts_local is an optional local provider and requires explicit license acceptance.\n\n"
        "Before enabling, review local model license constraints for your use case."
    )
    msg.setInformativeText(
        "Do you confirm that you reviewed and accept the local MMS usage/license constraints?"
    )
    yes_btn = msg.addButton("I Accept", QMessageBox.ButtonRole.AcceptRole)
    msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    msg.setDefaultButton(yes_btn)
    msg.exec()

    accepted = msg.clickedButton() == yes_btn
    if accepted:
        settings.set_value(MMS_LICENSE_ACCEPTED_KEY, True)
        settings.sync()
    return accepted
