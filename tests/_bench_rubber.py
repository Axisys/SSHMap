# -*- coding: utf-8 -*-
"""v1.2.10rc3 — the measurement of the rubber-band selection (the AUDIT auto #9). NOT part of the suite.

The pattern of the standalone measurement (like tests/_bench_history.py for v1.2.12): it is run
manually, prints the ms to stdout — the numbers go to CHANGELOG.md ("measured on …,
v1.2.10rc3"). run_all.py does NOT collect it (files with the _ prefix are skipped).

The scenario: a synthetic map of 500 ServerNode (the grid 25×20) + the connections and a note
(a realistic composition of the scene elements); the drag of the selection frame across the map —
N steps from the top-left corner to the bottom-right. Each step = one mouse movement
= one call of MapView._update_rubber_select (before the fix of v1.2.10rc3 — the full
O(n) sweep of scene.items(); after — the spatial index scene().items(rect)
+ the isinstance filter).

The before/after comparison: run the script on the codebase of v1.2.10rc2 (before the fix),
then after the fix of graphics/map_view.py — both pairs of numbers into the CHANGELOG.

Run:  python tests/_bench_rubber.py   (from the project root)
"""
import platform
import sys
import time

from _common import bootstrap

ROOT, WORK = bootstrap(faulthandler_timeout=300)

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])


def build_scene(n_cols=25, n_rows=20):
    """The synthetic map: the grid of the nodes + the connections and a note (the other elements of the scene)."""
    from models.server import ServerData
    from graphics.map_scene import MapScene

    scene = MapScene()
    dx, dy = 280.0, 240.0   # the grid step > MIN_NODE_WIDTH/HEIGHT — the nodes do not overlap
    ids = []
    for r in range(n_rows):
        for c in range(n_cols):
            data = ServerData(id=f"bench{r:02d}{c:02d}", alias=f"node-{r:02d}-{c:02d}",
                              host=f"10.0.{r}.{c}", user="root",
                              x=100.0 + c * dx, y=100.0 + r * dy)
            scene.add_server(data)
            ids.append(data.id)
    # The connections and the note — other scene elements (the old full walk saw them too;
    # items(rect) returns them as candidates — the isinstance filter must cut them off).
    for i in range(0, len(ids) - 1, 37):
        scene.add_connection(ids[i], ids[i + 1])
    scene.add_note("bench note", x=40.0, y=40.0)
    return scene


def drag_across(view, steps=25):
    """One full rubber-band drag across the map: start → the update steps → finish.

    Returns (ms of the updates, the width/height of the final band). Measures ONLY
    the _update_rubber_select loop — the start/finish (addItem/removeItem) do not count."""
    nodes = view.scene().nodes()
    xs = [n.pos().x() for n in nodes]
    ys = [n.pos().y() for n in nodes]
    origin = QPointF(min(xs) - 60.0, min(ys) - 60.0)
    end = QPointF(max(xs) + 240.0, max(ys) + 190.0)
    view._start_rubber_select(origin)
    t0 = time.perf_counter()
    for i in range(1, steps + 1):
        t = i / steps
        view._update_rubber_select(QPointF(origin.x() + (end.x() - origin.x()) * t,
                                           origin.y() + (end.y() - origin.y()) * t))
    dt_ms = (time.perf_counter() - t0) * 1000.0
    view._finish_rubber_select()
    return dt_ms, end.x() - origin.x(), end.y() - origin.y()


def main():
    from PySide6 import __version__ as pyside_ver
    from PySide6.QtCore import qVersion as qt_ver
    from graphics.map_view import MapView

    scene = build_scene()
    n_nodes = scene.node_count()
    n_items = len(scene.items())
    view = MapView(scene)
    view.resize(1200, 800)

    steps = 25
    print(f"_bench_rubber (v1.2.10rc3, AUDIT auto #9): {n_nodes} nodes (25x20 grid), "
          f"scene items={n_items}")
    print(f"  env: python {platform.python_version()}, Qt {qt_ver()}, "
          f"PySide6 {pyside_ver}, offscreen")

    # The warm-up: the first run builds the internal Qt indexes/caches — not counted.
    for _ in range(3):
        drag_across(view, steps)
    cycles = [drag_across(view, steps)[0] for _ in range(5)]
    w, h = drag_across(view, steps)[1], drag_across(view, steps)[2]

    print(f"  rubber-band drag across the map: {steps} steps (each = mouse move), "
          f"final rectangle {w:.0f}x{h:.0f}")
    for i, ms in enumerate(cycles, 1):
        print(f"  cycle {i}: {ms:8.2f} ms   ({ms * 1000.0 / steps:7.1f} µs/update)")
    best = min(cycles)
    print(f"  BEST of {len(cycles)} cycles: {best:.2f} ms "
          f"({best * 1000.0 / steps:.1f} µs/update, {n_nodes} nodes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
