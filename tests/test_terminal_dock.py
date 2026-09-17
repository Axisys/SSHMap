# -*- coding: utf-8 -*-
"""v1.2.2 — Terminals docked in the map window (terminal.mode: windows/tabs, ROADMAP v1.2.2).

The thematic test of the release v1.2.2 (the "new thematic file" convention): offscreen,
ALL without the network — the fake threads with the same API as SSHTerminalThread (the test seam
ST.SSHTerminalThread).

§1 The config key terminal_mode: no key → "windows" (the default, the current behavior);
   "tabs" / " TABS " (strip+lower) → "tabs"; a broken value/a foreign type (int) → the default
   (the validation of load_terminal_settings() by the pattern of the other keys).

§2 The structure of the dock + the spawn in the mode "tabs": MainWindow._spawn_terminal_window creates
   the QDockWidget "Terminals" (objectName terminals_dock, the title terminal.dock_title)
   with the QTabWidget of the TerminalSessionPage; the map stays the central widget
   (self.view is not touched); the second node — the second tab in the SAME dock (+ the status
   terminal.session_new_tab); the registry stores the SESSIONS.

§3 The apply without a restart: the mode switch by the config key — the new sessions go to
   the chosen mode, the open windows/dock live as is until the close (tabs→windows:
   a separate window; windows→tabs: the session in the dock, the old window lives).

§4 The cleanup in the dock — per page (v1.2): the tab close = the cleanup of the LOCAL page
   (the "ask" gate Cancel holds / Close closes only this tab; the neighbor lives and types);
   the close of the LAST tab → the dock is hidden (not destroyed); the green dot goes out
   when ALL the sessions of the node are closed; the cross on the tab — the same path.

§5 The status line of the dock — only the active tab + the auto-clear by the timeout (the token guard):
   the messages of the inactive tabs do not reach, the switch reconnects the bridge;
   the SFTP progress follows the active tab; timeout_ms>0 → the label is cleared, a
   newer message is not clobbered by the old timeout; the status bar of the MAP is not touched by the
   dock sessions.

§6 The tear-off of the dock into a window and back: setFloating(True) — a separate window (isWindow),
   the sessions type; setFloating(False) — back to the map, the state is unchanged.

§7 The shutdown of MainWindow: closeEvent closes ALL the sessions of the registry (the dock + the windows) —
   the threads are stopped, the registry is empty, the dock is hidden, the terminal window is destroyed.

§8 The limit terminal_max_open by the SESSIONS in all the containers: 1 window + 1 tab of the dock =
   the limit; Cancel → None; Close → the oldest one (_force_close) is closed in its own
   container, the new session goes to the chosen mode.

§9 The i18n parity (404 = 400 + 4: terminal.dock_title + settings.terminal.mode.*)
   + the release state (the pin _common.py).

Run:  python tests/test_terminal_dock.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys
import time

from _common import (bootstrap, check, finish, wait_until,
                     load_i18n_langs, check_i18n_parity, check_release_state)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QDockWidget, QTabWidget

app = QApplication(sys.argv)

import i18n
import modules.ssh_terminal as ST
from modules.terminal_page import TerminalSessionPage
from models.server import ServerData
import ui.main_window as MW


# ════════════════════════════════════════════════════════════
# The harness: fake threads (the same API as SSHTerminalThread) — _fakes.py
# ════════════════════════════════════════════════════════════

from _fakes import FakeSSHThread as _FakeThread, BlockingFakeSSHThread as _BlockingThread


def _cfg_path():
    return os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")


def write_config(d):
    """A merge write into config.json (the i18n.save_config semantics: the existing keys
    are preserved — changing one setting does not reset the others)."""
    p = _cfg_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    cur = {}
    if os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cur = data
        except (json.JSONDecodeError, OSError):
            pass
    cur.update(d)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cur, f)


def clear_config():
    try:
        os.remove(_cfg_path())
    except OSError:
        pass


def alive(w):
    """Is the C++ object alive (WA_DeleteOnClose: after the accept — already destroyed)."""
    try:
        w.windowTitle()
        return True
    except RuntimeError:  # Internal C++ object already deleted
        return False


def dot_color(node):
    return node._ssh_status.brush().color().name()


def spin(ms):
    """Process the events for ms (for the timer checks of the status bar)."""
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1000 < ms:
        app.processEvents()
        time.sleep(0.005)


def _inside(w, root):
    """Whether w is alive in the tree under root (the parentWidget chain)."""
    p = w.parentWidget()
    while p is not None:
        if p is root:
            return True
        p = p.parentWidget()
    return False


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeThread   # all the pages/windows in this file — on the fake


def make_main():
    """An offscreen MainWindow with a stopped autosave timer (determinism)."""
    w = MW.MainWindow()
    w._autosave_timer.stop()
    w.show()
    app.processEvents()
    return w


# ════════════════════════════════════════════════════════════
# 1. The terminal_mode config key — validation following the pattern of the other keys
# ════════════════════════════════════════════════════════════
print("== 1. terminal_mode config validation ==")

clear_config()
check("no key → the default 'windows' (the current behavior)",
      ST.load_terminal_settings()["mode"] == "windows")
write_config({"terminal_mode": "tabs"})
check("'tabs' → 'tabs'", ST.load_terminal_settings()["mode"] == "tabs")
write_config({"terminal_mode": " TABS "})
check("' TABS ' (strip+lower) → 'tabs'", ST.load_terminal_settings()["mode"] == "tabs")
write_config({"terminal_mode": "garbage"})
check("a broken value → the default 'windows'", ST.load_terminal_settings()["mode"] == "windows")
write_config({"terminal_mode": 123})
check("a foreign type (int) → the default 'windows'", ST.load_terminal_settings()["mode"] == "windows")
write_config({"terminal_mode": "tabs", "terminal_max_open": 7})
_ts = ST.load_terminal_settings()
check("the other keys are read in parallel (max_open=7, mode=tabs)",
      _ts["max_open"] == 7 and _ts["mode"] == "tabs")
clear_config()


# ════════════════════════════════════════════════════════════
# 2. The dock structure + spawning in "tabs" mode
# ════════════════════════════════════════════════════════════
print("== 2. dock structure + spawn in tabs mode ==")

write_config({"terminal_mode": "tabs"})
mw = make_main()
check("before the first session there is no dock (the lazy creation)",
      getattr(mw, "_terminals_dock", None) is None)

node_a = mw.scene.add_server(
    ServerData(id="td-a", alias="alpha", host="10.97.3.1", user="root"))
dock = mw._spawn_terminal_window(node_a)
app.processEvents()
check("the first session in the mode 'tabs' → the dock is created (QDockWidget)", isinstance(dock, QDockWidget))
check("the dock: the objectName terminals_dock", dock.objectName() == "terminals_dock")
check("the dock: the title terminal.dock_title",
      dock.windowTitle() == i18n.t("terminal.dock_title"), repr(dock.windowTitle()))
content = dock.content
check("the content of the dock: a QTabWidget of the sessions (session_tabs, 1 tab)",
      isinstance(content.session_tabs, QTabWidget) and content.session_tabs.count() == 1)
check("the content of the dock: the tabs are closable (the cross on the tab)",
      content.session_tabs.tabsClosable() is True)
page_a = content.session_tabs.widget(0)
check("the tab — a TerminalSessionPage; the title = the alias of the node; the tooltip terminal.tab_close_tooltip",
      isinstance(page_a, TerminalSessionPage) and content.session_tabs.tabText(0) == "alpha"
      and content.session_tabs.tabToolTip(0) == i18n.t("terminal.tab_close_tooltip"),
      repr(content.session_tabs.tabText(0)))
check("the page is bound to the host (the content of the dock): close_terminal → close_page",
      page_a._host_window is content)
check("the map stays the central widget: self.view is untouched, the dock — alongside",
      _inside(mw.view, mw.centralWidget()) and len(mw.findChildren(QDockWidget)) == 1)

node_b = mw.scene.add_server(
    ServerData(id="td-b", alias="beta", host="10.97.3.2", user="root"))
dock2 = mw._spawn_terminal_window(node_b)
app.processEvents()
check("the second node — the second tab in the SAME dock (not a new window)",
      dock2 is dock and content.session_tabs.count() == 2,
      f"tabs={content.session_tabs.count()}")
check("the registry stores the SESSIONS (TerminalSessionPage), not the containers",
      len(mw._terminal_windows) == 2
      and all(isinstance(s, TerminalSessionPage) for s in mw._terminal_windows),
      f"registry={[type(s).__name__ for s in mw._terminal_windows]}")
check("the green dot burns on both the nodes",
      dot_color(node_a) == "#22c55e" and dot_color(node_b) == "#22c55e",
      f"{dot_color(node_a)}/{dot_color(node_b)}")
check("the status message: terminal.session_new_tab (the join to the open container)",
      mw.statusBar().currentMessage() == i18n.t("terminal.session_new_tab", alias="beta"),
      repr(mw.statusBar().currentMessage()))


# ════════════════════════════════════════════════════════════
# 3. Application without a restart: new sessions — in the chosen mode
# ════════════════════════════════════════════════════════════
print("== 3. apply without restart ==")

page_b = content.session_tabs.widget(1)

# tabs → windows: a new session — a separate window; the dock sessions live as they are
write_config({"terminal_mode": "windows"})
node_c = mw.scene.add_server(
    ServerData(id="td-c", alias="gamma", host="10.97.3.3", user="root"))
win_c = mw._spawn_terminal_window(node_c)
app.processEvents()
check("tabs→windows: the new session — a separate window (the behavior v1.2.1)",
      win_c is not None and win_c is not dock and win_c.session_tabs.count() == 1,
      f"win={type(win_c).__name__ if win_c else None}")
check("tabs→windows: the dock sessions live as they are (not shut down)",
      page_a._shut_down is False and page_b._shut_down is False
      and content.session_tabs.count() == 2)
check("the registry: 3 sessions (2 in the dock + 1 in the window)", len(mw._terminal_windows) == 3,
      f"registry={len(mw._terminal_windows)}")

# windows → tabs: the session goes to the dock; the node's old window is NOT reused — it lives
write_config({"terminal_mode": "tabs"})
win_c2 = mw._spawn_terminal_window(node_c)   # the same node, but the mode is already "tabs"
app.processEvents()
check("windows→tabs: the new session — the tab in the dock (the old window is not reused)",
      win_c2 is dock and content.session_tabs.count() == 3,
      f"tabs={content.session_tabs.count()}")
check("windows→tabs: the old window of the node lives as it is with its tab",
      alive(win_c) and win_c.session_tabs.count() == 1)
check("the registry: 4 sessions (3 in the dock + 1 in the window)", len(mw._terminal_windows) == 4,
      f"registry={len(mw._terminal_windows)}")


# ════════════════════════════════════════════════════════════
# 4. Cleanup in the dock — per page (v1.2)
# ════════════════════════════════════════════════════════════
print("== 4. cleanup in the dock — per page ==")

# ── closing the non-last tab does not affect the neighbor ───────────────────────
content.close_page(content.session_tabs.widget(0))   # alpha (tab 0)
wait_until(lambda: len(mw._terminal_windows) == 3, timeout_ms=4000)
app.processEvents()
check("the tab in the dock is closed → the registry 3 (the destroyed-signal of the page)",
      len(mw._terminal_windows) == 3 and not alive(page_a),
      f"registry={len(mw._terminal_windows)}")
page_b2 = content.session_tabs.widget(0)   # now beta is first
check("the neighboring tab is untouched: the session is not shut down", page_b2._shut_down is False)
page_b2.terminal_thread.output_signal.emit(b"beta alive\r\n")
app.processEvents()
check("the neighboring tab is untouched: the output still renders on the canvas",
      "beta alive" in page_b2.widget.visible_text(),
      repr(page_b2.widget.visible_text())[:80])
check("the green dot of the closed node is off (all its sessions are closed)",
      dot_color(node_a) == "#64748b", dot_color(node_a))
check("the green dot of the node with the live session burns", dot_color(node_b) == "#22c55e",
      dot_color(node_b))

# ── closing the LAST tab hides the dock (does not destroy it) ──────────────────────
content.close_page(content.session_tabs.widget(0))   # beta
content.close_page(content.session_tabs.widget(0))   # gamma' (the second tab of node c)
wait_until(lambda: content.session_tabs.count() == 0, timeout_ms=4000)
app.processEvents()
check("the last tab → the dock HIDES (isHidden)", dock.isHidden())
check("the dock is not destroyed (the container outlives its sessions — no WA_DeleteOnClose)",
      alive(dock))
check("the registry after the close of all the dock tabs: the window-session remains",
      len(mw._terminal_windows) == 1, f"registry={len(mw._terminal_windows)}")

# ── a new session in the "tabs" mode: the hidden dock is shown again ─────────────
mw._spawn_terminal_window(node_b)   # beta → the dock (hidden after the last tab)
app.processEvents()
check("the new session: the hidden dock is shown again, the 1 tab",
      not dock.isHidden() and content.session_tabs.count() == 1)

# ── the cross on the tab: tabCloseRequested → the same path ─────────────────────────
content.session_tabs.tabCloseRequested.emit(0)
wait_until(lambda: len(mw._terminal_windows) == 1, timeout_ms=4000)
app.processEvents()
check("the cross on the tab (tabCloseRequested): the last tab is closed → the dock is hidden",
      dock.isHidden() and content.session_tabs.count() == 0,
      f"tabs={content.session_tabs.count()}")

# ── the "ask" gate in the dock: Cancel holds / Close closes only this tab ───────
write_config({"terminal_close_behavior": "ask"})
ST.SSHTerminalThread = _BlockingThread
node_d = mw.scene.add_server(
    ServerData(id="td-d", alias="delta", host="10.97.3.4", user="root"))
node_e = mw.scene.add_server(
    ServerData(id="td-e", alias="eps", host="10.97.3.5", user="root"))
mw._spawn_terminal_window(node_d)
mw._spawn_terminal_window(node_e)
app.processEvents()
page_d = content.session_tabs.widget(0)
page_e = content.session_tabs.widget(1)
wait_until(lambda: page_d.terminal_thread.isRunning(), timeout_ms=3000)

asked = []
_q_result = [QMessageBox.StandardButton.Cancel]
_orig_question = ST.QMessageBox.question


def _fake_question(*a, **k):
    asked.append(a[1] if len(a) > 1 else None)
    return _q_result[0]


ST.QMessageBox.question = staticmethod(_fake_question)
try:
    asked.clear()
    content.close_page(page_d)   # "ask" + an active session → a confirmation
    app.processEvents()
    check("the 'ask' + the Cancel on the close of the tab in the dock: the tab stays open",
          len(asked) == 1 and content.session_tabs.count() == 2
          and page_d._shut_down is False, f"asked={asked}")

    _q_result[0] = QMessageBox.StandardButton.Close
    asked.clear()
    content.close_page(page_d)   # "ask" + Close → teardown of THIS tab ONLY
    wait_until(lambda: content.session_tabs.count() == 1, timeout_ms=4000)
    app.processEvents()
    check("the 'ask' + the Close on the close of the tab in the dock: only this tab is closed (the neighbor lives)",
          len(asked) == 1 and content.session_tabs.count() == 1
          and not alive(page_d) and page_e._shut_down is False, f"asked={asked}")
finally:
    ST.QMessageBox.question = _orig_question

# the ask-section cleanup: release the blocked threads, close the remaining tabs
page_d.terminal_thread.release()
page_e.terminal_thread.release()
wait_until(lambda: (not page_d.terminal_thread.isRunning()
                    and not page_e.terminal_thread.isRunning()), timeout_ms=8000)
ST.SSHTerminalThread = _FakeThread
clear_config()
content.close_page(content.session_tabs.widget(0))   # beta
content.close_page(content.session_tabs.widget(0))   # eps
wait_until(lambda: len(mw._terminal_windows) == 1, timeout_ms=4000)
app.processEvents()
check("the cleanup of the ask section: the dock sessions are closed (the window of gamma remains)",
      len(mw._terminal_windows) == 1 and dock.isHidden(),
      f"registry={len(mw._terminal_windows)}")


# ════════════════════════════════════════════════════════════
# 5. The dock status line — only the active tab + timeouts
# ════════════════════════════════════════════════════════════
print("== 5. dock status strip: active tab only ==")

write_config({"terminal_mode": "tabs"})   # the "tabs" mode (the ask section ended on a clean config)
node_f = mw.scene.add_server(
    ServerData(id="td-f", alias="fio", host="10.97.3.6", user="root"))
node_g = mw.scene.add_server(
    ServerData(id="td-g", alias="gma", host="10.97.3.7", user="root"))
mw._spawn_terminal_window(node_f)
mw._spawn_terminal_window(node_g)
app.processEvents()
page_f = content.session_tabs.widget(0)
page_g = content.session_tabs.widget(1)
check("the bridge: after the add_session the NEW tab is active",
      content.session_tabs.currentWidget() is page_g)

mw.statusBar().showMessage("map-marker", 60000)   # the known map status-bar marker
page_g.status_message.emit("dock-g", 0)
app.processEvents()
check("the message of the ACTIVE tab → the status strip of the dock",
      content.status_label.text() == "dock-g", repr(content.status_label.text()))
check("the status bar of the MAP is not touched by the dock sessions (the isolation)",
      mw.statusBar().currentMessage() == "map-marker",
      repr(mw.statusBar().currentMessage()))

content.session_tabs.setCurrentIndex(0)   # switching to the first tab
app.processEvents()
page_g.status_message.emit("late-g", 0)   # an inactive tab — not bridged
app.processEvents()
check("the message of the INACTIVE tab does not reach the status strip",
      content.status_label.text() == "dock-g", repr(content.status_label.text()))
page_f.status_message.emit("dock-f", 0)
app.processEvents()
check("after the switch — the message of the active tab is in the strip",
      content.status_label.text() == "dock-f", repr(content.status_label.text()))

# timeout_ms>0 → auto-cleanup; the token guard: a newer message is not clobbered
page_f.status_message.emit("short", 250)
wait_until(lambda: content.status_label.text() == "", timeout_ms=2000)
check("timeout_ms>0: the label auto-clears", content.status_label.text() == "")
page_f.status_message.emit("a", 400)
app.processEvents()
page_f.status_message.emit("b", 0)   # a newer sticky message
spin(600)                            # the "a" timeout expired — but the label must keep "b"
check("the token-guard: the old timeout does not clobber the newer message",
      content.status_label.text() == "b", repr(content.status_label.text()))

# The SFTP progress bar follows the state of the active tab
page_f.progress_busy.emit()
app.processEvents()
check("the progress_busy on the active tab → the bar is visible (the indeterminate)",
      not content.sftp_progress.isHidden() and content.sftp_progress.maximum() == 0)
content.session_tabs.setCurrentIndex(1)   # a tab with no transfers
app.processEvents()
check("the switch to the tab without the transfers → the bar is hidden", content.sftp_progress.isHidden())

# cleanup: close both tabs + the gamma window (the registry is empty, the dock is hidden)
win_c.close()
content.close_page(page_f)
content.close_page(page_g)
wait_until(lambda: len(mw._terminal_windows) == 0, timeout_ms=4000)
app.processEvents()
check("the cleanup of the section: all the sessions are closed, the registry is empty, the dock is hidden",
      len(mw._terminal_windows) == 0 and dock.isHidden() and not alive(win_c),
      f"registry={len(mw._terminal_windows)}")


# ════════════════════════════════════════════════════════════
# 6. Floating the dock out to a window and back
# ════════════════════════════════════════════════════════════
print("== 6. detach dock to a window and back ==")

write_config({"terminal_mode": "tabs"})
node_h = mw.scene.add_server(
    ServerData(id="td-h", alias="eta", host="10.97.3.8", user="root"))
node_i = mw.scene.add_server(
    ServerData(id="td-i", alias="theta", host="10.97.3.9", user="root"))
mw._spawn_terminal_window(node_h)
mw._spawn_terminal_window(node_i)
app.processEvents()
check("the dock before the detach: not floating (embedded in the map)", not dock.isFloating())

dock.setFloating(True)
app.processEvents()
check("setFloating(True): the dock — a separate window (isWindow)",
      dock.isFloating() and dock.isWindow())
page_h = content.session_tabs.widget(0)
page_h.terminal_thread.output_signal.emit(b"floating line\r\n")
app.processEvents()
check("the session in the detached dock types (the canvas renders)",
      "floating line" in page_h.widget.visible_text(),
      repr(page_h.widget.visible_text())[:80])

dock.setFloating(False)
app.processEvents()
check("setFloating(False): back to the map (not floating, the dock is in the window of the map)",
      not dock.isFloating() and len(mw.findChildren(QDockWidget)) == 1)
check("the detach/the return: the state is not changed — the registry 2, the sessions live",
      len(mw._terminal_windows) == 2 and page_h._shut_down is False
      and content.session_tabs.count() == 2,
      f"registry={len(mw._terminal_windows)}")

# cleanup: close both tabs
content.close_page(content.session_tabs.widget(0))
content.close_page(content.session_tabs.widget(0))
wait_until(lambda: len(mw._terminal_windows) == 0, timeout_ms=4000)
app.processEvents()
check("the cleanup of the section: the registry is empty", len(mw._terminal_windows) == 0,
      f"registry={len(mw._terminal_windows)}")


# ════════════════════════════════════════════════════════════
# 7. The MainWindow shutdown: ALL sessions in the registry (dock + windows)
# ════════════════════════════════════════════════════════════
print("== 7. MainWindow shutdown: all sessions (dock + windows) ==")

clear_config()
mw2 = make_main()
write_config({"terminal_mode": "tabs"})
n1 = mw2.scene.add_server(
    ServerData(id="td-s1", alias="sig-1", host="10.97.4.1", user="root"))
d2 = mw2._spawn_terminal_window(n1)      # the dock tab
write_config({"terminal_mode": "windows"})
n2 = mw2.scene.add_server(
    ServerData(id="td-s2", alias="sig-2", host="10.97.4.2", user="root"))
w2 = mw2._spawn_terminal_window(n2)      # a separate window
app.processEvents()
page_s1 = d2.content.session_tabs.widget(0)
page_s2 = w2.page
check("before the shutdown: 2 sessions in different containers (the dock + the window)",
      len(mw2._terminal_windows) == 2 and page_s1 is not None and page_s2 is not None,
      f"registry={len(mw2._terminal_windows)}")

_ev = QCloseEvent()
mw2.closeEvent(_ev)
wait_until(lambda: len(mw2._terminal_windows) == 0, timeout_ms=8000)
app.processEvents()
check("the closeEvent: the event is accepted (no unsaved changes)", _ev.isAccepted())
check("the shutdown: the registry is empty — ALL the sessions are closed (the dock + the window)",
      len(mw2._terminal_windows) == 0, f"registry={len(mw2._terminal_windows)}")
check("the shutdown: the threads are stopped (the page.shutdown in both the containers)",
      page_s1.terminal_thread.stop_calls >= 1 and page_s2.terminal_thread.stop_calls >= 1
      and page_s1._shut_down is True and page_s2._shut_down is True)
check("the shutdown: the dock is hidden (all the tabs are closed per page)", d2.isHidden())
check("the shutdown: the terminal window is destroyed (WA_DeleteOnClose)", not alive(w2))
check("the shutdown: the green dots of the nodes are off",
      dot_color(n1) == "#64748b" and dot_color(n2) == "#64748b")


# ════════════════════════════════════════════════════════════
# 8. The terminal_max_open limit — by SESSIONS across all containers
# ════════════════════════════════════════════════════════════
print("== 8. limit counts sessions across containers ==")

clear_config()
mw3 = make_main()
write_config({"terminal_max_open": 2, "terminal_mode": "windows"})
n1 = mw3.scene.add_server(
    ServerData(id="td-l1", alias="lim-1", host="10.97.5.1", user="root"))
w1 = mw3._spawn_terminal_window(n1)      # the window, session 1
write_config({"terminal_mode": "tabs"})
n2 = mw3.scene.add_server(
    ServerData(id="td-l2", alias="lim-2", host="10.97.5.2", user="root"))
d3 = mw3._spawn_terminal_window(n2)      # the dock tab, session 2 → the limit (2)
app.processEvents()
check("the limit: 2 sessions in different containers (1 window + 1 tab of the dock)",
      len(mw3._terminal_windows) == 2 and d3 is not None
      and d3.content.session_tabs.count() == 1,
      f"registry={len(mw3._terminal_windows)}")

_limit_result = [QMessageBox.StandardButton.Cancel]
_orig_mw_question = MW.QMessageBox.question
asked8 = []


def _mw_fake_question(*a, **k):
    asked8.append(a[1] if len(a) > 1 else None)
    return _limit_result[0]


MW.QMessageBox.question = staticmethod(_mw_fake_question)
try:
    n3 = mw3.scene.add_server(
        ServerData(id="td-l3", alias="lim-3", host="10.97.5.3", user="root"))
    asked8.clear()
    w_cancel = mw3._spawn_terminal_window(n3)
    check("the limit (the sessions in all the containers): the Cancel → None, the registry is unchanged (2)",
          w_cancel is None and len(asked8) == 1 and len(mw3._terminal_windows) == 2,
          f"asked={asked8} registry={len(mw3._terminal_windows)}")

    _limit_result[0] = QMessageBox.StandardButton.Close
    asked8.clear()
    oldest_sess = mw3._terminal_windows[0]   # the window-session (created first)
    n4 = mw3.scene.add_server(
        ServerData(id="td-l4", alias="lim-4", host="10.97.5.4", user="root"))
    w_new = mw3._spawn_terminal_window(n4)
    check("the limit: the Close → the dialog about the oldest session", len(asked8) == 1, str(asked8))
    check("the limit: the _force_close is set on the oldest one (against the repeated 'ask')",
          getattr(oldest_sess, "_force_close", False) is True)
    wait_until(lambda: oldest_sess not in mw3._terminal_windows, timeout_ms=4000)
    app.processEvents()
    check("the limit: the oldest is closed in its OWN container — the window is destroyed (the last tab)",
          not alive(w1) and oldest_sess not in mw3._terminal_windows)
    check("the limit: the new session went to the chosen mode (the dock), the registry is 2 again",
          w_new is d3 and len(mw3._terminal_windows) == 2
          and d3.content.session_tabs.count() == 2,
          f"tabs={d3.content.session_tabs.count() if alive(d3) else '?'}")
finally:
    MW.QMessageBox.question = _orig_mw_question
clear_config()

# cleanup: close all mw3 sessions (the dock tabs; the window is already destroyed)
while d3.content.session_tabs.count() > 0:
    d3.content.close_page(d3.content.session_tabs.widget(0))
wait_until(lambda: len(mw3._terminal_windows) == 0, timeout_ms=4000)
app.processEvents()
check("the cleanup of the limit section: all the sessions are closed, the registry is empty",
      len(mw3._terminal_windows) == 0, f"registry={len(mw3._terminal_windows)}")


# ════════════════════════════════════════════════════════════
# 9. i18n parity + release state
# ════════════════════════════════════════════════════════════
print("== 9. i18n parity + release state ==")

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)   # v1.2.2: +4 keys (400 → 404)
for code in ("en", "ru", "zh"):
    check(f"i18n {code}: the new keys are not empty (dock_title/mode/*.windows/*.tabs)",
          all(langs[code].get(k, "").strip() for k in
              ("terminal.dock_title", "settings.terminal.mode",
               "settings.terminal.mode.windows", "settings.terminal.mode.tabs")))
check_release_state(ROOT)

finish()
