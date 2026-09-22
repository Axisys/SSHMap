# -*- coding: utf-8 -*-
"""v1.2.4.1 — Collapsing the sidebar and the map into a thin line (buttons + menu, ROADMAP v1.2.4.1).

The thematic test of the release (the "new thematic file" convention): offscreen, without the network
(the status probes are instantly offline; the terminal sessions — on the fake threads).

§1 The structure: QSplitter[container_sidebar | container_map]; setCollapsible(0/1)=False
   (the handle does not reach zero); the strips _CollapseStrip 18px (hidden in the expanded
   state); the corner buttons with the rhombus "◇" (the bottom row of the SidebarPanel / the overlay in the right
   BOTTOM corner of MapView — the top is reserved for the minimap, v1.2.4.1-fix); the items
   of the "View" menu act_show_sidebar/act_show_map — the checkable with the pair of icons.

§2 The sidebar — THREE paths: the corner button (the click), the click on the strip (QTest.mouseClick),
   the menu item (trigger() — PySide6 6.11: the click inverts the checked itself and emits).
   Each path: the panel hide()/show(), the strip in its place, the check of the item = the state,
   the persistence in config.json.

§3 The map — the same three paths (the overlay button + the repositioning by resizeEvent — the right
   bottom corner, the strip, the menu).

§4 The prohibition of the double collapsing (v1.2.4.1-fix, the QA request): both the panels
   must not be collapsed SIMULTANEOUSLY (a window-"shell" of two strips is not allowed,
   even with the open dock). The first panel is collapsed; the attempt to collapse the second — all
   three paths (the menu/the button/setChecked) are rejected: the panel stays expanded, the check
   does not diverge from the mechanics, the status hint; after the expansion of the first the second is
   collapsed again.

§5 The guard no-op on the collapsed map: fit_to_content/_center_view/reveal-a-node/the navigation
   of the search (Enter/Shift+Enter) — without exceptions and without the auto-show of the map; the selection and
   the statuses work in the background (scene-based), the dots appear on the expansion.

§6 The PNG/PDF/drawio export on the collapsed map: the files are created (the scene renders,
   the view is not needed).

§7 terminal_mode="tabs": the map is collapsed → the dock "Terminals" lives, the session types,
   the tear-off of the dock into a window and back work (the QDockWidget is independent of the splitter).

§8 The persistence: ui_sidebar_collapsed/ui_map_collapsed in config.json (the merge write —
   the foreign keys are not reset); a new window applies the state on the start AFTER
   restoreState(); a manual write of BOTH the keys True (the old config) — on the start
   only the sidebar is applied, the map stays expanded (the invariant §4); a partial
   expansion writes only its own key.

§9 The splitter handle does not reach zero: setSizes([0, …]) is clamped by the minimumWidth
   of the container (160/240).

§10 The i18n parity (421 = 417 + 3 + 1: view.toggle_map + the tooltips of the strips +
    status.collapse_both_forbidden) + the release state (the pin _common.py; the version
    is unchanged — v1.2.4.1-fix).

Run: python tests/test_view_toggles.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_release_state, cfg_path, merge_cfg, clear_cfg)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QDockWidget

app = QApplication(sys.argv)

# Network is forbidden in tests: the status probes return the result instantly.
import services.status_checker as _SC
_SC.probe_ssh = lambda host, port, timeout=3.0: "offline"

import i18n
import modules.ssh_terminal as ST
from models.server import ServerData
import ui.main_window as MW


# ════════════════════════════════════════════════════════════
# The harness
# ════════════════════════════════════════════════════════════
# QMessageBox — no modals offscreen; question → Discard (closing without saving).
boxes = []

from _fakes import FakeSSHThread as _FakeSSHThreadBase, QuestionStub

MW.QMessageBox.question = QuestionStub(
    QMessageBox.Discard,
    record=lambda title, text: boxes.append(("question", title))).install(MW)
MW.QMessageBox.critical = staticmethod(lambda *a, **k: boxes.append(("critical",)))
MW.QMessageBox.warning = staticmethod(lambda *a, **k: boxes.append(("warning",)))
MW.QMessageBox.information = staticmethod(lambda *a, **k: boxes.append(("information",)))


class _FakeThread(_FakeSSHThreadBase):
    """An idle thread (the same API as SSHTerminalThread) without a channel: send_data — a no-op."""
    RECORD = None


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeThread  # all the sessions in this file — on the fake


def make_main():
    """An offscreen MainWindow with a stopped autosave timer (determinism)."""
    w = MW.MainWindow()
    w._autosave_timer.stop()
    w.resize(1200, 800)
    w.show()
    app.processEvents()
    return w


STRIP_W = 18

# ════════════════════════════════════════════════════════════
# 1. Structure: containers, strips, buttons, menu items
# ════════════════════════════════════════════════════════════
print("== 1. structure ==")

clear_cfg()
win = make_main()
sp = win._splitter
check("QSplitter: two members (the panel containers)", sp.count() == 2, f"count={sp.count()}")
check("setCollapsible(0)=False and setCollapsible(1)=False",
      not sp.isCollapsible(0) and not sp.isCollapsible(1))
check("the sidebar lives in the container [sidebar | strip]",
      win.sidebar.parentWidget() is win._sidebar_container,
      f"parent={win.sidebar.parentWidget()}")
check("the map lives in the container [strip | view]",
      win.view.parentWidget() is win._map_container)
for name, strip in (("sidebar", win._sidebar_strip), ("map", win._map_strip)):
    check(f"the {name} strip: a fixed width of {STRIP_W}px",
          strip.minimumWidth() == STRIP_W and strip.maximumWidth() == STRIP_W,
          f"min={strip.minimumWidth()} max={strip.maximumWidth()}")
    check(f"the {name} strip: hidden in the expanded state", not strip.isVisible())
check("the sidebar's corner button: a QToolButton in the panel's bottom row (the right corner)",
      win.sidebar.collapse_btn.parentWidget() is win.sidebar)
check("the map's corner button: an overlay on MapView (a child of view)",
      win._map_collapse_btn.parentWidget() is win.view)
# v1.2.4.1-fix: the icon — a "◇" rhombus by both panels; the map button — in the bottom RIGHT corner
check("the corner buttons: the rhombus icon is set (not null)",
      not win.sidebar.collapse_btn.icon().isNull()
      and not win._map_collapse_btn.icon().isNull())
check("the map button: the bottom RIGHT corner of view (the top is reserved for the minimap)",
      win._map_collapse_btn.y() > win.view.height() // 2
      and win._map_collapse_btn.x() + win._map_collapse_btn.width() <= win.view.width(),
      f"btn=({win._map_collapse_btn.x()},{win._map_collapse_btn.y()}) "
      f"view={win.view.width()}x{win.view.height()}")
check("act_show_sidebar: checkable, checked by default, the icon is not null",
      win.act_show_sidebar.isCheckable() and win.act_show_sidebar.isChecked()
      and not win.act_show_sidebar.icon().isNull())
check("act_show_map: checkable, checked by default, the icon is not null",
      win.act_show_map.isCheckable() and win.act_show_map.isChecked()
      and not win.act_show_map.icon().isNull())
from ui.icons import get_icon
check("the pair of icons in _DRAWERS: sidebar_panel/map_panel render",
      not get_icon("sidebar_panel").isNull() and not get_icon("map_panel").isNull())

# ════════════════════════════════════════════════════════════
# 2. The sidebar — three collapse/expand paths
# ════════════════════════════════════════════════════════════
print("== 2. sidebar: three control paths ==")

# ── path A: the corner button (the bottom row of the sidebar) ─────────────────────────────
win.sidebar.collapse_btn.click()
app.processEvents()
check("the button: the sidebar is collapsed (the panel is hidden, the strip is shown)",
      win.sidebar.isHidden() and win._sidebar_strip.isVisible())
check("the button: the container = the strip width",
      win._sidebar_container.width() == STRIP_W, f"w={win._sidebar_container.width()}")
check("the button: the menu item is unchecked (checked = expanded)", not win.act_show_sidebar.isChecked())
check("the button: config ui_sidebar_collapsed=True",
      i18n.load_config().get("ui_sidebar_collapsed") is True)

# ── path B: the click on the strip (a real mouse event) ───────────────────────
QTest.mouseClick(win._sidebar_strip, Qt.LeftButton)
app.processEvents()
check("a click on the strip: the sidebar is expanded",
      not win.sidebar.isHidden() and not win._sidebar_strip.isVisible())
check("a click on the strip: the menu item is checked", win.act_show_sidebar.isChecked())
check("a click on the strip: config ui_sidebar_collapsed=False",
      i18n.load_config().get("ui_sidebar_collapsed") is False)

# ── path C: the menu item "View → Sidebar" (PySide6 6.11: trigger() = a click —
#    inverts checked itself and emits; a double setChecked+trigger is forbidden) ──
win.act_show_sidebar.trigger()
app.processEvents()
check("the menu (trigger #1): the sidebar is collapsed, the item is unchecked",
      win.sidebar.isHidden() and not win.act_show_sidebar.isChecked())
win.act_show_sidebar.trigger()
app.processEvents()
check("the menu (trigger #2): the sidebar is expanded, the item is checked",
      not win.sidebar.isHidden() and win.act_show_sidebar.isChecked())

# ════════════════════════════════════════════════════════════
# 3. The map — the same three paths (+ repositioning the overlay button on resize)
# ════════════════════════════════════════════════════════════
print("== 3. map: three control paths ==")

win._map_collapse_btn.click()
app.processEvents()
check("the button: the map is collapsed (view is hidden, the strip is shown)",
      win.view.isHidden() and win._map_strip.isVisible())
check("the button: the map container = the strip width",
      win._map_container.width() == STRIP_W, f"w={win._map_container.width()}")
check("the button: the 'Map' item is unchecked", not win.act_show_map.isChecked())
check("the button: config ui_map_collapsed=True",
      i18n.load_config().get("ui_map_collapsed") is True)

QTest.mouseClick(win._map_strip, Qt.LeftButton)
app.processEvents()
check("a click on the strip: the map is expanded",
      not win.view.isHidden() and not win._map_strip.isVisible())
check("a click on the strip: the 'Map' item is checked", win.act_show_map.isChecked())

win.act_show_map.trigger()
app.processEvents()
check("the menu (trigger #1): the map is collapsed, the item is unchecked",
      win.view.isHidden() and not win.act_show_map.isChecked())
win.act_show_map.trigger()
app.processEvents()
check("the menu (trigger #2): the map is expanded, the item is checked",
      not win.view.isHidden() and win.act_show_map.isChecked())

# the overlay button follows the resizeEvent (the MapView.resized signal) — in the bottom RIGHT corner
win.resize(1400, 800)
app.processEvents()
btn = win._map_collapse_btn
check("the overlay button after a resize: the bottom right corner of view",
      btn.y() + btn.height() >= win.view.height() - 12
      and btn.x() + btn.width() <= win.view.width()
      and btn.y() > win.view.height() // 2,
      f"btn=({btn.x()},{btn.y()}) view={win.view.width()}x{win.view.height()}")

# ════════════════════════════════════════════════════════════
# 3b. v1.4.6: the Sidebar / Map toggles on the toolbar
# ════════════════════════════════════════════════════════════
print("== 3b. the toolbar mirrors of the two panel toggles (v1.4.6) ==")

check("the toolbar carries a button for each panel toggle (the View items are the owners)",
      win._sidebar_toolbar_btn is win._view_toolbar_buttons["view.toggle_sidebar"]
      and win._map_toolbar_btn is win._view_toolbar_buttons["view.toggle_map"]
      and win._sidebar_toolbar_btn.isCheckable() and win._map_toolbar_btn.isCheckable())
check("both buttons mirror the item's state and own NO sequence (the v1.3.3.3 rule)",
      win._sidebar_toolbar_btn.isChecked() == win.act_show_sidebar.isChecked()
      and win._map_toolbar_btn.isChecked() == win.act_show_map.isChecked()
      and win._sidebar_toolbar_btn.shortcut().isEmpty()
      and win._map_toolbar_btn.shortcut().isEmpty(),
      f"{win._sidebar_toolbar_btn.shortcut().toString()!r} / "
      f"{win._map_toolbar_btn.shortcut().toString()!r}")

# The button owns the click, the item owns the state (the legend pattern).
win._sidebar_toolbar_btn.setChecked(False)
app.processEvents()
check("unchecking the toolbar button collapses the sidebar and unchecks the View item",
      win.sidebar.isHidden() and win._sidebar_strip.isVisible()
      and not win.act_show_sidebar.isChecked()
      and i18n.load_config().get("ui_sidebar_collapsed") is True)
win.act_show_sidebar.setChecked(True)
app.processEvents()
check("the View item drives the button back (blocked signals, no loop)",
      not win.sidebar.isHidden() and win._sidebar_toolbar_btn.isChecked())

# The REFUSED collapse must leave the mirror honest: _reject_collapse_both restores the
# item's checkmark with BLOCKED signals, so the button needs an explicit resync.
win._map_toolbar_btn.setChecked(False)          # the map collapses -> the list mode
app.processEvents()
check("the map button collapses the map (and switches the sidebar to LIST mode)",
      win.view.isHidden() and not win.act_show_map.isChecked()
      and win.sidebar.is_list_mode())
win._sidebar_toolbar_btn.setChecked(False)      # forbidden: both panels as strips
app.processEvents()
check("the refused collapse is reported and the sidebar stays expanded",
      not win._sidebar_collapsed and win.act_show_sidebar.isChecked()
      and win.statusBar().currentMessage() == i18n.t("status.collapse_both_forbidden"))
check("the refused collapse leaves the sidebar's toolbar button CHECKED (no lying mirror)",
      win._sidebar_toolbar_btn.isChecked(),
      f"btn={win._sidebar_toolbar_btn.isChecked()}")
win._map_toolbar_btn.setChecked(True)
app.processEvents()
check("expanding the map from the toolbar restores both panels and the narrow tree",
      not win.view.isHidden() and win._map_toolbar_btn.isChecked()
      and win.act_show_map.isChecked() and not win.sidebar.is_list_mode())
check("both mirrors agree with their items again",
      win._sidebar_toolbar_btn.isChecked() == win.act_show_sidebar.isChecked() is True
      and win._map_toolbar_btn.isChecked() == win.act_show_map.isChecked() is True)

# ════════════════════════════════════════════════════════════
# 4. Forbidding double collapsing (v1.2.4.1-fix, a QA request)
# ════════════════════════════════════════════════════════════
print("== 4. both collapsed is forbidden ==")

# The first panel collapses — allowed (the map is expanded).
win.act_show_sidebar.trigger()
app.processEvents()
check("the first panel is collapsed: the sidebar is hidden, the strip is visible",
      win.sidebar.isHidden() and win._sidebar_strip.isVisible())
w_before = win.width()

# An attempt to collapse the SECOND one (the map) — all three paths are rejected.
# The menu path: Qt inverts checked itself → toggled(False) → forbidden → the checkmark returns.
win.act_show_map.trigger()
check("the status hint on the rejection (checked before processEvents)",
      win.statusBar().currentMessage() == i18n.t("status.collapse_both_forbidden"))
app.processEvents()
check("the menu: the second panel is NOT collapsed (the map is visible, the strip is hidden)",
      not win.view.isHidden() and not win._map_strip.isVisible())
check("the menu: the checkmark does not diverge from the mechanics (the 'Map' item is checked)",
      win.act_show_map.isChecked())

# The corner-button path.
win._map_collapse_btn.click()
app.processEvents()
check("the button: the second panel is NOT collapsed either",
      not win.view.isHidden() and win.act_show_map.isChecked())

# The programmatic setChecked path (the same as applying the config at startup).
win.act_show_map.setChecked(False)
app.processEvents()
check("setChecked(False): also forbidden",
      not win.view.isHidden() and win.act_show_map.isChecked())

check("the window does not change (the size is kept)", win.width() == w_before,
      f"{w_before} -> {win.width()}")
check("config: ui_map_collapsed is NOT written as True",
      i18n.load_config().get("ui_map_collapsed") is not True)

# After expanding the first panel, the second can collapse again.
win.act_show_sidebar.trigger()  # expanding the sidebar
app.processEvents()
check("the sidebar is expanded", not win.sidebar.isHidden())
win.act_show_map.setChecked(False)  # now allowed
app.processEvents()
check("after the first panel returns, the second collapses (the map = the strip)",
      win.view.isHidden() and win._map_strip.isVisible()
      and not win.act_show_map.isChecked())
# Both are expanded (for the following sections).
QTest.mouseClick(win._map_strip, Qt.LeftButton)
app.processEvents()
check("both panels are expanded",
      not win.sidebar.isHidden() and not win.view.isHidden()
      and not win._sidebar_strip.isVisible() and not win._map_strip.isVisible())

# ════════════════════════════════════════════════════════════
# 5. The guard is a no-op with the map collapsed
# ════════════════════════════════════════════════════════════
print("== 5. guards with map collapsed ==")

n = win.scene.add_server(ServerData(id="vt-1", alias="GuardNode", host="10.99.0.1", user="root"))
win.act_show_map.setChecked(False)
app.processEvents()

guard_ok = True
try:
    win._fit_to_content()
    win._center_view()
    win._reveal_node_on_map(n)
except Exception as e:  # noqa: BLE001
    guard_ok = False
    print("   guard exception:", repr(e))
check("fit/center/reveal with the map collapsed: no exceptions", guard_ok)
check("the map is not shown automatically", win.view.isHidden())
check("reveal still selects the node (scene-based)", n.isSelected())

# the search navigation Enter/Shift+Enter
win.map_search.show()  # the panel — a child of the hidden view: it lives, but is not visible; no exceptions
app.processEvents()
win._on_map_search_query("guardnode")
app.processEvents()
nav_ok = True
try:
    win._map_search_step(1)
    win._map_search_step(-1)
except Exception as e:  # noqa: BLE001
    nav_ok = False
    print("   search-nav exception:", repr(e))
check("the search navigation (Enter/Shift+Enter): no exceptions, the map is not shown",
      nav_ok and win.view.isHidden())

# the status checks run in the background (scene-based), the dots appear on expansion
n.set_status("online")
app.processEvents()
marker_ok = True
try:
    win._update_sidebar_status_marker(n.data.id)
except Exception as e:  # noqa: BLE001
    marker_ok = False
    print("   status marker exception:", repr(e))
check("the status in the background: the node is online, the sidebar marker is updated without exceptions",
      marker_ok and n._status_dot.brush().color().name() == "#22c55e")
win.act_show_map.trigger()  # expanding the map — the dot is in place
app.processEvents()
check("after the expansion: the map is visible, the status dot is on the node",
      not win.view.isHidden() and n._status_dot.brush().color().name() == "#22c55e")

# ════════════════════════════════════════════════════════════
# 6. PNG/PDF/drawio export with the map collapsed
# ════════════════════════════════════════════════════════════
print("== 6. exports with map collapsed ==")

win.act_show_map.setChecked(False)
app.processEvents()

_export_path = {"p": None}


def _fake_save_name(*a, **k):
    return (_export_path["p"], "")


MW.QFileDialog.getSaveFileName = staticmethod(_fake_save_name)

_export_path["p"] = os.path.join(WORK, "vt_map.png")
win._export_map_image()
check("the PNG export with the map collapsed: the file is created",
      os.path.isfile(_export_path["p"]) and os.path.getsize(_export_path["p"]) > 0)

_export_path["p"] = os.path.join(WORK, "vt_map.pdf")
win._export_map_pdf()
pdf_ok = False
if os.path.isfile(_export_path["p"]):
    with open(_export_path["p"], "rb") as f:
        pdf_ok = f.read(5) == b"%PDF-" and os.path.getsize(_export_path["p"]) > 1024
check("the PDF export with the map collapsed: a valid file", pdf_ok)

_export_path["p"] = os.path.join(WORK, "vt_map.drawio")
win._export_map_drawio()
check("the drawio export with the map collapsed: the file is created",
      os.path.isfile(_export_path["p"]) and os.path.getsize(_export_path["p"]) > 0)

# ════════════════════════════════════════════════════════════
# 7. terminal_mode="tabs": the map collapsed → the dock is alive, the sessions print
# ════════════════════════════════════════════════════════════
print("== 7. terminals dock with map collapsed ==")

merge_cfg({"terminal_mode": "tabs"})
node_d = win.scene.add_server(ServerData(id="vt-d", alias="DockNode", host="10.99.0.2", user="root"))
dock = win._spawn_terminal_window(node_d)
app.processEvents()
check("the 'tabs' mode: the 'Terminals' dock is created (the map is collapsed)",
      isinstance(dock, QDockWidget) and dock.objectName() == "terminals_dock"
      and win.view.isHidden())

page = dock.content.session_tabs.widget(0)
page.terminal_thread.output_signal.emit(b"hello from dock\r\n")
app.processEvents()
check("the session prints with the map collapsed (the output on the canvas)",
      "hello from dock" in page.widget.visible_text(),
      repr(page.widget.visible_text())[:80])

dock.setFloating(True)
app.processEvents()
check("the dock tear-off: a separate window (isWindow), the dock is alive",
      dock.isFloating() and dock.isWindow())
page.terminal_thread.output_signal.emit(b"still printing\r\n")
app.processEvents()
check("in the torn-off dock the session keeps printing",
      "still printing" in page.widget.visible_text())
dock.setFloating(False)
app.processEvents()
page.terminal_thread.output_signal.emit(b"back on map\r\n")
app.processEvents()
check("the dock returns to the map: not floating, the session is alive and keeps printing",
      not dock.isFloating() and "back on map" in page.widget.visible_text())

win.act_show_map.trigger()  # expanding the map (the dock stays nearby)
app.processEvents()
check("the map is expanded, the dock is in place",
      not win.view.isHidden() and dock.isVisible())

# ════════════════════════════════════════════════════════════
# 8. Persistence: config.json + application at startup AFTER restoreState
# ════════════════════════════════════════════════════════════
print("== 8. persistence ==")

win._dirty = False
win.close()
app.processEvents()

clear_cfg()
merge_cfg({"terminal_mode": "tabs", "language": "en"})  # foreign keys — for the merge check
win_p = make_main()
win_p.act_show_sidebar.setChecked(False)  # only ONE panel (a second one — forbidden, §4)
app.processEvents()
cfg = i18n.load_config()
check("the collapsed state is written: ui_sidebar_collapsed=True",
      cfg.get("ui_sidebar_collapsed") is True, str(cfg))
check("the merge write: the foreign keys are not reset (terminal_mode/language are in place)",
      cfg.get("terminal_mode") == "tabs" and cfg.get("language") == "en", str(cfg))
win_p._dirty = False
win_p.close()
app.processEvents()

# A manual write of BOTH keys as True (for example, an old config): it is applied at startup
# only the first panel (the sidebar — first in the application order), collapsing the map
# forbidden by the §4 invariant — the map stays expanded.
merge_cfg({"ui_sidebar_collapsed": True, "ui_map_collapsed": True})
win_p2 = make_main()  # a new window — the state is applied at startup (after restoreState)
check("a new window: the sidebar is collapsed at startup",
      win_p2._sidebar_collapsed is True and win_p2.sidebar.isHidden()
      and not win_p2.act_show_sidebar.isChecked())
check("a new window: the map is NOT collapsed at startup (the invariant: at least one is open)",
      win_p2._map_collapsed is False and not win_p2.view.isHidden()
      and win_p2.act_show_map.isChecked())

# a partial deploy — writes only its own key
win_p2.act_show_sidebar.trigger()
app.processEvents()
cfg = i18n.load_config()
check("a partial return: ui_sidebar_collapsed=False, ui_map_collapsed=True (not reset)",
      cfg.get("ui_sidebar_collapsed") is False and cfg.get("ui_map_collapsed") is True, str(cfg))

win_p2._dirty = False
win_p2.close()
app.processEvents()

# ════════════════════════════════════════════════════════════
# 9. The splitter handle does not reach zero
# ════════════════════════════════════════════════════════════
print("== 9. splitter handle cannot reach zero ==")

clear_cfg()
win_h = make_main()
win_h._splitter.setSizes([0, 1200])
app.processEvents()
check("setSizes([0, …]): the sidebar is not squeezed below the minimum (160px)",
      win_h._sidebar_container.width() >= win_h.SIDEBAR_MIN_WIDTH,
      f"w={win_h._sidebar_container.width()}")
win_h._splitter.setSizes([1200, 0])
app.processEvents()
check("setSizes([…, 0]): the map is not squeezed below the minimum (240px)",
      win_h._map_container.width() >= win_h.MAP_MIN_WIDTH,
      f"w={win_h._map_container.width()}")

win_h._dirty = False
win_h.close()
app.processEvents()

# ════════════════════════════════════════════════════════════
# 10. i18n parity + release state
# ════════════════════════════════════════════════════════════
print("== 10. i18n parity + release state ==")

langs = load_i18n_langs(ROOT)
new_keys = ["view.toggle_map", "view.strip_sidebar_tooltip", "view.strip_map_tooltip",
            "status.collapse_both_forbidden"]  # +1 — v1.2.4.1-fix (forbidding double collapsing)
missing = [k for k in new_keys
           if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh"))]
check("the 4 v1.2.4.1 (+fix) keys are present and non-empty in en/ru/zh", not missing, str(missing))
check_i18n_parity(langs)  # 421 = 417 + 3 + 1 (the _common.py pin; the version is unchanged)
check_release_state(ROOT)

finish()
