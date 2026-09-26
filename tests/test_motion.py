# -*- coding: utf-8 -*-
"""v1.4.4 — Motion: the standards, the camera flights, the node scale-in, the hover focus/dim.

Checks (ROADMAP v1.4.4; offscreen, no network, isolated HOME):
  §1 `ui/motion.py` — the standards (150/250/300 ms, OutQuad, the 200 ms scale-in), the pure
     geometry helpers, and the two source-level rules (no `QGraphicsOpacityEffect`, no i18n —
     the release is behaviour only);
  §2 `fly_camera()` — it drives scale+centre to the target (both by hand and through the real
     animation), the zoom stays in sync, out-of-range targets are clamped, a NEW flight starts
     from the CURRENT state (no jump), and the wheel / a mouse press / every instant path stops
     a running flight immediately;
  §3 the app paths — "Fit map" (Ctrl+Shift+F) flies to exactly the transform `fit_to_content()`
     would apply (Qt's own 2 px fit margin), the sidebar reveal flies to the node's card centre
     and keeps the zoom, the collapsed-map guard holds, and the instant paths (the palette, the
     search step, the minimap drag) cancel a flight;
  §4 the node scale-in — `CmdAddRemoveNode`/`CmdAddRemoveNodeBatch` make the card appear
     (scale 0.9 → 1.0 + a fade) while a plain `add_server()` and a project load stay instant;
     the completion is at unit scale/opacity, the transform origin is restored and
     `boundingRect()`/`card_rect_scene()`/`edge_point` are not shifted; a dimmed node keeps its
     dim, and an undo in the middle of the gesture is harmless;
  §5 the arrow hover focus — the scene owns the state, `MainWindow` remains the ONE owner of
     the dim (the hover, the tag filter and the search merge and never stack), the two ends
     light up while the rest recedes, a fast hover/un-hover leaves no residue, and a dying
     arrow/node restores everything;
  §6 the MOTION SWITCH (v1.5rc1) — the flag defaults to ON, only a real False turns it off,
     and with it OFF every gesture applies its FINAL state at once: `fly_camera()` lands on
     the target inside the call (clamps included), a new card is settled at unit scale, and
     `fly_to_content()` still returns True and lands on the instant fit target;
  §7 i18n parity + the release state (v1.5rc1 adds the three "Appearance" keys — the pin is
     the shipped one, 619).

Run: python tests/test_motion.py   (from the project root) or python tests/run_all.py
"""
import ast
import inspect
import os
import sys
import time

from _common import (bootstrap, check, finish, wait_for, load_i18n_langs,
                     check_i18n_parity, check_i18n_format, check_release_state,
                     EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS, translation_keys,
                     i18n_lang_codes)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation, offscreen, faulthandler)

from PySide6.QtCore import QEvent, QEasingCurve, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QGraphicsSceneHoverEvent  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import ui.main_window as MW  # noqa: E402
import ui.motion as motion  # noqa: E402
import ui.command_palette as CP  # noqa: E402
from ui import theme  # noqa: E402
from models.server import ServerData  # noqa: E402
from graphics.map_scene import MapScene  # noqa: E402
from graphics.map_view import MapView  # noqa: E402
from graphics.server_node import ServerNode  # noqa: E402
from graphics.connection_arrow import edge_point  # noqa: E402
from modules.undo_commands import CmdAddRemoveNode, CmdAddRemoveNodeBatch  # noqa: E402

MOTION_SRC = open(os.path.join(ROOT, "ui", "motion.py"), encoding="utf-8").read()


def new_window(width=1000, height=700, show=True):
    """A MainWindow with the autosave timer stopped and a real geometry (the camera needs one)."""
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
        w._undo_baseline_dirty = False
        w.close()
        w.destroy()
    except RuntimeError:
        pass
    app.processEvents()


def add_node(scene, alias, x, y, tags=None, host="10.0.0.1"):
    return scene.add_server(ServerData(id=f"{alias}-id", alias=alias, host=host, user="u",
                                       x=x, y=y, tags=list(tags or [])))


def wheel_event(view, up=True):
    """A synthetic wheel tick over the viewport (PySide6 6.11 needs the full 8-argument form)."""
    delta = QPoint(0, 120 if up else -120)
    event = QWheelEvent(QPointF(40.0, 40.0), QPointF(40.0, 40.0), QPoint(0, 0), delta,
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    view.wheelEvent(event)


def mouse_event(kind, buttons):
    """A synthetic mouse event for the view (position 120,120 — empty space on a fresh map)."""
    return QMouseEvent(kind, QPointF(120.0, 120.0), QPointF(120.0, 120.0),
                       buttons, buttons, Qt.KeyboardModifier.NoModifier)


def hover_event(entering=True):
    """The scene hover event Qt sends to the item (the arrow reports it to the scene)."""
    kind = (QEvent.Type.GraphicsSceneHoverEnter if entering
            else QEvent.Type.GraphicsSceneHoverLeave)
    return QGraphicsSceneHoverEvent(kind)


def set_tag_filter(win, tag):
    """Select a tag in the sidebar filter (refresh_sidebar recomputes the dimming)."""
    combo = win.tag_filter
    for i in range(combo.count()):
        if combo.itemData(i) == tag:
            combo.setCurrentIndex(i)
            app.processEvents()
            return True
    return False


def dimmed_ids(win):
    """The ids of the nodes currently dimmed by the map dimming owner."""
    return sorted(n.data.id for n in win.scene.nodes() if n.opacity() < 1.0)


def matched_ids(win):
    """The ids of the nodes carrying the accent/search highlight frame right now."""
    return sorted(n.data.id for n in win.scene.nodes() if n.search_matched)


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the standards (ui/motion.py) ==")
# ════════════════════════════════════════════════════════════════════════════

check("§1 the three durations are the pinned standards (150 / 250 / 300 ms)",
      (motion.DURATION_FAST, motion.DURATION_NORMAL, motion.DURATION_SLOW) == (150, 250, 300)
      and motion.DURATION_FAST < motion.DURATION_NORMAL < motion.DURATION_SLOW,
      f"{motion.DURATION_FAST}/{motion.DURATION_NORMAL}/{motion.DURATION_SLOW}")
check("§1 the easing is OutQuad (one curve for the whole app)",
      motion.EASING == QEasingCurve.Type.OutQuad, str(motion.EASING))
check("§1 the scale-in standard is 200 ms from 0.9",
      motion.SCALE_IN_MS == 200 and abs(motion.SCALE_IN_FROM - 0.9) < 1e-9,
      f"{motion.SCALE_IN_MS} ms / {motion.SCALE_IN_FROM}")

_fly_sig = inspect.signature(motion.fly_camera)
check("§1 fly_camera(view, target_scale, target_center, ms=250) — the ROADMAP signature",
      list(_fly_sig.parameters) == ["view", "target_scale", "target_center", "ms"]
      and _fly_sig.parameters["ms"].default == motion.DURATION_NORMAL,
      str(_fly_sig))
def effect_names(path):
    """The identifiers the CODE of a file mentions (comments/docstrings excluded — AST)."""
    tree = ast.parse(open(os.path.join(ROOT, path), encoding="utf-8").read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.name.rsplit(".", 1)[-1])
    return names


MOTION_FILES = ["ui/motion.py", "graphics/map_view.py", "graphics/map_scene.py",
                "graphics/server_node.py", "graphics/connection_arrow.py"]
_effect_users = [f for f in MOTION_FILES if "QGraphicsOpacityEffect" in effect_names(f)]
check("§1 no opacity-effect layer anywhere in the touched files (the v1.2.10 audit rule)",
      not _effect_users, str(_effect_users))
check("§1 the AST audit really reads the code (a guard over nothing is useless)",
      "QVariantAnimation" in effect_names("ui/motion.py")
      and "QGraphicsOpacityEffect" not in effect_names("ui/motion.py"))
check("§1 the module knows no core module (graphics/ui.main_window) — no cycles",
      "from graphics" not in MOTION_SRC and "import graphics" not in MOTION_SRC
      and "main_window" not in MOTION_SRC)
check("§1 the module carries no user-facing string (v1.4.4 adds no i18n key)",
      "from i18n" not in MOTION_SRC and "import i18n" not in MOTION_SRC,
      "motion is behaviour only")

win1 = new_window()
view1 = win1.view
check("§1 zoom_bounds exposes the view's own range", motion.zoom_bounds(view1) == (0.1, 5.0),
      str(motion.zoom_bounds(view1)))
check("§1 clamp_scale clamps into the range",
      abs(motion.clamp_scale(view1, 99.0) - 5.0) < 1e-9
      and abs(motion.clamp_scale(view1, 0.0001) - 0.1) < 1e-9,
      str((motion.clamp_scale(view1, 99.0), motion.clamp_scale(view1, 0.0001))))
check("§1 clamp_scale with an unusable value keeps the current scale",
      abs(motion.clamp_scale(view1, "junk") - motion.camera_scale(view1)) < 1e-9)
check("§1 camera_scale/camera_center read the LIVE view",
      abs(motion.camera_scale(view1) - float(view1.transform().m11())) < 1e-9
      and abs(motion.camera_center(view1).x()
              - view1.mapToScene(view1.viewport().rect().center()).x()) < 1e-6,
      f"{motion.camera_scale(view1)} {motion.camera_center(view1)}")
check("§1 an unusable view falls back to the documented defaults",
      motion.camera_scale(None) == 1.0 and motion.camera_center(None) == QPointF(0.0, 0.0))
check("§1 no flight is running on a fresh window",
      motion.active_flight(view1) is None and not motion.is_flying(view1))

# ════════════════════════════════════════════════════════════════════════════
print("== §2 fly_camera: the target, the restart, the interruption ==")
# ════════════════════════════════════════════════════════════════════════════

zooms = []
view1.zoomChanged.connect(lambda z: zooms.append(float(z)))

flight = motion.fly_camera(view1, 1.5, QPointF(300.0, 200.0), ms=250)
check("§2 fly_camera returns a flight and owns the camera",
      flight is not None and motion.is_flying(view1)
      and motion.active_flight(view1) is flight,
      str(flight))
check("§2 the start state is the CURRENT one (no jump on creation)",
      abs(flight.start_scale - motion.camera_scale(view1)) < 1e-9,
      f"{flight.start_scale} vs {motion.camera_scale(view1)}")
check("§2 the animation runs for the requested duration",
      flight.duration_ms == 250 and flight.animation is not None
      and flight.animation.duration() == 250, str(flight.duration_ms))

flight.progress(1.0)
landed = motion.camera_center(view1)
check("§2 driving the flight by hand lands on the target scale",
      abs(motion.camera_scale(view1) - 1.5) < 1e-9, str(motion.camera_scale(view1)))
check("§2 …and on the target centre",
      abs(landed.x() - 300.0) < 1.0 and abs(landed.y() - 200.0) < 1.0, str(landed))
check("§2 the zoom of the view follows the camera (the status-bar % stays honest)",
      abs(view1.zoom - 1.5) < 1e-9 and zooms and abs(zooms[-1] - 1.5) < 1e-9,
      f"zoom={view1.zoom} signals={zooms[-3:]}")

# the real animation (the event loop) reaches the same state
flight2 = motion.fly_camera(view1, 0.5, QPointF(-200.0, -150.0), ms=120)
finished = wait_for(lambda: not motion.is_flying(view1), timeout_ms=2500)
landed2 = motion.camera_center(view1)
check("§2 the real animation finishes within its budget", finished and flight2.active is False)
check("§2 …at the requested scale/centre (the scrollbars are integer — ~1 device px of slack)",
      abs(motion.camera_scale(view1) - 0.5) < 1e-6
      and abs(landed2.x() + 200.0) < 3.0 and abs(landed2.y() + 150.0) < 3.0,
      f"scale={motion.camera_scale(view1)} center={landed2}")
check("§2 the flight is not left owning the camera after landing",
      motion.active_flight(view1) is None and flight2.active is False,
      str(motion.active_flight(view1)))

# the target scale is clamped into the view's range
flight3 = motion.fly_camera(view1, 99.0, QPointF(0.0, 0.0), ms=100)
check("§2 an out-of-range target scale is clamped (99 -> ZOOM_MAX)",
      abs(flight3.target_scale - MapView.ZOOM_MAX) < 1e-9, str(flight3.target_scale))
flight3.stop()

# a zero-length flight is the instant move
flight4 = motion.fly_camera(view1, 2.0, QPointF(10.0, 20.0), ms=0)
check("§2 a zero-length flight lands immediately (no event loop needed)",
      flight4 is not None and flight4.active is False
      and abs(motion.camera_scale(view1) - 2.0) < 1e-9,
      f"scale={motion.camera_scale(view1)}")

# unusable inputs
check("§2 an unusable view/target is refused instead of crashing",
      motion.fly_camera(None, 1.0, QPointF(0.0, 0.0)) is None
      and motion.fly_camera(view1, 1.0, object()) is None)

# a NEW flight during an old one: restart from the current state, no jump, correct end state
old = motion.fly_camera(view1, 3.0, QPointF(1000.0, 1000.0), ms=400)
old.progress(0.5)
mid_scale = motion.camera_scale(view1)
mid_center = motion.camera_center(view1)
try:
    new = motion.fly_camera(view1, 1.25, QPointF(-50.0, -60.0), ms=200)
    crashed = False
except Exception as e:  # noqa: BLE001
    crashed = True
    new = None
    print("   restart exception:", repr(e))
check("§2 a new flight over an old one does not raise", not crashed and new is not None)
check("§2 the old flight is stopped, the new one starts where the camera IS (no jump)",
      old.active is False and abs(new.start_scale - mid_scale) < 1e-9
      and abs(new.start_center.x() - mid_center.x()) < 1e-6
      and abs(new.start_center.y() - mid_center.y()) < 1e-6,
      f"old={old.active} start={new.start_scale}/{new.start_center}")
new.progress(1.0)
final = motion.camera_center(view1)
check("§2 the end state of the interrupting flight is correct",
      abs(motion.camera_scale(view1) - 1.25) < 1e-9
      and abs(final.x() + 50.0) < 2.0 and abs(final.y() + 60.0) < 2.0,
      f"scale={motion.camera_scale(view1)} center={final}")

# the user's wheel stops the flight immediately
motion.fly_camera(view1, 4.0, QPointF(500.0, 500.0), ms=600)
check("§2 a flight is running before the wheel", motion.is_flying(view1))
wheel_event(view1)
check("§2 the WHEEL stops the flight (manual control wins)",
      not motion.is_flying(view1), str(motion.active_flight(view1)))
scale_after_wheel = motion.camera_scale(view1)
app.processEvents()
check("§2 …and the camera does not keep moving after the stop",
      abs(motion.camera_scale(view1) - scale_after_wheel) < 1e-9,
      f"{scale_after_wheel} -> {motion.camera_scale(view1)}")

# a mouse press (a pan / a node drag) stops the flight too
motion.fly_camera(view1, 3.5, QPointF(800.0, 100.0), ms=600)
view1.mousePressEvent(mouse_event(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton))
check("§2 a MOUSE PRESS stops the flight", not motion.is_flying(view1))
view1.mouseReleaseEvent(mouse_event(QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton))

# stop_camera / MapView.stop_camera_flight
motion.fly_camera(view1, 1.0, QPointF(0.0, 0.0), ms=600)
check("§2 MapView.stop_camera_flight cancels a running flight",
      view1.stop_camera_flight() is True and not motion.is_flying(view1))
check("§2 stop_camera_flight is a no-op when nothing flies",
      view1.stop_camera_flight() is False)

# every instant navigation path cancels a flight
for name, action in (
        ("reset_zoom", lambda: view1.reset_zoom()),
        ("a keyboard zoom step", lambda: view1.zoom_in()),
        ("fit_to_content()", lambda: view1.fit_to_content()),
        ("set_zoom_and_center()", lambda: view1.set_zoom_and_center(1.0, 0.0, 0.0))):
    motion.fly_camera(view1, 4.0, QPointF(400.0, 400.0), ms=600)
    action()
    check(f"§2 the instant path {name} cancels a running flight", not motion.is_flying(view1))

close_window(win1)

# ════════════════════════════════════════════════════════════════════════════
print("== §3 the camera flights in the app (Fit map, Show on map) ==")
# ════════════════════════════════════════════════════════════════════════════

win3 = new_window()
view3 = win3.view
n_a = add_node(win3.scene, "cam-a", -400, -250)
n_b = add_node(win3.scene, "cam-b", 600, 420)
app.processEvents()

target = view3.fit_view_target()
check("§3 fit_view_target exposes the target of the instant fit", target is not None, str(target))
check("§3 …reproducing Qt's own 2 px fit margin (the flight lands ON the fit)",
      abs(target[0] - 0.0) > 0 and view3.FIT_VIEW_MARGIN_PX == 2,
      str(view3.FIT_VIEW_MARGIN_PX))
check("§3 the target centre is the content centre",
      abs(target[1].x() - view3.content_bounding_rect().center().x()) < 1e-6,
      str(target[1]))
twin = new_window()
check("§3 the twin window has the same viewport (the comparison is honest)",
      twin.view.viewport().width() == view3.viewport().width()
      and twin.view.viewport().height() == view3.viewport().height(),
      f"{twin.view.viewport().size()} vs {view3.viewport().size()}")
add_node(twin.scene, "cam-a", -400, -250)
add_node(twin.scene, "cam-b", 600, 420)
app.processEvents()
twin.view.fit_to_content()   # the instant primitive
check("§3 the flight target equals the transform the instant fit produces",
      abs(twin.view.transform().m11() - target[0]) < 1e-9,
      f"flight={target[0]} instant={twin.view.transform().m11()}")
close_window(twin)

check("§3 fly_to_content starts a flight instead of snapping",
      view3.fly_to_content() is True and motion.is_flying(view3))
check("§3 …and lands exactly on the instant fit target",
      wait_for(lambda: not motion.is_flying(view3), timeout_ms=2500)
      and abs(motion.camera_scale(view3) - target[0]) < 1e-6
      and abs(motion.camera_center(view3).x() - target[1].x()) < 2.0,
      f"scale={motion.camera_scale(view3)} target={target[0]}")

# the ACTION ("Fit map", Ctrl+Shift+F) goes through the same flight
view3.reset_zoom()
win3._fit_to_content()
check("§3 the Fit map ACTION flies (no snap)", motion.is_flying(view3))
check("§3 …and lands on the content",
      wait_for(lambda: not motion.is_flying(view3), timeout_ms=2500)
      and motion.camera_scale(view3) < 1.0, str(motion.camera_scale(view3)))

# nothing to frame
win_empty = new_window()
check("§3 Fit map on an empty map starts no flight and keeps the hint",
      win_empty.view.fly_to_content() is False and not motion.is_flying(win_empty.view))
win_empty._fit_to_content()
check("§3 …the action is a no-op there (no exception, no flight)",
      not motion.is_flying(win_empty.view))
close_window(win_empty)

# the collapsed-map guard
win3.act_show_map.setChecked(False)
app.processEvents()
win3._fit_to_content()
check("§3 Fit map with the map collapsed stays a no-op (the v1.2.4.1 guard)",
      not motion.is_flying(win3.view))
win3._reveal_node_on_map(n_a)
check("§3 the reveal on a collapsed map selects but does not fly (and does not show the map)",
      not motion.is_flying(win3.view) and n_a.isSelected() and win3.view.isHidden())
win3.act_show_map.setChecked(True)
win3.view.set_zoom_and_center(1.0, 0.0, 0.0)
app.processEvents()

# the reveal: a smooth flight to the node's card centre, at the CURRENT zoom
zoom_before = view3.zoom
win3._reveal_node_on_map(n_b)
check("§3 Show on map starts a camera flight", motion.is_flying(win3.view))
check("§3 …it keeps the zoom (a reveal is a pan, not a zoom change)",
      abs(motion.active_flight(win3.view).target_scale - zoom_before) < 1e-9,
      str(motion.active_flight(win3.view).target_scale))
check("§3 …and lands with the node's CARD centre under the viewport centre",
      wait_for(lambda: not motion.is_flying(win3.view), timeout_ms=2500)
      and abs(motion.camera_center(win3.view).x()
              - n_b.card_rect_scene().center().x()) < 3.0
      and abs(motion.camera_center(win3.view).y()
              - n_b.card_rect_scene().center().y()) < 3.0,
      str(motion.camera_center(win3.view)))
check("§3 the reveal still selects the node and flashes it (the v0.9.6 path)",
      n_b.isSelected() and n_b._pulse.isVisible())

# the instant paths cancel a flight
motion.fly_camera(view3, 3.0, QPointF(900.0, 900.0), ms=600)
win3._select_node(n_a, center=True)
check("§3 an instant _select_node(center=True) cancels a running flight",
      not motion.is_flying(view3))
motion.fly_camera(view3, 3.0, QPointF(900.0, 900.0), ms=600)
CP.CommandPalette._reveal_node(n_a)   # the Ctrl+K palette jumps to the node
check("§3 the command palette cancels a running flight", not motion.is_flying(view3))
motion.fly_camera(view3, 3.0, QPointF(900.0, 900.0), ms=600)
win3._on_minimap_center(QPointF(120.0, 140.0))
check("§3 dragging the minimap cancels a running flight", not motion.is_flying(view3))

# the flight does not block a plain instant centering from working
win3.view.centerOn(n_a)
check("§3 a direct centerOn still works after the flights", not motion.is_flying(view3))
close_window(win3)

# ════════════════════════════════════════════════════════════════════════════
print("== §4 the node scale-in (CmdAddRemoveNode / the batch import) ==")
# ════════════════════════════════════════════════════════════════════════════

win4 = new_window()
win4._dirty = False
win4._undo_baseline_dirty = False
data4 = ServerData(id="scale1", alias="twin", host="10.0.0.11", user="u", x=-400.0, y=-300.0)
win4._push_command(CmdAddRemoveNode(win4, win4.scene, data4, "add"))
node4 = win4.scene.get_node("scale1")
check("§4 CmdAddRemoveNode(add) makes the card APPEAR (not just pop in)",
      node4 is not None and motion.is_scaling_in(node4),
      f"scaling={motion.is_scaling_in(node4)}")
check("§4 …starting from the pinned 0.9 scale",
      abs(node4.scale() - motion.SCALE_IN_FROM) < 1e-9, str(node4.scale()))
check("§4 …and from a faded-in opacity (the item's OWN property — no opacity effect)",
      node4.opacity() < 1.0, str(node4.opacity()))
check("§4 the gesture is remembered on the item (a QGraphicsItem cannot parent a QObject)",
      motion.active_scale_in(node4) is not None)
check("§4 …and the item's boundingRect() is a card + halo, not an effect layer",
      node4.boundingRect().width() >= ServerNode.MIN_NODE_WIDTH - 0.5)
check("§4 the scale-in completes to unit within its budget",
      wait_for(lambda: abs(node4.scale() - 1.0) < 1e-9 and node4.opacity() == 1.0
               and not motion.is_scaling_in(node4), timeout_ms=2500),
      f"scale={node4.scale()} opacity={node4.opacity()}")

# the twin that never animated: the geometry must be identical
plain4 = win4.scene.add_server(ServerData(id="plain1", alias="twin", host="10.0.0.11", user="u",
                                          x=-400.0, y=200.0))
check("§4 a plain add_server() does NOT animate (project load, fixtures, tools)",
      not motion.is_scaling_in(plain4) and plain4.opacity() == 1.0 and plain4.scale() == 1.0,
      f"scale={plain4.scale()} opacity={plain4.opacity()}")
card4 = node4.card_rect_scene()
card_plain = plain4.card_rect_scene()
check("§4 the ended gesture leaves the SAME card rect as the un-animated twin",
      abs(card4.width() - card_plain.width()) < 1e-6
      and abs(card4.height() - card_plain.height()) < 1e-6,
      f"{card4} vs {card_plain}")
check("§4 the transform origin is restored (no hidden scaling for a later group resize)",
      node4.transformOriginPoint() == QPointF(0.0, 0.0), str(node4.transformOriginPoint()))
check("§4 boundingRect() equals the twin's (a card + its shadow halo)",
      abs(node4.boundingRect().width() - plain4.boundingRect().width()) < 1e-6
      and abs(node4.boundingRect().height() - plain4.boundingRect().height()) < 1e-6,
      f"{node4.boundingRect()} vs {plain4.boundingRect()}")
# edge_point is the anchor of every arrow: the same relative direction must give the same point
toward4 = QPointF(card4.center().x() + 200.0, card4.center().y() + 90.0)
toward_plain = QPointF(card_plain.center().x() + 200.0, card_plain.center().y() + 90.0)
ep4 = edge_point(card4, card4.center(), toward4)
ep_plain = edge_point(card_plain, card_plain.center(), toward_plain)
check("§4 edge_point() is not shifted by the gesture (the arrow anchor is honest)",
      abs((ep4.x() - card4.left()) - (ep_plain.x() - card_plain.left())) < 1e-6
      and abs((ep4.y() - card4.top()) - (ep_plain.y() - card_plain.top())) < 1e-6,
      f"{ep4} vs {ep_plain}")

# a connection anchored WHILE the card is still small must end up on the settled card
anchor_target = win4.scene.get_node("plain1")
data_anchor = ServerData(id="anch1", alias="anchor", host="10.0.0.21", user="u",
                         x=1500.0, y=-300.0)
win4._push_command(CmdAddRemoveNode(win4, win4.scene, data_anchor, "add"))
anim_node = win4.scene.get_node("anch1")
mid_arrow = win4.scene.add_connection("anch1", "plain1", "l", "ssh")
tip_before = QPointF(mid_arrow._curve_pts[0])   # p0 = the SOURCE edge (the animated card)
check("§4 the arrow of a mid-gesture card is anchored on the SCALED card first",
      anim_node.scale() < 1.0 and tip_before != QPointF(0.0, 0.0), str(tip_before))
scaled_card = anim_node.card_rect_scene()
on_scaled_edge = (abs(tip_before.x() - scaled_card.left()) < 0.5
                  or abs(tip_before.x() - scaled_card.right()) < 0.5
                  or abs(tip_before.y() - scaled_card.top()) < 0.5
                  or abs(tip_before.y() - scaled_card.bottom()) < 0.5)
check("§4 …on the scaled card's own edge (not on the settled one yet)",
      on_scaled_edge and scaled_card.width() < 197.0,
      f"tip={tip_before} scaled_card={scaled_card}")
wait_for(lambda: not motion.is_scaling_in(anim_node), timeout_ms=2500)
tip_after = QPointF(mid_arrow._curve_pts[0])
settled_card = anim_node.card_rect_scene()
on_edge = (abs(tip_after.x() - settled_card.left()) < 0.5
           or abs(tip_after.x() - settled_card.right()) < 0.5
           or abs(tip_after.y() - settled_card.top()) < 0.5
           or abs(tip_after.y() - settled_card.bottom()) < 0.5)
check("§4 …and the end of the gesture RE-ANCHORS it on the settled card (edge_point honest)",
      on_edge and (abs(tip_after.x() - tip_before.x()) > 0.01
                   or abs(tip_after.y() - tip_before.y()) > 0.01),
      f"before={tip_before} after={tip_after} card={settled_card}")
check("§4 the anchor node is a plain node (the fixture is honest)",
      anchor_target is not None and abs(anchor_target.scale() - 1.0) < 1e-9)

# the batch import animates every node of the batch
batch = [ServerData(id=f"batch{i}", alias=f"b{i}", host="10.0.0.2", user="u",
                    x=-900.0 + i * 200, y=600.0) for i in range(3)]
win4._push_command(CmdAddRemoveNodeBatch(win4, win4.scene, batch, "add"))
batch_nodes = [win4.scene.get_node(f"batch{i}") for i in range(3)]
check("§4 the batch import animates every node of the batch",
      all(motion.is_scaling_in(n) for n in batch_nodes),
      str([motion.is_scaling_in(n) for n in batch_nodes]))
check("§4 …and every one of them settles at unit scale/opacity",
      wait_for(lambda: all(abs(n.scale() - 1.0) < 1e-9 and n.opacity() == 1.0
                           for n in batch_nodes), timeout_ms=2500),
      str([(n.scale(), n.opacity()) for n in batch_nodes]))

# a project load never animates
win4._import_project_raw({"version": "0.9",
                          "servers": [{"id": "load1", "alias": "loaded", "host": "10.0.0.9",
                                       "user": "u", "x": 100.0, "y": 100.0}],
                          "connections": [], "notes": [], "groups": []})
loaded = win4.scene.get_node("load1")
check("§4 a project load stays instant (opening a 500-node map is not a light show)",
      loaded is not None and not motion.is_scaling_in(loaded)
      and loaded.scale() == 1.0 and loaded.opacity() == 1.0,
      f"scale={loaded.scale()} opacity={loaded.opacity()}")

# a dimmed card keeps its dim when the gesture ends (the owner wins)
data5 = ServerData(id="dim5", alias="dimmed", host="10.0.0.5", user="u", x=900.0, y=-400.0)
win4._push_command(CmdAddRemoveNode(win4, win4.scene, data5, "add"))
node5 = win4.scene.get_node("dim5")
node5.set_dimmed(True)
check("§4 a node added by the owner as DIMMED keeps the dim after the scale-in",
      wait_for(lambda: not motion.is_scaling_in(node5), timeout_ms=2500)
      and abs(node5.opacity() - ServerNode.DIM_OPACITY) < 1e-9,
      f"opacity={node5.opacity()}")
node5.set_dimmed(False)

# an undo in the middle of the gesture: nothing to resurrect, nothing to crash
data6 = ServerData(id="undomid", alias="mid", host="10.0.0.6", user="u", x=200.0, y=700.0)
win4._push_command(CmdAddRemoveNode(win4, win4.scene, data6, "add"))
node6 = win4.scene.get_node("undomid")
check("§4 the node of the interrupted gesture is animating", motion.is_scaling_in(node6))
try:
    win4.undo_stack.undo()
    win4.undo_stack.redo()
    error6 = None
except Exception as e:  # noqa: BLE001
    error6 = e
check("§4 undoing/redoing an adding node mid-gesture raises nothing", error6 is None,
      repr(error6))
check("§4 …the node is back and settles at unit scale",
      wait_for(lambda: abs(win4.scene.get_node("undomid").scale() - 1.0) < 1e-9,
               timeout_ms=2500),
      str(win4.scene.get_node("undomid").scale()))
node6_now = win4.scene.get_node("undomid")
win4.undo_stack.undo()
for _ in range(14):   # let the dead item's animation try to fire (it must stay silent)
    app.processEvents()
    time.sleep(0.03)
check("§4 …and the removed node does not come back on its own and nothing raises",
      not win4.scene.has_node("undomid") and node6_now is not None
      and node6_now.scene() is None)

# stop_scale_in settles an interrupted gesture
data7 = ServerData(id="stop7", alias="stop", host="10.0.0.7", user="u", x=500.0, y=900.0)
win4._push_command(CmdAddRemoveNode(win4, win4.scene, data7, "add"))
node7 = win4.scene.get_node("stop7")
check("§4 stop_scale_in settles a running gesture to unit",
      motion.stop_scale_in(node7) is True
      and abs(node7.scale() - 1.0) < 1e-9 and node7.opacity() == 1.0
      and not motion.is_scaling_in(node7),
      f"scale={node7.scale()} opacity={node7.opacity()}")
check("§4 …and is a no-op when nothing is running (idempotent)",
      motion.stop_scale_in(node7) is False)
check("§4 scale_in(None) is a safe no-op", motion.scale_in(None) is None)
close_window(win4)

# ════════════════════════════════════════════════════════════════════════════
print("== §5 the arrow hover focus / dim (one owner) ==")
# ════════════════════════════════════════════════════════════════════════════

win5 = new_window()
h1 = add_node(win5.scene, "hov-1", 0, 0)
h2 = add_node(win5.scene, "hov-2", 600, 300)
h3 = add_node(win5.scene, "hov-3", 900, 0, tags=["prod"])
arrow = win5.scene.add_connection("hov-1-id", "hov-2-id", "l", "ssh")
other = win5.scene.add_connection("hov-2-id", "hov-3-id", "l", "vpn")
app.processEvents()

check("§5 a fresh scene has no hover focus",
      win5.scene.hover_focus_arrow() is None and not dimmed_ids(win5), str(dimmed_ids(win5)))
signalled = []
win5.scene.hover_focus_changed.connect(lambda a: signalled.append(a))
check("§5 set_hover_focus_arrow stores the arrow and reports it",
      win5.scene.set_hover_focus_arrow(arrow) is True
      and win5.scene.hover_focus_arrow() is arrow and signalled[-1] is arrow)
check("§5 …and a repeated enter of the SAME arrow is a no-op (idempotent)",
      win5.scene.set_hover_focus_arrow(arrow) is False and len(signalled) == 1)

check("§5 hovering dims every OTHER node (DIM_OPACITY)",
      dimmed_ids(win5) == ["hov-3-id"], str(dimmed_ids(win5)))
check("§5 …at the pinned opacity",
      abs(h3.opacity() - ServerNode.DIM_OPACITY) < 1e-9, str(h3.opacity()))
check("§5 …while the two ends stay fully visible AND carry the accent frame",
      h1.opacity() == 1.0 and h2.opacity() == 1.0
      and h1.search_matched and h2.search_matched
      and h1._bg.pen().color().name() == QColor(theme.ACCENT).name(),
      f"{h1.opacity()}/{h2.opacity()} pen={h1._bg.pen().color().name()}")
check("§5 the highlight is the accent pen of the ACTIVE theme",
      h2._bg.pen().color().name() == QColor(ServerNode.SEARCH_MATCH_COLOR).name(),
      h2._bg.pen().color().name())

# the hover reaches the ONE owner of the dim (MainWindow._apply_map_dimming), not the scene
_hover_calls = []
_orig_apply = win5._apply_map_dimming
win5._apply_map_dimming = lambda: (_hover_calls.append(1), _orig_apply())[1]
win5.scene.set_hover_focus_arrow(other)
win5._apply_map_dimming = _orig_apply
check("§5 the hover re-enters the single dim owner (never a second set_dimmed writer)",
      len(_hover_calls) == 1, f"calls={len(_hover_calls)}")
win5.scene.clear_hover_focus(other)
win5.scene.set_hover_focus_arrow(arrow)

check("§5 un-hover restores everything",
      win5.scene.clear_hover_focus(arrow) is True
      and win5.scene.hover_focus_arrow() is None
      and not dimmed_ids(win5) and not matched_ids(win5),
      f"dim={dimmed_ids(win5)} match={matched_ids(win5)}")
check("§5 clearing an already-clear focus is a no-op",
      win5.scene.clear_hover_focus() is False)

# the REAL event path: the arrow reports the hover to the scene
arrow.hoverEnterEvent(hover_event(True))
check("§5 the arrow's hoverEnterEvent reaches the scene", win5.scene.hover_focus_arrow() is arrow)
arrow.hoverLeaveEvent(hover_event(False))
check("§5 the arrow's hoverLeaveEvent clears it", win5.scene.hover_focus_arrow() is None)
check("§5 …and the dim is fully restored by the real events",
      not dimmed_ids(win5) and not matched_ids(win5))

# a fast hover/un-hover storm leaves no residue
for _ in range(12):
    arrow.hoverEnterEvent(hover_event(True))
    other.hoverEnterEvent(hover_event(True))
    arrow.hoverLeaveEvent(hover_event(False))
    other.hoverLeaveEvent(hover_event(False))
app.processEvents()
check("§5 a fast hover/un-hover storm leaves no stuck dim",
      win5.scene.hover_focus_arrow() is None and not dimmed_ids(win5) and not matched_ids(win5),
      f"focus={win5.scene.hover_focus_arrow()} dim={dimmed_ids(win5)}")

# the stale leave of an OLD arrow must not clear a NEWER focus
win5.scene.set_hover_focus_arrow(arrow)
win5.scene.set_hover_focus_arrow(other)
win5.scene.clear_hover_focus(arrow)   # the old arrow's delayed leave
check("§5 a stale leave of the previous arrow keeps the NEW focus",
      win5.scene.hover_focus_arrow() is other, str(win5.scene.hover_focus_arrow()))
win5.scene.clear_hover_focus(other)

# the arrow that dies while hovered (delete a connection / a node) restores the map
win5.scene.set_hover_focus_arrow(arrow)
win5.scene.remove_connection(arrow)
check("§5 removing the hovered arrow clears the focus and the dim",
      win5.scene.hover_focus_arrow() is None and not dimmed_ids(win5) and not matched_ids(win5))
win5.scene.set_hover_focus_arrow(other)
win5.scene.remove_server("hov-2-id")   # the node takes its arrows with it
check("§5 deleting a node of the hovered connection restores the map too",
      win5.scene.hover_focus_arrow() is None and not dimmed_ids(win5))
check("§5 …and the third node is still there",
      win5.scene.has_node("hov-3-id") and win5.scene.arrow_count() == 0)

# the SEARCH and the hover merge into ONE dim state (they never stack)
win5.scene.add_server(ServerData(id="hov-4", alias="web-4", host="10.0.0.4", user="u",
                                 x=300.0, y=800.0))
win5.scene.add_connection("hov-1-id", "hov-3-id", "l", "http")
win5.refresh_sidebar()
win5._on_map_search_query("web-4")
check("§5 the search alone dims the non-matches",
      matched_ids(win5) == ["hov-4"] and "hov-1-id" in dimmed_ids(win5),
      f"match={matched_ids(win5)} dim={dimmed_ids(win5)}")
hover_arrow = win5.scene.arrows()[0]
win5.scene.set_hover_focus_arrow(hover_arrow)
check("§5 the hover focus wins over the search (the ends are read, the rest recedes)",
      matched_ids(win5) == sorted([hover_arrow.source.data.id, hover_arrow.target.data.id])
      and "hov-4" in dimmed_ids(win5),
      f"match={matched_ids(win5)} dim={dimmed_ids(win5)}")
win5.scene.clear_hover_focus(hover_arrow)
check("§5 un-hovering restores the SEARCH's own state exactly (no stacking)",
      matched_ids(win5) == ["hov-4"] and "hov-1-id" in dimmed_ids(win5),
      f"match={matched_ids(win5)} dim={dimmed_ids(win5)}")
win5._close_map_search()
check("§5 closing the search restores the plain map",
      not dimmed_ids(win5) and not matched_ids(win5))

# the TAG FILTER and the hover merge in the same owner
check("§5 the tag filter dims the nodes without the tag",
      set_tag_filter(win5, "prod") and "hov-1-id" in dimmed_ids(win5)
      and "hov-3-id" not in dimmed_ids(win5), str(dimmed_ids(win5)))
filter_arrow = [a for a in win5.scene.arrows()
                if a.source.data.id == "hov-1-id" and a.target.data.id == "hov-3-id"][0]
win5.scene.set_hover_focus_arrow(filter_arrow)
check("§5 hovering an arrow lifts its ends even out of the tag filter's dim",
      "hov-1-id" not in dimmed_ids(win5) and "hov-4" in dimmed_ids(win5),
      str(dimmed_ids(win5)))
win5.scene.clear_hover_focus(filter_arrow)
check("§5 and the tag filter comes back on un-hover",
      "hov-1-id" in dimmed_ids(win5) and "hov-3-id" not in dimmed_ids(win5),
      str(dimmed_ids(win5)))
win5.tag_filter.setCurrentIndex(0)   # "All tags"
app.processEvents()
check("§5 resetting the filter leaves a clean map",
      not dimmed_ids(win5) and not matched_ids(win5), str(dimmed_ids(win5)))

# the scene owns the state even WITHOUT a window (headless use)
bare = MapScene()
bn1 = bare.add_server(ServerData(id="bare1", alias="b1", host="10.0.0.1", user="u"))
bn2 = bare.add_server(ServerData(id="bare2", alias="b2", host="10.0.0.2", user="u"))
bare_arrow = bare.add_connection("bare1", "bare2", "", "ssh")
check("§5 the scene API works without a window attached",
      bare.set_hover_focus_arrow(bare_arrow) is True
      and bare.hover_focus_arrow() is bare_arrow
      and bare.clear_hover_focus() is True and bare.hover_focus_arrow() is None)
bare.clear_all()
check("§5 clear_all() drops the focus (a replaced project cannot keep a dim)",
      bare.hover_focus_arrow() is None)
close_window(win5)

# ════════════════════════════════════════════════════════════════════════════
print("== §6 the motion switch (v1.5rc1) ==")
# ════════════════════════════════════════════════════════════════════════════

check("§6 the flag defaults to ON — the behaviour of every release before v1.5rc1",
      motion.motion_enabled() is True and motion.set_motion_enabled(True) is True)
check("§6 set_motion_enabled reads nothing but a REAL False as 'off'",
      motion.set_motion_enabled(0) is True and motion.set_motion_enabled("no") is True
      and motion.set_motion_enabled(None) is True
      and motion.set_motion_enabled(False) is False
      and motion.set_motion_enabled(True) is True)
check("§6 the module still carries no user-facing string (the label lives in the hub)",
      "from i18n" not in MOTION_SRC and "import i18n" not in MOTION_SRC)

win6 = new_window()
view6 = win6.view
view6.resize(600, 400)
app.processEvents()
motion.set_motion_enabled(True)

# ── the camera: the SAME destination, reached inside the call ────────────────
motion.set_motion_enabled(False)
flight_off = motion.fly_camera(view6, 2.5, QPointF(300.0, 200.0), ms=600)
landed_off = motion.camera_center(view6)
check("§6 with the motion reduced fly_camera() lands on the target INSIDE the call",
      flight_off is not None and not motion.is_flying(view6)
      and abs(motion.camera_scale(view6) - 2.5) < 1e-9
      and abs(landed_off.x() - 300.0) < 1.0 and abs(landed_off.y() - 200.0) < 1.0,
      f"scale={motion.camera_scale(view6)} center={landed_off}")
check("§6 …and it is a zero-length flight, not a skipped one (the animation object exists)",
      flight_off.duration_ms == 0 and flight_off.animation is None
      and flight_off.active is False)
check("§6 the CLAMP is the same code path (an out-of-range target still clamps)",
      abs(motion.camera_scale(view6) - 2.5) < 1e-9
      and motion.fly_camera(view6, 99.0, QPointF(0.0, 0.0), ms=600) is not None
      and abs(motion.camera_scale(view6) - 5.0) < 1e-9,
      str(motion.camera_scale(view6)))
check("§6 the zoom of the view stays honest (the status-bar % follows the instant move)",
      abs(view6.zoom - 5.0) < 1e-9, str(view6.zoom))
check("§6 a user gesture still wins (stop_camera_flight after an instant landing)",
      view6.stop_camera_flight() in (True, False) and not motion.is_flying(view6))

# ── the node scale-in: the same end state, no frames ────────────────────────
win6._dirty = False
win6._undo_baseline_dirty = False
data_off = ServerData(id="motion-off", alias="quiet", host="10.0.0.31", user="u",
                      x=-400.0, y=-300.0)
win6._push_command(CmdAddRemoveNode(win6, win6.scene, data_off, "add"))
node_off = win6.scene.get_node("motion-off")
check("§6 a new card is SETTLED at once with the flag off (no gesture to wait for)",
      node_off is not None and not motion.is_scaling_in(node_off)
      and abs(node_off.scale() - 1.0) < 1e-9 and node_off.opacity() == 1.0,
      f"scale={getattr(node_off, 'scale', lambda: '?')()} "
      f"opacity={getattr(node_off, 'opacity', lambda: '?')()}")
check("§6 scale_in() returns no animation and leaves the item at unit scale",
      motion.scale_in(node_off) is None and node_off.scale() == 1.0
      and node_off.opacity() == 1.0 and node_off.transformOriginPoint() == QPointF(0.0, 0.0))
check("§6 stop_scale_in() is a safe no-op (there is nothing running)",
      motion.stop_scale_in(node_off) is False)

# ── turning it back ON restores the full gesture ────────────────────────────
motion.set_motion_enabled(True)
data_on = ServerData(id="motion-on", alias="loud", host="10.0.0.32", user="u",
                     x=400.0, y=-300.0)
win6._push_command(CmdAddRemoveNode(win6, win6.scene, data_on, "add"))
node_on = win6.scene.get_node("motion-on")
check("§6 with the flag back ON the card animates again (the switch is reversible)",
      node_on is not None and motion.is_scaling_in(node_on)
      and node_on.scale() < 1.0)
check("§6 …and it completes to the same unit scale as the instant one",
      wait_for(lambda: not motion.is_scaling_in(node_on), timeout_ms=2500)
      and node_on.scale() == 1.0 and node_on.opacity() == 1.0,
      f"scale={node_on.scale()}")
check("§6 the instant card and the animated one end on the same rect",
      abs(node_off.card_rect_scene().width() - node_on.card_rect_scene().width()) < 1e-6,
      f"{node_off.card_rect_scene()} vs {node_on.card_rect_scene()}")

# ── the action path: "Fit map" also applies its FINAL state instantly ──────
motion.set_motion_enabled(False)
win6.scene.add_server(ServerData(id="fit-off", alias="fit", host="10.0.0.33", user="u",
                                 x=900.0, y=900.0))
_before_fit = motion.camera_scale(view6)
check("§6 the Fit map ACTION still returns True with the flag off (nothing is skipped)",
      view6.fly_to_content() is True and not motion.is_flying(view6)
      and abs(motion.camera_scale(view6) - _before_fit) > 1e-9,
      f"{_before_fit} -> {motion.camera_scale(view6)}")
check("§6 …and it lands exactly on the INSTANT fit target (the two agree)",
      abs(motion.camera_scale(view6) - view6.fit_view_target()[0]) < 1e-6,
      f"{motion.camera_scale(view6)} vs {view6.fit_view_target()[0]}")
motion.set_motion_enabled(True)
check("§6 the module ends this file with the standard behaviour installed",
      motion.motion_enabled() is True)
close_window(win6)


# ════════════════════════════════════════════════════════════════════════════
print("== §7 i18n parity + the release state ==")
# ════════════════════════════════════════════════════════════════════════════

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)
check_i18n_format(langs)
check("§7 the v1.4.4 release added no key of its own (the pin has moved on with "
      "v1.4.5 … v1.5.7 — the pin in tests/_common.py is the shipped one)",
      EXPECTED_I18N_KEYS == 789
      and all(len(translation_keys(langs[c])) == EXPECTED_I18N_KEYS for c in i18n_lang_codes(ROOT)),
      str({c: len(translation_keys(langs[c])) for c in sorted(langs)}))
check("§7 v1.5rc1 named the switch in EVERY language (the one string this release adds)",
      all(str(langs[c].get("settings.appearance.motion", "")).strip()
          for c in sorted(langs)),
      str([c for c in sorted(langs)
           if not str(langs[c].get("settings.appearance.motion", "")).strip()]))
check("§7 ui/motion.py is the module this release documents",
      os.path.exists(os.path.join(ROOT, "ui", "motion.py")))
check_release_state(ROOT)
check("§7 the version pin of this test file is the release it describes",
      EXPECTED_APP_VERSION == "1.6.4", EXPECTED_APP_VERSION)

finish()
