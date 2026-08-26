# -*- coding: utf-8 -*-
"""Экспорт карты в формат draw.io (.drawio) — v0.9.5.

Сериализатор mxGraph XML через xml.etree.ElementTree, без новых зависимостей.

Что экспортируется:
  - ServerNode      → mxCell vertex (геометрия + текст alias/host/ОС/CPU/RAM);
  - ConnectionArrow → mxCell edge source→target с label и цветом типа связи;
  - StickyNote      → вершина со стилем shape=note;
  - NodeGroup       → контейнер (container=1), члены — дочерние ячейки
    с пересчётом координат относительно parent (членство геометрическое:
    вычитаем позицию группы);
  - фон-изображение → отдельный нижний слой (shape=image).

Слои drawio (порядок в XML = z-порядок, нижние первыми):
  layer-background → layer-groups → layer-map.

КРИТИЧНОЕ ТРЕБОВАНИЕ ФОРМАТА (подтверждено кодом mxModelCodec.draw.io,
decodeRoot: итерация идёт по прямым детям <root>):
  ВСЕ mxCell — прямые дети элемента <root>, плоская последовательность.
  Иерархия (слои, контейнеры групп) выражается ТОЛЬКО атрибутом parent.
  Ячейки, вложенные в XML внутри другого mxCell (например, внутри
  «layer-map»), при импорте draw.io МОЛЧА ОТБРАСЫВАЮТСЯ — диаграмма
  открывается пустой. (Это была причина битых экспортов mynet_01..03.)

Файл открывается в draw.io / diagrams.net / VS Code-плагине как обычная
диаграмма и остаётся редактируемой схемой инфраструктуры.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import quote

# Тёмная палитра приложения (приближение к canvas карты)
NODE_FILL = "#0f172a"       # тёмно-синий фон узла
NODE_STROKE = "#38bdf8"     # голубая рамка
NODE_TEXT = "#e2e8f0"       # светлый текст
NOTE_FILL = "#facc15"       # стикеры остаются «жёлтыми»
NOTE_TEXT = "#1e293b"
GROUP_FILL = "none"
GROUP_STROKE = "#64748b"

LAYER_BACKGROUND = "layer-background"
LAYER_GROUPS = "layer-groups"
LAYER_MAP = "layer-map"


def _uri_for_style(path: str) -> str:
    """URI для атрибута style=...image=... (drawio требует URL-кодирование)."""
    return "file:///" + quote(path.replace("\\", "/").lstrip("/"))


def _node_geometry(node) -> tuple:
    """(x, y, width, height) узла ServerNode из его текущей геометрии."""
    try:
        x = float(node.pos().x())
        y = float(node.pos().y())
        w = float(getattr(node, "_current_width", 180))
        h = float(getattr(node, "_current_height", 120))
    except Exception:
        x, y, w, h = 0.0, 0.0, 180.0, 120.0
    return x, y, max(w, 10.0), max(h, 10.0)


def _node_label(node) -> str:
    """Текстовая плашка узла: alias, host, ОС/CPU/RAM."""
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
    # Переносы строк в value: drawio требует сущность &#xa;. Литеральный "\n"
    # в атрибуте XML парсер нормализует в пробел, поэтому в to_xml_bytes()
    # плейсхолдер заменяется на "&#xa;" ПОСЛЕ сериализации (ET сам не умеет).
    return "\x01".join(lines)


def _vertex(root_el, cell_id, value, x, y, w, h, style, parent_id="1"):
    """Создать mxCell vertex.

    root_el — элемент <root>, которому ячейка добавляется как ПРЯМОЙ
    ребёнок (draw.io декодирует только прямые дети <root>; вложенные в
    XML mxCell при импорте отбрасываются).

    parent_id — ЛОГИЧЕСКИЙ родитель: id слоя или контейнера группы.
    Члены группы — parent="<containerId>" с относительными координатами.
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
    """Сборка mxGraph-модели из MapScene и сериализация в .drawio XML."""

    def __init__(self, scene, dark: bool = True):
        self.scene = scene
        self.dark = dark
        self._cell_seq = 0
        self._member_cell_ids: dict = {}  # ServerNode(в группе) → cell id

    # ── id-генерация ─────────────────────────────────────────────────
    def _next_id(self, prefix: str) -> str:
        self._cell_seq += 1
        return f"{prefix}-{self._cell_seq}"

    # ── сборка ───────────────────────────────────────────────────────
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

        # Слой drawio — mxCell с parent="0" без vertex/edge
        # (xml-reference §Layers); порядок в XML = z-порядок: нижние первыми.
        for name in (LAYER_BACKGROUND, LAYER_GROUPS, LAYER_MAP):
            ET.SubElement(root_cells, "mxCell", {
                "id": name, "value": name.removeprefix("layer-"),
                "parent": "0"})

        # ВАЖНО: все ячейки добавляются ПЛОСКО как прямые дети <root>.
        # Логическая принадлежность к слою/контейнеру — через parent_id.
        self._export_background(root_cells)
        groups = self._export_groups(root_cells)
        self._export_map(root_cells, groups)
        return root

    # ── фон ──────────────────────────────────────────────────────────
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

    # ── группы ───────────────────────────────────────────────────────
    def _export_groups(self, root_el) -> dict:
        """Группы → container-вершины. Возвращает {group_obj: cell_id}."""
        ids = {}
        for gi, group in enumerate(self.scene.groups()):
            try:
                gx, gy = float(group.pos().x()), float(group.pos().y())
                gw, gh = float(group._width), float(group._height)
            except Exception:
                continue
            style = (
                f"rounded=1;container=1;collapsible=0;childLayout=none;"
                f"fillColor={GROUP_FILL};strokeColor={GROUP_STROKE};"
                f"fontColor={NODE_TEXT if self.dark else '#0f172a'};"
                "verticalAlign=top;align=left;spacingLeft=8;"
                "html=1;whiteSpace=wrap;pointerEvents=0;")
            cell_id = self._next_id("group")
            # Контейнер группы — плоский mxCell на слое layer-groups
            _vertex(root_el, cell_id, getattr(group, "_name", "") or "",
                    gx, gy, gw, gh, style, parent_id=LAYER_GROUPS)
            ids[group] = cell_id
            # Члены группы — плоские mxCell с parent=контейнер,
            # координаты относительно parent (xml-reference §Containers)
            for mi, member in enumerate(group.get_members()):
                mx, my, mw, mh = _node_geometry(member)
                _vertex(
                    root_el, f"{cell_id}-member-{mi}", _node_label(member),
                    round(mx - gx, 2), round(my - gy, 2), mw, mh,
                    self._node_style(), parent_id=cell_id)
                # маппинг для стрелок: id члена внутри группы
                self._member_cell_ids[member] = f"{cell_id}-member-{mi}"
        return ids

    def _node_style(self) -> str:
        text = NODE_TEXT if self.dark else "#0f172a"
        fill = NODE_FILL if self.dark else "#ffffff"
        stroke = NODE_STROKE if self.dark else "#0284c7"
        return (
            f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};"
            f"strokeColor={stroke};fontColor={text};align=left;"
            "spacingLeft=8;verticalAlign=middle;fontFamily=Consolas;")

    # ── карта ────────────────────────────────────────────────────────
    def _export_map(self, root_el, group_ids: dict) -> None:
        node_ids = {}   # ServerNode → cell id
        # Узлы вне групп — плоские mxCell на слое layer-map
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

        # Стрелки — плоские mxCell; parent = слой (не контейнер),
        # иначе рёбра между членами разных групп будут обрезаться
        for ai, arrow in enumerate(self.scene.arrows()):
            src = node_ids.get(getattr(arrow, "source", None))
            dst = node_ids.get(getattr(arrow, "target", None))
            if not src or not dst:
                continue
            ctype = getattr(arrow, "connection_type", "ssh")
            color = type_color_safe(ctype)
            label = getattr(arrow, "label_text", "") or ""
            edge = ET.SubElement(root_el, "mxCell", {
                "id": f"edge-{ai}",
                "value": label,
                "style": (
                    "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;"
                    f"strokeColor={color};endArrow=classic;"
                    f"fontColor={NODE_TEXT if self.dark else '#0f172a'};"
                    "fontSize=10;"),
                "edge": "1",
                "parent": LAYER_MAP,
                "source": src,
                "target": dst,
            })
            ET.SubElement(edge, "mxGeometry",
                          {"relative": "1", "as": "geometry"})

        # Стикеры — плоские mxCell на слое layer-map
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

    # ── вывод ────────────────────────────────────────────────────────
    def to_xml_bytes(self) -> bytes:
        tree = self.build()
        ET.indent(tree, space="  ")
        xml = ET.tostring(tree, encoding="unicode")
        # Плейсхолдер переноса строки → drawio-сущность &#xa;
        xml = xml.replace("\x01", "&#xa;")
        return b'<?xml version="1.0" encoding="UTF-8"?>\n' + xml.encode("utf-8")


def type_color_safe(ctype: str) -> str:
    """HEX цвета типа связи без зависимости от Qt (дублирует палитру v0.7)."""
    return {
        "ssh": "#34d399",
        "vpn": "#60a5fa",
        "http": "#fbbf24",
        "database": "#a78bfa",
        "nfs": "#f472b6",
        "kubernetes": "#22d3ee",
    }.get(ctype, "#34d399")


def export_scene_to_drawio(scene, path: str, dark: bool = True) -> int:
    """Экспортировать сцену в .drawio файл. Возвращает число ячеек (диагностика)."""
    exporter = DrawioExporter(scene, dark=dark)
    data = exporter.to_xml_bytes()
    with open(path, "wb") as fh:
        fh.write(data)
    return exporter._cell_seq


def load_drawio_structure(path: str) -> Optional[dict]:
    """Лёгкий парсер «своих» файлов (импорт — опциональная задача v0.9.5 #5).

    Возвращает словарь со счётчиками вершин/рёбер или None при битом XML.
    """
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return None
    vertices = edges = notes = containers = 0
    for cell in tree.iter("mxCell"):
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
