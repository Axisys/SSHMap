"""Sticky notes: drag/resize/edit/delete + JSON round-trip (former smoke_test.py §6e "v0.7.2").

A part of the suite split out of smoke_test.py v0.6–v0.9.2 (see INDEX.md).
  * creation + serialization (to_dict/from_dict, broken values → the defaults);
  * the size clamp MIN/MAX;
  * the mouse drag through the FULL pipeline view→scene→item (QTest input): MapView itself
    switches to NoDrag on the press over a note; the moved signal on the release;
  * the resize by the bottom-right corner; the edit mode on the double click (the focus policy);
  * textChanged → note.textEdited; the Delete key via MainWindow._remove_note;
  * the JSON round-trip + the backward-compat of an old project without the "notes" key.

Run: python tests/test_notes.py   (from the project root) or python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish, viewport_point as _vp

ROOT, WORK = bootstrap()  # BEFORE the app module imports

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

# Creation + serialization
note1 = win4.scene.add_note(text="hello", x=50.0, y=60.0)
check("scene.add_note creates StickyNote in _notes", len(win4.scene._notes) == 1 and note1 is win4.scene._notes[0])
d1 = note1.to_dict()
check("note to_dict has id/text/x/y/width/height",
      set(d1.keys()) == {"id", "text", "x", "y", "width", "height"} and d1["text"] == "hello"
      and len(d1["id"]) == 8, str(d1))

# from_dict: corrupt values — the defaults, extra keys are ignored
n_bad = _SN2.from_dict({"x": "garbage", "width": None, "extra_key": 1})
check("note from_dict survives bad values (defaults)", n_bad.pos().x() == 0.0 and n_bad.rect().width() >= _SN2.MIN_W)

# The size: the clamp MIN/MAX
n_cl = win4.scene.add_note(x=800, y=400)
n_cl.set_note_size(10, 5)
check("note size clamped to MIN", n_cl.rect().width() == _SN2.MIN_W and n_cl.rect().height() == _SN2.MIN_H)
n_cl.set_note_size(9999, 9999)
check("note size clamped to MAX", n_cl.rect().width() == _SN2.MAX_W and n_cl.rect().height() == _SN2.MAX_H)

# A mouse drag of a note through the FULL pipeline view->scene->item (QTest input, see the v0.7 section):
# MapView switches NoDrag itself on a press over a note (the dynamic mode).
view4 = win4.view
check("drag mode is ScrollHandDrag before press over note", view4.dragMode() == _QGV2.DragMode.ScrollHandDrag)

vp4 = view4.viewport()   # QTest sends events to the viewport — the standard Qt routing path

moved_signals = []
note1.moved.connect(lambda: moved_signals.append(1))
p0 = _QP2(note1.pos().x() + 80, note1.pos().y() + 50)   # the body of the note (not the corner!)
pos_before = (note1.pos().x(), note1.pos().y())          # the offset: the note is shifted by DELTA
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

# A resize by the bottom-right corner: press in the corner -> move outward -> the size grows
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

# Edit mode: a double click via QTest — a REAL QGraphicsSceneMouseEvent (the handler may
# forward it to QTextEdit via super(); the fake duck-typed event fell on the C++ method).
check("note not in edit mode initially", note1.editing is False)
_QTest.mouseDClick(vp4, _Qt.LeftButton, pos=_vp(view4, _QP2(note1.pos().x() + 60, note1.pos().y() + 40)))
app.processEvents()
check("double-click enters edit mode", note1.editing is True)
ed = note1.widget()
from PySide6.QtCore import Qt as _Qt2
check("edit mode: editor focus policy becomes StrongFocus", ed.focusPolicy() == _Qt2.FocusPolicy.StrongFocus)
note1.exit_edit_mode()
check("exit_edit_mode restores NoFocus", note1.editing is False and ed.focusPolicy() == _Qt2.FocusPolicy.NoFocus)

# A text change -> a signal (only after adding to the scene)
dirty_hits = []
note1.textEdited.connect(lambda *_a: dirty_hits.append(1))
ed.setPlainText("changed")
check("editor textChanged emits note.textEdited", len(dirty_hits) == 1, str(dirty_hits))

# The Delete key removes the selected note via MainWindow._remove_note
note1.setSelected(True)
from PySide6.QtGui import QKeyEvent as _QKE
view4.keyPressEvent(_QKE(_QEv2.Type.KeyPress, _Qt.Key_Delete, _Qt.NoModifier))  # Qt.Key_Delete (0x0100007 in Qt 6.11 — no hardcoding!)
check("Delete key removes selected note via window", len(win4.scene._notes) == 1 and win4.scene.get_note_by_id(note1.note_id) is None)

# A JSON round-trip: a save with notes -> load -> backward-compat without the notes key
win4._add_note_at(_QP2(300, 300))  # via MainWindow (the signals are connected)
check("_add_note_at creates note via window", len(win4.scene._notes) == 2)
added = win4.scene._notes[-1]
win4._mark_dirty()  # the note is added — the project is dirty (as in the real flow)
# the text for the round-trip: we edit it via the editor (the textEdited signal fires on its own)
added.widget().setPlainText("roundtrip")
p_notes = os.path.join(WORK, "save_v072.json")
okn = win4._do_save(p_notes)
with open(p_notes, encoding="utf-8") as f:
    jn = json.load(f)
check("saved JSON contains notes array with 2 entries", okn and len(jn.get("notes", [])) == 2, str(jn.get("notes")))
ids_saved = {n["id"] for n in jn["notes"]}
# Loading into a new window via _import_project_raw (backward-compat: an old file without "notes")
win5 = MW.MainWindow()
win5._import_project_raw(json.load(open(p_notes, encoding="utf-8")))
check("reload restores both notes (same ids)",
      len(win5.scene._notes) == 2 and {n.note_id for n in win5.scene._notes} == ids_saved,
      str([(n.note_id, n.text()) for n in win5.scene._notes]))
check("note text round-trips through JSON", any(n.text() == "roundtrip" for n in win5.scene._notes))
win6 = MW.MainWindow()
old_raw = {"version": "0.7", "servers": [], "connections": []}  # without the notes key
win6._import_project_raw(old_raw)
check("v0.7 project without 'notes' key loads fine (backward-compat)", len(win6.scene._notes) == 0)

finish()
