# -*- coding: utf-8 -*-
"""v1.0RC4: "Quick launch" configuration dialog for a single server.

Quick launch entries — a list of links/commands attached to the server
(models/server.py: ServerData.quick_launch). From there they end up in the
context menu (right-click on a sidebar row and on a map node) as the
"Quick launch" submenu.

  * type="url"     — value opens in the default browser (webbrowser);
  * type="command" — value is sent as the first command to the server's SSH terminal.

Dialog pattern — same as AddServerDialog: i18n via try-import with an English
fallback; get_entries() returns a list of dicts after accept().
"""
from typing import List, Optional

try:
    from ..models.server import ServerData, sanitize_quick_launch
except ImportError:
    from models.server import ServerData, sanitize_quick_launch

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QTableWidget, QTableWidgetItem,
    QDialogButtonBox, QMessageBox, QAbstractItemView,
)


class QuickLaunchDialog(QDialog):
    """Configure Quick launch entries for a single server.

    get_entries() — a list of {"type": "url"|"command", "name": str, "value": str}
    (order = order in the table). Call after exec() == Accepted.
    """

    def __init__(self, parent=None, server_data: Optional[ServerData] = None):
        super().__init__(parent)

        # ── i18n support (AddServerDialog pattern) ────────────────────────
        self._i18n_available = False
        try:
            from i18n import get_current_language as _get_lang, t as __t
            self.t = __t
            self.current_language = _get_lang()
            self._i18n_available = True
            alias = getattr(server_data, "alias", "") if server_data else ""
            self.setWindowTitle(__t("dialog.quick_launch", alias=alias or "?"))
        except Exception:
            def _noop(key, **kwargs):
                return key.format(**kwargs) if kwargs else key
            self.t = _noop
            alias = getattr(server_data, "alias", "") if server_data else ""
            self.setWindowTitle(f"Quick Launch — {alias or '?'}")

        # Entry points: the server is known (properties/map context) or not.
        self._server_data = server_data
        self.setMinimumWidth(520)

        # Current list of entries (source of truth; the table is its display)
        self._entries: List[dict] = []
        if server_data is not None:
            self._entries = [dict(e) for e in sanitize_quick_launch(
                getattr(server_data, "quick_launch", None))]

        self._build_ui()

    def _tr(self, key: str, **kw) -> str:
        """Translation with fallback to the key itself (without i18n — English literals in the UI)."""
        if self._i18n_available:
            try:
                return self.t(key, **kw)
            except Exception:  # noqa: BLE001 — an i18n failure must not crash the dialog
                pass
        return key

    def _build_ui(self):
        layout = QVBoxLayout(self)

        desc = QLabel(
            self._tr("dialog.quick_launch_desc") if self._i18n_available else
            "Links open in the default browser; commands are sent\n"
            "as the first command to the server's SSH terminal.")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # ── Table of existing entries ───────────────────────────────────
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([
            self._tr("ql.type") if self._i18n_available else "Type",
            self._tr("ql.name") if self._i18n_available else "Name",
            self._tr("ql.value") if self._i18n_available else "Value",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(140)
        layout.addWidget(self.table)

        for e in self._entries:
            self._append_row(e["type"], e["name"], e["value"])

        # ── Add row: [type] [name] [value] [Add] ──────
        self.type_combo = QComboBox()
        self.type_combo.addItem(
            self._tr("ql.type.url") if self._i18n_available else "Link (URL)", "url")
        self.type_combo.addItem(
            self._tr("ql.type.command") if self._i18n_available else "Command", "command")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Webmin, K9S, ...")
        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText(
            self._tr("ql.value_hint_url") if self._i18n_available else "http://host:port/path")

        btn_add = QPushButton(
            self._tr("ql.add") if self._i18n_available else "Add")
        btn_add.clicked.connect(self._add_entry)

        add_row = QHBoxLayout()
        add_row.addWidget(self.type_combo)
        add_row.addWidget(self.name_edit, 1)
        add_row.addWidget(self.value_edit, 2)
        add_row.addWidget(btn_add)
        layout.addLayout(add_row)

        # ── Remove selected + OK/Cancel ──────────────────────────────────
        btn_remove = QPushButton(
            self._tr("ql.remove") if self._i18n_available else "Remove")
        btn_remove.clicked.connect(self._remove_selected)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        bottom_row = QHBoxLayout()
        bottom_row.addWidget(btn_remove)
        bottom_row.addStretch()
        bottom_row.addWidget(btns)
        layout.addLayout(bottom_row)

        self._on_type_changed(0)  # value placeholder for the "url" type

    def _append_row(self, etype: str, name: str, value: str):
        row = self.table.rowCount()
        self.table.insertRow(row)
        type_label = (self._tr("ql.type.url") if etype == "url" else self._tr("ql.type.command")) \
            if self._i18n_available else ("Link (URL)" if etype == "url" else "Command")
        for col, text in enumerate((type_label, name, value)):
            self.table.setItem(row, col, QTableWidgetItem(text))

    def _on_type_changed(self, index: int):
        """The value field's placeholder depends on the selected type."""
        if self.type_combo.currentData() == "command":
            self.value_edit.setPlaceholderText(
                self._tr("ql.value_hint_command") if self._i18n_available else "k9s, htop, docker ps ...")
        else:
            self.value_edit.setPlaceholderText(
                self._tr("ql.value_hint_url") if self._i18n_available else "http://host:port/path")

    def _warn(self, text: str):
        QMessageBox.warning(self,
                            self._tr("msg.error_title") if self._i18n_available else "Error",
                            text)

    def _add_entry(self):
        """Validation + adding the entry to the table and the list."""
        etype = self.type_combo.currentData() or "url"
        name = self.name_edit.text().strip()
        value = self.value_edit.text().strip()
        if not name:
            self._warn(self._tr("validation.ql_name_empty") if self._i18n_available
                       else "Item name cannot be empty.")
            return
        if not value:
            self._warn(self._tr("validation.ql_value_empty") if self._i18n_available
                       else "Value (URL or command) cannot be empty.")
            return
        if etype == "url" and not (value.lower().startswith("http://")
                                   or value.lower().startswith("https://")):
            self._warn(self._tr("validation.ql_url_scheme") if self._i18n_available
                       else "A link must start with http:// or https://")
            return
        # No duplicate entries (type+name) — the entry already exists
        for e in self._entries:
            if e["type"] == etype and e["name"].lower() == name.lower():
                self._warn(self._tr("validation.ql_duplicate", name=name) if self._i18n_available
                           else f"Item «{name}» already exists.")
                return
        self._entries.append({"type": etype, "name": name, "value": value})
        self._append_row(etype, name, value)
        self.name_edit.clear()
        self.value_edit.clear()

    def _remove_selected(self):
        row = self.table.currentRow()
        if 0 <= row < len(self._entries):
            del self._entries[row]
            self.table.removeRow(row)

    def get_entries(self) -> List[dict]:
        """List of entries (copies — external changes do not affect the model)."""
        return [dict(e) for e in self._entries]
