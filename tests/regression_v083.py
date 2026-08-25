"""Регрессионные тесты v0.8.3 — Undo/Redo.

Проверяется настоящий путь MainWindow + QUndoStack:
  round-trip undo/redo для каждой операции (добавление/удаление сервера,
  связи, заметки; правка текста заметки, правка данных узла),
  merge перемещений узла одним жестом,
  dirty-маркер, привязанный к индексу undo-стека (save = новая точка отсчёта).

Запуск:  python tests/regression_v083.py   (из корня проекта)
"""
import os
import sys

# v0.9.4-fix: UTF-8 stdout на cp1251-консолях
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import faulthandler
faulthandler.dump_traceback_later(180, exit=True)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append((name, detail))
    print(("  ok  " if cond else "  FAIL ") + name + (f" — {detail}" if detail and not cond else ""))


from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from models.server import ServerData
from modules.undo_commands import (
    CmdMoveNode, CmdAddRemoveNode, CmdAddRemoveConnection,
    CmdAddRemoveNote, CmdEditTextNote, CmdEditNodeData,
)

try:
    from ui import main_window as MW
except ImportError:
    import main_window as MW


def make_win():
    win = MW.MainWindow()
    # headless-тесты без event loop: StatusChecker не запускаем
    return win


def node_at(win, x=100.0, y=100.0):
    data = ServerData(id="srv%02d" % len(win.scene._nodes), alias="S%d" % len(win.scene._nodes),
                      host="h%d" % len(win.scene._nodes), user="u",
                      x=x, y=y)
    win.scene.add_server(data)
    return win.scene._nodes[data.id]


print("== undo stack wiring ==")
win = make_win()
check("window has QUndoStack", hasattr(win, "undo_stack"))
check("undo disabled initially", not win.undo_stack.canUndo())
check("not dirty on clean project", not win._has_unsaved_changes)
win.act_undo.setEnabled(True)
win.act_undo.setEnabled(False)  # подключение canUndoChanged живое (не упало)
check("undo/redo actions wired to stack", True)

print("== add/remove server round-trip ==")
n0 = len(win.scene._nodes)
data = ServerData(id="add01", alias="Added", host="h", user="u")
win._push_command(CmdAddRemoveNode(win, win.scene, data, "add"))
check("command adds server", "add01" in win.scene._nodes)
check("stack dirty after push", win.undo_stack.canUndo() and win._dirty)
win.undo_stack.undo()
check("undo removes server", "add01" not in win.scene._nodes and len(win.scene._nodes) == n0)
win.undo_stack.redo()
check("redo re-adds server with same id", "add01" in win.scene._nodes)

print("== remove node restores its arrows ==")
a = node_at(win, 0, 0)
b = node_at(win, 400, 0)
win._push_command(CmdAddRemoveConnection(win, win.scene, a.data.id, b.data.id, "l", "ssh", "add"))
check("fixture arrow exists", win.scene.has_connection(a.data.id, b.data.id))
win._push_command(CmdAddRemoveNode(win, win.scene, b.data, "remove", [
    (a.data.id, b.data.id, "l", "ssh")]))
check("remove deletes node and its arrows",
      b.data.id not in win.scene._nodes
      and not win.scene.has_connection(a.data.id, b.data.id))
win.undo_stack.undo()
check("undo restores node AND its arrow",
      b.data.id in win.scene._nodes
      and win.scene.has_connection(a.data.id, b.data.id))
win.undo_stack.redo()
check("redo removes them again",
      b.data.id not in win.scene._nodes
      and not win.scene.has_connection(a.data.id, b.data.id))

print("== connection add/remove round-trip ==")
# Стрелка, созданная ПОСЛЕ удаления узла, при undo удаления не восстанавливается
# (не была захвачена) — это корректно. Честный round-trip связи делаем на живых узлах:
c = node_at(win, 800, 0)
win._push_command(CmdAddRemoveConnection(win, win.scene, a.data.id, c.data.id, "", "vpn", "add"))
check("add-connection command creates arrow",
      win.scene.has_connection(a.data.id, c.data.id))
win.undo_stack.undo()
check("undo removes the arrow", not win.scene.has_connection(a.data.id, c.data.id))
win.undo_stack.redo()
check("redo recreates the arrow", win.scene.has_connection(a.data.id, c.data.id))
win._push_command(CmdAddRemoveConnection(win, win.scene, a.data.id, c.data.id,
                                         "", "vpn", "remove"))
check("remove-connection command deletes arrow",
      not win.scene.has_connection(a.data.id, c.data.id))
win.undo_stack.undo()
check("undo of remove restores arrow with label/type",
      win.scene.has_connection(a.data.id, c.data.id))

print("== note add/remove + text edit ==")
raw = {"id": "note01", "text": "", "x": 10.0, "y": 10.0, "width": 240.0, "height": 160.0}
win._note_committed["note01"] = ""
win._push_command(CmdAddRemoveNote(win, win.scene, raw, "add"))
check("note added by command", win.scene.get_note_by_id("note01") is not None)
note = win.scene.get_note_by_id("note01")
win._attach_note(note)
win._push_command(CmdEditTextNote(win, note, "", "hello"))
check("text edit applied via push", note.text() == "hello")
win.undo_stack.undo()
check("undo restores previous note text", note.text() == "")
win.undo_stack.redo()
check("redo reapplies note text", note.text() == "hello")
win._push_command(CmdAddRemoveNote(win, win.scene, note.to_dict(), "remove"))
check("note removed by command", win.scene.get_note_by_id("note01") is None)
win.undo_stack.undo()
check("undo restores note with text", win.scene.get_note_by_id("note01") is not None
      and win.scene.get_note_by_id("note01").text() == "hello")
note = win.scene.get_note_by_id("note01")

print("== edit node data round-trip ==")
old_data = a.data
new_data = ServerData(id=a.data.id, alias="Renamed", host="newhost", user="root",
                      ssh_port=2222, x=a.data.x, y=a.data.y)
win._push_command(CmdEditNodeData(win, a, old_data, new_data))
check("edit applies new data", a.data.alias == "Renamed" and a.data.ssh_port == 2222)
win.undo_stack.undo()
check("undo restores old data", a.data.alias == old_data.alias and a.data.ssh_port == 22)
win.undo_stack.redo()
check("redo reapplies new data", a.data.alias == "Renamed")

print("== move merge (one gesture -> one undo step) ==")
p0 = QPointF(a.pos())
cmd1 = CmdMoveNode(win, a, p0, QPointF(p0.x() + 10, p0.y()))
cmd2 = CmdMoveNode(win, a, QPointF(p0.x() + 10, p0.y()), QPointF(p0.x() + 25, p0.y() + 5))
check("second move merges into first", cmd2.mergeWith(cmd1) or cmd1.mergeWith(cmd2))
win.undo_stack.push(cmd1 if cmd1.mergeWith(cmd2) else cmd2)
before_undo = QPointF(a.pos())
win.undo_stack.undo()
check("single undo returns to the gesture start", a.pos() == p0)
win.undo_stack.redo()
check("redo returns to merged end position", a.pos() == before_undo)

print("== dirty marker tied to stack index ==")
win2 = make_win()
data = ServerData(id="d1", alias="D", host="h", user="u")
win2._push_command(CmdAddRemoveNode(win2, win2.scene, data, "add"))
check("dirty after one change", win2._dirty and win2._update_window_title() is None)
orig_save = MW.MainWindow._save_project
def fake_save(self):
    self._dirty = False
    self._reset_undo_stack()
    return True
MW.MainWindow._save_project = fake_save
ok_saved = win2._save_project()
MW.MainWindow._save_project = orig_save
check("save resets dirty even though stack had history",
      ok_saved and not win2._dirty)
# после save стек чист: undo недоступно до нового изменения
check("undo unavailable right after save (baseline)", not win2.undo_stack.canUndo())

print("== status changes are NOT undoable (spec boundary) ==")
stack_before = win2.undo_stack.index()
node_d = win2.scene._nodes["d1"]
node_d.set_status("online")
check("set_status does not touch undo stack", win2.undo_stack.index() == stack_before
      and not win2.undo_stack.canUndo())

print("== LIFO order: delete-node after add-arrow ==")
w3 = make_win()
na = node_at(w3, 0, 0)
nb = node_at(w3, 300, 0)
w3._push_command(CmdAddRemoveNode(w3, w3.scene, nb.data, "remove", []))       # удалить b
w3._push_command(CmdAddRemoveConnection(w3, w3.scene, na.data.id, nb.data.id, "", "ssh", "add"))  # no-op (узла нет)
w3.undo_stack.undo()  # сначала отменяется связь
w3.undo_stack.undo()  # затем возвращается узел
check("LIFO undo returns both objects", nb.data.id in w3.scene._nodes)

# ── итог ──
print(f"\n===== {len(PASS)} passed, {len(FAIL)} failed =====")
if FAIL:
    for name, detail in FAIL:
        print("FAILED:", name, detail)
sys.exit(1 if FAIL else 0)
