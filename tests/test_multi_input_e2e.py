# -*- coding: utf-8 -*-
"""v1.2.4 — Multi-input: E2E on REAL SSH channels (paramiko), no fake threads.

Why a separate file: the thematic test_multi_input.py proves the chain
TerminalWidget.keyPressEvent → _send → hub.broadcast → page.terminal_thread.send_data()
on the fakes (the same API as SSHTerminalThread). This file closes the last
uncovered segment — the REAL paramiko: the real Transport/Channel on the
server side (the in-process echo-shell), the real SSHTerminalThread of the client, the real
authentication and the known_hosts pinning. The incident of v1.2.4: the manual testing did not
confirm the broadcast on the live sessions — the E2E pins down the behavior on the real
channels and catches the regressions in send_data/the liveness of the threads that the fakes do not see.

§1 The window mode (as the user: terminal_mode=windows), 3 terminals:
   the enabling via the menu path (_toggle_multi_input(True)) → a key in the active
   widget → the same bytes into ALL the other real channels; the source receives
   exactly once (no echo). The mode is disabled → no duplicates (the behavior of v1.2.2).
   Plus the "real event path" (v1.2.4-fix): the keys by postEvent through the Qt
   event loop (the focus + QWidget::event) — not only the direct keyPressEvent calls.

§2 The dock mode (terminal_mode=tabs, TerminalDockContent): 2 sessions in the dock —
   the broadcast into all the other tabs of the dock.

§3 The diagnostics (v1.2.4-fix): the state change of the mode is written to the log of the application
   (the INFO "Multi-input mode enabled/disabled"), the broadcast — the DEBUG line on every
   input; the log file under the isolated HOME is checked by the content.

Run:  python tests/test_multi_input_e2e.py   (from the project root) or python tests/run_all.py
The network is not needed: the SSH server lives in the process (the paramiko ServerInterface, the echo-shell).
"""
import os
import socket
import sys
import threading
import time

from _common import bootstrap, check, finish, wait_until

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

import paramiko  # noqa: E402
import i18n  # noqa: E402
import modules.ssh_terminal as ST  # noqa: E402
from models.server import ServerData  # noqa: E402
import ui.main_window as MW  # noqa: E402
from modules.multi_input import get_hub  # noqa: E402
from modules.logger import setup_logging, get_log_file_path  # noqa: E402

setup_logging()   # the log into the isolated HOME (~/.sshmap/logs/sshmap.log) — needed for §3


# ════════════════════════════════════════════════════════
# The harness: an in-process SSH echo server (a real paramiko transport/channel)
# ════════════════════════════════════════════════════════

HOST_KEY = paramiko.RSAKey.generate(2048)


class EchoServer(paramiko.ServerInterface):
    """Echo-shell: every client input is echoed back (like a bash echo).

    IMPORTANT (verified by a run, paramiko 5.0): for the channel REQUESTs (pty/shell)
    the result must be TRUTHY — OPEN_SUCCEEDED == 0 (falsy!) would give
    CHANNEL_FAILURE, and the client closed the channel itself ("Channel closed.")."""

    def __init__(self):
        self.shell_channel = None
        self.data_log = []   # the whole client input (for the broadcast asserts)

    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(self, channel, term, width, height, pw, ph, modes):
        return True

    def check_channel_shell_request(self, channel):
        self.shell_channel = channel
        try:
            channel.send(b"\r\nECHO-SHELL READY\r\n")
        except Exception:
            pass
        return True


SERVERS = []       # An EchoServer on the connection (the order of accepts)
TRANSPORTS = []    # the live references: without them the GC would kill the Transport together with the channel


def _handle(conn):
    """One connection — its own thread (the accept loop is not blocked)."""
    try:
        transport = paramiko.Transport(conn)
        transport.add_server_key(HOST_KEY)
        srv = EchoServer()
        SERVERS.append(srv)
        TRANSPORTS.append(transport)
        transport.start_server(server=srv)
        # auth + open channel + the shell request come AFTER start_server — we wait
        deadline = time.time() + 20
        while srv.shell_channel is None and time.time() < deadline:
            if not transport.is_active():
                break
            time.sleep(0.05)
        chan = srv.shell_channel
        if chan is None:
            return
        while not chan.closed:
            if chan.recv_ready():
                data = chan.recv(4096)
                if data:
                    srv.data_log.append(data)
                    chan.sendall(data)   # an echo back into the client terminal
            else:
                time.sleep(0.02)
    except Exception:
        pass  # the server harness: a connection failure must not crash the test


_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
_listener.bind(("127.0.0.1", 0))
PORT = _listener.getsockname()[1]
_listener.listen(8)


def _serve():
    # IMPORTANT (v1.2.4-fix): THE THREAD ON THE CONNECTION — _handle is blocked in the recv loop
    # before closing the channel; a single-threaded accept loop would have served only the FIRST
    # client, the others would have been waiting for the banner ("Error reading SSH protocol banner").
    while True:
        try:
            conn, _addr = _listener.accept()
        except OSError:
            return  # the socket is closed (exit) — the accept loop is done
        threading.Thread(target=_handle, args=(conn,), daemon=True).start()


threading.Thread(target=_serve, daemon=True).start()


# The test seam (the v1.1.x pattern): QMessageBox from ssh_terminal is taken at the moment
# call — we replace it with a NON-MODAL fake so a session error does not block
# an offscreen run; we record every call (check: there must be no dialogs).
DIALOGS = []


class _FakeBox:
    Close = 1
    Cancel = 0

    @staticmethod
    def question(*args, **kwargs):
        DIALOGS.append(("question", args))
        return _FakeBox.Close

    @staticmethod
    def critical(*args, **kwargs):
        DIALOGS.append(("critical", args))
        return _FakeBox.Close

    @staticmethod
    def information(*args, **kwargs):
        DIALOGS.append(("information", args))
        return _FakeBox.Close


ST.QMessageBox = _FakeBox


def key_event(key, text="", mod=Qt.KeyboardModifier.NoModifier):
    return QKeyEvent(QKeyEvent.Type.KeyPress, int(key), mod, text)


def type_text(widget, text):
    """Keys at the single input point (keyPressEvent → _send).

    The physical keyboard goes through the same path: the app shortcuts are only
    F12 (in the mode)/Ctrl+Z/Ctrl+Y/Ctrl+K, none intercepts printable
    keys/Enter/Backspace (the setShortcut/QKeySequence audit over ui/)."""
    for ch in text:
        widget.keyPressEvent(QKeyEvent(
            QKeyEvent.Type.KeyPress, ord(ch.upper()),
            Qt.KeyboardModifier.NoModifier, ch))
    widget.keyPressEvent(QKeyEvent(
        QKeyEvent.Type.KeyPress, int(Qt.Key.Key_Return),
        Qt.KeyboardModifier.NoModifier, "\r"))


def all_logs():
    return [b"".join(s.data_log) for s in SERVERS]


# ════════════════════════════════════════════════════════
# 1. Window mode: 3 real terminals, broadcast to all the others
# ════════════════════════════════════════════════════════
print("== 1. windows mode, 3 real SSH terminals ==")

hub_app = get_hub()   # the process singleton (the same one as in the widgets and MainWindow)
hub_app.reset()

mw = MW.MainWindow()
mw._autosave_timer.stop()
mw.show()
app.processEvents()

check("the window holds the hub singleton + the provider", mw._multi_hub is hub_app
      and hub_app.session_provider is not None)

nodes, wins = [], {}
for alias in ("e2e-a", "e2e-b", "e2e-c"):
    node = mw.scene.add_server(ServerData(
        id=f"e2e-{alias}", alias=alias, host="127.0.0.1", user="root",
        password="e2e-pass", ssh_port=PORT))
    wins[alias] = mw._spawn_terminal_window(node)
    nodes.append(node)
    app.processEvents()


def all_connected():
    return len(mw._terminal_windows) == 3 and all(
        getattr(s.terminal_thread, "channel", None) is not None
        and not s.terminal_thread.channel.closed
        for s in mw._terminal_windows)


wait_until(all_connected, timeout_ms=25000)
check("3 sessions in the registry + all the REAL channels are open (paramiko)",
      all_connected() and len(SERVERS) == 3,
      f"registry={len(mw._terminal_windows)} servers={len(SERVERS)}")
check("no session errors (there were no dialogs)", DIALOGS == [], repr(DIALOGS))

# enabling — the checkable QAction path ("View" → Multi Input)
mw._toggle_multi_input(True)
app.processEvents()
check("the mode is on: the hub is active, the plaque 'MULTI: 3 sessions'",
      hub_app.active is True and not mw._multi_plaque.isHidden()
      and mw._multi_label.text() == i18n.t("terminal.multi_status", count=3),
      repr(mw._multi_label.text()))

pages = {s.server_data.alias: s for s in mw._terminal_windows}
type_text(pages["e2e-a"].widget, "hello-multi")
wait_until(lambda: all(b"hello-multi\r" in log for log in all_logs()),
           timeout_ms=5000)

logs = all_logs()
check("the broadcast: the same bytes into ALL the real channels (3 servers)",
      all(b"hello-multi\r" in log for log in logs), repr(logs))
check("each channel received the input exactly once (no duplicates / no echo)",
      all(log.count(b"hello-multi\r") == 1 for log in logs), repr(logs))

# the mode is off → the v1.2.2 behaviour: only the active session
mw._toggle_multi_input(False)
app.processEvents()
for s in SERVERS:
    s.data_log.clear()
type_text(pages["e2e-a"].widget, "solo-only")
wait_until(lambda: any(b"solo-only\r" in log for log in all_logs()), timeout_ms=5000)
logs = all_logs()
got = [i for i, log in enumerate(logs) if b"solo-only\r" in log]
check("the mode is off: exactly ONE channel (the source) received the bytes, no duplicates",
      len(got) == 1 and all(b"solo-only\r" not in log or i in got
                            for i, log in enumerate(logs)), repr(logs))

# ── The real event path (v1.2.4-fix): the keys via the Qt event loop ───────────
# The direct keyPressEvent() calls above bypass the focus and the QWidget::event() chain;
# postEvent + setFocus is closer to a physical keyboard (the event goes through
# the Qt queue → QWidget::event() → keyPressEvent). The app shortcuts on
# the printable keys/Enter are not registered (the QKeySequence audit over ui/:
# The Ctrl+K palette, F12 — only in the mode and only EXIT) — no interception.
mw._toggle_multi_input(True)
app.processEvents()
for s in SERVERS:
    s.data_log.clear()
src_w = pages["e2e-a"].widget
src_w.activateWindow()
src_w.setFocus()
app.processEvents()
for ch in "realpath":
    QApplication.postEvent(src_w, QKeyEvent(
        QKeyEvent.Type.KeyPress, ord(ch.upper()),
        Qt.KeyboardModifier.NoModifier, ch))
QApplication.postEvent(src_w, QKeyEvent(QKeyEvent.Type.KeyPress,
                                       int(Qt.Key.Key_Return),
                                       Qt.KeyboardModifier.NoModifier, "\r"))
wait_until(lambda: all(b"realpath\r" in b"".join(s.data_log) for s in SERVERS),
           timeout_ms=5000)
logs = all_logs()
check("the real event path (postEvent + the focus through the Qt loop): the broadcast into all the channels",
      all(b"realpath\r" in log for log in logs), repr(logs))
mw._toggle_multi_input(False)
app.processEvents()

try:
    mw.close()
except Exception:
    pass
app.processEvents()


# ════════════════════════════════════════════════════════
# 2. Dock mode (terminal_mode=tabs): broadcast to all dock tabs
# ════════════════════════════════════════════════════════
print("== 2. tabs (dock) mode, 2 real sessions ==")

_orig_load_ts = ST.load_terminal_settings


def _tabs_mode(*_a, **_kw):
    d = _orig_load_ts()
    d["mode"] = "tabs"
    return d


ST.load_terminal_settings = _tabs_mode
n_before = len(SERVERS)

mw2 = MW.MainWindow()
mw2._autosave_timer.stop()
mw2.show()
app.processEvents()
check("the hub is shared for all the windows (the process's singleton)", get_hub() is mw2._multi_hub)

for alias in ("dock-a", "dock-b"):
    node = mw2.scene.add_server(ServerData(
        id=f"dock-{alias}", alias=alias, host="127.0.0.1", user="root",
        password="e2e-pass", ssh_port=PORT))
    mw2._spawn_terminal_window(node)
    app.processEvents()

wait_until(lambda: len(mw2._terminal_windows) == 2 and all(
    getattr(s.terminal_thread, "channel", None) is not None
    and not s.terminal_thread.channel.closed
    for s in mw2._terminal_windows), timeout_ms=25000)
check("the dock mode: 2 sessions in the registry + the channels are open",
      len(mw2._terminal_windows) == 2 and len(SERVERS) == n_before + 2,
      f"registry={len(mw2._terminal_windows)} servers={len(SERVERS)}")

dock_pages = {s.server_data.alias: s for s in mw2._terminal_windows}
mw2._toggle_multi_input(True)
app.processEvents()
src_alias = sorted(dock_pages)[0]
type_text(dock_pages[src_alias].widget, "dock-broadcast")
wait_until(lambda: all(b"dock-broadcast\r" in log for log in
                       (b"".join(s.data_log) for s in SERVERS[n_before:])),
           timeout_ms=5000)
check("the dock mode: the broadcast into ALL the other tabs of the dock",
      all(b"dock-broadcast\r" in b"".join(s.data_log) for s in SERVERS[n_before:]),
      repr([b"".join(s.data_log) for s in SERVERS[n_before:]]))

mw2._toggle_multi_input(False)
try:
    mw2.close()
except Exception:
    pass
app.processEvents()
ST.load_terminal_settings = _orig_load_ts


# ════════════════════════════════════════════════════════
# 3. Diagnostics (v1.2.4-fix): mode switching and broadcast — in the log file
# ════════════════════════════════════════════════════════
print("== 3. diagnostics in app log ==")

try:
    with open(get_log_file_path(), encoding="utf-8") as f:
        log_text = f.read()
except OSError as e:
    log_text = ""
    check("the log file is readable", False, repr(e))

check("the log: the mode state change is written (the enabled + the disabled)",
      "Multi-input mode enabled" in log_text
      and "Multi-input mode disabled" in log_text)
check("the log: the broadcast lines for every input in the mode (DEBUG)",
      "multi-input broadcast:" in log_text
      and "-> 2 session(s)" in log_text,   # 3 sessions − the source = 2 receivers
      f"log tail: {log_text[-400:]!r}" if log_text else "(empty)")

finish()
