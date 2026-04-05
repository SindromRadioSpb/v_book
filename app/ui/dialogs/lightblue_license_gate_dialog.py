"""License gate confirmation for local LightBlueTTS provider."""

from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox

from app.infra.settings import SettingsService

LIGHTBLUE_LICENSE_ACCEPTED_KEY = "audio/providers/lightblue_tts/license_accepted"


def ensure_lightblue_license_accepted(*, parent=None) -> bool:
    """Prompt for explicit license acceptance. Returns True when accepted."""
    settings = SettingsService.get_instance()
    if settings.get_bool(LIGHTBLUE_LICENSE_ACCEPTED_KEY, False):
        return True

    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setWindowTitle("LightBlueTTS License Gate")
    msg.setText(
        "lightblue_tts is an experimental local provider.\n\n"
        "The license of the model weights (notmax123/LightBlue) has not been "
        "verified for commercial use. Enable only after your own review of the "
        "applicable license terms."
    )
    msg.setInformativeText(
        "Do you confirm that you have reviewed and accept responsibility for "
        "compliance with the model license for your use case?"
    )
    yes_btn = msg.addButton("I Accept", QMessageBox.ButtonRole.AcceptRole)
    msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    msg.setDefaultButton(yes_btn)
    msg.exec()

    accepted = msg.clickedButton() == yes_btn
    if accepted:
        settings.set_value(LIGHTBLUE_LICENSE_ACCEPTED_KEY, True)
        settings.sync()
    return accepted
