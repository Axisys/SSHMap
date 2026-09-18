# -*- coding: utf-8 -*-
"""Bidirectional arrows (v1.2.6, ROADMAP task 1).

It covers:
  * the geometry: the arrowheads on BOTH the ends of the curve — the tips exactly on the borders of the nodes, each arrowhead looks AT ITS node (←——→);
    the standard mode — the path of the original arrowhead is empty (the item is invisible);
  * set_bidirectional: the toggle + the idempotence without the recreation of the item;
  * ConnectionDialog / EditConnectionDialog: the checkbox, the prefill from the arrow,
    the tuples of get_connection() 5/3 elements (v1.2.6);
  * MapScene.add_connection(bidirectional=...);
  * the JSON: the "bidirectional" field is written only when true (the pattern of server_id),
    the round-trip save/load, the backward-compat (no field → one-way);
  * undo/redo: CmdAddRemoveConnection (the flag is preserved through undo/redo),
    CmdEditConnection (the toggle of the flag by one command), the removal of a node —
    the stash of the 5-tuples E2E (_remove_node_guarded with the patched QMessageBox.question);
  * the drawio export: the startArrow=classic of the two-way edge, without it of the regular one;
  * the i18n parity + the release state.

Run: python tests/test_bidirectional_arrows.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys
import xml.etree.ElementTree as ET

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_release_state)

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication(sys.argv)

import ui.main_window as MW
from _fakes import QuestionStub
from models.server import ServerData
from graphics.map_scene import MapScene
from dialogs.connection_dialog import ConnectionDialog, EditConnectionDialog
from modules.undo_commands import CmdAddRemoveConnection, CmdEditConnection
from storage.export_drawio import export_scene_to_drawio


def _find_arrow(scene, src_id, tgt_id):
    for a in scene.arrows():
        if a.source.data.id == src_id and a.target.data.id == tgt_id:
            return a
    return None


print("== v1.2.6: bidirectional arrows ==")

# ── §1 The geometry: two arrowheads, the tips on the node borders ────────────────
sc = MapScene()
na = sc.add_server(ServerData(id="ba01", alias="A", host="10.9.9.1", user="u"))
nb = sc.add_server(ServerData(id="bb02", alias="B", host="10.9.9.2", user="u"))
nb.setPos(400, 0)

std = sc.add_connection("ba01", "bb02", "one-way", "ssh")
check("standard arrow: bidirectional defaults to False",
      std is not None and std.bidirectional is False)
check("standard arrow: source head path is empty (item invisible)",
      std._arrow_head_src.path().elementCount() == 0,
      str(std._arrow_head_src.path().elementCount()))
# A closed triangle = moveTo + 2×lineTo + closeSubpath → 4 path elements.
check("standard arrow: target head present (moveTo + 2 lineTo + close)",
      std._arrow_head.path().elementCount() == 4,
      str(std._arrow_head.path().elementCount()))

nc = sc.add_server(ServerData(id="bc03", alias="C", host="10.9.9.3", user="u"))
nd = sc.add_server(ServerData(id="bd04", alias="D", host="10.9.9.4", user="u"))
nd.setPos(400, 200)  # C (0, 200), D (400, 200) — a horizontal pair

bi = sc.add_connection("bc03", "bd04", "two-way", "vpn", bidirectional=True)
check("scene.add_connection(bidirectional=True) sets the flag",
      bi is not None and bi.bidirectional is True)

# v1.4.2 (ROADMAP task 4): the arrow heads sit on the CARD rect (`card_rect_scene()`),
# not on the shadow halo-inflated boundingRect.
rect_c, rect_d = nc.card_rect_scene(), nd.card_rect_scene()
src_head = bi._arrow_head_src.path()
tgt_head = bi._arrow_head.path()
check("bidirectional arrow: both heads present (4 elements each)",
      src_head.elementCount() == 4 and tgt_head.elementCount() == 4,
      f"{src_head.elementCount()}/{tgt_head.elementCount()}")
# elementAt(0) — a MoveToElement; in PySide6 Element.x/.y are properties (not methods).
tip_src = src_head.elementAt(0) if src_head.elementCount() else None
tip_tgt = tgt_head.elementAt(0) if tgt_head.elementCount() else None
check("source head tip lies on source boundary (right edge of C)",
      tip_src is not None and abs(tip_src.x - rect_c.right()) < 1.5
      and rect_c.top() - 1 <= tip_src.y <= rect_c.bottom() + 1,
      f"tip=({tip_src.x:.1f},{tip_src.y:.1f}) right={rect_c.right()}" if tip_src else "no tip")
check("target head tip lies on target boundary (left edge of D)",
      tip_tgt is not None and abs(tip_tgt.x - rect_d.left()) < 1.5
      and rect_d.top() - 1 <= tip_tgt.y <= rect_d.bottom() + 1,
      f"tip=({tip_tgt.x:.1f},{tip_tgt.y:.1f}) left={rect_d.left()}" if tip_tgt else "no tip")

# v1.2.6-fix: THE ORIENTATION — each arrowhead looks AT ITS node (←——→), not both
# in the direction of movement (→——→). The centroid of the filled triangle lies on the "wing" side
# side from the tip: for the original arrowhead it must lie between p0 and p3 (on the
# curve, outside the node), in the target one — between p3 and p0. Before, only
# the elementCount/the tip position, so the flipped source arrowhead (the body under
# node) passed the tests, but visually it was indistinguishable from a one-way arrow.
p0_pts, _c1, _c2, p3_pts = bi._curve_pts


def _head_centroid(path):
    pts = [path.elementAt(i) for i in range(3)]  # MoveTo (the tip) + 2×lineTo (the wings)
    return (sum(p.x for p in pts) / 3.0, sum(p.y for p in pts) / 3.0)


csx, csy = _head_centroid(src_head)
ctx_, cty = _head_centroid(tgt_head)
check("source head points AT the source node (wings on curve side of p0)",
      (csx - p0_pts.x()) * (p3_pts.x() - p0_pts.x()) + (csy - p0_pts.y()) * (p3_pts.y() - p0_pts.y()) > 0,
      f"centroid=({csx:.1f},{csy:.1f}) p0=({p0_pts.x():.1f},{p0_pts.y():.1f}) "
      f"p3=({p3_pts.x():.1f},{p3_pts.y():.1f})")
check("target head points AT the target node (wings on curve side of p3)",
      (ctx_ - p3_pts.x()) * (p0_pts.x() - p3_pts.x()) + (cty - p3_pts.y()) * (p0_pts.y() - p3_pts.y()) > 0,
      f"centroid=({ctx_:.1f},{cty:.1f}) p3=({p3_pts.x():.1f},{p3_pts.y():.1f})")

# ── §2 set_bidirectional: the toggle + the idempotence ────────────────────
std.set_bidirectional(True)
check("set_bidirectional(True): source head appears",
      std.bidirectional is True and std._arrow_head_src.path().elementCount() == 4)
std.set_bidirectional(True)  # a repeated call with the same value — a no-op without errors
check("set_bidirectional idempotent (second call is a no-op)",
      std.bidirectional is True and std._arrow_head_src.path().elementCount() == 4)
std.set_bidirectional(False)
check("set_bidirectional(False): source head removed again",
      std.bidirectional is False and std._arrow_head_src.path().elementCount() == 0)

# ── §3 The dialogs: the checkbox, the prefill, the extended tuples ────────────────────────
cdlg = ConnectionDialog(list(sc.nodes()), None,
                        default_source_id="bc03", default_target_id="bd04")
check("ConnectionDialog: bidirectional checkbox exists and is unchecked by default",
      cdlg.bidirectional_check is not None and cdlg.bidirectional_check.isChecked() is False)
res = cdlg.get_connection()
check("ConnectionDialog: get_connection returns 5-tuple with bidir=False",
      len(res) == 5 and res[3] in ("ssh", "vpn", "http", "database", "nfs", "kubernetes")
      and res[4] is False, str(res))
cdlg.bidirectional_check.setChecked(True)
check("ConnectionDialog: checked → get_connection()[4] is True",
      cdlg.get_connection()[4] is True)

ecd = EditConnectionDialog(bi, None)
check("EditConnectionDialog: prefills bidirectional state (True)",
      ecd.bidirectional_check.isChecked() is True)
res2 = ecd.get_connection()
check("EditConnectionDialog: get_connection returns 3-tuple (label, type, bidir)",
      res2 == ("two-way", "vpn", True), str(res2))

ecd2 = EditConnectionDialog(std, None)
check("EditConnectionDialog: standard arrow → checkbox unchecked",
      ecd2.bidirectional_check.isChecked() is False
      and ecd2.get_connection()[2] is False)

# ── §4 The JSON serialization: the optional field + the round-trip + the backward-compat ───
win = MW.MainWindow()
win.scene.add_server(ServerData(id="snode001", alias="web-1", host="10.0.0.5", user="root"))
win.scene.add_server(ServerData(id="snode002", alias="db-1", host="10.0.0.6", user="root"))
win.scene.add_connection("snode001", "snode002", "bi-link", "vpn", bidirectional=True)
win.scene.add_connection("snode002", "snode001", "one-way-back", "ssh")

p = os.path.join(WORK, "save_v126.json")
ok = win._do_save(p)
with open(p, encoding="utf-8") as f:
    j = json.load(f)
recs = {c.get("label"): c for c in j["connections"]}
check("JSON: bidirectional connection carries 'bidirectional': true",
      ok and recs.get("bi-link", {}).get("bidirectional") is True, str(recs))
check("JSON: one-way connection has NO field (server_id pattern)",
      "bidirectional" not in recs.get("one-way-back", {}), str(recs))

win2 = MW.MainWindow()
win2._import_project_raw(j)
a_bi = _find_arrow(win2.scene, "snode001", "snode002")
a_one = _find_arrow(win2.scene, "snode002", "snode001")
check("round-trip: bidirectional flag survives save/load",
      a_bi is not None and a_bi.bidirectional is True)
check("round-trip: one-way connection stays one-way",
      a_one is not None and a_one.bidirectional is False)

raw_old = {
    "version": "0.9",
    "servers": [
        {"id": "oldaaa01", "alias": "old-1", "host": "10.1.1.1", "user": "u"},
        {"id": "oldbbb02", "alias": "old-2", "host": "10.1.1.2", "user": "u"},
    ],
    "connections": [{"source_id": "oldaaa01", "target_id": "oldbbb02", "label": "legacy"}],
}
win3 = MW.MainWindow()
win3._import_project_raw(raw_old)
la = _find_arrow(win3.scene, "oldaaa01", "oldbbb02")
check("backward-compat: connection without 'bidirectional' loads as one-way",
      la is not None and la.bidirectional is False)

# ── §5 undo/redo: the flag survives all the commands ───────────────────────────────
win4 = MW.MainWindow()
win4.scene.add_server(ServerData(id="u1", alias="U1", host="10.2.2.1", user="root"))
win4.scene.add_server(ServerData(id="u2", alias="U2", host="10.2.2.2", user="root"))
win4._push_command(CmdAddRemoveConnection(
    win4, win4.scene, "u1", "u2", "undo-bi", "ssh", "add", bidirectional=True))
au = _find_arrow(win4.scene, "u1", "u2")
check("CmdAddRemoveConnection(bidir): redo created arrow with flag",
      au is not None and au.bidirectional is True)
win4.undo_stack.undo()
check("CmdAddRemoveConnection(bidir): undo removed the arrow",
      _find_arrow(win4.scene, "u1", "u2") is None)
win4.undo_stack.redo()
au = _find_arrow(win4.scene, "u1", "u2")
check("CmdAddRemoveConnection(bidir): redo restored it with flag",
      au is not None and au.bidirectional is True)

win4._push_command(CmdEditConnection(
    win4, au, au.label_text, au.connection_type, True, "undo-bi2", "vpn", False))
check("CmdEditConnection(bidir): redo applied label/type/bidir",
      au.label_text == "undo-bi2" and au.connection_type == "vpn"
      and au.bidirectional is False,
      f"{au.label_text}/{au.connection_type}/{au.bidirectional}")
win4.undo_stack.undo()
check("CmdEditConnection(bidir): undo restored the old state",
      au.label_text == "undo-bi" and au.connection_type == "ssh"
      and au.bidirectional is True,
      f"{au.label_text}/{au.connection_type}/{au.bidirectional}")
win4.undo_stack.redo()

# E2E: removing a node captures the 5-tuples; undo restores the connection as it was
win5 = MW.MainWindow()
m1 = win5.scene.add_server(ServerData(id="m1", alias="M1", host="10.3.3.1", user="root"))
m2 = win5.scene.add_server(ServerData(id="m2", alias="M2", host="10.3.3.2", user="root"))
win5.scene.add_connection("m1", "m2", "stash-bi", "nfs", bidirectional=True)

_question = QuestionStub(QMessageBox.Yes).install()
try:
    removed = win5._remove_node_guarded(m2)
finally:
    _question.restore()
check("_remove_node_guarded deleted the node and its arrow",
      removed is True and not win5.scene.has_node("m2")
      and _find_arrow(win5.scene, "m1", "m2") is None)
win5.undo_stack.undo()
restored = _find_arrow(win5.scene, "m1", "m2")
check("undo of node deletion restored the bidirectional arrow (5-tuple stash)",
      win5.scene.has_node("m2") and restored is not None and restored.bidirectional is True)

# ── §6 the drawio export: the startArrow of a two-way edge ─────────────────────
dsc = MapScene()
dsc.add_server(ServerData(id="da", alias="DA", host="10.4.4.1", user="u"))
dsc.add_server(ServerData(id="db", alias="DB", host="10.4.4.2", user="u"))
dsc.add_server(ServerData(id="dc", alias="DC", host="10.4.4.3", user="u"))
dsc.add_server(ServerData(id="dd", alias="DD", host="10.4.4.4", user="u"))
dsc.add_connection("da", "db", label="bi-edge", ctype="ssh", bidirectional=True)
dsc.add_connection("dc", "dd", label="one-edge", ctype="ssh")

dp = os.path.join(WORK, "bi_export.drawio")
export_scene_to_drawio(dsc, dp)
edge_styles = {c.get("value"): c.get("style", "")
               for c in ET.parse(dp).getroot().iter("mxCell") if c.get("edge") == "1"}
check("drawio: bidirectional edge carries startArrow=classic",
      "startArrow=classic" in edge_styles.get("bi-edge", ""), str(edge_styles))
check("drawio: one-way edge has no startArrow",
      "startArrow" not in edge_styles.get("one-edge", ""), str(edge_styles))

# ── §7 the i18n parity + the release state ───────────────────────────────────────
langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)
check_release_state(ROOT)

finish()
