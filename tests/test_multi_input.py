# -*- coding: utf-8 -*-
"""v1.2.3 — Multi-input (broadcast of the active session's keystrokes to all other open sessions, ROADMAP v1.2.3).

The thematic test of the release v1.2.3 (the "new thematic file" convention): offscreen,
ALL without the network — the fake threads with the same API as SSHTerminalThread (the test seam
ST.SSHTerminalThread). The architecture: all the user input goes through one
point — TerminalWidget.keyPressEvent() → _send(bytes) → terminal_thread.send_data();
the hub (modules/multi_input.py, the singleton of the process) hangs on exactly this point.

§1 The hub unit (MultiInputHub/_thread_alive): the listeners are notified ONLY on the real
   state change; the toggle; the broadcast — the source is skipped (no echo), the dead
   threads are filtered, a dead C++ object in the registry does not crash the broadcast; the reset.

§2 The enabling of the mode via MainWindow: 3 sessions (the window mode); the checkable QAction
   "View" (_toggle_multi_input(True)) → the checkmark + the F12 shortcut (the ApplicationShortcut,
   lives only in the mode), the plaque of the status bar "MULTI: N sessions" with the counter
   and the exit button, the tab badges "MULTI · <alias>", the frame of the QTabWidget (objectName),
   the title prefix of the window terminal.multi_title_prefix, the status message.

§3 The broadcast at the single input point (task 1): a key in the active widget →
   the same bytes into send_data() of ALL the other threads; the source receives exactly once
   (the bytes from the keyboard, not from the output — no echo by definition); the mode is disabled
   → no duplicates (the behavior of v1.2.2).

§4 The F12 exit (task 3): in the mode — F12 does NOT reach the shell (the RC2 mapping \x1b[24~
   is paused), the mode is disabled, the shortcut is removed from the QAction; outside the mode —
   F12 goes to the shell as \x1b[24~ (the mapping is restored). Esc is NOT the exit:
   in the mode it is duplicated into the shell as \x1b (like any input).

§5 The Ctrl+V (the bracketed paste) in the multi mode is also duplicated (task 4): a single block
   \x1b[200~…\x1b[201~ into all the threads (otherwise the "typed text" would not be everywhere).

§6 The dead session (task 4): the closed window is removed from the registry by the regular path
   (destroyed → _forget_terminal_window), the counter of the plaque is updated, the broadcast
   continues into the remaining ones; a dead thread (channel closed) receives no bytes.

§7 The test seam: the explicit multi_hub in the constructor of TerminalWidget — the isolation from
   the singleton of the application (the broadcast goes through its own hub, the application is not touched).

§8 The i18n parity en/ru/zh (411 = 404 + 7: terminal.multi_* ×4, view.multi_input,
   status.multi_enabled/disabled) + the release state (the pin _common.py).

Run:  python tests/test_multi_input.py   (from the project root) or python tests/run_all.py
"""
import sys

from _common import (bootstrap, check, finish, load_i18n_langs,
                     check_i18n_parity, check_release_state)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import i18n
import modules.ssh_terminal as ST
from modules.multi_input import (MultiInputHub, _thread_alive, MULTI_FRAME_OBJECT_NAME)
from modules.terminal_page import TerminalSessionPage
from modules.terminal_screen import TerminalScreen
from modules.terminal_widget import TerminalWidget
from models.server import ServerData
import ui.main_window as MW


# ════════════════════════════════════════════════════════
# The harness: fake threads (the same API as SSHTerminalThread) — _fakes.py
# ════════════════════════════════════════════════════════

from _fakes import FakeSSHThread as _FakeThread


def key_event(key, text="", mod=Qt.KeyboardModifier.NoModifier):
    return QKeyEvent(QKeyEvent.Type.KeyPress, int(key), mod, text)


class _Page:
    """A duck-typed record of the registry (like TerminalSessionPage: .widget + .terminal_thread)."""

    def __init__(self, thread, widget=None):
        self.terminal_thread = thread
        self.widget = widget


def dot_color(node):
    return node._ssh_status.brush().color().name()


# ════════════════════════════════════════════════════════
# 1. The hub unit: state, listeners, broadcast, thread liveness
# ════════════════════════════════════════════════════════
print("== 1. MultiInputHub unit ==")

hub = MultiInputHub()   # an isolated instance (we do not touch the app singleton)

check("start: the mode is off, no registry",
      hub.active is False and hub.session_provider is None)

seen = []
hub.add_listener(seen.append)
hub.set_active(True)
hub.set_active(True)   # a repeat without a change — the notifications are not duplicated
check("the listener is notified ONLY on the real state change", seen == [True], repr(seen))
check("toggle: True → False + the notification", hub.toggle() is False and seen == [True, False])

t_a = _FakeThread("h1", "u", 22)
t_b = _FakeThread("h2", "u", 22)
t_c = _FakeThread("h3", "u", 22)
w_a, w_b, w_c = object(), object(), object()
pages = [_Page(t_a, w_a), _Page(t_b, w_b), _Page(t_c, w_c)]
hub.set_session_provider(lambda: list(pages))
hub.set_active(True)

n = hub.broadcast(b"hello", source_widget=w_a)
check("broadcast: 2 receivers (the source is skipped)", n == 2, f"n={n}")
check("the same bytes into ALL the other threads",
      t_b.channel.sent == [b"hello"] and t_c.channel.sent == [b"hello"],
      f"b={t_b.channel.sent!r} c={t_c.channel.sent!r}")
check("the source does NOT receive from the broadcast (its bytes go through its own send_data)",
      t_a.channel.sent == [])

# a dead session: channel closed (error → close) — filtered by liveness
t_c.channel.closed = True
n = hub.broadcast(b"x", source_widget=w_a)
check("a dead thread (the channel closed) is filtered out: 1 receiver, nothing goes to the dead one",
      n == 1 and t_b.channel.sent[-1] == b"x" and t_c.channel.sent == [b"hello"],
      f"n={n} c={t_c.channel.sent!r}")

# The broadcast never raises: a dead C++ object in the registry is silently skipped
class _BrokenPage:
    @property
    def widget(self):
        raise RuntimeError("Internal C++ object already deleted")

pages.append(_BrokenPage())
try:
    n = hub.broadcast(b"z", source_widget=w_a)
    check("a dead C++ object in the registry: the broadcast does not raise, the others receive",
          n == 1 and t_b.channel.sent[-1] == b"z")
except Exception as e:  # noqa: BLE001
    check("a dead C++ object in the registry: the broadcast does not raise, the others receive", False, repr(e))

# _thread_alive — liveness for the broadcast (task 4)
check("_thread_alive: an open channel → True", _thread_alive(t_a) is True)
t_dead = _FakeThread("h9", "u", 22)
t_dead.channel.closed = True
check("_thread_alive: a closed channel → False", _thread_alive(t_dead) is False)


class _StoppedThread:
    def isRunning(self):
        return False

    def send_data(self, d):
        pass


check("_thread_alive: no channel + the thread is stopped → False", _thread_alive(_StoppedThread()) is False)


class _TestDouble:
    """The test double without channel/isRunning — it is counted as live (its send_data is safe)."""

    def __init__(self):
        self.sent = []

    def send_data(self, d):
        self.sent.append(d)


check("_thread_alive: the test double (without channel/isRunning) → True", _thread_alive(_TestDouble()) is True)

n_seen = len(seen)   # [True, False, True] — switching to True before the broadcast also notified
hub.reset()
check("reset: the mode is off, no registry",
      hub.active is False and hub.session_provider is None)
hub.set_active(True)
check("after the reset: the listeners are cleared (a state change without the notifications)",
      len(seen) == n_seen and hub.active is True)


# ════════════════════════════════════════════════════════
# 2. Enabling the mode via MainWindow (the "View" QAction + UI)
# ════════════════════════════════════════════════════════
print("== 2. MainWindow: enable mode + UI ==")

_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeThread   # all the sessions in this file — on the fake

hub_app = MW._multi_input_mod.get_hub()   # the process singleton (the same one as in the widgets)
hub_app.reset()   # a fresh state; the window below will re-register the provider+listener

mw = MW.MainWindow()
mw._autosave_timer.stop()
mw.show()
app.processEvents()

check("the window holds the hub singleton + the provider — the registry of the sessions",
      mw._multi_hub is hub_app and mw._multi_hub.session_provider is not None)
check("before the enable the mode is off: the plaque is hidden, no F12 shortcut",
      hub_app.active is False and mw._multi_plaque.isHidden()
      and mw.act_multi_input.shortcut() == QKeySequence())

nodes = []
wins = {}
for i, alias in enumerate(("alpha", "beta", "gamma")):
    node = mw.scene.add_server(
        ServerData(id=f"mi-{alias}", alias=alias, host=f"10.98.{i}.1", user="root"))
    wins[alias] = mw._spawn_terminal_window(node)
    nodes.append(node)
    app.processEvents()

check("3 sessions in the registry (the window mode: a window per node)",
      len(mw._terminal_windows) == 3
      and all(isinstance(s, TerminalSessionPage) for s in mw._terminal_windows),
      f"registry={len(mw._terminal_windows)}")

mw._toggle_multi_input(True)   # the checkable QAction path (triggered passes the state)

check("the mode is on (the state of the hub)", hub_app.active is True)
check("the QAction: the checkmark + the F12 shortcut (the ApplicationShortcut — it catches the key wherever the focus is)",
      mw.act_multi_input.isChecked() is True
      and mw.act_multi_input.shortcut() == QKeySequence("F12")
      and mw.act_multi_input.shortcutContext() == Qt.ShortcutContext.ApplicationShortcut)
check("the status-bar plaque is visible + the counter 'MULTI: 3 sessions'",
      mw._multi_plaque.isHidden() is False
      and mw._multi_label.text() == i18n.t("terminal.multi_status", count=3),
      repr(mw._multi_label.text()))
check("the exit button on the plaque is wired and translated (the tooltip)",
      mw._multi_exit_btn.toolTip() == i18n.t("terminal.multi_exit_button"))
win_a = wins["alpha"]
check("the tab's badge 'MULTI · <alias>'",
      win_a.session_tabs.tabText(0) == i18n.t("terminal.multi_tab_badge", alias="alpha"),
      repr(win_a.session_tabs.tabText(0)))
check("the frame of the QTabWidget: the objectName selector + the QSS (amber)",
      win_a.session_tabs.objectName() == MULTI_FRAME_OBJECT_NAME
      and "border" in win_a.session_tabs.styleSheet())
check("the prefix of the window's title, terminal.multi_title_prefix",
      win_a.windowTitle().startswith(i18n.t("terminal.multi_title_prefix")),
      repr(win_a.windowTitle()))
check("the status message, status.multi_enabled",
      mw.statusBar().currentMessage() == i18n.t("status.multi_enabled"),
      repr(mw.statusBar().currentMessage()))


# ════════════════════════════════════════════════════════
# 3. Broadcast at the single input point (task 1)
# ════════════════════════════════════════════════════════
print("== 3. broadcast at the single input point ==")

page_a = wins["alpha"].page
w_a = page_a.widget
threads = {alias: wins[alias].page.terminal_thread for alias in wins}


def clear_sent():
    for t in threads.values():
        t.channel.sent.clear()


clear_sent()
w_a.keyPressEvent(key_event(Qt.Key.Key_A, "a"))
check("a key in the active session → the same bytes into ALL the other threads",
      threads["beta"].channel.sent == [b"a"] and threads["gamma"].channel.sent == [b"a"],
      f"beta={threads['beta'].channel.sent!r} gamma={threads['gamma'].channel.sent!r}")
check("the source receives exactly ONCE (no echo: the bytes from the keyboard, not from the output)",
      threads["alpha"].channel.sent == [b"a"], repr(threads["alpha"].channel.sent))

# the service keys go through the same point — Return is executed everywhere
clear_sent()
w_a.keyPressEvent(key_event(Qt.Key.Key_Return, "\r"))
check("the Return is duplicated (the Enter is executed everywhere)",
      threads["alpha"].channel.sent == [b"\r"] and threads["beta"].channel.sent == [b"\r"]
      and threads["gamma"].channel.sent == [b"\r"])

# the mode is off → the v1.2.2 behaviour: the input only into the active session
hub_app.set_active(False)
clear_sent()
w_a.keyPressEvent(key_event(Qt.Key.Key_B, "b"))
check("the mode is off: no duplicates (the input only into the active session)",
      threads["alpha"].channel.sent == [b"b"]
      and threads["beta"].channel.sent == [] and threads["gamma"].channel.sent == [])
check("the exit from the mode reset the UI: the plaque is hidden, the badge / the frame / the title are back to the originals",
      mw._multi_plaque.isHidden() is True
      and win_a.session_tabs.tabText(0) == "alpha"
      and win_a.session_tabs.styleSheet() == ""
      and win_a.session_tabs.objectName() == ""
      and not win_a.windowTitle().startswith(i18n.t("terminal.multi_title_prefix")),
      f"title={win_a.windowTitle()!r} tab={win_a.session_tabs.tabText(0)!r}")


# ════════════════════════════════════════════════════════
# 4. F12 exit (task 3): not Esc — Esc goes to the shell as \\x1b
# ════════════════════════════════════════════════════════
print("== 4. F12 exit ==")

mw._toggle_multi_input(True)
clear_sent()
w_a.keyPressEvent(key_event(Qt.Key.Key_F12, ""))
check("F12 in the mode: it does NOT reach the shell (the RC2 mapping \\x1b[24~ is suspended)",
      all(t.channel.sent == [] for t in threads.values()),
      f"sent={[t.channel.sent for t in threads.values()]}")
check("F12 turns the mode off", hub_app.active is False)
check("the QAction: the checkmark is removed, the F12 shortcut is removed (the key is free)",
      mw.act_multi_input.isChecked() is False
      and mw.act_multi_input.shortcut() == QKeySequence())

clear_sent()
w_a.keyPressEvent(key_event(Qt.Key.Key_F12, ""))
check("F12 outside the mode: the RC2 mapping is restored (\\x1b[24~ in the shell)",
      threads["alpha"].channel.sent == [b"\x1b[24~"], repr(threads["alpha"].channel.sent))
check("outside the mode there are no duplicates", threads["beta"].channel.sent == [] and threads["gamma"].channel.sent == [])

# Esc — NOT an exit: in the mode it is ordinary input (\\x1b), duplicated like everything else
mw._toggle_multi_input(True)
clear_sent()
w_a.keyPressEvent(key_event(Qt.Key.Key_Escape, ""))
check("Esc in the mode: it is not the exit — it goes to the shell as \\x1b and is duplicated into all the sessions",
      hub_app.active is True and threads["alpha"].channel.sent == [b"\x1b"]
      and threads["beta"].channel.sent == [b"\x1b"] and threads["gamma"].channel.sent == [b"\x1b"],
      f"sent={[t.channel.sent for t in threads.values()]}")
mw._toggle_multi_input(False)


# ════════════════════════════════════════════════════════
# 5. Ctrl+V (bracketed paste) in multi mode is also duplicated (task 4)
# ════════════════════════════════════════════════════════
print("== 5. Ctrl+V bracketed paste broadcast ==")

mw._toggle_multi_input(True)
app.clipboard().setText("line1\nline2")
clear_sent()
w_a.keyPressEvent(key_event(Qt.Key.Key_V, "", Qt.KeyboardModifier.ControlModifier))
expected = b"\x1b[200~" + "line1\nline2".encode("utf-8") + b"\x1b[201~"
check("Ctrl+V in the multi mode: a single bracketed-paste block into ALL the threads",
      threads["alpha"].channel.sent == [expected]
      and threads["beta"].channel.sent == [expected]
      and threads["gamma"].channel.sent == [expected],
      f"alpha={threads['alpha'].channel.sent!r}")
mw._toggle_multi_input(False)


# ════════════════════════════════════════════════════════
# 6. A dead session: the registry via the standard path, broadcast without breakage (task 4)
# ════════════════════════════════════════════════════════
print("== 6. dead session ==")

mw._toggle_multi_input(True)
page_b = wins["beta"].page
win_b = wins["beta"]
win_b.close()   # WA_DeleteOnClose: destroyed → _forget_terminal_window (the standard path)
app.processEvents()

check("the closed session is removed from the registry by the standard path",
      len(mw._terminal_windows) == 2 and all(s is not page_b for s in mw._terminal_windows),
      f"registry={len(mw._terminal_windows)}")
check("the green dot of the dead node is off (all the node's sessions are closed)",
      dot_color(nodes[1]) != "#22c55e", dot_color(nodes[1]))
check("the plaque's counter is updated: 2 sessions",
      mw._multi_label.text() == i18n.t("terminal.multi_status", count=2),
      repr(mw._multi_label.text()))

clear_sent()
w_a.keyPressEvent(key_event(Qt.Key.Key_C, "c"))
check("the broadcast continues into the remaining ones (the dead session does not break the mode)",
      threads["gamma"].channel.sent == [b"c"] and threads["alpha"].channel.sent == [b"c"],
      f"gamma={threads['gamma'].channel.sent!r}")

# a dead thread (the channel is closed) in the registry — the bytes do not go into it
t_g = threads["gamma"]
t_g.channel.closed = True   # imitating error → close without closing the window
clear_sent()
w_a.keyPressEvent(key_event(Qt.Key.Key_D, "d"))
check("a dead thread (the channel closed) receives no bytes",
      t_g.channel.sent == [] and threads["alpha"].channel.sent == [b"d"],
      f"gamma={t_g.channel.sent!r}")
mw._toggle_multi_input(False)


# ════════════════════════════════════════════════════════
# 7. The test seam: an explicit multi_hub in the TerminalWidget constructor
# ════════════════════════════════════════════════════════
print("== 7. explicit multi_hub seam (isolation) ==")

iso = MultiInputHub()   # an isolated hub — not the app singleton
t_iso_other = _FakeThread("h-iso", "u", 22)
tw = TerminalWidget(TerminalScreen(columns=120, lines=32), _FakeThread("h-src", "u", 22),
                    multi_hub=iso)
iso.set_session_provider(lambda: [_Page(t_iso_other, object())])
iso.set_active(True)
tw.keyPressEvent(key_event(Qt.Key.Key_Q, "q"))
check("an explicit multi_hub: the broadcast through its OWN hub", t_iso_other.channel.sent == [b"q"],
      repr(t_iso_other.channel.sent))
check("the application's singleton is not touched (the isolation)", hub_app.active is False)

# F12 on a widget with an explicit hub — exiting ITS mode (not the app's)
t_iso_other.channel.sent.clear()
tw.keyPressEvent(key_event(Qt.Key.Key_F12, ""))
check("F12: the exit from the explicit hub's mode, the bytes did not go",
      iso.active is False and t_iso_other.channel.sent == [])


# ════════════════════════════════════════════════════════
# 8. i18n parity + release state
# ════════════════════════════════════════════════════════
print("== 8. i18n parity + release state ==")

MULTI_KEYS = (
    "terminal.multi_status",
    "terminal.multi_exit_button",
    "terminal.multi_tab_badge",
    "terminal.multi_title_prefix",
    "view.multi_input",
    "status.multi_enabled",
    "status.multi_disabled",
)
langs = load_i18n_langs(ROOT)
check("v1.2.3: the 7 new keys are present and non-empty in en/ru/zh",
      all(k in langs[c] and str(langs[c][k]).strip() for c in ("en", "ru", "zh") for k in MULTI_KEYS))
check("the placeholders are formatted ({count}/{alias})",
      i18n.t("terminal.multi_status", count=5) == "MULTI: 5 sessions"
      and "{alias}" not in i18n.t("terminal.multi_tab_badge", alias="x"))
check_i18n_parity(langs)   # v1.2.3: +7 keys (404 → 411)
check_release_state(ROOT)

# ── the cleanup: the application exit — the mode is switched off, the provider is detached ──────
try:
    mw.close()
except Exception:
    pass
app.processEvents()
check("the shutdown of the MainWindow: the mode is off, the provider is detached",
      hub_app.active is False and hub_app.session_provider is None)

ST.SSHTerminalThread = _orig_thread_cls
finish()
