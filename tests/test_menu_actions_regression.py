# -*- coding: utf-8 -*-
"""v1.2.4-fix — REGRESSION: the real click path on checkable menu items (QAction.trigger()).

The incident: the manual testing did not confirm the multi-input — "I put the check in
View → Multi-input, and nothing happens: no frame, no badges, no plaque". The root
(the empirics on PySide6 6.11.1, offscreen): the auto-connection of QMenu.addAction(text, slot)
— what MainWindow._add_menu_action does — emits QAction.triggered into the Python slot
WITHOUT arguments (an explicit action.triggered.connect(slot) passes the new state, and
the auto-connection — not). _toggle_multi_input(checked=None) fell into the no-op branch
(target = the current state) — the mode from the menu was not enabled nor disabled at all;
only the checkmark moved (Qt itself flips it), F12 was silent (the shortcut is attached
only in the active mode).

The fix: the item is connected to toggled(bool) (the new state — the same as with the explicit
triggered.connect); the checked=None in _toggle_multi_input — now a real toggle.

This test goes EXACTLY the path of a user click: act.trigger() — Qt itself
inverts the checked and emits the signals (that is how both the menu item and the F12 shortcut on
the same QAction work). SSH is not needed: the hub/provider/the plaque live without the terminals; for
the check of the frame/badge one duck-typed fake container is put into the registry.

v1.3.3.3 (ROADMAP task 2/5) extends the same real-click discipline to four new menu items:
View → Zoom In / Zoom Out / Reset zoom (they must move the view scale, with the two new
vector icons) and "Check statuses now" (it must start exactly ONE round for the selection,
with the probes off the GUI thread).

Run:  python tests/test_menu_actions_regression.py   (from the project root) or python tests/run_all.py
"""
import inspect
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtWidgets import QApplication, QTabWidget, QWidget  # noqa: E402

app = QApplication(sys.argv)

import i18n  # noqa: E402
import ui.main_window as MW  # noqa: E402
import ui.sidebar as SB  # noqa: E402
from models.server import ServerData  # noqa: E402
from modules.multi_input import get_hub, MULTI_FRAME_OBJECT_NAME  # noqa: E402
from services.status_checker import StatusChecker  # noqa: E402
from ui.icons import get_icon  # noqa: E402


class _FakePageData:
    alias = "fake-a"


class _FakePage:
    """The registry record (duck-typing TerminalSessionPage): only what
    _on_multi_changed/_multi_refresh_ui (_host_window) use. terminal_thread=None —
    the broadcast is not checked here (covered by test_multi_input_e2e.py)."""

    def __init__(self, host):
        self._host_window = host
        self.widget = None
        self.terminal_thread = None


class _FakeHost(QWidget):
    """Duck-typing of SSHTerminalWindow/TerminalDockContent for apply_container_highlight:
    session_tabs (QTabWidget) + the pages with .server_data.alias + _multi_base_title."""

    def __init__(self):
        super().__init__()
        self.session_tabs = QTabWidget()
        page = QWidget()
        page.server_data = _FakePageData()
        self.session_tabs.addTab(page, "fake-a")
        self._multi_base_title = "fake host"


class _FakeChecker:
    """Records the calls of the on-demand status path.

    NEVER touches the network and never spawns a thread — the real
    ``StatusChecker.start_round()`` is the only place that builds a ``_ProbeThread``,
    and this double replaces it wholesale (the module-level import seam).
    """

    def __init__(self):
        self.rounds = []

    def start_round(self, server_ids=None):
        self.rounds.append(list(server_ids) if server_ids is not None else None)
        return True


def menu_action(window, menu_key, action_key):
    """The QAction of a menu item — found through the ``_menu_i18n`` registry.

    Never ``action.menu()``: PySide6 6.11 destroys the C++ QMenu when the temporary
    Python wrapper of the parent QAction dies (gotcha #9) — the registry holds the
    wrapper permanently, so this is the safe path (the established test pattern).
    """
    items = [w for w, k in window._menu_i18n if k == action_key]
    assert items, f"no QAction registered for {action_key!r}"
    return items[-1]


hub = get_hub()   # the process singleton (the same one as in MainWindow and the widgets)
hub.reset()

mw = MW.MainWindow()
mw._autosave_timer.stop()
mw.show()
app.processEvents()

check("precondition: the mode is off, the plaque is hidden, the item is unchecked",
      hub.active is False and mw._multi_plaque.isHidden()
      and not mw.act_multi_input.isChecked())

# One fake session in the registry — for the counter/badge/frame
host = _FakeHost()
mw._terminal_windows.append(_FakePage(host))
app.processEvents()

# ════════════════════════════════════════════════════════════
# 1. THE THING THAT BROKE: the "View → Multi Input" click (act.trigger() = a user click)
# ════════════════════════════════════════════════════════════
print("== 1. the click on the menu item (the real Qt-event path) ==")
mw.act_multi_input.trigger()
app.processEvents()

check("the click: the hub is ACTIVE (before the fix — a no-op, the mode was not enabled)",
      hub.active is True, f"active={hub.active}")
check("the click: the checkmark on the item", mw.act_multi_input.isChecked())
check("the click: the plaque 'MULTI: 1 sessions' is visible with the counter",
      not mw._multi_plaque.isHidden()
      and mw._multi_label.text() == i18n.t("terminal.multi_status", count=1),
      repr(mw._multi_label.text()))
check("the click: the container's frame (the objectName) + the tab's badge 'MULTI · fake-a'",
      host.session_tabs.objectName() == MULTI_FRAME_OBJECT_NAME
      and host.session_tabs.tabText(0) == i18n.t("terminal.multi_tab_badge", alias="fake-a"),
      f"objectName={host.session_tabs.objectName()!r} tab={host.session_tabs.tabText(0)!r}")
check("the click: the prefix of the session window's title",
      host.windowTitle() == i18n.t("terminal.multi_title_prefix") + "fake host",
      repr(host.windowTitle()))
check("the click: the status message (status.multi_enabled)",
      mw.statusBar().currentMessage() == i18n.t("status.multi_enabled"),
      repr(mw.statusBar().currentMessage()))
check("the click: the F12 shortcut is ATTACHED (the exit from the mode)",
      mw.act_multi_input.shortcut().toString() == "F12",
      repr(mw.act_multi_input.shortcut().toString()))

# ════════════════════════════════════════════════════════════
# 2. Exit: a second click = what F12 does (the shortcut on the same QAction)
# ════════════════════════════════════════════════════════════
print("== 2. the exit by a second click / F12 ==")
mw.act_multi_input.trigger()
app.processEvents()

check("the exit: the mode is off, the checkmark is removed",
      hub.active is False and not mw.act_multi_input.isChecked())
check("the exit: the plaque is hidden, the highlight is reset (the frame / the badge / the title)",
      mw._multi_plaque.isHidden()
      and host.session_tabs.objectName() == ""
      and host.session_tabs.tabText(0) == "fake-a"
      and host.windowTitle() == "fake host",
      f"objectName={host.session_tabs.objectName()!r} tab={host.session_tabs.tabText(0)!r} "
      f"title={host.windowTitle()!r}")
check("the exit: the F12 shortcut is removed (the key goes back to the shell)",
      mw.act_multi_input.shortcut().toString() == "")

# ════════════════════════════════════════════════════════════
# 3. The fallback path: an argumentless call — a real toggle (before the fix — a no-op)
# ════════════════════════════════════════════════════════════
print("== 3. _toggle_multi_input() without an argument ==")
mw._toggle_multi_input()
check("the argumentless call: the mode is ON (before the fix — a no-op)", hub.active is True)
mw._toggle_multi_input()
check("the repeated argumentless call: the mode is off", hub.active is False)

# ════════════════════════════════════════════════════════════
# 4. The ✕ exit button on the plaque (an explicit False) — with the mode active
# ════════════════════════════════════════════════════════════
print("== 4. the ✕ button on the plaque ==")
mw.act_multi_input.trigger()   # enabling via the menu path
app.processEvents()
check("✕: the mode is active before the click on the button", hub.active is True)
mw._multi_exit_btn.click()
app.processEvents()
check("✕: the mode is off, the checkmark is removed, the plaque is hidden",
      hub.active is False and not mw.act_multi_input.isChecked()
      and mw._multi_plaque.isHidden())

# cleanup: we remove the fake from the registry (the real teardown does this on destroyed)
mw._terminal_windows.clear()

# ════════════════════════════════════════════════════════════
# 5. v1.3.3.3 (task 2): the zoom menu items — a real click moves the view scale
# ════════════════════════════════════════════════════════════
print("== 5. View → Zoom In / Zoom Out / Reset zoom (v1.3.3.3) ==")

act_zoom_in = menu_action(mw, "menu.view", "view.zoom_in")
act_zoom_out = menu_action(mw, "menu.view", "view.zoom_out")
act_reset_zoom = menu_action(mw, "menu.view", "view.reset_zoom")

act_reset_zoom.trigger()
app.processEvents()
z0 = mw.view.zoom
check("zoom: Reset zoom puts the window at exactly 100%",
      abs(z0 - 1.0) < 1e-9 and abs(mw.view.transform().m11() - 1.0) < 1e-9, str(z0))

act_zoom_in.trigger()
app.processEvents()
z_in = mw.view.zoom
check("zoom in: a click on the menu item scales the view up by the step",
      z_in > z0 and abs(z_in - z0 * mw.view.ZOOM_STEP) < 1e-9, f"{z0} -> {z_in}")
check("zoom in: the reported zoom and the real transform agree",
      abs(mw.view.transform().m11() - z_in) < 1e-9,
      f"zoom={z_in} m11={mw.view.transform().m11()}")
check("zoom in: the percentage in the status bar follows",
      mw.zoom_label.text() == f"{int(round(z_in * 100))}%", mw.zoom_label.text())

act_zoom_out.trigger()
app.processEvents()
check("zoom out: a click returns to the starting scale",
      abs(mw.view.zoom - z0) < 1e-9 and abs(mw.view.transform().m11() - z0) < 1e-9,
      str(mw.view.zoom))

act_zoom_in.trigger()
act_zoom_in.trigger()
act_reset_zoom.trigger()
app.processEvents()
check("reset zoom: the menu item returns the scale to 1.0 after two steps",
      abs(mw.view.zoom - 1.0) < 1e-9 and abs(mw.view.transform().m11() - 1.0) < 1e-9,
      str(mw.view.zoom))

# The zoom pair carries the two NEW vector icons (ui/icons.py — the project draws them)
for _name in ("zoom_in", "zoom_out"):
    _icon = get_icon(_name)
    _img = _icon.pixmap(20, 20).toImage()
    _ink = sum(1 for y in range(_img.height()) for x in range(_img.width())
               if _img.pixelColor(x, y).alpha() > 0)
    check(f"icon: get_icon('{_name}') is drawn (the ink on the transparent canvas)",
          not _icon.isNull() and _ink > 25, f"ink={_ink}")
check("icon: the in/out pair differs (the +/- sign inside the lens is really there)",
      get_icon("zoom_in").pixmap(20, 20).toImage()
      != get_icon("zoom_out").pixmap(20, 20).toImage())
check("menu: the zoom items carry the vector icons",
      not act_zoom_in.icon().isNull() and not act_zoom_out.icon().isNull())

# ════════════════════════════════════════════════════════════
# 6. v1.3.3.3 (task 5): "Check statuses now" — exactly ONE round for the selection
# ════════════════════════════════════════════════════════════
print("== 6. Check statuses now (v1.3.3.3) ==")

made = []
for _i in (1, 2, 3):
    made.append(mw.scene.add_server(ServerData(id=f"chk-{_i}", alias=f"chk-{_i}",
                                               host=f"10.99.0.{_i}", user="root")))
mw.scene.clearSelection()
app.processEvents()

fake = _FakeChecker()
mw._status_checker = fake

started = mw._check_statuses_now(made[0])
check("no selection: the node the menu was opened on is probed (one round, one server)",
      started is True and fake.rounds == [["chk-1"]], str(fake.rounds))

fake.rounds.clear()
for _n in made[:2]:
    _n.setSelected(True)
app.processEvents()
started = mw._check_statuses_now(made[2])
check("with a selection: exactly ONE round, only the SELECTED ids",
      started is True and len(fake.rounds) == 1 and sorted(fake.rounds[0]) == ["chk-1", "chk-2"],
      str(fake.rounds))
check("the clicked node is ignored while a selection exists (the selection wins)",
      "chk-3" not in fake.rounds[0], str(fake.rounds))

fake.rounds.clear()
mw.scene.clearSelection()
app.processEvents()
started = mw._check_statuses_now()
check("no selection and no node: nothing to probe, no round starts",
      started is False and fake.rounds == [], str(fake.rounds))

# The menu/toolbar path hands QAction.triggered's bool over as the first argument
for _n in made[:2]:
    _n.setSelected(True)
app.processEvents()
fake.rounds.clear()
mw._check_statuses_now(True)   # exactly what QAction.triggered delivers to a plain slot
check("a QAction.triggered bool is not mistaken for a node (gotchas #10/#12)",
      len(fake.rounds) == 1 and sorted(fake.rounds[0]) == ["chk-1", "chk-2"],
      str(fake.rounds))
mw.scene.clearSelection()

fake.rounds.clear()
mw._status_checker = None
check("without a StatusChecker the action is a silent no-op (never raises)",
      mw._check_statuses_now(made[0]) is False and fake.rounds == [])

# The same method is the Edit-menu item AND both context menus' entry
edit_status = [w for w, k in mw._menu_i18n if k == "ctx.check_status"]
check("the action is a permanent Edit-menu item (a context menu is rebuilt on every click)",
      len(edit_status) == 1
      and edit_status[0] in mw._hotkey_targets.get("node.check_status", []))
check("the sidebar context menu composition gained 'check_status'",
      any(e is not None and e[0] == "check_status" for e in SB.CONTEXT_MENU_ITEMS),
      str(SB.CONTEXT_MENU_ITEMS))

# The GUI thread is never blocked: start_round() only builds the target list and starts
# a QThread — the probing lives in _ProbeThread (the source is the contract here).
_src = inspect.getsource(StatusChecker.start_round)
check("the round starter only builds targets + starts a QThread (no probe inline)",
      "_ProbeThread(" in _src and "thread.start()" in _src
      and "probe_ssh(" not in _src and "_probe_one" not in _src)

mw._dirty = False
finish()
