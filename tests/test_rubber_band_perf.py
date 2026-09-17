# -*- coding: utf-8 -*-
"""v1.2.10rc3 — rubber-band selection performance on large maps (AUDIT auto #9).

The thematic test of the release (ROADMAP v1.2.10rc3; offscreen, without the network):
  * the synthetic scene of 520 ServerNode (the grid 26×20) + the connections and the notes — the "large maps";
  * the frame selects exactly the intersected nodes — the result is identical to the algorithm BEFORE v1.2.10rc3
    (the reference in the test: the full sweep of scene.items() + intersects + base_ids, as in rc2);
  * the live selection on the intermediate drag steps also matches the reference;
  * the additive mode (Shift): the base selection ∪ the intersection, the base outside the frame is preserved;
  * the non-additive mode: the previously selected nodes outside the frame are cleared (the semantics of the replacement);
  * a click without the mouse movement does not change the selection (press→release without _update);
  * the notes/arrows are NOT selected by the frame (the filter is only the ServerNode — as before the fix);
  * the full mouse path via QTest (the Ctrl+LMB on the empty space → the drag → the release;
    the Ctrl+Shift — the additive) — the wiring of the modifiers end-to-end.

Run: python tests/test_rubber_band_perf.py or python tests/run_all.py
"""
import sys

from _common import (bootstrap, check, finish, viewport_point, load_i18n_langs,
                     check_i18n_parity, check_release_state)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

N_COLS, N_ROWS = 26, 20   # 520 nodes > 500 (Acceptance: "a synthetic scene of 500+ nodes")
DX, DY = 280.0, 240.0     # the grid step > MIN_NODE_WIDTH/HEIGHT — the nodes do not overlap


def build_scene():
    """The synthetic map: the grid of the nodes + the connections and the notes (the other elements of the scene)."""
    from models.server import ServerData
    from graphics.map_scene import MapScene
    scene = MapScene()
    ids = []
    for r in range(N_ROWS):
        for c in range(N_COLS):
            data = ServerData(id=f"rb{r:02d}{c:02d}", alias=f"node-{r:02d}-{c:02d}",
                              host=f"10.0.{r}.{c}", user="root",
                              x=100.0 + c * DX, y=100.0 + r * DY)
            scene.add_server(data)
            ids.append(data.id)
    for i in range(0, len(ids) - 1, 41):
        scene.add_connection(ids[i], ids[i + 1])
    notes = [scene.add_note("note A", x=60.0, y=60.0),
             scene.add_note("note B", x=3000.0, y=2400.0)]
    return scene, notes


def reference_selection(scene, rect, base_ids):
    """The algorithm BEFORE v1.2.10rc3 (the full sweep of scene.items()) — the reference "the result as before the fix"."""
    from graphics.server_node import ServerNode
    out = set()
    for item in scene.items():
        if isinstance(item, ServerNode):
            hit = rect.intersects(item.sceneBoundingRect())
            if hit or (id(item) in base_ids):
                out.add(id(item))
    return out


def selected_node_ids(scene):
    from graphics.server_node import ServerNode
    return {id(i) for i in scene.selectedItems() if isinstance(i, ServerNode)}


def drag_steps(origin, end, n=5):
    """The points of the drag: from the origin to the end (each = one movement of the mouse)."""
    return [QPointF(origin.x() + (end.x() - origin.x()) * i / n,
                    origin.y() + (end.y() - origin.y()) * i / n)
            for i in range(1, n + 1)]


def main():
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from graphics.map_view import MapView
    from graphics.server_node import ServerNode

    scene, notes = build_scene()
    check("the scene: 520 nodes (500+)", scene.node_count() == N_COLS * N_ROWS, str(scene.node_count()))
    check("the scene: the connections and the notes are present (the other elements)",
          len(scene.arrows()) > 0 and len(notes) == 2,
          f"arrows={len(scene.arrows())}")

    view = MapView(scene)
    view.resize(7800, 5400)   # the whole content within the viewport — the drag points are available to the mouse

    origin = QPointF(40.0, 40.0)
    end = QPointF(3500.0, 2600.0)          # the frame over a part of the map (~a quarter of the nodes)
    final_rect = QRectF(origin, end).normalized()

    # ── §1 the non-additive drag: exactly the intersected nodes, live + the final as before the fix ──
    print("== rubber band: 520 nodes, the non-additive drag ==")
    steps = drag_steps(origin, end, n=5)
    view._start_rubber_select(origin)
    check("the frame is added to the scene", view._rubber_select_item is not None
          and view._rubber_select_item.scene() is scene)
    live_ok = True
    for i, pos in enumerate(steps):
        view._update_rubber_select(pos)
        r_i = QRectF(origin, pos).normalized()
        if selected_node_ids(scene) != reference_selection(scene, r_i, set()):
            live_ok = False
    check("the live selection at each step = the reference (the algorithm before the fix)", live_ok)
    got = selected_node_ids(scene)
    want = reference_selection(scene, final_rect, set())
    check("the final: the frame selects exactly the intersected nodes", got == want,
          f"got={len(got)} want={len(want)}")
    check(">0 nodes are selected (the frame across the map is not empty)", len(want) > 0, str(len(want)))
    check("the notes are NOT selected by the frame", all(not n.isSelected() for n in notes))
    check("the arrows are NOT selected by the frame",
          all(not a.isSelected() for a in scene.arrows()))
    view._finish_rubber_select()
    check("the finish: the frame is removed, the selection is kept",
          view._rubber_select_item is None and selected_node_ids(scene) == want)

    # ── §2 the additive mode (Shift): the base ∪ the intersection, the base outside the frame is intact ──
    print("== rubber band: the additive mode (Shift) ==")
    for i in scene.selectedItems():
        i.setSelected(False)
    nodes_all = scene.nodes()
    outside = [n for n in nodes_all
               if not final_rect.intersects(n.sceneBoundingRect())][:3]
    inside = [n for n in nodes_all if final_rect.intersects(n.sceneBoundingRect())][:1]
    base_nodes = outside + inside
    for n in base_nodes:
        n.setSelected(True)
    base_ids = {id(n) for n in base_nodes}
    check("the base: 3 nodes outside the frame + 1 inside are selected",
          selected_node_ids(scene) == base_ids and len(base_nodes) == 4,
          f"base={len(base_nodes)}")
    view._start_rubber_select(origin, additive=True)
    for pos in steps:
        view._update_rubber_select(pos)
    want_add = reference_selection(scene, final_rect, base_ids)
    got_add = selected_node_ids(scene)
    check("additive: the result = the base ∪ the intersected (as before the fix)", got_add == want_add,
          f"got={len(got_add)} want={len(want_add)}")
    check("additive: the 3 base nodes outside the frame are kept",
          all(id(n) in got_add for n in outside))
    view._finish_rubber_select()

    # ── §3 the non-additive mode: the replacement — the base outside the frame is cleared ──
    print("== rubber band: the non-additive mode replaces the selection ==")
    for i in scene.selectedItems():
        i.setSelected(False)
    for n in outside[:2]:
        n.setSelected(True)
    view._start_rubber_select(origin)   # without additive
    for pos in steps:
        view._update_rubber_select(pos)
    got_repl = selected_node_ids(scene)
    check("the replacement: ONLY the intersected are selected (the base outside the frame is cleared)",
          got_repl == reference_selection(scene, final_rect, set()),
          f"got={len(got_repl)}")
    view._finish_rubber_select()

    # ── §4 a click without movement: the selection is unchanged ──
    print("== rubber band: a click without the movement ==")
    for i in scene.selectedItems():
        i.setSelected(False)
    keep = nodes_all[:2]
    for n in keep:
        n.setSelected(True)
    view._start_rubber_select(QPointF(7400.0, 4900.0))   # behind the content — empty
    view._finish_rubber_select()   # press→release without a single _update
    check("a click without the movement: the selection is unchanged",
          selected_node_ids(scene) == {id(n) for n in keep})

    # ── §5 the full mouse path via QTest (Ctrl+LMB → the drag → the release) ──
    print("== rubber band: the full mouse path (QTest, Ctrl / Ctrl+Shift) ==")
    for i in scene.selectedItems():
        i.setSelected(False)
    # empty: the gap between the grid columns 5/6 and the rows 0/1 (the nodes — from x=100+c*280, y=100+r*240)
    empty = QPointF(2550.0, 300.0)
    end_m = QPointF(7400.0, 2900.0)   # the drag end — the right part of the map (the point may be over a node)
    check("the press point is empty (a safety check)", view._item_at_scene(empty) is None,
          repr(view._item_at_scene(empty)))
    vp = view.viewport()
    QTest.mousePress(vp, Qt.LeftButton, stateKey=Qt.ControlModifier,
                     pos=viewport_point(view, empty))
    app.processEvents()
    check("Ctrl+LMB on the empty space: the frame started", view._rubber_select_item is not None)
    mid = QPointF((empty.x() + end_m.x()) / 2, (empty.y() + end_m.y()) / 2)
    QTest.mouseMove(vp, pos=viewport_point(view, mid))
    app.processEvents()
    r_mid = QRectF(empty, mid).normalized()
    check("the drag: the live selection = the reference",
          selected_node_ids(scene) == reference_selection(scene, r_mid, set()))
    QTest.mouseMove(vp, pos=viewport_point(view, end_m))
    app.processEvents()
    QTest.mouseRelease(vp, Qt.LeftButton, pos=viewport_point(view, end_m))
    app.processEvents()
    check("the release: the frame is removed", view._rubber_select_item is None)
    check("the release: the final = the reference (the Ctrl-drag through the mouse)",
          selected_node_ids(scene) == reference_selection(scene, QRectF(empty, end_m).normalized(), set()))

    # Ctrl+Shift — additive via the mouse: the base outside the frame is preserved
    for i in scene.selectedItems():
        i.setSelected(False)
    base_m = [n for n in nodes_all if not QRectF(empty, end_m).normalized()
              .intersects(n.sceneBoundingRect())][:2]
    for n in base_m:
        n.setSelected(True)
    QTest.mousePress(vp, Qt.LeftButton,
                     stateKey=Qt.ControlModifier | Qt.ShiftModifier,
                     pos=viewport_point(view, empty))
    app.processEvents()
    check("Ctrl+Shift+LMB: the frame started in the additive mode",
          view._rubber_select_item is not None and
          len(view._rubber_saved_selection) == 2,
          f"saved={len(view._rubber_saved_selection)}")
    QTest.mouseMove(vp, pos=viewport_point(view, end_m))
    app.processEvents()
    QTest.mouseRelease(vp, Qt.LeftButton, pos=viewport_point(view, end_m))
    app.processEvents()
    want_m = reference_selection(scene, QRectF(empty, end_m).normalized(),
                                 {id(n) for n in base_m})
    check("the Ctrl+Shift-drag: the base ∪ the intersected (the additive through the mouse)",
          selected_node_ids(scene) == want_m)

    # ── §6 the release state + the i18n parity ──
    print("== release state ==")
    langs = load_i18n_langs(ROOT)
    check_i18n_parity(langs)
    check_release_state(ROOT)

    finish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
