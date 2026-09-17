"""Node and arrow context menus v0.7.3 (former smoke_test.py "v0.7.3 context menus").

A part of the suite split out of smoke_test.py v0.6–v0.9.2 (see INDEX.md).
  * MapScene.remove_connection: the removal + the repeated call → False;
  * EditConnectionDialog: the prefill of the label/type, the readonly source/target, get_connection;
  * MainWindow._edit_connection: the apply of the label+type + the dirty marker;
  * _copy_node_info: the ip field to the clipboard (the fallback to the host when the ip is empty);
  * _ping_node: the background thread starts and finishes (the headless hermeticity:
    the modal QMessageBox.information is replaced by the stub);
  * MapView._classify_at: the node in the center, the arrow in the middle of the curve (the geometry EXACTLY as
    in ConnectionArrow._compute_geometry); _remove_connection through the confirmation.

Run: python tests/test_context_menus.py   (from the project root) or python tests/run_all.py
"""
import sys
import traceback

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication(sys.argv)

import ui.main_window as MW
from models.server import server_data_from_dict

# ══ v0.7.3: the context menu of the node and the arrow ═══════════════════════
print("== v0.7.3 context menus ==")

from dialogs.connection_dialog import ConnectionDialog as _CD73, EditConnectionDialog as _ECD73
from graphics.connection_arrow import CONNECTION_TYPES as _CT73

win73 = MW.MainWindow()
# Explicit, spread-out positions: without x/y both nodes fall into (0,0) — the rects overlap,
# the curve degenerates to a point inside the nodes themselves, and the _classify_at checks below lose their meaning.
d_a = server_data_from_dict({"alias": "ctx-a", "host": "192.168.3.52", "user": "u", "ip": "192.0.2.10", "x": 100, "y": 100})
d_b = server_data_from_dict({"alias": "ctx-b", "host": "192.168.3.53", "user": "u", "x": 450, "y": 160})
n_a = win73.scene.add_server(d_a)
n_b = win73.scene.add_server(d_b)
arrow73 = win73.scene.add_connection(d_a.id, d_b.id, "l1", "vpn")
check("fixture: two nodes + one vpn arrow", arrow73 is not None and arrow73.connection_type == "vpn")

# MapScene.remove_connection: removal + a repeated call
ok_rm = win73.scene.remove_connection(arrow73)
check("scene.remove_connection removes the arrow", ok_rm and arrow73 not in win73.scene._arrows)
check("scene.remove_connection returns False for unknown arrow",
      win73.scene.remove_connection(arrow73) is False)
arrow73 = win73.scene.add_connection(d_a.id, d_b.id, "l1", "vpn")  # return it for the following tests

# EditConnectionDialog: a label/type prefill, get_connection -> (label, ctype, bidir) (v1.2.6)
try:
    ecd = _ECD73(arrow73, None)
    check("EditConnectionDialog prefills label", ecd.label.text() == "l1")
    check("EditConnectionDialog prefills type vpn", ecd.type_combo.currentData() == "vpn")
    check("EditConnectionDialog source is readonly", ecd.source.isReadOnly() and ecd.target.isReadOnly())
    check("EditConnectionDialog get_connection returns (label, ctype, bidir)",
          ecd.get_connection() == ("l1", "vpn", False))
except Exception:
    check("EditConnectionDialog builds", False, traceback.format_exc(limit=1))

# MainWindow._edit_connection: applies the label and the type to the arrow + the dirty marker
class _FakeDlg:
    def __init__(self, label, ctype, bidir=False): self._r = (label, ctype, bidir)  # v1.2.6: a 3-tuple
    def exec(self): return 1  # QDialog.Accepted
    def get_connection(self): return self._r
_real_ecd = _ECD73
win73._dirty = False
import dialogs.connection_dialog as _dcd_mod
_dcd_mod.EditConnectionDialog = lambda arrow, parent=None: _FakeDlg("new-label", "database")
try:
    win73._edit_connection(arrow73)
finally:
    _dcd_mod.EditConnectionDialog = _real_ecd
check("_edit_connection applies label+type and marks dirty",
      arrow73.label_text == "new-label" and arrow73.connection_type == "database" and win73._dirty,
      f"{arrow73.label_text}/{arrow73.connection_type}/dirty={win73._dirty}")

# _copy_node_info: the IP in the clipboard (hostname — without a DNS dependency: only the call).
# v0.8.1: a node has a separate `ip` field (models.server) — "copy IP" returns it,
# and host is taken as a fallback when ip is empty (the _copy_node_info behaviour, v0.7.3).
win73._copy_node_info(n_a, "ip")
check("_copy_node_info(ip) copies the node's ip field when set",
      QApplication.clipboard().text() == "192.0.2.10", QApplication.clipboard().text())
d_noip = server_data_from_dict({"alias": "ctx-noip", "host": "192.168.3.99", "user": "u"})
n_noip = win73.scene.add_server(d_noip)
win73._copy_node_info(n_noip, "ip")
check("_copy_node_info(ip) falls back to host when ip is empty",
      QApplication.clipboard().text() == "192.168.3.99", QApplication.clipboard().text())
win73.scene.remove_server(n_noip.data.id)

# _ping_node: the thread starts and finishes (no network — 192.168.3.52 from TEST-NET, a fast fail).
# The headless hermeticity: on a failed ping the slot shows a MODAL QMessageBox.information()
# — in offscreen no one will close it and exec() will hang forever (pinned down by the run outcome
# audit v0.7.2). For the duration of the check we replace it with a recording stub, as above for EditConnectionDialog.
import PySide6.QtWidgets as _QW73
_real_qmb_info = _QW73.QMessageBox.information
_ping_dialog_calls = []
_QW73.QMessageBox.information = staticmethod(
    lambda *a, **kw: (_ping_dialog_calls.append(a), 0)[1])
try:
    win73._ping_node(n_a)
    check("_ping_node starts background thread", win73._ping_thread is not None)
    from PySide6.QtTest import QTest as _QTest
    for _ in range(200):
        if win73._ping_thread is None:
            break
        app.processEvents(); _QTest.qWait(50)
    check("_ping_node thread finishes and clears itself", win73._ping_thread is None)
finally:
    _QW73.QMessageBox.information = _real_qmb_info

# The context menu: the classification of a node/arrow point (no exec — headless)
v73 = win73.view
cls_node = v73._classify_at(n_a.sceneBoundingRect().center())
check("_classify_at finds node at its center", cls_node[0] is n_a)
# the middle of the connection: the edge-to-edge geometry EXACTLY as in ConnectionArrow._compute_geometry()
# (edge_point at the node borders → build_curve). Before, a center→center curve was built here —
# it does not match the drawn one, and the point t=0.5 ended up missing the arrow stroke.
from graphics.connection_arrow import build_curve as _bc73, curve_midpoint as _cm73, edge_point as _ep73
_src_rect_c = arrow73.source.sceneBoundingRect()
_tgt_rect_c = arrow73.target.sceneBoundingRect()
p0c = _ep73(_src_rect_c, _src_rect_c.center(), _tgt_rect_c.center())
p3c = _ep73(_tgt_rect_c, _tgt_rect_c.center(), _src_rect_c.center())
_path, c1c, c2c = _bc73(p0c, p3c)
cls_arrow = v73._classify_at(_cm73(p0c, c1c, c2c, p3c))
check("_classify_at finds arrow at curve midpoint", cls_arrow[1] is arrow73, str(cls_arrow))

# Removing a connection via MainWindow (no confirmation — a monkeypatch of question)
_real_q = QMessageBox.question
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
try:
    ok_del = win73._remove_connection(arrow73)
finally:
    QMessageBox.question = _real_q
check("_remove_connection deletes arrow after confirm",
      ok_del and arrow73 not in win73.scene._arrows and win73._dirty)

finish()
