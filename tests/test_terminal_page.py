# -*- coding: utf-8 -*-
"""v1.2 — TerminalSessionPage refactor (window → page) + per-session tracking.

The thematic test of the release v1.2 (ROADMAP v1.2, the "new thematic file" convention):

§1 The page construction: TerminalSessionPage — the session as a reusable
   widget (thread + screen + the terminal canvas + the SFTP tab; the status is data,
   not a row — the v1.4.7 follow-up), the terminal_* config from config.json, the test
   seam of the thread class (ST.SSHTerminalThread).

§2 ALL the teardown paths — through the single method page.shutdown() (idempotent):
   a) the regular path: the PTY timer is stopped, the signals of the thread/worker are detached
      (a late emit without receivers — a no-op), the thread is stopped, the registry of the orphan threads is empty;
   b) the orphan path (v1.1.2RC1 N4): the thread "connects" (blocks up to 15 s in
      reality) — shutdown() waits wait(1500), did not wait → the registry _orphan_threads,
      the late finished() self-cleans the registry;
   c) the SFTP worker: the lazy start on the live transport, shutdown() — the stop in the budget,
      the signals are detached (the pattern test_sftp_tab §6);
   d) the error path: error_signal → QMessageBox.critical + the status (state AND the
      status-bar bridge — the v1.4.7 follow-up) + close_terminal
      (without the host — the teardown directly);
   e) close_terminal() with the host window — the window is closed by the regular path.

§3 confirm_close — the "ask" gate (terminal_close_behavior): "close" without the dialog;
   "ask" + the active session → Cancel holds / Close closes; _force_close (the path
   of the limit v1.1.1) and a finished session — without the dialog.

§4 The regression of the window lifecycle (the mode `windows` = v1.1.x): the wrapper
   (WA_DeleteOnClose, the title, the geometry window_geometry.py), the central widget —
   the QTabWidget of the sessions (v1.2.1: the compat properties live-reference the ACTIVE tab),
   the canvas resize → the grid synchronization via eventFilter
   (before — the window resizeEvent), the bridge "the page status bar → the window status bar"
   (the sticky text + the SFTP progress), the round-trip of ui_window_geometry_terminal,
   the WA_DeleteOnClose E2E (the C++ object is destroyed after the close).

§5 The tracking by SESSIONS in MainWindow (ROADMAP task 4): the registry _terminal_windows
   stores the TerminalSessionPage, not the windows; v1.2.1: two sessions of one node — two tabs
   in one window (the second "connect to the node" reuses the live window); the green
   dot of the node goes out only when ALL the sessions of the node are closed; the limit "4 own terminals"
   (terminal_max_open) is counted by the sessions in all the windows — Close closes the tab
   of the oldest one (_force_close), Cancel — None.

§6 The i18n parity (the pin EXPECTED_I18N_KEYS in _common.py; v1.2.1: 400) + the release state
   (the pin _common.py).

Run:  python tests/test_terminal_page.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys

from _common import (bootstrap, check, finish, wait_until, load_i18n_langs, check_i18n_parity,
                     check_release_state, cfg_path, write_cfg, clear_cfg)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMessageBox, QTabWidget, QSplitter

app = QApplication(sys.argv)

import modules.ssh_terminal as ST
import modules.terminal_page as TP
import modules.sftp_worker as SWORK
from modules.terminal_page import TerminalSessionPage
from modules.terminal_screen import TerminalScreen
from modules.terminal_widget import TerminalWidget
from models.server import ServerData
import ui.main_window as MW


# ════════════════════════════════════════════════════════════
# The harness: fake threads (the same API as SSHTerminalThread) — _fakes.py
# ════════════════════════════════════════════════════════════

from _fakes import (FakeSSHThread as _FakeThread, BlockingFakeSSHThread as _BlockingThread,
                    QuestionStub)


class _FakeSftpAttr:
    def __init__(self, filename, is_dir, size, mtime):
        self.filename = filename
        self.st_mode = 0o40755 if is_dir else 0o100644
        self.st_size = size
        self.st_mtime = mtime


class _FakeSftpFS:
    def __init__(self):
        self.dirs = {"/"}
        self.files = {}

    def add_file(self, path, data, mtime=1700000000):
        self.files[path] = bytes(data)


class _FakeSftpFile:
    def __init__(self, fs, path, mode):
        self._fs, self._path, self._pos = fs, path, 0

    def read(self, n=-1):
        buf = self._fs.files.get(self._path, b"")
        end = len(buf) if n < 0 else min(len(buf), self._pos + n)
        data = bytes(buf[self._pos:end])
        self._pos = end
        return data

    def write(self, data):
        buf = self._fs.files.setdefault(self._path, bytearray())
        buf.extend(data)

    def close(self):
        pass


class _FakeSftpClient:
    """The minimal fake paramiko SFTPClient (listdir_attr/open/close/get_channel)."""

    def __init__(self, fs):
        self._fs = fs
        self._closed = False

    def listdir_attr(self, path):
        out = []
        for f in sorted(self._fs.files):
            if os.path.dirname(f) == (path or "/"):
                out.append(_FakeSftpAttr(os.path.basename(f), False, len(self._fs.files[f]), 0))
        return out

    def open(self, path, mode="r"):
        return _FakeSftpFile(self._fs, path, mode)

    def get_channel(self):
        return self

    @property
    def closed(self):
        return self._closed

    def close(self):
        self._closed = True


# The paramiko SSHClient surface for _ensure_sftp — shared (_fakes.FakeSSHClient):
# get_transport/open_sftp; open_sftp() with sftp=None raises an Exception.
from _fakes import FakeSSHClient as _FakeSshClient
def alive(w):
    """Is the C++ object alive (WA_DeleteOnClose: after the accept — already destroyed)."""
    try:
        w.windowTitle()
        return True
    except RuntimeError:  # Internal C++ object already deleted
        return False


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeThread   # all the pages/windows in this file — on the fake

_pages, _windows = [], []


def make_page(alias, password=None, initial_command=""):
    """The page with the fake thread (parent=None — standalone, without the host window)."""
    p = TerminalSessionPage(
        ServerData(id=f"tp-{alias}", alias=alias, host="10.99.0.1", user="root"),
        None, password=password, initial_command=initial_command)
    _pages.append(p)
    app.processEvents()
    return p


# ════════════════════════════════════════════════════════════
# 1. Page construction: the session as a reusable widget
# ════════════════════════════════════════════════════════════
print("== page construction ==")

clear_cfg()
data_pw = ServerData(id="tp-pw", alias="pw", host="10.99.0.2", user="root", password="nodepw")
p1 = make_page("pw", password="explicit")
check("the page is a QWidget with the session (server_data is kept)",
      p1.server_data is data_pw or p1.server_data.alias == "pw")
check("the test seam: the thread is created by the ST.SSHTerminalThread class (the monkeypatched one)",
      isinstance(p1.terminal_thread, _FakeThread), type(p1.terminal_thread).__name__)
check("the password parameter wins over node.data.password (AUDIT v0.7.2 medium #7)",
      p1.terminal_thread.password == "explicit")
p1b = make_page("pw2", password=None)
data_pw2 = ServerData(id="tp-pw3", alias="pw3", host="10.99.0.3", user="root", password="nodepw3")
p1c = TerminalSessionPage(data_pw2, None)   # password=None → node.data.password
_pages.append(p1c)
check("password=None → the password comes from node.data (the model need not keep it)",
      p1c.terminal_thread.password == "nodepw3", p1c.terminal_thread.password)

p1d = make_page("grid")
check("the pyte screen is 120×32 (the invoke_shell geometry)",
      p1d.tscreen.columns == 120 and p1d.tscreen.lines == 32,
      f"{p1d.tscreen.columns}x{p1d.tscreen.lines}")
check("the terminal canvas is a TerminalWidget", isinstance(p1d.widget, TerminalWidget))
check("QTabWidget [Terminal | Files | History] (v1.1.3; the third tab — v1.5.7)",
      p1d.tabs.count() == 3
      and p1d.tabs.widget(0) is p1d.widget and p1d.tabs.widget(1) is p1d.sftp_tab
      and p1d.tabs.widget(2) is p1d.history_tab)
# ── v1.4.7 follow-up: the page draws NO status line — the HOST's bar is the surface ──
check("the page draws no status line: the label is state, not a row (terminal.initializing)",
      p1d.status_label.text() != "" and p1d.status_label.isHidden() is True
      and p1d.layout().indexOf(p1d.status_label) == -1,
      p1d.status_label.text())
check("the state is readable as DATA (the `session_status` property)",
      p1d.session_status == p1d.status_label.text()
      == TP.get_translator()("terminal.initializing"),
      p1d.session_status)
_status_msgs = []
p1d.status_message.connect(lambda text, ms: _status_msgs.append((text, ms)))
p1d.terminal_thread.status_signal.emit("SSH session opened")
app.processEvents()
check("EVERY status write goes to the bridge (the single status path of the page)",
      _status_msgs == [("SSH session opened", 0)]
      and p1d.session_status == "SSH session opened",
      f"{_status_msgs}/{p1d.session_status}")
check("a two-tab page KEEPS its tab strip (the strip is only dropped for a single tab)",
      p1d.tabs.tabBar().isHidden() is False)

# The terminal_* config — read on page creation (load_terminal_settings)
write_cfg({"terminal_wheel": "off", "terminal_palette": "nord",
              "terminal_font": "Consolas", "terminal_font_size": 12,
              "terminal_history_lines": 50})
pcfg = make_page("cfg")
check("config: terminal_wheel='off' → widget._wheel_mode", pcfg.widget._wheel_mode == "off")
check("config: the nord palette is applied to the canvas", pcfg.widget._palette_name == "nord",
      pcfg.widget._palette_name)
check("config: the Consolas 12 font is applied",
      pcfg.widget._font.family() == "Consolas" and pcfg.widget._font.pointSize() == 12,
      f"{pcfg.widget._font.family()} pt{pcfg.widget._font.pointSize()}")
for _ in range(200):
    pcfg.tscreen.feed(b"x\r\n")
pos, size = pcfg.tscreen.scroll_info()
check("config: the history depth is 50 (terminal_history_lines)", size == 50 and pos == 50,
      f"pos={pos} size={size}")
clear_cfg()


# ════════════════════════════════════════════════════════════
# 2. Teardown: all paths — through the single shutdown() method
# ════════════════════════════════════════════════════════════
print("== teardown paths (single shutdown method) ==")

# ── a) the regular path: the idle thread ─────────────────────────────────────────────
pa = make_page("td-a")
app.processEvents()
text_before = pa.widget.visible_text()
pa.shutdown()
check("a: _shut_down=True (the method ran)", pa._shut_down is True)
check("a: the PTY debounce timer is stopped", not pa._pty_timer.isActive())
check("a: the thread is stopped (stop() was called)", pa.terminal_thread.stop_calls >= 1,
      f"calls={pa.terminal_thread.stop_calls}")
# The thread signals are disconnected: a late emit without receivers — a no-op
pa.terminal_thread.output_signal.emit(b"late output\r\n")
app.processEvents()
check("a: output_signal after shutdown does not change the screen (the slots are detached)",
      pa.widget.visible_text() == text_before, repr(pa.widget.visible_text())[:80])
# Idempotency: a repeated teardown — a no-op without exceptions
try:
    pa.shutdown()
    check("a: a double shutdown() — an idempotent no-op", True)
except Exception as e:  # noqa: BLE001
    check("a: a double shutdown() — an idempotent no-op", False, repr(e))
check("a: the orphan-thread registry is empty (the idle thread survived within the budget)",
      pa.terminal_thread not in ST._orphan_threads)

# ── b) the orphan path (N4 v1.1.2RC1): the thread "connects" longer than wait(1500) ────
ST.SSHTerminalThread = _BlockingThread
pb = make_page("td-b")
wait_until(lambda: pb.terminal_thread.isRunning(), timeout_ms=3000)
check("b: the thread is running (the 'connection' is in progress)", pb.terminal_thread.isRunning())
pb.shutdown()   # stop() + wait(1500) — the thread is blocked → it outlives the wait
th_b = pb.terminal_thread
check("b: the thread that outlived wait(1500) is in the _orphan_threads registry (N4)",
      th_b in ST._orphan_threads and th_b.isRunning(),
      f"registry={len(ST._orphan_threads)} running={th_b.isRunning()}")
check("b: stop() was called (running=False, but the paramiko block goes on)",
      th_b.stop_calls >= 1 and th_b.running is False)
th_b.release()   # "the connection is complete" — a late finished() cleans the registry on its own
wait_until(lambda: th_b not in ST._orphan_threads, timeout_ms=8000)
check("b: finished() → the registry self-cleans (the thread is not destroyed by the GC)",
      th_b not in ST._orphan_threads and th_b.isFinished(),
      f"registry={len(ST._orphan_threads)} finished={th_b.isFinished()}")
ST.SSHTerminalThread = _FakeThread

# ── c) The SFTP worker: a lazy start + a shutdown within the budget ──────────────────────
fs_c = _FakeSftpFS()
fs_c.add_file("/a.txt", b"hello")
pc = make_page("td-c")
pc.terminal_thread.client = _FakeSshClient(_FakeSftpClient(fs_c))   # "connected"
check("c: the worker is lazy — it does not exist before open_sftp", pc._sftp_worker is None)
check("c: _ensure_sftp() opened SFTP on the shared transport and started the worker",
      pc._ensure_sftp() is True and pc._sftp_worker is not None
      and pc._sftp_worker.isRunning())
worker_c = pc._sftp_worker
pc.shutdown()
check("c: the worker is stopped within the shutdown budget (wait_ms=2500)",
      not worker_c.isRunning(), f"running={worker_c.isRunning()}")
check("c: the idle worker did not go into the orphan-worker registry",
      worker_c not in SWORK._orphan_workers, f"registry={len(SWORK._orphan_workers)}")
# The worker's signals are disconnected: a late emit — a no-op
worker_c.task_started.emit(99, "list", "/late")
app.processEvents()
check("c: task_started after shutdown does not change the page state (the slots are detached)",
      pc._sftp_tasks == {} and pc._sftp_busy == 0,
      f"tasks={pc._sftp_tasks} busy={pc._sftp_busy}")

# ── d) the error path: error_signal → critical + the status + close_terminal ─────────
crit_calls = []
_orig_critical = ST.QMessageBox.critical
ST.QMessageBox.critical = staticmethod(lambda *a, **k: crit_calls.append(a))
try:
    pd = make_page("td-d")
    _err_msgs = []
    pd.status_message.connect(lambda text, ms: _err_msgs.append((text, ms)))
    pd.terminal_thread.error_signal.emit("boom")
    app.processEvents()
    check("d: error_signal → QMessageBox.critical (the parent — the host window / None)",
          len(crit_calls) == 1 and crit_calls[0][0] is None, str(crit_calls)[:120])
    check("d: the error text is the session state", "boom" in pd.status_label.text(),
          pd.status_label.text())
    check("d: ...and it reaches the STATUS BAR too (the v1.4.7 follow-up fixed the "
          "error path that only the modal dialog used to show)",
          "boom" in pd.session_status and _err_msgs[-1][0] == pd.session_status,
          f"{pd.session_status!r}/{_err_msgs[-1:]!r}")
    check("d: error → close_terminal (no host — the teardown runs directly)",
          pd._shut_down is True and pd.terminal_thread.stop_calls >= 1)
finally:
    ST.QMessageBox.critical = _orig_critical

# ── e) close_terminal() with the host window: the window closes via the regular path ─────────
pe_win = ST.SSHTerminalWindow(
    ServerData(id="tp-td-e", alias="td-e", host="10.99.0.4", user="root"), None, password="pw")
_windows.append(pe_win)
check("e: the page is bound to the host window (set_host_window)",
      pe_win.page._host_window is pe_win)
pe_win.show()
app.processEvents()
pe_win.page.close_terminal()   # the thread stop + the host's close() → closeEvent → shutdown
wait_until(lambda: not alive(pe_win), timeout_ms=4000)
check("e: page.close_terminal() closed the host window (WA_DeleteOnClose)",
      not alive(pe_win))


# ════════════════════════════════════════════════════════════
# 3. confirm_close — gate «ask» (terminal_close_behavior)
# ════════════════════════════════════════════════════════════
print("== confirm_close 'ask' gate ==")

asked = []
_question = QuestionStub(QMessageBox.StandardButton.Cancel,
                         record=lambda title, text: asked.append(title)).install(ST)
try:
    # "close" (the v1.0/v1.1 default) — no dialog
    clear_cfg()
    pg1 = make_page("ask-close")
    check("the close_behavior default is 'close'", getattr(pg1, "_close_behavior", None) == "close")
    asked.clear()
    check("'close' + an active session: no dialog → True",
          pg1.confirm_close() is True and len(asked) == 0, str(asked))

    # "ask" + an active session: Cancel → False (the window survives), Close → True
    write_cfg({"terminal_close_behavior": "ask"})
    ST.SSHTerminalThread = _BlockingThread
    pg2 = make_page("ask-live")
    wait_until(lambda: pg2.terminal_thread.isRunning(), timeout_ms=3000)
    asked.clear()
    _question.answer = QMessageBox.StandardButton.Cancel
    check("'ask' + an active session + Cancel → False (the teardown is not started)",
          pg2.confirm_close() is False and len(asked) == 1 and pg2._shut_down is False,
          f"asked={asked}")
    _question.answer = QMessageBox.StandardButton.Close
    check("'ask' + an active session + Close → True", pg2.confirm_close() is True)

    # _force_close (the v1.1.1 limit path): the decision is confirmed — no dialog
    asked.clear()
    pg2._force_close = True
    check("'ask' + _force_close: no dialog → True",
          pg2.confirm_close() is True and len(asked) == 0, str(asked))
    pg2.terminal_thread.release()
    wait_until(lambda: not pg2.terminal_thread.isRunning(), timeout_ms=5000)
    ST.SSHTerminalThread = _FakeThread

    # "ask", but the session is already finished → no dialog
    write_cfg({"terminal_close_behavior": "ask"})
    pg3 = make_page("ask-dead")
    pg3.terminal_thread.wait(2000)   # a guaranteed inactive session (no race)
    asked.clear()
    check("'ask' + a finished session: no dialog → True",
          pg3.confirm_close() is True and len(asked) == 0, str(asked))
finally:
    _question.restore()
    clear_cfg()


# ════════════════════════════════════════════════════════════
# 4. The window lifecycle regression (the `windows` mode = v1.1.x)
# ════════════════════════════════════════════════════════════
print("== window lifecycle regression (thin wrapper) ==")

clear_cfg()
wv = ST.SSHTerminalWindow(
    ServerData(id="tp-win", alias="win", host="10.99.0.5", user="root"), None, password="pw")
_windows.append(wv)
check("the window: WA_DeleteOnClose is kept",
      bool(wv.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)) is True)
check("the window: the title is terminal.window_title (alias+host)",
      "win" in wv.windowTitle() and "10.99.0.5" in wv.windowTitle(), wv.windowTitle())
# v1.3: the central widget — QSplitter [cmdlib_panel | session_tabs] (the "Terminal macros" panel)
# v1.3.3.5: the right member is the VERTICAL splitter [session_tabs | split_host] (the terminal split)
check("the window: the central widget is a QSplitter [cmdlib_panel | QSplitter(session_tabs | split_host)]",
      isinstance(wv.centralWidget(), QSplitter)
      and wv.cmdlib_panel is wv.centralWidget().widget(0)
      and wv._v_splitter is wv.centralWidget().widget(1)
      and wv.session_tabs is wv._v_splitter.widget(0)
      and wv.split_host is wv._v_splitter.widget(1)
      and wv.session_tabs.widget(0) is wv.page)
check("the window: the compat server_data (the BUGFIX v0.9.5.5 is kept)",
      wv.server_data.alias == "win")

# The Compat properties — live references to the page's session
check("compat: win.widget/tscreen/terminal_thread — the same objects as the page's",
      wv.widget is wv.page.widget and wv.tscreen is wv.page.tscreen
      and wv.terminal_thread is wv.page.terminal_thread)
check("compat: win.tabs/sftp_tab/status_label/_sftp_worker — live references",
      wv.tabs is wv.page.tabs and wv.sftp_tab is wv.page.sftp_tab
      and wv.status_label is wv.page.status_label
      and wv._sftp_worker is None)

# A canvas resize (inside the tab) → the grid synchronization via the page eventFilter
# (previously — the window's resizeEvent); a guard on grid change + ~150 ms debounce.
# IMPORTANT: show() BEFORE resize — offscreen defers the geometry of a hidden top-level
# before the first show (verified: a hidden window does NOT get a resizeEvent in v1.1.x,
# nor in v1.2 — the grid synchronization happens on show/resize of the visible window;
# the production path of _spawn_terminal_window always show()s right after the creation).
wv.show()
app.processEvents()
wv.resize(700, 500)
wait_until(lambda: (wv.page._last_cols, wv.page._last_rows) != (120, 32), timeout_ms=4000)
app.processEvents()
check("a window resize → the grid is recomputed (the page's eventFilter)",
      (wv.page._last_cols, wv.page._last_rows) != (120, 32),
      f"grid={wv.page._last_cols}x{wv.page._last_rows}")
check("compat: win._last_cols/_last_rows — the page's live properties",
      (wv._last_cols, wv._last_rows) == (wv.page._last_cols, wv.page._last_rows))
wv._pending_pty = (50, 20)   # the setter of the compat property
check("compat: win._pending_pty get/set — the page's live property",
      wv._pending_pty == (50, 20) and wv.page._pending_pty == (50, 20))
wv.page._pending_pty = None
check("close_terminal() is kept on the window (the MainWindow cleanup path)",
      callable(getattr(wv, "close_terminal", None)))

# The "page status bar → window status bar" bridge (the v1.1.x view)
wv.page.status_message.emit("bridge message", 0)
app.processEvents()
check("the bridge: status_message(sticky) → statusBar().currentMessage()",
      wv.statusBar().currentMessage() == "bridge message",
      repr(wv.statusBar().currentMessage()))
wv.page.status_message.emit("timed message", 5000)
app.processEvents()
check("the bridge: status_message with a timeout → showMessage(text, ms)",
      wv.statusBar().currentMessage() == "timed message")
check("the bridge: the SFTP progress bar is in the window's status bar, hidden",
      wv._sftp_progress.isHidden())
wv.page.progress_busy.emit()
app.processEvents()
check("the bridge: progress_busy → the bar is visible (indeterminate)",
      not wv._sftp_progress.isHidden() and wv._sftp_progress.maximum() == 0)
wv.page.progress_update.emit(5, 10)
app.processEvents()
check("the bridge: progress_update(5,10) → range/value",
      wv._sftp_progress.maximum() == 10 and wv._sftp_progress.value() == 5,
      f"max={wv._sftp_progress.maximum()} val={wv._sftp_progress.value()}")
wv.page.progress_hidden.emit()
app.processEvents()
check("the bridge: progress_hidden → the bar is hidden", wv._sftp_progress.isHidden())

# ── the geometry: closeEvent saves, a new window restores (U2) ─────────
clear_cfg()
wv.resize(640, 480)   # the terminal window default — 800×600, the restoration is visible
app.processEvents()
wv.close()
wait_until(lambda: not alive(wv), timeout_ms=4000)
with open(cfg_path(), encoding="utf-8") as f:
    _val = json.load(f).get("ui_window_geometry_terminal")
check("the geometry: closeEvent wrote ui_window_geometry_terminal {geometry, state}",
      isinstance(_val, dict) and set(_val) == {"geometry", "state"}, f"got={_val!r}")
wv2 = ST.SSHTerminalWindow(
    ServerData(id="tp-win2", alias="win2", host="10.99.0.6", user="root"), None, password="pw")
_windows.append(wv2)
app.processEvents()
check("the geometry: the new window restored 640×480 (the default is 800×600)",
      wv2.size() == QSize(640, 480), f"got={wv2.size()}")

# ── WA_DeleteOnClose E2E: show + close → the C++ object is destroyed ───────────────
wv3 = ST.SSHTerminalWindow(
    ServerData(id="tp-win3", alias="win3", host="10.99.0.7", user="root"), None, password="pw")
_windows.append(wv3)
wv3.show()
app.processEvents()
check("WA_DeleteOnClose: the window is alive before close()", alive(wv3))
wv3.close()
wait_until(lambda: not alive(wv3), timeout_ms=4000)
check("WA_DeleteOnClose: after close the C++ object is destroyed", not alive(wv3))
clear_cfg()


# ════════════════════════════════════════════════════════════
# 5. Tracking by SESSIONS in MainWindow (ROADMAP task 4)
# ════════════════════════════════════════════════════════════
print("== session tracking in MainWindow ==")

clear_cfg()
mw = MW.MainWindow()
mw.show()
app.processEvents()


def dot_color(node):
    return node._ssh_status.brush().color().name()


# ── two sessions of one node (v1.2.1: two tabs in one window): the dot goes out only when ALL are closed ──
node1 = mw.scene.add_server(
    ServerData(id="sess-a", alias="sessA", host="10.98.1.1", user="root"))
win_s1 = mw._spawn_terminal_window(node1)
win_s2 = mw._spawn_terminal_window(node1)   # v1.2.1: a new tab in the same window
app.processEvents()
check("the registry stores SESSIONS (TerminalSessionPage), not windows",
      len(mw._terminal_windows) == 2
      and all(isinstance(s, TerminalSessionPage) for s in mw._terminal_windows)
      and all(s is not win_s1 and s is not win_s2 for s in mw._terminal_windows),
      f"registry={[type(s).__name__ for s in mw._terminal_windows]}")
check("v1.2.1: the second session is a TAB in the same window (not a new window)",
      win_s2 is win_s1 and win_s1.session_tabs.count() == 2,
      f"tabs={win_s1.session_tabs.count() if alive(win_s1) else '?'}")
check("the node's green dot is lit (2 active sessions)", dot_color(node1) == "#22c55e",
      dot_color(node1))

page_s1 = win_s1.session_tabs.widget(0)
win_s1.close_page(page_s1)   # one tab is closed — the neighbour is alive
wait_until(lambda: len(mw._terminal_windows) == 1, timeout_ms=4000)
app.processEvents()
check("one of the two tabs is closed → the registry has 1 (the page's destroyed signal)",
      len(mw._terminal_windows) == 1 and not alive(page_s1))
check("the green dot is lit while the node's second session is alive", dot_color(node1) == "#22c55e",
      dot_color(node1))

win_s1.close_page(win_s1.session_tabs.widget(0))   # the last tab → the window (all the node's sessions are closed)
wait_until(lambda: len(mw._terminal_windows) == 0, timeout_ms=4000)
app.processEvents()
check("ALL the node's sessions are closed → the registry is empty", len(mw._terminal_windows) == 0)
check("the green dot went out (all the sessions are closed)", dot_color(node1) == "#64748b",
      dot_color(node1))
check("_ssh_connected_nodes: the node id is reset after all the sessions",
      node1.data.id not in mw._ssh_connected_nodes)

# ── the "own terminals" limit is counted by SESSIONS (terminal_max_open) ────────
write_cfg({"terminal_max_open": 2})
node2 = mw.scene.add_server(
    ServerData(id="sess-b", alias="sessB", host="10.98.1.2", user="root"))
w_a = mw._spawn_terminal_window(node2)
mw._spawn_terminal_window(node2)   # v1.2.1: a second tab in the same window (w_a)
app.processEvents()
check("the limit: 2 sessions are open (terminal_max_open=2; both tabs in one window)",
      len(mw._terminal_windows) == 2 and w_a.session_tabs.count() == 2,
      f"registry={len(mw._terminal_windows)} tabs={w_a.session_tabs.count() if alive(w_a) else '?'}")

_limit_stub = QuestionStub(QMessageBox.StandardButton.Cancel,
                           record=lambda title, text: asked.append(title)).install(MW)
try:
    # Cancel → None, the registry is untouched
    node3 = mw.scene.add_server(
        ServerData(id="sess-c", alias="sessC", host="10.98.1.3", user="root"))
    asked.clear()
    w_cancel = mw._spawn_terminal_window(node3)
    check("the limit: Cancel → None, the registry is unchanged (2 sessions)",
          w_cancel is None and len(asked) == 1 and len(mw._terminal_windows) == 2,
          f"asked={asked} registry={len(mw._terminal_windows)}")

    # Close → the oldest SESSION is closed (_force_close), a new one is registered
    _limit_stub.answer = QMessageBox.StandardButton.Close
    asked.clear()
    oldest_sess = mw._terminal_windows[0]   # the first tab of the node2 window (the creation order)
    node4 = mw.scene.add_server(
        ServerData(id="sess-d", alias="sessD", host="10.98.1.4", user="root"))
    w_new = mw._spawn_terminal_window(node4)
    check("the limit: Close → the dialog about the oldest session", len(asked) == 1, str(asked))
    check("the limit: _force_close is set on the oldest session (against a repeated 'ask')",
          getattr(oldest_sess, "_force_close", False) is True)
    wait_until(lambda: oldest_sess not in mw._terminal_windows, timeout_ms=4000)
    app.processEvents()
    check("the limit: the oldest session's tab is closed — its window stays alive with the neighbour (v1.2.1)",
          alive(w_a) and w_a.session_tabs.count() == 1,
          f"tabs={w_a.session_tabs.count() if alive(w_a) else '?'}")
    check("the limit: the registry is 2 again — the oldest is removed, the new session is registered",
          w_new is not None and len(mw._terminal_windows) == 2
          and oldest_sess not in mw._terminal_windows
          and mw._terminal_windows[-1] is w_new.page,
          f"registry={[type(s).__name__ for s in mw._terminal_windows]}")
finally:
    _limit_stub.restore()
clear_cfg()


# ════════════════════════════════════════════════════════════
# 6. i18n parity + release state
# ════════════════════════════════════════════════════════════
print("== i18n parity + release state ==")

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)   # the parity by the EXPECTED_I18N_KEYS pin (v1.2.1: 400)
check_release_state(ROOT)

finish()
