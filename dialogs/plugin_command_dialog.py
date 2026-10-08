# -*- coding: utf-8 -*-
"""The command a CORE-owned run sends to the servers it targets (v1.9.3).

ONE dialogue over the SHIPPED `PluginManager.plugin_run_command()`: the target list arrives ALREADY
resolved (the Plugins window's checked rows, or the whole registry when nothing is checked) and is
shown read-only, so the only field the user fills is the command itself. The dialogue ASKS and never
runs — the caller starts the run, each answer becomes a `command_result` row of the Plugins window's
session ring like every other run, and the identity those rows report under is the manager's own
`CORE_RUN_ID`, never a plugin's id.

The caller resolves the targets through the window's `resolve_targets()`, so the refusal of a
selection that no longer resolves (`plugins.selection_gone`) stays declared in ONE place.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QVBoxLayout)

try:
    from i18n import t as _t
except Exception:  # noqa: BLE001 — import outside the project tree (flat run)
    def _t(key, **kwargs):  # type: ignore
        return key

try:  # the per-node budget the runner applies when the caller names none
    from ..modules.plugin_manager import COMMAND_TIMEOUT_S
except ImportError:
    try:
        from modules.plugin_manager import COMMAND_TIMEOUT_S
    except ImportError:  # a stripped build — the note still reads sensibly
        COMMAND_TIMEOUT_S = 30.0


class PluginCommandDialog(QDialog):
    """Ask for ONE command to send to the servers a run targets.

    `command()` is the whole answer; a cancelled dialogue returns nothing and changes nothing. The
    OK button is refused while the field holds only whitespace — an empty command is a no-op the
    runner would silently drop, so the dialogue says it before the click instead of after.
    """

    def __init__(self, nodes, parent=None, timeout_s=None):
        super().__init__(parent)
        self._nodes = list(nodes or ())
        self._timeout_s = self._resolve_timeout(timeout_s)
        try:
            self.setWindowTitle(_t("plugins.command.title"))
        except Exception:  # noqa: BLE001 — a missing i18n must not break the dialogue
            self.setWindowTitle("Run a command")
        self.setMinimumWidth(460)

        self.command_edit = QLineEdit(self)
        self.command_edit.setPlaceholderText(_t("plugins.command.placeholder"))

        self.target_list = QListWidget(self)
        self.target_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.target_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.target_list.setMaximumHeight(120)
        for node in self._nodes:
            item = QListWidgetItem(self._target_text(node), self.target_list)
            item.setToolTip(self._target_tooltip(node))

        form = QFormLayout()
        form.addRow(_t("plugins.command.label"), self.command_edit)

        #: The three text rows the chrome is re-texted from (the panel's own caption convention).
        self.hint_label = QLabel(_t("plugins.command.hint"), self)
        self.hint_label.setWordWrap(True)
        self.targets_label = QLabel(_t("plugins.command.targets", count=len(self._nodes)), self)
        self.note_label = QLabel(_t("plugins.command.note", seconds=int(self._timeout_s)), self)
        self.note_label.setWordWrap(True)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                       | QDialogButtonBox.StandardButton.Cancel, self)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(_t("plugins.command.run"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.hint_label)
        layout.addLayout(form)
        layout.addWidget(self.targets_label)
        layout.addWidget(self.target_list)
        layout.addWidget(self.note_label)
        layout.addWidget(self.buttons)

        self.command_edit.textChanged.connect(self._sync_ok)
        self._sync_ok()

    @staticmethod
    def _resolve_timeout(timeout_s) -> float:
        """The per-node budget the note names (the module default for a foreign value)."""
        try:
            return max(0.0, float(timeout_s))
        except (TypeError, ValueError):
            return float(COMMAND_TIMEOUT_S)

    @staticmethod
    def _target_text(node) -> str:
        """One target row: the node's own label (`alias (host)`), the id when it has neither."""
        label = getattr(node, "label", None)
        if callable(label):
            try:
                text = str(label() or "")
                if text:
                    return text
            except Exception:  # noqa: BLE001 — a broken record is "no label", not a crash
                pass
        return str(getattr(node, "id", "") or "?")

    @staticmethod
    def _target_tooltip(node) -> str:
        """The account and the address behind a target row (what the run really opens)."""
        host = str(getattr(node, "host", "") or "")
        user = str(getattr(node, "user", "") or "")
        try:
            port = int(getattr(node, "port", 0) or 0)
        except (TypeError, ValueError):
            port = 0
        return f"{user}@{host}:{port}" if port else f"{user}@{host}"

    def _sync_ok(self, *_args):
        """The OK button follows the field: an empty command is not a command."""
        try:
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.command()))
        except RuntimeError:
            pass  # Qt teardown — nothing to gate

    def command(self) -> str:
        """The typed command, stripped of the leading/trailing whitespace a copy brings along.

        The interior is left BYTE FOR BYTE: a shell command owns its own spacing (`echo "a   b"`
        is not `echo "a b"`), so the field is never normalised — only trimmed.
        """
        try:
            return str(self.command_edit.text() or "").strip()
        except RuntimeError:
            return ""

    def set_command(self, text) -> None:
        """Fill the field programmatically (the topical test's seam)."""
        try:
            self.command_edit.setText(str(text or ""))
        except RuntimeError:
            pass  # Qt teardown

    def node_ids(self) -> list:
        """The ids of the targets, in the order the caller handed them over."""
        return [str(getattr(node, "id", "") or "") for node in self._nodes]

    def target_count(self) -> int:
        """How many servers the command would reach (the count the hint and the run share)."""
        return len(self._nodes)


def ask_plugin_command(nodes, parent=None, timeout_s=None):
    """Ask for the command of a CORE-run; `None` — the dialogue was cancelled.

    `None` is the only refusal: an empty command never leaves the dialogue (its OK button is
    disabled), so a caller that gets a string always has something to send.
    """
    dialog = PluginCommandDialog(nodes, parent, timeout_s=timeout_s)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.command()
