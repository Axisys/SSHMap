# -*- coding: utf-8 -*-
"""The elevation dialogue of the Files pane — the target user and the sudo password (v1.8).

ONE dialogue for the two things the handshake needs (`ELEVATED_PANE.md` §4): the USER the pane
should read the server as (empty means `root`) and the PASSWORD, asked only when the host's sudo
wants one. Neither value is stored: the pane passes them to `ElevatedHandshake` and the thread
drops its copy when the attempt ends, so a secret never reaches a file, an argv or a log.

The user name is judged by the PURE `user_problem()` allowlist BEFORE a channel is opened — the
value travels to a foreign parser on the other side of the channel.
"""

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
                               QVBoxLayout)

try:
    from i18n import t as _t
except Exception:  # noqa: BLE001 — import outside the project tree (flat run)
    def _t(key, **kwargs):  # type: ignore
        return key

try:  # the ONE allowlist of the sudo target user
    from ..modules.sftp_elevated import user_problem
except ImportError:
    from modules.sftp_elevated import user_problem


class ElevationDialog(QDialog):
    """Ask for the target user and (optionally) the sudo password of ONE elevation.

    `user()` and `password()` are the whole answer. A name the allowlist refuses is rejected in
    the dialogue itself with the shipped sentence, so the caller never sees an unusable value and
    no channel is opened for one.
    """

    def __init__(self, current_user: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(_t("sftp.elevated.title"))
        self.setMinimumWidth(420)
        self._user = QLineEdit(str(current_user or ""))
        self._user.setPlaceholderText(_t("sftp.elevated.user_hint"))
        self._password = QLineEdit("")
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setPlaceholderText(_t("sftp.elevated.password_hint"))
        self._problem = QLabel("")
        self._problem.setWordWrap(True)

        form = QFormLayout()
        form.addRow(_t("sftp.elevated.user_label"), self._user)
        form.addRow(_t("sftp.elevated.password_label"), self._password)
        note = QLabel(_t("sftp.elevated.note"))
        note.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(_t("sftp.elevated.connect"))
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(self._problem)
        layout.addWidget(buttons)

    def user(self) -> str:
        """The target user ("" — read as `root`)."""
        return (self._user.text() or "").strip()

    def password(self) -> str:
        """The sudo password ("" — the host needs none)."""
        return self._password.text() or ""

    def problem_text(self) -> str:
        """The sentence the dialogue is currently showing about the typed user ("" — none)."""
        return self._problem.text() or ""

    def _on_accept(self):
        """Refuse an unusable user INSIDE the dialogue; accept anything the allowlist passes."""
        reason = user_problem(self.user())
        if reason:
            self._problem.setText(_t("sftp.elevated.bad_user", user=self.user()))
            return
        self.accept()


def ask_elevation(parent=None, current_user: str = ""):
    """Ask for `(user, password)`; `None` — the dialogue was cancelled and there is NO answer.

    `None` is the ONLY refusal this seam has: `("", "")` is a legal answer (the empty user IS
    `root`, and a host with `NOPASSWD` needs no password), so a caller must never read the pair
    itself as the cancel (`ELEVATED_PANE.md` §4).
    """
    dialog = ElevationDialog(current_user, parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.user(), dialog.password()
