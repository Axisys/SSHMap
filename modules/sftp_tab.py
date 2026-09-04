# -*- coding: utf-8 -*-
"""SFTP-вкладка окна терминала (v1.1.3, ROADMAP задача 2).

Классический SFTP-режим поверх worker'а из modules/sftp_worker.py (один
поток с очередью — SFTPClient не thread-safe): дерево каталогов в виде
текущего листинга (QTreeWidget) + навигация «..»:

  * строка «..» (первая, если текущий ≠ "/") и кнопка «Вверх» — переход на
    уровень вверх; двойной клик по каталогу — вход в него;
  * upload: локальные файлы (QFileDialog) → ТЕКУЩИЙ показанный каталог
    (несколько файлов = последовательные задачи очереди);
  * download: выбранные файлы (мультивыделение) → выбранный локальный
    каталог; существующий файл той же цели перезаписывается (обработка
    конфликтов — v1.3 панель файлов);
  * прогресс — в статус-баре ОКНА (SSHTerminalWindow сам подключается к
    сигналам worker'а: progress bar + showMessage); вкладка ведёт только своё
    состояние (кнопка «Отменить» активна, пока есть передачи) и локальные
    подсказки через сигнал message();
  * GUI не блокируется: все операции SFTP — в worker-потоке, вкладка лишь
    ставит задачи в очередь и перерисовывает листинг по list_ready.

Устаревшие ответы (переход/Refresh, пока летит старый листинг) отбрасываются
по совпадению task_id → запрошенный путь: рисуется только ответ для ТЕКУЩЕГО
каталога. Если SSH-соединение ещё не готово, вкладка показывает «Ожидание
SSH-подключения…» и ждёт set_worker(worker) — окно вызывает его после
connected_signal / при переключении на вкладку (open_sftp() на том же
transport — ROADMAP задача 3).

Полное дерево с ленивым раскрытием, просмотрщик и D&D — цепочка v1.2.8/v1.3
(фундамент — этот модуль + sftp_worker.py).
"""
import posixpath
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QPushButton, QStyle, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

try:
    from i18n import t as _t
except Exception:  # noqa: BLE001 — импорт вне дерева проекта (плоский запуск)
    def _t(key, **kwargs):  # type: ignore
        return key


def format_size(n) -> str:
    """Человекочитаемый размер: 0 → "0 B", 1536 → "1.5 KB" (без локалей)."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "?"
    if n < 0:
        return "?"
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"


def format_mtime(ts) -> str:
    """Локальное время mtime "%Y-%m-%d %H:%M"; битое/нулевое → ""."""
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return ""


class SftpTab(QWidget):
    """Вкладка «Файлы»: листинг текущего каталога + upload/download через очередь."""

    PATH_ROLE = Qt.ItemDataRole.UserRole       # полный удалённый путь записи
    ISDIR_ROLE = Qt.ItemDataRole.UserRole + 1  # bool — каталог?
    SIZE_ROLE = Qt.ItemDataRole.UserRole + 2   # int — размер файла (0 для каталога)
    MTIME_ROLE = Qt.ItemDataRole.UserRole + 3  # int — unix mtime

    # Локальные подсказки в статус-бар окна (ожидание соединения, нет выбора).
    # Ошибки/прогресс worker'а окно показывает само по его сигналам.
    message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._current_dir = "/"
        self._pending_lists = {}     # task_id → запрошенный путь (сталинг-фильтр)
        self._transfer_tasks = set()  # task id активных upload/download
        self._up_item = None          # строка «..» (идентификация по объекту)

        t = _t
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)

        # Строка пути — текущий каталог («адресная строка»).
        self.path_label = QLabel(t("sftp.waiting_connection"))
        self.path_label.setStyleSheet("color: #94a3b8; padding: 2px 0;")
        outer.addWidget(self.path_label)

        # Кнопки: навигация | операции.
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.btn_up = QPushButton(t("sftp.up"))
        self.btn_refresh = QPushButton(t("sftp.refresh"))
        self.btn_upload = QPushButton(t("sftp.upload"))
        self.btn_download = QPushButton(t("sftp.download"))
        self.btn_cancel = QPushButton(t("sftp.cancel"))
        self.btn_cancel.setEnabled(False)  # активна, пока есть передачи
        for b in (self.btn_up, self.btn_refresh, self.btn_upload,
                  self.btn_download):
            b.setEnabled(False)  # до set_worker()
        bar.addWidget(self.btn_up)
        bar.addWidget(self.btn_refresh)
        bar.addStretch(1)
        bar.addWidget(self.btn_upload)
        bar.addWidget(self.btn_download)
        bar.addWidget(self.btn_cancel)
        outer.addLayout(bar)

        # Листинг: Имя | Размер | Изменён.
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([t("sftp.column_name"), t("sftp.column_size"),
                                   t("sftp.column_modified")])
        self.tree.setRootIsDecorated(True)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.setColumnWidth(0, 320)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        outer.addWidget(self.tree, 1)

        self.btn_up.clicked.connect(self.go_up)
        self.btn_refresh.clicked.connect(lambda: self._relist(self._current_dir))
        self.btn_upload.clicked.connect(self._on_upload)
        self.btn_download.clicked.connect(self._on_download)
        self.btn_cancel.clicked.connect(self._on_cancel)

    # ── Привязка worker'а (вызывает окно) ────────────────────────────────

    def set_worker(self, worker):
        """Привязать/отвязать SftpWorker. None — состояние «ожидание соединения»."""
        if self._worker is not None:
            for sig in (self._worker.list_ready, self._worker.task_started,
                        self._worker.task_done, self._worker.task_error,
                        self._worker.task_cancelled):
                try:
                    sig.disconnect(self)
                except TypeError:
                    pass  # не было подключения — делать нечего
        self._worker = worker
        self._transfer_tasks.clear()
        self.btn_cancel.setEnabled(False)

        if worker is None:
            self._current_dir = "/"
            self._pending_lists.clear()
            self.tree.clear()
            self._up_item = None
            self.path_label.setText(_t("sftp.waiting_connection"))
            for b in (self.btn_up, self.btn_refresh, self.btn_upload,
                      self.btn_download):
                b.setEnabled(False)
            return

        worker.list_ready.connect(self._on_list_ready)
        worker.task_started.connect(self._on_task_started)
        worker.task_done.connect(lambda tid, _d: self._on_task_finished(tid))
        worker.task_error.connect(lambda tid, _k, _m: self._on_task_finished(tid))
        worker.task_cancelled.connect(lambda tid, _k: self._on_task_finished(tid))
        for b in (self.btn_up, self.btn_refresh, self.btn_upload,
                  self.btn_download):
            b.setEnabled(True)
        self._relist("/")

    @property
    def worker(self):
        return self._worker

    @property
    def current_dir(self) -> str:
        """Текущий показанный каталог (цель upload)."""
        return self._current_dir

    # ── Навигация и листинг ──────────────────────────────────────────────

    def go_up(self):
        """«..» — на уровень вверх (от "/" — no-op)."""
        if self._current_dir == "/":
            return
        parent = posixpath.dirname(self._current_dir) or "/"
        self._relist(parent)

    def _navigate(self, path: str):
        """Вход в каталог (двойной клик по строке каталога)."""
        self._relist(path)

    def _relist(self, path: str):
        """Перерисовать листинг для нового текущего каталога."""
        self._current_dir = path or "/"
        self.tree.clear()
        self._up_item = None
        self.path_label.setText(self._current_dir)
        self.btn_up.setEnabled(self._current_dir != "/")
        if self._worker is None:
            return
        tid = self._worker.queue_list(self._current_dir)
        if tid is not None:
            self._pending_lists[tid] = self._current_dir

    def _on_list_ready(self, task_id: int, remote_dir: str, entries: list):
        requested = self._pending_lists.pop(task_id, None)
        # Сталкинг-фильтр: рисуем только ответ для ТЕКУЩЕГО каталога (переход
        # или Refresh, пока старый листинг летел — игнор).
        if requested is None or requested != self._current_dir \
                or remote_dir != self._current_dir:
            return
        self.tree.clear()
        self._up_item = None
        if self._current_dir != "/":
            up = QTreeWidgetItem(self.tree)
            up.setText(0, "..")
            up.setIcon(0, self._dir_icon())
            up.setData(0, self.PATH_ROLE, posixpath.dirname(self._current_dir) or "/")
            up.setData(0, self.ISDIR_ROLE, True)
            up.setData(0, self.SIZE_ROLE, 0)
            up.setData(0, self.MTIME_ROLE, 0)
            self._up_item = up
        for e in entries:
            self._add_entry_item(e)

    def _add_entry_item(self, entry: dict) -> QTreeWidgetItem:
        full = posixpath.join(self._current_dir, entry["name"])
        item = QTreeWidgetItem(self.tree)
        item.setText(0, entry["name"])
        item.setIcon(0, self._dir_icon() if entry["is_dir"] else self._file_icon())
        item.setData(0, self.PATH_ROLE, full)
        item.setData(0, self.ISDIR_ROLE, bool(entry["is_dir"]))
        item.setData(0, self.SIZE_ROLE, int(entry.get("size") or 0))
        item.setData(0, self.MTIME_ROLE, int(entry.get("mtime") or 0))
        item.setText(1, "" if entry["is_dir"] else format_size(entry.get("size")))
        item.setText(2, "" if entry["is_dir"] else format_mtime(entry.get("mtime")))
        return item

    def _dir_icon(self):
        return self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)

    def _file_icon(self):
        return self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    # ── События дерева ───────────────────────────────────────────────────

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int):
        if not item.data(0, self.ISDIR_ROLE):
            return  # файл — ничего (просмотрщик файлов — v1.3.1)
        if item is self._up_item:
            self.go_up()
        else:
            self._navigate(item.data(0, self.PATH_ROLE))

    # ── Операции (кнопки) ────────────────────────────────────────────────

    def _on_upload(self):
        if self._worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, _t("sftp.upload_dialog_title"))
        for f in files:  # несколько файлов = последовательные задачи очереди
            self._worker.queue_upload(f, self._current_dir)

    def _on_download(self):
        if self._worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        items = [i for i in self.tree.selectedItems()
                 if not i.data(0, self.ISDIR_ROLE)]
        if not items:
            self.message.emit(_t("sftp.no_selection"))
            return
        local_dir = QFileDialog.getExistingDirectory(
            self, _t("sftp.download_dir_title"))
        if not local_dir:  # отмена диалога — тихо ничего не делаем
            return
        for it in items:
            self._worker.queue_download(
                it.data(0, self.PATH_ROLE), local_dir, it.data(0, self.SIZE_ROLE))

    def _on_cancel(self):
        if self._worker is not None:
            self._worker.cancel()

    # ── Состояние передач (кнопка «Отменить») ────────────────────────────

    def _on_task_started(self, task_id: int, kind: str, _label: str):
        if kind in ("upload", "download"):
            self._transfer_tasks.add(task_id)
            self.btn_cancel.setEnabled(True)

    def _on_task_finished(self, task_id: int):
        if task_id in self._transfer_tasks:
            self._transfer_tasks.discard(task_id)
            if not self._transfer_tasks:
                self.btn_cancel.setEnabled(False)
