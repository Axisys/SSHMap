# -*- coding: utf-8 -*-
"""v1.3.3.5 — Terminal split: a second pane under the sessions (ROADMAP v1.3.3.5).

The topical test of the release v1.3.3.5 (the "new thematic file" convention): offscreen,
ALL without the network — the fake threads with the same API as SSHTerminalThread
(the test seam ST.SSHTerminalThread), a fake channel that records its own traffic.

§1 The layout and the action: the split is OFF by default (the single-pane look of
   v1.3.3.4 is preserved — the host is hidden and costs no geometry); the central widget
   is `[cmdlib_panel | QSplitter(Vertical)[session_tabs | split_host]]`; ONE checkable
   action (`terminal.split`) drives the toolbar button AND the window's context-menu item.
§2 The pane's birth: the action creates a REAL TerminalSessionPage — a DIFFERENT object
   with the same `server_data.id`, its own SSHTerminalThread, the same node credentials
   and NO Quick Launch command; the host is shown, the default ratio is ≈25%, the pane
   is not a tab, and it joins the MainWindow session registry with the split marker.
§3 Input isolation: a byte typed into one pane reaches only its own channel.
§4 The geometry rules: the divider drag becomes the ratio, a window resize keeps the
   proportion, the minimum-height floor keeps ≥ SPLIT_MIN_ROWS rows in the pane, and the
   pane's PTY resize goes through the debounce exactly once per settled geometry.
§5 Focus and the bridges: `win.page` and the status bar follow the FOCUSED pane, the
   command library sends to the focused pane, and multi-input marks the pane (frame on
   the host + badge on its inner Terminal tab) and broadcasts into it. **v1.4.7
   follow-up:** no session draws a status line and a single-tab page hides its tab
   strip, so the pane's live state is the SECOND text of the window's status bar
   (`Split Terminal  <state>`), shown with the pane and dropped when it closes.
§6 The registry rules (ROADMAP task 2): the terminal_max_open limit and
   `_find_terminal_window_for` ignore the pane, while the green dot and the multi-input
   provider count it.
§7 The teardown paths: turning the split off, the pane's own error path, the window
   close and the session-limit path all run the single idempotent `page.shutdown()`.
§8 Persistence: the split state and the ratio survive save→load (one merged geometry
   write), a broken value falls back to the default.
§9 The i18n (a language switch re-texts the new action) + the release state.

Run:  python tests/test_terminal_split.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys

from _common import (bootstrap, check, finish, wait_until, load_i18n_langs, check_i18n_parity,
                     check_release_state, cfg_path, write_cfg, clear_cfg, read_cfg)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QSplitter

app = QApplication(sys.argv)

import i18n
import modules.ssh_terminal as ST
import modules.multi_input as MI
from modules.terminal_page import TerminalSessionPage
from models.server import ServerData
import ui.main_window as MW


# ════════════════════════════════════════════════════════════
# The harness: fake threads (the same API as SSHTerminalThread) — _fakes.py
# ════════════════════════════════════════════════════════════

from _fakes import FakeSSHThread as _FakeThread, QuestionStub
def alive(w):
    """Is the C++ object alive (WA_DeleteOnClose: after the accept — already destroyed)."""
    try:
        w.windowTitle()
        return True
    except RuntimeError:  # Internal C++ object already deleted
        return False


def key_event(key, text="", mod=Qt.KeyboardModifier.NoModifier):
    return QKeyEvent(QKeyEvent.Type.KeyPress, int(key), mod, text)


def type_into(widget, key, text):
    """A real key press into a canvas (the single input point → its own send_data)."""
    app.sendEvent(widget, key_event(key, text))
    app.processEvents()


def dot_color(node):
    return node._ssh_status.brush().color().name()


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeThread   # all the pages/windows in this file — on the fake

clear_cfg()
mw = MW.MainWindow()
mw.show()
app.processEvents()


def new_node(alias, host):
    return mw.scene.add_server(
        ServerData(id=f"sp-{alias}", alias=alias, host=host, user="root"))


# ════════════════════════════════════════════════════════════
# 1. The layout and the action — the split is OFF by default
# ════════════════════════════════════════════════════════════
print("== 1. the layout and the action (split off by default) ==")

node_a = new_node("alpha", "10.90.0.1")
win_a = mw._spawn_terminal_window(node_a, password="pw")
app.processEvents()
top_a = win_a.session_tabs.widget(0)

check("the split is OFF by default: no pane, the host is hidden",
      win_a.split_pane is None and win_a._split_on is False and win_a.split_host.isHidden())
check("the central widget is [cmdlib_panel | QSplitter(Vertical)[session_tabs | split_host]]",
      isinstance(win_a.centralWidget(), QSplitter)
      and win_a.cmdlib_panel is win_a.centralWidget().widget(0)
      and win_a._v_splitter is win_a.centralWidget().widget(1)
      and win_a.session_tabs is win_a._v_splitter.widget(0)
      and win_a.split_host is win_a._v_splitter.widget(1))
check("the vertical splitter is NOT collapsible on either side (the divider cannot lose a pane)",
      win_a._v_splitter.isCollapsible(0) is False
      and win_a._v_splitter.isCollapsible(1) is False)
check("the single-pane look is preserved: the hidden host costs no geometry",
      win_a._v_splitter.sizes()[1] == 0 and win_a.session_tabs.minimumHeight() == 0,
      f"sizes={win_a._v_splitter.sizes()}")
check("ONE checkable action terminal.split drives the tab-bar BUTTON",
      win_a.act_split.isCheckable() and win_a.act_split.isChecked() is False
      and win_a.act_split.text() == i18n.t("terminal.split")
      and win_a.act_split.toolTip() == i18n.t("terminal.split_tooltip")
      and win_a.session_tabs.cornerWidget(Qt.Corner.TopRightCorner) is win_a.btn_split)
check("the button is a REAL QPushButton in the RIGHT corner (not a toolbar label)",
      isinstance(win_a.btn_split, QPushButton)
      and win_a.btn_split.isCheckable() and win_a.btn_split.isChecked() is False
      and win_a.btn_split.text() == i18n.t("terminal.split")
      and win_a.btn_split.toolTip() == i18n.t("terminal.split_tooltip")
      and win_a.session_tabs.cornerWidget(Qt.Corner.TopLeftCorner) is None)
check("... and the context-menu item is the SAME action (one action, two views)",
      win_a._build_context_menu().actions() == [win_a.act_split])
check("no keyboard shortcut is attached (deliberately not in this version)",
      win_a.act_split.shortcut().isEmpty())
check("the registry holds ONE session (no pane yet) and the node's dot is lit",
      len(mw._terminal_windows) == 1 and len(mw._limit_terminal_sessions()) == 1)


# ════════════════════════════════════════════════════════════
# 2. The action creates the pane (a REAL second session of the same node)
# ════════════════════════════════════════════════════════════
print("== 2. the action creates the pane ==")

win_a.btn_split.click()   # the real click path of the corner button (→ act_split → the slot)
app.processEvents()
pane_a = win_a.split_pane
app.processEvents()

check("the BUTTON opened the pane (the click goes through the one action)",
      isinstance(pane_a, TerminalSessionPage) and win_a.split_host.isHidden() is False
      and win_a.act_split.isChecked() is True and win_a.btn_split.isChecked() is True)
check("the default ratio is ≈25% of the height",
      abs(win_a._split_ratio - ST.SPLIT_RATIO_DEFAULT) < 0.06, f"ratio={win_a._split_ratio:.3f}")
_sizes_a = win_a._v_splitter.sizes()
check("the splitter really shows two panes with the bottom one smaller",
      0 < _sizes_a[1] < _sizes_a[0], f"sizes={_sizes_a}")
check("the pane is NOT a tab (session_tabs still holds the single tab)",
      win_a.session_tabs.count() == 1 and win_a.session_tabs.widget(0) is top_a)
check("the pane is a DIFFERENT page object with the SAME node",
      pane_a is not top_a and pane_a.server_data.id == node_a.data.id
      and pane_a.server_data is not None)
check("the pane has its OWN fake thread (a fresh SSHTerminalThread, a second channel)",
      isinstance(pane_a.terminal_thread, _FakeThread)
      and pane_a.terminal_thread is not top_a.terminal_thread
      and pane_a.terminal_thread.channel is not top_a.terminal_thread.channel)
check("the pane's channel carries the SAME node credentials",
      (pane_a.terminal_thread.host, pane_a.terminal_thread.user, pane_a.terminal_thread.port)
      == (top_a.terminal_thread.host, top_a.terminal_thread.user, top_a.terminal_thread.port)
      and pane_a.terminal_thread.password == "pw")
check("the Quick Launch command of the parent is NOT re-sent into the pane",
      pane_a._initial_command == "" and pane_a._initial_cmd_conn is None)
check("the pane is bound to its host and carries the split marker",
      pane_a._host_window is win_a and pane_a._is_split_pane is True
      and top_a._is_split_pane is False)
check("the pane joined the MainWindow session registry (green dot / multi-input)",
      len(mw._terminal_windows) == 2 and pane_a in mw._terminal_windows)
# ── v1.3.3.5-fix: the pane is a COMMAND LINE — no SFTP tab, no SFTP channel ──────
check("a TAB keeps its SFTP and History tabs (with_sftp=True is untouched)",
      top_a.sftp_tab is not None and top_a.history_tab is not None
      and top_a.tabs.count() == 3
      and top_a.tabs.widget(1) is top_a.sftp_tab
      and top_a.tabs.widget(2) is top_a.history_tab)
check("the PANE has NO SFTP tab: one tab (the canvas) and sftp_tab is None",
      pane_a.sftp_tab is None and pane_a.tabs.count() == 1
      and pane_a.tabs.widget(0) is pane_a.widget)
check("the pane never opens an SFTP channel, not even on demand",
      pane_a._ensure_sftp() is False and pane_a._sftp_worker is None)
check("the pane's layout minimum is driven by the CANVAS, not by the SFTP tree",
      win_a.split_host.minimumSizeHint().height() < top_a.minimumSizeHint().height() - 40,
      f"pane={win_a.split_host.minimumSizeHint().height()} "
      f"tab={top_a.minimumSizeHint().height()}")
# ── v1.4.7 follow-up: NO session draws a status line — the status bar is the surface ──
check("NEITHER surface draws a status line (the page keeps the label as hidden state)",
      pane_a.status_label.isHidden() is True and top_a.status_label.isHidden() is True
      and pane_a.status_label.parent() is pane_a
      and top_a.status_label.parent() is top_a
      and top_a.layout().indexOf(top_a.status_label) == -1
      and pane_a.layout().indexOf(pane_a.status_label) == -1)
check("the pane's tab strip is GONE (one tab — nothing to switch; the frame stays)",
      pane_a.tabs.tabBar().isHidden() is True and top_a.tabs.tabBar().isHidden() is False)
check("the pane's inner title is the plain `Terminal` (no live status on it)",
      pane_a.tabs.tabText(0) == i18n.t("sftp.tab_terminal"), repr(pane_a.tabs.tabText(0)))
pane_a.terminal_thread.status_signal.emit("SSH session opened")
app.processEvents()
check("a status from the pane's thread reaches the WINDOW's status bar, after the main line",
      win_a.split_status_text == "SSH session opened"
      and win_a._split_status_label.text()
      == f"{i18n.t('terminal.split')}  SSH session opened"
      and win_a._split_status_label.isHidden() is False,
      f"{win_a.split_status_text!r}/{win_a._split_status_label.text()!r}")
check("the pane's label follows as hidden STATE (the compatibility reader)",
      pane_a.status_label.text() == "SSH session opened"
      and pane_a.session_status == "SSH session opened")
check("the pane's status never lands on the tab title any more",
      pane_a.tabs.tabText(0) == i18n.t("sftp.tab_terminal"))
check("the space the missing status line gives back goes to the CANVAS (more rows)",
      pane_a.widget.height() >= pane_a.height() - win_a._v_splitter.handleWidth() - 50
      and pane_a._visible_grid()[1] >= ST.SPLIT_MIN_ROWS + 1,
      f"canvas={pane_a.widget.height()} pane={pane_a.height()} grid={pane_a._visible_grid()}")
check("the pane's grid is sane (no zero-row PTY)",
      pane_a._visible_grid()[0] >= 2 and pane_a._visible_grid()[1] >= 1,
      f"grid={pane_a._visible_grid()}")
pane_a.terminal_thread.output_signal.emit(b"pane-output\r\n")
app.processEvents()
check("the pane renders its own output independently of the top tab",
      "pane-output" in pane_a.widget.visible_text()
      and "pane-output" not in top_a.widget.visible_text())


# ════════════════════════════════════════════════════════════
# 3. Input isolation — the panes never share a channel
# ════════════════════════════════════════════════════════════
print("== 3. input isolation ==")

top_a.terminal_thread.channel.sent.clear()
pane_a.terminal_thread.channel.sent.clear()
type_into(top_a.widget, Qt.Key_A, "a")
check("a byte typed into the TOP pane reaches only its own channel",
      top_a.terminal_thread.channel.sent == [b"a"]
      and pane_a.terminal_thread.channel.sent == [],
      f"top={top_a.terminal_thread.channel.sent!r} pane={pane_a.terminal_thread.channel.sent!r}")

type_into(pane_a.widget, Qt.Key_B, "b")
check("a byte typed into the PANE reaches only its own channel",
      pane_a.terminal_thread.channel.sent == [b"b"]
      and top_a.terminal_thread.channel.sent == [b"a"],
      f"top={top_a.terminal_thread.channel.sent!r} pane={pane_a.terminal_thread.channel.sent!r}")

check("the pane's shell output does not leak into the top canvas",
      "pane-output" not in top_a.widget.visible_text())


# ════════════════════════════════════════════════════════════
# 4. The geometry rules (task 3a)
# ════════════════════════════════════════════════════════════
print("== 4. the geometry rules ==")

win_a.show()
app.processEvents()
vs = win_a._v_splitter
_total = sum(vs.sizes())
vs.setSizes([int(_total * 0.6), int(_total * 0.4)])
win_a._on_split_moved()   # setSizes() does not emit splitterMoved (a drag does)
check("the explicit drag of the divider becomes the remembered ratio",
      abs(win_a._split_ratio - 0.4) < 0.05, f"ratio={win_a._split_ratio:.3f}")

win_a.resize(900, 420)
app.processEvents()
_sizes = vs.sizes()
check("a window resize keeps the PROPORTION (a fraction of the height, not pixels)",
      abs(_sizes[1] / float(sum(_sizes)) - win_a._split_ratio) < 0.08,
      f"sizes={_sizes} ratio={win_a._split_ratio:.3f}")
check("the ratio itself is untouched by the resize",
      abs(win_a._split_ratio - 0.4) < 0.05, f"ratio={win_a._split_ratio:.3f}")

win_a.resize(700, 360)
app.processEvents()
_floor = win_a._split_min_height()
check("the minimum-height floor is derived from the canvas metrics, not from a magic number",
      _floor >= pane_a.widget.cell_size[1] * ST.SPLIT_MIN_ROWS,
      f"floor={_floor} row_h={pane_a.widget.cell_size[1]}")
check("the floor holds: the pane keeps at least SPLIT_MIN_ROWS rows of grid",
      pane_a._visible_grid()[1] >= ST.SPLIT_MIN_ROWS,
      f"rows={pane_a._visible_grid()[1]} floor={_floor} pane_h={win_a.split_host.height()}")
check("the top pane keeps its floor too (neither pane can be collapsed into unusability)",
      win_a.session_tabs.height() >= _floor,
      f"top={win_a.session_tabs.height()} floor={_floor}")

# ── the PTY resize of the pane: through the debounce, once per settled geometry ──
_pane_channel = pane_a.terminal_thread.channel
_pane_channel.resizes.clear()
pane_a._pending_pty = None
win_a.resize(820, 460)
app.processEvents()
wait_until(lambda: len(_pane_channel.resizes) >= 1, timeout_ms=4000)
app.processEvents()
check("the pane's PTY resize went through the page debounce (resize_pty called)",
      len(_pane_channel.resizes) == 1, f"resizes={_pane_channel.resizes!r}")
check("the PTY got the pane's REAL grid (cols, rows), not the 120×32 default",
      _pane_channel.resizes and _pane_channel.resizes[0] == (pane_a._last_cols, pane_a._last_rows)
      and _pane_channel.resizes[0][0] >= 2 and _pane_channel.resizes[0][1] >= 1,
      f"resizes={_pane_channel.resizes!r} grid={pane_a._last_cols}x{pane_a._last_rows}")
wait_until(lambda: False, timeout_ms=400)   # a quiet window: no repeat without a resize
app.processEvents()
check("a settled geometry does not resize the PTY again (the debounce fired exactly once)",
      len(_pane_channel.resizes) == 1, f"resizes={_pane_channel.resizes!r}")

win_a._split_ratio = ST.SPLIT_RATIO_DEFAULT
win_a._apply_split_sizes()
app.processEvents()


# ════════════════════════════════════════════════════════════
# 5. Focus and the bridges (task 6)
# ════════════════════════════════════════════════════════════
print("== 5. focus and the bridges ==")

win_a.raise_()
win_a.activateWindow()
QApplication.setActiveWindow(win_a)
app.processEvents()
pane_a.widget.setFocus()
app.processEvents()
check("the pane's canvas can hold the focus (the probe is meaningful)",
      QApplication.focusWidget() is pane_a.widget, type(QApplication.focusWidget()).__name__)
check("win.page follows the FOCUSED pane (the v1.2.1 active-session rule extended)",
      win_a.page is pane_a)
check("the status-bar bridge follows the focused pane",
      win_a._bridged_page is pane_a)
pane_a.status_message.emit("from-the-pane", 0)
app.processEvents()
check("a message of the FOCUSED pane reaches the window's status bar",
      win_a.statusBar().currentMessage() == "from-the-pane",
      repr(win_a.statusBar().currentMessage()))

top_a.widget.setFocus()
app.processEvents()
check("clicking back into the top canvas gives the bridge (and win.page) back to the tab",
      win_a.page is top_a and win_a._bridged_page is top_a)
top_a.status_message.emit("from-the-tab", 0)
app.processEvents()
check("... and the top tab's message is bridged again",
      win_a.statusBar().currentMessage() == "from-the-tab",
      repr(win_a.statusBar().currentMessage()))

# ── the command library targets the focused pane ────────────────────────────
pane_a.terminal_thread.channel.sent.clear()
top_a.terminal_thread.channel.sent.clear()
win_a.cmdlib_panel.send_entry({"id": "x", "name": "n", "command": "uptime",
                               "category": "", "enabled": True})
app.processEvents()
check("the command library sends a macro to the ACTIVE (top) session by default",
      top_a.terminal_thread.channel.sent == [b"uptime\n"]
      and pane_a.terminal_thread.channel.sent == [],
      f"top={top_a.terminal_thread.channel.sent!r} pane={pane_a.terminal_thread.channel.sent!r}")
pane_a.widget.setFocus()
app.processEvents()
pane_a.terminal_thread.channel.sent.clear()
top_a.terminal_thread.channel.sent.clear()
win_a.cmdlib_panel.send_entry({"id": "x", "name": "n", "command": "uptime",
                               "category": "", "enabled": True})
app.processEvents()
check("... and to the FOCUSED PANE once the user is in it (ROADMAP task 6)",
      pane_a.terminal_thread.channel.sent == [b"uptime\n"]
      and top_a.terminal_thread.channel.sent == [],
      f"top={top_a.terminal_thread.channel.sent!r} pane={pane_a.terminal_thread.channel.sent!r}")

# ── multi-input: the badge/frame reach the pane, the bytes reach the pane ────
mw._toggle_multi_input(True)
app.processEvents()
check("multi-input marks the pane: the badge is its inner title (hidden strip — the frame speaks)",
      pane_a.tabs.tabText(0) == i18n.t("terminal.multi_tab_badge", alias="alpha"),
      repr(pane_a.tabs.tabText(0)))
check("multi-input marks the pane: the frame on the pane's own host",
      win_a.split_host.objectName() == MI.MULTI_PANE_FRAME_OBJECT_NAME,
      win_a.split_host.objectName())
pane_a.terminal_thread.channel.sent.clear()
top_a.terminal_thread.channel.sent.clear()
type_into(top_a.widget, Qt.Key_X, "x")
check("multi-input broadcasts the typed byte INTO the pane",
      pane_a.terminal_thread.channel.sent == [b"x"]
      and top_a.terminal_thread.channel.sent == [b"x"],
      f"top={top_a.terminal_thread.channel.sent!r} pane={pane_a.terminal_thread.channel.sent!r}")
check("the pane counts as a multi-input participant",
      mw._multi_participant_count() == len(mw._terminal_windows))
mw._toggle_multi_input(False)
app.processEvents()
check("the mode off restores the pane's inner title (badge dropped) and drops the host frame",
      pane_a.tabs.tabText(0) == i18n.t("sftp.tab_terminal")
      and win_a.split_host.objectName() == "",
      f"{pane_a.tabs.tabText(0)!r}/{win_a.split_host.objectName()!r}")


# ════════════════════════════════════════════════════════════
# 6. The registry rules: the limit ignores the pane, the dot counts it (task 2)
# ════════════════════════════════════════════════════════════
print("== 6. the registry rules ==")

check("the limit list excludes the pane while the registry keeps it",
      len(mw._limit_terminal_sessions()) == 1 and len(mw._terminal_windows) == 2,
      f"limit={len(mw._limit_terminal_sessions())} registry={len(mw._terminal_windows)}")
check("_find_terminal_window_for ignores the pane session",
      mw._find_terminal_window_for(node_a.data.id) is win_a)

# ── a window whose only tab was closed closes its pane with it ──────────────
node_b = new_node("bravo", "10.90.0.2")
win_b = mw._spawn_terminal_window(node_b, password="pw")
app.processEvents()
win_b.act_split.trigger()
app.processEvents()
pane_b = win_b.split_pane
win_b.close_page(win_b.session_tabs.widget(0))   # the LAST tab: the window closes, the pane with it
wait_until(lambda: not alive(win_b), timeout_ms=4000)
app.processEvents()
check("closing the last TAB tears the PANE down with the window",
      pane_b._shut_down is True and not alive(win_b))
wait_until(lambda: pane_b not in mw._terminal_windows, timeout_ms=4000)
app.processEvents()
check("the destroyed pane leaves the registry (the green dot / the plaque follow)",
      pane_b not in mw._terminal_windows)

# a clean registry for the limit scenario
win_a.close()
wait_until(lambda: len(mw._terminal_windows) == 0, timeout_ms=4000)
app.processEvents()
check("closing a window with a live pane shuts BOTH sessions down",
      pane_a._shut_down is True and top_a._shut_down is True
      and len(mw._terminal_windows) == 0)

# ── the limit really ignores the pane ──────────────────────────────────────
_limit_asked = []
_limit_stub = QuestionStub(QMessageBox.StandardButton.Cancel,
                           record=lambda title, text: _limit_asked.append(title)).install(MW)

write_cfg({"terminal_max_open": 2})
node_c = new_node("charlie", "10.90.0.3")
win_c = mw._spawn_terminal_window(node_c, password="pw")
app.processEvents()
win_c.act_split.trigger()
app.processEvents()
pane_c = win_c.split_pane
check("1 session + 1 pane: the REGISTRY is at terminal_max_open (2) already",
      len(mw._terminal_windows) == 2 and len(mw._limit_terminal_sessions()) == 1,
      f"limit={len(mw._limit_terminal_sessions())} registry={len(mw._terminal_windows)}")

try:
    node_d = new_node("delta", "10.90.0.4")
    _limit_asked.clear()
    win_d = mw._spawn_terminal_window(node_d, password="pw")   # 2 sessions + 1 pane → allowed
    app.processEvents()
    check("a pane open at terminal_max_open does NOT consume the limit: a new window opens",
          win_d is not None and len(_limit_asked) == 0
          and len(mw._limit_terminal_sessions()) == 2
          and len(mw._terminal_windows) == 3,
          f"asked={len(_limit_asked)} limit={len(mw._limit_terminal_sessions())}")

    node_e = new_node("echo", "10.90.0.5")
    _limit_asked.clear()
    w_over = mw._spawn_terminal_window(node_e, password="pw")   # 3 REGULAR sessions → the limit
    check("the limit fires at max_open REGULAR sessions (the pane never counted)",
          w_over is None and len(_limit_asked) == 1)

    _limit_stub.answer = QMessageBox.StandardButton.Close
    _limit_asked.clear()
    _oldest = mw._limit_terminal_sessions()[0]
    check("the 'close the oldest' candidate is a REGULAR session, never the pane",
          _oldest is not pane_c and getattr(_oldest, "_is_split_pane", False) is False)
    node_g2 = new_node("golf2", "10.90.0.12")
    w_new = mw._spawn_terminal_window(node_g2, password="pw")
    check("Close → the oldest REGULAR session is closed and the new one is registered",
          w_new is not None and getattr(_oldest, "_force_close", False) is True
          and len(_limit_asked) == 1, f"asked={len(_limit_asked)}")
    wait_until(lambda: _oldest not in mw._terminal_windows, timeout_ms=4000)
finally:
    _limit_stub.restore()

# clean up the limit section (windows + panes)
for _w in (win_c, win_d, w_new):
    try:
        if _w is not None and alive(_w):
            _w.close()
    except RuntimeError:
        pass
wait_until(lambda: len(mw._terminal_windows) == 0, timeout_ms=4000)
app.processEvents()
check("the limit section cleaned up (every session and pane left the registry)",
      len(mw._terminal_windows) == 0, f"registry={len(mw._terminal_windows)}")
check("the green dot of the node whose sessions are all closed went out",
      dot_color(node_c) == "#64748b" and dot_color(node_d) == "#64748b")

# ── the green dot counts the PANE as a session ─────────────────────────────
node_f = new_node("foxtrot", "10.90.0.6")
win_f = mw._spawn_terminal_window(node_f, password="pw")
app.processEvents()
win_f.act_split.trigger()
app.processEvents()
check("the node has 2 live sessions (a tab + the pane) and the dot is lit",
      len([s for s in mw._terminal_windows if s.server_data.id == node_f.data.id]) == 2
      and dot_color(node_f) == "#22c55e", dot_color(node_f))
mw._forget_terminal_window(win_f.session_tabs.widget(0))   # the TAB leaves, the pane stays
check("the green dot is kept by the PANE alone (the green-dot rule counts it)",
      dot_color(node_f) == "#22c55e", dot_color(node_f))
win_f.close()
wait_until(lambda: len(mw._terminal_windows) == 0, timeout_ms=4000)
app.processEvents()
check("after the pane is gone too, the dot goes out and the registry is empty",
      dot_color(node_f) == "#64748b" and len(mw._terminal_windows) == 0, dot_color(node_f))
clear_cfg()


# ════════════════════════════════════════════════════════════
# 7. The teardown paths (task 2/4)
# ════════════════════════════════════════════════════════════
print("== 7. the teardown paths ==")

# ── a) turning the split OFF: the pane is shut down, the single-pane look returns ──
node_g = new_node("golf", "10.90.0.7")
win_g = mw._spawn_terminal_window(node_g, password="pw")
app.processEvents()
win_g.act_split.trigger()
app.processEvents()
pane_g = win_g.split_pane
top_g = win_g.session_tabs.widget(0)
win_g.act_split.trigger()   # off, through the same action
wait_until(lambda: pane_g not in mw._terminal_windows, timeout_ms=4000)
app.processEvents()
check("the split off closed the pane through the single idempotent shutdown()",
      pane_g._shut_down is True and pane_g.terminal_thread.stop_calls >= 1
      and win_g.split_pane is None)
check("the pane's thread is not left running (no orphan QThread)",
      not pane_g.terminal_thread.isRunning() and pane_g.terminal_thread not in ST._orphan_threads)
check("the single-pane look is back: the host is hidden and the floors are dropped",
      win_g.split_host.isHidden() and win_g.session_tabs.minimumHeight() == 0
      and win_g._v_splitter.sizes()[1] == 0,
      f"sizes={win_g._v_splitter.sizes()}")
check("the top tab survived the pane teardown", top_g._shut_down is False)
check("the bridge returned to the ACTIVE tab after the pane died",
      win_g._bridged_page is top_g and win_g.page is top_g)

# ── b) the pane's own ERROR path: critical + only the pane is closed ─────────
crit_calls = []
_orig_critical = ST.QMessageBox.critical
ST.QMessageBox.critical = staticmethod(lambda *a, **k: crit_calls.append(a))
try:
    win_g.act_split.trigger()   # a fresh pane
    app.processEvents()
    pane_g2 = win_g.split_pane
    pane_g2.terminal_thread.error_signal.emit("boom-split")
    app.processEvents()
    check("the pane's error → QMessageBox.critical (the parent — the host window)",
          len(crit_calls) == 1 and crit_calls[0][0] is win_g, str(crit_calls)[:120])
finally:
    ST.QMessageBox.critical = _orig_critical
wait_until(lambda: win_g.split_pane is None, timeout_ms=4000)
app.processEvents()
check("the pane's error path closed ONLY the pane (the window and its tab live)",
      alive(win_g) and win_g.session_tabs.count() == 1 and pane_g2._shut_down is True
      and win_g.act_split.isChecked() is False,
      f"tabs={win_g.session_tabs.count() if alive(win_g) else '?'}")

# ── c) the window close shuts BOTH pages down ───────────────────────────────
win_g.act_split.trigger()
app.processEvents()
pane_g3 = win_g.split_pane
top_g3 = win_g.session_tabs.widget(0)
win_g.close()
wait_until(lambda: not alive(win_g), timeout_ms=4000)
app.processEvents()
check("closing the window ran shutdown() on the TAB and on the PANE",
      top_g3._shut_down is True and pane_g3._shut_down is True)
check("no live thread is left behind by the window close",
      not top_g3.terminal_thread.isRunning() and not pane_g3.terminal_thread.isRunning()
      and pane_g3.terminal_thread not in ST._orphan_threads)
wait_until(lambda: len(mw._terminal_windows) == 0, timeout_ms=4000)
app.processEvents()
check("the registry is empty after the window close", len(mw._terminal_windows) == 0)

# ── d) MainWindow._shutdown_background_threads tears the pane down too ──────
clear_cfg()   # win_g.close() persisted its split state — start this window single-pane
node_h = new_node("hotel", "10.90.0.8")
win_h = mw._spawn_terminal_window(node_h, password="pw")
app.processEvents()
win_h.act_split.trigger()
app.processEvents()
pane_h = win_h.split_pane
top_h = win_h.session_tabs.widget(0)
mw._shutdown_background_threads()
app.processEvents()
check("_shutdown_background_threads() closed the pane as well (the registry holds it)",
      pane_h._shut_down is True and top_h._shut_down is True
      and not pane_h.terminal_thread.isRunning())
if alive(win_h):
    win_h.close()
wait_until(lambda: len(mw._terminal_windows) == 0, timeout_ms=4000)
app.processEvents()
check("the shutdown section left no session in the registry",
      len(mw._terminal_windows) == 0, f"registry={len(mw._terminal_windows)}")


# ════════════════════════════════════════════════════════════
# 8. Persistence — the state and the ratio survive save→load (task 5)
# ════════════════════════════════════════════════════════════
print("== 8. persistence ==")

clear_cfg()
node_i = new_node("india", "10.90.0.9")
win_i = mw._spawn_terminal_window(node_i, password="pw")
win_i.show()
app.processEvents()
win_i.act_split.trigger()
app.processEvents()
_vs_i = win_i._v_splitter
_total_i = sum(_vs_i.sizes())
_vs_i.setSizes([int(_total_i * 0.62), int(_total_i * 0.38)])
win_i._on_split_moved()
win_i.resize(880, 520)
app.processEvents()
_ratio_saved = win_i._split_ratio
win_i.close()
wait_until(lambda: not alive(win_i), timeout_ms=4000)
app.processEvents()
_cfg = read_cfg({})
check("closeEvent merged ui_terminal_split into the geometry write (one config file)",
      _cfg.get("ui_terminal_split") is True
      and isinstance(_cfg.get("ui_terminal_split_ratio"), float)
      and "ui_window_geometry_terminal" in _cfg,
      f"split={_cfg.get('ui_terminal_split')!r} ratio={_cfg.get('ui_terminal_split_ratio')!r}")
check("the saved ratio is the one the user left behind (≈0.38)",
      abs(float(_cfg.get("ui_terminal_split_ratio")) - _ratio_saved) < 0.05,
      f"saved={_cfg.get('ui_terminal_split_ratio')!r} live={_ratio_saved:.3f}")

node_j = new_node("juliet", "10.90.0.10")
win_j = mw._spawn_terminal_window(node_j, password="pw")
app.processEvents()
check("a new window restores the split STATE (the pane is created by the ONE action)",
      win_j.split_pane is not None and win_j.act_split.isChecked() is True
      and win_j.split_host.isHidden() is False)
check("a new window restores the RATIO",
      abs(win_j._split_ratio - _ratio_saved) < 0.05, f"ratio={win_j._split_ratio:.3f}")
check("the restored pane is registered as a session too",
      win_j.split_pane in mw._terminal_windows)
win_j.close()
wait_until(lambda: not alive(win_j), timeout_ms=4000)
app.processEvents()

# ── the split OFF must not clobber the remembered ratio with 0 ──────────────
clear_cfg()
node_j2 = new_node("juliet2", "10.90.0.13")
win_j2 = mw._spawn_terminal_window(node_j2, password="pw")
win_j2.show()
app.processEvents()
win_j2.act_split.trigger()
app.processEvents()
_vs_j = win_j2._v_splitter
_tot_j = sum(_vs_j.sizes())
_vs_j.setSizes([int(_tot_j * 0.55), int(_tot_j * 0.45)])
win_j2._on_split_moved()
_ratio_kept = win_j2._split_ratio
win_j2.act_split.trigger()   # OFF — the ratio must survive
app.processEvents()
win_j2.close()
wait_until(lambda: not alive(win_j2), timeout_ms=4000)
app.processEvents()
_cfg_off = read_cfg({})
check("with the split OFF the state is saved false but the RATIO the user left is kept",
      _cfg_off.get("ui_terminal_split") is False
      and abs(float(_cfg_off.get("ui_terminal_split_ratio")) - _ratio_kept) < 0.05,
      f"split={_cfg_off.get('ui_terminal_split')!r} "
      f"ratio={_cfg_off.get('ui_terminal_split_ratio')!r} kept={_ratio_kept:.3f}")

# a broken ratio / a foreign type → the default (a broken config never squeezes the panes)
write_cfg({"ui_terminal_split": True, "ui_terminal_split_ratio": 42})
check("a foreign (out of range) ratio is clamped to the ceiling, not trusted",
      ST.load_split_settings()["ratio"] == ST.SPLIT_RATIO_MAX,
      str(ST.load_split_settings()))
write_cfg({"ui_terminal_split": "yes", "ui_terminal_split_ratio": "0.5"})
check("a foreign split value falls back to the default (off, 0.25)",
      ST.load_split_settings() == {"split": False, "ratio": ST.SPLIT_RATIO_DEFAULT},
      str(ST.load_split_settings()))
clear_cfg()
node_k = new_node("kilo", "10.90.0.11")
win_k = mw._spawn_terminal_window(node_k, password="pw")
app.processEvents()
check("with no config the split is off (the v1.3.3.4 default behaviour)",
      win_k.split_pane is None and win_k._split_on is False)
win_k.close()
wait_until(lambda: len(mw._terminal_windows) == 0, timeout_ms=4000)


# ════════════════════════════════════════════════════════════
# 9. i18n (a language switch re-texts the new action) + the release state
# ════════════════════════════════════════════════════════════
print("== 9. i18n + release state ==")

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)   # the pin EXPECTED_I18N_KEYS (+2: terminal.split / terminal.split_tooltip)
for _code in sorted(langs):
    check(f"i18n {_code}: terminal.split / terminal.split_tooltip are present and not empty",
          bool(langs[_code].get("terminal.split"))
          and bool(langs[_code].get("terminal.split_tooltip")),
          f"{langs[_code].get('terminal.split')!r}")

node_l = new_node("lima", "10.90.0.12")
win_l = mw._spawn_terminal_window(node_l, password="pw")
app.processEvents()
i18n.set_language("ru")
try:
    mw._apply_ui_translations()
    app.processEvents()
    check("a language switch re-texts the split action (the v1.3.3.1 container rule)",
          win_l.act_split.text() == i18n.t("terminal.split")
          and win_l.act_split.text() == langs["ru"]["terminal.split"]
          and win_l.act_split.toolTip() == langs["ru"]["terminal.split_tooltip"],
          f"{win_l.act_split.text()!r}/{win_l.act_split.toolTip()!r}")
finally:
    i18n.set_language("en")
    mw._apply_ui_translations()
    app.processEvents()
check("switching back re-texts it to English",
      win_l.act_split.text() == i18n.t("terminal.split"), repr(win_l.act_split.text()))

# ── the split pane survives a language switch (the badge of the inner tab + the status) ──
win_l.act_split.trigger()
app.processEvents()
pane_l = win_l.split_pane
_live = pane_l.session_status             # live session state — deliberately not re-translated
mw._toggle_multi_input(True)
app.processEvents()
_badge = pane_l.tabs.tabText(0)
i18n.set_language("ru")
try:
    mw._apply_ui_translations()
    app.processEvents()
    check("the pane's multi-input badge survives a language switch (the live status is not re-texted)",
          pane_l.tabs.tabText(0)
          == langs['ru']['terminal.multi_tab_badge'].format(alias='lima'),
          f"{_badge!r} -> {pane_l.tabs.tabText(0)!r}")
    check("the split status line re-renders its PREFIX in the new language (the state stays RAW)",
          win_l.split_status_text == _live
          and win_l._split_status_label.text()
          == f"{langs['ru']['terminal.split']}  {_live}",
          f"{win_l.split_status_text!r}/{win_l._split_status_label.text()!r}")
finally:
    mw._toggle_multi_input(False)
    i18n.set_language("en")
    mw._apply_ui_translations()
    app.processEvents()
check("the mode off restored the inner title in English",
      pane_l.tabs.tabText(0) == i18n.t("sftp.tab_terminal"),
      repr(pane_l.tabs.tabText(0)))
check("the split status line is back to the English prefix",
      win_l._split_status_label.text() == f"{i18n.t('terminal.split')}  {_live}",
      repr(win_l._split_status_label.text()))
win_l.act_split.trigger()          # close the pane — its status line goes with it
app.processEvents()
check("closing the Split Terminal REMOVES the second status text",
      win_l.split_pane is None and win_l.split_status_text == ""
      and win_l._split_status_label.isHidden() is True
      and win_l._split_status_label.text() == "",
      f"{win_l.split_status_text!r}/{win_l._split_status_label.text()!r}")
win_l.close()
wait_until(lambda: len(mw._terminal_windows) == 0, timeout_ms=4000)
app.processEvents()

check_release_state(ROOT)
finish()
