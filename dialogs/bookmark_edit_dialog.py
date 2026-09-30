# -*- coding: utf-8 -*-
"""The bookmarks editor — its OWN dialog (AGENTS.md §4.23; DOCUMENTATION.md §57).

The quick-launch editor is PER SERVER and would have to ignore a server argument here, so the two share
the entry SHAPE and the opener and nothing else. This one edits the APPLICATION-LEVEL list of
`modules/bookmarks.py`: add, edit in place, remove and reorder, writing ONLY `"type": "url"` entries
through the store.

Pinned: the editor writes the URL subset and nothing else — `BookmarkStore.save_urls()` keeps every
foreign entry (a hand-edited or plugin-written `command`) exactly where it is, so the editor can never
drop one merely by not showing it; the message boxes are module attributes taken at CALL time (the
quick-launch precedent), so a test monkeypatches `BED.QMessageBox.warning` and no modal ever opens; the
validation sentences are the EXISTING quick-launch keys (`validation.ql_*`), because the two editors validate the very same shape and one rule with two wordings would be two rules; and import/export is deliberately NOT part of it — the file is plain JSON under `~/.sshmap/` and the ask is about USING links, not moving them. The dialog pattern matches `QuickLaunchDialog`: i18n through a try-import with an English fallback, and `get_entries()` returns the list after `accept()`."""

from typing import List, Optional

from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

try:  # the store the dialog writes through (the panel talks to the same one)
    from ..modules import bookmarks as BM
except ImportError:  # flat layout: the project root is on sys.path
    from modules import bookmarks as BM


class BookmarkEditDialog(QDialog):
    """Add / edit / remove / reorder the application-level bookmarks.

    `get_entries()` — the URL entries as `{"type": "url", "name", "value"}` in the order of
    the table (which is the order of the panel). With a store installed, `accept()` writes
    them; `saved` / `save_failed` say what really happened, so the window reports the truth
    instead of a claim.
    """

    def __init__(self, parent=None, store=None, entries: Optional[list] = None):
        super().__init__(parent)

        # ── i18n support (the QuickLaunchDialog / AddServerDialog pattern) ─────
        self._i18n_available = False
        try:
            from i18n import t as __t
            self.t = __t
            self._i18n_available = True
            self.setWindowTitle(__t("dialog.bookmarks"))
        except Exception:
            def _noop(key, **kwargs):
                return key.format(**kwargs) if kwargs else key
            self.t = _noop
            self.setWindowTitle("Bookmarks")

        self._store = store
        #: What really happened at `accept()` (the window reports it).
        self.saved = False
        self.save_failed = False
        self._entries: List[dict] = []
        #: The row loaded back into the fields, or None (the v1.6.1 in-place edit rule).
        self._edit_index: Optional[int] = None
        if entries is None and store is not None:
            try:
                entries = store.load_urls()
            except Exception:  # noqa: BLE001 — an unreadable store edits an empty list
                entries = []
        for entry in (entries or []):
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            value = str(entry.get("value") or "").strip()
            if name and value:
                self._entries.append({"type": BM.BOOKMARK_TYPE if BM else "url",
                                      "name": name, "value": value})

        self.setMinimumWidth(560)
        self._build_ui()

    # ── i18n helpers ────────────────────────────────────────────────────────

    def _tr(self, key: str, **kw) -> str:
        """Translation with a fallback to the key itself (the quick-launch pattern)."""
        if self._i18n_available:
            try:
                return self.t(key, **kw)
            except Exception:  # noqa: BLE001 — an i18n failure must not crash the dialog
                pass
        return key

    # ── The UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)

        desc = QLabel(self._tr("dialog.bookmarks_desc") if self._i18n_available
                      else "The links the team uses — a wiki, a dashboard, a console. "
                           "Stored in ~/.sshmap/bookmarks.json, outside every project.")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([
            self._tr("bookmarks.col_name") if self._i18n_available else "Name",
            self._tr("bookmarks.col_url") if self._i18n_available else "URL",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(150)
        self.table.itemDoubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self.table)
        for entry in self._entries:
            self._append_row(entry["name"], entry["value"])

        self.name_edit = QLineEdit(self)
        self.value_edit = QLineEdit(self)
        self.value_edit.setPlaceholderText(
            self._tr("bookmarks.url_hint") if self._i18n_available
            else "https://wiki.example.com")
        self.btn_apply = QPushButton(
            self._tr("bookmarks.add") if self._i18n_available else "Add", self)
        self.btn_apply.clicked.connect(self._apply_fields)

        add_row = QHBoxLayout()
        add_row.addWidget(self.name_edit, 1)
        add_row.addWidget(self.value_edit, 2)
        add_row.addWidget(self.btn_apply)
        layout.addLayout(add_row)

        # Edit / Remove / the two arrows + OK/Cancel — the quick-launch layout, minus the
        # type combo (a global list offers URL entries only). The arrows are SYMBOLS: the
        # order is not a word.
        self.btn_edit = QPushButton(
            self._tr("terminal.cmdlib.edit") if self._i18n_available else "Edit", self)
        self.btn_edit.clicked.connect(self._edit_selected)
        self.btn_remove = QPushButton(
            self._tr("bookmarks.remove") if self._i18n_available else "Remove", self)
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_up = QPushButton("↑", self)
        self.btn_up.clicked.connect(lambda: self._move_selected(-1))
        self.btn_down = QPushButton("↓", self)
        self.btn_down.clicked.connect(lambda: self._move_selected(1))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        bottom = QHBoxLayout()
        bottom.addWidget(self.btn_edit)
        bottom.addWidget(self.btn_remove)
        bottom.addWidget(self.btn_up)
        bottom.addWidget(self.btn_down)
        bottom.addStretch(1)
        bottom.addWidget(buttons)
        layout.addLayout(bottom)
        self._sync_apply_button()

    def _set_row(self, row: int, name: str, value: str):
        """Write ONE row of the table from the model (the table is the display)."""
        for column, text in enumerate((name, value)):
            self.table.setItem(row, column, QTableWidgetItem(text))

    def _append_row(self, name: str, value: str):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._set_row(row, name, value)

    # ── The model operations ────────────────────────────────────────────────

    def _warn(self, text: str):
        QMessageBox.warning(self,
                            self._tr("msg.error_title") if self._i18n_available else "Error",
                            text)

    def _apply_fields(self):
        """Validate the fields: ADD a new entry, or REPLACE the one Edit loaded."""
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
        if not (value.lower().startswith("http://") or value.lower().startswith("https://")):
            self._warn(self._tr("validation.ql_url_scheme") if self._i18n_available
                       else "A link must start with http:// or https://")
            return
        # The entry being EDITED is skipped: keeping its own name is not a duplicate.
        for index, entry in enumerate(self._entries):
            if index == self._edit_index:
                continue
            if entry["name"].lower() == name.lower():
                self._warn(self._tr("validation.ql_duplicate", name=name)
                           if self._i18n_available else f"Item «{name}» already exists.")
                return
        if self._edit_index is not None:
            index = self._edit_index
            self._entries[index] = {"type": "url", "name": name, "value": value}
            self._set_row(index, name, value)      # in place — the order does not move
            self._clear_edit_state()
        else:
            self._entries.append({"type": "url", "name": name, "value": value})
            self._append_row(name, value)
        self.name_edit.clear()
        self.value_edit.clear()

    def _on_row_double_clicked(self, item):
        """A double click on a row = the Edit button."""
        if item is not None:
            self._start_edit(item.row())

    def _edit_selected(self):
        """Load the selected entry back into the input fields."""
        self._start_edit(self.table.currentRow())

    def _start_edit(self, row: int):
        """Load `row` into the fields — the next apply REPLACES it in place."""
        if not (0 <= row < len(self._entries)):
            return
        entry = self._entries[row]
        self.name_edit.setText(entry["name"])
        self.value_edit.setText(entry["value"])
        self._edit_index = row
        self.table.setCurrentCell(row, 0)
        self._sync_apply_button()

    def _clear_edit_state(self):
        self._edit_index = None
        self._sync_apply_button()

    def _sync_apply_button(self):
        """The apply button says what it will do: `Add` normally, `Save` while editing.

        Both labels are EXISTING i18n keys (the quick-launch rule)."""
        try:
            if self._edit_index is None:
                self.btn_apply.setText(
                    self._tr("bookmarks.add") if self._i18n_available else "Add")
            else:
                self.btn_apply.setText(
                    self._tr("file.save") if self._i18n_available else "Save")
            self.btn_edit.setEnabled(self._edit_index is None)
        except (RuntimeError, AttributeError):
            pass  # Qt teardown — the button is already gone

    def _move_selected(self, delta: int):
        """Move the selected entry inside the list (the order of the panel). No wrap-around."""
        row = self.table.currentRow()
        if not (0 <= row < len(self._entries)):
            return
        target = row + delta
        if not (0 <= target < len(self._entries)):
            return
        self._entries[row], self._entries[target] = self._entries[target], self._entries[row]
        for index in (row, target):
            entry = self._entries[index]
            self._set_row(index, entry["name"], entry["value"])
        if self._edit_index == row:
            self._edit_index = target
        elif self._edit_index == target:
            self._edit_index = row
        self.table.setCurrentCell(target, 0)

    def _remove_selected(self):
        row = self.table.currentRow()
        if not (0 <= row < len(self._entries)):
            return
        del self._entries[row]
        self.table.removeRow(row)
        if self._edit_index == row:
            self.name_edit.clear()
            self.value_edit.clear()
            self._clear_edit_state()
        elif self._edit_index is not None and self._edit_index > row:
            self._edit_index -= 1

    # ── The result ──────────────────────────────────────────────────────────

    def get_entries(self) -> List[dict]:
        """The URL entries (copies — an external change cannot alias the model)."""
        return [{"type": "url", "name": e["name"], "value": e["value"]}
                for e in self._entries]

    def accept(self):  # noqa: N802 — Qt API
        """Write through the store, then close. `saved` / `save_failed` are the truth.

        The dialog writes ONLY the URL subset (`BookmarkStore.save_urls`): a foreign entry
        of the file stays where it is even though this dialog never shows it.
        """
        entries = self.get_entries()
        self.saved = False
        self.save_failed = False
        if self._store is not None:
            try:
                self.saved = bool(self._store.save_urls(entries))
            except Exception:  # noqa: BLE001 — a broken store is reported, never raised
                self.saved = False
            self.save_failed = not self.saved
        super().accept()
