# -*- coding: utf-8 -*-
"""v1.2.1 — Multiple SSH sessions as tabs in one terminal window (ROADMAP v1.2.1).

The thematic test of the release v1.2.1 (the "new thematic file" convention): offscreen,
ALL without the network — the fake threads with the same API as SSHTerminalThread (the test seam
ST.SSHTerminalThread).

§1 The window structure: SSHTerminalWindow receives the QTabWidget of the pages (the central
   widget session_tabs), the closable tabs; the title of the tab — the alias of the node, the tooltip —
   terminal.tab_close_tooltip; the WA_DeleteOnClose/the title are kept; the compat attributes —
   the live references to the ACTIVE tab (win.page = the current tab).

§2 A new session = a new tab (the existing "connect to the node" path):
   MainWindow._spawn_terminal_window for the already open node → the same window + the second tab
   (the status message terminal.session_new_tab); another node — a new window.

§3 The tab close = the existing cleanup logic on the page: the "ask" gate confirm_close
   → the single teardown shutdown (the thread is stopped, _shut_down); the close of one tab does NOT
   affect the neighbor (the session lives and types); the close of the LAST tab closes
   the window (the WA_DeleteOnClose E2E); the cross on the tab (tabCloseRequested) — the same path.

§4 The error path in the tabbed window: the error_signal on one tab → QMessageBox.critical +
   only THIS tab is closed; the neighboring session lives and types.

§5 The limit "4 own terminals" (terminal_max_open) is counted by SESSIONS in all the windows:
   2 tabs (one window) + 1 session (another window) = the limit; Cancel → None, Close →
   the oldest session (_force_close) — its tab is closed, and the window with the neighboring session lives.

§6 The "status bar" bridge — only the active tab: the messages of the inactive tabs do not reach
   the status bar; on the tab switch the bridge reconnects; the SFTP progress bar follows
   the state of the active tab.

§7 The i18n parity (400 = 398 + 2 terminal.*) + the release state (the pin _common.py).

Run:  python tests/test_terminal_tabs.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys

from _common import (bootstrap, check, finish, wait_until, load_i18n_langs, check_i18n_parity,
                     check_release_state, cfg_path, write_cfg, clear_cfg)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QTabWidget, QSplitter

app = QApplication(sys.argv)

import i18n
import modules.ssh_terminal as ST
from modules.terminal_page import TerminalSessionPage
from models.server import ServerData
import ui.main_window as MW


# ════════════════════════════════════════════════════════════
# The harness: fake threads (the same API as SSHTerminalThread) — _fakes.py
# ════════════════════════════════════════════════════════════

from _fakes import (FakeSSHThread as _FakeThread, BlockingFakeSSHThread as _BlockingThread,
                    QuestionStub)
def alive(w):
    """Is the C++ object alive (WA_DeleteOnClose: after the accept — already destroyed)."""
    try:
        w.windowTitle()
        return True
    except RuntimeError:  # Internal C++ object already deleted
        return False


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeThread   # all the pages/windows in this file — on the fake

_windows = []


def make_window(alias, host="10.98.2.1", password="pw"):
    """The terminal window with the fake thread (one tab)."""
    w = ST.SSHTerminalWindow(
        ServerData(id=f"tt-{alias}", alias=alias, host=host, user="root"),
        None, password=password)
    _windows.append(w)
    app.processEvents()
    return w


def dot_color(node):
    return node._ssh_status.brush().color().name()


# ════════════════════════════════════════════════════════════
# 1. Window structure: a QTabWidget of session pages
# ════════════════════════════════════════════════════════════
print("== 1. window structure: QTabWidget of sessions ==")

clear_cfg()
w1 = make_window("struct")
check("the window: WA_DeleteOnClose is kept",
      bool(w1.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)) is True)
check("the window: the title is terminal.window_title (alias+host)",
      "struct" in w1.windowTitle() and "10.98.2.1" in w1.windowTitle(), w1.windowTitle())
# v1.3: the central widget — QSplitter [cmdlib_panel | session_tabs] (the "Terminal macros" panel)
# v1.3.3.5: the right member is the VERTICAL splitter [session_tabs | split_host] (the terminal split)
check("the window: the central widget is a QSplitter [cmdlib_panel | QSplitter(session_tabs | split_host)]",
      isinstance(w1.centralWidget(), QSplitter)
      and w1.cmdlib_panel is w1.centralWidget().widget(0)
      and w1._v_splitter is w1.centralWidget().widget(1)
      and w1.session_tabs is w1._v_splitter.widget(0))
check("the window: the tabs are closable (the cross on the tab)",
      w1.session_tabs.tabsClosable() is True)
check("the window: the first tab is a TerminalSessionPage (the v1.2 compat: win.page)",
      isinstance(w1.session_tabs.widget(0), TerminalSessionPage)
      and w1.session_tabs.widget(0) is w1.page)
check("the tab title is the node alias", w1.session_tabs.tabText(0) == "struct",
      repr(w1.session_tabs.tabText(0)))
check("the tab tooltip is terminal.tab_close_tooltip",
      w1.session_tabs.tabToolTip(0) == i18n.t("terminal.tab_close_tooltip"),
      repr(w1.session_tabs.tabToolTip(0)))
p1 = w1.page
check("the page is bound to the host (set_host_window)", p1._host_window is w1)
check("compat: win.widget/tscreen/terminal_thread — live references to the active tab",
      w1.widget is w1.page.widget and w1.tscreen is w1.page.tscreen
      and w1.terminal_thread is w1.page.terminal_thread)
check("compat: win.tabs/sftp_tab/status_label — live references (the session's inner tabs)",
      w1.tabs is w1.page.tabs and w1.sftp_tab is w1.page.sftp_tab
      and w1.status_label is w1.page.status_label)

# add_session: a second tab of the same node — active, the bridge switched
p2 = w1.add_session(
    ServerData(id="tt-struct-b", alias="struct", host="10.98.2.1", user="root"), password="pw")
app.processEvents()
check("add_session: the second tab is added and became active (Qt: addTab does not activate)",
      w1.session_tabs.count() == 2 and w1.session_tabs.currentWidget() is p2)
check("add_session: the second tab's title is the node alias",
      w1.session_tabs.tabText(1) == "struct")
check("compat: win.page — now the ACTIVE tab", w1.page is p2)

# ── closing the non-LAST tab does not close the window; the last tab → WA_DeleteOnClose ──
w1.close_page(w1.session_tabs.widget(0))   # struct (tab 0) — the neighbour p2 is alive
app.processEvents()
check("close_page: closing a NON-last tab leaves the window with the neighbour tab",
      alive(w1) and w1.session_tabs.count() == 1 and w1.session_tabs.widget(0) is p2,
      f"tabs={w1.session_tabs.count() if alive(w1) else '?'}")
w1.close_page(p2)   # the last tab → the window closes entirely
wait_until(lambda: not alive(w1), timeout_ms=4000)
check("close_page: closing the LAST tab destroyed the window (WA_DeleteOnClose)",
      not alive(w1))


# ════════════════════════════════════════════════════════════
# 2. A new session = a new tab (the existing "connect to node" path)
# ════════════════════════════════════════════════════════════
print("== 2. new session = new tab (existing connect path) ==")

mw = MW.MainWindow()
mw.show()
app.processEvents()

node_a = mw.scene.add_server(
    ServerData(id="tt-a", alias="alpha", host="10.98.3.1", user="root"))
win_a1 = mw._spawn_terminal_window(node_a)
check("the first connection: a new window with one tab (the v1.2 behavior)",
      win_a1 is not None and win_a1.session_tabs.count() == 1
      and len(mw._terminal_windows) == 1,
      f"registry={len(mw._terminal_windows)}")

win_a2 = mw._spawn_terminal_window(node_a)
app.processEvents()
check("the second connection to the same node — a new tab in the SAME window (v1.2.1)",
      win_a2 is win_a1 and win_a1.session_tabs.count() == 2,
      f"tabs={win_a1.session_tabs.count() if alive(win_a1) else '?'}")
check("the registry stores SESSIONS (TerminalSessionPage), not windows",
      len(mw._terminal_windows) == 2
      and all(isinstance(s, TerminalSessionPage) for s in mw._terminal_windows)
      and all(s is not win_a1 and s is not win_a2 for s in mw._terminal_windows),
      f"registry={[type(s).__name__ for s in mw._terminal_windows]}")
check("the tab titles are the node alias (both tabs)",
      win_a1.session_tabs.tabText(0) == "alpha" and win_a1.session_tabs.tabText(1) == "alpha",
      f"{win_a1.session_tabs.tabText(0)!r}/{win_a1.session_tabs.tabText(1)!r}")
check("the node's green dot is lit (2 active sessions)", dot_color(node_a) == "#22c55e",
      dot_color(node_a))
check("the status message: terminal.session_new_tab (the alias in the text)",
      mw.statusBar().currentMessage() == i18n.t("terminal.session_new_tab", alias="alpha"),
      repr(mw.statusBar().currentMessage()))

node_b = mw.scene.add_server(
    ServerData(id="tt-b", alias="beta", host="10.98.3.2", user="root"))
win_b = mw._spawn_terminal_window(node_b)
app.processEvents()
check("another node — a NEW window (not a tab in a foreign window)",
      win_b is not None and win_b is not win_a1 and win_b.session_tabs.count() == 1
      and len(mw._terminal_windows) == 3,
      f"registry={len(mw._terminal_windows)}")


# ════════════════════════════════════════════════════════════
# 3. Closing a tab = the existing cleanup logic on the page
# ════════════════════════════════════════════════════════════
print("== 3. closing a tab = existing page cleanup ==")

page_a1 = win_a1.session_tabs.widget(0)
page_a2 = win_a1.session_tabs.widget(1)

# ── closing one tab does not affect the neighbor ─────────────────────────────
win_a1.close_page(page_a1)
wait_until(lambda: len(mw._terminal_windows) == 2, timeout_ms=4000)
app.processEvents()
check("one tab is closed → the registry has 2 (the page's destroyed signal)",
      len(mw._terminal_windows) == 2 and not alive(page_a1),
      f"registry={len(mw._terminal_windows)}")
check("the window is alive with the neighbour tab (not destroyed)",
      alive(win_a1) and win_a1.session_tabs.count() == 1
      and win_a1.session_tabs.widget(0) is page_a2)
check("the closed session: the thread is stopped + the single shutdown",
      page_a1.terminal_thread.stop_calls >= 1 and page_a1._shut_down is True,
      f"stop={page_a1.terminal_thread.stop_calls} shut_down={page_a1._shut_down}")
check("the green dot is lit while the node's second session is alive", dot_color(node_a) == "#22c55e",
      dot_color(node_a))
check("the neighbour tab is untouched: the session is not shut down", page_a2._shut_down is False)
page_a2.terminal_thread.output_signal.emit(b"still alive\r\n")
app.processEvents()
check("the neighbour tab is untouched: the output still renders on the canvas",
      "still alive" in page_a2.widget.visible_text(),
      repr(page_a2.widget.visible_text())[:80])

# ── the last tab closes the window (the WA_DeleteOnClose E2E) ──────────────────────
win_a1.close_page(win_a1.session_tabs.widget(0))
wait_until(lambda: len(mw._terminal_windows) == 1, timeout_ms=4000)
app.processEvents()
check("the last tab → the window is destroyed (WA_DeleteOnClose)", not alive(win_a1))
check("the green dot went out (all the node's sessions are closed)", dot_color(node_a) == "#64748b",
      dot_color(node_a))
check("_ssh_connected_nodes: the node id is reset after all the sessions",
      node_a.data.id not in mw._ssh_connected_nodes)

# ── the cross on the tab: tabCloseRequested → the same path ─────────────────────────
win_b.session_tabs.tabCloseRequested.emit(0)
wait_until(lambda: not alive(win_b), timeout_ms=4000)
app.processEvents()
check("the cross on the tab (tabCloseRequested): the last tab is closed → the window is destroyed",
      not alive(win_b) and len(mw._terminal_windows) == 0,
      f"registry={len(mw._terminal_windows)}")

# ── the "ask" gate on tab close: Cancel holds / Close closes ────────────
write_cfg({"terminal_close_behavior": "ask"})
ST.SSHTerminalThread = _BlockingThread
node_c = mw.scene.add_server(
    ServerData(id="tt-c", alias="gamma", host="10.98.3.3", user="root"))
win_c1 = mw._spawn_terminal_window(node_c)
mw._spawn_terminal_window(node_c)   # two tabs in one window (v1.2.1)
app.processEvents()
page_c1 = win_c1.session_tabs.widget(0)
page_c2 = win_c1.session_tabs.widget(1)
wait_until(lambda: page_c1.terminal_thread.isRunning(), timeout_ms=3000)

asked = []
_question = QuestionStub(QMessageBox.StandardButton.Cancel,
                         record=lambda title, text: asked.append(title)).install(ST)
try:
    asked.clear()
    win_c1.close_page(page_c1)   # "ask" + an active session → a confirmation
    app.processEvents()
    check("'ask' + Cancel on a tab close: the tab stays open",
          len(asked) == 1 and alive(win_c1) and win_c1.session_tabs.count() == 2
          and page_c1._shut_down is False, f"asked={asked}")

    _question.answer = QMessageBox.StandardButton.Close
    asked.clear()
    win_c1.close_page(page_c1)   # "ask" + Close → teardown of THIS tab ONLY
    wait_until(lambda: len(mw._terminal_windows) == 1, timeout_ms=4000)
    app.processEvents()
    check("'ask' + Close on a tab close: only this tab is closed (the neighbour is alive)",
          len(asked) == 1 and alive(win_c1) and win_c1.session_tabs.count() == 1
          and not alive(page_c1), f"asked={asked}")
finally:
    _question.restore()

# the "ask" section cleanup: release the blocked threads, close the remainder
page_c1.terminal_thread.release()
page_c2.terminal_thread.release()
wait_until(lambda: (not page_c1.terminal_thread.isRunning()
                    and not page_c2.terminal_thread.isRunning()), timeout_ms=8000)
ST.SSHTerminalThread = _FakeThread
clear_cfg()
if alive(win_c1):
    win_c1.close()   # the sessions are finished — no dialog; the last tab → the window
wait_until(lambda: len(mw._terminal_windows) == 0, timeout_ms=4000)
app.processEvents()
check("the ask-section cleanup: all the sessions are closed, the registry is empty",
      len(mw._terminal_windows) == 0, f"registry={len(mw._terminal_windows)}")


# ════════════════════════════════════════════════════════════
# 4. The error path in a tabbed window: only the tab with the error is closed
# ════════════════════════════════════════════════════════════
print("== 4. error path in a tabbed window ==")

clear_cfg()
node_d = mw.scene.add_server(
    ServerData(id="tt-d", alias="delta", host="10.98.3.4", user="root"))
win_d1 = mw._spawn_terminal_window(node_d)
mw._spawn_terminal_window(node_d)   # two tabs in one window
app.processEvents()
page_d1 = win_d1.session_tabs.widget(0)
page_d2 = win_d1.session_tabs.widget(1)

crit_calls = []
_orig_critical = ST.QMessageBox.critical
ST.QMessageBox.critical = staticmethod(lambda *a, **k: crit_calls.append(a))
try:
    page_d1.terminal_thread.error_signal.emit("boom-d")
    app.processEvents()
    check("error → QMessageBox.critical (the parent — the host window)",
          len(crit_calls) == 1 and crit_calls[0][0] is win_d1, str(crit_calls)[:120])
finally:
    ST.QMessageBox.critical = _orig_critical

wait_until(lambda: len(mw._terminal_windows) == 1, timeout_ms=4000)
app.processEvents()
check("error: ONLY the tab with the error is closed (the registry has 1)",
      len(mw._terminal_windows) == 1 and not alive(page_d1),
      f"registry={len(mw._terminal_windows)}")
check("error: the window is alive with the neighbour session",
      alive(win_d1) and win_d1.session_tabs.count() == 1
      and win_d1.session_tabs.widget(0) is page_d2)
check("error: the neighbour session is not shut down", page_d2._shut_down is False)
page_d2.terminal_thread.output_signal.emit(b"delta alive\r\n")
app.processEvents()
check("error: the neighbour tab still prints",
      "delta alive" in page_d2.widget.visible_text(),
      repr(page_d2.widget.visible_text())[:80])

win_d1.close_page(page_d2)   # the last tab → the window
wait_until(lambda: not alive(win_d1), timeout_ms=4000)
app.processEvents()
check("the error path: closing the last tab → the window is destroyed", not alive(win_d1))


# ════════════════════════════════════════════════════════════
# 5. The "own terminals" limit — by SESSIONS across all windows
# ════════════════════════════════════════════════════════════
print("== 5. limit counts sessions across all windows ==")

write_cfg({"terminal_max_open": 3})
node_e = mw.scene.add_server(
    ServerData(id="tt-e", alias="eps", host="10.98.3.5", user="root"))
win_e1 = mw._spawn_terminal_window(node_e)   # tab 1
mw._spawn_terminal_window(node_e)            # tab 2 (the same window)
node_f = mw.scene.add_server(
    ServerData(id="tt-f", alias="fio", host="10.98.3.6", user="root"))
win_f = mw._spawn_terminal_window(node_f)    # a new window, session 3
app.processEvents()
check("the limit: 3 sessions (2 tabs in one window + 1 in another)",
      len(mw._terminal_windows) == 3 and win_e1 is not None
      and win_e1.session_tabs.count() == 2 and win_f is not win_e1,
      f"registry={len(mw._terminal_windows)}")

asked5 = []
_limit_stub = QuestionStub(QMessageBox.StandardButton.Cancel,
                           record=lambda title, text: asked5.append(title)).install(MW)
try:
    node_g = mw.scene.add_server(
        ServerData(id="tt-g", alias="gma", host="10.98.3.7", user="root"))
    asked5.clear()
    w_cancel = mw._spawn_terminal_window(node_g)
    check("the limit (sessions across all the windows): Cancel → None, the registry is unchanged (3)",
          w_cancel is None and len(asked5) == 1 and len(mw._terminal_windows) == 3,
          f"asked={asked5} registry={len(mw._terminal_windows)}")

    _limit_stub.answer = QMessageBox.StandardButton.Close
    asked5.clear()
    oldest_sess = mw._terminal_windows[0]   # the first tab of the eps window
    node_h = mw.scene.add_server(
        ServerData(id="tt-h", alias="eta", host="10.98.3.8", user="root"))
    w_new = mw._spawn_terminal_window(node_h)
    check("the limit: Close → the dialog about the oldest session", len(asked5) == 1, str(asked5))
    check("the limit: _force_close is set on the oldest session (against a repeated 'ask')",
          getattr(oldest_sess, "_force_close", False) is True)
    wait_until(lambda: oldest_sess not in mw._terminal_windows, timeout_ms=4000)
    app.processEvents()
    check("the limit: the oldest session's tab is closed — its window stays alive with the neighbour (v1.2.1)",
          alive(win_e1) and win_e1.session_tabs.count() == 1
          and oldest_sess not in mw._terminal_windows,
          f"tabs={win_e1.session_tabs.count() if alive(win_e1) else '?'}")
    check("the limit: the registry is 3 again — the oldest is removed, the new session is in a new window",
          w_new is not None and len(mw._terminal_windows) == 3
          and mw._terminal_windows[-1] is w_new.page and w_new is not win_e1,
          f"registry={[type(s).__name__ for s in mw._terminal_windows]}")
finally:
    _limit_stub.restore()
clear_cfg()

# cleanup: close all the remaining windows (sessions)
for ww in (win_e1, win_f, w_new):
    if alive(ww):
        ww.close()
wait_until(lambda: len(mw._terminal_windows) == 0, timeout_ms=4000)
app.processEvents()
check("the limit-section cleanup: all the sessions are closed, the registry is empty",
      len(mw._terminal_windows) == 0, f"registry={len(mw._terminal_windows)}")


# ════════════════════════════════════════════════════════════
# 6. The "status bar" bridge — only the active tab
# ════════════════════════════════════════════════════════════
print("== 6. status bridge: active tab only ==")

clear_cfg()
node_i = mw.scene.add_server(
    ServerData(id="tt-i", alias="iota", host="10.98.3.9", user="root"))
win_i1 = mw._spawn_terminal_window(node_i)
mw._spawn_terminal_window(node_i)   # two tabs; the active one — the second (add_session)
app.processEvents()
page_i1 = win_i1.session_tabs.widget(0)
page_i2 = win_i1.session_tabs.widget(1)
check("the bridge: after add_session the NEW tab is active",
      win_i1.session_tabs.currentWidget() is page_i2)

page_i2.status_message.emit("iota-2", 0)
app.processEvents()
check("the bridge: the ACTIVE tab's message → the window's status bar",
      win_i1.statusBar().currentMessage() == "iota-2",
      repr(win_i1.statusBar().currentMessage()))

win_i1.session_tabs.setCurrentIndex(0)   # switching to the first tab
app.processEvents()
page_i2.status_message.emit("iota-2-late", 0)   # an inactive tab — not bridged
app.processEvents()
check("the bridge: an INACTIVE tab's message does not reach the status bar",
      win_i1.statusBar().currentMessage() == "iota-2",
      repr(win_i1.statusBar().currentMessage()))
page_i1.status_message.emit("iota-1", 0)
app.processEvents()
check("the bridge: after the switch — the active tab's message is in the status bar",
      win_i1.statusBar().currentMessage() == "iota-1",
      repr(win_i1.statusBar().currentMessage()))

# The SFTP progress bar follows the state of the active tab
page_i1.progress_busy.emit()
app.processEvents()
check("the bridge: progress_busy on the active tab → the bar is visible (indeterminate)",
      not win_i1._sftp_progress.isHidden() and win_i1._sftp_progress.maximum() == 0)
win_i1.session_tabs.setCurrentIndex(1)   # a tab with no transfers
app.processEvents()
check("the bridge: switching to a tab with no transfers → the bar is hidden",
      win_i1._sftp_progress.isHidden())

win_i1.close()   # both tabs (the default 'close' — no dialog)
wait_until(lambda: len(mw._terminal_windows) == 0, timeout_ms=4000)
app.processEvents()
check("the window with two tabs closed entirely, the registry is empty",
      len(mw._terminal_windows) == 0 and not alive(win_i1),
      f"registry={len(mw._terminal_windows)}")


# ════════════════════════════════════════════════════════════
# 7. i18n parity + release state
# ════════════════════════════════════════════════════════════
print("== 7. i18n parity + release state ==")

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)   # v1.2.1: +2 terminal.* keys (398 → 400)
for code in ("en", "ru", "zh"):
    check(f"i18n {code}: the new keys tab_close_tooltip/session_new_tab are not empty",
          bool(langs[code].get("terminal.tab_close_tooltip"))
          and bool(langs[code].get("terminal.session_new_tab")))
check_release_state(ROOT)

finish()
