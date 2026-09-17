"""Connections: Bézier arrows, types, edge-to-edge, drag mode (former smoke_test.py §6b "v0.7").

A part of the suite split out of smoke_test.py v0.6–v0.9.2 (see INDEX.md).
  * the geometry of the cubic Bezier (moveTo + curve), the edge-to-edge on the borders of the nodes;
  * the A→B and the B→A bend to the opposite sides; the unknown type → the default ssh;
  * set_type changes the color/the type; the field type is serialized in the JSON, version = 0.9;
  * the backward-compat: the project v0.6 without the field type loads as ssh;
  * ConnectionDialog: the 6 types + the prefill of the source/target (the drag mode);
  * the drag mode Shift+LMB: the full path MapView→MainWindow through the QTest input.

Run: python tests/test_connections.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys

from _common import bootstrap, check, finish, viewport_point as _vp

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

import ui.main_window as MW
from models.server import ServerData

# ── v0.7: Bezier arrows, typed connections, edge-to-edge, drag mode ──
print("== v0.7 ==")
from graphics.map_scene import MapScene as _MapScene
from graphics.connection_arrow import (
    ConnectionArrow as _CA, CONNECTION_TYPES, DEFAULT_CONNECTION_TYPE, type_color,
)

# Geometry: two nodes facing each other horizontally (A on the left, B 310 px to the right)
vsc = _MapScene()
ndA = ServerData(id="va01", alias="A", host="10.9.9.1", user="u")
ndB = ServerData(id="vb02", alias="B", host="10.9.9.2", user="u")
node_a = vsc.add_server(ndA)          # the rect (0, 0, 180, 130), the center (90, 65)
node_b = vsc.add_server(ndB)
node_b.setPos(400, 0)                 # the rect (400, 0, 180, 130), the center (490, 65)

arrow_ab = vsc.add_connection("va01", "vb02", "lan-1", "vpn")
check("typed connection: type stored on arrow",
      arrow_ab is not None and arrow_ab.connection_type == "vpn")
check("type colors are distinct and vpn=#60a5fa",
      len({c.name().lower() for c in map(type_color, CONNECTION_TYPES)}) == 6
      and type_color("vpn").name().lower() == "#60a5fa")

# Geometry: (path, p0, p3, c1, c2); the path structure — via elementAt (Qt6 PySide6)
from PySide6.QtCore import QPointF as _QPointF
geom = arrow_ab._compute_geometry()
check("arrow geometry computed (nodes apart)", geom is not None)
if geom is not None:
    _gpath, p0, p3, _c1, _c2 = geom
else:  # a fallback, so the checks below do not fail with AttributeError
    _gpath = arrow_ab.path(); p0 = _QPointF(0, 0); p3 = _QPointF(0, 0)
# A cubic Bezier in Qt6: [MoveTo(p0), CurveTo(p3), data(c1), data(c2)] → elementCount == 4
check("arrow path is a single cubic Bezier (moveTo + curve)",
      _gpath.elementCount() == 4 and _gpath.elementAt(0).isMoveTo()
      and _gpath.elementAt(1).isCurveTo(), str(_gpath.elementCount()))
rect_a, rect_b = node_a.sceneBoundingRect(), node_b.sceneBoundingRect()
check("edge-to-edge: starts on source boundary (right edge of A)",
      abs(p0.x() - rect_a.right()) < 1.5 and rect_a.top() - 1 <= p0.y() <= rect_a.bottom() + 1,
      f"p0=({p0.x():.1f},{p0.y():.1f}) right={rect_a.right()}")
check("edge-to-edge: ends on target boundary (left edge of B)",
      abs(p3.x() - rect_b.left()) < 1.5 and rect_b.top() - 1 <= p3.y() <= rect_b.bottom() + 1,
      f"p3=({p3.x():.1f},{p3.y():.1f}) left={rect_b.left()}")
check("arrow is a curve (bbox taller than the chord)",
      arrow_ab.path().boundingRect().height() > 2, str(arrow_ab.path().boundingRect()))

# A->B and B->A bend to the opposite sides — they do not overlap
arrow_ba = vsc.add_connection("vb02", "va01", "", "carrier-pigeon")  # an unknown type → the default
check("unknown connection type falls back to default (ssh)",
      arrow_ba is not None and arrow_ba.connection_type == DEFAULT_CONNECTION_TYPE)
check("A->B and B->A bow on opposite sides of the chord",
      arrow_ab.path().boundingRect().center().y() > 65.0
      and arrow_ba.path().boundingRect().center().y() < 65.0,
      f"{arrow_ab.path().boundingRect().center().y():.1f} / {arrow_ba.path().boundingRect().center().y():.1f}")

# set_type changes the color and the type (for the future context menu, v0.7.3)
old_color = arrow_ba._base_color.name()
arrow_ba.set_type("database")
check("set_type changes color",
      arrow_ba.connection_type == "database" and arrow_ba._base_color.name() != old_color
      and arrow_ba._base_color.name().lower() == "#a78bfa")
arrow_ba.set_type("not-a-type")  # an unknown one — ignored without errors

# Serialization: the version is synchronized with the app release (review fix v0.8.0 #2)
# + the type field in connections. The field is not validated on load — old
# the files (0.6/0.7/0.7.2) are read unchanged, see the backward-compat below.
win = MW.MainWindow()
win.scene.add_server(ServerData(id="snode001", alias="web-1", host="10.0.0.5", user="root"))
win.scene.add_server(ServerData(id="snode002", alias="db-1", host="10.0.0.6", user="root"))
typed = win.scene.add_connection("snode002", "snode001", "vpn-link", "database")
check("scene accepts reverse-direction typed connection",
      typed is not None and typed.connection_type == "database")
p7 = os.path.join(WORK, "save_v07.json")
ok7 = win._do_save(p7)
with open(p7, encoding="utf-8") as f:
    j7 = json.load(f)
# v0.8.1: the format version — new (the "groups" key); the old versions read unchanged below
check("saved version synced to format 0.9", ok7 and j7.get("version") == "0.9", str(j7.get("version")))
conn_db = [c for c in j7["connections"] if c.get("label") == "vpn-link"]
check("connection type serialized in JSON",
      conn_db and conn_db[0].get("type") == "database", str(conn_db))

# Backward-compat: a v0.6 project without the type field loads as SSH
raw_old = {
    "version": "0.6",
    "servers": [
        {"id": "oldaaa01", "alias": "old-1", "host": "10.1.1.1", "user": "u"},
        {"id": "oldbbb02", "alias": "old-2", "host": "10.1.1.2", "user": "u"},
    ],
    "connections": [{"source_id": "oldaaa01", "target_id": "oldbbb02", "label": "legacy"}],
}
win3 = MW.MainWindow()
win3._import_project_raw(raw_old)
la = win3.scene._arrows[0] if win3.scene._arrows else None
check("v0.6 project (no type field): connection loads with default ssh",
      la is not None and la.connection_type == DEFAULT_CONNECTION_TYPE, str(getattr(la, "connection_type", None)))

# ConnectionDialog: 6 types + a source/target prefill for the drag mode
from dialogs.connection_dialog import ConnectionDialog as _CDlg
cdlg = _CDlg(list(win3.scene._nodes.values()), None,
             default_source_id="oldaaa01", default_target_id="oldbbb02")
check("ConnectionDialog exposes type combo with 6 types", cdlg.type_combo.count() == 6)
check("ConnectionDialog prefills source/target (drag mode)",
      cdlg.source.currentData() == "oldaaa01" and cdlg.target.currentData() == "oldbbb02")
res = cdlg.get_connection()
# v1.2.6: the tuple is extended to 5 elements (the 5th — bidirectional, the default False)
check("get_connection returns 5-tuple with valid type + bidir flag",
      len(res) == 5 and res[3] in CONNECTION_TYPES and res[4] is False, str(res))

# The drag mode: Shift+LMB on a node → movement → release over another node.
# The modal dialog is replaced with a fake (offscreen), the whole MapView→MainWindow path is checked.
# The B→A direction: the A→B connection ("legacy") already exists, a duplicate in the same direction will be rejected.
# IMPORTANT (Qt 6.11): manual QMouseEvents do NOT trigger the QGraphicsView internal processing
# (verified empirically on PySide6 and PyQt6) — we send input via QTest.mousePress/move/release,
# which generates events the standard Qt way (the viewport→view routing).
from PySide6.QtCore import Qt as _Qt, QPoint as _QPt
from PySide6.QtTest import QTest as _QTest

na3 = win3.scene._nodes["oldaaa01"]
nb3 = win3.scene._nodes["oldbbb02"]
na3.setPos(-300, -300)   # we disconnect the nodes (from the v0.6 file both were at (0,0))
nb3.setPos(500, 100)

drag_calls = []

class _FakeConnDialog:
    def __init__(self, nodes, parent=None, default_source_id=None, default_target_id=None):
        drag_calls.append((default_source_id, default_target_id))
    def exec(self): return 1  # QDialog.Accepted
    def get_connection(self):
        src, tgt = drag_calls[-1]
        # v1.2.6: a 5-tuple (src, tgt, label, ctype, bidirectional) — as in the real dialog;
        # the old 4-tuple crashes _add_connection with a ValueError → the QMessageBox.critical modal
        # hangs offscreen on the faulthandler timeout (180 s).
        return (src, tgt, "drag-label", "http", False)

_orig_cd = MW.ConnectionDialog
MW.ConnectionDialog = _FakeConnDialog
try:
    view3 = win3.view
    vp3 = view3.viewport()
    _QTest.mousePress(vp3, _Qt.LeftButton, stateKey=_Qt.ShiftModifier,
                      pos=_vp(view3, nb3.sceneBoundingRect().center()))
    app.processEvents()
    check("drag mode starts on Shift+press over node", view3._connect_source is nb3)
    mid_scene = (na3.sceneBoundingRect().center() + nb3.sceneBoundingRect().center()) / 2
    _QTest.mouseMove(vp3, pos=_vp(view3, mid_scene))
    app.processEvents()
    _rb = view3._rubber_band
    check("rubber band follows the cursor",
          _rb is not None and _rb.path().elementCount() >= 2)
    _QTest.mouseRelease(vp3, _Qt.LeftButton, pos=_vp(view3, na3.sceneBoundingRect().center()))
    app.processEvents()
finally:
    MW.ConnectionDialog = _orig_cd

check("drag state cleaned up after release",
      win3.view._connect_source is None and win3.view._rubber_band is None)
check("release over target opens pre-filled connection dialog (B->A)",
      drag_calls == [("oldbbb02", "oldaaa01")], str(drag_calls))
new_arrow = win3.scene._arrows[-1] if win3.scene._arrows else None
check("drag created typed connection (http) with label",
      new_arrow is not None and new_arrow.connection_type == "http"
      and new_arrow.label_text == "drag-label"
      and new_arrow.source.data.id == "oldbbb02" and new_arrow.target.data.id == "oldaaa01")

finish()
