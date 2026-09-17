# -*- coding: utf-8 -*-
"""Regression v0.9.3: node duplication + multi-select + group drag.

Run: python tests/test_duplicate_multiselect.py or python tests/run_all.py
Without pytest: the common harness tests/_common.py.
"""
import os
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])


class _FakeWin:
    """The minimal double for MainWindow (as in regression_v081)."""

    def __init__(self):
        self.refreshed = 0

    def _post_undo_refresh(self):
        self.refreshed += 1


def make_scene():
    from graphics.map_scene import MapScene
    return MapScene()


def main():
    global FAIL
    print("== v0.9.3: node duplication + multiselection ==")

    from models.server import ServerData
    from graphics.map_scene import MapScene
    from graphics.server_node import ServerNode
    from modules.undo_commands import (
        CmdMoveNodes, CmdConnectSelected, CmdAddRemoveNode,
    )

    scene = make_scene()

    # ── #1 Duplicating the node data (a copy of the fields + an offset) ──
    data = ServerData(id="aaa11111", alias="web", host="10.0.0.1", user="root",
                      x=100.0, y=50.0, ssh_port=2222, os_name="Ubuntu", cpu_model="Xeon")
    n1 = scene.add_server(data)
    check("node added", scene.node_count() == 1)

    import copy as _copy
    dup = _copy.deepcopy(n1.data)
    dup.x += 40.0
    dup.y += 40.0
    dup.id = "bbb22222"
    check("dup keeps fields",
          dup.alias == "web" and dup.host == "10.0.0.1" and dup.ssh_port == 2222
          and dup.os_name == "Ubuntu" and dup.cpu_model == "Xeon")
    check("dup offset", (dup.x, dup.y) == (140.0, 90.0))
    check("dup new id", dup.id != n1.data.id)
    n2 = scene.add_server(dup)
    check("both nodes on scene", scene.node_count() == 2)

    # ── #2 CmdMoveNodes: a group move in a single command ──
    win = _FakeWin()
    old1, old2 = QPointF(140.0, 90.0), QPointF(100.0, 50.0)
    new1, new2 = QPointF(300.0, 300.0), QPointF(260.0, 260.0)
    cmd = CmdMoveNodes(win, [(n1, old1, new1), (n2, old2, new2)])
    cmd.redo()
    check("group move redo applied",
          n1.pos() == new1 and n2.pos() == new2)
    cmd.undo()
    check("group move undo restored",
          n1.pos() == old1 and n2.pos() == old2)

    # ── #3 CmdConnectSelected: connections between the selected ones in a single operation ──
    pairs = [("aaa11111", "bbb22222")]
    cc = CmdConnectSelected(win, scene, pairs)
    check("no connection before", not scene.has_connection("aaa11111", "bbb22222"))
    cc.redo()
    check("connection created by redo",
          scene.has_connection("aaa11111", "bbb22222"))
    cc.undo()
    check("connection removed by undo",
          not scene.has_connection("aaa11111", "bbb22222"))
    cc.redo()
    check("connection re-created",
          scene.has_connection("aaa11111", "bbb22222"))

    # ── #4 The multi-selection: several ServerNodes can be selected ──
    n1.setSelected(True)
    n2.setSelected(True)
    sel = [i for i in scene.selectedItems() if isinstance(i, ServerNode)]
    check("multi-selection works", len(sel) == 2)

    # ── #5 MapView: the signals and the selection-frame state ──
    view_cls_loaded = False
    try:
        from graphics.map_view import MapView
        v = MapView(scene)
        check("MapView has nodes_drag_committed signal",
              hasattr(v, "nodes_drag_committed"))
        check("rubber-select state initialized",
              v._rubber_select_item is None and v._group_drag_olds == [])
        # the frame: start → update → finish
        v._start_rubber_select(QPointF(0, 0))
        check("rubber item added to scene", v._rubber_select_item is not None
              and v._rubber_select_item.scene() is scene)
        v._update_rubber_select(QPointF(500, 500))
        check("live selection inside rubber rect", len(scene.selectedItems()) >= 2)
        v._finish_rubber_select()
        check("rubber removed on finish", v._rubber_select_item is None)
        view_cls_loaded = True
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: MapView init: {e}")
        FAIL += 1
    check("MapView loaded", view_cls_loaded)

    # ── #6 Deleting the selected via the guarded path (no dialog — the scene directly) ──
    for nid in ("aaa11111", "bbb22222"):
        scene.remove_server(nid)
    check("scene empty after cleanup", scene.node_count() == 0)

    # ── #7 CmdAddRemoveNode: undo/redo of the duplicate (the copy's data) ──
    d = ServerData(id="ccc33333", alias="db", host="10.0.0.9", user="root")
    add_cmd = CmdAddRemoveNode(win, scene, d, "add")
    add_cmd.redo()
    check("duplicate added via command", scene.has_node("ccc33333"))
    add_cmd.undo()
    check("duplicate removed via undo", not scene.has_node("ccc33333"))

    finish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
