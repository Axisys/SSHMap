# -*- coding: utf-8 -*-
"""Export the map to the draw.io format (.drawio) — v0.9.5, label completed in v1.3.3.7.

An mxGraph XML serializer via xml.etree.ElementTree, no new dependencies.

What is exported:
  - ServerNode      → an mxCell vertex (geometry + alias/host/OS/CPU/RAM text
                      + the tag line + the comment — see _node_label());

  - ConnectionArrow → an mxCell edge source→target with a label and the connection type color;
  - StickyNote      → a vertex with the shape=note style;
  - NodeGroup       → a container (container=1), members — child cells
    with coordinates recomputed relative to the parent (membership is geometric:
    we subtract the group's position);
  - background image → a separate bottom layer (shape=image).

drawio layers (order in the XML = z-order, bottom ones first):
  layer-background → layer-groups → layer-map.

CRITICAL FORMAT REQUIREMENT (confirmed by the mxModelCodec.draw.io code,
decodeRoot: the iteration goes over the direct children of <root>):
  ALL mxCell — direct children of the <root> element, a flat sequence.
  Hierarchy (layers, group containers) is expressed ONLY via the parent attribute.
  Cells nested in the XML inside another mxCell (e.g. inside
  "layer-map") are SILENTLY DROPPED by the draw.io import — the diagram
  opens empty. (This was the cause of the broken mynet_01..03 exports.)

The file opens in draw.io / diagrams.net / the VS Code plugin as an ordinary
diagram and remains an editable infrastructure scheme.

DECISIONS pinned here so the next reader does not "fix" them (v1.3.3.7):
  * The vertex text carries the map's DATA — the tag line (`[tag1, tag2]`, the shape
    the sidebar row uses) and the comment included, so a `.drawio` export says the
    same as the PNG/JPEG/PDF ones (which render the live scene). Tag COLOURS are NOT
    replicated: drawio rich-text styling (`html=1` + `<font>`/`<span>` markup) is a
    separate rabbit hole, the label carries the text.
  * `status` (online/warn/offline) is deliberately NOT exported. It is a RUNTIME fact —
    the result of the last SSH probe — not project data, so writing it would make two
    exports of one unchanged project differ. Same decision in DOCUMENTATION.md §28.

v1.5rc2 (ROADMAP task 3) — the EXPORT PALETTE and the second channel:
  * `export_scene_to_drawio(scene, path, palette=…)` renders PRINT-FRIENDLY by
    default (`ui/theme.py PALETTE_PRINT`): a white card, the LIGHT instance's STRONG
    accent as the outline and the six LIGHT arrow colours — the same decision and the
    same source as the PNG/PDF/SVG exports, so the formats agree. `PALETTE_THEME`
    keeps the current look (the format's own dark palette, deliberately outside the
    UI theme — see DOCUMENTATION.md §3, "out of theme scope").
  * Every EDGE carries the DECLARED dash pattern of its type
    (`theme.ARROW_TYPE_STYLES` through `edge_dash_attributes()`), so the six types
    stay apart in the file without relying on their colour.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import quote

try:  # v1.5rc2: the export palette + the declared pen styles (pure data — no PySide6 there)
    from ..ui import theme
except ImportError:
    from ui import theme

# The application's dark palette (an approximation of the map canvas)
NODE_FILL = "#0f172a"       # dark blue node background
NODE_STROKE = "#38bdf8"     # light blue frame
NODE_TEXT = "#e2e8f0"       # light text
NOTE_FILL = "#facc15"       # notes stay "yellow"
NOTE_TEXT = "#1e293b"
GROUP_FILL = "none"
GROUP_STROKE = "#64748b"

# The palette ids (the ONE vocabulary of the export path — `ui/theme.py`).
PALETTE_PRINT = theme.PALETTE_PRINT
PALETTE_THEME = theme.PALETTE_THEME

LAYER_BACKGROUND = "layer-background"
LAYER_GROUPS = "layer-groups"
LAYER_MAP = "layer-map"


def export_palette_colors(palette=PALETTE_PRINT) -> dict:
    """The colours the drawio writer paints with (v1.5rc2, ROADMAP task 3).

    `print` (the default) FOLLOWS THE LIGHT THEME: the white card (`node_bg`), the
    STRONG accent as the outline (`accent_strong` — the tone the v1.5rc1 contrast gate
    measured at 4.83 on the light canvas, where the decorative sky sits at 2.05) and
    the six arrow colours of the same instance, so the file agrees with the raster
    export instead of repeating a second palette. `theme` keeps the format's own dark
    palette (the module constants above), which is what the pre-v1.5rc2 exporter
    wrote; an unknown id resolves to the print one.
    """
    instance = theme.export_theme(palette)
    if theme.resolve_export_palette(palette) != PALETTE_PRINT:
        return {"node_fill": NODE_FILL, "node_stroke": NODE_STROKE,
                "node_text": NODE_TEXT, "group_stroke": GROUP_STROKE,
                "arrow_colors": dict(instance.arrow_type_colors)}
    return {"node_fill": instance.node_bg,
            "node_stroke": instance.accent_strong,
            "node_text": instance.text_primary,
            "group_stroke": instance.icon_color,
            "arrow_colors": dict(instance.arrow_type_colors)}


def edge_dash_attributes(style) -> str:
    """The drawio attributes of a DECLARED pen style (v1.5rc2) — the second channel.

    The pattern is written in PIXELS (`dashPattern`), i.e. one declared rhythm, not
    the pen's own unit: the map's dots (1.2 pen widths) would be sub-pixel here. A
    double line has no drawio equivalent (an edge carries ONE stroke), so the DOUBLE
    type is expressed by a rhythm of its own — the six types stay apart in the FILE
    too, which is what "no meaning in a colour alone" means for an export.
    """
    if getattr(style, "double", False):
        return "dashed=1;dashPattern=10 3 2 3;"
    dash = getattr(style, "dash", ())
    if not dash:
        return "dashed=0;"
    return "dashed=1;dashPattern=" + " ".join(f"{float(v):g}" for v in dash) + ";"



def _uri_for_style(path: str) -> str:
    """URI for the style=...image=... attribute (drawio requires URL-encoding)."""
    return "file:///" + quote(path.replace("\\", "/").lstrip("/"))


def _node_geometry(node) -> tuple:
    """(x, y, width, height) of a ServerNode from its current geometry."""
    try:
        x = float(node.pos().x())
        y = float(node.pos().y())
        w = float(getattr(node, "_current_width", 180))
        h = float(getattr(node, "_current_height", 120))
    except Exception:
        x, y, w, h = 0.0, 0.0, 180.0, 120.0
    return x, y, max(w, 10.0), max(h, 10.0)


def _node_label(node) -> str:
    """The node's text card: alias, host, OS/CPU/RAM, tags, comment.

    v1.3.3.7 — export fidelity: the label carries the map's DATA, not only the
    hardware summary. The tag line uses the `[tag1, tag2]` shape of the sidebar row
    (ALL the tags, not the first three the row shows — an export must not lose data)
    and the comment follows it — multi-line safe: its line breaks go through the
    `\\x01` placeholder and become `&#xa;` in to_xml_bytes(), so no line is lost.
    An empty field adds NO line (the optional-field pattern of the project format).

    Deliberately NOT part of the label:
      * `status` — a RUNTIME fact (the result of the last SSH probe), not project
        data; two exports of one unchanged project must stay identical (module
        docstring + DOCUMENTATION.md §28);
      * tag colours — drawio rich-text styling is out of scope, the text is enough.
    """
    data = getattr(node, "data", None)
    if data is None:
        return ""
    lines = [data.alias or "Unnamed", f"@{data.host}"]
    details = []
    if getattr(data, "os_name", ""):
        details.append(data.os_name)
    if getattr(data, "cpu_model", "") or getattr(data, "cpu", ""):
        details.append(data.cpu_model or data.cpu)
    if getattr(data, "ram", ""):
        details.append(f"RAM {data.ram}")
    if getattr(data, "ip", "") and data.ip != data.host:
        details.append(data.ip)
    lines.extend(details)
    tags = [str(t).strip() for t in (getattr(data, "tags", None) or []) if str(t).strip()]
    if tags:
        lines.append(f"[{', '.join(tags)}]")
    comment = str(getattr(data, "comment", "") or "")
    if comment.strip():
        lines.extend(comment.splitlines() or [comment])
    # Newlines in value: drawio requires the &#xa; entity. A literal "\n"
    # in an XML attribute is normalized to a space by the parser, so in to_xml_bytes()
    # the placeholder is replaced with "&#xa;" AFTER serialization (ET can't do it itself).
    return "\x01".join(lines)


def _vertex(root_el, cell_id, value, x, y, w, h, style, parent_id="1"):
    """Create an mxCell vertex.

    root_el — the <root> element to which the cell is added as a DIRECT
    child (draw.io decodes only direct children of <root>; mxCells nested
    in the XML are dropped on import).

    parent_id — the LOGICAL parent: the layer id or a group container.
    Group members — parent="<containerId>" with relative coordinates.
    """
    el = ET.SubElement(root_el, "mxCell", {
        "id": cell_id,
        "value": value,
        "style": style,
        "vertex": "1",
        "parent": parent_id,
    })
    ET.SubElement(el, "mxGeometry", {
        "x": str(round(float(x), 2)),
        "y": str(round(float(y), 2)),
        "width": str(round(float(w), 2)),
        "height": str(round(float(h), 2)),
        "as": "geometry",
    })
    return el


class DrawioExporter:
    """Assembling an mxGraph model from a MapScene and serializing it into .drawio XML."""

    def __init__(self, scene, palette=PALETTE_PRINT):
        self.scene = scene
        # v1.5rc2: the palette id (unknown → print) + the colours it resolves to.
        self.palette = theme.resolve_export_palette(palette)
        self._colors = export_palette_colors(self.palette)
        self._cell_seq = 0
        self._member_cell_ids: dict = {}  # ServerNode (in a group) → cell id

    @property
    def dark(self) -> bool:
        """True while the export keeps the CURRENT theme (the pre-v1.5rc2 `dark` flag)."""
        return self.palette == PALETTE_THEME

    # ── id generation ─────────────────────────────────────────────────
    def _next_id(self, prefix: str) -> str:
        self._cell_seq += 1
        return f"{prefix}-{self._cell_seq}"

    # ── assembly ───────────────────────────────────────────────────────
    def build(self) -> ET.Element:
        root = ET.Element("mxfile", {"host": "SSHMap"})
        diagram = ET.SubElement(root, "diagram", {
            "id": "sshmap-0", "name": "SSH Map"})
        model = ET.SubElement(diagram, "mxGraphModel", {
            "dx": "1000", "dy": "700", "grid": "1", "gridSize": "10",
            "guides": "1", "tooltips": "1", "connect": "1", "arrows": "1",
            "fold": "1", "page": "1", "pageScale": "1", "pageWidth": "850",
            "pageHeight": "1100", "math": "0", "shadow": "0"})
        root_cells = ET.SubElement(model, "root")
        ET.SubElement(root_cells, "mxCell", {"id": "0"})
        ET.SubElement(root_cells, "mxCell", {
            "id": "1", "parent": "0"})

        # A drawio layer — an mxCell with parent="0" and no vertex/edge
        # (xml-reference §Layers); order in the XML = z-order: bottom ones first.
        for name in (LAYER_BACKGROUND, LAYER_GROUPS, LAYER_MAP):
            ET.SubElement(root_cells, "mxCell", {
                "id": name, "value": name.removeprefix("layer-"),
                "parent": "0"})

        # IMPORTANT: all cells are added FLAT as direct children of <root>.
        # Logical belonging to a layer/container — via parent_id.
        self._export_background(root_cells)
        groups = self._export_groups(root_cells)
        self._export_map(root_cells, groups)
        return root

    # ── background ──────────────────────────────────────────────────────────
    def _export_background(self, root_el) -> None:
        bg = self.scene.background()
        if bg is None:
            return
        path = getattr(bg, "path", "")
        if not path or not os.path.isfile(path):
            return
        try:
            x, y = float(bg.pos().x()), float(bg.pos().y())
            w, h = bg.size()
        except Exception:
            return
        _vertex(
            root_el, "bg-image", "", x, y, w, h,
            f"shape=image;image={_uri_for_style(path)};"
            "verticalLabelPosition=bottom;verticalAlign=top;opacity=60;",
            parent_id=LAYER_BACKGROUND)

    # ── groups ───────────────────────────────────────────────────────
    def _export_groups(self, root_el) -> dict:
        """Groups → container vertices. Returns {group_obj: cell_id}."""
        ids = {}
        for gi, group in enumerate(self.scene.groups()):
            try:
                gx, gy = float(group.pos().x()), float(group.pos().y())
                gw, gh = float(group._width), float(group._height)
            except Exception:
                continue
            style = (
                f"rounded=1;container=1;collapsible=0;childLayout=none;"
                f"fillColor={GROUP_FILL};strokeColor={self._colors['group_stroke']};"
                f"fontColor={self._colors['node_text']};"
                "verticalAlign=top;align=left;spacingLeft=8;"
                "html=1;whiteSpace=wrap;pointerEvents=0;")
            cell_id = self._next_id("group")
            # A group container — a flat mxCell on the layer-groups layer
            _vertex(root_el, cell_id, getattr(group, "_name", "") or "",
                    gx, gy, gw, gh, style, parent_id=LAYER_GROUPS)
            ids[group] = cell_id
            # Group members — flat mxCells with parent=container,
            # coordinates relative to the parent (xml-reference §Containers)
            for mi, member in enumerate(group.get_members()):
                mx, my, mw, mh = _node_geometry(member)
                _vertex(
                    root_el, f"{cell_id}-member-{mi}", _node_label(member),
                    round(mx - gx, 2), round(my - gy, 2), mw, mh,
                    self._node_style(), parent_id=cell_id)
                # mapping for the arrows: the id of a member inside a group
                self._member_cell_ids[member] = f"{cell_id}-member-{mi}"
        return ids

    def _node_style(self) -> str:
        """The vertex style of the ACTIVE export palette (v1.5rc2)."""
        return (
            f"rounded=1;whiteSpace=wrap;html=1;fillColor={self._colors['node_fill']};"
            f"strokeColor={self._colors['node_stroke']};"
            f"fontColor={self._colors['node_text']};align=left;"
            "spacingLeft=8;verticalAlign=middle;fontFamily=Consolas;")

    # ── map ────────────────────────────────────────────────────────
    def _export_map(self, root_el, group_ids: dict) -> None:
        node_ids = {}   # ServerNode → cell id
        # Nodes outside groups — flat mxCells on the layer-map layer
        for node in self.scene.nodes():
            if any(node in g.get_members() for g in self.scene.groups()):
                continue
            x, y, w, h = _node_geometry(node)
            nid = getattr(getattr(node, "data", None), "id", None) \
                or self._next_id("node")
            cell_id = f"node-{nid}"
            _vertex(root_el, cell_id, _node_label(node), x, y, w, h,
                    self._node_style(), parent_id=LAYER_MAP)
            node_ids[node] = cell_id
        node_ids.update(self._member_cell_ids)

        # Arrows — flat mxCells; parent = the layer (not the container),
        # otherwise edges between members of different groups would be cut off
        for ai, arrow in enumerate(self.scene.arrows()):
            src = node_ids.get(getattr(arrow, "source", None))
            dst = node_ids.get(getattr(arrow, "target", None))
            if not src or not dst:
                continue
            ctype = getattr(arrow, "connection_type", "ssh")
            color = type_color_safe(ctype, self._colors["arrow_colors"])
            label = getattr(arrow, "label_text", "") or ""
            # v1.5rc2 (ROADMAP task 1/3): the DECLARED pen style of the type travels into
            # the file as the edge's width + dash pattern — the six types stay apart
            # without their colour.
            style = theme.arrow_type_style(ctype)
            # v1.2.6: bidirectional connection — an arrowhead at the start end too (startArrow)
            bidir = bool(getattr(arrow, "bidirectional", False))
            edge = ET.SubElement(root_el, "mxCell", {
                "id": f"edge-{ai}",
                "value": label,
                "style": (
                    "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;"
                    f"strokeColor={color};strokeWidth={float(style.width):g};"
                    f"endArrow=classic;{edge_dash_attributes(style)}"
                    + ("startArrow=classic;" if bidir else "")
                    + f"fontColor={self._colors['node_text']};"
                      "fontSize=10;"),
                "edge": "1",
                "parent": LAYER_MAP,
                "source": src,
                "target": dst,
            })
            ET.SubElement(edge, "mxGeometry",
                          {"relative": "1", "as": "geometry"})

        # Notes — flat mxCells on the layer-map layer
        for ni, note in enumerate(self.scene.notes()):
            try:
                nx, ny = float(note.pos().x()), float(note.pos().y())
                nw, nh = float(note.rect().width()), float(note.rect().height())
            except Exception:
                continue
            _vertex(
                root_el, f"note-{ni}", note.text(), nx, ny, nw, nh,
                f"shape=note;whiteSpace=wrap;html=1;size=16;"
                f"fillColor={NOTE_FILL};strokeColor=#b45309;"
                f"fontColor={NOTE_TEXT};align=left;spacingLeft=4;",
                parent_id=LAYER_MAP)

    # ── output ────────────────────────────────────────────────────────
    def to_xml_bytes(self, root_el: Optional[ET.Element] = None) -> bytes:
        """Serialize the model to XML bytes. root_el — the ready tree from build()
        (v1.0-fix audit #7: the export counts cells on the same tree, without building twice);
        without the argument — it builds it itself."""
        if root_el is None:
            root_el = self.build()
        tree = root_el
        ET.indent(tree, space="  ")
        xml = ET.tostring(tree, encoding="unicode")
        # Newline placeholder → the drawio &#xa; entity
        xml = xml.replace("\x01", "&#xa;")
        return b'<?xml version="1.0" encoding="UTF-8"?>\n' + xml.encode("utf-8")


def type_color_safe(ctype: str, colors: Optional[dict] = None) -> str:
    """HEX color of a connection type without a Qt dependency (v0.9.5, palette-aware in v1.5rc2).

    Without ``colors`` the DARK palette of the format (`ui/theme.py`'s DARK instance,
    the values this helper carried since v0.9.5) is used; an export passes the arrow
    colours of ITS palette (``export_palette_colors()``), so the file and the map agree.
    """
    table = colors if colors is not None else theme.DARK.arrow_type_colors
    return table.get(ctype, table.get("ssh", "#34d399"))


def export_scene_to_drawio(scene, path: str, palette=PALETTE_PRINT) -> int:
    """Export the scene to a .drawio file. Returns the number of cells (diagnostics).

    v1.0-fix (audit #7): earlier _cell_seq was returned — it was incremented only
    for groups and nodes without data.id, i.e. the "cells" log actually counted groups. Now —
    the real number of mxCell in the file (including structural ones: the root "0"/"1" and the 3 layers).

    v1.5rc2 (ROADMAP task 3): ``palette`` decides the colours — PRINT-FRIENDLY by
    default (the light page + the high-contrast outlines, the same decision as the
    PNG/PDF/SVG exports), ``PALETTE_THEME`` for the current look.
    """
    exporter = DrawioExporter(scene, palette=palette)
    root = exporter.build()
    cells = sum(1 for _ in root.iter("mxCell"))
    data = exporter.to_xml_bytes(root)
    with open(path, "wb") as fh:
        fh.write(data)
    return cells

# v1.3.3.7 (ROADMAP task 4) — the fate of `load_drawio_structure()` is decided: DELETED.
# The helper counted vertices/edges/notes/containers of "our own" files and was
# production-dead since v0.9.5 (its only caller was tests/test_drawio_export.py), while
# NO version of ROADMAP.md owns the drawio IMPORT. A parser without a consumer is not
# import groundwork but dead weight that silently rots — the decision and its reason are
# in CHANGELOG.md (v1.3.3.7). The test's structure counting now scans the XML inline
# with the same `ET.iter("mxCell")` pattern, so the round-trip check lost nothing.
# Bringing the IMPORT back = one version section in ROADMAP.md + the parser written
# against the reader's needs (which cannot be guessed today), not a resurrected counter.
