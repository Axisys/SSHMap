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

v1.3.1 (ROADMAP v1.3.1): the read-only PREVIEW. The tab body is a
QSplitter [tree | viewer]: a double click on a text file queues a "read"
task through the SAME worker queue (never a read on the GUI thread), and the
answer (read_ready) fills a read-only QPlainTextEdit in a monospace font
under a header line (path + size + × close). Selecting another file replaces
the content; × hides the panel — a repeated double click opens it again.
Directories keep the tree behaviour (navigation). The refusals come from the
worker as machine codes (READ_ERROR_*): a binary file (known-binary
extension or a null byte in the first chunk) and files over MAX_READ_BYTES
are reported as a message, WITHOUT a panel and without a download. The
encoding: UTF-8 (BOM-aware) first, the Latin-1 fallback on a decode failure
+ a note in the header. close_viewer() drops the panel — the tab goes
through the single page teardown (page.shutdown()).

v1.3.1.1 (the follow-up polish): the listing MARKS the rows the viewer cannot
preview — a binary file or one over MAX_READ_BYTES — with a recoloured file
icon (the theme's "no preview" tone) and the reason in the row's tooltip. The
mark is deliberately NOT the name colour: an explicit setForeground() would
overcome the style's selection colours, and the recoloured glyph is a shape,
not only a colour. The mark comes from preview_block_reason(): a session FACT
(a real refusal by the worker — the only way to see a null byte), then the
certain size from the listing, then the extension guess. A `.txt` with a null
byte therefore gets its mark after the first attempt, and the mark stays for
the session (set_worker clears the facts together with the transport).

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
from PySide6.QtGui import QColor, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSplitter,
    QStyle, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
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

try:  # v1.3.1: the viewer's shared constants (limit + task_error codes)
    from .sftp_worker import (KIND_READ, MAX_READ_BYTES, READ_ERROR_BINARY,
                              READ_ERROR_TOO_LARGE, classify_extension)
except ImportError:
    from sftp_worker import (KIND_READ, MAX_READ_BYTES, READ_ERROR_BINARY,
                             READ_ERROR_TOO_LARGE, classify_extension)


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


def decode_text(data: bytes):
    """v1.3.1 (ROADMAP task 3): bytes → (text, encoding).

    UTF-8 (BOM-aware — "utf-8-sig" strips an UTF-8 BOM) first; on a decode
    failure the Latin-1 fallback, which never fails and always yields a string
    (mojibake instead of an exception — the header carries the encoding note).
    """
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace"), "latin-1"


def preview_block_reason(path: str, size, facts=None) -> str:
    """v1.3.1.1: will the viewer refuse this file? "" (no) | "binary" | "too_large".

    The order of the answers is the point of this function — from the certain to
    the guessed:

      1. `facts` — the results of REAL read attempts of this session (path →
         reason): the worker is the only one who sees the content, so its verdict
         wins. A `.txt` with a null byte looks like text by name and is refused by
         the worker — the row is marked only after the attempt, and from then on
         the mark is the truth;
      2. the SIZE from the listing (always known, never a guess): over
         MAX_READ_BYTES the task is refused before the file is opened;
      3. the extension (a GUESS — the null-byte screen can still refuse the file,
         and a file with an unknown/absent extension usually reads fine).

    A broken/absent size is treated as unknown (0) — it never marks a row.
    """
    if facts:
        known = facts.get(path)
        if known:
            return known
    try:
        size = int(size or 0)
    except (TypeError, ValueError):
        size = 0
    if size > MAX_READ_BYTES:
        return READ_ERROR_TOO_LARGE
    if classify_extension(path) == "binary":
        return READ_ERROR_BINARY
    return ""


class SftpTab(QWidget):
    """The "Files" tab: listing of the current directory + upload/download via the queue."""

    PATH_ROLE = Qt.ItemDataRole.UserRole       # full remote path of the entry
    ISDIR_ROLE = Qt.ItemDataRole.UserRole + 1  # bool — is it a directory?
    SIZE_ROLE = Qt.ItemDataRole.UserRole + 2   # int — file size (0 for a directory)
    MTIME_ROLE = Qt.ItemDataRole.UserRole + 3  # int — unix mtime

    # v1.3.1: the preview panel — the tree's share of the splitter on the first open.
    VIEWER_TREE_SHARE = 0.45

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
        # v1.3.1: the viewer's read tasks — task_id → remote path, and the id of
        # the LAST requested read (only its answer fills the panel: a fast double
        # click on two files must end up showing the SECOND one).
        self._read_tasks = {}
        self._last_read = None
        self._viewer_encoding = "utf-8"
        # v1.3.1.1: the FACTS about previewability — path → READ_ERROR_* of a read
        # that the worker really refused (see preview_block_reason); per session.
        self._blocked = {}
        self._blocked_icon_cache = None

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

        # v1.3.1 (ROADMAP task 1): the preview panel — QSplitter [tree | viewer].
        # The panel starts hidden (it appears on a double click on a text file);
        # the splitter is a horizontal pair, the viewer is collapsible — but the
        # size is only fixed via minimumWidth + setSizes (Qt gotcha #13:
        # setMaximumWidth on a splitter member breaks the size accounting).
        self.viewer = QWidget()
        self.viewer.setMinimumWidth(240)
        viewer_box = QVBoxLayout(self.viewer)
        viewer_box.setContentsMargins(4, 0, 0, 0)
        viewer_box.setSpacing(2)
        viewer_head = QHBoxLayout()
        viewer_head.setSpacing(6)
        self.viewer_label = QLabel("")
        # v1.2.5: color — from the central theme (ui/theme.py)
        self.viewer_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; padding: 2px 0;")
        self.viewer_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.viewer_label.setWordWrap(False)
        self.btn_viewer_close = QPushButton("\u00d7")  # × — the panel header's close cross
        self.btn_viewer_close.setFixedWidth(24)
        self.btn_viewer_close.setToolTip(t("sftp.viewer.close_tooltip"))
        viewer_head.addWidget(self.viewer_label, 1)
        viewer_head.addWidget(self.btn_viewer_close, 0)
        viewer_box.addLayout(viewer_head)
        self.viewer_text = QPlainTextEdit()
        self.viewer_text.setReadOnly(True)          # v1.3.1: read-only (editing is rejected)
        self.viewer_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.viewer_text.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        viewer_box.addWidget(self.viewer_text, 1)
        self.viewer.hide()

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.tree)
        self.splitter.addWidget(self.viewer)
        # setCollapsible AFTER addWidget (Qt: an out-of-range index otherwise):
        # the tree must never vanish, the viewer may be dragged shut.
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, True)
        outer.addWidget(self.splitter, 1)

        self.btn_up.clicked.connect(self.go_up)
        self.btn_refresh.clicked.connect(lambda: self._relist(self._current_dir))
        self.btn_upload.clicked.connect(self._on_upload)
        self.btn_download.clicked.connect(self._on_download)
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_viewer_close.clicked.connect(self.close_viewer)

        # v1.2.8: D&D — files from Explorer into any spot of the tab. Qt delivers
        # drag events to the widget under the cursor (the tree covers almost the
        # whole tab), so the handlers live here, and eventFilter forwards events
        # from the CHILDREN (tree/viewport/header/buttons) to the same handlers.
        self.setAcceptDrops(True)
        for w in self.findChildren(QWidget):
            w.installEventFilter(self)
        self.installEventFilter(self)

    # ── v1.3.3.1 (ROADMAP task 1): live i18n — re-text on a language switch ──

    def retranslate(self):
        """v1.3.3.1: re-text the tab's own strings in the current language.

        Every string already has an i18n key (ZERO new keys): the five buttons,
        the three column headers, the viewer's close tooltip and the "no preview"
        row tooltips. The module translator (`i18n.t`) is looked up at call time,
        so no cache has to be invalidated.

        Deliberately NOT touched: the path label and the viewer header — they carry
        the CURRENT directory / file (data, not UI text); the "waiting connection"
        state is re-texted by `set_worker(None)` on the next call. Never raises —
        the dead-C++-object discipline of every container method.
        """
        try:
            self.btn_up.setText(_t("sftp.up"))
            self.btn_refresh.setText(_t("sftp.refresh"))
            self.btn_upload.setText(_t("sftp.upload"))
            self.btn_download.setText(_t("sftp.download"))
            self.btn_cancel.setText(_t("sftp.cancel"))
            self.tree.setHeaderLabels([_t("sftp.column_name"), _t("sftp.column_size"),
                                       _t("sftp.column_modified")])
            self.btn_viewer_close.setToolTip(_t("sftp.viewer.close_tooltip"))
            # The row markers carry the refusal text in the tooltip — re-text the
            # rows of the CURRENT listing that are really marked (the facts of this
            # session; the marker itself is re-applied by the next listing).
            for path, reason in list(getattr(self, "_blocked", {}).items()):
                if not reason:
                    continue
                for i in range(self.tree.topLevelItemCount()):
                    item = self.tree.topLevelItem(i)
                    if item.data(0, self.PATH_ROLE) == path:
                        item.setToolTip(0, self._blocked_tooltip(reason))
                        break
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)

    # ── Worker binding (called by the window) ────────────────────────────

    def set_worker(self, worker):
        """Bind/unbind the SftpWorker. None — the "waiting for connection" state."""
        if self._worker is not None:
            for sig in (self._worker.list_ready, self._worker.task_started,
                        self._worker.task_done, self._worker.task_error,
                        self._worker.task_cancelled, self._worker.read_ready):
                try:
                    sig.disconnect(self)
                except TypeError:
                    pass  # no connection existed — nothing to do
        self._worker = worker
        self._transfer_tasks.clear()
        # v1.3.1.1: the previewability facts belong to ONE transport/session — a new
        # worker (a new connection, possibly another server on the same paths) starts
        # with a clean listing.
        self._blocked.clear()
        self.btn_cancel.setEnabled(False)

        if worker is None:
            self._current_dir = "/"
            self._pending_lists.clear()
            self.tree.clear()
            self._up_item = None
            # v1.3.1: the preview belongs to the session's transport — the content
            # of a dead worker must not stay on the screen.
            self.close_viewer()
            self.path_label.setText(_t("sftp.waiting_connection"))
            for b in (self.btn_up, self.btn_refresh, self.btn_upload,
                      self.btn_download):
                b.setEnabled(False)
            return

        worker.list_ready.connect(self._on_list_ready)
        worker.task_started.connect(self._on_task_started)
        worker.task_done.connect(lambda tid, _d: self._on_task_finished(tid))
        worker.task_error.connect(self._on_task_error)
        worker.task_cancelled.connect(lambda tid, _k: self._on_task_finished(tid))
        worker.read_ready.connect(self._on_read_ready)   # v1.3.1: the viewer
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
        self._apply_preview_marker(item, full)   # v1.3.1.1: "no preview" markers
        return item

    def _dir_icon(self):
        return self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)

    def _file_icon(self):
        return self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    # ── v1.3.1.1: the "no preview" markers of the listing ────────────────

    def _apply_preview_marker(self, item: QTreeWidgetItem, path: str):
        """Mark a row the viewer cannot preview (a recoloured file icon + the
        reason in the tooltip); a previewable row is left with the plain icon and
        without a tooltip (the call is idempotent — it also CLEARS a stale mark).

        Directories are never marked. The name colour is deliberately untouched:
        an explicit setForeground() would overcome the selection colours of the
        style, while the recoloured glyph survives selection and does not rely on
        the colour alone (the tooltip spells the reason out).
        """
        if item.data(0, self.ISDIR_ROLE):
            return
        reason = preview_block_reason(path, item.data(0, self.SIZE_ROLE),
                                     self._blocked)
        if not reason:
            item.setIcon(0, self._file_icon())
            item.setToolTip(0, "")
            return
        item.setIcon(0, self._blocked_icon())
        item.setToolTip(0, self._blocked_tooltip(reason))

    def _blocked_tooltip(self, reason: str) -> str:
        """The reason of a marked row — the SAME texts the refusal itself shows."""
        if reason == READ_ERROR_TOO_LARGE:
            return _t("sftp.viewer.too_large", limit=format_size(MAX_READ_BYTES))
        return _t("sftp.viewer.binary")

    def _blocked_icon(self):
        """The file icon of a marked row: the style's file glyph recoloured to the
        theme's "no preview" tone (cached).

        CompositionMode_SourceIn keeps the SHAPE and replaces the colour — the
        marker is visible as a shape, not only as a colour. A style that returns
        no pixmap for the standard icon (an exotic platform) falls back to the
        plain glyph: the tooltip still explains the row.
        """
        if self._blocked_icon_cache is not None:
            return self._blocked_icon_cache
        base = self._file_icon()
        pixmap = base.pixmap(16, 16)
        if pixmap.isNull():
            self._blocked_icon_cache = base
            return self._blocked_icon_cache
        pixmap = QPixmap(pixmap)   # a copy: the style may keep/share the pixmap
        painter = QPainter(pixmap)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(theme.SFTP_PREVIEW_BLOCKED))
        painter.end()
        self._blocked_icon_cache = QIcon(pixmap)
        return self._blocked_icon_cache

    def _mark_row(self, path: str):
        """Re-apply the marker of the row showing `path`; no such row in the
        current listing (another directory / a refreshed one) — nothing to do."""
        try:
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item.data(0, self.PATH_ROLE) == path:
                    self._apply_preview_marker(item, path)
                    return
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)

    # ── Tree events ──────────────────────────────────────────────────────

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int):
        if not item.data(0, self.ISDIR_ROLE):
            self._open_viewer(item)   # v1.3.1: a file — the read-only preview
            return
        if item is self._up_item:
            self.go_up()
        else:
            self._navigate(item.data(0, self.PATH_ROLE))

    # ── v1.3.1: the preview panel (ROADMAP task 1) ───────────────────────

    def _open_viewer(self, item: QTreeWidgetItem):
        """A double click on a file → read it through the worker queue and show it.

        The tab never touches the remote file itself: the read is a "read" task
        of the existing queue (32 KB chunks, the limit and the binary check are
        the worker's job), the answer arrives via read_ready. The panel opens
        only when the answer is there — a refusal (binary / too large) stays a
        message in the status bar (task_error → _on_task_error).
        """
        if self._worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        path = item.data(0, self.PATH_ROLE)
        tid = self._worker.queue_read(path, int(item.data(0, self.SIZE_ROLE) or 0))
        if tid is None:
            return  # the worker is finished — there is nobody to read
        self._read_tasks[tid] = path
        self._last_read = tid
        self.viewer_label.setText(_t("sftp.viewer.reading", name=posixpath.basename(path)))

    def _on_read_ready(self, task_id: int, remote_path: str, data: bytes):
        """The read answer (already on the GUI thread): render it in the panel."""
        path = self._read_tasks.pop(task_id, remote_path)
        if task_id != self._last_read:
            return  # an outdated answer (another file was opened since) — dropped
        self._last_read = None
        # v1.3.1.1: a successful read is a FACT too — drop a stale mark of this row
        # (defensive: the two heuristics agree today, and the state must not drift).
        if self._blocked.pop(path, None) is not None:
            self._mark_row(path)
        text, encoding = decode_text(bytes(data))
        self._show_viewer(path, len(data), text, encoding)

    def _on_task_error(self, task_id: int, kind: str, message: str):
        """task_error: for a "read" task the message is a MACHINE code — the tab
        turns it into an i18n hint (the window's status bar stays silent about
        reads: terminal_page skips them, the tab owns the message).

        The QUEUE is untouched (the worker contract): a refusal of one file does
        not break the listing or the transfers.

        v1.3.1.1: a refusal is also a FACT for the session — only the worker sees
        the content, so its verdict marks the row (a null byte inside a `.txt`
        cannot be guessed from the name) and the mark survives re-listing.
        """
        if kind == KIND_READ:
            path = self._read_tasks.pop(task_id, "")
            if task_id == self._last_read:
                self._last_read = None
            if path and message in (READ_ERROR_BINARY, READ_ERROR_TOO_LARGE):
                self._blocked[path] = message
                self._mark_row(path)
            self.message.emit(self._read_error_text(message, path))
        self._on_task_finished(task_id)

    def _read_error_text(self, code: str, path: str = "") -> str:
        """READ_ERROR_* → the translated hint.

        Any OTHER message is a real failure reported by the worker (a path or
        permission error, str(exception)) — it goes through the same translated
        line with the file name, so the reader always gets a readable sentence.
        """
        if code == READ_ERROR_BINARY:
            return _t("sftp.viewer.binary")
        if code == READ_ERROR_TOO_LARGE:
            return _t("sftp.viewer.too_large", limit=format_size(MAX_READ_BYTES))
        return _t("sftp.viewer.read_failed",
                  name=posixpath.basename(path) if path else "?",
                  error=code or "unknown error")

    def _show_viewer(self, path: str, size: int, text: str, encoding: str = "utf-8"):
        """Fill the panel with the file and show it (an unshown panel gets sizes)."""
        head = _t("sftp.viewer.header", path=path, size=format_size(size))
        if encoding != "utf-8":
            head = f"{head} · {_t('sftp.viewer.encoding_note', encoding=encoding)}"
        self.viewer_label.setText(head)
        self.viewer_label.setToolTip(path)
        self._viewer_encoding = encoding
        self.viewer_text.setPlainText(text)   # the cursor lands at the start by itself
        if self.viewer.isHidden():
            self.viewer.show()
            # Qt gotcha #13: the splitter member's share is set via setSizes only.
            total = max(self.splitter.width(), 640)
            left = int(total * self.VIEWER_TREE_SHARE)
            self.splitter.setSizes([left, total - left])

    @property
    def viewer_encoding(self) -> str:
        """The encoding of the shown content ("utf-8" | "latin-1")."""
        return self._viewer_encoding

    def close_viewer(self):
        """v1.3.1: hide the panel and drop its content.

        Idempotent and never raises: it is called by the header's ×, by
        set_worker(None) (the worker died) and by the single page teardown
        (page.shutdown()) — the preview closes together with the session.
        """
        self._read_tasks.clear()
        self._last_read = None
        try:
            self.viewer.hide()
            self.viewer_text.clear()
            self.viewer_label.clear()
            self.viewer_label.setToolTip("")
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race) — nothing to hide

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
        # v1.3.1: a read task that ended without an answer (cancelled) leaves no trace.
        self._read_tasks.pop(task_id, None)
        if task_id in self._transfer_tasks:
            self._transfer_tasks.discard(task_id)
            if not self._transfer_tasks:
                self.btn_cancel.setEnabled(False)
