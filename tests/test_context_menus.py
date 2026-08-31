"""Контекстные меню узла и стрелки v0.7.3 (бывш. smoke_test.py «v0.7.3 context menus»).

Часть сьюта, разбитого из smoke_test.py v0.6–v0.9.2 (см. INDEX.md).
  * MapScene.remove_connection: удаление + повторный вызов → False;
  * EditConnectionDialog: prefill метки/типа, readonly source/target, get_connection;
  * MainWindow._edit_connection: применение метки+типа + dirty-маркер;
  * _copy_node_info: ip-поле в буфер (fallback на host при пустом ip);
  * _ping_node: фоновый поток стартует и завершается (headless-герметичность:
    модальный QMessageBox.information подменяется заглушкой);
  * MapView._classify_at: узел в центре, стрелка в середине кривой (геометрия РОВНО как
    в ConnectionArrow._compute_geometry); _remove_connection через подтверждение.

Запуск: python tests/test_context_menus.py   (из корня проекта) или python tests/run_all.py
"""
import sys
import traceback

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication(sys.argv)

import ui.main_window as MW
from models.server import server_data_from_dict

# ══ v0.7.3: контекстное меню узла и стрелки ═══════════════════════
print("== v0.7.3 context menus ==")

from dialogs.connection_dialog import ConnectionDialog as _CD73, EditConnectionDialog as _ECD73
from graphics.connection_arrow import CONNECTION_TYPES as _CT73

win73 = MW.MainWindow()
# Позиции явные и разнесённые: без x/y обе ноды падают в (0,0) — rect'и перекрываются,
# кривая вырождается в точку внутри самих нод, и _classify_at-проверки ниже теряют смысл.
d_a = server_data_from_dict({"alias": "ctx-a", "host": "192.168.3.52", "user": "u", "ip": "192.0.2.10", "x": 100, "y": 100})
d_b = server_data_from_dict({"alias": "ctx-b", "host": "192.168.3.53", "user": "u", "x": 450, "y": 160})
n_a = win73.scene.add_server(d_a)
n_b = win73.scene.add_server(d_b)
arrow73 = win73.scene.add_connection(d_a.id, d_b.id, "l1", "vpn")
check("fixture: two nodes + one vpn arrow", arrow73 is not None and arrow73.connection_type == "vpn")

# MapScene.remove_connection: удаление + повторный вызов
ok_rm = win73.scene.remove_connection(arrow73)
check("scene.remove_connection removes the arrow", ok_rm and arrow73 not in win73.scene._arrows)
check("scene.remove_connection returns False for unknown arrow",
      win73.scene.remove_connection(arrow73) is False)
arrow73 = win73.scene.add_connection(d_a.id, d_b.id, "l1", "vpn")  # вернуть для следующих тестов

# EditConnectionDialog: prefill метки/типа, get_connection -> (label, ctype)
try:
    ecd = _ECD73(arrow73, None)
    check("EditConnectionDialog prefills label", ecd.label.text() == "l1")
    check("EditConnectionDialog prefills type vpn", ecd.type_combo.currentData() == "vpn")
    check("EditConnectionDialog source is readonly", ecd.source.isReadOnly() and ecd.target.isReadOnly())
    check("EditConnectionDialog get_connection returns (label, ctype)",
          ecd.get_connection() == ("l1", "vpn"))
except Exception:
    check("EditConnectionDialog builds", False, traceback.format_exc(limit=1))

# MainWindow._edit_connection: применяет метку и тип к стрелке + dirty-маркер
class _FakeDlg:
    def __init__(self, label, ctype): self._r = (label, ctype)
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

# _copy_node_info: IP в буфере обмена (hostname — без DNS-зависимости: только вызов).
# v0.8.1: у узла есть отдельное поле `ip` (models.server) — «копировать IP» отдаёт его,
# а host берётся как fallback, когда ip пустой (поведение _copy_node_info, v0.7.3).
win73._copy_node_info(n_a, "ip")
check("_copy_node_info(ip) copies the node's ip field when set",
      QApplication.clipboard().text() == "192.0.2.10", QApplication.clipboard().text())
d_noip = server_data_from_dict({"alias": "ctx-noip", "host": "192.168.3.99", "user": "u"})
n_noip = win73.scene.add_server(d_noip)
win73._copy_node_info(n_noip, "ip")
check("_copy_node_info(ip) falls back to host when ip is empty",
      QApplication.clipboard().text() == "192.168.3.99", QApplication.clipboard().text())
win73.scene.remove_server(n_noip.data.id)

# _ping_node: поток стартует и завершается (без сети — 192.168.3.52 из TEST-NET, быстрый fail).
# Headless-герметичность: при неудачном пинге слот показывает МОДАЛЬНЫЙ QMessageBox.information()
# — в offscreen его никто не закроет и exec() зависнет навсегда (закреплено по итогам прогона
# аудита v0.7.2). На время проверки подменяем на заглушку-записчик, как выше для EditConnectionDialog.
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

# Контекстное меню: классификация точки узла/стрелки (без exec — headless)
v73 = win73.view
cls_node = v73._classify_at(n_a.sceneBoundingRect().center())
check("_classify_at finds node at its center", cls_node[0] is n_a)
# середина связи: геометрия edge-to-edge РОВНО как в ConnectionArrow._compute_geometry()
# (edge_point на границах узлов → build_curve). Раньше здесь строилась кривая центр→центр —
# она не совпадает с нарисованной, и точка t=0.5 оказывалась мимо штриха стрелки.
from graphics.connection_arrow import build_curve as _bc73, curve_midpoint as _cm73, edge_point as _ep73
_src_rect_c = arrow73.source.sceneBoundingRect()
_tgt_rect_c = arrow73.target.sceneBoundingRect()
p0c = _ep73(_src_rect_c, _src_rect_c.center(), _tgt_rect_c.center())
p3c = _ep73(_tgt_rect_c, _tgt_rect_c.center(), _src_rect_c.center())
_path, c1c, c2c = _bc73(p0c, p3c)
cls_arrow = v73._classify_at(_cm73(p0c, c1c, c2c, p3c))
check("_classify_at finds arrow at curve midpoint", cls_arrow[1] is arrow73, str(cls_arrow))

# Удаление связи через MainWindow (без подтверждения — monkeypatch question)
_real_q = QMessageBox.question
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
try:
    ok_del = win73._remove_connection(arrow73)
finally:
    QMessageBox.question = _real_q
check("_remove_connection deletes arrow after confirm",
      ok_del and arrow73 not in win73.scene._arrows and win73._dirty)

finish()
