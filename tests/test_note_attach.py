"""v1.2.4: крепление заметок к серверам + особая линия (тема релиза v1.2.4).

Тематический тест нового релиза (см. INDEX.md):
  * §1 Формат и сериализация: "server_id" в to_dict() пишется только если задан;
    _do_save → JSON; backward-compat старых файлов; битая ссылка → свободная заметка;
  * §2 Механика сцены: якорь (правый верхний угол узла + 12,12), линия-якорь
    (DashLine #eedd9f — цвет тела стикера, z=-1, концы — edge_point), движение узла
    (одношаговый лаг ровно как у стрелок — itemChange ДО применения позиции; точное
    совпадение на следующем шаге), v1.2.4-fix: offset якоря — закреплённую заметку
    можно двигать (dragUpdated → линия следует live, узел ведёт заметку с сохранением
    смещения), collapse/expand, detach, очистки remove_server/clear_all;
  * §3 Undo/Redo: attach/detach round-trip через win.undo_stack; LIFO-цепочка
    «открепление + удаление сервера»; мёртвый C++-объект (audit #8) — разрешение по id;
  * §4 Контекстное меню: свободная заметка → подменю со всеми узлами / прямой пункт
    над узлом; закреплённая → открепить; «Удалить заметку» на месте (синтетический
    QContextMenuEvent + capture-паттерн test_groups.py);
  * §5 Drag & drop E2E (QTest, полный pipeline view→scene→item): drag на узел = прикрепить,
    v1.2.4-fix: сдвиг закреплённой = ПЕРЕМЕЩЕНИЕ без открепления (линия следует,
    offset сохраняется), drag на другой узел = пере-крепление (одна команда),
    клик без движения — no-op;
  * §6 Save/Load round-trip: крепление восстанавливается, v1.2.4-fix: сохранённая
    позиция закреплённой заметки доверяется (offset от якоря вычисляется от неё);
  * §7 i18n-паритет (417 ключей) + состояние релиза v1.2.4.

Запуск: python tests/test_note_attach.py   (из корня проекта) или python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish, viewport_point as _vp, \
    load_i18n_langs, check_i18n_parity, check_release_state

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication(sys.argv)

import ui.main_window as MW
from models.server import server_data_from_dict
from graphics.connection_arrow import edge_point as _ep
from PySide6.QtCore import QPointF as _QP, QPoint as _QPt, Qt as _Qt
from PySide6.QtTest import QTest as _QTest
from i18n import t as _t

import json
import os


def _anchor(node):
    """Якорная позиция заметки: правый верхний угол узла + (12, 12)."""
    r = node.sceneBoundingRect()
    return (r.right() + 12.0, r.top() + 12.0)


def _at(pos, exp):
    return abs(pos[0] - exp[0]) < 0.5 and abs(pos[1] - exp[1]) < 0.5


print("== v1.2.4 note attach ==")

# ══ §1 Формат и сериализация ═════════════════════════════════════════
win_m = MW.MainWindow()
n_a = win_m.scene.add_server(server_data_from_dict(
    {"alias": "att-a", "host": "10.0.0.1", "user": "u", "x": 100, "y": 100}))
n_b = win_m.scene.add_server(server_data_from_dict(
    {"alias": "att-b", "host": "10.0.0.2", "user": "u", "x": 500, "y": 400}))

note_f = win_m.scene.add_note(text="free", x=900.0, y=100.0)
d0 = note_f.to_dict()
check("§1 free note to_dict has no server_id key", "server_id" not in d0, str(d0))

ok_att = win_m.scene.attach_note_to_node(note_f, n_a)
d1 = note_f.to_dict()
check("§1 attach: to_dict carries server_id == node id",
      ok_att and d1.get("server_id") == n_a.data.id, str(d1))

win_m.scene.detach_note_from_node(note_f)
d2 = note_f.to_dict()
check("§1 detach: server_id key disappears again", "server_id" not in d2, str(d2))

# Сохранение: у закреплённой — ключ, у свободной — нет
win_m.scene.attach_note_to_node(note_f, n_a)
note_free2 = win_m.scene.add_note(text="free2", x=900.0, y=300.0)
p1 = os.path.join(WORK, "attach_v124.json")
ok_s = win_m._do_save(p1)
with open(p1, encoding="utf-8") as f:
    j1 = json.load(f)
notes_j = {n["id"]: n for n in j1.get("notes", [])}
check("§1 saved JSON: attached note has server_id",
      ok_s and notes_j.get(note_f.note_id, {}).get("server_id") == n_a.data.id, str(notes_j))
check("§1 saved JSON: free note has no server_id key",
      "server_id" not in notes_j.get(note_free2.note_id, {}), str(notes_j))

# Backward-compat: старый файл (заметки без server_id) → свободные
win_l = MW.MainWindow()
old_raw = {"version": "0.9",
           "servers": [{"alias": "lc", "host": "10.0.0.3", "user": "u", "id": "lcnode01"}],
           "connections": [],
           "notes": [{"id": "oldnote1", "text": "old", "x": 50, "y": 60,
                      "width": 240, "height": 160}]}
win_l._import_project_raw(old_raw)
n_old = win_l.scene.get_note_by_id("oldnote1")
check("§1 old file (no server_id) loads: note is free",
      n_old is not None and getattr(n_old, "server_id", None) is None,
      str(getattr(n_old, "server_id", "MISSING")))

# Битая ссылка: server_id на несуществующий узел → свободная на сохранённой позиции
win_b = MW.MainWindow()
bad_raw = {"version": "0.9",
           "servers": [{"alias": "lc2", "host": "10.0.0.4", "user": "u", "id": "lcnode02"}],
           "connections": [],
           "notes": [{"id": "badnote1", "text": "broken ref", "x": 77, "y": 88,
                      "width": 240, "height": 160, "server_id": "ghostnode"}]}
win_b._import_project_raw(bad_raw)
n_bad = win_b.scene.get_note_by_id("badnote1")
check("§1 broken server_id ref: note stays free at saved position",
      n_bad is not None and getattr(n_bad, "server_id", None) is None
      and abs(n_bad.pos().x() - 77.0) < 0.5 and abs(n_bad.pos().y() - 88.0) < 0.5,
      f"pos=({n_bad.pos().x() if n_bad else '?'}, {n_bad.pos().y() if n_bad else '?'})")

# ══ §2 Механика сцены: якорь, линия, следование, очистки ══════════════
win_x = MW.MainWindow()
n_x = win_x.scene.add_server(server_data_from_dict(
    {"alias": "mech", "host": "10.0.0.7", "user": "u", "x": 100, "y": 100}))
note_x = win_x.scene.add_note(text="mech", x=600.0, y=300.0)

ok = win_x.scene.attach_note_to_node(note_x, n_x)
ax, ay = _anchor(n_x)
check("§2 attach places note exactly at topRight+(12,12)",
      ok and _at((note_x.pos().x(), note_x.pos().y()), (ax, ay)),
      f"note=({note_x.pos().x()}, {note_x.pos().y()}) expected=({ax}, {ay})")

line = win_x.scene._note_anchor_lines.get(note_x.note_id)
check("§2 anchor line exists in _note_anchor_lines", line is not None)
pen = line.pen()
# setDashPattern([4,3]) переводит стиль в CustomDashLine — визуально тот же пунктир;
# цвет = тело стикера (v1.2.4-fix: приглушённый #eedd9f)
check("§2 line pen: dashed, #eedd9f, width 1.2",
      pen.style() in (_Qt.PenStyle.DashLine, _Qt.PenStyle.CustomDashLine)
      and pen.color().name().lower() == "#eedd9f"
      and abs(pen.widthF() - 1.2) < 0.01,
      f"style={pen.style()} color={pen.color().name()} w={pen.widthF()}")
check("§2 line dash pattern [4,3]", list(pen.dashPattern()) == [4.0, 3.0],
      str(list(pen.dashPattern())))
check("§2 line zValue == -1 (above arrows -2, below nodes/notes 0)",
      abs(line.zValue() + 1.0) < 0.001, str(line.zValue()))

# Концы линии — edge_point на границах обоих rect'ов
nr, rr = note_x.sceneBoundingRect(), n_x.sceneBoundingRect()
exp_p0 = _ep(nr, nr.center(), rr.center())   # сторона заметки (moveTo)
exp_p1 = _ep(rr, rr.center(), nr.center())   # сторона узла (lineTo → currentPosition)
path = line.path()
e0 = path.elementAt(0)
start = (e0.x, e0.y)
end = (path.currentPosition().x(), path.currentPosition().y())
check("§2 line note-side endpoint matches edge_point",
      abs(start[0] - exp_p0.x()) < 0.5 and abs(start[1] - exp_p0.y()) < 0.5,
      f"start={start} expected={exp_p0.x()},{exp_p0.y()}")
check("§2 line node-side endpoint matches edge_point",
      abs(end[0] - exp_p1.x()) < 0.5 and abs(end[1] - exp_p1.y()) < 0.5,
      f"end={end} expected={exp_p1.x()},{exp_p1.y()}")

# Движение узла: itemChange вызывается ДО применения позиции (Qt-нюанс) — заметка
# ведёт себя ровно как стрелки: после одиночного setPos отстаёт на шаг, на следующем
# шаге (повторный setPos — «release-самоисцеление» CmdMoveNode) — точное совпадение.
r_before = n_x.sceneBoundingRect()
anchor_before = (r_before.right() + 12.0, r_before.top() + 12.0)
n_x.setPos(n_x.pos().x() + 100, n_x.pos().y() + 50)
app.processEvents()
check("§2 single setPos: note lags one step (same as arrows; itemChange pre-apply)",
      _at((note_x.pos().x(), note_x.pos().y()), anchor_before),
      f"note=({note_x.pos().x()}, {note_x.pos().y()}) anchor(before)={anchor_before}")
r_mid = n_x.sceneBoundingRect()
n_x.setPos(n_x.pos().x() + 0.5, n_x.pos().y())
app.processEvents()
check("§2 next setPos: note exactly at previous geometry anchor",
      _at((note_x.pos().x(), note_x.pos().y()), (r_mid.right() + 12.0, r_mid.top() + 12.0)),
      f"note=({note_x.pos().x()}, {note_x.pos().y()})")

# v1.2.4-fix: закреплённую заметку можно двигать — dragUpdated пересчитывает offset
# (относительно ТЕКУЩЕЙ геометрии узла), линия-якорь следует live; узел дальше ведёт
# заметку С сохранением смещения
r_off0 = n_x.sceneBoundingRect()   # геометрия узла в момент драга
note_x.prepareGeometryChange()
note_x.setPos(note_x.pos().x() + 80.0, note_x.pos().y() + 40.0)
note_x.dragUpdated.emit(note_x)
app.processEvents()
exp_off = (note_x.pos().x() - (r_off0.right() + 12.0),
           note_x.pos().y() - (r_off0.top() + 12.0))
check("§2 drag of attached note: NO detach, offset stored",
      note_x.server_id == n_x.data.id
      and abs(note_x.anchor_offset[0] - exp_off[0]) < 0.5
      and abs(note_x.anchor_offset[1] - exp_off[1]) < 0.5,
      f"server_id={note_x.server_id} offset={note_x.anchor_offset}")
nr_d, rr_d = note_x.sceneBoundingRect(), n_x.sceneBoundingRect()
exp_d0 = _ep(nr_d, nr_d.center(), rr_d.center())
e0_d = line.path().elementAt(0)
check("§2 drag: anchor line follows live (note endpoint recomputed)",
      abs(e0_d.x - exp_d0.x()) < 0.5 and abs(e0_d.y - exp_d0.y()) < 0.5,
      f"start=({e0_d.x}, {e0_d.y}) expected=({exp_d0.x()}, {exp_d0.y()})")
n_x.setPos(n_x.pos().x() + 60, n_x.pos().y() - 30)
app.processEvents()
r_off_mid = n_x.sceneBoundingRect()
n_x.setPos(n_x.pos().x() + 0.5, n_x.pos().y())
app.processEvents()
check("§2 node move: attached note follows WITH offset",
      _at((note_x.pos().x(), note_x.pos().y()),
          (r_off_mid.right() + 12.0 + note_x.anchor_offset[0],
           r_off_mid.top() + 12.0 + note_x.anchor_offset[1])),
      f"note=({note_x.pos().x()}, {note_x.pos().y()}) offset={note_x.anchor_offset}")

# Collapse/expand: update_appearance применяет геометрию ДО хука — точное совпадение;
# концы линии пересчитаны под новую высоту карточки; offset заметки сохраняется
n_x.toggle_collapsed()
app.processEvents()
rc = n_x.sceneBoundingRect()
check("§2 collapse: note exactly at new anchor + offset",
      _at((note_x.pos().x(), note_x.pos().y()),
          (rc.right() + 12.0 + note_x.anchor_offset[0],
           rc.top() + 12.0 + note_x.anchor_offset[1])),
      f"note=({note_x.pos().x()}, {note_x.pos().y()}) offset={note_x.anchor_offset}")
nr_c, rr_c = note_x.sceneBoundingRect(), n_x.sceneBoundingRect()
exp_c = _ep(rr_c, rr_c.center(), nr_c.center())
end_c = (line.path().currentPosition().x(), line.path().currentPosition().y())
check("§2 collapse: line node-side endpoint recomputed",
      abs(end_c[0] - exp_c.x()) < 0.5 and abs(end_c[1] - exp_c.y()) < 0.5,
      f"end={end_c} expected={exp_c.x()},{exp_c.y()}")
n_x.toggle_collapsed()
app.processEvents()
re_ = n_x.sceneBoundingRect()
check("§2 expand back: note exactly at restored anchor + offset",
      _at((note_x.pos().x(), note_x.pos().y()),
          (re_.right() + 12.0 + note_x.anchor_offset[0],
           re_.top() + 12.0 + note_x.anchor_offset[1])))

# Detach: позиция не меняется, линия убирается
pos_attached = (note_x.pos().x(), note_x.pos().y())
ok_d = win_x.scene.detach_note_from_node(note_x)
check("§2 detach keeps note position",
      ok_d and _at((note_x.pos().x(), note_x.pos().y()), pos_attached),
      f"pos=({note_x.pos().x()}, {note_x.pos().y()}) was={pos_attached}")
check("§2 detach removes the anchor line",
      note_x.note_id not in win_x.scene._note_anchor_lines)

# remove_server: страховка — заметки снимаются, линии не остаются сиротами
win_x.scene.attach_note_to_node(note_x, n_x)
win_x.scene.remove_server(n_x.data.id)
check("§2 remove_server: note freed and no orphan lines",
      note_x.server_id is None and len(win_x.scene._note_anchor_lines) == 0,
      f"server_id={note_x.server_id} lines={list(win_x.scene._note_anchor_lines)}")

# clear_all: то же самое (чистая сцена без окна)
from graphics.map_scene import MapScene as _MS
sc = _MS()
nd = sc.add_server(server_data_from_dict(
    {"alias": "clr", "host": "10.0.0.8", "user": "u", "x": 0, "y": 0}))
nt = sc.add_note(text="clr", x=300, y=200)
sc.attach_note_to_node(nt, nd)
check("§2 clear_all precondition: line present", nt.note_id in sc._note_anchor_lines)
sc.clear_all()
check("§2 clear_all: anchor lines cleared (no orphans)",
      len(sc._note_anchor_lines) == 0 and len(sc.items()) == 0,
      f"lines={list(sc._note_anchor_lines)} items={len(sc.items())}")

# ══ §3 Undo/Redo: round-trip, LIFO-удаление, мёртвый объект (audit #8) ══
win_u = MW.MainWindow()
n_u = win_u.scene.add_server(server_data_from_dict(
    {"alias": "ur-a", "host": "10.0.0.5", "user": "u", "x": 100, "y": 100}))
note_u = win_u.scene.add_note(text="undo", x=600.0, y=300.0)
win_u._connect_note_signals(note_u)
old_pos = (note_u.pos().x(), note_u.pos().y())

ok_a = win_u._attach_note_to_node(note_u, n_u)
axu, ayu = _anchor(n_u)
check("§3 attach: command pushed, note at anchor",
      ok_a and note_u.server_id == n_u.data.id and win_u.undo_stack.canUndo()
      and _at((note_u.pos().x(), note_u.pos().y()), (axu, ayu)),
      f"server_id={note_u.server_id} pos=({note_u.pos().x()}, {note_u.pos().y()})")

win_u.undo_stack.undo()
check("§3 undo(attach): free at old position, line gone",
      note_u.server_id is None
      and _at((note_u.pos().x(), note_u.pos().y()), old_pos)
      and note_u.note_id not in win_u.scene._note_anchor_lines,
      f"pos=({note_u.pos().x()}, {note_u.pos().y()}) old={old_pos}")

win_u.undo_stack.redo()
check("§3 redo(attach): back at anchor with line",
      note_u.server_id == n_u.data.id
      and _at((note_u.pos().x(), note_u.pos().y()), (axu, ayu))
      and note_u.note_id in win_u.scene._note_anchor_lines)

ok_d2 = win_u._detach_note(note_u)
check("§3 detach: command pushed, note stays in place",
      ok_d2 and note_u.server_id is None
      and _at((note_u.pos().x(), note_u.pos().y()), (axu, ayu)))
win_u.undo_stack.undo()   # undo(detach) → повторный attach
check("§3 undo(detach): re-attached at anchor",
      note_u.server_id == n_u.data.id
      and _at((note_u.pos().x(), note_u.pos().y()), (axu, ayu)))
win_u.undo_stack.redo()   # redo(detach) → свободная на том же месте
check("§3 redo(detach): free, position unchanged",
      note_u.server_id is None
      and _at((note_u.pos().x(), note_u.pos().y()), (axu, ayu)))

# LIFO: «открепление + удаление сервера» откатывается полностью
n_c = win_u.scene.add_server(server_data_from_dict(
    {"alias": "ur-c", "host": "10.0.0.6", "user": "u", "x": 400, "y": 300}))
win_u._add_note_at(_QP(900, 500))            # [Add note] (метод не возвращает заметку)
note_l = win_u.scene._notes[-1]
win_u._attach_note_to_node(note_l, n_c)      # [Attach note]
axc, ayc = _anchor(n_c)
_real_q = QMessageBox.question
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
try:
    ok_rm = win_u._remove_node_guarded(n_c)  # [Detach note, Remove node] (LIFO-порядок)
finally:
    QMessageBox.question = _real_q
check("§3 LIFO: delete with attached note — node gone, note free",
      ok_rm and win_u.scene.get_node(n_c.data.id) is None and note_l.server_id is None,
      f"node={win_u.scene.get_node(n_c.data.id)} server_id={note_l.server_id}")
win_u.undo_stack.undo()   # undo(Remove node) → узел возвращается
win_u.undo_stack.undo()   # undo(Detach) → переприкрепление (узел уже жив)
n_c_back = win_u.scene.get_node(n_c.data.id)
check("§3 LIFO: undo×2 — node alive AND note re-attached at anchor",
      n_c_back is not None and note_l.server_id == n_c.data.id
      and _at((note_l.pos().x(), note_l.pos().y()), (axc, ayc)),
      f"node={n_c_back} server_id={note_l.server_id}")
win_u.undo_stack.redo()
win_u.undo_stack.redo()
check("§3 LIFO: redo×2 — node gone, note free again",
      win_u.scene.get_node(n_c.data.id) is None and note_l.server_id is None)

# Мёртвый C++-объект (audit #8): «создать → прикрепить → удалить» + undo×2
n_d = win_u.scene.add_server(server_data_from_dict(
    {"alias": "ur-d", "host": "10.0.0.11", "user": "u", "x": 700, "y": 300}))
win_u._add_note_at(_QP(1100, 500))            # [Add note]
note_d = win_u.scene._notes[-1]
old_d = (note_d.pos().x(), note_d.pos().y())
win_u._attach_note_to_node(note_d, n_d)        # [Attach note]
note_d_id = note_d.note_id
win_u._remove_note(note_d)                     # [Delete note] → deleteLater
app.processEvents()                            # C++-объект уничтожен (RuntimeError-путь)
win_u.undo_stack.undo()                        # undo(Delete) → НОВАЯ заметка с тем же id
note_d2 = win_u.scene.get_note_by_id(note_d_id)
check("§3 dead obj: undo(delete) recreates note with same id",
      note_d2 is not None and note_d2 is not note_d,
      f"resolved={note_d2}")
try:
    win_u.undo_stack.undo()                    # undo(Attach) — _resolve_note по id
    crashed = ""
except Exception as e:  # noqa: BLE001
    crashed = repr(e)
check("§3 dead obj: undo(attach) after delete-undo does not crash", crashed == "", crashed)
check("§3 dead obj: resolved note free at pre-attach position",
      note_d2 is not None and getattr(note_d2, "server_id", None) is None
      and _at((note_d2.pos().x(), note_d2.pos().y()), old_d),
      f"pos=({note_d2.pos().x() if note_d2 else '?'}, {note_d2.pos().y() if note_d2 else '?'})")

# ══ §4 Контекстное меню заметки (синтетический QContextMenuEvent) ═════
import graphics.map_view as _MVm
from PySide6.QtWidgets import QMenu as _QMenuBase

win_c = MW.MainWindow()
c_a = win_c.scene.add_server(server_data_from_dict(
    {"alias": "cm-a", "host": "10.0.0.21", "user": "u", "x": 100, "y": 100}))
c_b = win_c.scene.add_server(server_data_from_dict(
    {"alias": "cm-b", "host": "10.0.0.22", "user": "u", "x": 500, "y": 400}))

captured = []


class _CaptureMenu(_QMenuBase):
    def exec(self, *a, **k):      # offscreen: перехватываем — не блокируемся
        captured.append(self)
        return 0

    def exec_(self, *a, **k):     # legacy-имя
        captured.append(self)
        return 0


def _ctx(view, sp):
    from PySide6.QtGui import QContextMenuEvent as _QCME
    vp_ = view.mapFromScene(sp)
    x, y = int(vp_.x()), int(vp_.y())
    ev = _QCME(_QCME.Reason.Mouse, _QPt(x, y), _QPt(x + 5, y + 5))
    view.contextMenuEvent(ev)


def _find_act(menu, text):
    for act in menu.actions():
        if act.text() == text:
            return act
    return None


_orig_menu_cls = _MVm.QMenu
_MVm.QMenu = _CaptureMenu
try:
    # Случай A: свободная заметка, узла под курсором нет, выделения нет → подменю
    note_m1 = win_c.scene.add_note(text="menu-a", x=700.0, y=100.0)
    win_c.scene.clearSelection()
    captured.clear()
    _ctx(win_c.view, _QP(820, 180))   # центр заметки (rect 700..940 × 100..260)
    check("§4 ctx menu over free note captured", len(captured) == 1)
    if captured:
        m = captured[-1]
        texts = [a.text() for a in m.actions()]
        act_sub = _find_act(m, _t("ctx.note_attach"))
        check("§4 free note (no target): submenu ctx.note_attach present",
              act_sub is not None and _t("ctx.delete_note") in texts, str(texts))
        if act_sub is not None:
            sub_texts = [a.text() for a in act_sub.menu().actions()]
            check("§4 submenu lists ALL nodes (cm-a, cm-b)",
                  "cm-a" in sub_texts and "cm-b" in sub_texts, str(sub_texts))
            for sa in act_sub.menu().actions():
                if sa.text() == "cm-a":
                    sa.trigger()
                    break
        check("§4 submenu trigger attaches note to cm-a",
              note_m1.server_id == c_a.data.id
              and _at((note_m1.pos().x(), note_m1.pos().y()), _anchor(c_a)),
              f"server_id={note_m1.server_id}")

    # Случай B: свободная заметка НАД узлом → прямой пункт с alias
    note_m2 = win_c.scene.add_note(text="menu-b", x=520.0, y=420.0)  # пересекает c_b
    win_c.scene.clearSelection()
    captured.clear()
    _ctx(win_c.view, _QP(600, 470))   # точка в пересечении заметки и карточки c_b
    if captured:
        m = captured[-1]
        act_att = _find_act(m, _t("ctx.note_attach_to").format(alias="cm-b"))
        check("§4 note over node: direct item with alias in text",
              act_att is not None and _t("ctx.delete_note") in
              [a.text() for a in m.actions()],
              str([a.text() for a in m.actions()]))
        if act_att is not None:
            act_att.trigger()
        check("§4 direct item trigger attaches note to cm-b",
              note_m2.server_id == c_b.data.id
              and _at((note_m2.pos().x(), note_m2.pos().y()), _anchor(c_b)),
              f"server_id={note_m2.server_id}")

    # Случай C: закреплённая заметка → пункт открепления; позиция не меняется
    pos_c = (note_m2.pos().x(), note_m2.pos().y())
    captured.clear()
    _ctx(win_c.view, _QP(pos_c[0] + 50, pos_c[1] + 40))   # тело закреплённой заметки
    if captured:
        m = captured[-1]
        act_det = _find_act(m, _t("ctx.note_detach"))
        check("§4 attached note: ctx.note_detach present (delete item kept)",
              act_det is not None and _t("ctx.delete_note") in
              [a.text() for a in m.actions()],
              str([a.text() for a in m.actions()]))
        if act_det is not None:
            act_det.trigger()
        check("§4 detach trigger: note free, position unchanged",
              note_m2.server_id is None and _at((note_m2.pos().x(), note_m2.pos().y()), pos_c),
              f"server_id={note_m2.server_id} pos=({note_m2.pos().x()}, {note_m2.pos().y()})")
finally:
    _MVm.QMenu = _orig_menu_cls

# ══ §5 Drag & drop E2E (QTest, полный pipeline view→scene→item) ═══════
win_e = MW.MainWindow()
n_e = win_e.scene.add_server(server_data_from_dict(
    {"alias": "e2e-a", "host": "10.0.0.31", "user": "u", "x": -400, "y": -100}))
n_f = win_e.scene.add_server(server_data_from_dict(
    {"alias": "e2e-b", "host": "10.0.0.32", "user": "u", "x": 200, "y": -100}))
win_e._add_note_at(_QP(0, 250))             # заметка через окно — сигналы подключены
note_e = win_e.scene._notes[-1]
vp = win_e.view.viewport()


def _drag(view, vp_, from_sp, to_sp, steps=6):
    """QTest drag: press в from_sp → шаги к to_sp → release (паттерн test_notes.py)."""
    _QTest.mousePress(vp_, _Qt.LeftButton, pos=_vp(view, from_sp))
    app.processEvents()
    for i in range(1, steps + 1):
        mid = _QP(from_sp.x() + (to_sp.x() - from_sp.x()) * i / steps,
                  from_sp.y() + (to_sp.y() - from_sp.y()) * i / steps)
        _QTest.mouseMove(vp_, pos=_vp(view, mid))
        app.processEvents()
    _QTest.mouseRelease(vp_, _Qt.LeftButton, pos=_vp(view, to_sp))
    app.processEvents()


# Drag 1: свободная заметка → release над узлом = прикрепить
ne_cx, ne_cy = n_e.sceneBoundingRect().center().x(), n_e.sceneBoundingRect().center().y()
drag1_from = _QP(note_e.pos().x() + 120, note_e.pos().y() + 80)   # центр заметки
_drag(win_e.view, vp, drag1_from, _QP(ne_cx, ne_cy))
check("§5 E2E: drag free note onto node attaches it",
      note_e.server_id == n_e.data.id, f"server_id={note_e.server_id}")
check("§5 E2E: attached at exact anchor",
      _at((note_e.pos().x(), note_e.pos().y()), _anchor(n_e)),
      f"pos=({note_e.pos().x()}, {note_e.pos().y()}) expected={_anchor(n_e)}")
check("§5 E2E: line created on attach",
      note_e.note_id in win_e.scene._note_anchor_lines)
# Нюанс биндинга: в этой сборке PySide6 index() возвращает count (не count-1) —
# верхняя команда на позиции count()-1.
top = win_e.undo_stack.count() - 1
check("§5 E2E: CmdAttachNote is the last undo command",
      top >= 1 and win_e.undo_stack.text(top) == "Attach note",
      f"count={win_e.undo_stack.count()} text={win_e.undo_stack.text(top)!r}")

# Drag 2 (v1.2.4-fix): сдвиг закреплённой заметки = ПЕРЕМЕЩЕНИЕ без открепления;
# release вне узлов — заметка остаётся закреплённой на позиции отпускания, линия
# следует live, offset сохраняется, undo-команд не появляется
count2 = win_e.undo_stack.count()
press2 = _QP(note_e.pos().x() + 100, note_e.pos().y() + 50)   # тело (не над n_e)
rel2 = _QP(0, 250)
_drag(win_e.view, vp, press2, rel2)
check("§5 E2E: moving attached note does NOT detach it",
      note_e.server_id == n_e.data.id, f"server_id={note_e.server_id}")
exp2 = (rel2.x() - 100.0, rel2.y() - 50.0)   # точка нажатия в локальных координатах заметки
check("§5 E2E: attached note stays at drop position",
      abs(note_e.pos().x() - exp2[0]) < 3 and abs(note_e.pos().y() - exp2[1]) < 3,
      f"pos=({note_e.pos().x()}, {note_e.pos().y()}) expected≈{exp2}")
check("§5 E2E: anchor line survives the move",
      note_e.note_id in win_e.scene._note_anchor_lines)
ne_r = n_e.sceneBoundingRect()
check("§5 E2E: offset from anchor preserved after drag",
      abs(note_e.anchor_offset[0] - (exp2[0] - ne_r.right() - 12.0)) < 3
      and abs(note_e.anchor_offset[1] - (exp2[1] - ne_r.top() - 12.0)) < 3,
      f"offset={note_e.anchor_offset}")
check("§5 E2E: no undo command for a plain move",
      win_e.undo_stack.count() == count2,
      f"count={win_e.undo_stack.count()} was={count2}")

# Drag 3 (v1.2.4-fix): закреплённая → drag на ДРУГОЙ узел = пере-крепление: ОДНА
# команда Attach note (server_id перезаписывается), заметка «встает» в якорь нового
win_e._attach_note_to_node(note_e, n_f)   # [Attach note] — заметка у n_f
press3 = _QP(note_e.pos().x() + 100, note_e.pos().y() + 50)   # тело (не над n_f)
count_before = win_e.undo_stack.count()
_drag(win_e.view, vp, press3, _QP(ne_cx, ne_cy))
top3 = win_e.undo_stack.count() - 1
check("§5 E2E: drag attached note to another node — ONE re-attach command",
      win_e.undo_stack.count() == count_before + 1
      and win_e.undo_stack.text(top3) == "Attach note",
      f"count={win_e.undo_stack.count()} (was {count_before}) "
      f"text={win_e.undo_stack.text(top3)!r}")
check("§5 E2E: ends attached to the NEW node at its anchor",
      note_e.server_id == n_e.data.id
      and _at((note_e.pos().x(), note_e.pos().y()), _anchor(n_e)),
      f"server_id={note_e.server_id} pos=({note_e.pos().x()}, {note_e.pos().y()})")

# Drag 4: клик без движения по закреплённой заметке НЕ открепляет
press4 = _QP(note_e.pos().x() + 60, note_e.pos().y() + 50)   # тело (не над n_e)
pos4 = (note_e.pos().x(), note_e.pos().y())
count4 = win_e.undo_stack.count()
_QTest.mousePress(vp, _Qt.LeftButton, pos=_vp(win_e.view, press4))
app.processEvents()
_QTest.mouseRelease(vp, _Qt.LeftButton, pos=_vp(win_e.view, press4))
app.processEvents()
check("§5 E2E: click without movement does NOT detach",
      note_e.server_id == n_e.data.id
      and _at((note_e.pos().x(), note_e.pos().y()), pos4)
      and win_e.undo_stack.count() == count4,
      f"server_id={note_e.server_id} count={win_e.undo_stack.count()}")

# ══ §6 Save/Load round-trip с креплением ══════════════════════════════
win_s = MW.MainWindow()
n_s = win_s.scene.add_server(server_data_from_dict(
    {"alias": "sl-a", "host": "10.0.0.41", "user": "u", "x": 100, "y": 100}))
note_s_free = win_s.scene.add_note(text="free-s", x=500.0, y=500.0)
win_s._connect_note_signals(note_s_free)
note_s_att = win_s.scene.add_note(text="att-s", x=600.0, y=300.0)
win_s._connect_note_signals(note_s_att)
win_s.scene.attach_note_to_node(note_s_att, n_s)
# v1.2.4-fix: сдвигаем закреплённую заметку (drag без открепления) — сохранённая
# позиция больше НЕ равна якорю; при загрузке она доверяется (offset вычисляется от неё)
note_s_att.prepareGeometryChange()
note_s_att.setPos(note_s_att.pos().x() + 60.0, note_s_att.pos().y() - 35.0)
note_s_att.dragUpdated.emit(note_s_att)
p6 = os.path.join(WORK, "attach_roundtrip.json")
ok6 = win_s._do_save(p6)
with open(p6, encoding="utf-8") as f:
    j6 = json.load(f)
n6 = {n["id"]: n for n in j6.get("notes", [])}
check("§6 saved JSON: attached note carries server_id; free note has no key",
      ok6 and n6.get(note_s_att.note_id, {}).get("server_id") == n_s.data.id
      and "server_id" not in n6.get(note_s_free.note_id, {}), str(n6))

win_s2 = MW.MainWindow()
win_s2._import_project_raw(j6)
att2 = win_s2.scene.get_note_by_id(note_s_att.note_id)
free2 = win_s2.scene.get_note_by_id(note_s_free.note_id)
n_s2 = win_s2.scene.get_node(n_s.data.id)
a2x, a2y = _anchor(n_s2)
check("§6 reload: note re-attached to its server",
      att2 is not None and att2.server_id == n_s.data.id,
      f"server_id={getattr(att2, 'server_id', 'MISSING')}")
# v1.2.4-fix: сохранённая x/y доверяется (заметку можно двигать) — НЕ прыжок в угол
check("§6 reload: saved position trusted (not snapped to corner)",
      att2 is not None
      and abs(att2.pos().x() - n6[att2.note_id]["x"]) < 0.5
      and abs(att2.pos().y() - n6[att2.note_id]["y"]) < 0.5,
      f"pos=({att2.pos().x() if att2 else '?'}, {att2.pos().y() if att2 else '?'}) "
      f"saved=({n6[att2.note_id]['x'] if att2 else '?'}, {n6[att2.note_id]['y'] if att2 else '?'})")
check("§6 reload: offset derived from saved position (+60,-35)",
      att2 is not None
      and abs(att2.anchor_offset[0] - (n6[att2.note_id]["x"] - a2x)) < 0.5
      and abs(att2.anchor_offset[1] - (n6[att2.note_id]["y"] - a2y)) < 0.5,
      f"offset={getattr(att2, 'anchor_offset', 'MISSING')}")
check("§6 reload: free note unchanged (position + no server_id)",
      free2 is not None and getattr(free2, "server_id", None) is None
      and abs(free2.pos().x() - n6[note_s_free.note_id]["x"]) < 0.5
      and abs(free2.pos().y() - n6[note_s_free.note_id]["y"]) < 0.5,
      f"pos=({free2.pos().x() if free2 else '?'}, {free2.pos().y() if free2 else '?'})")

# v1.2.4-fix: сохранённая x/y закреплённой заметки доверяется как есть (даже необычная)
# — позиция первична (её двигал пользователь), крепление и линия восстанавливаются,
# offset вычисляется от этой позиции относительно якоря узла
j6b = json.loads(json.dumps(j6))
for rec in j6b["notes"]:
    if rec["id"] == note_s_att.note_id:
        rec["x"], rec["y"] = 0.0, 0.0
win_s3 = MW.MainWindow()
win_s3._import_project_raw(j6b)
att3 = win_s3.scene.get_note_by_id(note_s_att.note_id)
check("§6 reload: unusual saved position trusted as-is, attachment + line restored",
      att3 is not None and att3.server_id == n_s.data.id
      and abs(att3.pos().x() - 0.0) < 0.5 and abs(att3.pos().y() - 0.0) < 0.5
      and att3.note_id in win_s3.scene._note_anchor_lines,
      f"pos=({att3.pos().x() if att3 else '?'}, {att3.pos().y() if att3 else '?'}) "
      f"server_id={getattr(att3, 'server_id', 'MISSING')}")

# Файл старого формата через полный путь _import_project_raw
win_s4 = MW.MainWindow()
old_raw6 = {"version": "0.9",
            "servers": [{"alias": "sl-b", "host": "10.0.0.42", "user": "u", "x": 100, "y": 100}],
            "connections": [],
            "notes": [{"id": "oldfmt1", "text": "t", "x": 50, "y": 60,
                       "width": 240, "height": 160}]}
win_s4._import_project_raw(old_raw6)
n_old6 = win_s4.scene.get_note_by_id("oldfmt1")
check("§6 old-format file via full path: note loads free",
      n_old6 is not None and getattr(n_old6, "server_id", None) is None)

# ══ §7 i18n + состояние релиза v1.2.4 ═════════════════════════════════
langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)
for k in ("ctx.note_attach", "ctx.note_attach_to", "ctx.note_detach",
          "status.note_attached", "status.note_detached", "msg.delete_server_with_notes"):
    check(f"§7 i18n key {k!r} present in en/ru/zh",
          all(k in langs[c] for c in ("en", "ru", "zh")))
check_release_state(ROOT)

finish()
