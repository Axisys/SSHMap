# -*- coding: utf-8 -*-
"""v0.9.7: диалог бэкапов проекта (кольцевой буфер) + последнего автосохранения.

Data-driven: вызывающий (MainWindow) передаёт список items
``[{label, path, mtime, size}, ...]`` (свежие первыми — см.
storage/autosave.py) и получает сигнал ``restore_requested(path, label)``.
Все решения (подтверждение dirty-правки, перезапись файла, перезагрузка сцены)
остаются в MainWindow — единый путь восстановления (ROADMAP v0.9.7 #2).
"""
import os  # noqa: F401 — сохранён для совместимости импорта вызывающим кодом
from datetime import datetime

try:
    from ..i18n import t
except ImportError:
    try:
        from i18n import t
    except ImportError:  # flat-раскладка без i18n — ключи как есть (паттерн main_window)
        def t(key, **kwargs):
            return key.format(**kwargs) if kwargs else key

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QHeaderView,
)


def _fmt_time(mtime: float) -> str:
    """Локальное время изменения; битый mtime — «-» (не роняем диалог)."""
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
    """Список бэкапов (свежие первыми) + кнопка «Восстановить» для выбранной строки.

    Двойной клик по строке — то же, что кнопка. Закрыть без выбора — reject().
    """

    restore_requested = Signal(str, str)  # (path исходника, label для статуса/лога)

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
            # path+label — данные строки; сигнал несёт их дальше в MainWindow
            row.setData(0, Qt.UserRole, (it["path"], it.get("label", "")))
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

    # ── Публичный доступ для тестов ─────────────────────────────

    def selected_item(self) -> QTreeWidgetItem:
        """Выбранная строка (или первая, если выбор пуст)."""
        items = self.tree.selectedItems()
        if items:
            return items[0]
        return self.tree.topLevelItem(0) if self.tree.topLevelItemCount() else None

    def item_count(self) -> int:
        return self.tree.topLevelItemCount()

    # ── Слоты ───────────────────────────────────────────────────

    def _emit_restore(self):
        item = self.selected_item()
        if item is None:
            return
        data = item.data(0, Qt.UserRole)
        if isinstance(data, (tuple, list)) and len(data) == 2:
            self.restore_requested.emit(str(data[0]), str(data[1]))
