# -*- coding: utf-8 -*-
"""v1.4.1 (ROADMAP v1.4.1, task 2): the "Import from ~/.ssh/config" picker.

Data-driven, like `BackupsDialog`: the caller (`MainWindow._import_servers_from_ssh_config`)
passes what `services/ssh_config_importer.py` parsed and receives the CHECKED
records back through `selected_hosts()` — the dialog imports nothing itself and
holds no state of its own beyond the checkboxes. Every row starts checked, so
"import the whole config" is one OK; the "Import" button is disabled while
nothing is checked (there is no import to confirm).

The report under the tree shows what the parse DROPPED:
  • `skipped` — not imported at all (a wildcard pattern, a `Match` block, an
    unreadable `Include`, a host the map already knows);
  • `notes`   — imported, but a directive was dropped (`ProxyJump`/`ProxyCommand`,
    an extra `IdentityFile`).
Both are hidden while empty, so a clean config shows the table and nothing else.
The reason CODES are the parser's; the translation lives here (`_REASON_KEYS`).
"""

try:
    from ..i18n import t
except ImportError:
    try:
        from i18n import t
    except ImportError:  # flat layout without i18n — keys as-is (main_window pattern)
        def t(key, **kwargs):
            return key.format(**kwargs) if kwargs else key

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QPushButton, QPlainTextEdit, QHeaderView,
)

# The parser's reason codes → the keys this dialog renders (the translation owner).
_REASON_KEYS = {
    "wildcard": "sshconfig.reason.wildcard",
    "match": "sshconfig.reason.match",
    "include_missing": "sshconfig.reason.include_missing",
    "duplicate": "sshconfig.reason.duplicate",
    "proxy": "sshconfig.note.proxy",
    "identity_extra": "sshconfig.note.identity_extra",
}

# The index of the parsed record inside a row — gotcha #12: QTreeWidgetItem.setData
# stores a COPY of a dict, so only the (live) index travels through the item.
_RECORD_ROLE = Qt.ItemDataRole.UserRole


def reason_text(issue) -> str:
    """The user-facing line of a skip record / a note (i18n; falls back to the code)."""
    key = _REASON_KEYS.get(getattr(issue, "reason", ""), "")
    if not key:
        return f"{getattr(issue, 'subject', '')} ({getattr(issue, 'reason', '')})"
    return t(key, detail=getattr(issue, "detail", "") or "")


class SshConfigImportDialog(QDialog):
    """The checkbox table of the hosts found in the SSH config + its skip report."""

    def __init__(self, hosts, skipped=(), notes=(), source: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("sshconfig.title"))
        self.resize(780, 470)

        self._hosts = list(hosts)
        self._rows = []            # the QTreeWidgetItem of each host, same order
        self.skipped = list(skipped)
        self.notes = list(notes)

        layout = QVBoxLayout(self)

        hint = QLabel(t("sshconfig.hint", path=source or "", count=len(self._hosts)))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels([
            t("sshconfig.col_alias"), t("sshconfig.col_host"), t("sshconfig.col_port"),
            t("sshconfig.col_user"), t("sshconfig.col_key"),
        ])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.itemChanged.connect(lambda *_a: self._sync_import_button())
        for host in self._hosts:
            row = QTreeWidgetItem([
                str(host.alias), str(host.host), str(host.port),
                str(host.user), str(host.key_path or ""),
            ])
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(0, Qt.CheckState.Checked)
            if host.source:
                row.setToolTip(0, f"{host.source}:{host.line}")
            row.setData(0, _RECORD_ROLE, len(self._rows))
            self.tree.addTopLevelItem(row)
            self._rows.append(row)

        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        layout.addWidget(self.tree, 1)

        buttons = QHBoxLayout()
        self.btn_all = QPushButton(t("sshconfig.select_all"))
        self.btn_all.clicked.connect(lambda: self._set_all(True))
        self.btn_none = QPushButton(t("sshconfig.select_none"))
        self.btn_none.clicked.connect(lambda: self._set_all(False))
        self.btn_import = QPushButton(t("btn.import"))
        self.btn_import.setDefault(True)
        self.btn_import.clicked.connect(self.accept)
        btn_cancel = QPushButton(t("btn.cancel"))
        btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(self.btn_all)
        buttons.addWidget(self.btn_none)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_import)
        buttons.addWidget(btn_cancel)
        layout.addLayout(buttons)

        # ── the report (hidden while the parse dropped nothing) ──
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setMaximumHeight(120)
        lines = []
        if self.skipped:
            lines.append(t("sshconfig.skipped", count=len(self.skipped)))
            lines += [f"  • {i.subject} — {reason_text(i)}" for i in self.skipped]
        if self.notes:
            lines.append(t("sshconfig.notes", count=len(self.notes)))
            lines += [f"  • {i.subject} — {reason_text(i)}" for i in self.notes]
        if lines:
            self.report.setPlainText("\n".join(lines))
            layout.addWidget(self.report)
        else:
            self.report.hide()

        self._sync_import_button()

    # ── Public access for tests and the caller ───────────────────

    def item_count(self) -> int:
        return len(self._rows)

    def checked_count(self) -> int:
        return sum(1 for row in self._rows
                   if row.checkState(0) == Qt.CheckState.Checked)

    def selected_hosts(self) -> list:
        """The records whose checkbox is checked (in table order)."""
        out = []
        for row in self._rows:
            if row.checkState(0) != Qt.CheckState.Checked:
                continue
            index = row.data(0, _RECORD_ROLE)
            if isinstance(index, int) and 0 <= index < len(self._hosts):
                out.append(self._hosts[index])
        return out

    def report_text(self) -> str:
        """The report body ("" when the parse dropped nothing)."""
        return self.report.toPlainText()

    # ── Slots ────────────────────────────────────────────────────

    def _set_all(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in self._rows:
            row.setCheckState(0, state)
        self._sync_import_button()

    def _sync_import_button(self):
        self.btn_import.setEnabled(self.checked_count() > 0)
