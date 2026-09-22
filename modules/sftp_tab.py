# -*- coding: utf-8 -*-
"""SFTP tab of the terminal window (v1.1.3, ROADMAP task 2).

Classic SFTP mode on top of the worker from modules/sftp_worker.py (a single
thread with a queue — SFTPClient is not thread-safe): the directory tree as
a current listing (QTreeWidget) + "..." navigation:

  * the ".." row (first, if the current dir != "/") and the "Up" button — go
    one level up; double-click on a directory — enter it;
  * upload: local files (QFileDialog) → the CURRENT shown directory
    (several files = sequential queue tasks);
  * D&D (v1.2.8): files from Explorer into the tab → the same worker-queue
    upload; v1.3.3.2: the target is the directory UNDER THE CURSOR — a drop on a
    directory row goes into THAT directory, a drop on a file row or on empty
    space goes into the current directory; directories/non-files are ignored
    with a hint; no connection — "waiting" hint (same as the Upload button);
  * download: selected files (multi-selection) → the chosen local directory;
  * the OVERWRITE CONFLICT (v1.3.3.2, ROADMAP task 2 — the deferred v1.3
    promise): an existing destination in either direction opens a dialog with
    Overwrite / Skip / Rename / "Apply to all" for the rest of the batch; a
    cancelled dialog skips that file; the existence check is never a guess (the
    current listing for the shown directory, a listing of the target directory
    queued first for a drop on a row, os.path.exists for the local side);
  * progress — in the window's status bar (SSHTerminalWindow connects to
    the worker's signals itself: progress bar + showMessage); the tab only
    keeps its own state (the "Cancel" button is active while transfers are
    running) and local hints via the message() signal;
  * the GUI is not blocked: all SFTP operations run in the worker thread,
    the tab merely queues tasks and redraws the listing on list_ready.

v1.3.3.2 (ROADMAP v1.3.3.2): the tab becomes a FILE MANAGER.
  * the file operations — New folder / Rename / Delete / Copy remote path in the
    tree's context menu (`_build_context_menu(item)` — the test seam, the
    QActions are triggered directly by the tests, no menu.exec()). The three
    operations are ordinary tasks of the SAME worker queue (kind mkdir/rename/
    delete): the client stays single-threaded, a failure is a task_error and the
    queue lives on; the listing is refreshed when an operation finishes; the
    delete asks for a confirmation (QMessageBox — a module attribute, the
    command-library test-seam pattern);
  * both transfer directions are ATOMIC (modules/sftp_worker.py): the download
    goes to `<dest>.part` + os.replace, the upload to `<remote>.part` + rename —
    a cancelled or failed transfer never truncates the destination;
  * drag-OUT: a dragged row publishes its REMOTE PATH as text/plain, so a file
    can be dropped into a terminal, an editor or a chat window (the real "drag
    files out to Explorer" — a download into a temp dir with its own
    progress/cancel story — is NOT in this version).

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

v1.4.7 (ROADMAP v1.4.7): SYNTAX HIGHLIGHTING of the preview. The panel gains
ONE `QSyntaxHighlighter` per tab (modules/syntax_highlight.py) and the visible
content stops being monochrome: numbers everywhere, and a real grammar for
JSON/XML/YAML. The release rules, unchanged from the plan:

  * the viewer stays READ-ONLY and the read path (worker queue, 1 MB limit,
    encodings) is untouched — the highlighter only paints what is already in
    the widget;
  * **the honesty rule**: the extension is a HINT, the content is the VERDICT.
    `detect_syntax(path, text)` accepts `.json`/`.xml` only after `json.loads` /
    `ElementTree.fromstring` really parsed the text; a file that does not parse
    degrades to the language-agnostic `"numbers"` mode instead of wearing a
    grammar that does not describe it. YAML has no stdlib parser, so it is a
    HEURISTIC — the header says so (`sftp.viewer.syntax_heuristic`), exactly the
    way the `encoding` note works;
  * **colours only** (no bold/italic), which is what lets the formatting be
    applied LAZILY to the blocks around the viewport
    (`QPlainTextEdit.updateRequest` → `_highlight_visible()`): a 1 MB file costs
    roughly what its first screen costs, and a minified 1 MB single line trips
    the per-block TOKEN cap of the tokenizer instead of freezing the GUI.

Stale responses (navigation/Refresh while an old listing is in flight) are
dropped by matching task_id → requested path: only the response for the
CURRENT directory is rendered. If the SSH connection is not ready yet, the
tab shows "Waiting for SSH connection…" and waits for set_worker(worker) —
the window calls it after connected_signal / when switching to the tab
(open_sftp() on the same transport — ROADMAP task 3).

A full tree with lazy expansion and recursive transfers — still the backlog: the tab
is built around ONE current directory (a model change), and the drop "into a specific
row" landed in v1.3.3.2 as the directory under the cursor.
"""
import os
import posixpath
from datetime import datetime

from PySide6.QtCore import QEvent, QMimeData, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
    QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QStyle,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
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

try:  # v1.4.3 (ROADMAP task 4): the ONE QSS registry
    from ..ui import theme_qss
except ImportError:
    try:
        from ui import theme_qss
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        theme_qss = None

try:  # v1.3.1: the viewer's shared constants (limit + task_error codes)
    from .sftp_worker import (KIND_DELETE, KIND_MKDIR, KIND_READ, KIND_RENAME,
                              MAX_READ_BYTES, OP_KINDS, READ_ERROR_BINARY,
                              READ_ERROR_TOO_LARGE, classify_extension)
except ImportError:
    from sftp_worker import (KIND_DELETE, KIND_MKDIR, KIND_READ, KIND_RENAME,
                             MAX_READ_BYTES, OP_KINDS, READ_ERROR_BINARY,
                             READ_ERROR_TOO_LARGE, classify_extension)

try:  # v1.4.7 (ROADMAP task 4): detection + tokenizers + the ONE highlighter
    from . import syntax_highlight as syntax
except ImportError:
    import syntax_highlight as syntax


def _apply_status_style(widget, key: str) -> None:
    """v1.4.3 (ROADMAP task 4): apply a muted status-label style from the registry.

    Falls back to the pre-v1.4.3 inline string when the Qt theme module is not
    importable (a flat run outside the project tree), so a status label is styled
    either way. Never raises: a missing registry key yields an empty stylesheet.
    """
    if theme_qss is not None:
        widget.setStyleSheet(theme_qss.style(key))
    else:
        widget.setStyleSheet(f"color: {theme.TEXT_MUTED}; padding: 2px 0;")


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


def ask_conflict(parent, name: str, target: str, remaining: int = 0):
    """v1.3.3.2 (ROADMAP task 2): the overwrite question for ONE item of a batch.

    Returns `(action, apply_all)`, where action is one of

      * `"overwrite"` — replace the existing destination;
      * `"skip"` — leave the destination alone and go on with the batch;
      * `"rename"` — ask for another name (the caller prompts, then uploads /
        downloads under it) — `apply_all` is never set for it: a batch rename needs
        a name per file;
      * a cancelled dialog (Esc / the window's X) is reported as `"skip"`.

    `remaining` is the number of conflicts still to come in this batch — "Apply to
    all" is offered only when there is anything left to apply it to.

    The QMessageBox is taken as a MODULE ATTRIBUTE at call time
    (`STAB.QMessageBox = <fake>` is the test seam — the command-library pattern);
    `SftpTab._ask_conflict()` is the caller, so a test can also replace the whole
    decision.
    """
    box = QMessageBox(parent)   # a module attribute — the monkeypatch seam
    box.setWindowTitle(_t("sftp.conflict.title"))
    try:
        box.setIcon(QMessageBox.Icon.Question)
    except Exception:   # noqa: BLE001 — an exotic Qt build without the enum
        pass
    box.setText(_t("sftp.conflict.message", name=name, target=target))
    btn_over = box.addButton(_t("sftp.conflict.overwrite"),
                             QMessageBox.ButtonRole.AcceptRole)
    btn_skip = box.addButton(_t("sftp.conflict.skip"),
                             QMessageBox.ButtonRole.RejectRole)
    btn_rename = box.addButton(_t("sftp.conflict.rename"),
                               QMessageBox.ButtonRole.ActionRole)
    check = QCheckBox(_t("sftp.conflict.apply_all"))
    check.setEnabled(int(remaining or 0) > 0)
    box.setCheckBox(check)
    box.exec()
    clicked = box.clickedButton()
    if clicked is btn_over:
        action = "overwrite"
    elif clicked is btn_rename:
        action = "rename"
    else:
        action = "skip"        # Skip, or a cancelled dialog (clickedButton() is None)
    apply_all = bool(check.isChecked()) and action in ("overwrite", "skip")
    return action, apply_all


class _SftpTree(QTreeWidget):
    """The listing tree of the tab (v1.3.3.2, ROADMAP task 5): drag-OUT.

    A row can be dragged into a terminal, an editor or a chat window: the drag
    payload is the REMOTE PATH of the row as `text/plain` (the file itself is not
    transferred). A SUBCLASS, because `startDrag()` is a C++ slot — runtime
    monkey-patching is forbidden (Qt gotcha #7).

    `drag_mime(item)` builds the payload on its own, which is the seam the tests
    read (a real drag needs an event loop and a drop target).
    """

    def startDrag(self, supported_actions):
        mime = self.drag_mime(self.currentItem())
        if mime is None:
            return
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    def drag_mime(self, item):
        """The drag payload of a row: the remote path as text/plain.

        None — nothing to drag (no row / a row without a path).
        """
        if item is None:
            return None
        path = item.data(0, SftpTab.PATH_ROLE)
        if not path:
            return None
        mime = QMimeData()
        mime.setText(str(path))
        return mime


class SftpTab(QWidget):
    """The "Files" tab: listing of the current directory + upload/download via the queue."""

    PATH_ROLE = Qt.ItemDataRole.UserRole       # full remote path of the entry
    ISDIR_ROLE = Qt.ItemDataRole.UserRole + 1  # bool — is it a directory?
    SIZE_ROLE = Qt.ItemDataRole.UserRole + 2   # int — file size (0 for a directory)
    MTIME_ROLE = Qt.ItemDataRole.UserRole + 3  # int — unix mtime

    # v1.3.1: the preview panel — the tree's share of the splitter on the first open.
    VIEWER_TREE_SHARE = 0.45

    # v1.4.7: the blocks formatted AROUND the viewport on either side (the lazy
    # window of the highlighter — a small scroll costs nothing because the
    # neighbours are already done).
    VIEWER_LAZY_MARGIN = syntax.VIEWER_LAZY_MARGIN

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
        # v1.4.7: ONE highlighter per tab (created on the first preview), the
        # language of what is on the screen, and the block window the last
        # formatting pass covered (so a repeated scroll is free).
        self._highlighter = None
        self._viewer_language = syntax.LANG_NUMBERS
        self._highlight_range = None
        # v1.3.1.1: the FACTS about previewability — path → READ_ERROR_* of a read
        # that the worker really refused (see preview_block_reason); per session.
        self._blocked = {}
        self._blocked_icon_cache = None
        # v1.3.3.2 (ROADMAP task 1): the file operations — task_id → kind, so an
        # answer refreshes the listing and an error is reported as an OPERATION
        # error (the queue itself is untouched), and the pre-flight listings of a
        # drop on a directory row — task_id → (target dir, local files).
        self._op_tasks = {}
        self._pending_batches = {}
        self._drag_source = None      # the widget the current drag event came from

        t = _t
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)

        # Path row — the current directory (the "address bar").
        self.path_label = QLabel(t("sftp.waiting_connection"))
        _apply_status_style(self.path_label, "status.sftp_row")
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
        self.tree = _SftpTree()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([t("sftp.column_name"), t("sftp.column_size"),
                                   t("sftp.column_modified")])
        self.tree.setRootIsDecorated(True)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.setColumnWidth(0, 320)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        # v1.3.3.2: the operations live in the context menu (the QActions are built
        # by _build_context_menu — the test seam; exec() never runs in the tests).
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        # v1.3.3.2: drag-OUT — a dragged row hands out its remote path as text/plain
        # (DragOnly: the tree never accepts its own drops; D&D INTO the tab is
        # handled by the tab's own eventFilter, which consumes those events first).
        self.tree.setDragEnabled(True)
        self.tree.setDragDropMode(QTreeWidget.DragDropMode.DragOnly)
        self.tree.setToolTip(t("sftp.drag_hint"))

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
        _apply_status_style(self.viewer_label, "status.sftp_row")
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
        # v1.4.7: the lazy hook — updateRequest fires on a scroll AND on a
        # resize, which is exactly the two moments new blocks become visible.
        self.viewer_text.updateRequest.connect(self._on_viewer_update_request)
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

    def refresh_theme(self):
        """v1.4.3 (ROADMAP task 4): re-apply the theme to this tab's own labels.

        Both label styles come from the ONE registry (`_apply_status_style`), so
        the switch is the same call the constructor made. Never raises.

        v1.4.7: the syntax colours are read LIVE from the active `Theme` by the
        highlighter (its format cache is keyed by the instance), but the formats
        already APPLIED to the visible blocks are values — so the highlighter is
        asked to drop them and repaint the window.
        """
        for widget in (getattr(self, "path_label", None),
                       getattr(self, "viewer_label", None)):
            if widget is None:
                continue
            try:
                _apply_status_style(widget, "status.sftp_row")
            except RuntimeError:
                continue  # Qt teardown — this label is already destroyed
        if self._highlighter is not None:
            try:
                self._highlighter.refresh_theme()
            except RuntimeError:
                pass  # Qt teardown — the document is already gone

    def retranslate(self):
        """v1.3.3.1: re-text the tab's own strings in the current language.

        Every string already has an i18n key (ZERO new keys): the five buttons,
        the three column headers, the viewer's close tooltip and the "no preview"
        row tooltips. The module translator (`i18n.t`) is looked up at call time,
        so no cache has to be invalidated.

        v1.3.3.2: the drag-out hint of the tree (the context menu is rebuilt on
        every right click and needs nothing here).

        v1.4.7: the heuristic-highlighting note of the viewer header
        (`sftp.viewer.syntax_heuristic`) is deliberately NOT re-texted here — like
        the path and the size it describes the file ON THE SCREEN; the next
        preview renders it in the active language.

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
            self.tree.setToolTip(_t("sftp.drag_hint"))
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
        # v1.3.3.2: the operation answers and the pre-flight listings belong to the
        # transport that was asked — a new worker starts with a clean bookkeeping.
        self._op_tasks.clear()
        self._pending_batches.clear()
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
        worker.task_done.connect(self._on_task_done)
        worker.task_error.connect(self._on_task_error)
        worker.task_cancelled.connect(self._on_task_cancelled)
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
        # v1.3.3.2: the pre-flight listing of a drop on a directory row — the answer
        # is NOT rendered (that directory is not on the screen), it only feeds the
        # conflict check of the batch that is waiting for it.
        pending = self._pending_batches.pop(task_id, None)
        if pending is not None:
            target, files = pending
            self._queue_uploads(files, target, {e["name"] for e in entries})
            self.message.emit(
                _t("sftp.drop_queued", count=len(files), dir=target))
            return
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
        elif kind in OP_KINDS:
            # v1.3.3.2: a file operation failed (the queue lives on) — the tab owns
            # the message (the page stays silent about the operation kinds), and the
            # listing is NOT refreshed: nothing changed on the server.
            self._op_tasks.pop(task_id, None)
            self.message.emit(_t("sftp.op.error", error=message))
        elif kind == "list":
            # v1.3.3.2: the pre-flight listing of a drop on a row failed (the
            # directory vanished / no permission) — the batch is dropped, the tab
            # reports the reason instead of uploading into nowhere.
            pending = self._pending_batches.pop(task_id, None)
            if pending is not None:
                self.message.emit(_t("sftp.op.error", error=message))
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
        """Fill the panel with the file and show it (an unshown panel gets sizes).

        v1.4.7: the language is decided from the path AND the content
        (`syntax.detect_syntax` — the honesty rule: a `.json`/`.xml` hint is
        accepted only after a real parse) and the tab's ONE highlighter colours
        the blocks around the viewport. The header carries the heuristic note
        for the modes no parser verified (YAML), exactly like the encoding note.
        """
        language = syntax.detect_syntax(path, text)
        head = _t("sftp.viewer.header", path=path, size=format_size(size))
        if encoding != "utf-8":
            head = f"{head} · {_t('sftp.viewer.encoding_note', encoding=encoding)}"
        if syntax.is_heuristic(language):
            head = f"{head} · {_t('sftp.viewer.syntax_heuristic', language=language)}"
        self.viewer_label.setText(head)
        self.viewer_label.setToolTip(path)
        self._viewer_encoding = encoding
        self._viewer_language = language
        highlighter = self._ensure_highlighter()
        if highlighter is not None:
            highlighter.set_language(language)
            # BEFORE setPlainText: Qt reformats the WHOLE changed range, and with
            # an EMPTY window that pass applies no format at all — which is what
            # keeps the previous file from bleeding into this one.
            highlighter.reset_for_document()
        self._highlight_range = None
        self.viewer_text.setPlainText(text)   # the cursor lands at the start by itself
        if self.viewer.isHidden():
            self.viewer.show()
            # Qt gotcha #13: the splitter member's share is set via setSizes only.
            total = max(self.splitter.width(), 640)
            left = int(total * self.VIEWER_TREE_SHARE)
            self.splitter.setSizes([left, total - left])
        self._highlight_visible(force=True)

    # ── v1.4.7 (ROADMAP task 3/4): the lazy syntax highlighting ─────────────

    def _ensure_highlighter(self):
        """The tab's ONE highlighter (built on the first preview, reused after).

        A viewer must keep working when the highlighter cannot be built (an
        exotic Qt build): the preview then stays monochrome, which is exactly
        the v1.3.1 behaviour.
        """
        if self._highlighter is None:
            try:
                self._highlighter = syntax.create_highlighter(
                    self.viewer_text.document())
            except Exception:   # noqa: BLE001 — highlighting is never critical
                self._highlighter = None
        return self._highlighter

    def _viewer_block_range(self):
        """The block numbers on the screen → `(first, last)`, or None.

        Measured from the LAYOUT (`blockBoundingGeometry` + `contentOffset`), so
        it answers correctly for a hidden panel too (it degrades to block 0).
        """
        edit = self.viewer_text
        try:
            block = edit.firstVisibleBlock()
            if not block.isValid():
                return None
            height = edit.viewport().height()
            offset = edit.contentOffset()
            first = last = block.blockNumber()
            while block.isValid():
                if edit.blockBoundingGeometry(block).translated(offset).top() > height:
                    break
                last = block.blockNumber()
                block = block.next()
            return first, last
        except RuntimeError:
            return None   # the C++ object was already destroyed (a close race)

    def _highlight_visible(self, force: bool = False) -> int:
        """Format the blocks around the viewport (v1.4.7 task 4 — the lazy half).

        A 1 MB file is ~20 000 blocks and `setPlainText()` marks every one of
        them dirty, so the EXPENSIVE half (turning spans into text formats) is
        applied only to the visible window ± `VIEWER_LAZY_MARGIN`; the block
        STATE is still computed for every line, because the state of a line
        depends on the line before it. A repeated call whose window is already
        done costs one comparison.

        Returns the number of blocks really rehighlighted.
        """
        highlighter = self._highlighter
        if highlighter is None:
            return 0
        window = self._viewer_block_range()
        if window is None:
            return 0
        first = max(0, window[0] - self.VIEWER_LAZY_MARGIN)
        last = window[1] + self.VIEWER_LAZY_MARGIN
        if not force and (first, last) == self._highlight_range:
            return 0
        self._highlight_range = (first, last)
        highlighter.set_window(first, last)
        return highlighter.highlight_window(force=force)

    def _on_viewer_update_request(self, _rect, dy):
        """`QPlainTextEdit.updateRequest`: a scroll (`dy != 0`) or a resize.

        A hidden panel is skipped: the content of a closed viewer is gone, and
        `clear()` fires the signal while it empties the document — formatting a
        block nobody can see would only leave a mark behind.
        """
        if self.viewer.isHidden():
            return
        self._highlight_visible()

    @property
    def viewer_highlighter(self):
        """The tab's highlighter (None until the first preview — the test seam)."""
        return self._highlighter

    @property
    def viewer_language(self) -> str:
        """The language the shown content was detected as (v1.4.7)."""
        return self._viewer_language

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
        # v1.4.7: the panel is empty → the formatting pass has nothing to cover.
        self._highlight_range = None
        if self._highlighter is not None:
            self._highlighter.reset_for_document()
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
        if not files:
            return   # the dialog was cancelled
        self._queue_uploads(files, self._current_dir,
                            self._names_in_current_dir())

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
        self._queue_downloads(items, local_dir)

    def _on_cancel(self):
        if self._worker is not None:
            self._worker.cancel()

    # ── v1.3.3.2: the batch + the overwrite conflict (ROADMAP task 2) ────

    def _names_in_current_dir(self) -> set:
        """The names the CURRENT listing shows.

        The conflict check must never be a guess, and the tree is exactly what the
        server last answered for the shown directory (a row of another directory
        cannot be in it).
        """
        names = set()
        try:
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item is self._up_item:
                    continue
                names.add(item.text(0))
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)
        return names

    def _ask_conflict(self, name: str, target: str, remaining: int):
        """The overwrite question — a method so a test can replace the whole policy."""
        return ask_conflict(self, name, target, remaining)

    def _conflict_decision(self, name: str, target: str, remaining: int):
        """The decision of ONE conflict → `(action, apply_all)`.

        action ∈ `"overwrite" | "skip" | "rename"`; a cancelled dialog — and any
        broken answer of a replaced seam — is a SKIP: the destination is left alone
        and the batch goes on. `apply_all` asks to reuse the decision for the REST
        of this batch (never for "rename": a batch rename needs a name per file).
        """
        try:
            action, apply_all = self._ask_conflict(name, target, remaining)
        except Exception:   # noqa: BLE001 — a dialog must never break a transfer
            return "skip", False
        if action not in ("overwrite", "skip", "rename"):
            return "skip", False
        if action == "rename":
            return action, False
        return action, bool(apply_all)

    def _prompt_name(self, title: str, current: str = "") -> str:
        """The name input of New folder / Rename (QInputDialog — a module attribute:
        `STAB.QInputDialog = <fake>` is the test seam).

        Returns the validated name; "" — cancelled or invalid (empty, ".", "..",
        a path separator): the caller quietly does nothing. The worker never sees a
        name it would have to sanitize.
        """
        try:
            text, ok = QInputDialog.getText(self, title, _t("sftp.op.name_prompt"),
                                            text=current)
        except Exception:   # noqa: BLE001 — a dialog must never break the tab
            return ""
        if not ok:
            return ""
        name = (text or "").strip()
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            self.message.emit(_t("sftp.op.invalid_name"))
            return ""
        return name

    def _queue_uploads(self, files: list, target_dir: str, known: set):
        """Queue a batch of local files into target_dir, resolving the conflicts.

        `known` — the names already present in target_dir (from a LISTING of that
        directory: the current listing for the Upload button and for a drop on the
        body, the pre-flight listing for a drop on a directory row). "Apply to all"
        of the dialog is remembered for the REST of this batch only.
        """
        worker = self._worker
        if worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        apply_all = ""
        total = len(files)
        for index, local_path in enumerate(files):
            name = os.path.basename(local_path)
            if name in known:
                if apply_all:
                    action = apply_all
                else:
                    action, to_all = self._conflict_decision(
                        name, target_dir, total - index - 1)
                    if to_all:
                        apply_all = action
                if action == "skip":
                    continue
                if action == "rename":
                    new_name = self._prompt_name(_t("sftp.op.rename"), name)
                    if not new_name:
                        continue   # cancelled → this file is skipped
                    name = new_name
            worker.queue_upload(local_path, target_dir, remote_name=name)

    def _queue_downloads(self, items: list, local_dir: str):
        """Queue a batch of remote files into local_dir, resolving the conflicts.

        The local existence check is a plain `os.path.exists` — no listing and no
        network, so it can never be stale.
        """
        worker = self._worker
        if worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        apply_all = ""
        total = len(items)
        for index, item in enumerate(items):
            remote_path = item.data(0, self.PATH_ROLE)
            name = posixpath.basename(remote_path)
            if os.path.exists(os.path.join(local_dir, name)):
                if apply_all:
                    action = apply_all
                else:
                    action, to_all = self._conflict_decision(
                        name, local_dir, total - index - 1)
                    if to_all:
                        apply_all = action
                if action == "skip":
                    continue
                if action == "rename":
                    new_name = self._prompt_name(_t("sftp.op.rename"), name)
                    if not new_name:
                        continue
                    name = new_name
            worker.queue_download(remote_path, local_dir,
                                  item.data(0, self.SIZE_ROLE), local_name=name)

    # ── v1.3.3.2: the file operations (ROADMAP task 1) ───────────────────

    def _on_context_menu(self, pos):
        """The tree's context menu (the seam is `_build_context_menu(item)`)."""
        try:
            item = self.tree.itemAt(pos)
        except RuntimeError:
            return   # the C++ object is already deleted (a close race)
        menu = self._build_context_menu(item)
        if menu is not None:
            menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _build_context_menu(self, item=None):
        """New folder / Rename / Delete / Copy remote path (a test seam: the tests
        trigger the QActions directly — `menu.exec()` never runs offscreen).

        Rename/Delete/Copy are enabled only for a REAL row of the current listing
        (never for the ".." row, never for empty space) — a disabled item is the
        hint, the actions themselves stay defensive.
        """
        menu = QMenu(self)
        act_new = menu.addAction(_t("sftp.op.new_folder"))
        act_rename = menu.addAction(_t("sftp.op.rename"))
        act_delete = menu.addAction(_t("sftp.op.delete"))
        act_copy = menu.addAction(_t("sftp.op.copy_path"))
        menu.addSeparator()
        act_refresh = menu.addAction(_t("sftp.refresh"))

        real = (item is not None and item is not self._up_item
                and bool(item.data(0, self.PATH_ROLE)))
        for act in (act_rename, act_delete, act_copy):
            act.setEnabled(bool(real))

        act_new.triggered.connect(lambda: self._op_new_folder())
        act_refresh.triggered.connect(lambda: self._relist(self._current_dir))
        if real:
            act_rename.triggered.connect(lambda: self._op_rename(item))
            act_delete.triggered.connect(lambda: self._op_delete(item))
            act_copy.triggered.connect(lambda: self._op_copy_path(item))
        return menu

    def _op_new_folder(self):
        """New folder in the CURRENT directory (mkdir through the worker queue)."""
        if self._worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        name = self._prompt_name(_t("sftp.op.new_folder"))
        if not name:
            return
        self._queue_op(self._worker.queue_mkdir(self._current_dir, name), KIND_MKDIR)

    def _op_rename(self, item):
        """Rename a row inside its own directory (only the NAME changes)."""
        if self._worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        path = item.data(0, self.PATH_ROLE)
        if not path:
            return
        current = posixpath.basename(path)
        name = self._prompt_name(_t("sftp.op.rename"), current)
        if not name or name == current:
            return   # cancelled, or the name did not change — nothing to do
        self._queue_op(self._worker.queue_rename(path, name), KIND_RENAME)

    def _op_delete(self, item):
        """Delete a row — with a confirmation (QMessageBox — a module attribute).

        A directory is removed with rmdir: a NON-EMPTY one reports the server's
        error (recursive delete is not in this version).
        """
        if self._worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        path = item.data(0, self.PATH_ROLE)
        if not path:
            return
        is_dir = bool(item.data(0, self.ISDIR_ROLE))
        box = QMessageBox   # the monkeypatch STAB.QMessageBox works in the tests
        reply = box.question(
            self, _t("sftp.op.delete"),
            _t("sftp.op.delete_confirm", name=posixpath.basename(path)),
            box.Yes | box.No, box.No)
        if reply != box.Yes:
            return
        self._queue_op(self._worker.queue_delete(path, is_dir), KIND_DELETE)

    def _op_copy_path(self, item):
        """Copy the REMOTE path of the row to the clipboard (never a URL)."""
        path = item.data(0, self.PATH_ROLE)
        if not path:
            return
        try:
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(str(path))
        except Exception:   # noqa: BLE001 — the clipboard is not critical
            pass
        self.message.emit(_t("sftp.op.path_copied"))

    def _queue_op(self, task_id, kind: str):
        """Remember an operation task: its answer refreshes the listing (task_done)
        or reports a message (task_error)."""
        if task_id is not None:
            self._op_tasks[task_id] = kind

    # ── D&D: files from Explorer (v1.2.8) ────────────────────────────────

    _DRAG_TYPES = (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop)

    def eventFilter(self, obj, event):
        """Drag events on the tab's children are forwarded to the tab's OWN
        handlers. Returning True = the event is consumed (QTreeWidget does not
        process it "its own way").

        v1.3.3.2: the SOURCE widget of the event is remembered for the drop — the
        directory under the cursor is resolved in the tree's coordinates whatever
        child (viewport, header, button) received the event.
        """
        etype = event.type()
        if etype in self._DRAG_TYPES and (obj is self or self.isAncestorOf(obj)):
            self._drag_source = obj
            try:
                if etype == QEvent.Type.DragEnter:
                    self.dragEnterEvent(event)
                elif etype == QEvent.Type.DragMove:
                    self.dragMoveEvent(event)
                else:  # Drop
                    self.dropEvent(event)
            finally:
                self._drag_source = None
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
        target = self._drop_target_dir(event)
        files = self._local_files(event.mimeData())
        if files:
            event.acceptProposedAction()
        self._on_drop(files, target)

    def _item_under(self, event):
        """The listing row under a drag event (None — empty space / outside the tree).

        The event may arrive from any child (the tab's eventFilter forwards it): the
        point is mapped into the viewport's coordinates first, so the row is found
        regardless of who received the event.
        """
        try:
            pos = event.position().toPoint()
        except AttributeError:   # an older event object without position()
            pos = event.pos()
        source = self._drag_source or self
        try:
            if source is not self.tree.viewport():
                pos = self.tree.viewport().mapFrom(source, pos)
            return self.tree.itemAt(pos)
        except (RuntimeError, TypeError):
            return None   # the C++ object is gone / the source is not an ancestor

    def _drop_target_dir(self, event) -> str:
        """v1.3.3.2 (ROADMAP task 4): the directory UNDER THE CURSOR.

        A directory row (including "..") is the target; a file row and empty space
        keep the current directory — the second half of the "drop into a specific
        row" promise quoted in the goal of the version.
        """
        item = self._item_under(event)
        if item is not None and item.data(0, self.ISDIR_ROLE):
            return item.data(0, self.PATH_ROLE) or self._current_dir
        return self._current_dir

    def _on_drop(self, files: list, target_dir: str = ""):
        """Drop result: upload into the directory under the cursor.

        The conflict check must not be a guess, so a target directory that is NOT on
        the screen is LISTED first (a "list" task of the same queue) and the batch is
        queued when the answer arrives — see `_on_list_ready`.
        """
        target = target_dir or self._current_dir
        if not files:
            # No local files in the drag (directories/other data).
            self.message.emit(_t("sftp.drop_no_files"))
            return
        if self._worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        if target == self._current_dir:
            # The listing on the screen IS the answer of the server for that
            # directory — the conflict check needs nothing else.
            self._queue_uploads(files, target, self._names_in_current_dir())
        else:
            task_id = self._worker.queue_list(target)
            if task_id is not None:
                self._pending_batches[task_id] = (target, files)
                return   # the hint + the uploads follow the listing answer
            self._queue_uploads(files, target, set())
        self.message.emit(_t("sftp.drop_queued", count=len(files), dir=target))

    # ── Transfer state (the "Cancel" button) ─────────────────────────────

    def _on_task_started(self, task_id: int, kind: str, _label: str):
        if kind in ("upload", "download"):
            self._transfer_tasks.add(task_id)
            self.btn_cancel.setEnabled(True)

    def _on_task_done(self, task_id: int, detail: str):
        """task_done: an OPERATION refreshes the listing (v1.3.3.2) and reports the
        result; a transfer and a read keep their v1.1.3/v1.3.1 handling."""
        kind = self._op_tasks.pop(task_id, None)
        if kind is not None:
            self.message.emit(_t("sftp.op.done", name=detail))
            self._relist(self._current_dir)
        self._on_task_finished(task_id)

    def _on_task_cancelled(self, task_id: int, _kind: str):
        self._op_tasks.pop(task_id, None)
        # A cancelled pre-flight listing: its batch will never be queued (the
        # bookkeeping must not leak into the next transport).
        self._pending_batches.pop(task_id, None)
        self._on_task_finished(task_id)

    def _on_task_finished(self, task_id: int):
        # v1.3.1: a read task that ended without an answer (cancelled) leaves no trace.
        self._read_tasks.pop(task_id, None)
        if task_id in self._transfer_tasks:
            self._transfer_tasks.discard(task_id)
            if not self._transfer_tasks:
                self.btn_cancel.setEnabled(False)
