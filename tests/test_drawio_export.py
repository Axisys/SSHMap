# -*- coding: utf-8 -*-
"""Экспорт карты в drawio (.drawio) v0.9.5 (бывш. tests/smoke_v095_drawio.py).

Проверяет (DOCUMENTATION.md v0.9.5 #6):
  1. Round-trip структуры XML: узлы / связи / группы / заметки / фон.
  2. Файл открывается валидатором XML (ET.parse).
  3. Координаты членов групп пересчитаны относительно parent.

Запуск: python tests/test_drawio_export.py   (из корня проекта) или python tests/run_all.py
"""
import os
import xml.etree.ElementTree as ET

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from models.server import ServerData
from graphics.map_scene import MapScene
from storage.export_drawio import export_scene_to_drawio, load_drawio_structure


def find_cells(root):
    cells = {}
    for c in root.iter("mxCell"):
        cells[c.get("id")] = c
    return cells


scene = MapScene()

# Узлы: два свободных + один внутри группы
n1 = scene.add_server(ServerData(
    id="srv1", alias="web-01", host="10.0.0.11", user="ubuntu",
    x=700, y=80, cpu="2", ram="4GB", ip="10.0.0.11", os_name="Ubuntu 24.04"))
n2 = scene.add_server(ServerData(
    id="srv2", alias="db-01", host="10.0.0.12", user="ubuntu",
    x=700, y=350))
n3 = scene.add_server(ServerData(
    id="srv3", alias="cache-01", host="10.0.0.13", user="ubuntu",
    x=120, y=160))
scene.add_connection("srv1", "srv2", label="replication", ctype="database")
note = scene.add_note("Проверить бэкапы", x=600, y=50)
check("стикер добавлен в сцену", note is not None and bool(scene.notes()))
group = scene.add_group("prod", x=50, y=50, width=400, height=300)
group.add_member(n3)

path = os.path.join(WORK, "test_drawio_export.drawio")
cells_n = export_scene_to_drawio(scene, path)
check("экспорт вернул число ячеек", isinstance(cells_n, int) and cells_n > 0, f"got {cells_n!r}")

# ── 1. Валидный XML ───────────────────────────────────────────────────────────
try:
    tree = ET.parse(path)  # бросит ParseError при битой структуре
    root = tree.getroot()
except ET.ParseError as e:
    check("XML валиден (ET.parse)", False, str(e))
    finish()
check("корневой тег == mxfile", root.tag == "mxfile", f"got {root.tag!r}")

cells = find_cells(root)
stats = load_drawio_structure(path)

# ── 2. Структура: 3 вершины узлов + 1 стикер; 1 контейнер; 1 ребро ───────────
check("vertices == 3 (n1, n2, член группы)", stats.get("vertices") == 3, str(stats))
check("notes == 1", stats.get("notes") == 1, str(stats))
check("containers == 1", stats.get("containers") == 1, str(stats))
check("edges == 1", stats.get("edges") == 1, str(stats))

edge = next((c for c in cells.values() if c.get("edge") == "1"), None)
check("ячейка ребра существует", edge is not None)
if edge is not None:
    src_cell = cells.get(edge.get("source"))
    dst_cell = cells.get(edge.get("target"))
    check("концы ребра существуют", src_cell is not None and dst_cell is not None)
    check("цвет типа связи применён (a78bfa)", "a78bfa" in (edge.get("style") or ""))

# ── 3. Координаты члена группы относительно parent + parent = контейнер ──────
member_id = next((k for k in cells if k.endswith("-member-0")), None)
group_id = next((k for k in cells
                 if k.startswith("group-") and not k.endswith("-member-0")), None)
check("ячейка группы существует", group_id is not None, str(sorted(cells)))
check("ячейка члена группы существует", member_id is not None)
if member_id is not None and group_id is not None:
    geom = cells[member_id].find("mxGeometry")
    # Член группы обязан быть дочерней ячейкой контейнера (xml-reference §Containers)
    check("parent члена == контейнер", cells[member_id].get("parent") == group_id,
          f"got {cells[member_id].get('parent')!r}")
    gx = float(cells[group_id].find("mxGeometry").get("x"))
    gy = float(cells[group_id].find("mxGeometry").get("y"))
    mx = float(geom.get("x"))
    my = float(geom.get("y"))
    expected_x = round(float(n3.pos().x()) - gx, 2)
    expected_y = round(float(n3.pos().y()) - gy, 2)
    check("координаты члена относительно parent",
          abs(mx - expected_x) < 0.51 and abs(my - expected_y) < 0.51,
          f"({mx},{my}) vs ({expected_x},{expected_y})")

# ── 4. Текст узла содержит alias и host; перенос строки — &#xa; ───────────────
node_cell = next((c for c in cells.values()
                  if (c.get("value") or "").startswith("web-01")), None)
check("ячейка узла web-01 существует", node_cell is not None)
if node_cell is not None:
    check("метка содержит @host", "@10.0.0.11" in (node_cell.get("value") or ""))
    check("метка содержит строку OS", "Ubuntu 24.04" in (node_cell.get("value") or ""))
    check("style содержит html=1", "html=1" in (node_cell.get("style") or ""))
raw = open(path, encoding="utf-8").read()
check("перенос строки закодирован как &#xa; в файле", "&#xa;" in raw)

# ── 5. Слои в правильном порядке и висят на root (parent="0") ────────────────
layer_ids = [c.get("id") for c in cells.values()
             if str(c.get("id", "")).startswith("layer-")]
check("слои в порядке background→groups→map",
      layer_ids == ["layer-background", "layer-groups", "layer-map"], str(layer_ids))
for lid in layer_ids:
    check(f"слой {lid}: parent==0 и не vertex/edge",
          cells[lid].get("parent") == "0"
          and cells[lid].get("vertex") is None and cells[lid].get("edge") is None)

try:
    os.remove(path)
except OSError:
    pass  # WORK всё равно сносится bootstrap'ом на следующем прогоне

finish()
