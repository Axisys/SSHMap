# -*- coding: utf-8 -*-
"""Двухсторонние стрелки (v1.2.6, ROADMAP задача 1).

Покрывает:
  * геометрия: наконечники на ОБОИХ концах кривой — кончики ровно на границах узлов, каждый наконечник смотрит НА СВОЙ узел (←——→);
    стандартный режим — путь исходного наконечника пуст (item невидим);
  * set_bidirectional: переключение + идемпотентность без пересоздания item'а;
  * ConnectionDialog / EditConnectionDialog: чекбокс, prefill из стрелки,
    кортежи get_connection() 5/3 элементов (v1.2.6);
  * MapScene.add_connection(bidirectional=...);
  * JSON: поле "bidirectional" пишется только когда true (паттерн server_id),
    round-trip save/load, backward-compat (нет поля → односторонняя);
  * undo/redo: CmdAddRemoveConnection (флаг сохраняется через undo/redo),
    CmdEditConnection (переключение флага одной командой), удаление узла —
    стэш 5-кортежей E2E (_remove_node_guarded с patched QMessageBox.question);
  * drawio-экспорт: startArrow=classic у двухстороннего ребра, без него у обычного;
  * i18n-паритет + состояние релиза.

Запуск: python tests/test_bidirectional_arrows.py   (из корня проекта) или python tests/run_all.py
"""
import json
import os
import sys
import xml.etree.ElementTree as ET

from _common import bootstrap, check, finish, load_i18n_langs, check_i18n_parity, check_release_state

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication(sys.argv)

import ui.main_window as MW
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

# ── §1 Геометрия: два наконечника, кончики на границах узлов ────────────────
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
# Замкнутый треугольник = moveTo + 2×lineTo + closeSubpath → 4 элемента пути.
check("standard arrow: target head present (moveTo + 2 lineTo + close)",
      std._arrow_head.path().elementCount() == 4,
      str(std._arrow_head.path().elementCount()))

nc = sc.add_server(ServerData(id="bc03", alias="C", host="10.9.9.3", user="u"))
nd = sc.add_server(ServerData(id="bd04", alias="D", host="10.9.9.4", user="u"))
nd.setPos(400, 200)  # C (0, 200), D (400, 200) — горизонтальная пара

bi = sc.add_connection("bc03", "bd04", "two-way", "vpn", bidirectional=True)
check("scene.add_connection(bidirectional=True) sets the flag",
      bi is not None and bi.bidirectional is True)

rect_c, rect_d = nc.sceneBoundingRect(), nd.sceneBoundingRect()
src_head = bi._arrow_head_src.path()
tgt_head = bi._arrow_head.path()
check("bidirectional arrow: both heads present (4 elements each)",
      src_head.elementCount() == 4 and tgt_head.elementCount() == 4,
      f"{src_head.elementCount()}/{tgt_head.elementCount()}")
# elementAt(0) — MoveToElement; в PySide6 у Element.x/.y свойства (не методы).
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

# v1.2.6-fix: ОРИЕНТАЦИЯ — каждый наконечник смотрит НА СВОЙ узел (←——→), а не оба
# в сторону движения (→——→). Центроид заполненного треугольника лежит по «крыльевую»
# сторону от кончика: у исходного наконечника он обязан быть между p0 и p3 (на стороне
# кривой, вне узла), у целевого — между p3 и p0. Раньше проверялись только
# elementCount/позиция кончика, поэтому перевёрнутый исходный наконечник (тело под
# узлом) проходил тесты, но визуально не отличался от односторонней стрелки.
p0_pts, _c1, _c2, p3_pts = bi._curve_pts


def _head_centroid(path):
    pts = [path.elementAt(i) for i in range(3)]  # MoveTo (кончик) + 2×lineTo (крылья)
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

# ── §2 set_bidirectional: переключение + идемпотентность ────────────────────
std.set_bidirectional(True)
check("set_bidirectional(True): source head appears",
      std.bidirectional is True and std._arrow_head_src.path().elementCount() == 4)
std.set_bidirectional(True)  # повторный вызов с тем же значением — no-op без ошибок
check("set_bidirectional idempotent (second call is a no-op)",
      std.bidirectional is True and std._arrow_head_src.path().elementCount() == 4)
std.set_bidirectional(False)
check("set_bidirectional(False): source head removed again",
      std.bidirectional is False and std._arrow_head_src.path().elementCount() == 0)

# ── §3 Диалоги: чекбокс, prefill, расширенные кортежи ────────────────────────
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

# ── §4 Сериализация JSON: опциональное поле + round-trip + backward-compat ───
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

# ── §5 undo/redo: флаг живёт через все команды ───────────────────────────────
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

# E2E: удаление узла захватывает 5-кортежи; undo возвращает связь как была
win5 = MW.MainWindow()
m1 = win5.scene.add_server(ServerData(id="m1", alias="M1", host="10.3.3.1", user="root"))
m2 = win5.scene.add_server(ServerData(id="m2", alias="M2", host="10.3.3.2", user="root"))
win5.scene.add_connection("m1", "m2", "stash-bi", "nfs", bidirectional=True)

_orig_question = QMessageBox.question


def _fake_question(*a, **k):
    return QMessageBox.Yes


QMessageBox.question = staticmethod(_fake_question)
try:
    removed = win5._remove_node_guarded(m2)
finally:
    QMessageBox.question = _orig_question
check("_remove_node_guarded deleted the node and its arrow",
      removed is True and not win5.scene.has_node("m2")
      and _find_arrow(win5.scene, "m1", "m2") is None)
win5.undo_stack.undo()
restored = _find_arrow(win5.scene, "m1", "m2")
check("undo of node deletion restored the bidirectional arrow (5-tuple stash)",
      win5.scene.has_node("m2") and restored is not None and restored.bidirectional is True)

# ── §6 drawio-экспорт: startArrow у двухстороннего ребра ─────────────────────
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

# ── §7 i18n-паритет + состояние релиза ───────────────────────────────────────
langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)
check_release_state(ROOT)

finish()
