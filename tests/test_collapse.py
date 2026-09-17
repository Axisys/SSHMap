# -*- coding: utf-8 -*-
"""Server card collapsing v0.8.4 (former DESIGN.md §D) (former tests/smoke_collapse.py).

The items declared in the design are checked:
  1. toggle_collapsed changes the boundingRect (the height → COLLAPSED_HEIGHT and back);
  2. the JSON round-trip keeps the collapsed (server_data_to_dict / server_data_from_dict);
  3. the old JSON without the collapsed key → the node is expanded;
  4. update_appearance is idempotent in both the modes;
  5. the mousePressEvent on the chevron toggles the mode (QTest.mousePress — the output of v0.7.3).

Run: python tests/test_collapse.py   (from the project root) or python tests/run_all.py
"""
import json

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtWidgets import QApplication, QGraphicsSceneMouseEvent
from PySide6.QtCore import QPointF, Qt

app = QApplication.instance() or QApplication([])

from models.server import ServerData, server_data_from_dict, server_data_to_dict
from graphics.server_node import ServerNode


# ── 1. the toggle changes the boundingRect ────────────────────────────────────────────
data = ServerData(id="t1", alias="web", user="u", host="10.0.0.5", cpu="4", ram="8G")
node = ServerNode(data)
h_expanded = node.boundingRect().height()
node.toggle_collapsed()
h_collapsed = node.boundingRect().height()
check("toggle: the height is reduced to COLLAPSED_HEIGHT",
      abs(h_collapsed - (ServerNode.COLLAPSED_HEIGHT + ServerNode.SHADOW_BOTTOM)) < 0.5,
      f"got {h_collapsed}")
check("toggle: the original height was MIN_NODE_HEIGHT + the shadow",
      abs(h_expanded - (ServerNode.MIN_NODE_HEIGHT + ServerNode.SHADOW_BOTTOM)) < 0.5,
      f"got {h_expanded}")
check("toggle: the data switched",
      node.data.collapsed is True)
node.toggle_collapsed()
check("toggle back: the height is restored",
      abs(node.boundingRect().height() - h_expanded) < 0.5)

# ── 2. The JSON round-trip preserves collapsed ──────────────────────────────────
data2 = ServerData(id="t2", alias="db", user="u", host="10.0.0.6", collapsed=True)
d = server_data_to_dict(data2)
check("to_dict contains collapsed=true", d.get("collapsed") is True)
back = server_data_from_dict(json.loads(json.dumps(d)))
check("round-trip: collapsed survived the serialization", back.collapsed is True)

# ── 3. an old JSON without the key → expanded ────────────────────────────────────
old = {"id": "t3", "alias": "legacy", "host": "10.0.0.7", "x": 1.0, "y": 2.0}
back_old = server_data_from_dict(old)
check("an old JSON without the key → collapsed=False (expanded)", back_old.collapsed is False)

# ── 4. the idempotence of update_appearance in both modes ────────────────────
w1, h1 = node._current_width, node._current_height
node.update_appearance()
check("update_appearance is idempotent (expanded)",
      (node._current_width, node._current_height) == (w1, h1))
node.toggle_collapsed()
w2, h2 = node._current_width, node._current_height
node.update_appearance()
check("update_appearance is idempotent (collapsed)",
      (node._current_width, node._current_height) == (w2, h2))

# ── 5. the chevron click: a synthetic QGraphicsSceneMouseEvent ───────────────
# (the v0.7.3 note: mouse input in tests; QTest.mousePress accepts only QWidget,
# for a QGraphicsItem we assemble the event by hand)

def _press_at(item, local: QPointF):
    """The synthetic click: QTest.mousePress accepts only a QWidget, and
    QGraphicsItem.sceneEvent() outside the scene does not dispatch the mouse — therefore
    mousePressEvent() is called directly (the event is assembled manually)."""
    ev = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.Type.MouseButtonPress)
    ev.setButton(Qt.MouseButton.LeftButton)
    ev.setButtons(Qt.MouseButton.LeftButton)
    ev.setScenePos(local)   # the item is not added to the scene → scene==item coordinates
    ev.setPos(local)
    ev.setModifiers(Qt.KeyboardModifier.NoModifier)
    ev.setAccepted(False)
    item.mousePressEvent(ev)
    return ev.isAccepted()

node3 = ServerNode(ServerData(id="t4", alias="srv", user="u", host="10.0.0.8"))
before = node3.data.collapsed
_press_at(node3, node3.chevron_rect().center())
check("a click on the chevron toggles the mode",
      node3.data.collapsed != before)  # isAccepted() on a synthetic event is unreliable
_press_at(node3, node3.chevron_rect().center())
check("a second click restores the mode", node3.data.collapsed == before)
# a click missing the chevron must not toggle
_press_at(node3, QPointF(60, 60))
check("a click missing the chevron does not toggle the mode", node3.data.collapsed == before)

finish()
