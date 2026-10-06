# -*- coding: utf-8 -*-
"""The ONE credential prompt: a verification code, or the passphrase of an encrypted key (AGENTS.md §4.4).

It is the window `modules/interactive_ask.py` opens when `modules/ssh_connect.py` needs an answer that
only the user has — the keyboard-interactive prompt of a server after a key was accepted, or the
passphrase of a key file that will not open without one. The value is returned to the asker and is
NEVER written anywhere: no config key, no project field, no log line.

Mechanism — `DOCUMENTATION.md` §16."""

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout,
)


class AuthPromptDialog(QDialog):
    """One secret question: a label, an optional hint, a masked field and Continue / Cancel."""

    def __init__(self, parent=None, title: str = "", label: str = "", hint: str = "",
                 secret: bool = True):
        super().__init__(parent)
        self.setWindowTitle(title or label or "SSH")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        headline = QLabel(title or label)
        headline.setStyleSheet(f"font-size: 12pt; font-weight: bold; color: {theme.TEXT_PRIMARY};")
        layout.addWidget(headline)

        if hint:
            note = QLabel(hint)
            note.setWordWrap(True)
            note.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            layout.addWidget(note)
        layout.addSpacing(6)

        layout.addWidget(QLabel(label))
        self.value_edit = QLineEdit()
        self.value_edit.setEchoMode(QLineEdit.EchoMode.Password if secret
                                    else QLineEdit.EchoMode.Normal)
        self.value_edit.returnPressed.connect(self.accept)
        layout.addWidget(self.value_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self) -> str:
        """The typed secret — the empty string when the window was cancelled or left blank."""
        return self.value_edit.text()
