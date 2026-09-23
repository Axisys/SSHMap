# -*- coding: utf-8 -*-
"""The declared STATUS SHAPES (v1.5rc2, ROADMAP task 2) — one mark, three consumers.

The 1.5 line opened with a measured problem: the interface encoded meaning in COLOUR
alone, so an availability status was unreadable in greyscale and for a colour-vision
deficiency. v1.5rc2 gives every status a SHAPE beside its colour — the pinned set of
`ui/theme.py`: a filled dot / a ring / a triangle — and this module is the ONE place
that turns that declaration into pixels.

Three consumers, one declaration (so a mark can never drift from the map):

  * the card's status dot (`graphics/server_node.py` — a `QGraphicsPathItem`, the
    shape comes from :func:`shape_path`);
  * the sidebar row marker (`ui/sidebar.py` — a 16 px `QIcon`, :func:`shape_icon`);
  * the legend row (`ui/legend.py` — painted directly, :func:`paint_shape`).

The colour is never invented here: the caller passes the tone the status already had
(`Theme.status_colors`, the idle grey while unchecked), so the shape is a SECOND
channel and not a new palette. The WORDS stay in the tooltips (`node.status.*`) —
"the tooltips keep the words" is what makes the shape a hint rather than a riddle.

Like `ui/theme.py` this module is Qt-light by construction: it imports PySide6 for
the path/pixmap types and nothing else — no window, no widget, no i18n.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

try:  # the declaration (pure data — ui/theme.py)
    from . import theme
except ImportError:  # flat layout: the ui/ directory itself is on sys.path
    try:
        from ui import theme
    except ImportError:
        import theme  # type: ignore


# The ring: the share of the box its stroke takes (0.30 of 14 px ≈ a 4 px ring).
RING_THICKNESS_RATIO = 0.30
# The triangle: the top vertex height and the base inset of the box.
TRIANGLE_TOP_RATIO = 0.08
TRIANGLE_BASE_INSET_RATIO = 0.06
TRIANGLE_BOTTOM_RATIO = 0.92


def shape_id(status) -> str:
    """The declared shape of a status (an unchecked / unknown one → the dot)."""
    return theme.status_shape(status)


def shape_path(status, size: float) -> QPainterPath:
    """The shape of a status as a FILLED path inside a ``size × size`` box at (0, 0).

    Filled on purpose: the caller hands it ONE brush (the status colour) and no pen,
    so every consumer draws the mark with the same call shape — the card's item, the
    sidebar's pixmap and the legend's painter. A ring is an annulus built with the
    ODD-EVEN fill rule (an outer and an inner ellipse), never a stroked circle: a
    stroke would need its own width and the callers would have to agree on it.
    """
    box = max(float(size), 1.0)
    path = QPainterPath()
    shape = shape_id(status)

    if shape == theme.STATUS_SHAPE_RING:
        inset = box * RING_THICKNESS_RATIO
        path.setFillRule(Qt.FillRule.OddEvenFill)
        path.addEllipse(QRectF(0.0, 0.0, box, box))
        path.addEllipse(QRectF(inset, inset, box - 2.0 * inset, box - 2.0 * inset))
        return path

    if shape == theme.STATUS_SHAPE_TRIANGLE:
        inset = box * TRIANGLE_BASE_INSET_RATIO
        path.moveTo(QPointF(box / 2.0, box * TRIANGLE_TOP_RATIO))
        path.lineTo(QPointF(box - inset, box * TRIANGLE_BOTTOM_RATIO))
        path.lineTo(QPointF(inset, box * TRIANGLE_BOTTOM_RATIO))
        path.closeSubpath()
        return path

    # The default: a filled dot (also the mark of an unchecked status).
    path.addEllipse(QRectF(0.0, 0.0, box, box))
    return path


def shape_color(color) -> QColor:
    """Normalise a colour argument (a QColor, a ``#rrggbb`` string or None)."""
    if isinstance(color, QColor):
        return QColor(color)
    if isinstance(color, str) and color:
        return QColor(color)
    return QColor(theme.STATUS_ONLINE)


def paint_shape(painter: QPainter, box: QRectF, status, color) -> None:
    """Draw the status shape into ``box`` (scene/widget coordinates) with ``color``.

    The caller keeps its own painter state — this helper saves and restores it, and
    it never sets a pen: the mark is a fill, always.
    """
    size = min(float(box.width()), float(box.height()))
    if size <= 0.0:
        return
    painter.save()
    try:
        painter.translate(box.left() + (float(box.width()) - size) / 2.0,
                          box.top() + (float(box.height()) - size) / 2.0)
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        painter.setBrush(QBrush(shape_color(color)))
        painter.drawPath(shape_path(status, size))
    finally:
        painter.restore()


def shape_pixmap(status, color, size: int = 16) -> QPixmap:
    """A transparent pixmap of the status shape (the sidebar row marker)."""
    side = max(int(size), 4)
    pixmap = QPixmap(side, side)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # The mark is inset by 3 px so a 16 px icon keeps the size of the v1.4.x
        # round dot (a 10 px mark) — the row height is fixed by the tree.
        mark = float(side) - 6.0
        paint_shape(painter, QRectF(3.0, 3.0, mark, mark), status, color)
    finally:
        painter.end()
    return pixmap


def shape_icon(status, color, size: int = 16) -> QIcon:
    """The status mark as a QIcon (the sidebar's `apply_status_marker`)."""
    return QIcon(shape_pixmap(status, color, size))
