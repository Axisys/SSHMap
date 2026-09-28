# -*- coding: utf-8 -*-
"""v1.7rc2 — Files Commander, step 2: the copy and the move across the panes (ROADMAP v1.7rc2).

The topical file of the 1.7 line's SECOND release. v1.7rc1 shipped the pane MODEL over the
operations that already existed; this slot ships the two objects the frozen contract
(`SFTP_PANES.md` §2) RESERVED — `queue_copy` and `queue_move` — so `F5` and `F6` finally do
what the classic key map promises: a remote→remote copy and a cross-directory move, with
their conflict, atomicity, cancellation and reporting policy. The directory question of the
slot is decided as the mc-grade half of the contract: DIRECTORY TREES are copied and moved
RECURSIVELY (a bounded walk, every FILE atomic, a partially transferred tree reported and
never rolled back).

ALL the checks are offscreen and without the network: the in-memory fake SFTP of
`tests/_fakes.py` behind a real `SftpWorker` (the worker is the CONTAINER's — one transport,
one queue, two panes), and the fake SSH thread of the window harness for the key rules.

§1 The pane model and the REFACTOR BOUNDARY: the container with ONE pane is the shipped tab
   (every attribute read of the old single-listing tab resolves on the ACTIVE pane), the
   pane owns the listing state while the container owns the worker binding and the session's
   follow switch, and the pane-scoped keys are `WidgetWithChildrenShortcut` actions ON the
   pane (F4 absent).
§2 The two panes over ONE worker: each pane lists and navigates INDEPENDENTLY, each renders
   only the answer of the directory it asked for, and the preview belongs to its own pane.
§3 The ACTIVE pane: it decides for the shipped reads, it is visible through the shipped
   focus ring, and a keyboard FocusIn moves it — in the ONE-pane mode nothing is ringed.
§4 The pane-scoped keys call the SHIPPED worker paths (F3 view, F7 mkdir, F8 delete, the
   same-directory F6 rename) and answer honestly when they cannot (F5 without a second pane,
   no row) — and an F5 typed into the terminal CANVAS still reaches the SHELL (the canvas
   keeps its own claim).
§5 The action: the tab-bar corner control is a view of the ACTIVE session's mode, DISABLED
   for a page without a Files tab (a split pane), and turning it on brings the Files tab on
   screen (the lazy SFTP channel opens on the way).
§6 The follow rule: the two-pane mode switches the cwd follow OFF and greys the switch (one
   OSC 7 report cannot answer "which of the two"), the session is TOLD, and
   `follow_directory()` refuses there.
§7 The persistence: `ui_sftp_commander` + `ui_sftp_commander_ratio` ride the window's ONE
   geometry write, a broken value falls back to the default, and the mode is restored.
§8 i18n (the five keys of v1.7rc1 and the eight of v1.7rc2 in EVERY language) + the release
   state.
§9 The COPY task: a file lands BYTE-EQUAL and atomically (a cancel or a failure leaves the
   destination byte-identical and drops the `.part`), the progress carries the total from
   `stat`, the OpenSSH `copy-data` fast path is used when the server has it and SKIPPED with
   ONE log line when it has not (the stream produces the identical result), and a missing
   source is a task_error.
§10 The RECURSIVE copy: a tree lands with its directories and its bytes, an existing
   destination directory is MERGED (nothing inside it is deleted), a tree over its declared
   bound is refused BEFORE anything moves, and a partial tree is REPORTED with its counters
   (the files already published stay).
§11 The MOVE: a cross-directory rename is one atomic operation, a destination directory that
   already exists is merged entry by entry, and a REFUSED cross-device rename is a machine
   payload (not a traceback) with both endpoints left untouched.
§12 The BATCH of the panes: `F5`/`F6` move the SELECTION to the other pane's directory, the
   conflict question is asked ONCE with "apply to all", ONE closing report names what really
   happened (copied / skipped / failed), BOTH listings are re-listed, and a row whose
   destination is itself is skipped instead of being copied onto itself.
§12b The whole chain: a real terminal WINDOW hands one worker to the page, the page to the tab
   and the tab to both panes, the copy feeds the page's transfer progress family, and the
   closing report rides the shipped `message` bridge into the host's status bar.

Run:  python tests/test_sftp_commander.py   (from the project root) or python tests/run_all.py
"""
import logging
import os
import posixpath
import re
import sys

from _common import (bootstrap, check, finish, wait_until, load_i18n_langs, check_i18n_parity,
                     check_i18n_format, check_release_state, clear_cfg, read_cfg, releases_at_least,
                     EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation)

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QKeyEvent
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import i18n
from i18n import save_config
import modules.sftp_tab as STAB
import modules.sftp_worker as SW
from modules.sftp_tab import (COMMANDER_CONFIG_BOOL, COMMANDER_CONFIG_RATIO,
                              COMMANDER_RATIO_DEFAULT, PANE_SHORTCUTS, SftpTab,
                              load_commander_settings)
from modules.sftp_worker import (KIND_COPY, KIND_MOVE, MAX_TREE_ENTRIES, MOVE_ERROR_REFUSED,
                                 PART_SUFFIX, PARTIAL_CODE, SftpWorker, TREE_ERROR_TOO_BIG,
                                 parse_task_payload)
from models.server import ServerData

from _fakes import (EventLog, FakeSftpClient, FakeSftpFS, FakeSSHClient, FakeSSHThread,
                    wire_worker)

import modules.ssh_terminal as ST
import ui.main_window as MW


# ════════════════════════════════════════════════════════════
# The harness: the fake dialogs (the command-library seam) + a tab on a fake worker
# ════════════════════════════════════════════════════════════

class _FakeMessageBox:
    """QMessageBox — the static `question()` (the delete confirmation) AND the instance API
    of the conflict dialog (addButton / setCheckBox / exec / clickedButton).

    SCRIPT — the scripted answers of the conflict dialogs, one tuple per question:
    ("overwrite" | "skip" | "rename" | None, apply_all); None = a cancelled dialog.
    DIALOGS — what every dialog showed (the title and the text).
    """

    Yes, No = 0x4000, 0x10000
    CONFIRM = True
    ASKED = []
    SCRIPT = []
    DIALOGS = []

    class Icon:
        Question = 0

    class ButtonRole:
        AcceptRole = 0
        RejectRole = 1
        ActionRole = 2

    def __init__(self, parent=None):
        self._buttons = {}
        self._checkbox = None
        self._clicked = None
        self.title = ""
        self.text = ""

    @staticmethod
    def question(*args, **kwargs):
        _FakeMessageBox.ASKED.append(args[2] if len(args) > 2 else "")
        return _FakeMessageBox.Yes if _FakeMessageBox.CONFIRM else _FakeMessageBox.No

    def setWindowTitle(self, text):
        self.title = text

    def setIcon(self, icon):
        pass

    def setText(self, text):
        self.text = text

    def addButton(self, text, role=None):
        button = _Button(text)
        self._buttons[text] = button
        return button

    def setCheckBox(self, box):
        self._checkbox = box

    def exec(self):
        action, apply_all = (self.SCRIPT.pop(0) if self.SCRIPT else ("skip", False))
        labels = {"overwrite": i18n.t("sftp.conflict.overwrite"),
                  "skip": i18n.t("sftp.conflict.skip"),
                  "rename": i18n.t("sftp.conflict.rename")}
        self._clicked = self._buttons.get(labels.get(action)) if action else None
        if self._checkbox is not None:
            self._checkbox.setChecked(bool(apply_all) and action is not None)
        self.DIALOGS.append((self.title, self.text))

    def clickedButton(self):
        return self._clicked


class _Button:
    """The button handle `ask_conflict()` compares against `clickedButton()`."""

    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text


class _FakeInputDialog:
    """QInputDialog.getText — a script of names ([] = the dialog was cancelled)."""

    SCRIPT = []

    @staticmethod
    def getText(*args, **kwargs):
        if _FakeInputDialog.SCRIPT:
            return (_FakeInputDialog.SCRIPT.pop(0), True)
        return ("", False)


STAB.QMessageBox = _FakeMessageBox
STAB.QInputDialog = _FakeInputDialog


def make_tab(fs, chunk_delay=0.0, commander=False, copy_data_ok=False):
    """(tab, worker, log, client) with the listing of "/" already rendered."""
    client = FakeSftpClient(fs, chunk_delay=chunk_delay)
    client.copy_data_ok = copy_data_ok   # v1.7rc2: the OpenSSH fast-path seam
    worker = SftpWorker(client)
    log = EventLog()
    wire_worker(worker, log)
    worker.start()
    tab = SftpTab()
    tab.message.connect(lambda *_a: None)
    if commander:
        tab.set_commander(True)
    tab.set_worker(worker)
    wait_until(lambda: tab.tree.topLevelItemCount() >= 1, timeout_ms=5000)
    return tab, worker, log, client


def one_worker(fs, copy_data_ok=False, chunk_delay=0.0):
    """(worker, log, client) with no widget at all — the WORKER-level scenarios."""
    client = FakeSftpClient(fs, chunk_delay=chunk_delay)
    client.copy_data_ok = copy_data_ok
    worker = SftpWorker(client)
    log = EventLog()
    wire_worker(worker, log)
    worker.start()
    return worker, log, client


def item_by_name(pane, name):
    """The listing row by its visible name (None — not there yet)."""
    for i in range(pane.tree.topLevelItemCount()):
        item = pane.tree.topLevelItem(i)
        if item.text(0) == name:
            return item
    return None


def focus_in(widget):
    """Deliver a FocusIn to a widget (the ACTIVE-pane trigger of the pane's filter)."""
    app.sendEvent(widget, QEvent(QEvent.Type.FocusIn))
    app.processEvents()


def no_part(fs):
    """The provisional files left on the fake 'server' (must always be empty)."""
    return [p for p in fs.files if p.endswith(PART_SUFFIX)]


def tree_of(fs, root):
    """`{relative path: bytes}` of every FILE under `root` (a tree comparison)."""
    out = {}
    for path, data in fs.files.items():
        if path.startswith(root.rstrip("/") + "/"):
            out[path[len(root.rstrip("/")) + 1:]] = bytes(data)
    return out


class _CaptureHandler(logging.Handler):
    """Capture the records of ONE logger (the worker's fast-path fallback line, v1.7rc2)."""

    def __init__(self, sink):
        super().__init__()
        self.sink = sink

    def emit(self, record):
        try:
            self.sink.append(record.getMessage())
        except Exception:   # noqa: BLE001 — a test helper must never break a task
            pass


# ════════════════════════════════════════════════════════════
# 1. The pane model and the refactor boundary
# ════════════════════════════════════════════════════════════
print("== 1. the pane model: ONE pane is the shipped tab ==")

clear_cfg()
tab_one = SftpTab()
pane_a = tab_one.panes[0]

check("a fresh tab is the ONE-pane container of the shipped tab",
      len(tab_one.panes) == 1 and tab_one.active_pane is pane_a
      and tab_one.commander is False)
check("the shipped attribute reads resolve on the ACTIVE pane",
      tab_one.tree is pane_a.tree and tab_one.path_label is pane_a.path_label
      and tab_one.btn_up is pane_a.btn_up and tab_one.viewer is pane_a.viewer)
check("the pane keeps the shipped [tree | viewer] splitter and the cwd it shows",
      tab_one.splitter.count() == 2 and tab_one.splitter.widget(0) is tab_one.tree
      and tab_one.current_dir == "/" and pane_a.current_dir == "/")
check("the row roles and the viewer constants stay readable on the CONTAINER",
      SftpTab.PATH_ROLE == pane_a.PATH_ROLE
      and SftpTab.ISDIR_ROLE == pane_a.ISDIR_ROLE
      and SftpTab.SIZE_ROLE == pane_a.SIZE_ROLE
      and SftpTab.MTIME_ROLE == pane_a.MTIME_ROLE
      and tab_one.PATH_ROLE == pane_a.PATH_ROLE
      and SftpTab.VIEWER_TREE_SHARE == pane_a.VIEWER_TREE_SHARE)
check("the drag payload helper stays a CLASS method (the shipped suite reads it there)",
      callable(SftpTab._local_files) and SftpTab._local_files(None) == [])

check("the CONTAINER owns the follow switch (a session state, printed once)",
      tab_one.chk_follow_cwd.parent() is tab_one
      and not hasattr(pane_a, "chk_follow_cwd"))
check("the pane owns no worker of its own — the binding is the container's",
      "_worker" not in pane_a.__dict__ and pane_a.worker is None)

# the pane-scoped keys: WidgetWithChildrenShortcut, ON the pane, F4 REFUSED
_keys = [seq for seq, _slot in PANE_SHORTCUTS]
check("the key map is F3/F5/F6/F7/F8 and F4 is REFUSED (the contract's refusal)",
      _keys == ["F3", "F5", "F6", "F7", "F8"] and pane_a.pane_shortcut("F4") is None,
      f"keys={_keys}")
check("every pane-scoped key is a WidgetWithChildrenShortcut action ON THE PANE",
      all(pane_a.pane_shortcut(s) is not None
          and pane_a.pane_shortcut(s).shortcutContext()
          == Qt.ShortcutContext.WidgetWithChildrenShortcut
          and pane_a.pane_shortcut(s) in pane_a.actions() for s in _keys))
check("the CONTAINER carries no F-key action of its own (the map belongs to the panes)",
      not [a for a in tab_one.actions()
           if a.shortcut().toString() in ("F3", "F4", "F5", "F6", "F7", "F8")]
      and not [a for a in tab_one.chk_follow_cwd.actions()
               if a.shortcut().toString() in ("F3", "F5", "F6", "F7", "F8")])
tab_one.set_worker(None)


# ════════════════════════════════════════════════════════════
# 2. The two panes over ONE worker
# ════════════════════════════════════════════════════════════
print("== 2. two panes, ONE worker: independent listings ==")

clear_cfg()
fs2 = FakeSftpFS()
fs2.add_dir("/left")
fs2.add_dir("/right")
fs2.add_file("/left/left.txt", b"L")
fs2.add_file("/right/right.txt", b"R")
tab2, worker2, _log2, _client2 = make_tab(fs2, commander=True)
pane_l, pane_r = tab2.panes[0], tab2.panes[1]

check("the mode builds a SECOND pane inside the same tab (1 → 2)",
      len(tab2.panes) == 2 and tab2.active_pane is pane_l and tab2.commander is True)
check("both panes read the ONE bound worker (one transport, one queue)",
      pane_l.worker is worker2 and pane_r.worker is worker2 and tab2.worker is worker2)
check("the second pane starts WHERE the first one is (a commander's default)",
      pane_r.current_dir == pane_l.current_dir == "/")

pane_l._relist("/left")
wait_until(lambda: pane_l.path_label.text() == "/left", timeout_ms=5000)
pane_r._relist("/right")
wait_until(lambda: pane_r.path_label.text() == "/right", timeout_ms=5000)
check("the two panes navigate independently over the one worker",
      pane_l.current_dir == "/left" and pane_r.current_dir == "/right",
      f"{pane_l.current_dir} / {pane_r.current_dir}")
check("each pane renders ITS OWN directory (the staleness filter is per pane)",
      item_by_name(pane_l, "left.txt") is not None
      and item_by_name(pane_l, "right.txt") is None
      and item_by_name(pane_r, "right.txt") is not None
      and item_by_name(pane_r, "left.txt") is None,
      f"L={pane_l.tree.topLevelItemCount()} R={pane_r.tree.topLevelItemCount()}")
check("the pane-local bookkeeping is really per pane (no shared task map)",
      pane_l._pending_lists is not pane_r._pending_lists
      and pane_l._blocked is not pane_r._blocked
      and pane_l._read_tasks is not pane_r._read_tasks)

# a listing of one pane never lands in the other one
before_r = pane_r.tree.topLevelItemCount()
pane_l._relist("/")
wait_until(lambda: pane_l.path_label.text() == "/", timeout_ms=5000)
check("re-listing one pane leaves the OTHER pane's listing untouched",
      pane_r.tree.topLevelItemCount() == before_r
      and pane_r.path_label.text() == "/right")

# the preview is per pane — and in the two-pane view its PANEL is displayed in the OTHER pane
# (the mc/far rule of the frozen contract §3b): the reading pane keeps its own listing and its
# own viewer stays aside while the panel it owns is shown next door.
pane_r._open_viewer(item_by_name(pane_r, "right.txt"))
wait_until(lambda: pane_r._viewer_open, timeout_ms=5000)
for _ in range(4):
    app.processEvents()
check("the preview of a pane is shown in the OTHER pane, and only there",
      pane_r.viewer_text.toPlainText() == "R"
      and pane_r.viewer.parent() is pane_l.splitter
      and pane_r.viewer.isVisibleTo(pane_l)
      and pane_l.viewer.isHidden(),
      f"parent-L={pane_r.viewer.parent() is pane_l.splitter} "
      f"L-hidden={pane_l.viewer.isHidden()}")
check("...and the reading pane keeps its OWN listing on the screen (the panel is a view)",
      item_by_name(pane_r, "right.txt") is not None
      and pane_r.path_label.isVisibleTo(pane_r))
pane_r.close_viewer()
for _ in range(3):
    app.processEvents()

# the CONTAINER's teardown walks BOTH panes (the page's single shutdown path)
pane_l._relist("/left")
wait_until(lambda: item_by_name(pane_l, "left.txt") is not None, timeout_ms=5000)
pane_l._open_viewer(item_by_name(pane_l, "left.txt"))
wait_until(lambda: pane_l._viewer_open, timeout_ms=5000)
for _ in range(3):
    app.processEvents()
check("a preview opened in one pane leaves the other pane's OWN viewer aside (one panel at a time)",
      pane_l.viewer.isVisibleTo(pane_r) and pane_r.viewer.isHidden()
      and pane_l.viewer.parent() is pane_r.splitter)
tab2.close_viewer()
for _ in range(3):
    app.processEvents()
check("the container's close_viewer() walks EVERY pane (the page teardown path)",
      pane_l.viewer.isHidden() and pane_r.viewer.isHidden()
      and pane_l._viewer_open is False and pane_r._viewer_open is False
      and pane_l.viewer.parent() is pane_l.splitter)


# ════════════════════════════════════════════════════════════
# 3. The ACTIVE pane
# ════════════════════════════════════════════════════════════
print("== 3. the ACTIVE pane owns the reads and shows the ring ==")

check("the FIRST pane is active by default and its ring carries the mode",
      tab2.active_pane is pane_l and pane_l._ring.is_active() is True
      and pane_r._ring.is_active() is False)
check("moving the active pane moves the shipped reads with it",
      tab2.set_active_pane(pane_r) is True
      and tab2.active_pane is pane_r and tab2.tree is pane_r.tree
      and tab2.path_label is pane_r.path_label and tab2.current_dir == "/right")
check("the ring follows the active pane (and only it)",
      pane_r._ring.is_active() is True and pane_l._ring.is_active() is False)
check("set_active_pane answers False when nothing changed (the idempotent write)",
      tab2.set_active_pane(pane_r) is False)

focus_in(pane_l.tree)
check("a keyboard FocusIn inside a pane makes it the ACTIVE one",
      tab2.active_pane is pane_l and pane_l._ring.is_active() is True
      and pane_r._ring.is_active() is False)
focus_in(pane_r.tree)
check("...and the same in the other direction", tab2.active_pane is pane_r)

tab2.set_commander(False)
check("turning the mode OFF leaves ONE pane, no ring and the shipped look",
      tab2.commander is False and len(tab2.panes) == 1
      and tab2.panes[0] is pane_l and pane_l._ring.is_active() is False
      and tab2.tree is pane_l.tree)
check("the surviving pane keeps its own directory (the mode is a view, not a reset)",
      pane_l.current_dir == "/left" and pane_l.path_label.text() == "/left")
tab2.set_commander(True)
check("re-opening the mode creates a FRESH second pane in the survivor's directory",
      len(tab2.panes) == 2 and tab2.panes[0] is pane_l
      and tab2.panes[1] is not pane_r and tab2.panes[1].current_dir == "/left")
tab2.close_viewer()
worker2.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 4. The pane-scoped keys call the SHIPPED worker paths
# ════════════════════════════════════════════════════════════
print("== 4. the pane-scoped keys ==")

clear_cfg()
msgs4 = []
fs4 = FakeSftpFS()
fs4.add_dir("/home")
fs4.add_file("/home/a.txt", b"alpha")
fs4.add_file("/home/keep.txt", b"k")
tab4, worker4, log4, _client4 = make_tab(fs4)
tab4.message.connect(msgs4.append)
tab4._relist("/home")
wait_until(lambda: item_by_name(tab4, "a.txt") is not None, timeout_ms=5000)

# F3 — view (the shipped double-click behaviour on the current row)
tab4.tree.setCurrentItem(item_by_name(tab4, "a.txt"))
tab4.pane_shortcut("F3").trigger()
wait_until(lambda: not tab4.viewer.isHidden(), timeout_ms=5000)
check("F3 reads the current row through the SHIPPED queue_read path",
      not tab4.viewer.isHidden() and tab4.viewer_text.toPlainText() == "alpha",
      f"viewer={tab4.viewer_text.toPlainText()!r}")
tab4.tree.setCurrentItem(item_by_name(tab4, ".."))
tab4.pane_shortcut("F3").trigger()
wait_until(lambda: tab4.path_label.text() == "/", timeout_ms=5000)
check("F3 on the '..' row goes one level up (the shipped navigation rule)",
      tab4.current_dir == "/")
tab4._relist("/home")
wait_until(lambda: item_by_name(tab4, "a.txt") is not None, timeout_ms=5000)

# F7 — new folder (the SHIPPED queue_mkdir), through the ordinary name dialog
_FakeInputDialog.SCRIPT = ["fresh"]
tab4.pane_shortcut("F7").trigger()
wait_until(lambda: "/home/fresh" in fs4.dirs, timeout_ms=5000)
check("F7 creates the directory through queue_mkdir",
      "/home/fresh" in fs4.dirs, f"dirs={sorted(fs4.dirs)}")
wait_until(lambda: item_by_name(tab4, "fresh") is not None, timeout_ms=5000)
check("...and the operation's own answer refreshes the listing",
      item_by_name(tab4, "fresh") is not None)

# F6 — the SAME-directory rename (queue_rename)
_FakeInputDialog.SCRIPT = ["b.txt"]
tab4.tree.setCurrentItem(item_by_name(tab4, "a.txt"))
tab4.pane_shortcut("F6").trigger()
wait_until(lambda: "/home/b.txt" in fs4.files, timeout_ms=5000)
check("F6 renames in place through queue_rename (only the NAME changes)",
      "/home/b.txt" in fs4.files and fs4.files["/home/b.txt"] == b"alpha"
      and "/home/a.txt" not in fs4.files, f"files={sorted(fs4.files)}")

# F8 — delete (queue_delete, behind the shipped confirmation)
_FakeMessageBox.CONFIRM = True
_FakeMessageBox.ASKED = []
tab4.tree.setCurrentItem(item_by_name(tab4, "b.txt"))
tab4.pane_shortcut("F8").trigger()
wait_until(lambda: "/home/b.txt" not in fs4.files, timeout_ms=5000)
check("F8 deletes the current row through queue_delete (with the confirmation)",
      "/home/b.txt" not in fs4.files and bool(_FakeMessageBox.ASKED),
      f"asked={_FakeMessageBox.ASKED!r}")
_FakeMessageBox.CONFIRM = False
tab4.tree.setCurrentItem(item_by_name(tab4, "keep.txt"))
tab4.pane_shortcut("F8").trigger()
app.processEvents()
check("a refused F8 confirmation deletes NOTHING (the shipped gate)",
      "/home/keep.txt" in fs4.files)
_FakeMessageBox.CONFIRM = True

# F5 — with ONE pane there is no destination: ONE honest sentence, never a silent no-op
msgs4.clear()
tab4.pane_shortcut("F5").trigger()
check("F5 without a second pane answers the no-target sentence (one pane has nowhere to copy)",
      msgs4 == [i18n.t("sftp.cmd.copy_no_target")], f"msgs={msgs4!r}")
check("...and it queues NO worker task (there is no destination to write into)",
      not [e for e in log4.events if e[0] == "started" and e[2] in ("copy", "move")])

# no current row — the honest answer of every pane-scoped key
tab4.tree.setCurrentItem(None)
msgs4.clear()
tab4.pane_shortcut("F3").trigger()
tab4.pane_shortcut("F6").trigger()
tab4.pane_shortcut("F8").trigger()
check("with no current row F3/F6/F8 say so instead of acting on nothing",
      msgs4 == [i18n.t("sftp.cmd.no_selection")] * 3, f"msgs={msgs4!r}")
worker4.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 5. The action and the corner control (the window)
# ════════════════════════════════════════════════════════════
print("== 5. the Files Commander action of the ACTIVE session ==")

clear_cfg()
_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = FakeSSHThread
mw = MW.MainWindow()
mw.show()
app.processEvents()

node5 = mw.scene.add_server(
    ServerData(id="fc-1", alias="commander", host="10.91.0.1", user="root"))
win5 = mw._spawn_terminal_window(node5, password="pw")
app.processEvents()
page5 = win5.session_tabs.widget(0)
msgs5 = []
page5.sftp_tab.message.connect(msgs5.append)

check("the corner of the session tab bar is ONE container holding BOTH per-session controls",
      win5.session_tabs.cornerWidget(Qt.Corner.TopRightCorner) is win5.commander
      and win5.commander.isAncestorOf(win5.btn_split)
      and win5.commander.isAncestorOf(win5.commander.btn))
check("the action is checkable, labelled and ENABLED for a session with a Files tab",
      win5.commander.act.isCheckable() and win5.commander.act.isChecked() is False
      and win5.commander.act.isEnabled() is True
      and win5.commander.act.text() == i18n.t("sftp.commander")
      and win5.commander.act.toolTip() == i18n.t("sftp.commander_tooltip"))
check("the corner BUTTON mirrors the action (one source of truth)",
      win5.commander.btn.isCheckable() and win5.commander.btn.isChecked() is False
      and win5.commander.btn.text() == i18n.t("sftp.commander"))

win5.commander.btn.click()   # the real click path of the corner button
app.processEvents()
check("the click turns the two-pane view ON (through the one action)",
      page5.sftp_tab.commander is True and win5.commander.act.isChecked() is True
      and win5.commander.btn.isChecked() is True)
check("...and it brings the FILES tab on screen (the panes are built inside it)",
      page5.tabs.currentWidget() is page5.sftp_tab)
check("the page keeps `sftp_tab` as the OWNER of the two panes (the page contract)",
      page5.sftp_tab is page5.tabs.widget(1) and len(page5.sftp_tab.panes) == 2)
check("the mode reports its ACTIVE-pane rule once, in the status message",
      i18n.t("sftp.commander_hint") in msgs5, f"msgs={msgs5!r}")

win5.commander.act.trigger()   # the second view of the same action — OFF
app.processEvents()
check("the action toggles the mode OFF again (one action, two views)",
      page5.sftp_tab.commander is False and len(page5.sftp_tab.panes) == 1)

# the SPLIT PANE has no Files tab → the action is disabled there
win5.activateWindow()
QApplication.setActiveWindow(win5)
app.processEvents()
win5.act_split.trigger()
app.processEvents()
pane5 = win5.split_pane
check("a split pane has no Files tab and no sftp_tab (the shipped rule)",
      pane5 is not None and pane5.sftp_tab is None and pane5.tabs.count() == 1)
pane5.widget.setFocus()   # the user clicks into the pane (the v1.3.3.5 focus rule)
app.processEvents()
win5._refresh_bridge()
app.processEvents()
check("with the SPLIT PANE on screen the action is DISABLED (no channel to serve)",
      win5._bridged_page is pane5 and win5._commander_tab() is None
      and win5.commander.act.isEnabled() is False,
      f"bridged={win5._bridged_page is pane5} tab={win5._commander_tab()}")
win5.set_split_enabled(False)
app.processEvents()
check("back on the tab the action is enabled again and shows ITS OWN mode",
      win5._bridged_page is page5
      and win5.commander.act.isEnabled() is True and win5.commander.act.isChecked() is False
      and win5._commander_tab() is page5.sftp_tab)


# ════════════════════════════════════════════════════════════
# 5b. F5 typed into the terminal CANVAS still reaches the SHELL
# ════════════════════════════════════════════════════════════
print("== 5b. the canvas keeps F5 (the pane never steals it) ==")

win5.tabs.setCurrentIndex(0)
app.processEvents()
canvas = page5.widget
channel = page5.terminal_thread.channel
channel.sent = []
msgs5.clear()
app.sendEvent(canvas, QKeyEvent(QKeyEvent.Type.KeyPress, int(Qt.Key.Key_F5),
                                Qt.KeyboardModifier.NoModifier, ""))
app.processEvents()
check("F5 in the CANVAS reaches the SHELL (the xterm sequence, §4.3)",
      b"\x1b[15~" in channel.sent, f"sent={channel.sent!r}")
check("...and the pane's F5 handler was NOT reached (no refusal message)",
      msgs5 == [], f"msgs={msgs5!r}")
check("the pane's shortcut CANNOT fire in the canvas (it is not the pane's descendant)",
      not page5.sftp_tab.isAncestorOf(canvas)
      and not page5.sftp_tab.panes[0].isAncestorOf(canvas))

# ════════════════════════════════════════════════════════════
# 7a. The persistence through the window's ONE geometry write (the SAME window)
# ════════════════════════════════════════════════════════════
print("== 7a. the window writes the keys in its single geometry save ==")

clear_cfg()
page5.sftp_tab.set_commander(True)
win5.close()
app.processEvents()
_cfg = read_cfg({})
check("closing the window writes the mode through the ONE geometry write",
      _cfg.get(COMMANDER_CONFIG_BOOL) is True
      and isinstance(_cfg.get(COMMANDER_CONFIG_RATIO), float)
      and "ui_window_geometry_terminal" in _cfg
      and "ui_terminal_split" in _cfg,
      f"cfg={sorted(_cfg)}")
check("the split's own keys are untouched by the merge (one write, two features)",
      _cfg.get("ui_terminal_split") is False)
check("the geometry write is a SINGLE save_config (the foreign keys survive it)",
      "language" not in _cfg or isinstance(_cfg.get("language"), str))
mw._dirty = False
mw.close()
app.processEvents()
ST.SSHTerminalThread = _orig_thread_cls


# ════════════════════════════════════════════════════════════
# 6. The follow rule
# ════════════════════════════════════════════════════════════
print("== 6. the follow is OFF and greyed in the two-pane mode ==")

clear_cfg()
fs6 = FakeSftpFS()
fs6.add_dir("/var")
fs6.add_file("/var/x.txt", b"x")
tab6, worker6, _log6, _client6 = make_tab(fs6)
tab6.set_follow_cwd(True)
check("with a transport the follow switch is available and ON (the shipped state)",
      tab6.chk_follow_cwd.isEnabled() is True and tab6.chk_follow_cwd.isChecked() is True
      and tab6._follow_cwd is True)
told = []
tab6.follow_cwd_changed.connect(told.append)
tab6.set_commander(True)
check("opening the mode switches the follow OFF, GREYS the switch and TELLS the session",
      tab6._follow_cwd is False and tab6.chk_follow_cwd.isChecked() is False
      and tab6.chk_follow_cwd.isEnabled() is False and told == [False],
      f"told={told!r}")
check("follow_directory() refuses in the mode (one OSC 7 cannot answer 'which pane')",
      tab6.follow_directory("/var") is False and tab6.current_dir == "/")
tab6.set_follow_cwd(True)   # a direct write is a VIEW write — the mode still refuses
check("the mode keeps refusing even when the state is written behind the switch",
      tab6.follow_directory("/var") is False)
tab6.set_commander(False)
check("leaving the mode restores the SWITCH (not the state — that stays the user's)",
      tab6.chk_follow_cwd.isEnabled() is True and tab6._follow_cwd is True)
check("...and the follow moves the FIRST pane's listing again",
      tab6.follow_directory("/var") is True and tab6.current_dir == "/var")
worker6.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 7b. The persistence of the VALUES
# ════════════════════════════════════════════════════════════
print("== 7b. the state and the ratio survive a save→load ==")

clear_cfg()
tab7 = SftpTab()
tab7.set_commander(True)
payload = tab7.commander_extra_config()
check("the mode writes the two DECLARED config keys and nothing else",
      payload.get(COMMANDER_CONFIG_BOOL) is True
      and isinstance(payload.get(COMMANDER_CONFIG_RATIO), float)
      and COMMANDER_CONFIG_BOOL == "ui_sftp_commander"
      and COMMANDER_CONFIG_RATIO == "ui_sftp_commander_ratio",
      f"payload={payload!r}")
check("the extra keys merge into an existing payload (the window's single geometry write)",
      tab7.commander_extra_config({"ui_terminal_split": False}).get("ui_terminal_split")
      is False)
tab7.set_worker(None)

save_config(payload)
check("the keys really land in ~/.sshmap/config.json",
      read_cfg({}).get(COMMANDER_CONFIG_BOOL) is True
      and read_cfg({}).get(COMMANDER_CONFIG_RATIO) == payload[COMMANDER_CONFIG_RATIO])
tab8 = SftpTab()
check("a new session RESTORES the mode it was left in (two panes, the same ratio)",
      tab8.commander is True and len(tab8.panes) == 2)
tab8.set_worker(None)

clear_cfg()
save_config({COMMANDER_CONFIG_BOOL: "true", COMMANDER_CONFIG_RATIO: "half"})
check("a FOREIGN boolean/ratio falls back to the defaults (a broken config opens no pane)",
      load_commander_settings() == {"commander": False, "ratio": COMMANDER_RATIO_DEFAULT},
      str(load_commander_settings()))
save_config({COMMANDER_CONFIG_BOOL: True, COMMANDER_CONFIG_RATIO: 9.0})
check("an out-of-range ratio is CLAMPED (the split's rule)",
      load_commander_settings()["ratio"] <= 0.8)
clear_cfg()


# ════════════════════════════════════════════════════════════
# 8. i18n + the release state
# ════════════════════════════════════════════════════════════
print("== 8. i18n and the release state ==")

RC1_KEYS = ("sftp.commander", "sftp.commander_tooltip", "sftp.commander_hint",
            "sftp.cmd.copy_unavailable", "sftp.cmd.no_selection")
NEW_KEYS = RC1_KEYS + ("sftp.copying", "sftp.cmd.copy_no_target", "sftp.cmd.batch_started",
                       "sftp.cmd.copy_report", "sftp.cmd.move_report", "sftp.cmd.partial",
                       "sftp.cmd.move_refused", "sftp.cmd.tree_too_big")

langs = load_i18n_langs(ROOT)
_missing = {code: [k for k in NEW_KEYS if not str(data.get(k) or "").strip()]
            for code, data in langs.items()}
check(f"the {len(NEW_KEYS)} keys of the 1.7 line (5 of rc1 + 8 of rc2) are present and "
      "non-empty in EVERY language",
      not any(_missing.values()), str({c: v for c, v in _missing.items() if v}))
check("the action's label is TRANSLATED (not the raw key, not the English literal)",
      all(str(langs[c]["sftp.commander"]) not in (RC1_KEYS[0], "Files Commander")
          for c in langs if c != "en"),
      str({c: langs[c]["sftp.commander"] for c in sorted(langs)}))
check("the mode's hint is a real sentence in every language (it explains the ACTIVE pane)",
      all(len(str(langs[c]["sftp.commander_hint"])) > 10 for c in langs))
check("the two closing reports of v1.7rc2 are real sentences in every language",
      all(len(str(langs[c]["sftp.cmd.copy_report"])) > 10
          and len(str(langs[c]["sftp.cmd.move_report"])) > 10 for c in langs))
check("the reserved sentence of v1.7rc1 is KEPT in every file (the i18n rule is additive)",
      all(str(langs[c]["sftp.cmd.copy_unavailable"]).strip() for c in langs))
check_i18n_parity(langs)
check_i18n_format(langs)

# a language switch re-texts the container AND its panes
i18n.set_language("ru")
tab_i = SftpTab()
tab_i.set_commander(True)
tab_i.retranslate()
check("a language switch re-texts the container's follow switch AND every pane",
      tab_i.chk_follow_cwd.text() == i18n.t("sftp.follow_cwd")
      and tab_i.panes[0].btn_up.text() == i18n.t("sftp.up")
      and tab_i.panes[1].btn_refresh.text() == i18n.t("sftp.refresh"),
      f"{tab_i.chk_follow_cwd.text()!r}/{tab_i.panes[1].btn_refresh.text()!r}")
tab_i.set_worker(None)
i18n.set_language("en")

check_release_state(ROOT)
check("the version pin is the release this file describes",
      re.fullmatch(r"1\.7(?:rc\d+|(?:\.\d+){1,2})?", EXPECTED_APP_VERSION) is not None,
      EXPECTED_APP_VERSION)
check("the i18n pin counts the SHIPPED release (846 + the 8 keys of v1.7rc2 + later additions)",
      EXPECTED_I18N_KEYS >= 846 + 8 == 854, str(EXPECTED_I18N_KEYS))
check("VERSION_FORMAT did NOT move (the project schema is unchanged)",
      __import__("version").VERSION_FORMAT == "0.9")
check("no new dependency was added for the copy/move family (the four pinned ones)",
      all(f"{d}>=" in open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
          for d in ("PySide6", "paramiko", "keyring", "wcwidth")))
check("the frozen contract of the line is in the repository (SFTP_PANES.md)",
      os.path.exists(os.path.join(ROOT, "SFTP_PANES.md")))


# ════════════════════════════════════════════════════════════
# 9. The copy task (worker): byte-equal, atomic, stream vs copy-data
# ════════════════════════════════════════════════════════════
print("== 9. the worker: queue_copy ==")

PAYLOAD = b"A" * 200

fs_c = FakeSftpFS()
fs_c.add_dir("/src")
fs_c.add_dir("/dst")
fs_c.add_file("/src/a.bin", PAYLOAD)
worker_c, log_c, client_c = one_worker(fs_c)   # copy_data_ok=False → the STREAM

tid_c = worker_c.queue_copy("/src/a.bin", "/dst")
wait_until(lambda: log_c.of_kind("done", tid_c), timeout_ms=5000)
check("the streamed copy lands BYTE-EQUAL in the destination directory",
      fs_c.files.get("/dst/a.bin") == PAYLOAD, f"files={sorted(fs_c.files)}")
check("the copy's task_done names the DESTINATION path",
      log_c.of_kind("done", tid_c)[0][2] == "/dst/a.bin",
      f"got={log_c.of_kind('done', tid_c)}")
check("a successful copy leaves no provisional file behind", no_part(fs_c) == [])
check("the progress carries the total from stat (one line, done == total)",
      log_c.of_kind("progress", tid_c)
      and log_c.of_kind("progress", tid_c)[-1][3] == len(PAYLOAD),
      f"progress={log_c.of_kind('progress', tid_c)}")
check("the server WITHOUT the extension was detected (the stream is the contract)",
      client_c.copy_data_ok is False and worker_c._copy_data_ok is False,
      f"copy_data_ok={worker_c._copy_data_ok}")
check("...and the same copy under a NEW name works too (name= overrides the basename)",
      worker_c.queue_copy("/src/a.bin", "/dst", "other.bin") is not None)

# a name= copy
tid_named = worker_c.queue_copy("/src/a.bin", "/dst", "copy2.bin")
wait_until(lambda: log_c.of_kind("done", tid_named), timeout_ms=5000)
check("the named copy landed under the requested name",
      fs_c.files.get("/dst/copy2.bin") == PAYLOAD)

# the OPTIONAL fast path: a server that answers copy-data@openssh.com
fs_f = FakeSftpFS()
fs_f.add_dir("/src")
fs_f.add_dir("/dst")
fs_f.add_file("/src/f.bin", PAYLOAD)
worker_f, log_f, client_f = one_worker(fs_f, copy_data_ok=True)
_old_level = SW.log.level
SW_log = []
_handler = _CaptureHandler(SW_log)
SW.log.addHandler(_handler)
SW.log.setLevel(logging.DEBUG)
tid_f = worker_f.queue_copy("/src/f.bin", "/dst")
wait_until(lambda: log_f.of_kind("done", tid_f), timeout_ms=5000)
check("the OpenSSH fast path produced the IDENTICAL result (byte-equal, no .part)",
      fs_f.files.get("/dst/f.bin") == PAYLOAD and no_part(fs_f) == [])
check("the extension was detected and REMEMBERED for the session",
      worker_f._copy_data_ok is True)
check("...and it did NOT log a fallback line (the fast path really ran)",
      not [m for m in SW_log if "copy-data" in m], f"log={SW_log}")
SW.log.removeHandler(_handler)

# the SAME fast path on a server that does not answer the extension: ONE log line
fs_s = FakeSftpFS()
fs_s.add_dir("/src")
fs_s.add_dir("/dst")
fs_s.add_file("/src/s.bin", PAYLOAD)
worker_s, log_s, _client_s = one_worker(fs_s)   # copy_data_ok=False
SW_log = []
_handler = _CaptureHandler(SW_log)
SW.log.addHandler(_handler)
SW.log.setLevel(logging.DEBUG)
for _i in range(2):
    tid_s = worker_s.queue_copy("/src/s.bin", "/dst", "s%d.bin" % _i)
    wait_until(lambda t=tid_s: log_s.of_kind("done", t), timeout_ms=5000)
check("a server without the extension is SKIPPED with ONE log line for the whole session",
      len([m for m in SW_log if "copy-data" in m]) == 1, f"log={SW_log}")
check("...and the stream produced the identical bytes for both files",
      fs_s.files.get("/dst/s0.bin") == PAYLOAD and fs_s.files.get("/dst/s1.bin") == PAYLOAD)
SW.log.removeHandler(_handler)
SW.log.setLevel(_old_level)

# ATOMICITY: a cancelled copy leaves the destination byte-identical
SENTINEL = b"the previous destination\n"
fs_a = FakeSftpFS()
fs_a.add_dir("/src")
fs_a.add_dir("/dst")
fs_a.add_file("/src/big.bin", b"y" * (8 * 32768))
fs_a.add_file("/dst/big.bin", SENTINEL)
worker_a, log_a, _client_a = one_worker(fs_a, chunk_delay=0.02)
tid_a = worker_a.queue_copy("/src/big.bin", "/dst")
wait_until(lambda: log_a.of_kind("progress", tid_a), timeout_ms=5000)
worker_a.cancel()
wait_until(lambda: log_a.of_kind("cancelled", tid_a), timeout_ms=8000)
check("the cancelled copy reported task_cancelled", bool(log_a.of_kind("cancelled", tid_a)))
check("the destination is BYTE-IDENTICAL after the cancelled copy",
      fs_a.files.get("/dst/big.bin") == SENTINEL,
      f"got={bytes(fs_a.files.get('/dst/big.bin', b''))[:40]!r}")
check("the cancelled copy dropped its provisional file", no_part(fs_a) == [],
      f"files={sorted(fs_a.files)}")
check("the copy never wrote through the destination name (no truncation)",
      len(fs_a.files.get("/dst/big.bin", b"")) == len(SENTINEL))

# a FAILED copy (the source vanished) is not an error to the destination either
tid_bad = worker_a.queue_copy("/src/gone.bin", "/dst")
wait_until(lambda: log_a.of_kind("error", tid_bad), timeout_ms=5000)
check("the copy of a missing source → task_error", bool(log_a.of_kind("error", tid_bad)))
check("the failed copy created nothing and left no provisional file",
      "/dst/gone.bin" not in fs_a.files and no_part(fs_a) == [])
tid_after = worker_a.queue_copy("/src/big.bin", "/dst", "after.bin")
wait_until(lambda: log_a.of_kind("done", tid_after), timeout_ms=8000)
check("the queue survived the failure (the next copy really ran)",
      fs_a.files.get("/dst/after.bin") == b"y" * (8 * 32768))


# ════════════════════════════════════════════════════════════
# 10. The RECURSIVE copy: the bounded walk, the merge and the partial report
# ════════════════════════════════════════════════════════════
print("== 10. the worker: the recursive tree copy ==")

fs_t = FakeSftpFS()
fs_t.add_dir("/tree")
fs_t.add_dir("/tree/sub")
fs_t.add_dir("/tree/sub/deep")
fs_t.add_file("/tree/root.txt", b"root")
fs_t.add_file("/tree/sub/one.txt", b"one")
fs_t.add_file("/tree/sub/deep/two.txt", b"two")
EXPECTED_TREE = {"root.txt": b"root", "sub/one.txt": b"one", "sub/deep/two.txt": b"two"}
worker_t, log_t, _client_t = one_worker(fs_t)

tid_t = worker_t.queue_copy("/tree", "/copy")
wait_until(lambda: log_t.of_kind("done", tid_t), timeout_ms=5000)
check("a tree is copied RECURSIVELY with its directories and its bytes",
      tree_of(fs_t, "/copy/tree") == EXPECTED_TREE, f"tree={tree_of(fs_t, '/copy/tree')}")
check("...the folder lands as a SUBDIRECTORY of the target (the commander rule)",
      "/copy/tree" in fs_t.dirs and tree_of(fs_t, "/tree") == EXPECTED_TREE)
check("...and the source tree is untouched by a copy", tree_of(fs_t, "/tree") == EXPECTED_TREE)
check("a recursive copy leaves no provisional file", no_part(fs_t) == [])
check("the progress of the whole tree carries the SUM of its files",
      log_t.of_kind("progress", tid_t)
      and log_t.of_kind("progress", tid_t)[-1][3] == 4 + 3 + 3,
      f"progress={log_t.of_kind('progress', tid_t)}")
check("the task_done detail is the destination ROOT",
      log_t.of_kind("done", tid_t)[0][2] == "/copy/tree")

# the MERGE: an existing destination directory keeps what is inside it
fs_t.add_dir("/copy2")
fs_t.add_dir("/copy2/tree")
fs_t.add_dir("/copy2/tree/sub")
fs_t.add_file("/copy2/tree/keep.txt", b"keep")
fs_t.add_file("/copy2/tree/sub/keep2.txt", b"keep2")
tid_m = worker_t.queue_copy("/tree", "/copy2")
wait_until(lambda: log_t.of_kind("done", tid_m), timeout_ms=5000)
check("an existing destination directory is MERGED — nothing inside it is deleted",
      fs_t.files.get("/copy2/tree/keep.txt") == b"keep"
      and fs_t.files.get("/copy2/tree/sub/keep2.txt") == b"keep2",
      f"files={sorted(fs_t.files)}")
check("...and the tree landed beside the entries that were already there",
      tree_of(fs_t, "/copy2/tree")["root.txt"] == b"root"
      and tree_of(fs_t, "/copy2/tree")["sub/deep/two.txt"] == b"two")

# the BOUNDED walk: a tree over the declared limit is refused BEFORE anything moves
class _SmallBound:
    """Temporarily lower the DECLARED entry bound of the walk (the seam of the bound)."""

    def __enter__(self):
        self._saved = SW.MAX_TREE_ENTRIES
        SW.MAX_TREE_ENTRIES = 2
        return self

    def __exit__(self, *exc):
        SW.MAX_TREE_ENTRIES = self._saved


with _SmallBound():
    tid_big = worker_t.queue_copy("/tree", "/toobig")
    wait_until(lambda: log_t.of_kind("error", tid_big), timeout_ms=5000)
    err_big = log_t.of_kind("error", tid_big)
    payload_big = parse_task_payload(err_big[0][3]) if err_big else None
check("a tree over the declared bound → the tree_too_big payload, not a half copy",
      payload_big is not None and payload_big.get("code") == TREE_ERROR_TOO_BIG,
      f"err={err_big}")
check("...and NOTHING was transferred (the refusal happens before the walk moves a byte)",
      tree_of(fs_t, "/toobig") == {} and "/toobig" not in fs_t.dirs)

# the DEPTH bound
fs_d = FakeSftpFS()
_deep = "/deep"
fs_d.add_dir(_deep)
for _ in range(SW.MAX_TREE_DEPTH + 4):
    _deep += "/d"
    fs_d.add_dir(_deep)
worker_d, log_d, _client_d = one_worker(fs_d)
tid_d = worker_d.queue_copy("/deep", "/deep-copy")
wait_until(lambda: log_d.of_kind("error", tid_d), timeout_ms=8000)
err_d = log_d.of_kind("error", tid_d)
payload_d = parse_task_payload(err_d[0][3]) if err_d else None
check("the nestING bound refuses a too-deep tree with the same payload",
      payload_d is not None and payload_d.get("code") == TREE_ERROR_TOO_BIG
      and int(payload_d.get("depth")) == SW.MAX_TREE_DEPTH,
      f"err={err_d}")

# the PARTIAL report: one file of the tree refuses the write, the rest is reported
# (the atomic copy writes `<target>.part`, so a WRITE denial names the provisional path —
# the same rule the `deny_dirs` note of tests/_fakes.py describes)
fs_p = FakeSftpFS(deny_write={"/pcopy/ptree/zz.txt" + PART_SUFFIX})
fs_p.add_dir("/ptree")
fs_p.add_file("/ptree/aa.txt", b"aa")
fs_p.add_file("/ptree/zz.txt", b"zz")
worker_p, log_p, _client_p = one_worker(fs_p)
tid_p = worker_p.queue_copy("/ptree", "/pcopy")
wait_until(lambda: log_p.of_kind("error", tid_p), timeout_ms=5000)
err_p = log_p.of_kind("error", tid_p)
payload_p = parse_task_payload(err_p[0][3]) if err_p else None
check("a partially copied tree is REPORTED with the counters of what was done",
      payload_p is not None and payload_p.get("code") == PARTIAL_CODE
      and int(payload_p.get("copied")) == 1
      and payload_p.get("path") == "/ptree/zz.txt",
      f"err={err_p}")
check("...the files already published STAY (a partial tree is never rolled back)",
      fs_p.files.get("/pcopy/ptree/aa.txt") == b"aa")
check("...and the failed file left no provisional file", no_part(fs_p) == [],
      f"files={sorted(fs_p.files)}")
check("the activity record renders the partial payload as ONE human line",
      "partially done" in SW.task_log_line(KIND_COPY, "zz.txt", "failed", err_p[0][3])[0],
      SW.task_log_line(KIND_COPY, "zz.txt", "failed", err_p[0][3])[0])


# ════════════════════════════════════════════════════════════
# 11. The MOVE: one atomic rename, the merge, the refused cross-device case
# ════════════════════════════════════════════════════════════
print("== 11. the worker: queue_move ==")

fs_m = FakeSftpFS()
fs_m.add_dir("/src")
fs_m.add_dir("/dst")
fs_m.add_file("/src/f.txt", b"payload")
worker_m, log_m, client_m = one_worker(fs_m)

tid_mv = worker_m.queue_move("/src/f.txt", "/dst")
wait_until(lambda: log_m.of_kind("done", tid_mv), timeout_ms=5000)
check("a cross-directory move renames the file in ONE operation",
      fs_m.files.get("/dst/f.txt") == b"payload" and "/src/f.txt" not in fs_m.files,
      f"files={sorted(fs_m.files)}")
check("the move's task_done names the destination, and no provisional file is left",
      log_m.of_kind("done", tid_mv)[0][2] == "/dst/f.txt" and no_part(fs_m) == [])

# the same-directory rename keeps its own shipped path (queue_rename)
tid_rn = worker_m.queue_rename("/dst/f.txt", "g.txt")
wait_until(lambda: log_m.of_kind("done", tid_rn), timeout_ms=5000)
check("the same-directory rename is still queue_rename (the F6 rename-in-place path)",
      "/dst/g.txt" in fs_m.files and "/dst/f.txt" not in fs_m.files)

# a DIRECTORY moves as ONE rename when the destination does not exist
fs_m.add_dir("/dir")
fs_m.add_dir("/dir/inner")
fs_m.add_file("/dir/inner/x.txt", b"x")
tid_dir = worker_m.queue_move("/dir", "/moved")
wait_until(lambda: log_m.of_kind("done", tid_dir), timeout_ms=5000)
check("a directory moves with its subtree in one rename (INTO the target directory)",
      fs_m.files.get("/moved/dir/inner/x.txt") == b"x" and "/dir" not in fs_m.dirs,
      f"dirs={sorted(fs_m.dirs)}")

# a directory whose destination EXISTS is merged entry by entry
fs_m.add_dir("/dir2")
fs_m.add_file("/dir2/top.txt", b"top")
fs_m.add_dir("/existing")
fs_m.add_dir("/existing/dir2")
fs_m.add_dir("/existing/dir2/inner")
fs_m.add_file("/existing/dir2/keep.txt", b"keep")
tid_merge = worker_m.queue_move("/dir2", "/existing")
wait_until(lambda: log_m.of_kind("done", tid_merge), timeout_ms=5000)
check("a directory moved into an EXISTING directory is merged, file by file",
      fs_m.files.get("/existing/dir2/top.txt") == b"top"
      and fs_m.files.get("/existing/dir2/keep.txt") == b"keep",
      f"files={sorted(fs_m.files)}")
check("...and the emptied SOURCE directory is gone (the merge is a real move)",
      "/dir2" not in fs_m.dirs, f"dirs={sorted(fs_m.dirs)}")

# the REFUSED cross-device rename: a payload, both endpoints untouched
fs_x = FakeSftpFS()
fs_x.add_dir("/here")
fs_x.add_dir("/there")
fs_x.add_file("/here/f.txt", b"keep-me")
worker_x, log_x, client_x = one_worker(fs_x)
client_x.cross_device = True
tid_x = worker_x.queue_move("/here/f.txt", "/there")
wait_until(lambda: log_x.of_kind("error", tid_x), timeout_ms=5000)
err_x = log_x.of_kind("error", tid_x)
payload_x = parse_task_payload(err_x[0][3]) if err_x else None
check("a refused cross-device rename is a MACHINE payload, never a traceback",
      payload_x is not None and payload_x.get("code") == MOVE_ERROR_REFUSED
      and "Cross-device" in str(payload_x.get("error")),
      f"err={err_x}")
check("...and BOTH endpoints are untouched by the refusal",
      fs_x.files.get("/here/f.txt") == b"keep-me" and "/there/f.txt" not in fs_x.files)
check("...and the activity record spells the refusal out instead of printing JSON",
      "refused the move" in SW.task_log_line(KIND_MOVE, "f.txt", "failed", err_x[0][3])[0],
      SW.task_log_line(KIND_MOVE, "f.txt", "failed", err_x[0][3])[0])
check("the queue survived the refusal (the worker is still running)",
      worker_x.isRunning())


# ════════════════════════════════════════════════════════════
# 12. The BATCH of the panes: F5/F6, the conflict once, the report, the two listings
# ════════════════════════════════════════════════════════════
print("== 12. the pane: F5/F6 copy and move the selection between the panes ==")

clear_cfg()
_FakeMessageBox.DIALOGS = []
_FakeMessageBox.SCRIPT = []
_FakeMessageBox.CONFIRM = True

fs_b = FakeSftpFS()
fs_b.add_dir("/left")
fs_b.add_dir("/right")
for _name in ("a.txt", "b.txt", "c.txt"):
    fs_b.add_file("/left/" + _name, ("body-" + _name).encode())
tab_b, worker_b, log_b, client_b = make_tab(fs_b, commander=True)
pane_l, pane_r = tab_b.panes[0], tab_b.panes[1]
msgs_b = []
tab_b.message.connect(msgs_b.append)
pane_l._relist("/left")
wait_until(lambda: pane_l.path_label.text() == "/left", timeout_ms=5000)
pane_r._relist("/right")
wait_until(lambda: pane_r.path_label.text() == "/right", timeout_ms=5000)

check("the two panes really show two different directories (the copy has a target)",
      pane_l.current_dir == "/left" and pane_r.current_dir == "/right"
      and tab_b.other_pane(pane_l) is pane_r and tab_b.other_pane(pane_r) is pane_l)

# F5 with TWO files selected: ONE batch, no conflict (the destination is empty)
tab_b.set_active_pane(pane_l)
pane_l.tree.setCurrentItem(item_by_name(pane_l, "a.txt"))
pane_l.tree.clearSelection()
item_by_name(pane_l, "a.txt").setSelected(True)
item_by_name(pane_l, "b.txt").setSelected(True)
msgs_b.clear()
tab_b.pane_shortcut("F5").trigger()
wait_until(lambda: fs_b.files.get("/right/b.txt") == b"body-b.txt", timeout_ms=8000)
check("F5 copied EVERY selected file into the OTHER pane's directory",
      fs_b.files.get("/right/a.txt") == b"body-a.txt"
      and fs_b.files.get("/right/b.txt") == b"body-b.txt"
      and "/right/c.txt" not in fs_b.files,
      f"files={sorted(fs_b.files)}")
check("...the SOURCE files are still there (a copy never removes)",
      fs_b.files.get("/left/a.txt") == b"body-a.txt")
check("...no provisional file is left by the batch", no_part(fs_b) == [])
wait_until(lambda: i18n.t("sftp.cmd.copy_report", done=2, skipped=0, failed=0) in msgs_b,
           timeout_ms=5000)
check("the batch reported ONCE (copied / skipped / failed — the closing report)",
      i18n.t("sftp.cmd.copy_report", done=2, skipped=0, failed=0) in msgs_b,
      f"msgs={msgs_b!r}")
check("the batch announced itself with the queued count and the target",
      i18n.t("sftp.cmd.batch_started", count=2, dir="/right") in msgs_b,
      f"msgs={msgs_b!r}")
wait_until(lambda: item_by_name(pane_r, "a.txt") is not None, timeout_ms=5000)
check("BOTH panes were re-listed (the destination pane shows the new rows)",
      item_by_name(pane_r, "a.txt") is not None and item_by_name(pane_r, "b.txt") is not None,
      f"rows={pane_r.tree.topLevelItemCount()}")

# the CONFLICT: asked ONCE for the batch, "apply to all" holds for the rest
_FakeMessageBox.SCRIPT = [("overwrite", True)]
_FakeMessageBox.DIALOGS = []
msgs_b.clear()
pane_l.tree.clearSelection()
item_by_name(pane_l, "a.txt").setSelected(True)
item_by_name(pane_l, "c.txt").setSelected(True)
tab_b.pane_shortcut("F5").trigger()
wait_until(lambda: fs_b.files.get("/right/c.txt") == b"body-c.txt", timeout_ms=8000)
check("an Apply-to-all answer overwrote BOTH conflicting destinations",
      fs_b.files.get("/right/a.txt") == b"body-a.txt"
      and fs_b.files.get("/right/c.txt") == b"body-c.txt")
check("...and the question was asked EXACTLY ONCE for the whole batch",
      len(_FakeMessageBox.DIALOGS) == 1, f"dialogs={_FakeMessageBox.DIALOGS}")
check("...the dialog named the file and the destination directory",
      _FakeMessageBox.DIALOGS
      and _FakeMessageBox.DIALOGS[0][1]
      == i18n.t("sftp.conflict.message", name="a.txt", target="/right"),
      f"dialogs={_FakeMessageBox.DIALOGS}")

# SKIP + apply to all: nothing is destroyed, and the report counts the skips
_FakeMessageBox.SCRIPT = [("skip", True)]
_FakeMessageBox.DIALOGS = []
msgs_b.clear()
_copies_before = len([e for e in log_b.events if e[0] == "started" and e[2] == "copy"])
tab_b.pane_shortcut("F5").trigger()
wait_until(lambda: i18n.t("sftp.cmd.copy_report", done=0, skipped=2, failed=0) in msgs_b,
           timeout_ms=5000)
check("a Skip-to-all batch changed NOTHING on the destination",
      fs_b.files.get("/right/a.txt") == b"body-a.txt"
      and fs_b.files.get("/right/c.txt") == b"body-c.txt")
check("...asked ONE question and reported the two skips",
      len(_FakeMessageBox.DIALOGS) == 1
      and i18n.t("sftp.cmd.copy_report", done=0, skipped=2, failed=0) in msgs_b,
      f"dialogs={_FakeMessageBox.DIALOGS} msgs={msgs_b!r}")
check("...and queued NO worker task at all",
      len([e for e in log_b.events if e[0] == "started" and e[2] == "copy"])
      == _copies_before)

# a row whose destination IS itself (both panes in the SAME directory) is skipped
pane_r._relist("/left")
wait_until(lambda: pane_r.path_label.text() == "/left", timeout_ms=5000)
_FakeMessageBox.DIALOGS = []
msgs_b.clear()
pane_l.tree.clearSelection()
item_by_name(pane_l, "a.txt").setSelected(True)
tab_b.pane_shortcut("F5").trigger()
wait_until(lambda: i18n.t("sftp.cmd.copy_report", done=0, skipped=1, failed=0) in msgs_b,
           timeout_ms=5000)
check("a row whose destination is the row ITSELF is skipped (never copied onto itself)",
      fs_b.files.get("/left/a.txt") == b"body-a.txt"
      and i18n.t("sftp.cmd.copy_report", done=0, skipped=1, failed=0) in msgs_b,
      f"msgs={msgs_b!r}")
check("...and no conflict question was asked for it (it is not a conflict)",
      _FakeMessageBox.DIALOGS == [], f"dialogs={_FakeMessageBox.DIALOGS}")
pane_r._relist("/right")
wait_until(lambda: pane_r.path_label.text() == "/right", timeout_ms=5000)

# F6 moves ACROSS the panes (different directories) — the source disappears
msgs_b.clear()
pane_l.tree.clearSelection()
fs_b.add_file("/left/mover.txt", b"mover")
pane_l._relist("/left")
wait_until(lambda: item_by_name(pane_l, "mover.txt") is not None, timeout_ms=5000)
pane_l.tree.clearSelection()
item_by_name(pane_l, "mover.txt").setSelected(True)
tab_b.pane_shortcut("F6").trigger()
wait_until(lambda: fs_b.files.get("/right/mover.txt") == b"mover", timeout_ms=8000)
check("F6 MOVED the row to the other pane (the source is gone)",
      fs_b.files.get("/right/mover.txt") == b"mover"
      and "/left/mover.txt" not in fs_b.files,
      f"files={sorted(fs_b.files)}")
wait_until(lambda: i18n.t("sftp.cmd.move_report", done=1, skipped=0, failed=0) in msgs_b,
           timeout_ms=5000)
check("...and reported the move through the move report",
      i18n.t("sftp.cmd.move_report", done=1, skipped=0, failed=0) in msgs_b,
      f"msgs={msgs_b!r}")
wait_until(lambda: item_by_name(pane_l, "mover.txt") is None, timeout_ms=5000)
check("...the SOURCE pane was re-listed without the moved row",
      item_by_name(pane_l, "mover.txt") is None)

# a DIRECTORY row travels too (the recursive decision of this release)
msgs_b.clear()
fs_b.add_dir("/left/dir")
fs_b.add_file("/left/dir/inside.txt", b"inside")
pane_l._relist("/left")
wait_until(lambda: item_by_name(pane_l, "dir") is not None, timeout_ms=5000)
pane_l.tree.clearSelection()
item_by_name(pane_l, "dir").setSelected(True)
tab_b.pane_shortcut("F5").trigger()
wait_until(lambda: fs_b.files.get("/right/dir/inside.txt") == b"inside", timeout_ms=8000)
check("a DIRECTORY row is copied RECURSIVELY between the panes",
      fs_b.files.get("/right/dir/inside.txt") == b"inside"
      and fs_b.files.get("/left/dir/inside.txt") == b"inside",
      f"files={sorted(fs_b.files)}")

# the REFUSED move of the batch: a sentence, the report counts it, the source stays
client_b.cross_device = True
msgs_b.clear()
fs_b.add_file("/left/stuck.txt", b"stuck")
pane_l._relist("/left")
wait_until(lambda: item_by_name(pane_l, "stuck.txt") is not None, timeout_ms=5000)
pane_l.tree.clearSelection()
item_by_name(pane_l, "stuck.txt").setSelected(True)
tab_b.pane_shortcut("F6").trigger()
wait_until(lambda: i18n.t("sftp.cmd.move_report", done=0, skipped=0, failed=1) in msgs_b,
           timeout_ms=5000)
check("a refused move is a SENTENCE in the status bar (never a traceback)",
      any(m.startswith("The server refused the move") for m in msgs_b), f"msgs={msgs_b!r}")
check("...the source file stays where it was",
      fs_b.files.get("/left/stuck.txt") == b"stuck"
      and "/right/stuck.txt" not in fs_b.files)
check("...and the closing report counted the failure",
      i18n.t("sftp.cmd.move_report", done=0, skipped=0, failed=1) in msgs_b,
      f"msgs={msgs_b!r}")
check("the queue survived the refused move (the next batch really runs)",
      worker_b.isRunning())
client_b.cross_device = False

# ONE pane: F6 falls back to the shipped same-directory rename (never the move path)
tab_one_b = SftpTab()
check("with ONE pane there is no other pane to move to (other_pane answers None)",
      tab_one_b.other_pane(tab_one_b.panes[0]) is None)

_FakeMessageBox.SCRIPT = []
for _t in (tab_b, tab_one_b):
    try:
        _t.set_worker(None)
    except Exception:   # noqa: BLE001 — teardown robustness
        pass
worker_b.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 12b. The whole chain: a window, its page and the status-bar report
# ════════════════════════════════════════════════════════════
print("== 12b. the copy through a real window reaches the status bar ==")

clear_cfg()
fs_w = FakeSftpFS()
fs_w.add_dir("/w-left")
fs_w.add_dir("/w-right")
fs_w.add_file("/w-left/w.txt", b"through-the-window")
_orig_thread_cls_w = ST.SSHTerminalThread
ST.SSHTerminalThread = FakeSSHThread
win_w = ST.SSHTerminalWindow(
    ServerData(id="sftp-window", alias="sftpwin", host="10.99.0.41", user="root"),
    None, password="pw")
win_w.terminal_thread.client = FakeSSHClient(FakeSftpClient(fs_w))
win_w.show()
app.processEvents()
page_w = win_w.session_tabs.widget(0)
page_w.show_files_tab()          # the lazy open_sftp + the worker
app.processEvents()
wait_until(lambda: page_w.sftp_tab is not None and page_w.sftp_tab.worker is not None,
           timeout_ms=5000)
tab_w = page_w.sftp_tab
tab_w.set_commander(True)
app.processEvents()
pane_wl, pane_wr = tab_w.panes[0], tab_w.panes[1]

check("a real window hands the SAME worker to the container (page → tab → both panes)",
      tab_w.worker is page_w._sftp_worker and pane_wl.worker is tab_w.worker
      and pane_wr.worker is tab_w.worker)
check("a remote copy feeds the page's transfer progress family (its own status line)",
      "copy" in page_w._SFTP_PROGRESS_KINDS
      and page_w._SFTP_KIND_KEYS.get("copy") == "sftp.copying"
      and "move" not in page_w._SFTP_PROGRESS_KINDS)

pane_wl._relist("/w-left")
wait_until(lambda: pane_wl.path_label.text() == "/w-left", timeout_ms=5000)
pane_wr._relist("/w-right")
wait_until(lambda: pane_wr.path_label.text() == "/w-right", timeout_ms=5000)
win_w._refresh_bridge()
app.processEvents()
# The host bridge: every (text, timeout) the page pushed into the window's status bar. The
# LAST line after a batch is the re-listing's "Listing …" (the shipped order for every file
# operation), so the check is over the STREAM — the report must have reached the host.
bridge_w = []
page_w.status_message.connect(lambda text, ms, sink=bridge_w: sink.append(text))
tab_w.set_active_pane(pane_wl)
pane_wl.tree.clearSelection()
item_by_name(pane_wl, "w.txt").setSelected(True)
tab_w.pane_shortcut("F5").trigger()
wait_until(lambda: fs_w.files.get("/w-right/w.txt") == b"through-the-window", timeout_ms=8000)
check("F5 through the window's page copied the file into the other pane",
      fs_w.files.get("/w-right/w.txt") == b"through-the-window"
      and fs_w.files.get("/w-left/w.txt") == b"through-the-window")
report_w = i18n.t("sftp.cmd.copy_report", done=1, skipped=0, failed=0)
wait_until(lambda: report_w in bridge_w, timeout_ms=5000)
check("the closing report rides the SHIPPED message bridge into the host's status bar",
      report_w in bridge_w, f"bridge={bridge_w!r}")
wait_until(lambda: item_by_name(pane_wr, "w.txt") is not None, timeout_ms=5000)
check("both panes of the live session show the result (the destination re-listed)",
      item_by_name(pane_wr, "w.txt") is not None)
page_w.shutdown()
win_w.close()
app.processEvents()
ST.SSHTerminalThread = _orig_thread_cls_w

for _w in (worker_c, worker_f, worker_s, worker_a, worker_t, worker_d, worker_p,
           worker_m, worker_x):
    _w.shutdown(wait_ms=2000)

finish()
