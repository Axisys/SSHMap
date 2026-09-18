"""Vector UI icons (emoji replacement, UI polish).

All icons are drawn with QPainterPath onto a transparent QPixmap:
cross-platform (independent of emoji fonts), crisp at any DPI/zoom and in a
consistent style — monochrome 20×20 outline. Used for the sidebar, toolbar
and menu buttons: QAction/QPushButton receive a QIcon from get_icon(name).
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from . import theme
except ImportError:
    try:
        from ui import theme
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        import theme

# Base icon color (slate-300) — readable on the dark Fusion palette (#1e293b).
# v1.2.5: the value comes from the central theme; the name is kept (public module constant).
ICON_COLOR = theme.ICON_COLOR
ICON_SIZE = 20


def _canvas(size: int = ICON_SIZE):
    """Transparent QPixmap + prepared QPainter (antialiasing, outline style)."""
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(ICON_COLOR), 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    return pm, p


def _icon(pm, painter) -> QIcon:
    painter.end()
    icon = QIcon()
    icon.addPixmap(pm)
    return icon


# ── Drawers (20×20 canvas, working area ~3..17) ─────────────

def _draw_new(p):
    """Document: a page with a clipped corner and a fold."""
    path = QPainterPath()
    path.moveTo(6.5, 3.0)
    path.lineTo(12.0, 3.0)
    path.lineTo(14.5, 5.5)
    path.lineTo(14.5, 17.0)
    path.lineTo(6.5, 17.0)
    path.closeSubpath()
    p.drawPath(path)
    fold = QPainterPath()
    fold.moveTo(12.0, 3.0)
    fold.lineTo(12.0, 5.5)
    fold.lineTo(14.5, 5.5)
    p.drawPath(fold)


def _draw_open(p):
    """Folder."""
    path = QPainterPath()
    path.moveTo(3.0, 6.0)
    path.lineTo(7.5, 6.0)
    path.lineTo(9.0, 8.0)
    path.lineTo(17.0, 8.0)
    path.lineTo(17.0, 16.5)
    path.lineTo(3.0, 16.5)
    path.closeSubpath()
    p.drawPath(path)


def _draw_save(p):
    """Floppy disk: body + top shutter + bottom label."""
    body = QPainterPath()
    body.addRoundedRect(QRectF(3.5, 3.0, 13.0, 14.0), 1.5, 1.5)
    p.drawPath(body)
    shutter = QPainterPath()
    shutter.addRect(QRectF(7.0, 3.0, 6.0, 4.5))
    p.drawPath(shutter)
    label = QPainterPath()
    label.addRect(QRectF(6.0, 10.5, 8.0, 6.5))
    p.drawPath(label)


def _draw_add_server(p):
    """Server: two stacked units with indicator LEDs."""
    top = QPainterPath()
    top.addRoundedRect(QRectF(3.5, 4.0, 13.0, 5.0), 1.5, 1.5)
    p.drawPath(top)
    bottom = QPainterPath()
    bottom.addRoundedRect(QRectF(3.5, 11.0, 13.0, 5.0), 1.5, 1.5)
    p.drawPath(bottom)
    # LED dots (a thin-circle stroke reads as a dot)
    for cy in (6.5, 13.5):
        led = QPainterPath()
        led.addEllipse(QPointF(14.0, float(cy)), 0.7, 0.7)
        p.drawPath(led)


def _draw_connection(p):
    """Two nodes and a line between them."""
    a = QPainterPath()
    a.addEllipse(QPointF(5.8, 14.2), 2.6, 2.6)
    p.drawPath(a)
    b = QPainterPath()
    b.addEllipse(QPointF(14.2, 5.8), 2.6, 2.6)
    p.drawPath(b)
    line = QPainterPath()
    line.moveTo(7.6, 12.4)
    line.lineTo(12.4, 7.6)
    p.drawPath(line)


def _draw_ssh(p):
    """Terminal: frame + the ">_" prompt."""
    frame = QPainterPath()
    frame.addRoundedRect(QRectF(2.5, 3.5, 15.0, 13.0), 1.8, 1.8)
    p.drawPath(frame)
    prompt = QPainterPath()
    prompt.moveTo(6.0, 7.0)
    prompt.lineTo(9.2, 10.0)
    prompt.lineTo(6.0, 13.0)
    p.drawPath(prompt)
    cursor = QPainterPath()
    cursor.moveTo(11.5, 13.0)
    cursor.lineTo(14.8, 13.0)
    p.drawPath(cursor)


def _draw_properties(p):
    """Sliders (properties/settings)."""
    for y in (5.5, 10.0, 14.5):
        track = QPainterPath()
        track.moveTo(3.5, float(y))
        track.lineTo(16.5, float(y))
        p.drawPath(track)
    knobs = {5.5: 8.5, 10.0: 12.5, 14.5: 7.0}
    for y, kx in knobs.items():
        knob = QPainterPath()
        knob.addEllipse(QPointF(float(kx), float(y)), 1.6, 1.6)
        p.drawPath(knob)


def _draw_delete(p):
    """Trash can: lid with a handle + body with ribs."""
    lid = QPainterPath()
    lid.moveTo(3.5, 6.0)
    lid.lineTo(16.5, 6.0)
    p.drawPath(lid)
    handle = QPainterPath()
    handle.moveTo(8.0, 6.0)
    handle.lineTo(8.0, 4.2)
    handle.lineTo(12.0, 4.2)
    handle.lineTo(12.0, 6.0)
    p.drawPath(handle)
    body = QPainterPath()
    body.moveTo(5.3, 6.0)
    body.lineTo(6.2, 16.8)
    body.lineTo(13.8, 16.8)
    body.lineTo(14.7, 6.0)
    p.drawPath(body)
    for x in (8.5, 11.5):
        rib = QPainterPath()
        rib.moveTo(float(x), 9.2)
        rib.lineTo(float(x), 13.8)
        p.drawPath(rib)


def _draw_fit(p):
    """Four corner brackets for "fit to frame"."""
    corners = (
        ((3.0, 7.5), (3.0, 3.0), (7.5, 3.0)),    # top-left
        ((12.5, 3.0), (17.0, 3.0), (17.0, 7.5)),  # top-right
        ((3.0, 12.5), (3.0, 17.0), (7.5, 17.0)),  # bottom-left
        ((17.0, 12.5), (17.0, 17.0), (12.5, 17.0)),  # bottom-right
    )
    for (x1, y1), (xm, ym), (x2, y2) in corners:
        path = QPainterPath()
        path.moveTo(float(x1), float(y1))
        path.lineTo(float(xm), float(ym))
        path.lineTo(float(x2), float(y2))
        p.drawPath(path)


def _draw_center(p):
    """Crosshair: ring + cross ticks with gaps."""
    ring = QPainterPath()
    ring.addEllipse(QPointF(10.0, 10.0), 4.5, 4.5)
    p.drawPath(ring)
    for x1, y1, x2, y2 in (
        (10.0, 1.8, 10.0, 3.6),
        (10.0, 16.4, 10.0, 18.2),
        (1.8, 10.0, 3.6, 10.0),
        (16.4, 10.0, 18.2, 10.0),
    ):
        tick = QPainterPath()
        tick.moveTo(float(x1), float(y1))
        tick.lineTo(float(x2), float(y2))
        p.drawPath(tick)


def _draw_undo(p):
    """Left-pointing arrow with an arc tail (undo)."""
    arc = QPainterPath()
    arc.moveTo(6.0, 6.5)
    arc.arcTo(QRectF(4.0, 5.0, 12.0, 10.0), 90.0, -180.0)
    p.drawPath(arc)
    head = QPainterPath()
    head.moveTo(8.8, 2.8)
    head.lineTo(5.2, 6.5)
    head.lineTo(8.8, 10.2)
    p.drawPath(head)


def _draw_redo(p):
    """Mirrored undo — right-pointing arrow (redo)."""
    arc = QPainterPath()
    arc.moveTo(14.0, 6.5)
    arc.arcTo(QRectF(4.0, 5.0, 12.0, 10.0), 90.0, 180.0)
    p.drawPath(arc)
    head = QPainterPath()
    head.moveTo(11.2, 2.8)
    head.lineTo(14.8, 6.5)
    head.lineTo(11.2, 10.2)
    p.drawPath(head)


def _draw_settings(p):
    """Gear (settings, v1.1): an 8-tooth outline + a central ring.

    The polygon is computed analytically (cos/sin in screen coordinates,
    y down): two vertices per tooth on the outer radius, one between
    teeth on the inner radius; Qt's arcTo angle conventions are not used
    (straight segments only). The geometry is tuned for 20×20: small
    radii/wide teeth make the outline "splat" into a blob (verified by
    rendering) — deep valleys + narrow teeth.
    """
    import math
    cx, cy = 10.0, 10.0
    r_out, r_in = 8.0, 5.0
    tooth_half = math.radians(9.0)   # tooth half-width (narrow teeth — valleys read clearly)
    pts = []
    for i in range(8):
        base = math.radians(i * 45.0)
        a_start = base - tooth_half
        a_end = base + tooth_half
        a_valley = base + math.radians(45.0 - 9.0)  # end of valley = start of next tooth
        pts.append((cx + r_out * math.cos(a_start), cy + r_out * math.sin(a_start)))
        pts.append((cx + r_out * math.cos(a_end), cy + r_out * math.sin(a_end)))
        pts.append((cx + r_in * math.cos(a_valley), cy + r_in * math.sin(a_valley)))
    path = QPainterPath()
    path.moveTo(pts[0][0], pts[0][1])
    for x, y in pts[1:]:
        path.lineTo(x, y)
    path.closeSubpath()
    # The gear is slightly bolder than the base outline (1.6): on 20×20
    # a thin stroke rounds the valleys and the teeth stop reading.
    pen = QPen(QColor(ICON_COLOR), 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawPath(path)
    hub = QPainterPath()
    hub.addEllipse(QPointF(cx, cy), 2.3, 2.3)
    p.drawPath(hub)


def _draw_sidebar_panel(p):
    """v1.2.4.1: window with a highlighted left column (sidebar) + row marks.

    The pair to map_panel: the same 14×13 frame outline, the same stroke —
    reads as "panel on the left" in the View menu and on the corner
    sidebar-collapse button.
    """
    frame = QPainterPath()
    frame.addRoundedRect(QRectF(3.0, 3.5, 14.0, 13.0), 1.8, 1.8)
    p.drawPath(frame)
    divider = QPainterPath()
    divider.moveTo(8.0, 3.5)
    divider.lineTo(8.0, 16.5)
    p.drawPath(divider)
    for y in (6.9, 10.0, 13.1):
        row = QPainterPath()
        row.moveTo(4.7, float(y))
        row.lineTo(6.5, float(y))
        p.drawPath(row)


def _draw_map_panel(p):
    """v1.2.4.1: window with a mini-map inside (two nodes and a line).

    The pair to sidebar_panel: the same frame; the interior echoes the
    connection icon (node-line-node), but at "map" scale — for the map
    menu item/button.
    """
    frame = QPainterPath()
    frame.addRoundedRect(QRectF(3.0, 3.5, 14.0, 13.0), 1.8, 1.8)
    p.drawPath(frame)
    a = QPainterPath()
    a.addEllipse(QPointF(7.3, 12.7), 1.6, 1.6)
    p.drawPath(a)
    b = QPainterPath()
    b.addEllipse(QPointF(12.7, 7.3), 1.6, 1.6)
    p.drawPath(b)
    line = QPainterPath()
    line.moveTo(8.4, 11.6)
    line.lineTo(11.6, 8.4)
    p.drawPath(line)


def _draw_zoom_in(p):
    """v1.3.3.3: magnifier with a "+" inside — "Zoom In" (View menu)."""
    _draw_magnifier(p)
    plus = QPainterPath()
    plus.moveTo(5.6, 8.4)
    plus.lineTo(9.4, 8.4)
    plus.moveTo(7.5, 6.5)
    plus.lineTo(7.5, 10.3)
    p.drawPath(plus)


def _draw_zoom_out(p):
    """v1.3.3.3: magnifier with a "−" inside — "Zoom Out" (View menu)."""
    _draw_magnifier(p)
    minus = QPainterPath()
    minus.moveTo(5.6, 8.4)
    minus.lineTo(9.4, 8.4)
    p.drawPath(minus)


def _draw_magnifier(p):
    """The shared body of the zoom pair: a lens ring + an SE handle at 20×20.

    The glyph works at MENU size (16 px): the ring is 10 px wide, the handle is a
    single thick stroke, the +/- sign inside is 3.8 px — below that they smear.
    """
    ring = QPainterPath()
    ring.addEllipse(QPointF(8.2, 8.2), 5.0, 5.0)
    p.drawPath(ring)
    handle = QPainterPath()
    handle.moveTo(11.9, 11.9)
    handle.lineTo(16.2, 16.2)
    p.drawPath(handle)


def _draw_plugin(p):
    """v1.4rc3: a puzzle piece — the plugin glyph of the palette and the menu.

    An outline body (a rounded square) with one knob on the right edge and a notch
    where the neighbouring piece would sit on the top edge: readable at MENU size
    (16 px), where the details of a real jigsaw outline would smear into a blob.
    """
    body = QPainterPath()
    body.addRoundedRect(QRectF(4.0, 4.6, 10.0, 10.0), 1.6, 1.6)
    p.drawPath(body)
    knob = QPainterPath()
    knob.addEllipse(QPointF(14.0, 9.6), 1.9, 1.9)
    p.drawPath(knob)
    notch = QPainterPath()
    notch.moveTo(7.0, 4.6)
    notch.lineTo(7.0, 6.6)
    notch.lineTo(10.6, 6.6)
    notch.lineTo(10.6, 4.6)
    p.drawPath(notch)


_DRAWERS = {
    "new": _draw_new,
    "open": _draw_open,
    "save": _draw_save,
    "add_server": _draw_add_server,
    "connection": _draw_connection,
    "ssh": _draw_ssh,
    "properties": _draw_properties,
    "delete": _draw_delete,
    "fit": _draw_fit,
    "center": _draw_center,
    "undo": _draw_undo,
    "redo": _draw_redo,
    "settings": _draw_settings,  # v1.1: gear — the Settings button/menu item
    # v1.2.4.1: panel-collapse icon pair (View menu + corner buttons)
    "sidebar_panel": _draw_sidebar_panel,
    "map_panel": _draw_map_panel,
    # v1.3.3.3 (task 2): the zoom pair of the View menu (project-drawn, no image files)
    "zoom_in": _draw_zoom_in,
    "zoom_out": _draw_zoom_out,
    # v1.4rc3 (plugin foundation): the puzzle glyph of the "Plugins" menu items and
    # of the plugin section of the command palette.
    "plugin": _draw_plugin,
}


def get_icon(name: str) -> QIcon:
    """Icon by name; unknown name — empty QIcon (the button stays text-only)."""
    drawer = _DRAWERS.get(name)
    if drawer is None:
        return QIcon()
    pm, painter = _canvas()
    try:
        drawer(painter)
    except Exception:  # noqa: BLE001 — an icon must not crash the UI
        painter.end()
        return QIcon()
    return _icon(pm, painter)
