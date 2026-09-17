"""Map background image (v0.9.1): a building diagram / data-center floor plan UNDER all nodes.

BackgroundImage — a QGraphicsPixmapItem with z = Z_VALUE (-10), below groups (-5),
arrows (-2) and nodes (0). Position and size — in SCENE coordinates; manual gestures
in the style of StickyNote/NodeGroup (ItemIsMovable is NOT set — see the docstring
in sticky_note.py about ScrollHandDrag):

    drag  — dragging by any point moves the background;
    resize — dragging the bottom-right corner (CORNER_HIT px) changes the size (aspect
            ratio is NOT enforced, but by default the size equals the native image
            size, so the corner pulls "along the image").

In the project (JSON "background") a PATH to the image is stored + geometry:
{path, x, y, width, height}. The file is NOT embedded in the JSON (the project stays
light); on load a missing file is simply ignored with a warning.

QGraphicsObject (not a plain QGraphicsPixmapItem subclass without signals) —
the changed signals are needed for the MainWindow dirty marker, as with notes/groups.
"""
import os

from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme


class BackgroundImage(QGraphicsObject):
    """Background image under all map elements; drag + resize by the corner."""

    Z_VALUE = -10.0          # lowest of all: groups -5, arrows -2, nodes 0
    CORNER_HIT = 18.0        # "grab the corner" zone for resize (px, NodeGroup pattern)
    MIN_SIZE = 64.0          # minimal side when resizing
    MAX_SIDE = 20000.0       # guard against absurd sizes
    BORDER_ALPHA = 90        # opacity of the thin hint border

    # Signals for MainWindow (project dirty marker)
    moved = Signal()
    resized = Signal()

    def __init__(self, path: str, x: float = 0.0, y: float = 0.0,
                 width: float = None, height: float = None):
        super().__init__()
        self._path = str(path or "")
        self._pixmap = QPixmap(self._path)

        if self._pixmap.isNull():
            raise ValueError(f"Cannot load image: {self._path}")

        native_w = float(self._pixmap.width())
        native_h = float(self._pixmap.height())
        self._width = self._clamp_dim(width if width else native_w, native_w)
        self._height = self._clamp_dim(height if height else native_h, native_h)

        # Manual move/resize (StickyNote/NodeGroup pattern)
        self._drag_mode = None
        self._drag_start_scene = None
        self._size_start = None

        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(self.Z_VALUE)
        self.setPos(x, y)

    @staticmethod
    def _clamp_dim(value: float, fallback: float) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = float(fallback)
        return max(BackgroundImage.MIN_SIZE, min(BackgroundImage.MAX_SIDE, v))

    # ── Geometry ───────────────────────────────────────────────

    @property
    def path(self) -> str:
        return self._path

    def size(self):
        """Current size (w, h) in scene coordinates."""
        return float(self._width), float(self._height)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._width, self._height)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(QRectF(0, 0, self._width, self._height))
        return path

    def _in_corner(self, local: QPointF) -> bool:
        """Bottom-right corner — the resize zone (NodeGroup/StickyNote pattern)."""
        return (self._width - self.CORNER_HIT <= local.x() <= self._width and
                self._height - self.CORNER_HIT <= local.y() <= self._height)

    def set_bg_size(self, width: float, height: float):
        """Change the background size (clamped MIN/MAX). Returns True if it changed."""
        w = max(self.MIN_SIZE, min(self.MAX_SIDE, float(width)))
        h = max(self.MIN_SIZE, min(self.MAX_SIDE, float(height)))
        if abs(w - self._width) < 0.5 and abs(h - self._height) < 0.5:
            return False
        self.prepareGeometryChange()
        self._width, self._height = w, h
        self.update()
        self.resized.emit()
        return True

    # ── Rendering ──────────────────────────────────────────────

    def paint(self, painter: QPainter, option, widget=None):
        if self._pixmap.isNull():
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(QRectF(0, 0, self._width, self._height),
                           self._pixmap, QRectF(self._pixmap.rect()))

        # A thin translucent border — so the background is distinguishable on the dark grid.
        # v1.2.5: colors — from the central theme (ui/theme.py); values unchanged.
        color = QColor(theme.SELECTION_AMBER) if self.isSelected() else QColor(theme.TEXT_MUTED)
        color.setAlpha(self.BORDER_ALPHA if not self.isSelected() else 180)
        painter.setPen(QPen(color, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(0, 0, self._width, self._height))

    # ── Mouse (manual drag/resize — NodeGroup pattern) ──────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            scene_pos = event.scenePos()
            local = self.mapFromScene(scene_pos) if scene_pos is not None else None
            if local is None or not self.boundingRect().contains(local):
                super().mousePressEvent(event)
                return
            self.setSelected(True)
            if self._in_corner(local):
                self._drag_mode = "resize"
                self._size_start = (self._width, self._height)
            else:
                self._drag_mode = "move"
            self._drag_start_scene = scene_pos
            event.accept()  # do NOT pass it to the scene — ScrollHandDrag would steal the gesture
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_mode and (event.buttons() & Qt.MouseButton.LeftButton):
            scene_pos = event.scenePos()
            if scene_pos is None:
                return
            if self._drag_mode == "move":
                delta = scene_pos - self._drag_start_scene
                if abs(delta.x()) + abs(delta.y()) > 0.5:
                    self.setPos(self.pos() + delta)
                    self.moved.emit()
                self._drag_start_scene = scene_pos
            else:  # resize by the bottom-right corner
                w0, h0 = self._size_start or (self._width, self._height)
                start_local = self.mapFromScene(self._drag_start_scene or scene_pos)
                cur_local = self.mapFromScene(scene_pos)
                if abs(cur_local.x() - start_local.x()) + abs(cur_local.y() - start_local.y()) > 1.0:
                    self.set_bg_size(w0 + (cur_local.x() - start_local.x()),
                                     h0 + (cur_local.y() - start_local.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_mode = None
        self._drag_start_scene = None
        self._size_start = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        # A double click does nothing (the background — a passive layer), but the
        # gesture does not fall through to the scene, to avoid starting a rubber band.
        event.accept()

    # ── Hover: cursors, NodeGroup pattern ───────────────────────

    def hoverEnterEvent(self, event):
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update()
        super().hoverEnterEvent(event)

    def hoverMoveEvent(self, event):
        if event.scenePos() is not None:
            local = self.mapFromScene(event.scenePos())
            if local is not None and self.boundingRect().contains(local):
                if self._in_corner(local):
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                else:
                    self.setCursor(Qt.CursorShape.PointingHandCursor)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        self.update()
        super().hoverLeaveEvent(event)

    # ── Serialization (JSON "background") ───────────────────────

    def to_dict(self) -> dict:
        return {
            "path": self._path,
            "x": float(self.pos().x()),
            "y": float(self.pos().y()),
            "width": float(self._width),
            "height": float(self._height),
        }

    @classmethod
    def try_from_dict(cls, raw: dict) -> "Optional[BackgroundImage]":
        """Create the background from a JSON entry, or None (no file / corrupt entry).

        A missing image is NOT a project load error: the warning is logged by the
        caller, and the map opens without the background.
        """
        if not isinstance(raw, dict):
            return None
        path = str(raw.get("path") or "")
        if not path or not os.path.isfile(path):
            return None
        try:
            return cls(
                path=path,
                x=float(raw.get("x") or 0.0),
                y=float(raw.get("y") or 0.0),
                width=raw.get("width"),
                height=raw.get("height"),
            )
        except (TypeError, ValueError):
            return None


# Qt imports above; the tail of the file — serialization/utilities only.
