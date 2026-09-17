# -*- coding: utf-8 -*-
"""v0.9.7: project backups dialog (ring buffer) + the last autosave.

Data-driven: the caller (MainWindow) passes a list of items
``[{label, path, mtime, size}, ...]`` (newest first — see
storage/autosave.py) and receives the ``restore_requested(path, label)`` signal.
All decisions (confirming a dirty change, overwriting the file, reloading the scene)
stay in MainWindow — a single restore path (ROADMAP v0.9.7 #2).
"""
import os  # noqa: F401 — kept for import compatibility with calling code
from datetime import datetime

try:
    from ..i18n import t
except ImportError:
    try:
        from i18n import t
    except ImportError:  # flat layout without i18n — keys as-is (main_window pattern)
        def t(key, **kwargs):
            return key.format(**kwargs) if kwargs else key

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QHeaderView,
)


def _fmt_time(mtime: float) -> str:
    """Local modification time; a broken mtime — "-" (we don't crash the dialog)."""
    try:
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return "-"


def _fmt_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


class BackupsDialog(QDialog):
    """Backup list (newest first) + a "Restore" button for the selected row.

    Double-clicking a row — same as the button. Close without a selection — reject().
    """

    restore_requested = Signal(str, str)  # (source path, label for status/log)

    def __init__(self, items: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("dialog.backups"))
        self.resize(580, 340)

        layout = QVBoxLayout(self)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([
            t("backups.col_source"), t("backups.col_modified"), t("backups.col_size"),
        ])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QTreeWidget.SingleSelection)
        self.tree.itemDoubleClicked.connect(lambda *_a: self._emit_restore())
        for it in items:
            row = QTreeWidgetItem([
                str(it.get("label", "")),
                _fmt_time(it.get("mtime", 0.0)),
                _fmt_size(int(it.get("size", 0))),
            ])
            # path+label — the row's data; the signal carries them on to MainWindow.
            # v1.2.10 (auto AUDIT #4): parity with .get() for label/mtime/size above — an item
            # without "path" doesn't crash the dialog with a KeyError.
            row.setData(0, Qt.UserRole, (it.get("path", ""), it.get("label", "")))
            self.tree.addTopLevelItem(row)

        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)

        buttons = QHBoxLayout()
        self.btn_restore = QPushButton(t("btn.restore"))
        self.btn_restore.setDefault(True)
        self.btn_restore.clicked.connect(self._emit_restore)
        btn_cancel = QPushButton(t("btn.cancel"))
        btn_cancel.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_restore)
        buttons.addWidget(btn_cancel)

        layout.addWidget(self.tree)
        layout.addLayout(buttons)

        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    # ── Public access for tests ─────────────────────────────

    def selected_item(self) -> QTreeWidgetItem:
        """The selected row (or the first one if the selection is empty)."""
        items = self.tree.selectedItems()
        if items:
            return items[0]
        return self.tree.topLevelItem(0) if self.tree.topLevelItemCount() else None

    def item_count(self) -> int:
        return self.tree.topLevelItemCount()

    # ── Slots ───────────────────────────────────────────────────

    def _emit_restore(self):
        item = self.selected_item()
        if item is None:
            return
        data = item.data(0, Qt.UserRole)
        if isinstance(data, (tuple, list)) and len(data) == 2:
            self.restore_requested.emit(str(data[0]), str(data[1]))
