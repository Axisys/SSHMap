# -*- coding: utf-8 -*-
"""Smoke-тест v0.9.5: экспорт карты в drawio (.drawio).

Проверяет (DOCUMENTATION.md v0.9.5 #6):
  1. Round-trip структуры XML: узлы / связи / группы / заметки / фон.
  2. Файл открывается валидатором XML (ET.parse).
  3. Координаты членов групп пересчитаны относительно parent.
Запуск из корня репозитория: python tests/smoke_v095_drawio.py
"""
import os
import sys
import tempfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF

from models.server import ServerData
from graphics.map_scene import MapScene


def find_cells(root):
    cells = {}
    for c in root.iter("mxCell"):
        cells[c.get("id")] = c
    return cells


def main():
    app = QApplication.instance() or QApplication([])
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
    assert note is not None and scene.notes(), "sticker not added"
    group = scene.add_group("prod", x=50, y=50, width=400, height=300)
    group.add_member(n3)

    from storage.export_drawio import (
        export_scene_to_drawio, load_drawio_structure)

    path = os.path.join(tempfile.gettempdir(), "sshmap_smoke_v095.drawio")
    cells_n = export_scene_to_drawio(scene, path)
    print(f"exported cells (containers only): {cells_n}")

    # 1. Валидный XML
    tree = ET.parse(path)  # бросит ParseError при битой структуре
    root = tree.getroot()
    assert root.tag == "mxfile", f"root tag: {root.tag}"
    print("XML parses OK")

    cells = find_cells(root)
    stats = load_drawio_structure(path)
    print("structure:", stats)

    # 2. Структура: 3 вершины узлов + 1 стикер; 1 контейнер; 1 ребро;
    #    член группы — дочерняя ячейка контейнера
    assert stats["vertices"] == 3, stats   # n1, n2, member(n3)
    assert stats["notes"] == 1, stats
    assert stats["containers"] == 1, stats
    assert stats["edges"] == 1, stats
    edge = next(c for c in cells.values() if c.get("edge") == "1")
    src_cell = cells.get(edge.get("source"))
    dst_cell = cells.get(edge.get("target"))
    assert src_cell is not None and dst_cell is not None, "edge endpoints missing"
    assert "a78bfa" in (edge.get("style") or ""), \
        "connection type color not applied"
    print("edges/labels/types OK")

    # 3. Координаты члена группы относительно parent + parent = контейнер
    member_id = next(k for k in cells if k.endswith("-member-0"))
    geom = cells[member_id].find("mxGeometry")
    group_id = next(k for k in cells
                    if k.startswith("group-") and not k.endswith("-member-0"))
    # Член группы обязан быть дочерней ячейкой контейнера (xml-reference §Containers)
    assert cells[member_id].get("parent") == group_id, \
        cells[member_id].get("parent")
    gx = float(cells[group_id].find("mxGeometry").get("x"))
    gy = float(cells[group_id].find("mxGeometry").get("y"))
    mx = float(geom.get("x"))
    my = float(geom.get("y"))
    expected_x = round(float(n3.pos().x()) - gx, 2)
    expected_y = round(float(n3.pos().y()) - gy, 2)
    assert abs(mx - expected_x) < 0.51 and abs(my - expected_y) < 0.51, \
        (mx, my, expected_x, expected_y)
    print(f"group-member coords relative to parent OK ({mx},{my})")

    # 4. Текст узла содержит alias и host; перенос строки — &#xa;
    node_cell = next(c for c in cells.values()
                     if (c.get("value") or "").startswith("web-01"))
    assert "@10.0.0.11" in node_cell.get("value"), node_cell.get("value")
    assert "Ubuntu 24.04" in node_cell.get("value"), "OS line missing"
    raw = open(path, encoding="utf-8").read()
    assert "&#xa;" in raw, "line break must be encoded as &#xa; in file"
    assert "html=1" in (node_cell.get("style") or ""), "html=1 required"
    print("node label content OK")

    # 5. Слои присутствуют в правильном порядке и висят на root (parent="0")
    layer_ids = [c.get("id") for c in cells.values() if str(c.get("id", "")).startswith("layer-")]
    assert layer_ids == ["layer-background", "layer-groups", "layer-map"], layer_ids
    for lid in layer_ids:
        assert cells[lid].get("parent") == "0", (lid, cells[lid].get("parent"))
        assert cells[lid].get("vertex") is None and cells[lid].get("edge") is None
    print("layers OK:", layer_ids)

    os.remove(path)
    print("\nSMOKE v0.9.5 PASSED")


if __name__ == "__main__":
    main()
