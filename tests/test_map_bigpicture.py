# -*- coding: utf-8 -*-
"""v1.4.2 — The big-picture map level: the minimap, the cached card drop-shadow, the group fold.

Checks (ROADMAP v1.4.2; offscreen, no network, isolated HOME):
  §1 the minimap (`ui/minimap.py`): the panel over the canvas (never a scene item), the
     cached layer + its debounce, the fit transform, the status colours, the viewport
     frame, the two-way synchronization (a click/drag asks for the right scene point and
     the window centers the view there), the top-right placement and the "below the
     search bar" rule, the toggle + `ui_minimap` in config.json (a round-trip; a broken
     value → the default), the registry action, i18n;
  §2 the cached drop-shadow: a QGraphicsPixmapItem fed by ONE pixmap per card SIZE (a
     cache hit), a size change misses, the cache is bounded, the halo is inside
     boundingRect() while `card_rect()` is the card, the item is mouse-transparent, no
     QGraphicsDropShadowEffect anywhere, the SVG export hides the halos and restores them;
  §3 the anchors (`card_rect_scene()`): the arrow tips on the card on all four sides, the
     pinned-note anchor + the anchor line, the group membership by the CARD centre,
     `set_group_size` scaling by the card, `fit_to_content` still framing the halo;
  §4 the group fold: the chevron ASKS (collapseRequested) and the window pushes ONE undo
     command, the badges/grid/frame re-fit, the membership survives, a folded group drags
     as a whole and re-lays out on resize, expand restores everything (including after a
     group move), the JSON round-trip (keys written only while folded; an old file loads
     unfolded; a reloaded folded group unfolds in place), a node captured while folded;
  §5 i18n parity (+4 keys × en/ru/zh/de) + the release state.

Run: python tests/test_map_bigpicture.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys

from _common import (bootstrap, check, finish, wait_for, clear_cfg, read_cfg, write_cfg,
                     check_i18n_parity, check_i18n_format, load_i18n_langs,
                     check_release_state)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation, offscreen, faulthandler)

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtWidgets import QApplication, QGraphicsPixmapItem, QGraphicsSceneMouseEvent
from PySide6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv)

import ui.main_window as MW
import ui.hotkey_registry as HR
from i18n import set_language
import i18n as _i18n_mod   # v1.4.6: t() at call time (the minimap band title, the legend.title pattern)
from models.server import ServerData
from graphics.map_scene import MapScene
from graphics.node_group import NodeGroup
from graphics.connection_arrow import edge_point
from graphics.server_node import (ServerNode, SHADOW_BLUR, SHADOW_DY,
                                  SHADOW_CACHE_SIZE, shadow_cache_info, clear_shadow_cache,
                                  _shadow_pixmap)

SHADOW_BOTTOM = ServerNode.SHADOW_BOTTOM   # the DERIVED total (2*BLUR + DY)


def new_window(width=1200, height=700, show=True):
    """A MainWindow with the autosave timer stopped and a real geometry (the minimap needs one)."""
    w = MW.MainWindow()
    w._autosave_timer.stop()
    w.resize(width, height)
    if show:
        w.show()
    app.processEvents()
    return w


def close_window(w):
    try:
        w._dirty = False
        w.close()
        w.destroy()
    except RuntimeError:
        pass
    app.processEvents()


def add_node(scene, alias, x, y, host="10.0.0.1"):
    return scene.add_server(ServerData(id=f"{alias}-id", alias=alias, host=host, user="u", x=x, y=y))


def press_item(item, local):
    """A synthetic click on a QGraphicsItem (the test_collapse.py pattern: no QTest for items)."""
    ev = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.Type.MouseButtonPress)
    ev.setButton(Qt.MouseButton.LeftButton)
    ev.setButtons(Qt.MouseButton.LeftButton)
    ev.setScenePos(local)   # the item is not in a scene → scene == item coordinates
    ev.setPos(local)
    ev.setModifiers(Qt.KeyboardModifier.NoModifier)
    ev.setAccepted(False)
    item.mousePressEvent(ev)
    return ev.isAccepted()


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the minimap ==")
# ════════════════════════════════════════════════════════════════════════════

clear_cfg()
win = new_window()
mini = win.minimap
view = win.view

check("§1 the minimap is a CHILD OF THE VIEW and never a scene item",
      mini.parent() is view and all(item is not mini for item in view.scene().items()),
      f"parent={type(mini.parent()).__name__}")
check("§1 the panel has a fixed size that fits the view",
      mini.width() == mini.DEFAULT_WIDTH and mini.height() == mini.DEFAULT_HEIGHT
      and view.width() >= mini.width() and view.height() >= mini.height(),
      f"mini={mini.width()}x{mini.height()} view={view.width()}x{view.height()}")
check("§1 visible by default (no ui_minimap key in the config)",
      read_cfg({}).get("ui_minimap") is None and win._minimap_enabled is True and mini.isVisible(),
      f"enabled={win._minimap_enabled} visible={mini.isVisible()}")
check("§1 the empty map draws the empty panel (no content, no crash)",
      mini.item_count() == 0 and mini.fit() is None and mini.content_rect().isEmpty(),
      f"items={mini.item_count()} fit={mini.fit()}")
check("§1 the panel sits in the top-right corner of the map",
      abs(mini.x() - (view.width() - mini.width() - 12)) <= 2 and mini.y() == 12,
      f"mini=({mini.x()},{mini.y()}) view={view.width()}x{view.height()}")
_mini_home = QPoint(mini.x(), mini.y())   # v1.4.6: the corner it starts in (the move tests compare with it)

# The layer: nodes (coloured by status), a note, a group frame
n1 = add_node(win.scene, "mm-a", 0, 0)
n2 = add_node(win.scene, "mm-b", 400, 120)
n3 = add_node(win.scene, "mm-c", 200, 300)
n1.set_status("online")
n2.set_status("offline")
win.scene.add_note(text="mm note", x=600, y=340)
win.scene.add_group(name="mm-grp", x=-100, y=-100, width=900, height=600)

mini.refresh()
check("§1 the layer holds every node + note + group frame",
      mini.item_count() == 5, f"items={mini.item_count()}")
check("§1 the content rect is the union of the layer (scene coordinates)",
      mini.content_rect().contains(n1.card_rect_scene()) and mini.content_rect().width() > 800,
      str(mini.content_rect()))
colors = [c.name() for _r, c, _f in mini._items]
check("§1 node blocks are coloured by STATUS (online green / offline red)",
      "#22c55e" in colors and "#ef4444" in colors, str(colors))
check("§1 the note and the group frame are in the layer too (note fill + violet outline)",
      "#eedd9f" in colors and "#7c3aed" in colors, str(colors))

# The fit transform: KeepAspectRatio, the margin, centered INSIDE THE MAP AREA
# (v1.4.6: the panel is [map area | vertical title band], so the fit works on body_rect())
fit = mini.fit()
body = mini.body_rect()
check("§1 the fit transform is KeepAspectRatio inside the map area margin",
      fit is not None and fit[0] > 0
      and mini.content_rect().width() * fit[0] <= body.width() - 2 * mini.MARGIN + 0.5
      and mini.content_rect().height() * fit[0] <= body.height() - 2 * mini.MARGIN + 0.5,
      str(fit))
mapped = mini._transform().map(mini.content_rect().center())
check("§1 the content is centered inside the map area (the band excluded)",
      abs(mapped.x() - body.center().x()) < 1.0 and abs(mapped.y() - body.center().y()) < 1.0,
      f"({mapped.x():.1f},{mapped.y():.1f}) body_center=({body.center().x():.1f},{body.center().y():.1f})")

# The viewport frame = the visible scene rect through the same transform
frame = mini.viewport_frame()
vp_rect = mini.viewport_scene_rect()
check("§1 the viewport frame maps the visible scene rect",
      frame is not None and vp_rect is not None and frame.width() > 0
      and abs(frame.width() - vp_rect.width() * fit[0]) < 0.5,
      f"frame={frame} vp={vp_rect}")
win.view.set_zoom_and_center(2.0, 200, 150)
app.processEvents()
check("§1 the frame follows a ZOOM change",
      mini.viewport_frame().width() != frame.width(), str(mini.viewport_frame()))

# Two-way synchronization: a click asks for the scene point under the cursor
requested = []
mini.center_requested.connect(lambda p: requested.append(QPointF(p)))
click_point = QPoint(int(body.width()) // 2 + 20, mini.height() // 2)
expected_scene = mini.scene_point_at(click_point)
QTest.mouseClick(mini, Qt.MouseButton.LeftButton, pos=click_point)
app.processEvents()
check("§1 a click emits center_requested with the scene point under the cursor",
      bool(requested) and abs(requested[-1].x() - expected_scene.x()) < 1.0
      and abs(requested[-1].y() - expected_scene.y()) < 1.0,
      f"asked={requested[-1] if requested else None} expected={expected_scene}")
after_click = view.mapToScene(view.viewport().rect().center())
check("§1 the window centers the view on the asked point",
      abs(after_click.x() - expected_scene.x()) < 3.0 and abs(after_click.y() - expected_scene.y()) < 3.0,
      f"center={after_click} asked={expected_scene}")

# A drag that MOVES is a camera pan at once (v1.4.6: a real movement settles the
# press — the hold never gets the chance to turn it into a panel move).
drag_from = QPoint(20, 20)
drag_mid = QPoint(int(body.width()) // 2, mini.height() // 2)
drag_to = QPoint(int(body.width()) - 20, mini.height() - 20)
_pan_requests = len(requested)
QTest.mousePress(mini, Qt.MouseButton.LeftButton, pos=drag_from)
app.processEvents()
QTest.mouseMove(mini, pos=drag_mid)
app.processEvents()
QTest.mouseMove(mini, pos=drag_to)
app.processEvents()
QTest.mouseRelease(mini, Qt.MouseButton.LeftButton, pos=drag_to)
app.processEvents()
check("§1 a drag moves the view step by step (the last point wins)",
      len(requested) == _pan_requests + 2
      and abs(view.mapToScene(view.viewport().rect().center()).x()
              - mini.scene_point_at(drag_to).x()) < 3.0,
      f"requests={len(requested)} (was {_pan_requests})")
check("§1 a camera drag does NOT move the panel (that is the HOLD gesture)",
      mini.pos() == _mini_home, f"{mini.pos()} vs {_mini_home}")

# The layer rebuild is debounced (a scene change schedules ONE walk)
add_node(win.scene, "mm-d", 900, 500)
check("§1 a scene change does NOT rebuild the layer synchronously",
      mini.item_count() == 5, f"items={mini.item_count()}")
check("§1 …and the debounced rebuild picks it up",
      wait_for(lambda: mini.item_count() == 6, timeout_ms=2000), f"items={mini.item_count()}")

# The toggle + the config
win.act_show_minimap.setChecked(False)
check("§1 the View item hides the panel and writes ui_minimap=false",
      not mini.isVisible() and read_cfg({}).get("ui_minimap") is False,
      f"visible={mini.isVisible()} cfg={read_cfg({})}")
win.act_show_minimap.setChecked(True)
check("§1 switching it back shows the panel and writes ui_minimap=true",
      mini.isVisible() and read_cfg({}).get("ui_minimap") is True, str(read_cfg({})))

write_cfg({"ui_minimap": False})
win_cfg = new_window()
check("§1 a saved ui_minimap=false builds the window with the panel OFF",
      win_cfg._minimap_enabled is False and win_cfg.act_show_minimap.isChecked() is False
      and win_cfg.minimap.isVisible() is False, f"enabled={win_cfg._minimap_enabled}")
close_window(win_cfg)
write_cfg({"ui_minimap": "yes"})   # a broken value: not a bool
win_bad = new_window()
check("§1 a broken ui_minimap value falls back to the default (visible)",
      win_bad._minimap_enabled is True and win_bad.minimap.isVisible() is True,
      f"enabled={win_bad._minimap_enabled}")
close_window(win_bad)
clear_cfg()

# The two floating panels never overlap: the minimap steps BELOW an open search bar
win._open_map_search()
app.processEvents()
bar_bottom = win.map_search.geometry().bottom()
check("§1 the minimap moves BELOW the search bar while it is open",
      mini.y() >= bar_bottom + 4, f"mini.y={mini.y()} bar_bottom={bar_bottom}")
win._close_map_search()
app.processEvents()
check("§1 and returns to the top-right corner when the search closes",
      mini.y() == 12, f"mini.y={mini.y}")

# The registry action + the i18n of the tooltip
check("§1 view.toggle_minimap is a registry action with an EMPTY default (assignable)",
      "view.toggle_minimap" in HR.action_ids()
      and HR.default_sequence("view.toggle_minimap") == ""
      and HR.action_label_key("view.toggle_minimap") == "view.toggle_minimap",
      str(HR.default_sequence("view.toggle_minimap")))
check("§1 the QAction is a registered hotkey target (the menu owns the sequence)",
      win.act_show_minimap in win._hotkey_targets.get("view.toggle_minimap", []),
      str(win._hotkey_targets.get("view.toggle_minimap")))
check("§1 the item is checkable and carries the translated label",
      win.act_show_minimap.isCheckable()
      and win.act_show_minimap.text() == win.t("view.toggle_minimap"),
      win.act_show_minimap.text())
check("§1 the panel is a real widget that owns its clicks (no pass-through to the canvas)",
      mini.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) is False
      and mini.isEnabled(),
      f"enabled={mini.isEnabled()}")

tooltip_en = mini.toolTip()
set_language("ru")
mini.retranslate()
check("§1 the minimap tooltip follows the language switch (retranslate)",
      mini.toolTip() != tooltip_en and "Миникарта" in mini.toolTip(), mini.toolTip())
set_language("en")
mini.retranslate()
clear_cfg()

# ── v1.4.6: the vertical title band + the side fold + the toolbar switch ──────
print("== §1b the minimap title band, the side fold and the toolbar switch ==")

check("§1b the panel is [map area | title band]: the band is the RIGHT edge, the full height",
      abs(mini.header_rect().left() - (mini.width() - mini.HEADER_W)) < 0.5
      and abs(mini.header_rect().width() - mini.HEADER_W) < 0.5
      and abs(mini.header_rect().height() - mini.height()) < 0.5,
      f"header={mini.header_rect()} w={mini.width()}")
check("§1b the map area is what is left of the band (the v1.4.2 size is kept)",
      abs(mini.body_rect().width() - mini.BODY_WIDTH) < 0.5
      and mini.BODY_WIDTH + mini.HEADER_W == mini.DEFAULT_WIDTH,
      f"body={mini.body_rect()} width={mini.width()}")
check("§1b the band carries the translated title (minimap.title — the legend.title precedent)",
      mini._title == _i18n_mod.t("minimap.title") == "Minimap", mini._title)
set_language("ru")
mini.retranslate()
check("§1b the title follows a language switch (retranslate re-reads it)",
      mini._title == "Миникарта" and mini._title == _i18n_mod.t("minimap.title"), mini._title)
set_language("en")
mini.retranslate()

# A click on the BAND folds the panel sideways to the RIGHT (the map area disappears).
_asked = len(requested)
QTest.mouseClick(mini, Qt.MouseButton.LeftButton,
                 pos=QPoint(mini.width() - mini.HEADER_W // 2, 40))
app.processEvents()
check("§1b a click on the title band folds the panel to the side",
      mini.is_collapsed() and mini.width() == mini.HEADER_W
      and mini.height() == mini.DEFAULT_HEIGHT,
      f"collapsed={mini.is_collapsed()} size={mini.width()}x{mini.height()}")
check("§1b a folded panel has no map area — the fit is None, like an empty map",
      mini.body_rect().isEmpty() and mini.fit() is None and mini.viewport_frame() is None)
check("§1b the fold did NOT move the camera (a band click is not a pan)",
      len(requested) == _asked, f"requests={len(requested)}")
check("§1b the window persisted ui_minimap_collapsed=True",
      read_cfg({}).get("ui_minimap_collapsed") is True, str(read_cfg({})))
check("§1b the folded strip stays on the RIGHT edge of the map",
      abs(mini.x() - (view.width() - mini.width() - 12)) <= 2 and mini.y() == 12,
      f"mini=({mini.x()},{mini.y()}) view={view.width()}")

# A second click unfolds it back.
QTest.mouseClick(mini, Qt.MouseButton.LeftButton,
                 pos=QPoint(mini.width() - mini.HEADER_W // 2, 40))
app.processEvents()
check("§1b a second click on the band unfolds the panel (the map area is back)",
      not mini.is_collapsed() and mini.width() == mini.DEFAULT_WIDTH
      and mini.fit() is not None and read_cfg({}).get("ui_minimap_collapsed") is False,
      f"collapsed={mini.is_collapsed()} w={mini.width()} fit={mini.fit()}")

# A click INSIDE the map area keeps the v1.4.2 gesture (a camera move, not a fold).
QTest.mouseClick(mini, Qt.MouseButton.LeftButton, pos=QPoint(30, 40))
app.processEvents()
check("§1b a click in the map area still pans (it does not fold the panel)",
      not mini.is_collapsed() and len(requested) > _asked,
      f"collapsed={mini.is_collapsed()} requests={len(requested)}")

# The toolbar switch (next to the legend's).
check("§1b the toolbar carries the minimap switch next to the legend one",
      win._minimap_toolbar_btn is not None
      and win._minimap_toolbar_btn is win._view_toolbar_buttons["view.toggle_minimap"]
      and win._view_toolbar_buttons["view.toggle_legend"] is win._legend_toolbar_btn)
check("§1b the minimap button mirrors the View item and owns no sequence",
      win._minimap_toolbar_btn.isCheckable()
      and win._minimap_toolbar_btn.isChecked() == win.act_show_minimap.isChecked()
      and win._minimap_toolbar_btn.shortcut().isEmpty(),
      str(win._minimap_toolbar_btn.shortcut().toString()))
win._minimap_toolbar_btn.setChecked(False)
app.processEvents()
check("§1b unchecking the toolbar button hides the panel and unchecks the menu item",
      not mini.isVisible() and not win.act_show_minimap.isChecked()
      and read_cfg({}).get("ui_minimap") is False)
win.act_show_minimap.setChecked(True)
app.processEvents()
check("§1b the menu item drives the button back (blocked signals, no loop)",
      mini.isVisible() and win._minimap_toolbar_btn.isChecked())
check("§1b the toolbar group holds the FOUR view toggles in the panel order",
      list(win._view_toolbar_buttons) == ["view.toggle_sidebar", "view.toggle_map",
                                          "view.toggle_minimap", "view.toggle_legend"]
      and win._sidebar_toolbar_btn.shortcut().isEmpty()
      and win._map_toolbar_btn.shortcut().isEmpty(),
      str(list(win._view_toolbar_buttons)))
check("§1b the sidebar/map buttons mirror their View items (checked = expanded)",
      win._sidebar_toolbar_btn.isChecked() == win.act_show_sidebar.isChecked()
      and win._map_toolbar_btn.isChecked() == win.act_show_map.isChecked())

# ── v1.4.6: the MOVE gesture — a long press turns the press into "move the panel" ──
print("== §1c the minimap MOVE gesture (hold the left button, then drag) ==")

check("§1c the panel reports moves (moved(QPoint)) and knows when it is being moved",
      hasattr(mini, "moved") and mini.is_moving() is False)
_mini_before = QPoint(mini.x(), mini.y())
_requests_before = len(requested)

# A SHORT press must stay the v1.4.2 click: the view jumps, the panel does not move.
QTest.mouseClick(mini, Qt.MouseButton.LeftButton,
                 pos=QPoint(int(body.width()) // 2, mini.height() // 2))
app.processEvents()
check("§1c a short press is still the click (the view jumps, the panel stays put)",
      len(requested) == _requests_before + 1 and mini.pos() == _mini_before
      and not mini.is_moving() and mini._hold_timer.isActive() is False,
      f"requests={len(requested)} pos={mini.pos()}")

# A HOLD (longer than MOVE_HOLD_MS) switches to MOVE mode — and does NOT pan.
QTest.mousePress(mini, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                 QPoint(60, 60))
app.processEvents()
check("§1c the hold timer is armed by the press, while nothing is decided yet",
      mini._press_pending and mini._hold_timer.isActive() and not mini.is_moving())
check("§1c no camera request is emitted by the press itself (a hold must not pan)",
      len(requested) == _requests_before + 1, f"requests={len(requested)}")
check("§1c the hold fires and the panel enters MOVE mode",
      wait_for(lambda: mini.is_moving(), timeout_ms=2000), "the hold timer never fired")
check("§1c the camera was not asked to move by the hold either",
      len(requested) == _requests_before + 1, f"requests={len(requested)}")
check("§1c the move mode announces itself (the SizeAll cursor)",
      mini.cursor().shape() == Qt.CursorShape.SizeAllCursor, str(mini.cursor().shape()))

# …and a drag now moves the PANEL (clamped inside the view) and persists the spot.
mi = win.minimap
QTest.mouseMove(mi, QPoint(60 - 70, 60 + 45))
app.processEvents()
check("§1c dragging in MOVE mode moves the panel, not the view",
      mi.pos() != _mini_before and len(requested) == _requests_before + 1,
      f"pos={mi.pos()} was={_mini_before} requests={len(requested)}")
_saved_pos = read_cfg({}).get("ui_minimap_position")
QTest.mouseRelease(mi, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                   QPoint(60 - 70, 60 + 45))
app.processEvents()
check("§1c the release leaves MOVE mode and restores the pointer cursor",
      not mi.is_moving() and mi.cursor().shape() == Qt.CursorShape.PointingHandCursor)
check("§1c the release persists the panel's spot in ui_minimap_position",
      read_cfg({}).get("ui_minimap_position") == {"x": mi.x(), "y": mi.y()}
      and win._minimap_pos == QPoint(mi.x(), mi.y()),
      f"saved={read_cfg({}).get('ui_minimap_position')} in-memory={win._minimap_pos} "
      f"pos={mi.pos()} (before the release: {_saved_pos})")
check("§1c the panel stays inside the view (the drag is clamped)",
      0 <= mi.x() and mi.x() + mi.width() <= view.width()
      and 0 <= mi.y() and mi.y() + mi.height() <= view.height(),
      f"pos={mi.pos()} view={view.width()}x{view.height()}")

# A drag far outside is clamped, not obeyed.
QTest.mousePress(mi, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(30, 30))
wait_for(lambda: mi.is_moving(), timeout_ms=2000)
QTest.mouseMove(mi, QPoint(10 ** 5, 10 ** 5))
app.processEvents()
QTest.mouseRelease(mi, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                   QPoint(10 ** 5, 10 ** 5))
app.processEvents()
check("§1c a drag far outside the view is clamped into it",
      mi.x() + mi.width() <= view.width() and mi.y() + mi.height() <= view.height()
      and mi.x() >= 0 and mi.y() >= 0,
      f"pos={mi.pos()} view={view.width()}x{view.height()}")

# The detached spot wins over the corner rule — including the "below the search bar" one.
win._open_map_search()
app.processEvents()
check("§1c an OPEN search bar no longer re-places a panel the user moved",
      mi.pos() == QPoint(win._minimap_pos.x(), win._minimap_pos.y()),
      f"pos={mi.pos()} saved={win._minimap_pos}")
win._close_map_search()
app.processEvents()

close_window(win)

# The position survives a restart, and a broken value falls back to the corner.
write_cfg({"ui_minimap_position": {"x": 40, "y": 60}})
win_pos = new_window()
check("§1c a saved ui_minimap_position places the panel there (detached from the corner)",
      win_pos.minimap.pos() == QPoint(40, 60)
      and win_pos._minimap_pos == QPoint(40, 60),
      f"pos={win_pos.minimap.pos()} saved={win_pos._minimap_pos}")
write_cfg({"ui_minimap_position": [10 ** 5, 10 ** 5]})
win_far = new_window()
check("§1c a saved position outside the view is clamped, not obeyed",
      win_far.minimap.x() + win_far.minimap.width() <= win_far.view.width()
      and win_far.minimap.y() + win_far.minimap.height() <= win_far.view.height(),
      f"pos={win_far.minimap.pos()} view={win_far.view.width()}x{win_far.view.height()}")
close_window(win_far)
write_cfg({"ui_minimap_position": ["a", "b"]})   # a broken value
win_bad_pos = new_window()
check("§1c a broken ui_minimap_position falls back to the top-right corner",
      win_bad_pos._minimap_pos is None
      and abs(win_bad_pos.minimap.x()
              - (win_bad_pos.view.width() - win_bad_pos.minimap.width() - 12)) <= 2
      and win_bad_pos.minimap.y() == 12,
      f"pos={win_bad_pos.minimap.pos()}")
close_window(win_bad_pos)
close_window(win_pos)
clear_cfg()

# The fold survives a restart (the ui_minimap_collapsed round-trip).
write_cfg({"ui_minimap_collapsed": True})
win_fold = new_window()
check("§1b a saved ui_minimap_collapsed=True builds the window with a FOLDED strip",
      win_fold.minimap.is_collapsed() and win_fold.minimap.width() == win_fold.minimap.HEADER_W
      and win_fold.minimap.isVisible(),
      f"collapsed={win_fold.minimap.is_collapsed()} w={win_fold.minimap.width()}")
write_cfg({"ui_minimap_collapsed": "yes"})   # a broken value: not a bool
win_bad_fold = new_window()
check("§1b a broken ui_minimap_collapsed value falls back to the default (unfolded)",
      win_bad_fold.minimap.is_collapsed() is False
      and win_bad_fold.minimap.width() == win_bad_fold.minimap.DEFAULT_WIDTH,
      f"collapsed={win_bad_fold.minimap.is_collapsed()}")
close_window(win_bad_fold)
close_window(win_fold)
clear_cfg()

# ════════════════════════════════════════════════════════════════════════════
print("== §2 the cached card drop-shadow ==")
# ════════════════════════════════════════════════════════════════════════════

clear_shadow_cache()
s2 = MapScene()
na = s2.add_server(ServerData(id="sh-a", alias="sh-a", host="10.0.0.1", user="u", x=0, y=0))
mid_cache = shadow_cache_info()
nb = s2.add_server(ServerData(id="sh-b", alias="sh-b", host="10.0.0.2", user="u", x=500, y=0))

check("§2 the shadow is a QGraphicsPixmapItem (a cached pixmap, not an effect, not a path)",
      isinstance(na._shadow, QGraphicsPixmapItem) and na.graphicsEffect() is None,
      type(na._shadow).__name__)
check("§2 two cards of the same size SHARE one pixmap (a cache HIT, both sizes equal)",
      na._current_width == nb._current_width and na._current_height == nb._current_height
      and na._shadow.pixmap().cacheKey() == nb._shadow.pixmap().cacheKey()
      and shadow_cache_info().misses == mid_cache.misses,
      f"sizes=({na._current_width},{na._current_height})/({nb._current_width},{nb._current_height}) "
      f"misses={mid_cache.misses}→{shadow_cache_info().misses}")

before_key = na._shadow.pixmap().cacheKey()
entries = shadow_cache_info().currsize
na.toggle_collapsed()
check("§2 a SIZE change misses the cache and swaps the pixmap",
      na._shadow.pixmap().cacheKey() != before_key
      and shadow_cache_info().currsize == entries + 1
      and shadow_cache_info().misses > mid_cache.misses,
      f"currsize={shadow_cache_info().currsize}")
na.toggle_collapsed()
check("§2 the cache is BOUNDED (an lru_cache, not an unbounded dict)",
      shadow_cache_info().maxsize == SHADOW_CACHE_SIZE
      and _shadow_pixmap.cache_info().currsize <= SHADOW_CACHE_SIZE,
      str(shadow_cache_info()))

check("§2 boundingRect() is the card + the halo on all four sides",
      abs(na.boundingRect().top() + SHADOW_BLUR) < 0.5
      and abs(na.boundingRect().left() + SHADOW_BLUR) < 0.5
      and abs(na.boundingRect().height() - (na._current_height + SHADOW_BOTTOM)) < 0.5
      and abs(SHADOW_BOTTOM - (2 * SHADOW_BLUR + SHADOW_DY)) < 1e-9,
      str(na.boundingRect()))
check("§2 card_rect() is the card WITHOUT the halo",
      abs(na.card_rect().width() - na._current_width) < 1e-6
      and abs(na.card_rect().height() - na._current_height) < 1e-6
      and na.card_rect().top() == 0.0 and na.card_rect().left() == 0.0,
      str(na.card_rect()))
check("§2 card_rect_scene() is the card at the node position",
      abs(na.card_rect_scene().left() - na.pos().x()) < 1e-6
      and abs(na.card_rect_scene().top() - na.pos().y()) < 1e-6,
      str(na.card_rect_scene()))
check("§2 the shadow item sits at (-BLUR, -BLUR) with a card-sized halo pixmap",
      abs(na._shadow.pos().x() + SHADOW_BLUR) < 0.5
      and abs(na._shadow.pos().y() + SHADOW_BLUR) < 0.5
      and abs(na._shadow.pixmap().width() - (na._current_width + 2 * SHADOW_BLUR)) <= 1
      and abs(na._shadow.pixmap().height() - (na._current_height + 2 * SHADOW_BLUR + SHADOW_DY)) <= 1,
      f"pos={na._shadow.pos()} pm={na._shadow.pixmap().size()}")
check("§2 the halo stays INSIDE the boundingRect (Qt clips children by it)",
      na.boundingRect().contains(na._shadow.sceneBoundingRect().translated(-na.pos().x(),
                                                                           -na.pos().y())),
      f"halo={na._shadow.sceneBoundingRect()} rect={na.mapRectToScene(na.boundingRect())}")
check("§2 the halo is mouse-transparent (a shadow is not a hit zone)",
      na._shadow.acceptedMouseButtons() == Qt.MouseButton.NoButton,
      str(na._shadow.acceptedMouseButtons()))

# The vector export hides the halos for the render (a pixmap would be a base64 blob)
svg_path = os.path.join(WORK, "bigpicture_shadow.svg")
size_svg = s2.render_to_svg(svg_path)
svg_text = open(svg_path, encoding="utf-8").read()
check("§2 the SVG export is still fully VECTOR (the halos are hidden for the render)",
      size_svg > 512 and "base64" not in svg_text and "<text" in svg_text,
      f"size={size_svg} base64={'base64' in svg_text}")
check("§2 …and the halos are visible again after the export",
      na._shadow.isVisible() and nb._shadow.isVisible(),
      f"{na._shadow.isVisible()}/{nb._shadow.isVisible()}")
png = s2.render_to_pixmap(scale=1.0)
check("§2 the PNG export keeps the halos (a raster format)", not png.isNull(), str(png.size()))

# ════════════════════════════════════════════════════════════════════════════
print("== §3 the anchors (card_rect_scene) ==")
# ════════════════════════════════════════════════════════════════════════════

s3 = MapScene()
left = add_node(s3, "an-left", 0, 0)
right = add_node(s3, "an-right", 600, 0)
arrow = s3.add_connection("an-left-id", "an-right-id", "anchored", "ssh")
geom = arrow._compute_geometry()
check("§3 the arrow geometry is computable", geom is not None)
_gpath, p0, p3, _c1, _c2 = geom
check("§3 the tail sits EXACTLY on the source card's right edge (not on the halo)",
      abs(p0.x() - left.card_rect_scene().right()) < 1.5
      and p0.x() < left.sceneBoundingRect().right() - 1.0,
      f"p0.x={p0.x():.1f} card={left.card_rect_scene().right():.1f} "
      f"halo={left.sceneBoundingRect().right():.1f}")
check("§3 the head sits on the target card's left edge",
      abs(p3.x() - right.card_rect_scene().left()) < 1.5
      and p3.x() > right.sceneBoundingRect().left() + 1.0, f"p3.x={p3.x():.1f}")

above = add_node(s3, "an-above", 300, -500)
below = add_node(s3, "an-below", 300, 500)
arrow_v = s3.add_connection("an-above-id", "an-below-id", "", "ssh")
_g2, v0, v3, _c3, _c4 = arrow_v._compute_geometry()
check("§3 vertically the tips use the card too (bottom/top edges, not the halo)",
      abs(v0.y() - above.card_rect_scene().bottom()) < 1.5
      and abs(v3.y() - below.card_rect_scene().top()) < 1.5,
      f"v0.y={v0.y():.1f} card_bottom={above.card_rect_scene().bottom():.1f} "
      f"v3.y={v3.y():.1f} card_top={below.card_rect_scene().top():.1f}")

note = s3.add_note(text="anchored note", x=900.0, y=900.0)
s3.attach_note_to_node(note, left)
anchor = left.card_rect_scene()
check("§3 a pinned note lands on the CARD's top-right corner + 12 px",
      abs(note.pos().x() - (anchor.right() + 12.0)) < 0.5
      and abs(note.pos().y() - (anchor.top() + 12.0)) < 0.5,
      f"note=({note.pos().x():.1f},{note.pos().y():.1f}) "
      f"card=({anchor.right():.1f},{anchor.top():.1f})")
line = s3._note_anchor_lines.get(note.note_id)
exp_end = edge_point(anchor, anchor.center(), note.sceneBoundingRect().center())
end = line.path().currentPosition()
check("§3 the anchor LINE ends on the card edge (not on the halo)",
      abs(end.x() - exp_end.x()) < 0.5 and abs(end.y() - exp_end.y()) < 0.5,
      f"end=({end.x():.1f},{end.y():.1f}) expected=({exp_end.x():.1f},{exp_end.y():.1f})")

# The membership centre is the CARD centre — a frame edge 1 px below/above it decides
s3b = MapScene()
member = add_node(s3b, "mem-a", 0, 0)
grp = s3b.add_group(name="mem", x=-100, y=-100, width=400, height=400)
check("§3 the node joined the frame (its card centre is inside)", member in set(grp.get_members()))
centre = member.card_rect_scene().center()
grp.set_frame_size(400, centre.y() + 100.0 + 1.0)     # the bottom edge 1 px BELOW the centre
check("§3 a CARD centre 1 px inside the frame is a member (the halo would push it out)",
      member in set(grp.get_members()),
      f"centre.y={centre.y():.1f} frame_bottom={grp.sceneBoundingRect().bottom():.1f}")
grp.set_frame_size(400, centre.y() + 100.0 - 1.0)     # the bottom edge 1 px ABOVE the centre
check("§3 a CARD centre just outside is not a member",
      member not in set(grp.get_members()),
      f"centre.y={centre.y():.1f} frame_bottom={grp.sceneBoundingRect().bottom():.1f}")

# set_group_size scales the members by their CARD rect
s3c = MapScene()
scaled = add_node(s3c, "sc-a", 100, 100)
grp_c = s3c.add_group(name="scale", x=0, y=0, width=400, height=400)
grp_c.clear_members()
grp_c.add_member(scaled)
card0 = scaled.card_rect_scene()
grp_c.set_group_size(800, 400)   # sx=2, sy=1 → the local left doubles
check("§3 a group resize scales the member by its CARD rect",
      abs(scaled.pos().x() - card0.left() * 2.0) < 1.0,
      f"pos.x={scaled.pos().x():.1f} expected={card0.left() * 2.0:.1f}")

# fit_to_content still frames the cards WITH their halos
win_fit = new_window()
add_node(win_fit.scene, "fit-a", 0, 0)
add_node(win_fit.scene, "fit-b", 500, 300)
content = win_fit.view.content_bounding_rect()
card = win_fit.scene.nodes()[0].card_rect_scene()
check("§3 fit_to_content frames the painted rect (cards + shadows)",
      content.height() >= card.height() + 2 * SHADOW_BLUR - 0.5,
      f"content={content} card={card}")
close_window(win_fit)

# ════════════════════════════════════════════════════════════════════════════
print("== §4 the group fold ==")
# ════════════════════════════════════════════════════════════════════════════

win4 = new_window()
g = win4.scene.add_group(name="fold-me", x=0, y=0, width=480, height=320)
win4._connect_group_signals(g)
members = [add_node(win4.scene, f"f-{i}", 20 + i * 70, 60 + (i % 2) * 90) for i in range(5)]
check("§4 the fixture captured the five members", len(g.get_members()) == 5, str(len(g.get_members())))
check("§4 a fresh group is expanded and writes NO fold keys",
      g.is_collapsed() is False and "collapsed" not in g.to_dict(), str(g.to_dict()))

# The chevron ASKS (the group never mutates itself) — and the window answers with ONE undo step
asked = []
g.collapseRequested.connect(lambda: asked.append(True))
stack0 = win4.undo_stack.count()
check("§4 a click on the chevron is accepted", press_item(g, g.chevron_rect().center()))
check("§4 …the group only ASKS (collapseRequested) …", bool(asked), f"asked={len(asked)}")
check("§4 …and the WINDOW answers: the group is folded by one undo command",
      g.is_collapsed() and win4.undo_stack.count() == stack0 + 1
      and win4.undo_stack.text(win4.undo_stack.count() - 1) == "Collapse group",
      f"collapsed={g.is_collapsed()} steps={win4.undo_stack.count() - stack0}")
win4._undo()   # back to a clean expanded state (the fold below is the measured one)
check("§4 …and Ctrl+Z takes the chevron fold back", g.is_collapsed() is False)

# The window pushes ONE undo command
before_state = [(m.data.id, m.pos().x(), m.pos().y(), m.data.collapsed) for m in members]
frame_before = g.size()
stack_before = win4.undo_stack.index()
check("§4 _toggle_group_collapsed folds the group", win4._toggle_group_collapsed(g) and g.is_collapsed())
check("§4 …as exactly ONE undo step named for the fold",
      win4.undo_stack.index() == stack_before + 1
      and win4.undo_stack.text(win4.undo_stack.index() - 1) == "Collapse group",
      f"index={win4.undo_stack.index()} / "
      f"{win4.undo_stack.text(win4.undo_stack.index() - 1)!r}")
check("§4 every member became its BADGE (the v0.8.4 collapsed card)",
      all(m.data.collapsed and abs(m._current_height - ServerNode.COLLAPSED_HEIGHT) < 0.5
          for m in members),
      str([m._current_height for m in members]))
check("§4 the badges are laid out INSIDE the frame (the membership survives by construction)",
      all(g.sceneBoundingRect().contains(m.card_rect_scene().center()) for m in members)
      and len(g.get_members()) == 5,
      str(len(g.get_members())))
rects = [m.card_rect_scene() for m in members]
check("§4 the badge grid does not overlap",
      not any(rects[i].intersects(rects[j])
              for i in range(len(rects)) for j in range(i + 1, len(rects))))
check("§4 the frame was re-fitted to the grid (it changed size)",
      g.size() != frame_before, f"{frame_before} → {g.size()}")
check("§4 a folded member is NOT draggable (a summary view)",
      all(not (m.flags() & m.GraphicsItemFlag.ItemIsMovable) for m in members))
check("§4 the folded state is written to the JSON (collapsed + the pre-fold frame size)",
      g.to_dict().get("collapsed") is True
      and abs(g.to_dict().get("expanded_width") - frame_before[0]) < 0.5
      and abs(g.to_dict().get("expanded_height") - frame_before[1]) < 0.5,
      str(g.to_dict()))

# The folded group moves as a whole; a resize re-lays the grid out
pos_before_move = [QPointF(m.pos()) for m in members]
delta = QPointF(120.0, 60.0)
g._apply_move(delta)
check("§4 the folded group drags as a WHOLE (every badge follows by the same delta)",
      all(abs(m.pos().x() - (p.x() + delta.x())) < 1.0
          and abs(m.pos().y() - (p.y() + delta.y())) < 1.0
          for m, p in zip(members, pos_before_move)),
      str([(round(m.pos().x(), 1), round(m.pos().y(), 1)) for m in members[:2]]))
check("§4 …and the grid survives the move (still inside, still no overlap)",
      all(g.sceneBoundingRect().contains(m.card_rect_scene().center()) for m in members))
rows_before = len({round(m.pos().y(), 1) for m in members})
g.set_group_size(g.size()[0] * 3.0, 400)
rows_after = len({round(m.pos().y(), 1) for m in members})
check("§4 resizing a folded group re-lays the grid (fewer rows with more columns)",
      rows_after < rows_before and all(m.data.collapsed for m in members),
      f"rows {rows_before} → {rows_after}")
check("§4 the badges stay inside after the resize",
      all(g.sceneBoundingRect().contains(m.card_rect_scene().center()) for m in members))

# Undo/redo of the fold (the group is at a new position: the snapshot is LOCAL)
win4._undo()
check("§4 Ctrl+Z unfolds: the badges are cards again, draggable and restored",
      g.is_collapsed() is False and all(not m.data.collapsed for m in members)
      and all(bool(m.flags() & m.GraphicsItemFlag.ItemIsMovable) for m in members))
check("§4 …the frame size is restored to the pre-fold one",
      abs(g.size()[0] - frame_before[0]) < 0.5 and abs(g.size()[1] - frame_before[1]) < 0.5,
      f"{frame_before} vs {g.size()}")
gpos = g.pos()
check("§4 …every member is back at its pre-fold LOCAL position (a moved group unfolds in place)",
      all(abs(m.pos().x() - (gpos.x() + lx)) < 1.0 and abs(m.pos().y() - (gpos.y() + ly)) < 1.0
          for m, (_i, lx, ly, _c) in zip(members, before_state)),
      str([(round(m.pos().x(), 1), round(m.pos().y(), 1)) for m in members]))
win4._redo()
check("§4 Ctrl+Y folds again (the grid is reproduced)",
      g.is_collapsed() and all(m.data.collapsed for m in members))
win4._undo()

# The context-menu pair (a point in the TITLE band — the frame centre may hold a badge)
title_point = QPointF(g.pos().x() + 10.0, g.pos().y() + 10.0)
menu_open = win4.view.build_context_menu(title_point)
texts_open = [a.text() for a in menu_open.actions()]
check("§4 the group context menu carries 'Collapse Group' while expanded",
      win4.t("ctx.collapse_group") in texts_open and win4.t("ctx.expand_group") not in texts_open,
      str(texts_open))
win4._toggle_group_collapsed(g)
menu_folded = win4.view.build_context_menu(title_point)
texts_folded = [a.text() for a in menu_folded.actions()]
check("§4 …and 'Expand Group' while folded",
      win4.t("ctx.expand_group") in texts_folded
      and win4.t("ctx.collapse_group") not in texts_folded, str(texts_folded))
for act in menu_folded.actions():
    if act.text() == win4.t("ctx.expand_group"):
        act.trigger()
        break
check("§4 the context-menu action unfolds the group", g.is_collapsed() is False)

# A node captured while folded joins the grid (a session fold)
win4._toggle_group_collapsed(g)
newcomer = add_node(win4.scene, "f-new", g.pos().x() + 40, g.pos().y() + 60)
app.processEvents()
check("§4 a node dropped into a folded frame joins the group AND is badged",
      newcomer in set(g.get_members()) and newcomer.data.collapsed is True,
      f"member={newcomer in set(g.get_members())} collapsed={newcomer.data.collapsed}")
check("§4 …and the grid was re-laid out (it is inside the frame)",
      g.sceneBoundingRect().contains(newcomer.card_rect_scene().center()))

# The JSON round-trip: saved folded → loaded folded → unfolded in place
folded_size = g.size()
save_path = os.path.join(WORK, "bigpicture_fold.json")
check("§4 the project saves", win4._do_save(save_path))
with open(save_path, encoding="utf-8") as f:
    raw = json.load(f)
raw_group = [rg for rg in raw.get("groups", []) if rg.get("id") == g.group_id]
check("§4 the saved group record carries the fold keys",
      bool(raw_group) and raw_group[0].get("collapsed") is True
      and "expanded_width" in raw_group[0] and "expanded_height" in raw_group[0],
      str(raw_group))

win_reload = new_window()
win_reload._import_project_raw(raw)
grp_r = win_reload.scene.get_group_by_id(g.group_id)
check("§4 a reloaded FOLDED group comes back folded", grp_r is not None and grp_r.is_collapsed())
check("§4 …with its folded geometry, its members and their badges intact",
      grp_r is not None and abs(grp_r.size()[0] - folded_size[0]) < 0.5
      and len(grp_r.get_members()) == 6
      and all(m.data.collapsed for m in grp_r.get_members()),
      f"{grp_r.size() if grp_r else None} members={len(grp_r.get_members()) if grp_r else 0}")
positions_reload = {m.data.id: (m.pos().x(), m.pos().y()) for m in grp_r.get_members()}
win_reload._toggle_group_collapsed(grp_r)
check("§4 unfolding a RELOADED fold restores the frame size and un-badges in place",
      grp_r.is_collapsed() is False
      and all(not m.data.collapsed for m in grp_r.get_members())
      and abs(grp_r.size()[1] - raw_group[0]["expanded_height"]) < 0.5
      and all(abs(m.pos().x() - positions_reload[m.data.id][0]) < 0.5
              for m in grp_r.get_members()),
      str(grp_r.size()))
close_window(win_reload)

# An old file (no fold keys) loads unfolded
old_raw = {"version": "0.9",
           "servers": [{"id": "old1", "alias": "old-1", "host": "10.0.0.1", "user": "u",
                        "x": 40.0, "y": 60.0}],
           "connections": [],
           "notes": [],
           "groups": [{"id": "oldgrp", "name": "legacy", "x": 0.0, "y": 0.0,
                       "width": 400.0, "height": 300.0}],
           "background": None}
win_old = new_window()
win_old._import_project_raw(old_raw)
grp_old = win_old.scene.get_group_by_id("oldgrp")
check("§4 an old file (no fold keys) loads as an UNFOLDED group",
      grp_old is not None and grp_old.is_collapsed() is False
      and "collapsed" not in grp_old.to_dict(),
      str(grp_old.to_dict() if grp_old else None))
check("§4 …and its member joined by geometry",
      grp_old is not None and len(grp_old.get_members()) == 1,
      str(len(grp_old.get_members()) if grp_old else 0))
close_window(win_old)
close_window(win4)

# ════════════════════════════════════════════════════════════════════════════
print("== §5 i18n parity + the release state ==")
# ════════════════════════════════════════════════════════════════════════════

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)
check_i18n_format(langs)
new_keys = ("view.toggle_minimap", "minimap.tooltip", "ctx.collapse_group", "ctx.expand_group")
check("§5 the four v1.4.2 keys exist in EVERY discovered language",
      all(k in langs[code] for k in new_keys for code in langs),
      str({code: [k for k in new_keys if k not in langs[code]] for code in langs}))
check("§5 the labels are real translations (not the raw keys)",
      all(str(langs[code][k]).strip() and langs[code][k] != k for k in new_keys for code in langs))
check_release_state(ROOT)

finish()
