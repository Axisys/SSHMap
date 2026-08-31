"""Sticky notes: drag/resize/edit/delete + JSON round-trip (бывш. smoke_test.py §6e «v0.7.2»).

Часть сьюта, разбитого из smoke_test.py v0.6–v0.9.2 (см. INDEX.md).
  * создание + сериализация (to_dict/from_dict, битые значения → дефолты);
  * clamp размера MIN/MAX;
  * drag мышью через ПОЛНЫЙ pipeline view→scene→item (QTest-ввод): MapView сам
    переключает NoDrag при нажатии над заметкой; moved-сигнал на release;
  * resize за правый нижний угол; edit mode по двойному клику (focus policy);
  * textChanged → note.textEdited; Delete-клавиша через MainWindow._remove_note;
  * JSON round-trip + backward-compat старого проекта без ключа "notes".

Запуск: python tests/test_notes.py   (из корня проекта) или python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish, viewport_point as _vp

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

import ui.main_window as MW

# ── v0.7.2: sticky notes (drag/resize/edit/delete + JSON) ───
print("== v0.7.2 notes ==")
import json
import os
from graphics.sticky_note import StickyNote as _SN2
from PySide6.QtWidgets import QGraphicsView as _QGV2
from PySide6.QtCore import QPointF as _QP2, QEvent as _QEv2
from PySide6.QtCore import Qt as _Qt
from PySide6.QtTest import QTest as _QTest

win4 = MW.MainWindow()

# Создание + сериализация
note1 = win4.scene.add_note(text="hello", x=50.0, y=60.0)
check("scene.add_note creates StickyNote in _notes", len(win4.scene._notes) == 1 and note1 is win4.scene._notes[0])
d1 = note1.to_dict()
check("note to_dict has id/text/x/y/width/height",
      set(d1.keys()) == {"id", "text", "x", "y", "width", "height"} and d1["text"] == "hello"
      and len(d1["id"]) == 8, str(d1))

# from_dict: битые значения — дефолты, лишние ключи игнорируются
n_bad = _SN2.from_dict({"x": "garbage", "width": None, "extra_key": 1})
check("note from_dict survives bad values (defaults)", n_bad.pos().x() == 0.0 and n_bad.rect().width() >= _SN2.MIN_W)

# Размер: clamp MIN/MAX
n_cl = win4.scene.add_note(x=800, y=400)
n_cl.set_note_size(10, 5)
check("note size clamped to MIN", n_cl.rect().width() == _SN2.MIN_W and n_cl.rect().height() == _SN2.MIN_H)
n_cl.set_note_size(9999, 9999)
check("note size clamped to MAX", n_cl.rect().width() == _SN2.MAX_W and n_cl.rect().height() == _SN2.MAX_H)

# Drag заметки мышью через ПОЛНЫЙ pipeline view->scene->item (QTest-ввод, см. v0.7 секцию):
# MapView сам переключает NoDrag при нажатии над заметкой (динамический режим).
view4 = win4.view
check("drag mode is ScrollHandDrag before press over note", view4.dragMode() == _QGV2.DragMode.ScrollHandDrag)

vp4 = view4.viewport()   # QTest шлёт события в viewport — штатный путь маршрутизации Qt

moved_signals = []
note1.moved.connect(lambda: moved_signals.append(1))
p0 = _QP2(note1.pos().x() + 80, note1.pos().y() + 50)   # тело заметки (не угол!)
pos_before = (note1.pos().x(), note1.pos().y())          # отсчёт: заметка сдвигается на DELTA
_QTest.mousePress(vp4, _Qt.LeftButton, pos=_vp(view4, p0))
app.processEvents()
check("press over note switches view to NoDrag", view4.dragMode() == _QGV2.DragMode.NoDrag)
check("note press in body starts move-drag", note1._drag_mode == "move")
p1 = _QP2(p0.x() + 65, p0.y() + 45)
_QTest.mouseMove(vp4, pos=_vp(view4, p1))
app.processEvents()
pos_after_move = (note1.pos().x(), note1.pos().y())
check("note drag moves the item by delta (~+65/+45)",
      abs(pos_after_move[0] - (pos_before[0] + 65)) < 3 and abs(pos_after_move[1] - (pos_before[1] + 45)) < 3,
      f"{pos_before} -> {pos_after_move}")
_QTest.mouseRelease(vp4, _Qt.LeftButton, pos=_vp(view4, p1))
app.processEvents()
check("note moved signal fired on release", len(moved_signals) == 1, str(moved_signals))
check("drag mode restored to ScrollHandDrag after release", view4.dragMode() == _QGV2.DragMode.ScrollHandDrag)

# Resize за правый нижний угол: press в углу -> move наружу -> размер растёт
w0, h0 = note1.rect().width(), note1.rect().height()
corner = _QP2(note1.pos().x() + w0 - 6, note1.pos().y() + h0 - 6)
_QTest.mousePress(vp4, _Qt.LeftButton, pos=_vp(view4, corner))
app.processEvents()
check("press in bottom-right corner starts resize", note1._drag_mode == "resize")
_QTest.mouseMove(vp4, pos=_vp(view4, _QP2(corner.x() + 60, corner.y() + 40)))
app.processEvents()
check("note resize grows from the corner",
      note1.rect().width() > w0 + 40 and note1.rect().height() > h0 + 30,
      f"{w0:.0f}x{h0:.0f} -> {note1.rect().width():.0f}x{note1.rect().height():.0f}")
_QTest.mouseRelease(vp4, _Qt.LeftButton, pos=_vp(view4, corner))
app.processEvents()

# Edit mode: двойной клик через QTest — РЕАЛЬНЫЙ QGraphicsSceneMouseEvent (handler может
# переслать его в QTextEdit через super(); фейковый duck-typed event падал на C++-методе).
check("note not in edit mode initially", note1.editing is False)
_QTest.mouseDClick(vp4, _Qt.LeftButton, pos=_vp(view4, _QP2(note1.pos().x() + 60, note1.pos().y() + 40)))
app.processEvents()
check("double-click enters edit mode", note1.editing is True)
ed = note1.widget()
from PySide6.QtCore import Qt as _Qt2
check("edit mode: editor focus policy becomes StrongFocus", ed.focusPolicy() == _Qt2.FocusPolicy.StrongFocus)
note1.exit_edit_mode()
check("exit_edit_mode restores NoFocus", note1.editing is False and ed.focusPolicy() == _Qt2.FocusPolicy.NoFocus)

# Text change -> signal (только после добавления в сцену)
dirty_hits = []
note1.textEdited.connect(lambda *_a: dirty_hits.append(1))
ed.setPlainText("changed")
check("editor textChanged emits note.textEdited", len(dirty_hits) == 1, str(dirty_hits))

# Delete-клавиша удаляет выделенную заметку через MainWindow._remove_note
note1.setSelected(True)
from PySide6.QtGui import QKeyEvent as _QKE
view4.keyPressEvent(_QKE(_QEv2.Type.KeyPress, _Qt.Key_Delete, _Qt.NoModifier))  # Qt.Key_Delete (0x0100007 в Qt 6.11 — не хардкод!)
check("Delete key removes selected note via window", len(win4.scene._notes) == 1 and win4.scene.get_note_by_id(note1.note_id) is None)

# JSON round-trip: save с заметками -> load -> backward-compat без ключа notes
win4._add_note_at(_QP2(300, 300))  # через MainWindow (сигналы подключены)
check("_add_note_at creates note via window", len(win4.scene._notes) == 2)
added = win4.scene._notes[-1]
win4._mark_dirty()  # заметка добавлена — проект dirty (как в реальном потоке)
# текст для round-trip: правим через редактор (сигнал textEdited сработает сам)
added.widget().setPlainText("roundtrip")
p_notes = os.path.join(WORK, "save_v072.json")
okn = win4._do_save(p_notes)
with open(p_notes, encoding="utf-8") as f:
    jn = json.load(f)
check("saved JSON contains notes array with 2 entries", okn and len(jn.get("notes", [])) == 2, str(jn.get("notes")))
ids_saved = {n["id"] for n in jn["notes"]}
# Загрузка в новое окно через _import_project_raw (backward-compat: старый файл без "notes")
win5 = MW.MainWindow()
win5._import_project_raw(json.load(open(p_notes, encoding="utf-8")))
check("reload restores both notes (same ids)",
      len(win5.scene._notes) == 2 and {n.note_id for n in win5.scene._notes} == ids_saved,
      str([(n.note_id, n.text()) for n in win5.scene._notes]))
check("note text round-trips through JSON", any(n.text() == "roundtrip" for n in win5.scene._notes))
win6 = MW.MainWindow()
old_raw = {"version": "0.7", "servers": [], "connections": []}  # без ключа notes
win6._import_project_raw(old_raw)
check("v0.7 project without 'notes' key loads fine (backward-compat)", len(win6.scene._notes) == 0)

finish()
