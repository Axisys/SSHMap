# -*- coding: utf-8 -*-
"""v0.8.4 (DESIGN.md §D): smoke-тесты сворачивания плашек серверов.

Проверяются пункты, заявленные в дизайне:
  1. toggle_collapsed меняет boundingRect (высота → COLLAPSED_HEIGHT и обратно);
  2. JSON round-trip сохраняет collapsed (server_data_to_dict / server_data_from_dict);
  3. старый JSON без ключа collapsed → узел развёрнут;
  4. update_appearance идемпотентен в обоих режимах;
  5. mousePressEvent по шеврону переключает режим (QTest.mousePress — вывод v0.7.3).
Запуск: python tests/smoke_collapse.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv)

from models.server import ServerData, server_data_from_dict, server_data_to_dict
try:
    from graphics.server_node import ServerNode
except ImportError:
    from graphics.server_node import ServerNode

_results = []


def check(name, cond, detail=""):
    _results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))


# ── 1. toggle меняет boundingRect ────────────────────────────────────────────
data = ServerData(id="t1", alias="web", user="u", host="10.0.0.5", cpu="4", ram="8G")
node = ServerNode(data)
h_expanded = node.boundingRect().height()
node.toggle_collapsed()
h_collapsed = node.boundingRect().height()
check("toggle: высота уменьшилась до COLLAPSED_HEIGHT",
      abs(h_collapsed - (ServerNode.COLLAPSED_HEIGHT + ServerNode.SHADOW_BOTTOM)) < 0.5,
      f"got {h_collapsed}")
check("toggle: исходная высота была MIN_NODE_HEIGHT+тень",
      abs(h_expanded - (ServerNode.MIN_NODE_HEIGHT + ServerNode.SHADOW_BOTTOM)) < 0.5,
      f"got {h_expanded}")
check("toggle: данные переключились",
      node.data.collapsed is True)
node.toggle_collapsed()
check("toggle обратно: высота восстановилась",
      abs(node.boundingRect().height() - h_expanded) < 0.5)

# ── 2. JSON round-trip сохраняет collapsed ──────────────────────────────────
data2 = ServerData(id="t2", alias="db", user="u", host="10.0.0.6", collapsed=True)
d = server_data_to_dict(data2)
check("to_dict содержит collapsed=true", d.get("collapsed") is True)
back = server_data_from_dict(json.loads(json.dumps(d)))
check("round-trip: collapsed пережил сериализацию", back.collapsed is True)

# ── 3. старый JSON без ключа → развёрнут ────────────────────────────────────
old = {"id": "t3", "alias": "legacy", "host": "10.0.0.7", "x": 1.0, "y": 2.0}
back_old = server_data_from_dict(old)
check("старый JSON без ключа → collapsed=False (развёрнут)", back_old.collapsed is False)

# ── 4. идемпотентность update_appearance в обоих режимах ────────────────────
w1, h1 = node._current_width, node._current_height
node.update_appearance()
check("update_appearance идемпотентен (развёрнут)",
      (node._current_width, node._current_height) == (w1, h1))
node.toggle_collapsed()
w2, h2 = node._current_width, node._current_height
node.update_appearance()
check("update_appearance идемпотентен (свёрнут)",
      (node._current_width, node._current_height) == (w2, h2))

# ── 5. клик по шеврону: синтетический QGraphicsSceneMouseEvent ───────────────
# (вывод v0.7.3: мышиный ввод в тестах; QTest.mousePress принимает только QWidget,
# для QGraphicsItem собираем событие вручную)
from PySide6.QtWidgets import QGraphicsSceneMouseEvent

def _press_at(item, local: QPointF):
    """Синтетический клик: QTest.mousePress принимает только QWidget, а
    QGraphicsItem.sceneEvent() вне сцены не диспетчеризует мышь — поэтому
    вызываем mousePressEvent() напрямую (событие собирается вручную)."""
    ev = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.Type.MouseButtonPress)
    ev.setButton(Qt.MouseButton.LeftButton)
    ev.setButtons(Qt.MouseButton.LeftButton)
    ev.setScenePos(local)   # item в сцене не добавлен → scene==item coords
    ev.setPos(local)
    ev.setModifiers(Qt.KeyboardModifier.NoModifier)
    ev.setAccepted(False)
    item.mousePressEvent(ev)
    return ev.isAccepted()

node3 = ServerNode(ServerData(id="t4", alias="srv", user="u", host="10.0.0.8"))
before = node3.data.collapsed
ev = _press_at(node3, node3.chevron_rect().center())
check("клик по шеврону переключает режим",
      node3.data.collapsed != before)  # isAccepted() у синтетического события ненадёжен
_press_at(node3, node3.chevron_rect().center())
check("повторный клик возвращает режим", node3.data.collapsed == before)
# клик мимо шеврона не должен переключать
_press_at(node3, QPointF(60, 60))
check("клик мимо шеврона не переключает режим", node3.data.collapsed == before)

# ── итоги ─────────────────────────────────────────────────────────────────────
failed = [n for n, ok, _ in _results if not ok]
print(f"\n{len(_results) - len(failed)}/{len(_results)} passed")
if failed:
    print("FAILED:", *failed, sep="\n  ")
    sys.exit(1)
