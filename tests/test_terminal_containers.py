# -*- coding: utf-8 -*-
"""v1.7.2 — Terminal containers: the split in the dock, the single window, the merge and the titles.

The topical test of the release: offscreen, no network (the fake threads of `ST.SSHTerminalThread`).
§1 ONE split controller shared by both containers; §2 the dock's pane is a real session (the registry,
the limit, the teardown); §3 the OWNER rule (the checkmark mirrors the active session, a foreign press
MOVES the pane, a Cancel keeps it, the tooltip names the owner); §4 `terminal_mode = "single"`; §5 the
merge moves SESSIONS without recreating them and closes the emptied windows; §6 the container's title
names the session on screen and carries the remote `OSC 2` title; §7 i18n and the release state."""
import re
import sys

from _common import (bootstrap, check, finish, wait_until, load_i18n_langs, check_i18n_parity,
                     check_release_state, clear_cfg, merge_cfg, read_cfg,
                     EXPECTED_APP_VERSION, releases_at_least)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QSplitter

app = QApplication(sys.argv)

import i18n
import modules.ssh_terminal as ST
import modules.terminal_split as SP
import modules.terminal_dock as TD
from modules.terminal_page import TerminalSessionPage
from models.server import ServerData
import ui.main_window as MW

from _fakes import (FakeSSHThread as _FakeThread,
                    BlockingFakeSSHThread as _BlockingThread, QuestionStub)

ST.SSHTerminalThread = _FakeThread   # every page/window of this file — on the fake
_orig_thread_cls = ST.SSHTerminalThread


def alive(w) -> bool:
    """Is the C++ object alive (WA_DeleteOnClose: after the accept — already destroyed)."""
    try:
        w.windowTitle()
        return True
    except RuntimeError:
        return False


def make_main():
    """An offscreen MainWindow with a stopped autosave timer (determinism)."""
    w = MW.MainWindow()
    w._autosave_timer.stop()
    w.show()
    app.processEvents()
    return w


def new_node(mw, alias, host):
    return mw.scene.add_server(
        ServerData(id=f"tc-{alias}", alias=alias, host=host, user="root"))


def make_window(mw, alias, host):
    """A standalone terminal window (mode "windows") with ONE tab."""
    win = mw._spawn_terminal_window(new_node(mw, alias, host), password="pw")
    app.processEvents()
    return win


def release_threads(*pages):
    """Let every BLOCKING fake thread finish (the orphan registry is for the real ones)."""
    for page in pages:
        try:
            page.terminal_thread.release()
        except Exception:  # noqa: BLE001 — a thread that is already gone
            pass
    for page in pages:
        try:
            wait_until(lambda p=page: not p.terminal_thread.isRunning(), timeout_ms=4000)
        except Exception:  # noqa: BLE001 — a torn-down page has no thread left
            pass


clear_cfg()
print("== 1. ONE split controller, two containers ==")

check("the controller is ONE class of its own module (the window's furniture moved out)",
      hasattr(SP, "TerminalSplit") and ST.SSHTerminalWindow.CONTAINER_KIND == SP.CONTAINER_WINDOW
      and TD.TerminalDockContent.CONTAINER_KIND == SP.CONTAINER_DOCK)
check("the two split config keys are declared ONCE (the controller's, re-exported by ssh_terminal)",
      SP.SPLIT_CONFIG_BOOL == "ui_terminal_split"
      and SP.SPLIT_CONFIG_RATIO == "ui_terminal_split_ratio"
      and ST.SPLIT_CONFIG_BOOL == SP.SPLIT_CONFIG_BOOL
      and ST.SPLIT_RATIO_DEFAULT == SP.SPLIT_RATIO_DEFAULT
      and ST.load_split_settings is SP.load_split_settings)

mw1 = make_main()
win1 = make_window(mw1, "alpha", "10.98.0.1")
check("the window owns ONE controller and hands the shipped names to it",
      isinstance(win1.split, SP.TerminalSplit) and win1.split_host is win1.split.host
      and win1._v_splitter is win1.split.splitter
      and win1._v_splitter.widget(0) is win1.session_tabs
      and win1._v_splitter.widget(1) is win1.split_host)
check("the shipped action/button pair belongs to the controller (ONE source of truth)",
      win1.act_split is win1.split.act and win1.btn_split is win1.split.btn
      and win1.commander.isAncestorOf(win1.btn_split))
check("no split is open yet and the host is hidden",
      win1.split.pane is None and win1.split.on is False and win1.split_host.isHidden())

win1.act_split.trigger()
app.processEvents()
check("the action opens a REAL pane of the active session and records its OWNER",
      isinstance(win1.split.pane, TerminalSessionPage)
      and win1.split.owner_page is win1.session_tabs.currentWidget()
      and win1.split_host.isHidden() is False)
check("the shipped delegates follow the controller (the refactor gate)",
      win1.split_pane is win1.split.pane and win1._split_pane is win1.split.pane
      and win1._split_on is win1.split.on and win1._split_ratio == win1.split.ratio)
win1.act_split.trigger()
app.processEvents()
check("the same action closes it (the shipped behaviour) and forgets the owner",
      win1.split.pane is None and win1.split.owner_page is None and win1.split_host.isHidden())
mw1._shutdown_background_threads()
app.processEvents()


# ════════════════════════════════════════════════════════════
# 2. The DOCK's split — the same construct, a real session
# ════════════════════════════════════════════════════════════
print("== 2. the dock's split ==")

clear_cfg()
merge_cfg({"terminal_mode": "tabs"})
mw2 = make_main()
node2 = new_node(mw2, "beta", "10.98.0.2")
dock = mw2._spawn_terminal_window(node2, password="pw")
app.processEvents()
content = dock.content
check("the dock's session area is the SAME construct (V[session_tabs | split_host])",
      isinstance(content.split, SP.TerminalSplit) and isinstance(content._v_splitter, QSplitter)
      and content._v_splitter.widget(0) is content.session_tabs
      and content._v_splitter.widget(1) is content.split_host
      and content.split_host.isHidden())
check("the dock's corner holds the split BUTTON beside the Commander control",
      isinstance(content.btn_split, QPushButton) and content.commander.isAncestorOf(content.btn_split)
      and content.act_split.isCheckable() and content.act_split.shortcut().isEmpty()
      and content.act_split.text() == i18n.t("terminal.split")
      and content.act_split.toolTip() == i18n.t("terminal.split_tooltip"))

content.btn_split.click()   # the real click path of the corner button
app.processEvents()
pane_d = content.split.pane
check("the dock's Split Terminal opens a REAL second shell of the ACTIVE TAB's node",
      isinstance(pane_d, TerminalSessionPage) and pane_d is not content.session_tabs.widget(0)
      and pane_d.server_data.id == node2.data.id and pane_d._is_split_pane is True
      and content.split.owner_page is content.session_tabs.widget(0))
check("the dock's pane is a command line (no Files tab) and is bound to the dock content",
      pane_d.sftp_tab is None and pane_d._host_window is content
      and content.session_tabs.count() == 1)
check("the pane JOINED the MainWindow registry through the dock's OWN sink (the parent chain)",
      pane_d in mw2._terminal_windows and node2._ssh_status.brush().color().name() == "#22c55e")
check("the pane is EXCLUDED from the session limit while the registry keeps it",
      pane_d not in mw2._limit_terminal_sessions()
      and len(mw2._limit_terminal_sessions()) == 1)
check("the pane's live status reaches the dock's ONE status line",
      content.status_label.text() == pane_d.session_status, repr(content.status_label.text()))

content.act_split.trigger()   # OFF, the default "close" behaviour — no dialog
app.processEvents()
check("the dock's OFF tears the pane down through the ONE idempotent shutdown()",
      content.split.pane is None and pane_d._shut_down is True and content.split_host.isHidden())
check("the dock itself SURVIVES its pane (the container outlives its sessions)",
      alive(dock) and content.session_tabs.count() == 1)
mw2._shutdown_background_threads()
app.processEvents()
wait_until(lambda: len(mw2._terminal_windows) == 0, timeout_ms=4000)
check("the dock section left nothing in the registry", len(mw2._terminal_windows) == 0)


# ════════════════════════════════════════════════════════════
# 3. The OWNER rule — the split belongs to the ACTIVE SESSION
# ════════════════════════════════════════════════════════════
print("== 3. the owner rule ==")

clear_cfg()
mw3 = make_main()
win3 = make_window(mw3, "gamma", "10.98.0.3")
tab_a = win3.session_tabs.widget(0)
win3.add_session(new_node(mw3, "delta", "10.98.0.4").data, password="pw")   # a SECOND tab
app.processEvents()
tab_b = win3.session_tabs.widget(1)
win3.session_tabs.setCurrentIndex(0)
app.processEvents()

win3.act_split.trigger()   # open for tab A
app.processEvents()
pane3 = win3.split.pane
check("the pane is opened for the ACTIVE tab and the checkmark mirrors it",
      win3.split.owner_page is tab_a and win3.act_split.isChecked() is True)
check("the TOOLTIP names the owner (the second channel, no third checkmark state)",
      win3.act_split.toolTip() == f"{i18n.t('terminal.split_tooltip')} — gamma",
      repr(win3.act_split.toolTip()))

win3.session_tabs.setCurrentIndex(1)   # a FOREIGN session — the pane keeps running
app.processEvents()
check("switching to a session that does not own the pane UNCHECKS the action",
      win3.act_split.isChecked() is False and win3.btn_split.isChecked() is False)
check("the pane KEEPS RUNNING while its owner is not the active session (it is a session)",
      win3.split.pane is pane3 and pane3._shut_down is False
      and win3.split_host.isHidden() is False)
check("the tooltip still names the owner while another session is on screen",
      win3.act_split.toolTip().endswith("— gamma"), repr(win3.act_split.toolTip()))

win3.session_tabs.setCurrentIndex(0)
app.processEvents()
check("the owner's checkmark is restored WITHOUT touching the pane",
      win3.act_split.isChecked() is True and win3.split.pane is pane3
      and win3.split.owner_page is tab_a)
check("the window title names the session ON SCREEN, not the first one",
      win3.windowTitle() == i18n.t("terminal.window_title", alias="gamma", host="10.98.0.3"),
      repr(win3.windowTitle()))

win3.session_tabs.setCurrentIndex(1)
app.processEvents()
check("the title follows the tab switch (a shared window cannot name the first session)",
      win3.windowTitle() == i18n.t("terminal.window_title", alias="delta", host="10.98.0.4"),
      repr(win3.windowTitle()))
win3.act_split.trigger()   # a FOREIGN session asks for the split — the MOVE
app.processEvents()
check("the press MOVES the split to the session the keyboard is in",
      win3.split.pane is not None and win3.split.pane is not pane3
      and win3.split.owner_page is tab_b and win3.act_split.isChecked() is True)
check("the moved-away pane went through the ONE teardown",
      pane3._shut_down is True and win3.split.pane._shut_down is False)
check("the pane is a session of the SAME window and the tab strip keeps the two tabs",
      win3.session_tabs.count() == 2 and win3.split.pane in mw3._terminal_windows)
check("the pane is reachable from EVERY inner tab (the action is not tied to the canvas)",
      win3.act_split in win3._build_context_menu().actions())
win3.act_split.trigger()   # the OWNER closes it
app.processEvents()
check("pressing it on the OWNER closes the pane (the shipped behaviour)",
      win3.split.pane is None and win3.act_split.isChecked() is False)
mw3._shutdown_background_threads()
app.processEvents()

# ── the "ask" gate: a Cancel leaves the foreign pane where it is ──
merge_cfg({"terminal_close_behavior": "ask"})
ST.SSHTerminalThread = _BlockingThread
mw3b = make_main()
win3b = mw3b._spawn_terminal_window(new_node(mw3b, "epsilon", "10.98.0.5"), password="pw")
app.processEvents()
tab_1 = win3b.session_tabs.widget(0)
win3b.add_session(new_node(mw3b, "zeta", "10.98.0.6").data, password="pw")
app.processEvents()
tab_2 = win3b.session_tabs.widget(1)
wait_until(lambda: tab_1.terminal_thread.isRunning() and tab_2.terminal_thread.isRunning(),
           timeout_ms=4000)
win3b.session_tabs.setCurrentIndex(0)
win3b.act_split.trigger()
app.processEvents()
pane_3b = win3b.split.pane
stub = QuestionStub(QMessageBox.StandardButton.Cancel).install(ST)
try:
    win3b.session_tabs.setCurrentIndex(1)
    app.processEvents()
    win3b.act_split.trigger()
    app.processEvents()
    check("a foreign press asks the OLD pane's OWN gate first",
          len(stub.calls) == 1 and stub.calls[0][0] == i18n.t("msg.close_session_title"),
          str(stub.calls))
    check("a Cancel leaves the pane exactly where it was (and the checkmark mirrors the owner)",
          win3b.split.pane is pane_3b and win3b.split.owner_page is tab_1
          and win3b.act_split.isChecked() is False)
finally:
    stub.restore()
release_threads(pane_3b, tab_1, tab_2)
app.processEvents()
stub2 = QuestionStub(QMessageBox.StandardButton.Close).install(ST)
try:
    win3b.act_split.trigger()
    app.processEvents()
    check("with the gate passed the pane MOVES to the session on screen",
          win3b.split.pane is not None and win3b.split.pane is not pane_3b
          and win3b.split.owner_page is tab_2 and win3b.act_split.isChecked() is True)
finally:
    stub2.restore()
release_threads(win3b.split.pane)
mw3b._shutdown_background_threads()
app.processEvents()
wait_until(lambda: len(mw3b._terminal_windows) == 0, timeout_ms=4000)
clear_cfg()
ST.SSHTerminalThread = _FakeThread


# ════════════════════════════════════════════════════════════
# 4. terminal_mode = "single" — the window that collects them
# ════════════════════════════════════════════════════════════
print("== 4. the single-window mode ==")

clear_cfg()
check("no key → 'windows' (the shipped default)", ST.load_terminal_settings()["mode"] == "windows")
merge_cfg({"terminal_mode": "single"})
check("'single' is a real mode", ST.load_terminal_settings()["mode"] == "single")
merge_cfg({"terminal_mode": " SINGLE "})
check("the strip+lower rule applies to it too", ST.load_terminal_settings()["mode"] == "single")
merge_cfg({"terminal_mode": "quad"})
check("a foreign value still falls back to 'windows'",
      ST.load_terminal_settings()["mode"] == "windows")
check("the accepted set is DECLARED once, the default first",
      ST.TERMINAL_MODES == ("windows", "tabs", "single"))

clear_cfg()
merge_cfg({"terminal_mode": "single"})
mw5 = make_main()
w_a = mw5._spawn_terminal_window(new_node(mw5, "eta", "10.98.0.7"), password="pw")
app.processEvents()
check("the first session opens a window with ONE tab", w_a.session_tabs.count() == 1
      and w_a.CONTAINER_KIND == SP.CONTAINER_WINDOW)
w_b = mw5._spawn_terminal_window(new_node(mw5, "theta", "10.98.0.8"), password="pw")
app.processEvents()
check("a session of ANOTHER node joins the LAST live window (the per-node rule is bypassed)",
      w_b is w_a and w_a.session_tabs.count() == 2)
check("the tab titles are the two aliases, in order",
      w_a.session_tabs.tabText(0) == "eta" and w_a.session_tabs.tabText(1) == "theta")
check("the registry holds the two SESSIONS (the limit counts them, the window is one)",
      len(mw5._terminal_windows) == 2 and len(mw5._limit_terminal_sessions()) == 2)
check("the window title names the session ON SCREEN (the new tab is current)",
      w_a.windowTitle() == i18n.t("terminal.window_title", alias="theta", host="10.98.0.8"),
      repr(w_a.windowTitle()))
w_c = mw5._spawn_terminal_window(new_node(mw5, "iota", "10.98.0.9"), password="pw")
app.processEvents()
check("the third node joins the SAME window — one window collects them all",
      w_c is w_a and w_a.session_tabs.count() == 3)
check("the dock is not involved in the mode (no Terminals dock was created)",
      getattr(mw5, "_terminals_dock", None) is None)


# ════════════════════════════════════════════════════════════
# 5. The MERGE — sessions move, nothing is recreated
# ════════════════════════════════════════════════════════════
print("== 5. Merge Windows ==")

check("the merge is ONE context-menu action (no registry sequence, no fourth corner button)",
      hasattr(w_a, "act_merge") and w_a.act_merge in w_a._build_context_menu().actions()
      and w_a.act_merge.text() == i18n.t("terminal.merge_windows")
      and w_a.act_merge.shortcut().isEmpty())
check("the corner keeps exactly its two controls (the split button + the Commander)",
      len(w_a.commander.findChildren(QPushButton)) == 2,
      str([b.text() for b in w_a.commander.findChildren(QPushButton)]))
mw5._shutdown_background_threads()
app.processEvents()

clear_cfg()
mw6 = make_main()
t1 = make_window(mw6, "kappa", "10.98.1.1")
t1.add_session(new_node(mw6, "lambda", "10.98.1.2").data, password="pw")   # a second TAB
app.processEvents()
w2 = make_window(mw6, "mu", "10.98.1.3")
app.processEvents()
check("before the merge: 2 windows, 3 sessions and the registry's own list",
      t1 is not w2 and t1.session_tabs.count() == 2 and w2.session_tabs.count() == 1
      and len(mw6._terminal_windows) == 2)
moved_pages = [t1.session_tabs.widget(0), t1.session_tabs.widget(1),
               w2.session_tabs.widget(0)]
w2.act_split.trigger()   # the TARGET owns a split of its own
app.processEvents()
pane_m = w2.split.pane
_registry_before = list(mw6._terminal_windows)
check("the target window really has a split open (and its pane joined the registry)",
      pane_m is not None and pane_m in _registry_before and len(_registry_before) == 3)

w2.act_merge.trigger()
app.processEvents()
check("every session of the other window moved into THIS one, in order "
      "(the target's own tabs come first)",
      w2.session_tabs.count() == 3
      and [w2.session_tabs.widget(i) for i in range(3)]
      == [moved_pages[2]] + moved_pages[:2],
      str([w2.session_tabs.tabText(i) for i in range(3)]))
check("the pages are the SAME objects — no session was recreated",
      all(w2.session_tabs.widget(i) in moved_pages for i in range(3)))
check("no session was torn down (the scrollback / the history / the worker survive)",
      all(not p._shut_down for p in moved_pages))
check("the moved pages were re-bound to their NEW host",
      all(p._host_window is w2 for p in moved_pages))
check("the emptied source window was closed, the target lives",
      not alive(t1) and alive(w2))
check("the tabs carry the node aliases of the moved sessions, in source order",
      [w2.session_tabs.tabText(i) for i in range(3)] == ["mu", "kappa", "lambda"],
      str([w2.session_tabs.tabText(i) for i in range(3)]))
check("the registry is the SAME list — a merge moves sessions and keeps them where they are",
      list(mw6._terminal_windows) == _registry_before,
      str(mw6._terminal_windows))
check("the ONE closing report names BOTH numbers",
      mw6.statusBar().currentMessage()
      == i18n.t("terminal.merge_report", sessions=2, windows=1),
      repr(mw6.statusBar().currentMessage()))
check("the TARGET's own split is untouched (only a SOURCE's split is settled first)",
      w2.split.pane is pane_m and pane_m._shut_down is False)

# ── a source whose split gate is CANCELLED stays out of the merge ──
merge_cfg({"terminal_close_behavior": "ask"})
ST.SSHTerminalThread = _BlockingThread
w_src = mw6._spawn_terminal_window(new_node(mw6, "nu", "10.98.1.4"), password="pw")
app.processEvents()
src_page = w_src.session_tabs.widget(0)
wait_until(lambda: src_page.terminal_thread.isRunning(), timeout_ms=4000)
w_src.act_split.trigger()
app.processEvents()
src_pane = w_src.split.pane
stub3 = QuestionStub(QMessageBox.StandardButton.Cancel).install(ST)
try:
    w2.act_merge.trigger()
    app.processEvents()
    check("a Cancel on the source's split gate keeps THAT window out of the merge",
          len(stub3.calls) == 1 and alive(w_src) and w_src.session_tabs.count() == 1
          and w2.session_tabs.count() == 3, str(stub3.calls))
finally:
    stub3.restore()
release_threads(src_pane, src_page)
app.processEvents()
w2.act_merge.trigger()
app.processEvents()
check("with the gate passed the merge takes that window too",
      not alive(w_src) and w2.session_tabs.count() == 4
      and src_page._host_window is w2 and src_page._shut_down is False)
clear_cfg()
ST.SSHTerminalThread = _FakeThread
mw6._shutdown_background_threads()
app.processEvents()
wait_until(lambda: len(mw6._terminal_windows) == 0, timeout_ms=4000)
check("the merge section left no session behind", len(mw6._terminal_windows) == 0)


# ════════════════════════════════════════════════════════════
# 6. The container's title and the remote title (OSC 2)
# ════════════════════════════════════════════════════════════
print("== 6. the tab tooltip and the window title ==")

clear_cfg()
mw7 = make_main()
win7 = make_window(mw7, "xi", "10.98.2.1")
page7 = win7.session_tabs.widget(0)
check("the tab TEXT is the node alias and the tooltip is the shipped sentence",
      win7.session_tabs.tabText(0) == "xi"
      and win7.session_tabs.tabToolTip(0) == i18n.t("terminal.tab_close_tooltip"))
check("no remote title yet", page7.remote_title == "")

page7._on_output(b"hello\r\n")
app.processEvents()
check("plain output sets no title (the reader is honest about an empty one)",
      page7.remote_title == "" and win7.session_tabs.tabToolTip(0)
      == i18n.t("terminal.tab_close_tooltip"))

page7._on_output(b"\x1b]2;vim /etc/hosts\x07more\r\n")
app.processEvents()
check("an OSC 2 from the remote program is READ (pyte stored it all along)",
      page7.remote_title == "vim /etc/hosts", repr(page7.remote_title))
check("the remote title lands on the tab TOOLTIP as its second line",
      win7.session_tabs.tabToolTip(0).splitlines()
      == [i18n.t("terminal.tab_close_tooltip"),
          i18n.t("terminal.tab_remote_title", title="vim /etc/hosts")],
      repr(win7.session_tabs.tabToolTip(0)))
check("the tab TEXT still carries the node alias (the tooltip is the second channel)",
      win7.session_tabs.tabText(0) == "xi")
check("the window title PREFERS the remote title for the session on screen",
      win7.windowTitle() == i18n.t("terminal.window_title", alias="vim /etc/hosts",
                                   host="10.98.2.1"),
      repr(win7.windowTitle()))

page7._on_output(b"\x1b]0;tail -f /var/log/syslog\x07")
app.processEvents()
check("a new OSC 0 replaces it (and the title follows)",
      page7.remote_title == "tail -f /var/log/syslog"
      and win7.windowTitle() == i18n.t("terminal.window_title",
                                       alias="tail -f /var/log/syslog", host="10.98.2.1"))

page7._on_output(b"\x1b]2;same title\x07")
app.processEvents()
_first = win7.session_tabs.tabToolTip(0)
page7._on_output(b"\x1b]2;same title\x07")
app.processEvents()
check("an UNCHANGED title is not a change (the host is told once, the tooltip stays)",
      page7.remote_title == "same title" and win7.session_tabs.tabToolTip(0) == _first)

page7.set_activity(True)
app.processEvents()
check("the activity mark's sentence keeps its own line above the remote title",
      win7.session_tabs.tabToolTip(0).splitlines()[0] == i18n.t("terminal.tab_new_output")
      and win7.session_tabs.tabToolTip(0).splitlines()[1]
      == i18n.t("terminal.tab_remote_title", title="same title"))
page7.set_activity(False)
app.processEvents()

win7.add_session(new_node(mw7, "omicron", "10.98.2.2").data, password="pw")
app.processEvents()
check("a session that never set a title carries the plain sentence (no empty second line)",
      win7.session_tabs.tabToolTip(1) == i18n.t("terminal.tab_close_tooltip"))
check("the title follows the tab switch (the new session is on screen)",
      win7.windowTitle() == i18n.t("terminal.window_title", alias="omicron", host="10.98.2.2"),
      repr(win7.windowTitle()))
win7.session_tabs.setCurrentIndex(0)
app.processEvents()
check("... and back to the first session's remote title",
      win7.windowTitle() == i18n.t("terminal.window_title", alias="same title",
                                   host="10.98.2.1"))

i18n.set_language("ru")
win7.retranslate()
app.processEvents()
check("a language switch re-renders the remote-title line of the OPEN tab",
      "Заголовок с сервера" in win7.session_tabs.tabToolTip(0),
      repr(win7.session_tabs.tabToolTip(0)))
check("... and the window title keeps naming the session on screen in the new language",
      win7.windowTitle() == i18n.t("terminal.window_title", alias="same title",
                                   host="10.98.2.1"),
      repr(win7.windowTitle()))
i18n.set_language("en")
win7.retranslate()
app.processEvents()
check("switching back restores the English line",
      "Remote title" in win7.session_tabs.tabToolTip(0),
      repr(win7.session_tabs.tabToolTip(0)))
mw7._shutdown_background_threads()
app.processEvents()


# ════════════════════════════════════════════════════════════
# 7. i18n and the release state
# ════════════════════════════════════════════════════════════
print("== 7. i18n + release state ==")

_langs = load_i18n_langs(ROOT)
check_i18n_parity(_langs)
_NEW_KEYS = ("terminal.merge_windows", "terminal.merge_report",
             "terminal.tab_remote_title", "settings.terminal.mode.single")
check("the four keys of the release are TRANSLATION keys of EVERY language file",
      all(all(_data.get(k) for k in _NEW_KEYS) for _data in _langs.values())
      and all(k in _langs["en"] for k in _NEW_KEYS),
      str([k for k in _NEW_KEYS if k not in _langs["en"]]))
check("the merge report carries BOTH counters as placeholders",
      set(re.findall(r"\{(\w+)\}", _langs["en"]["terminal.merge_report"])) == {"sessions", "windows"},
      _langs["en"]["terminal.merge_report"])
check("the remote-title line carries the title placeholder",
      "{title}" in _langs["en"]["terminal.tab_remote_title"])
check("the dock's split button reuses the SHIPPED label (ONE key, two containers)",
      _langs["en"]["terminal.split"] == "Split Terminal"
      and TD.TerminalDockContent.CONTAINER_KIND == "dock")
check("the new mode row is translated everywhere (not an English copy)",
      all(_langs[c]["settings.terminal.mode.single"]
          != _langs["en"]["settings.terminal.mode.single"] for c in _langs if c != "en"))
check("no new dependency was added for the containers (the four pinned ones)",
      all(f"{d}>=" in open("requirements.txt", encoding="utf-8").read()
          for d in ("PySide6", "paramiko", "keyring", "wcwidth")))

check_release_state(ROOT)
check("release: this file describes the 1.7.2 containers (the three modes are the shipped set)",
      releases_at_least(EXPECTED_APP_VERSION, "1.7.2")
      and SP.SPLIT_MIN_ROWS == 4 and SP.SPLIT_RATIO_DEFAULT == 0.25)

finish()
