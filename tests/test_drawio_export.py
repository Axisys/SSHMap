# -*- coding: utf-8 -*-
"""Map export to drawio (.drawio) v0.9.5 (former tests/smoke_v095_drawio.py).

Checks (DOCUMENTATION.md v0.9.5 #6):
  1. The round-trip of the structure of the XML: the nodes / the connections / the groups / the notes / the background.
  2. The file opens by the XML validator (ET.parse).
  3. The coordinates of the members of the groups are recalculated relative to the parent.

v1.3.3.7 (ROADMAP task 4): the structure counting is done INLINE here — the module's
`load_drawio_structure()` was deleted as production-dead (see CHANGELOG.md, v1.3.3.7),
so `count_structure()` below is the same `ET.iter("mxCell")` scan the helper used.

Run: python tests/test_drawio_export.py   (from the project root) or python tests/run_all.py
"""
import os
import xml.etree.ElementTree as ET

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from models.server import ServerData
from graphics.map_scene import MapScene
from storage.export_drawio import export_scene_to_drawio


def find_cells(root):
    cells = {}
    for c in root.iter("mxCell"):
        cells[c.get("id")] = c
    return cells


def count_structure(root):
    """The vertex/edge/note/container counters (the deleted load_drawio_structure scan)."""
    vertices = edges = notes = containers = 0
    for cell in root.iter("mxCell"):
        style = cell.get("style") or ""
        if cell.get("edge") == "1":
            edges += 1
        elif cell.get("vertex") == "1":
            if "shape=note" in style:
                notes += 1
            elif "container=1" in style:
                containers += 1
            else:
                vertices += 1
    return {"vertices": vertices, "edges": edges,
            "notes": notes, "containers": containers}


scene = MapScene()

# The nodes: two free + one inside a group
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
note = scene.add_note("Check the backups", x=600, y=50)
check("the note is added to the scene", note is not None and bool(scene.notes()))
group = scene.add_group("prod", x=50, y=50, width=400, height=300)
group.add_member(n3)

path = os.path.join(WORK, "test_drawio_export.drawio")
cells_n = export_scene_to_drawio(scene, path)
check("the export returns the cell count", isinstance(cells_n, int) and cells_n > 0, f"got {cells_n!r}")

# ── 1. A valid XML ───────────────────────────────────────────────────────────
try:
    tree = ET.parse(path)  # will throw a ParseError on a corrupt structure
    root = tree.getroot()
except ET.ParseError as e:
    check("the XML is valid (ET.parse)", False, str(e))
    finish()
check("the root tag == mxfile", root.tag == "mxfile", f"got {root.tag!r}")

cells = find_cells(root)
stats = count_structure(root)

# ── 2. The structure: 3 node corners + 1 sticker; 1 container; 1 edge ───────────
check("vertices == 3 (n1, n2, the group member)", stats.get("vertices") == 3, str(stats))
check("notes == 1", stats.get("notes") == 1, str(stats))
check("containers == 1", stats.get("containers") == 1, str(stats))
check("edges == 1", stats.get("edges") == 1, str(stats))

edge = next((c for c in cells.values() if c.get("edge") == "1"), None)
check("the edge cell exists", edge is not None)
if edge is not None:
    src_cell = cells.get(edge.get("source"))
    dst_cell = cells.get(edge.get("target"))
    check("the edge ends exist", src_cell is not None and dst_cell is not None)
    check("the connection type color is applied (a78bfa)", "a78bfa" in (edge.get("style") or ""))

# ── 3. The member coordinates relative to the parent + the parent = the container ──────
member_id = next((k for k in cells if k.endswith("-member-0")), None)
group_id = next((k for k in cells
                 if k.startswith("group-") and not k.endswith("-member-0")), None)
check("the group cell exists", group_id is not None, str(sorted(cells)))
check("the group member cell exists", member_id is not None)
if member_id is not None and group_id is not None:
    geom = cells[member_id].find("mxGeometry")
    # A group member must be a child cell of the container (xml-reference §Containers)
    check("the member's parent == the container", cells[member_id].get("parent") == group_id,
          f"got {cells[member_id].get('parent')!r}")
    gx = float(cells[group_id].find("mxGeometry").get("x"))
    gy = float(cells[group_id].find("mxGeometry").get("y"))
    mx = float(geom.get("x"))
    my = float(geom.get("y"))
    expected_x = round(float(n3.pos().x()) - gx, 2)
    expected_y = round(float(n3.pos().y()) - gy, 2)
    check("the member's coordinates are relative to the parent",
          abs(mx - expected_x) < 0.51 and abs(my - expected_y) < 0.51,
          f"({mx},{my}) vs ({expected_x},{expected_y})")

# ── 4. The node text contains the alias and the host; the line break — &#xa; ───────────────
node_cell = next((c for c in cells.values()
                  if (c.get("value") or "").startswith("web-01")), None)
check("the node cell web-01 exists", node_cell is not None)
if node_cell is not None:
    check("the label contains the @host", "@10.0.0.11" in (node_cell.get("value") or ""))
    check("the label contains the OS line", "Ubuntu 24.04" in (node_cell.get("value") or ""))
    check("the style contains html=1", "html=1" in (node_cell.get("style") or ""))
raw = open(path, encoding="utf-8").read()
check("the line break is encoded as &#xa; in the file", "&#xa;" in raw)

# ── 5. The layers in the right order, hanging on the root (parent="0") ────────────────
layer_ids = [c.get("id") for c in cells.values()
             if str(c.get("id", "")).startswith("layer-")]
check("the layers are in the order background→groups→map",
      layer_ids == ["layer-background", "layer-groups", "layer-map"], str(layer_ids))
for lid in layer_ids:
    check(f"layer {lid}: parent==0 and not vertex/edge",
          cells[lid].get("parent") == "0"
          and cells[lid].get("vertex") is None and cells[lid].get("edge") is None)

try:
    os.remove(path)
except OSError:
    pass  # WORK is still wiped by the bootstrap on the next run

finish()
