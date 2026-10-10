# -*- coding: utf-8 -*-
"""The tab-bar CORNER control of the Files Commander — the checkable switch of the two-pane view.

It belongs to the CONTAINER (the corner is the tab bar's) while the mode is the SESSION's, so the
control is a VIEW over an action the container reads (`is_commander()`), drawn beside the split
button. Its own module keeps `modules/sftp_tab.py` — the pane FACADE — under the line budget the
two split waves won (`tests/test_sftp_pane_split.py`), and the facade RE-EXPORTS the class, so
`modules.sftp_tab.CommanderCorner` stays the shipped name. Mechanism — `DOCUMENTATION.md` §14g."""

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

try:
    from i18n import t as _t
except Exception:  # noqa: BLE001 — a build without i18n keeps the keys, not a crash
    def _t(key, **kwargs):  # type: ignore
        return key

try:  # v1.9.8 (task 3): the vector glyph of the corner control
    from ..ui.icons import get_icon
except ImportError:
    try:
        from ui.icons import get_icon
    except ImportError:  # a stripped build — the corner button stays text-only
        def get_icon(name):
            return QIcon()

try:  # v1.9.8 (task 3): the shared corner-button stylesheet of the split controller
    from .terminal_split import apply_corner_style
except ImportError:  # flat launch from the project root
    try:
        from terminal_split import apply_corner_style
    except ImportError:  # a stripped build — the global QPushButton rule stands
        def apply_corner_style(*buttons):
            return 0


class CommanderCorner(QWidget):
    """The corner control of the two-pane view: ONE checkable action, a button that views it.

    The `act_split` pattern: the action is the single source of truth and the button is a view of
    it, so the checkmark and the pane state can never diverge. The container calls `set_state()`
    whenever the active session changes, and the action is DISABLED while the active session has no
    Files tab (a split pane). The corner holds exactly TWO controls — the split button and this one
    — and the Files panel of the WINDOW is NOT a third: since v1.7.1.1 that mode is a SETTING
    (`terminal_files_mode`), so the pair keeps the floor the window's own minimum width is built on.
    Never raises — the corner is chrome.
    """

    def __init__(self, parent=None, split_button=None):
        super().__init__(parent)
        self.setObjectName("sftpCommanderCorner")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        self.act = QAction(_t("sftp.commander"), self)
        self.act.setCheckable(True)
        self.act.setToolTip(_t("sftp.commander_tooltip"))
        self.btn = QPushButton(_t("sftp.commander"))
        self.btn.setCheckable(True)
        self.btn.setToolTip(_t("sftp.commander_tooltip"))
        # v1.9.8 (task 3): the second corner control of the session tab bar — its own GLYPH (two
        # listings) and the SAME checkable feedback as the split button (`corner.button`).
        self.refresh_theme()
        self.btn.clicked.connect(self._on_button_clicked)
        self.act.toggled.connect(self._sync_button)
        if split_button is not None:
            row.addWidget(split_button)
        row.addWidget(self.btn)
        self.set_enabled(False)   # until a session tells us what it has

    def refresh_theme(self):
        """Re-apply the corner control's glyph and stylesheet (construction and a theme switch)."""
        try:
            self.btn.setIcon(QIcon())
            self.btn.setIcon(get_icon("files"))
        except RuntimeError:
            return  # Qt teardown — the button is already destroyed
        apply_corner_style(self.btn)

    def _on_button_clicked(self, _checked=False):
        """The BUTTON asks the ACTION (one source of truth), exactly like `btn_split`."""
        self.act.setChecked(bool(self.btn.isChecked()))

    def _sync_button(self, checked=None):
        """Keep the button in step with the action WITHOUT re-entering the slot."""
        try:
            if checked is None:
                checked = bool(self.act.isChecked())
            self.btn.blockSignals(True)
            self.btn.setChecked(bool(checked))
            self.btn.blockSignals(False)
        except RuntimeError:
            pass  # Qt teardown — the button is gone

    def is_commander(self) -> bool:
        """The action's state — the ONE answer the container reads."""
        return bool(self.act.isChecked())

    def set_enabled(self, on: bool):
        """Enable/disable both views (a session without a Files tab disables the action)."""
        on = bool(on)
        try:
            self.act.setEnabled(on)
            self.btn.setEnabled(on)
        except RuntimeError:
            pass  # Qt teardown

    def set_state(self, on: bool):
        """Show a session's mode WITHOUT reporting it back (the `_set_split_action_checked`
        discipline: the action's signals stay blocked, so the container is never re-entered)."""
        on = bool(on)
        try:
            self.act.blockSignals(True)
            self.act.setChecked(on)
            self.act.blockSignals(False)
        except RuntimeError:
            pass  # Qt teardown
        self._sync_button(on)

    def retranslate(self):
        """Re-text the label and the tooltip of both views (one key each)."""
        try:
            self.act.setText(_t("sftp.commander"))
            self.act.setToolTip(_t("sftp.commander_tooltip"))
            self.btn.setText(_t("sftp.commander"))
            self.btn.setToolTip(_t("sftp.commander_tooltip"))
        except RuntimeError:
            pass  # Qt teardown — the corner is already destroyed
