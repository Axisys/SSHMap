# -*- coding: utf-8 -*-
"""SFTP tab of the terminal window (v1.1.3, ROADMAP task 2).

Classic SFTP mode on top of the worker from modules/sftp_worker.py (a single
thread with a queue — SFTPClient is not thread-safe): the directory tree as
a current listing (QTreeWidget) + "..." navigation:

  * the ".." row (first, if the current dir != "/") and the "Up" button — go
    one level up; double-click on a directory — enter it;
  * upload: local files (QFileDialog) → the CURRENT shown directory
    (several files = sequential queue tasks);
  * D&D (v1.2.8): files from Explorer into any spot of the tab → the same
    worker-queue upload into the CURRENT directory; directories/non-files are
    ignored with a hint; no connection — "waiting" hint (same as the Upload
    button);
  * download: selected files (multi-selection) → the chosen local directory;
    an existing file at the same target is overwritten (conflict handling —
    v1.3 file panel);
  * progress — in the window's status bar (SSHTerminalWindow connects to
    the worker's signals itself: progress bar + showMessage); the tab only
    keeps its own state (the "Cancel" button is active while transfers are
    running) and local hints via the message() signal;
  * the GUI is not blocked: all SFTP operations run in the worker thread,
    the tab merely queues tasks and redraws the listing on list_ready.

Stale responses (navigation/Refresh while an old listing is in flight) are
dropped by matching task_id → requested path: only the response for the
CURRENT directory is rendered. If the SSH connection is not ready yet, the
tab shows "Waiting for SSH connection…" and waits for set_worker(worker) —
the window calls it after connected_signal / when switching to the tab
(open_sftp() on the same transport — ROADMAP task 3).

A full tree with lazy expansion, a file viewer, and drop "into a specific row"
— the v1.3 chain (foundation — this module + sftp_worker.py).
"""
import os
import posixpath
from datetime import datetime

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QPushButton, QStyle, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

try:
    from i18n import t as _t
except Exception:  # noqa: BLE001 — import outside the project tree (flat run)
    def _t(key, **kwargs):  # type: ignore
        return key

try:  # v1.2.5: central theme (status labels — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme


def format_size(n) -> str:
    """Human-readable size: 0 → "0 B", 1536 → "1.5 KB" (no locales)."""
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
    """Local mtime time "%Y-%m-%d %H:%M"; broken/zero → ""."""
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
    """The "Files" tab: listing of the current directory + upload/download via the queue."""

    PATH_ROLE = Qt.ItemDataRole.UserRole       # full remote path of the entry
    ISDIR_ROLE = Qt.ItemDataRole.UserRole + 1  # bool — is it a directory?
    SIZE_ROLE = Qt.ItemDataRole.UserRole + 2   # int — file size (0 for a directory)
    MTIME_ROLE = Qt.ItemDataRole.UserRole + 3  # int — unix mtime

    # Local hints in the window's status bar (waiting for connection, no selection).
    # Worker errors/progress are shown by the window itself via its signals.
    message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._current_dir = "/"
        self._pending_lists = {}     # task_id → requested path (staleness filter)
        self._transfer_tasks = set()  # task ids of active upload/download
        self._up_item = None          # the ".." row (identified by object)

        t = _t
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)

        # Path row — the current directory (the "address bar").
        self.path_label = QLabel(t("sftp.waiting_connection"))
        # v1.2.5: color — from the central theme (ui/theme.py); value unchanged
        self.path_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; padding: 2px 0;")
        outer.addWidget(self.path_label)

        # Buttons: navigation | operations.
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.btn_up = QPushButton(t("sftp.up"))
        self.btn_refresh = QPushButton(t("sftp.refresh"))
        self.btn_upload = QPushButton(t("sftp.upload"))
        self.btn_download = QPushButton(t("sftp.download"))
        self.btn_cancel = QPushButton(t("sftp.cancel"))
        self.btn_cancel.setEnabled(False)  # active while transfers are running
        for b in (self.btn_up, self.btn_refresh, self.btn_upload,
                  self.btn_download):
            b.setEnabled(False)  # until set_worker()
        bar.addWidget(self.btn_up)
        bar.addWidget(self.btn_refresh)
        bar.addStretch(1)
        bar.addWidget(self.btn_upload)
        bar.addWidget(self.btn_download)
        bar.addWidget(self.btn_cancel)
        outer.addLayout(bar)

        # Listing: Name | Size | Modified.
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

        # v1.2.8: D&D — files from Explorer into any spot of the tab. Qt delivers
        # drag events to the widget under the cursor (the tree covers almost the
        # whole tab), so the handlers live here, and eventFilter forwards events
        # from the CHILDREN (tree/viewport/header/buttons) to the same handlers.
        self.setAcceptDrops(True)
        for w in self.findChildren(QWidget):
            w.installEventFilter(self)
        self.installEventFilter(self)

    # ── Worker binding (called by the window) ────────────────────────────

    def set_worker(self, worker):
        """Bind/unbind the SftpWorker. None — the "waiting for connection" state."""
        if self._worker is not None:
            for sig in (self._worker.list_ready, self._worker.task_started,
                        self._worker.task_done, self._worker.task_error,
                        self._worker.task_cancelled):
                try:
                    sig.disconnect(self)
                except TypeError:
                    pass  # no connection existed — nothing to do
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
        """The currently shown directory (upload target)."""
        return self._current_dir

    # ── Navigation and listing ───────────────────────────────────────────

    def go_up(self):
        """".." — one level up (no-op from "/")."""
        if self._current_dir == "/":
            return
        parent = posixpath.dirname(self._current_dir) or "/"
        self._relist(parent)

    def _navigate(self, path: str):
        """Enter a directory (double-click on a directory row)."""
        self._relist(path)

    def _relist(self, path: str):
        """Redraw the listing for the new current directory."""
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
        # Staleness filter: render only the response for the CURRENT directory
        # (navigation or Refresh while an old listing was in flight — ignored).
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

    # ── Tree events ──────────────────────────────────────────────────────

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int):
        if not item.data(0, self.ISDIR_ROLE):
            return  # file — nothing (file viewer — v1.3.1)
        if item is self._up_item:
            self.go_up()
        else:
            self._navigate(item.data(0, self.PATH_ROLE))

    # ── Operations (buttons) ─────────────────────────────────────────────

    def _on_upload(self):
        if self._worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, _t("sftp.upload_dialog_title"))
        for f in files:  # several files = sequential queue tasks
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
        if not local_dir:  # dialog cancelled — quietly do nothing
            return
        for it in items:
            self._worker.queue_download(
                it.data(0, self.PATH_ROLE), local_dir, it.data(0, self.SIZE_ROLE))

    def _on_cancel(self):
        if self._worker is not None:
            self._worker.cancel()

    # ── D&D: files from Explorer (v1.2.8) ────────────────────────────────

    _DRAG_TYPES = (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop)

    def eventFilter(self, obj, event):
        """Drag events on the tab's children are forwarded to the tab's OWN
        handlers: the drop target is the current directory regardless of where
        exactly (a tree row, a button) the files landed. Returning True = the
        event is consumed (QTreeWidget does not process it "its own way")."""
        etype = event.type()
        if etype in self._DRAG_TYPES and (obj is self or self.isAncestorOf(obj)):
            if etype == QEvent.Type.DragEnter:
                self.dragEnterEvent(event)
            elif etype == QEvent.Type.DragMove:
                self.dragMoveEvent(event)
            else:  # Drop
                self.dropEvent(event)
            return True
        return False

    @staticmethod
    def _local_files(mime_data) -> list:
        """Existing local files from the dragged URLs. Directories, deleted/
        nonexistent paths, and non-file data — are skipped."""
        out = []
        if mime_data is None or not mime_data.hasUrls():
            return out
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if os.path.isfile(path):
                out.append(path)
        return out

    def dragEnterEvent(self, event):
        if self._local_files(event.mimeData()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        # Same answer as dragEnter — otherwise Qt will reset the action before Drop.
        if self._local_files(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = self._local_files(event.mimeData())
        if files:
            event.acceptProposedAction()
        self._on_drop(files)

    def _on_drop(self, files: list):
        """Drop result: upload into the CURRENT directory (like the Upload button)."""
        if not files:
            # No local files in the drag (directories/other data).
            self.message.emit(_t("sftp.drop_no_files"))
            return
        if self._worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        for f in files:  # several files = sequential queue tasks (v1.1.3)
            self._worker.queue_upload(f, self._current_dir)
        self.message.emit(
            _t("sftp.drop_queued", count=len(files), dir=self._current_dir))

    # ── Transfer state (the "Cancel" button) ─────────────────────────────

    def _on_task_started(self, task_id: int, kind: str, _label: str):
        if kind in ("upload", "download"):
            self._transfer_tasks.add(task_id)
            self.btn_cancel.setEnabled(True)

    def _on_task_finished(self, task_id: int):
        if task_id in self._transfer_tasks:
            self._transfer_tasks.discard(task_id)
            if not self._transfer_tasks:
                self.btn_cancel.setEnabled(False)
