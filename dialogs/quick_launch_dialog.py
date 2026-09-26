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
        # v1.6.1 (ROADMAP task 9): the row loaded back into the fields, or None. The next
        # apply REPLACES that entry in place instead of adding a new one — an entry can be
        # corrected without removing and retyping it.
        self._edit_index: Optional[int] = None
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
            "Links open in the default browser; commands are sent as the first "
            "command to the server's SSH terminal.")
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
        # v1.6.1 (ROADMAP task 9): a double click on a row is the SECOND door to the same
        # "load it back into the fields" gesture the Edit button opens.
        self.table.itemDoubleClicked.connect(self._on_row_double_clicked)
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
        self.btn_apply = btn_add      # v1.6.1: Add …, or Save while a row is being edited

        add_row = QHBoxLayout()
        add_row.addWidget(self.type_combo)
        add_row.addWidget(self.name_edit, 1)
        add_row.addWidget(self.value_edit, 2)
        add_row.addWidget(btn_add)
        layout.addLayout(add_row)

        # ── Edit / Remove / reorder + OK/Cancel ──────────────────────────
        # v1.6.1 (ROADMAP task 9): the editor could only ADD and REMOVE, so a typo cost the
        # entry and the order of the launched menu could not be changed at all. Edit (and a
        # double click on a row) loads the entry back into the fields and REPLACES it in
        # place; the two arrows move the selected entry inside the list — the table is the
        # single source of the order. The arrows are SYMBOLS on purpose: the release adds no
        # i18n key, and a reorder is not a translated word.
        btn_edit = QPushButton(
            self._tr("terminal.cmdlib.edit") if self._i18n_available else "Edit")
        btn_edit.clicked.connect(self._edit_selected)
        self.btn_edit = btn_edit

        btn_up = QPushButton("↑")
        btn_up.clicked.connect(lambda: self._move_selected(-1))
        self.btn_up = btn_up
        btn_down = QPushButton("↓")
        btn_down.clicked.connect(lambda: self._move_selected(1))
        self.btn_down = btn_down

        btn_remove = QPushButton(
            self._tr("ql.remove") if self._i18n_available else "Remove")
        btn_remove.clicked.connect(self._remove_selected)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        bottom_row = QHBoxLayout()
        bottom_row.addWidget(btn_edit)
        bottom_row.addWidget(btn_remove)
        bottom_row.addWidget(btn_up)
        bottom_row.addWidget(btn_down)
        bottom_row.addStretch()
        bottom_row.addWidget(btns)
        layout.addLayout(bottom_row)

        self._on_type_changed(0)  # value placeholder for the "url" type

    def _set_row(self, row: int, etype: str, name: str, value: str):
        """Write ONE row of the table from the model (the table is the display of `_entries`)."""
        type_label = (self._tr("ql.type.url") if etype == "url" else self._tr("ql.type.command")) \
            if self._i18n_available else ("Link (URL)" if etype == "url" else "Command")
        for col, text in enumerate((type_label, name, value)):
            self.table.setItem(row, col, QTableWidgetItem(text))

    def _append_row(self, etype: str, name: str, value: str):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._set_row(row, etype, name, value)

    def _on_type_changed(self, index: int):
        """The value field's placeholder depends on the selected type."""
        if self.type_combo.currentData() == "command":
            self.value_edit.setPlaceholderText(
                self._tr("ql.value_hint_command") if self._i18n_available else "k9s, htop, docker ps …")
        else:
            self.value_edit.setPlaceholderText(
                self._tr("ql.value_hint_url") if self._i18n_available else "http://host:port/path")

    def _warn(self, text: str):
        QMessageBox.warning(self,
                            self._tr("msg.error_title") if self._i18n_available else "Error",
                            text)

    def _add_entry(self):
        """Validation + writing the fields into the model: ADD a new entry, or REPLACE
        the one the Edit gesture loaded (`_edit_index`)."""
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
        # No duplicate entries (type+name) — the entry already exists. The row being
        # EDITED is skipped: keeping its own name is not a duplicate of itself.
        for index, e in enumerate(self._entries):
            if index == self._edit_index:
                continue
            if e["type"] == etype and e["name"].lower() == name.lower():
                self._warn(self._tr("validation.ql_duplicate", name=name) if self._i18n_available
                           else f"Item «{name}» already exists.")
                return
        if self._edit_index is not None:
            index = self._edit_index
            self._entries[index] = {"type": etype, "name": name, "value": value}
            self._set_row(index, etype, name, value)   # in place — the order does not move
            self._clear_edit_state()
        else:
            self._entries.append({"type": etype, "name": name, "value": value})
            self._append_row(etype, name, value)
        self.name_edit.clear()
        self.value_edit.clear()

    def _on_row_double_clicked(self, item):
        """v1.6.1 (task 9): a double click on a row = the Edit button."""
        if item is not None:
            self._start_edit(item.row())

    def _edit_selected(self):
        """v1.6.1 (task 9): load the selected entry back into the input fields."""
        self._start_edit(self.table.currentRow())

    def _start_edit(self, row: int):
        """Load `row` into the fields — the next apply REPLACES that entry in place."""
        if not (0 <= row < len(self._entries)):
            return
        entry = self._entries[row]
        index = self.type_combo.findData(entry["type"])
        self.type_combo.setCurrentIndex(index if index >= 0 else 0)
        self.name_edit.setText(entry["name"])
        self.value_edit.setText(entry["value"])
        self._edit_index = row
        self.table.setCurrentCell(row, 0)
        self._sync_apply_button()

    def _clear_edit_state(self):
        """Leave the edit mode (the fields are cleared by the caller)."""
        self._edit_index = None
        self._sync_apply_button()

    def _sync_apply_button(self):
        """The apply button says what it will do: `Add` normally, `Save` while editing.

        Both labels are EXISTING i18n keys — the release adds none (v1.6.1 task 9).
        """
        if self._edit_index is None:
            self.btn_apply.setText(
                self._tr("ql.add") if self._i18n_available else "Add")
        else:
            self.btn_apply.setText(
                self._tr("file.save") if self._i18n_available else "Save")
        try:
            self.btn_edit.setEnabled(self._edit_index is None)
        except (RuntimeError, AttributeError):
            pass  # Qt teardown — the button is already gone

    def _move_selected(self, delta: int):
        """v1.6.1 (task 9): move the selected entry inside the list (the menu's order).

        The LIST is the source of the order and the table is its display, so both rows
        involved are re-written. A pending edit follows its entry; a move is refused at
        the ends instead of wrapping around (the menu's order stays predictable).
        """
        row = self.table.currentRow()
        if not (0 <= row < len(self._entries)):
            return
        target = row + delta
        if not (0 <= target < len(self._entries)):
            return
        self._entries[row], self._entries[target] = self._entries[target], self._entries[row]
        for index in (row, target):
            e = self._entries[index]
            self._set_row(index, e["type"], e["name"], e["value"])
        if self._edit_index == row:
            self._edit_index = target
        elif self._edit_index == target:
            self._edit_index = row
        self.table.setCurrentCell(target, 0)

    def _remove_selected(self):
        row = self.table.currentRow()
        if 0 <= row < len(self._entries):
            del self._entries[row]
            self.table.removeRow(row)
            if self._edit_index == row:
                # the entry being edited is gone — leave the edit mode
                self.name_edit.clear()
                self.value_edit.clear()
                self._clear_edit_state()
            elif self._edit_index is not None and self._edit_index > row:
                self._edit_index -= 1

    def get_entries(self) -> List[dict]:
        """List of entries (copies — external changes do not affect the model)."""
        return [dict(e) for e in self._entries]
