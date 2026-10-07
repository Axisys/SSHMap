# -*- coding: utf-8 -*-
"""The Files tree as a right-hand panel of a standalone terminal window.

Offscreen, NO network (the fake threads + the fake paramiko/SFTP surface of `_fakes.py`). Pins the
`[commands | terminal | files]` layout, the RE-PARENTING of the ACTIVE session's Files widget, the
lazy channel open, the fold, the floors and the Commander exclusion.
Contract — `AGENTS.md` §4.3; mechanism — `DOCUMENTATION.md` §63.

Run: python tests/test_terminal_files_panel.py   (from the project root) or python tests/run_all.py"""
import inspect
import re
import sys

from _common import (VERSION_FORMAT_RE, bootstrap, check, finish, load_i18n_langs,
                     check_i18n_parity, check_i18n_format, check_release_state, read_cfg,
                     merge_cfg, clear_cfg, write_cfg, EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS,
                     releases_at_least)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QSplitter, QStackedWidget

app = QApplication(sys.argv)

import i18n
import modules.ssh_terminal as ST
import modules.command_library as CL
import modules.sftp_tab as SFTP
from modules.terminal_page import TerminalSessionPage
from models.server import ServerData
from ui.settings_dialog import SettingsDialog  # noqa: E402 — the hub's own row of the mode
import ui.main_window as MW

from _fakes import (FakeSSHThread as _FakeThread, FakeSSHClient, FakeSftpClient, FakeSftpFS)

ST.SSHTerminalThread = _FakeThread   # every page/window of this file runs on the fake


def new_node(mw, alias, host, nid=None):
    return mw.scene.add_server(
        ServerData(id=nid or f"fp-{alias}", alias=alias, host=host, user="root"))


def fake_sftp(win, page, files=None):
    """Wire the fake paramiko client so `_ensure_sftp()` really opens a worker."""
    fs = FakeSftpFS()
    for path, data in (files or {"/readme.txt": b"hello\\n"}).items():
        fs.add_file(path, data)
    page.terminal_thread.client = FakeSSHClient(FakeSftpClient(fs))
    return fs


def close_window(win):
    try:
        win._dirty = False
        win.close()
    except Exception:  # noqa: BLE001 — teardown robustness of the scenario
        pass
    app.processEvents()


#: Every container this scenario created. A page added with `win.add_session()` is NOT in the
#: MainWindow registry (that is `_spawn_terminal_window`'s job), so the final teardown walks
#: the containers themselves — a live SftpWorker left behind aborts the process at exit and
#: the suite reads the EXIT CODE, not the log.
_WINDOWS = []


def hold(win):
    _WINDOWS.append(win)
    return win


def teardown_all():
    for win in _WINDOWS:
        try:
            for page in win._all_pages():
                page.shutdown()
        except Exception:  # noqa: BLE001 — teardown robustness of the scenario
            pass
    for main in (mw, mw5, mw8, mw9):
        try:
            main._dirty = False
            main.close()
        except Exception:  # noqa: BLE001 — teardown robustness of the scenario
            pass
    app.processEvents()


# ════════════════════════════════════════════════════════════
# 1. The shape and the switch
# ════════════════════════════════════════════════════════════
print("== 1. the shape of the window and the ONE switch ==")

clear_cfg()
mw = MW.MainWindow()
mw._autosave_timer.stop()
mw._freshness_timer.stop()
mw._status_checker = None
mw.resize(1100, 640)
mw.show()
app.processEvents()

node_a = new_node(mw, "alpha", "10.70.0.1")
win = hold(mw._spawn_terminal_window(node_a, password="pw"))
app.processEvents()
page_a = win.session_tabs.widget(0)
fake_sftp(win, page_a)
splitter = win.centralWidget()

check("the central widget is QSplitter[cmdlib_panel | V(session_tabs | split_host) | files_panel]",
      isinstance(splitter, QSplitter) and splitter.count() == 3
      and splitter.widget(0) is win.cmdlib_panel
      and splitter.widget(1) is win._v_splitter
      and splitter.widget(2) is win.files_panel)
check("the panel cannot be lost by dragging the divider (setCollapsible(False) on every side)",
      not splitter.isCollapsible(0) and not splitter.isCollapsible(1) and not splitter.isCollapsible(2))
check("the mode is OFF by default: the panel is hidden and the tabs are the shipped three",
      win.files_panel_on is False and win.files_panel.isHidden()
      and [page_a.tabs.tabText(i) for i in range(page_a.tabs.count())]
      == ["Terminal", "Files", "History"])
check("the panel carries a QStackedWidget (ONE page per session)",
      isinstance(win.files_panel.stack, QStackedWidget) and win.files_panel.stack.count() == 0)

check("ONE checkable action terminal.files_panel IS the switch of a live window",
      win.act_files_panel.isCheckable() and win.act_files_panel.isChecked() is False
      and win.act_files_panel.text() == i18n.t("terminal.files_panel")
      and win.act_files_panel.toolTip() == i18n.t("terminal.files_panel_tooltip"))
check("...and the corner keeps the shipped PAIR — no third control, no Files panel button",
      win.session_tabs.cornerWidget(Qt.Corner.TopRightCorner) is win.commander
      and win.commander.isAncestorOf(win.btn_split)
      and win.commander.isAncestorOf(win.commander.btn)
      and not hasattr(win, "btn_files_panel")
      and not any(b.text() == i18n.t("terminal.files_panel")
                  for b in win.commander.findChildren(QPushButton)))
check("...which is what keeps the window's own floor at the shipped two-button width",
      not hasattr(SFTP, "CORNER_BUTTON_MIN_WIDTH")
      and "panel_button" not in inspect.signature(SFTP.CommanderCorner.__init__).parameters
      and len(win.commander.findChildren(QPushButton)) == 2,
      f"floor={win.minimumSizeHint().width()}")
check("...and the context-menu item is the ONLY surface of that action left",
      win.act_files_panel in win._build_context_menu().actions()
      and win.act_split in win._build_context_menu().actions())
check("no keyboard shortcut and no registry sequence (a layout preference, not a hotkey)",
      win.act_files_panel.shortcut().isEmpty())

# v1.7.1.1: WHERE the mode comes from — the settings hub's `terminal_files_mode`
# (`resolve_files_mode()`), read once per window like `terminal_mode`. The legacy
# `ui_files_panel` of v1.7.1 is the MIGRATION source and is never written again.
write_cfg({})
check("the default is 'tab' — the shipped Files tab (no key, an empty config)",
      ST.resolve_files_mode() == "tab"
      and ST.load_files_panel_settings() == {"mode": "tab", "collapsed": False})
write_cfg({"terminal_files_mode": " PANEL "})
check("a real key is read (strip + lower, the terminal_mode rule)",
      ST.resolve_files_mode() == "panel")
write_cfg({"terminal_files_mode": "garbage"})
check("an unknown value falls back to the shipped tab", ST.resolve_files_mode() == "tab")
write_cfg({"terminal_files_mode": 1})
check("a foreign TYPE is a broken key, not a legacy one", ST.resolve_files_mode() == "tab")
write_cfg({"ui_files_panel": True})
check("the LEGACY ui_files_panel migrates when the new key is absent (v1.7.1 layout kept)",
      ST.resolve_files_mode() == "panel")
write_cfg({"terminal_files_mode": "tab", "ui_files_panel": True})
check("...but a real terminal_files_mode always wins over the legacy value",
      ST.resolve_files_mode() == "tab")
write_cfg({"ui_files_panel": "yes"})
check("a broken legacy value is ignored too (only a real JSON bool counts)",
      ST.resolve_files_mode() == "tab")
clear_cfg()

# The opening mode of a NEW window — the whole point of the setting: the key decides how a
# window is BUILT (the action's checkmark, the stack and the tab strips included).
write_cfg({"terminal_files_mode": "panel"})
win_key = hold(ST.SSHTerminalWindow(ServerData(id="fp-open-panel", alias="opened", host="10.70.9.8",
                                               user="root"), None, password="pw"))
win_key.show()
app.processEvents()
_page_key = win_key.session_tabs.widget(0)
check("a window opened with terminal_files_mode = 'panel' starts with the panel ON",
      win_key.files_panel_on is True and win_key.act_files_panel.isChecked() is True
      and win_key.files_panel.isHidden() is False
      and [ _page_key.tabs.tabText(i) for i in range(_page_key.tabs.count())]
      == ["Terminal", "History"])
close_window(win_key)
write_cfg({"terminal_files_mode": "tab"})
win_tab = hold(ST.SSHTerminalWindow(ServerData(id="fp-open-tab", alias="plain", host="10.70.9.7",
                                              user="root"), None, password="pw"))
win_tab.show()
app.processEvents()
_page_tab = win_tab.session_tabs.widget(0)
check("...and 'tab' (the default) opens the shipped single-pane look",
      win_tab.files_panel_on is False and win_tab.files_panel.isHidden()
      and [_page_tab.tabs.tabText(i) for i in range(_page_tab.tabs.count())]
      == ["Terminal", "Files", "History"])
close_window(win_tab)
clear_cfg()

_before_sizes = splitter.sizes()
win.act_files_panel.setChecked(True)   # the ONE switch of a live window (its context-menu item)
app.processEvents()
check("turning the mode ON through the action turns it on (the checkmark IS the state)",
      win.files_panel_on is True and win.act_files_panel.isChecked() is True
      and win.files_panel.isHidden() is False)
check("the width really moved out of the terminal column (the panel got a column of its own)",
      splitter.sizes()[2] > CL._CollapseStrip.STRIP_WIDTH and splitter.sizes()[1] < _before_sizes[1],
      f"before={_before_sizes} after={splitter.sizes()}")


# ════════════════════════════════════════════════════════════
# 2. The mode moves the WIDGET, not the session
# ════════════════════════════════════════════════════════════
print("== 2. the Files widget moves; the PAGE keeps its owner ==")

check("the session's tab strip became Terminal | History (the Files TAB is gone)",
      [page_a.tabs.tabText(i) for i in range(page_a.tabs.count())] == ["Terminal", "History"]
      and page_a.tabs.count() == 2)
check("the widget that left the strip is the panel's current page",
      win.files_panel.stack.count() == 1
      and win.files_panel.stack.currentWidget() is page_a.sftp_tab)
check("the PAGE keeps `sftp_tab` as the OWNER (every page-level read survives)",
      page_a.sftp_tab is not None and isinstance(page_a.sftp_tab.parentWidget(), QStackedWidget)
      and page_a.sftp_tab.parentWidget() is win.files_panel.stack)
check("...and the page knows that its tree lives in the panel", page_a.files_panel_on is True)
check("the tab it lost is not the one the page re-texts (retranslate walks what is there)",
      page_a.tabs.widget(0) is page_a.widget
      and page_a.tabs.widget(1) is page_a.history_tab)
check("...and the page's lazy-open path is told to open WITHOUT a tab switch",
      page_a._files_panel_on is True)

win.act_files_panel.setChecked(False)
app.processEvents()
check("switching the mode OFF puts the tab back at its shipped position",
      [page_a.tabs.tabText(i) for i in range(page_a.tabs.count())]
      == ["Terminal", "Files", "History"]
      and page_a.tabs.widget(1) is page_a.sftp_tab
      and win.files_panel.stack.count() == 0 and win.files_panel.isHidden())
check("...and the page's owner identity is untouched by the round trip",
      page_a.sftp_tab is not None and page_a.tabs.indexOf(page_a.sftp_tab) == 1
      and page_a.files_panel_on is False)


# ════════════════════════════════════════════════════════════
# 3. ONE page per session (the stack follows the tab strip)
# ════════════════════════════════════════════════════════════
print("== 3. the stack follows session_tabs.currentChanged ==")

node_b = new_node(mw, "beta", "10.70.0.2")
win.add_session(node_b.data, password="pw")
app.processEvents()
page_b = win.session_tabs.widget(1)
fake_sftp(win, page_b)

win.act_files_panel.setChecked(True)
app.processEvents()
check("EVERY tab session joined the stack (one page per session)",
      win.files_panel.stack.count() == 2
      and {win.files_panel.stack.widget(i) for i in range(2)}
      == {page_a.sftp_tab, page_b.sftp_tab})
check("the stack shows the ACTIVE tab's tree",
      win.session_tabs.currentWidget() is page_b
      and win.files_panel.stack.currentWidget() is page_b.sftp_tab)

page_a.sftp_tab._current_dir = "/var/log"
page_b.sftp_tab._current_dir = "/etc"
win.session_tabs.setCurrentIndex(0)
app.processEvents()
check("a tab switch shows THAT session's own tree (its browsed directory survives)",
      win.files_panel.stack.currentWidget() is page_a.sftp_tab
      and page_b.sftp_tab._current_dir == "/etc")
win.session_tabs.setCurrentIndex(1)
app.processEvents()
check("...and back to the other one", win.files_panel.stack.currentWidget() is page_b.sftp_tab)

node_c = new_node(mw, "gamma", "10.70.0.3")
page_c = win.add_session(node_c.data, password="pw")
app.processEvents()
check("a session born IN the mode joins the stack at once (its Files tab never shows)",
      win.files_panel.stack.count() == 3
      and page_c.tabs.count() == 2
      and win.files_panel.stack.indexOf(page_c.sftp_tab) >= 0)

win.close_page(page_c)
app.processEvents()
check("closing a tab in the mode hands its widget back before the session dies "
      "(no orphan page in the stack)",
      win.files_panel.stack.count() == 2
      and win.files_panel.stack.indexOf(page_c.sftp_tab) < 0)

check("a SPLIT PANE is not a page of the stack (it is built with_sftp=False)",
      page_a.tabs.count() == 2)
win.activateWindow()
QApplication.setActiveWindow(win)
app.processEvents()
win.act_split.trigger()
app.processEvents()
pane = win.split_pane
check("the split pane has no Files tab and no panel page (the shipped rule)",
      pane is not None and pane.sftp_tab is None and pane.tabs.count() == 1
      and win.files_panel.stack.count() == 2)
win.set_split_enabled(False)
app.processEvents()


# ════════════════════════════════════════════════════════════
# 4. The lazy channel open moves to connected_signal
# ════════════════════════════════════════════════════════════
print("== 4. the SFTP channel opens without a tab switch ==")

clear_cfg()
win2 = hold(ST.SSHTerminalWindow(ServerData(id="fp-lazy", alias="lazy", host="10.70.1.1",
                                             user="root"), None, password="pw"))
win2.show()
app.processEvents()
page_l = win2.session_tabs.widget(0)
check("the mode is restored from the config BEFORE the first tab could ever be switched",
      win2.act_files_panel.isChecked() is False and page_l._sftp_worker is None)
win2.act_files_panel.setChecked(True)
app.processEvents()
check("the panel is ON and its page really moved (the connection is still in flight)",
      win2.files_panel_on is True and page_l.tabs.count() == 2
      and page_l._sftp_worker is None)
# the transport appears and the thread announces the connection — the ONLY lazy-open trigger
# the mode has (there is no Files tab to switch to)
fake_sftp(win2, page_l)
page_l.terminal_thread.connected_signal.emit()
app.processEvents()
check("connected_signal opened the channel even though the Files tab was never current",
      page_l._sftp_worker is not None and win2.files_panel.stack.currentWidget()
      is page_l.sftp_tab)
worker_l = page_l._sftp_worker
close_window(win2)

# ...and for a session whose transport is ALREADY alive when the mode is switched on: the
# mode switch itself must reach the channel (there is no connected_signal to come back)
clear_cfg()
win3 = hold(ST.SSHTerminalWindow(ServerData(id="fp-late", alias="late", host="10.70.1.2",
                                            user="root"), None, password="pw"))
win3.show()
app.processEvents()
page_late = win3.session_tabs.widget(0)
fake_sftp(win3, page_late)
check("the session is connected but has no channel yet (its Files tab was never current)",
      win3.files_panel_on is False and page_late._sftp_worker is None
      and page_late.tabs.currentWidget() is page_late.widget)
win3.act_files_panel.setChecked(True)
app.processEvents()
check("switching the mode ON opens the channel for an already connected session",
      page_late._sftp_worker is not None and page_late.files_panel_on is True)
close_window(win3)


# ════════════════════════════════════════════════════════════
# 5. The fold (one owner-written key + the three-member arithmetic)
# ════════════════════════════════════════════════════════════
print("== 5. the fold and its width hand-over ==")

clear_cfg()
mw5 = MW.MainWindow()
mw5._autosave_timer.stop()
mw5._freshness_timer.stop()
mw5._status_checker = None
mw5.resize(1100, 640)
mw5.show()
app.processEvents()
node5 = new_node(mw5, "fold", "10.70.2.1")
win5 = hold(mw5._spawn_terminal_window(node5, password="pw"))
app.processEvents()
page5 = win5.session_tabs.widget(0)
fake_sftp(win5, page5)
win5.act_files_panel.setChecked(True)
app.processEvents()
app.processEvents()
sp5 = win5.centralWidget()
_expanded = sp5.sizes()[2]
check("the open panel asks for its declared width (not the layout's minimum)",
      _expanded > CL._CollapseStrip.STRIP_WIDTH + 40, f"sizes={sp5.sizes()}")

win5.files_panel.set_collapsed(True)
app.processEvents()
check("the fold caps the container at the strip (the ONE declared exception to gotcha #13)",
      win5.files_panel.is_collapsed() is True
      and win5.files_panel.maximumWidth() <= CL._CollapseStrip.STRIP_WIDTH
      and sp5.sizes()[2] <= CL._CollapseStrip.STRIP_WIDTH + 1,
      f"sizes={sp5.sizes()} maxW={win5.files_panel.maximumWidth()}")
check("the strip is visible and the body is not (a hidden member costs 0 px)",
      win5.files_panel._strip.isVisible() and not win5.files_panel._body.isVisible())
check("the fold is written by its owner into ONE ui_* key",
      read_cfg({}).get("ui_files_panel_collapsed") is True)
check("the freed width went to the columns on the LEFT (the three-member arithmetic)",
      sp5.sizes()[0] + sp5.sizes()[1] >= _expanded - CL._CollapseStrip.STRIP_WIDTH - 2,
      f"sizes={sp5.sizes()} was={_expanded}")

win5.files_panel.set_collapsed(False)
app.processEvents()
check("expanding releases the cap (it lives only while folded)",
      win5.files_panel.maximumWidth() > CL._CollapseStrip.STRIP_WIDTH
      and sp5.sizes()[2] >= _expanded - 10,
      f"sizes={sp5.sizes()} was={_expanded}")
check("...and the fold is remembered as a config key of its own",
      read_cfg({}).get("ui_files_panel_collapsed") is False)

# the arithmetic itself: the pure hand-over of the shared helper (three members)
class _FakeSplitter:
    def __init__(self, sizes):
        self._sizes = list(sizes)
    def count(self):
        return len(self._sizes)
    def sizes(self):
        return list(self._sizes)
    def setSizes(self, values):
        self._sizes = list(values)

_fs = _FakeSplitter([100, 500, 0])
CL.hand_over_splitter_width(_fs, 2, 200)
check("hand_over_splitter_width gives the member its width and keeps the others' PROPORTION",
      _fs.sizes()[2] == 200 and _fs.sizes()[0] < 100 and _fs.sizes()[1] < 500
      and sum(_fs.sizes()) == sum([100, 500, 0]),
      f"sizes={_fs.sizes()}")
check("...and a member that is NOT in the splitter is refused (never a short setSizes list)",
      CL.hand_over_splitter_width(_FakeSplitter([100, 500, 0]), 5, 200) is False)


# ════════════════════════════════════════════════════════════
# 6. The floors (the canvas keeps its columns)
# ════════════════════════════════════════════════════════════
print("== 6. the floors of the mode ==")

win5.act_files_panel.setChecked(False)
app.processEvents()
check("the OFF mode drops every floor (the shipped single-pane look comes back)",
      win5._v_splitter.minimumWidth() == 0 and page5.widget.minimumWidth() == 0
      and win5.files_panel.minimumWidth() == 0)
win5.resize(700, 520)
app.processEvents()
win5.act_files_panel.setChecked(True)
app.processEvents()
app.processEvents()
_cols = page5.widget.width() // max(1, int(page5.widget.cell_size[0]))
check(f"a NARROW window keeps the canvas at its column floor ({ST.FILES_PANEL_MIN_COLS} cells)",
      _cols >= ST.FILES_PANEL_MIN_COLS,
      f"cols={_cols} canvas={page5.widget.width()} cell={page5.widget.cell_size}")
check("the floor is BUILT from the live cell metrics (never a magic pixel number)",
      win5._v_splitter.minimumWidth() == int(page5.widget.cell_size[0] * ST.FILES_PANEL_MIN_COLS)
      or win5._v_splitter.minimumWidth() >= int(page5.widget.cell_size[0] * ST.FILES_PANEL_MIN_COLS) - 1,
      f"min={win5._v_splitter.minimumWidth()} cell={page5.widget.cell_size}")
check("the OPEN panel keeps its own floor (the pane cannot be squeezed away)",
      win5.files_panel.minimumWidth() >= 1,
      f"min={win5.files_panel.minimumWidth()}")
win5.act_files_panel.setChecked(False)
app.processEvents()


# ════════════════════════════════════════════════════════════
# 7. The mutual exclusion with the Files Commander
# ════════════════════════════════════════════════════════════
print("== 7. the panel and the Files Commander are mutually exclusive ==")

win5.commander.btn.click()          # the two-pane view ON (the panel is off)
app.processEvents()
check("with the panel OFF the commander is enabled and its mode is the session's",
      win5.commander.act.isEnabled() is True and page5.sftp_tab.commander is True
      and len(page5.sftp_tab.panes) == 2)
win5.act_files_panel.setChecked(True)
app.processEvents()
check("the mode is SINGLE-PANE: the panel forced the two-pane view OFF",
      page5.sftp_tab.commander is False and len(page5.sftp_tab.panes) == 1)
check("the corner control is DISABLED while the panel is on (its state is kept)",
      win5.commander.act.isEnabled() is False
      and bool(win5._commander_kept.get(page5.sftp_tab)) is True)
win5.act_files_panel.setChecked(False)
app.processEvents()
check("switching the panel off RESTORES the two-pane view the user had",
      page5.sftp_tab.commander is True and len(page5.sftp_tab.panes) == 2
      and win5.commander.act.isEnabled() is True
      and win5._commander_kept == {})

win5.act_files_panel.setChecked(True)
app.processEvents()
win5._dirty = False
win5.close()
app.processEvents()
check("a window closed WITH the panel on keeps the two-pane state in the config",
      read_cfg({}).get("ui_sftp_commander") is True)


# ════════════════════════════════════════════════════════════
# 8. The refusals and the scope
# ════════════════════════════════════════════════════════════
print("== 8. terminal_mode = tabs ignores the mode; a split pane has no tree ==")

clear_cfg()
merge_cfg({"terminal_mode": "tabs", "terminal_files_mode": "panel",
           "ui_files_panel_collapsed": True})
mw8 = MW.MainWindow()
mw8._autosave_timer.stop()
mw8._freshness_timer.stop()
mw8._status_checker = None
mw8.show()
app.processEvents()
node8 = new_node(mw8, "dock", "10.70.3.1")
dock = mw8._spawn_terminal_window(node8, password="pw")
app.processEvents()
content = dock.content
page8 = content.session_tabs.widget(0)
check("the dock content has NO Files panel at all (the mode needs window chrome)",
      not hasattr(content, "files_panel") and content.cmdlib_panel is not None)
check("...and the Files TAB stays exactly where the shipped dock keeps it",
      [page8.tabs.tabText(i) for i in range(page8.tabs.count())]
      == ["Terminal", "Files", "History"] and page8._files_panel_on is False)
check("the window-mode settings are simply ignored by the dock (independent settings)",
      read_cfg({}).get("terminal_mode") == "tabs"
      and read_cfg({}).get("terminal_files_mode") == "panel")
cache = mw8._terminal_windows
mw8._dirty = False
mw8.close()
app.processEvents()


# ════════════════════════════════════════════════════════════
# 9. The persistence (one merged geometry write)
# ════════════════════════════════════════════════════════════
print("== 9. the persistence of the mode ==")

clear_cfg()
merge_cfg({"terminal_files_mode": "panel"})   # the SETTING decides how a window opens
mw9 = MW.MainWindow()
mw9._autosave_timer.stop()
mw9._freshness_timer.stop()
mw9._status_checker = None
mw9.show()
app.processEvents()
node9 = new_node(mw9, "persist", "10.70.4.1")
win9 = hold(mw9._spawn_terminal_window(node9, password="pw"))
app.processEvents()
page9 = win9.session_tabs.widget(0)
fake_sftp(win9, page9)
app.processEvents()
win9.files_panel.set_collapsed(True)
app.processEvents()
win9._dirty = False
win9.close()
app.processEvents()
_cfg9 = read_cfg({})
check("the window's SINGLE geometry write carries the FOLD of the panel",
      _cfg9.get("ui_files_panel_collapsed") is True
      and isinstance(_cfg9.get("ui_window_geometry_terminal"), dict)
      and "ui_terminal_split" in _cfg9 and "ui_sftp_commander" in _cfg9)
check("...and the MODE is NOT written back (the setting stays the one owner of it)",
      "ui_files_panel" not in _cfg9
      and _cfg9.get("terminal_files_mode") == "panel")
check("...and nothing the panel does NOT own was written (no width key, no ratio)",
      not any(k.startswith("ui_files_panel_") and k.endswith("width") for k in _cfg9)
      and len([k for k in _cfg9 if k.startswith("ui_files_panel")]) == 1)

win10 = hold(ST.SSHTerminalWindow(ServerData(id="fp-restore", alias="restore", host="10.70.4.2",
                                             user="root"), None, password="pw"))
win10.show()
app.processEvents()
page10 = win10.session_tabs.widget(0)
check("the restore comes back through the ONE action (the checkmark, the stack and the fold)",
      win10.files_panel_on is True and win10.act_files_panel.isChecked() is True
      and win10.files_panel.is_collapsed() is True
      and win10.files_panel.stack.count() == 1
      and [page10.tabs.tabText(i) for i in range(page10.tabs.count())]
      == ["Terminal", "History"])
win10.files_panel.set_collapsed(False)
app.processEvents()
check("expanding the restored panel comes back to the declared opening width",
      win10.files_panel.width() > CL._CollapseStrip.STRIP_WIDTH + 40,
      f"w={win10.files_panel.width()}")
close_window(win10)

write_cfg({"terminal_files_mode": "panel", "ui_files_panel_collapsed": 1})
check("a foreign/broken FOLD value falls back to the expanded panel",
      ST.load_files_panel_settings() == {"mode": "panel", "collapsed": False},
      str(ST.load_files_panel_settings()))
write_cfg({"terminal_files_mode": "panel", "ui_files_panel_collapsed": True})
check("...and a real pair is read as it stands",
      ST.load_files_panel_settings() == {"mode": "panel", "collapsed": True},
      str(ST.load_files_panel_settings()))
clear_cfg()


# ════════════════════════════════════════════════════════════
# 10. A panel that dies inside its own open (the teardown race)
# ════════════════════════════════════════════════════════════
print("== 10. a panel that dies inside its own open leaves no state behind ==")

clear_cfg()
_win_race = hold(ST.SSHTerminalWindow(ServerData(id="fp-race", alias="race", host="10.70.6.1",
                                                user="root"), None, password="pw"))
_win_race.show()
app.processEvents()
_page_race = _win_race.session_tabs.widget(0)
check("the race scenario starts from the shipped look (3 tabs, the mode off)",
      [_page_race.tabs.tabText(i) for i in range(_page_race.tabs.count())]
      == ["Terminal", "Files", "History"] and _win_race.files_panel_on is False)
# the panel's C++ object dies with the window — PySide6 reports the first touch like this
_win_race.files_panel.set_collapsed = lambda *a, **k: (_ for _ in ()).throw(
    RuntimeError("Internal C++ object (_FilesPanel) already deleted."))
_win_race.set_files_panel_enabled(True)   # the user's click, into the dying panel
app.processEvents()
check("the window does NOT claim the panel is on (the flag is not left behind)",
      _win_race.files_panel_on is False)
check("…and the View action is not checked over a panel that is not there",
      _win_race.act_files_panel.isChecked() is False)
check("…and the panel is really hidden", _win_race.files_panel.isHidden())
check("…every session got its Files tab BACK (no widget stranded in the panel)",
      [_page_race.tabs.tabText(i) for i in range(_page_race.tabs.count())]
      == ["Terminal", "Files", "History"]
      and _page_race.tabs.indexOf(_page_race.sftp_tab) == 1)
check("…and the page's own half of the mode agrees with reality",
      _page_race.files_panel_on is False and _win_race.files_panel.stack.count() == 0)
# the ONE switch is idempotent afterwards: the next press reports the same truth
_win_race.set_files_panel_enabled(True)
app.processEvents()
check("a second press of the switch is refused the same way (the state stays honest)",
      _win_race.files_panel_on is False and _win_race.act_files_panel.isChecked() is False)
del _win_race.files_panel.set_collapsed   # the instance shadow goes, the class method is back
close_window(_win_race)


# ════════════════════════════════════════════════════════════
# 11. The chrome (live i18n) and the release state
# ════════════════════════════════════════════════════════════
print("== 11. live i18n and the release state ==")

LANGS = load_i18n_langs(ROOT)
check_i18n_parity(LANGS)
check_i18n_format(LANGS)

_NEW_KEYS = ("terminal.files_panel", "terminal.files_panel_tooltip",
             "terminal.files_panel_collapse_tooltip", "terminal.files_panel_expand_tooltip",
             # v1.7.1.1: the settings hub's row of the Files display mode and its two values
             "settings.terminal.files_mode", "settings.terminal.files_mode.tab",
             "settings.terminal.files_mode.panel")
_missing = {code: [k for k in _NEW_KEYS if not str(data.get(k) or "").strip()]
            for code, data in LANGS.items()}
check(f"the {len(_NEW_KEYS)} keys of the Files surface are present and non-empty in every language",
      not any(_missing.values()), str({c: v for c, v in _missing.items() if v}))
check("the panel's own header REUSES the tab's title (no second spelling of \"Files\")",
      "terminal.files_panel_title" not in LANGS["en"]
      and 't("sftp.tab_files")' in open(
          __import__("os").path.join(ROOT, "modules", "terminal_files_panel.py"),
          encoding="utf-8").read())

# the live chrome: ONE window with the mode on, re-texted in two languages
_win_i18n = hold(ST.SSHTerminalWindow(ServerData(id="fp-i18n", alias="i18n", host="10.70.5.1",
                                                 user="root"), None, password="pw"))
_win_i18n.show()
app.processEvents()
_win_i18n.act_files_panel.setChecked(True)
app.processEvents()
retranslated = []
for code in ("ru", "de"):
    i18n.set_language(code)
    _win_i18n.retranslate()
    app.processEvents()
    # the expected strings are read WHILE that language is active (the check below runs after
    # the loop, when the language is back to en)
    retranslated.append((code, _win_i18n.act_files_panel.text(),
                         _win_i18n.files_panel._strip.toolTip(),
                         _win_i18n.files_panel._collapse_btn.toolTip(),
                         _win_i18n.files_panel._title.text(),
                         i18n.t("terminal.files_panel"), i18n.t("terminal.files_panel_expand_tooltip"),
                         i18n.t("terminal.files_panel_collapse_tooltip"), i18n.t("sftp.tab_files")))
check("a language switch re-texts the action and the panel's own strings",
      all(act == want_act and strip == want_strip and fold == want_fold
          and title == want_title
          for _code, act, strip, fold, title, want_act, want_strip, want_fold, want_title
          in retranslated),
      str(retranslated))
check("...and the translations are really translated (not the English text)",
      all(act != "Files Panel" for _code, act, *_rest in retranslated), str(retranslated))

# the settings hub's new row — the SECOND surface of the same choice, re-texted by its own tab
_settings_i18n = SettingsDialog(None)
_rows_i18n = []
for code in ("ru", "de"):
    i18n.set_language(code)
    _settings_i18n.retranslate()
    app.processEvents()
    _rows_i18n.append((code,
                       _settings_i18n._lbl_files_mode.text(),
                       _settings_i18n.files_mode_combo.itemText(0),
                       _settings_i18n.files_mode_combo.itemText(1),
                       i18n.t("settings.terminal.files_mode"),
                       i18n.t("settings.terminal.files_mode.tab"),
                       i18n.t("settings.terminal.files_mode.panel")))
check("a language switch re-texts the 'Files display mode' row of the 'Terminal' tab",
      all(label == want_label and tab == want_tab and panel == want_panel
          for _code, label, tab, panel, want_label, want_tab, want_panel in _rows_i18n),
      str(_rows_i18n))
_settings_i18n.close()
i18n.set_language("en")
_win_i18n.retranslate()
app.processEvents()
close_window(_win_i18n)

check_release_state(ROOT)
check("§11 EXPECTED_APP_VERSION is the release this file describes (the 1.7.1 patch, or later)",
      releases_at_least(EXPECTED_APP_VERSION, "1.7.1")
      and VERSION_FORMAT_RE.fullmatch(EXPECTED_APP_VERSION) is not None,
      EXPECTED_APP_VERSION)
check("§11 the pin counts the shipped release (863 + the 4 keys of the Files panel"
      " + the 3 of the Files display mode + the 4 of the v1.7.1.2 device choice"
      " + the 4 of the v1.7.2 containers + the 19 of v1.7.3: the Send-to row and its dialog,"
      " the busy/progress/done/failed reports, the two-sided conflict facts, the remembered-folder"
      " sentence, the two drop refusals and Word wrap + the 17 of v1.7.4rc1: the local source switch"
      " of a pane, its two refusals, the permanent-delete warning and the local file-surface sentences"
      " + the 1 of v1.7.4rc2: the refusal of a move that would cross the two sources"
      " + the 4 of v1.7.5: the Files settings page, its ceiling row and warning, and the"
      " truncation notice + the 20 of v1.8: the elevated pane + the 41 of v1.8.1: the trust surface,"
      " and v1.8.1.1 adds ONE: the send identity sentence) and v1.8.2 adds SIXTEEN: the library file — the History door, the backup ring and the import/export pair — and v1.8.3 adds TWENTY-THREE: the Plugins window (its chrome, its three columns and its export) and v1.8.4 adds TEN: the whole-map layout, the reverse traversal and the inode fact",
      EXPECTED_I18N_KEYS == 863 + 4 + 3 + 4 + 4 + 19 + 17 + 1 + 4 + 6 + 20 + 41 + 1 + 16 + 23 + 10, str(EXPECTED_I18N_KEYS))
check("§11 VERSION_FORMAT stays `0.9` (the mode lives in config.json, not in the project file)",
      __import__("version").VERSION_FORMAT == "0.9")
check("§11 no new dependency was added for the panel (the four pinned ones)",
      all(f"{d}>=" in open("requirements.txt", encoding="utf-8").read()
          for d in ("PySide6", "paramiko", "keyring", "wcwidth")))

# every container of this file goes down through the ONE teardown path (a live QThread left
# behind would abort the process at exit — the suite reads the exit code, not the log)
teardown_all()
finish()
