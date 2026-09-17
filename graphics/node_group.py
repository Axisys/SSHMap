"""Node grouping (v0.8.1): a cluster/folder on the map.

A group — a labeled rectangular area UNDER the nodes and arrows (z = Z_VALUE,
the lowest: the map's "background" zone). The gestures — as in StickyNote
(manual mouse handling, ItemIsMovable is NOT set — see the sticky_note.py
docstring about ScrollHandDrag):

    drag  — by any point of the frame it moves the group; ALL members are shifted
            by the same delta (task v0.8.1 #2: "the servers inside a group move
            automatically when the group boundary changes");
    resize — by the bottom-right corner (CORNER_HIT px): the members are repositioned
            proportionally to the new size and clamped inside the frame;
    a double click on the top band (TITLE_ZONE_H) — the renameRequested signal →
            the rename dialog in MainWindow.

Membership is geometric: a server center inside the TOPMOST group → it is its member
(MapScene.resync_group_members() recomputes on any move/resize).
That is why the JSON (the "groups" array) stores only {id, name, x, y, width, height} —
membership is not serialized and is restored from the geometry on load.

QGraphicsObject (not QGraphicsItem) — per the v0.8.1 spec: the signals
(moved/resized/titleChanged/membershipChanged/renameRequested) are needed, which
MainWindow turns into the project dirty marker, as with the notes.
"""
import uuid
from typing import List, Optional

from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QFontMetrics,
)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme


def _tint(hex_color: str, alpha: int) -> "QColor":
    """v1.2.5: a central theme color with opacity (the group fills)."""
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


class NodeGroup(QGraphicsObject):
    """A cluster/folder on the map: a frame + a title, drag/resize, server membership."""

    Z_VALUE = -5.0     # below the nodes (z=0) and the arrows (z=-2) — the map's "background" zone
    MIN_W, MIN_H = 160.0, 100.0
    MAX_W, MAX_H = 2400.0, 1600.0
    DEFAULT_W, DEFAULT_H = 480.0, 320.0

    CORNER_HIT = 18.0      # "grab the corner" zone for resize (px from the bottom-right, as with the notes)
    TITLE_ZONE_H = 28.0    # the top band: a double click — rename
    MEMBER_MARGIN = 8.0    # the minimum inset of the members from the frame when clamping on resize

    CORNER_RADIUS = theme.RADIUS_GROUP   # rounding of the frame (in one style with the node card)

    # v1.2.5: colors — from the central theme (ui/theme.py); values unchanged.
    COLOR_BORDER = QColor(theme.GROUP_BORDER)     # violet-600 — distinct from the nodes' blue
    COLOR_HOVER = QColor(theme.GROUP_HOVER)       # violet-400
    COLOR_SELECTED = QColor(theme.SELECTION_AMBER)  # the same amber as the node selection (a single palette)
    COLOR_FILL = _tint(theme.GROUP_BORDER, 16)        # a nearly transparent fill — the grid shows through
    COLOR_FILL_HOVER = _tint(theme.GROUP_BORDER, 28)
    COLOR_FILL_SELECTED = _tint(theme.SELECTION_AMBER, 20)
    COLOR_TITLE = QColor(theme.GROUP_TITLE)       # violet-300 — reads on the dark map

    moved = Signal()               # the group was moved (a dirty reason for MainWindow)
    resized = Signal()             # the size changed (a corner drag or set_group_size)
    titleChanged = Signal(str)     # the title was renamed (the new name — the argument)
    membershipChanged = Signal()   # the member composition changed (a user dragged a node into/out of the group)
    renameRequested = Signal()     # a double click on the title → MainWindow opens the dialog
    # v0.8.3-audit (#6): completed gestures — for the undo commands (the node_drag_committed pattern)
    moveCommitted = Signal(object, object)   # (the old position as a QPointF, the new one)
    resizeCommitted = Signal(float, float, float, float)  # (w0, h0, w1, h1)

    def __init__(self, x: float = 0.0, y: float = 0.0, width: Optional[float] = None,
                 height: Optional[float] = None, name: str = "",
                 group_id: Optional[str] = None):
        super().__init__()

        self.group_id = (str(group_id)[:8] if group_id else "") or None
        if self.group_id is None:
            self.group_id = str(uuid.uuid4())[:8]  # the same pattern as with the notes/servers

        self._name = str(name or "").strip()
        w, h = self._clamp_size(
            width if width else self.DEFAULT_W, height if height else self.DEFAULT_H)
        self._width, self._height = float(w), float(h)

        # Members: ServerNode (NOT child QGraphicsItems — independent scene objects;
        # their data.x/data.y stay SCENE coordinates and are saved correctly in the JSON).
        self._members = set()

        # Manual move/resize (the StickyNote pattern: otherwise ScrollHandDrag would steal the gesture)
        self._drag_mode = None        # None | "move" | "resize"
        self._drag_start_scene = None
        self._size_start = None
        # v0.8.3-audit (#6): the geometry at the start of the gesture — for moveCommitted/resizeCommitted
        self._gesture_start_pos = None    # the QPointF of the group position
        self._hover = False
        self._applying_move = False   # our own setPos in _apply_move — do not duplicate the shift in itemChange

        # ItemIsMovable is NOT set (see the module docstring); selection only.
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(self.Z_VALUE)
        self.setPos(x, y)

        self._display_name = ""
        self._update_title_text()

    # ── Geometry helpers (the StickyNote/ServerNode pattern: explicit geometry) ──

    @classmethod
    def _clamp_size(cls, w: float, h: float):
        w = max(cls.MIN_W, min(cls.MAX_W, float(w)))
        h = max(cls.MIN_H, min(cls.MAX_H, float(h)))
        return w, h

    @property
    def name(self) -> str:
        """The group name (the title above the frame)."""
        return self._name

    def set_title(self, text: str):
        """Rename the group. An empty name is allowed (the title is not drawn)."""
        new = str(text or "").strip()
        if new == self._name:
            return
        self._name = new
        self._update_title_text()
        self.titleChanged.emit(new)

    def size(self):
        """Current size (w, h) in scene coordinates."""
        return float(self._width), float(self._height)

    def boundingRect(self) -> QRectF:
        """Explicit group geometry (uniform with ServerNode/StickyNote)."""
        return QRectF(0, 0, self._width, self._height)

    def shape(self) -> QPainterPath:
        """The hit area — the whole frame: a click anywhere in the zone lands on the group."""
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self._width, self._height),
                            self.CORNER_RADIUS, self.CORNER_RADIUS)
        return path

    def _in_corner(self, local: QPointF) -> bool:
        """The bottom-right corner — the resize zone (as with the notes)."""
        return (self._width - self.CORNER_HIT <= local.x() <= self._width and
                self._height - self.CORNER_HIT <= local.y() <= self._height)

    def _in_title_zone(self, local: QPointF) -> bool:
        """The top band — the double-click zone for renaming."""
        return 0.0 <= local.x() <= self._width and 0.0 <= local.y() <= self.TITLE_ZONE_H

    def set_group_size(self, width: float, height: float) -> bool:
        """Change the group size (clamped MIN/MAX).

        Task v0.8.1 #2: the members move automatically when the boundary changes —
        their positions are scaled proportionally to the new size (sx/sy from the
        top-left corner), then clamped inside the frame with MEMBER_MARGIN, so they
        do not "fall out" of the folder even if the group became smaller than a node.

        Returns True if the size really changed.
        """
        w, h = self._clamp_size(width, height)
        if abs(w - self._width) < 0.5 and abs(h - self._height) < 0.5:
            return False

        old_w, old_h = self._width, self._height
        sx, sy = w / old_w, h / old_h
        gpos = self.pos()

        # First OUR OWN geometry: the intermediate resyncs (from the members' setPos below)
        # will see the new frame already — the membership does not "flicker" on a group expansion.
        m = self.MEMBER_MARGIN
        self.prepareGeometryChange()
        self._width, self._height = float(w), float(h)

        for node in list(self._members):
            r = node.sceneBoundingRect()  # a node — an independent scene item: scene coordinates
            lx = (r.left() - gpos.x()) * sx
            ly = (r.top() - gpos.y()) * sy
            nw, nh = r.width(), r.height()
            max_lx = max(m, w - nw - m)   # a node wider than the group → anchored at the top-left corner
            max_ly = max(m, h - nh - m)
            lx = min(max(lx, m), max_lx)
            ly = min(max(ly, m), max_ly)
            node.setPos(gpos.x() + lx, gpos.y() + ly)

        self._update_title_text()  # the title eliding depends on the width

        sc = self.scene()
        if sc is not None and hasattr(sc, "resync_group_members"):
            sc.resync_group_members()  # other nodes may have ended up under the frame / left it
        self.update()
        self.resized.emit()
        return True

    def _apply_move(self, delta: QPointF):
        """Shift the group AND all members by delta (task v0.8.1 #2 — the drag part)."""
        if abs(delta.x()) < 0.5 and abs(delta.y()) < 0.5:
            return
        self.prepareGeometryChange()
        self._applying_move = True
        try:
            self.setPos(self.pos() + delta)
        finally:
            self._applying_move = False
        for node in list(self._members):
            # ServerNode.itemChange syncs data.x/data.y and the connection arrows by itself
            node.setPos(node.pos() + delta)
        sc = self.scene()
        if sc is not None and hasattr(sc, "resync_group_members"):
            sc.resync_group_members()  # other nodes may have ended up under the frame
        self.moved.emit()

    def itemChange(self, change, value):
        """An external (programmatic) setPos — the members follow the group the same way.

        An interactive drag goes through _apply_move() with the _applying_move flag — there
        the member shift is already done manually; without the flag itemChange catches only
        programmatic moves (tests/scripts), and there is no duplication.

        As with ServerNode, the hook is called BEFORE the position is applied: the frame for
        the resync is computed from value explicitly (the moving_group override in MapScene).
        """
        if change == QGraphicsItem.ItemPositionChange and not getattr(self, "_applying_move", False):
            try:
                dx = float(value.x()) - float(self.pos().x())
                dy = float(value.y()) - float(self.pos().y())
            except Exception:  # noqa: BLE001 — an unexpected value type — hand it to the standard path
                return super().itemChange(change, value)
            if abs(dx) + abs(dy) > 0.5:
                result = super().itemChange(change, value)  # accept → Qt applies the position
                for node in list(self._members):
                    node.setPos(node.pos() + QPointF(dx, dy))
                sc = self.scene()
                if sc is not None and hasattr(sc, "resync_group_members"):
                    target_rect = QRectF(float(value.x()), float(value.y()),
                                         self._width, self._height)
                    sc.resync_group_members(moving_group=(self, target_rect))
                return result
        return super().itemChange(change, value)

    # ── Membership (ServerNode objects; exclusivity — one node in one group) ──

    def get_members(self) -> List:
        """The member list (no order guaranteed)."""
        return list(self._members)

    def member_count(self) -> int:
        return len(self._members)

    def has_member(self, node) -> bool:
        return node in self._members

    def add_member(self, node):
        """Add a member. Exclusivity: a node cannot be in two groups —
        if needed we remove it from its old one (the topmost group wins)."""
        if node is None or node in self._members:
            return
        sc = self.scene()
        if sc is not None and hasattr(sc, "_groups"):
            for other in list(sc._groups):
                if other is not self and node in other._members:
                    other.remove_member(node)  # removes the old group's membershipChanged
        self._members.add(node)
        self.membershipChanged.emit()

    def remove_member(self, node):
        """Remove a member (a no-op if it was not there)."""
        if node in self._members:
            self._members.discard(node)
            self.membershipChanged.emit()

    def clear_members(self):
        """Clear the composition with a single signal (deleting a group / rebuilding the scene)."""
        if self._members:
            self._members.clear()
            self.membershipChanged.emit()

    # ── Title ──────────────────────────────────────────────

    def _title_font(self) -> QFont:
        return QFont(theme.FONT_UI, 9, QFont.Bold)

    def _update_title_text(self):
        """Elide a long name to the frame width (the full name — in the tooltip; the ServerNode pattern)."""
        fm = QFontMetrics(self._title_font())
        max_w = max(int(self._width - 28), 1)
        if self._name and fm.horizontalAdvance(self._name) > max_w:
            self._display_name = fm.elidedText(self._name, Qt.TextElideMode.ElideRight, max_w)
            self.setToolTip(self._name)
        else:
            self._display_name = self._name
            self.setToolTip("")

    # ── Rendering (all the graphics in paint() — no child items:
    #      a single hit object, the standard drag works over the whole frame area) ──

    def _state_colors(self):
        """(pen_color, pen_width, fill, title_color) for the current state."""
        if self.isSelected():
            return (self.COLOR_SELECTED, 2.5, self.COLOR_FILL_SELECTED,
                    QColor(theme.GROUP_TITLE_SELECTED))
        if self._hover:
            color = QColor(self.COLOR_HOVER)
            color.setAlpha(170)
            return (color, 2.0, self.COLOR_FILL_HOVER, QColor(theme.GROUP_TITLE_HOVER))
        return (self.COLOR_BORDER, 1.5, self.COLOR_FILL, self.COLOR_TITLE)

    def paint(self, painter: QPainter, option, widget=None):
        w, h = self._width, self._height
        if w <= 2 or h <= 2:
            return
        pen_color, pen_width, fill, title_color = self._state_colors()

        path = QPainterPath()
        # A 1 px inset — the frame is entirely inside the boundingRect (Qt clips to it)
        path.addRoundedRect(1.0, 1.0, w - 2.0, h - 2.0, self.CORNER_RADIUS, self.CORNER_RADIUS)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(pen_color, pen_width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QBrush(fill))
        painter.drawPath(path)

        # The title in the top band (see _update_title_text for the eliding)
        if self._display_name:
            painter.setFont(self._title_font())
            painter.setPen(QPen(title_color))
            painter.drawText(
                QRectF(14.0, 3.0, max(w - 28.0, 1.0), self.TITLE_ZONE_H - 6.0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self._display_name)

        # The resize-corner marker — visible on hover/selection (a "drag by this corner" hint)
        if self._hover or self.isSelected():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(pen_color))
            r = theme.RADIUS_RESIZE_MARK
            painter.drawRoundedRect(QRectF(w - 16.0, h - 16.0, 10.0, 10.0), r, r)

    # ── Mouse (manual move/resize — the StickyNote pattern) ──

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            scene_pos = event.scenePos()
            local = self.mapFromScene(scene_pos) if scene_pos is not None else None
            if local is None or not self.boundingRect().contains(local):
                super().mousePressEvent(event)  # a click outside the group — the standard path
                return
            self.setSelected(True)
            if self._in_corner(local):
                self._drag_mode = "resize"
                self._size_start = (self._width, self._height)
                self._drag_start_scene = scene_pos
            else:
                self._drag_mode = "move"
                self._drag_start_scene = scene_pos
            # v0.8.3-audit (#6): remember the start-of-gesture geometry (for undo)
            self._gesture_start_pos = QPointF(self.pos())
            event.accept()  # do NOT pass it to the scene — otherwise ScrollHandDrag would steal the gesture
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
                    self._apply_move(delta)
                # Incremental shift (the start is updated) — no cumulative drift (StickyNote)
                self._drag_start_scene = scene_pos
            else:  # resize by the bottom-right corner
                w0, h0 = self._size_start or (self._width, self._height)
                start_local = self.mapFromScene(self._drag_start_scene or scene_pos)
                cur_local = self.mapFromScene(scene_pos)
                if abs(cur_local.x() - start_local.x()) + abs(cur_local.y() - start_local.y()) > 1.0:
                    self.set_group_size(w0 + (cur_local.x() - start_local.x()),
                                        h0 + (cur_local.y() - start_local.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_mode:
            mode = self._drag_mode
            start_pos = self._gesture_start_pos
            start_size = self._size_start
            self._drag_mode = None
            self._drag_start_scene = None
            self._size_start = None
            self._gesture_start_pos = None
            # v0.8.3-audit (#6): the gesture is complete → a signal for the window's undo command.
            # Emitted only on a real geometry change (otherwise an empty stack entry).
            try:
                if mode == "move" and start_pos is not None:
                    end_pos = QPointF(self.pos())
                    if ((end_pos - start_pos).manhattanLength() > 0.5):
                        self.moveCommitted.emit(QPointF(start_pos), end_pos)
                elif mode == "resize" and start_size is not None:
                    cur = (self._width, self._height)
                    if abs(cur[0] - start_size[0]) + abs(cur[1] - start_size[1]) > 0.5:
                        self.resizeCommitted.emit(start_size[0], start_size[1], cur[0], cur[1])
            except Exception:  # noqa: BLE001 — the undo signal must not kill the release
                pass
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """A double click on the title — a rename request (MainWindow shows the dialog)."""
        scene_pos = event.scenePos()
        local = self.mapFromScene(scene_pos) if scene_pos is not None else None
        if local is not None and self._in_title_zone(local):
            self.renameRequested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ── Hover: cursors (drag / resize corner), as with the notes ──────

    def hoverEnterEvent(self, event):
        self._hover = True
        if not self.isSelected():
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
        self._hover = False
        self.unsetCursor()
        self.update()
        super().hoverLeaveEvent(event)

    # ── Serialization (v0.8.1: the "groups" array in the project JSON) ───
    # Membership is NOT stored — the geometric invariant recomputes it on load.

    def to_dict(self) -> dict:
        return {
            "id": self.group_id,
            "name": self._name,
            "x": float(self.pos().x()),
            "y": float(self.pos().y()),
            "width": float(self._width),
            "height": float(self._height),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "NodeGroup":
        """Create a group from a JSON entry (corrupt values — defaults; the StickyNote pattern)."""
        try:
            x = float(raw.get("x") or 0.0)
            y = float(raw.get("y") or 0.0)
            w = float(raw.get("width") or cls.DEFAULT_W)
            h = float(raw.get("height") or cls.DEFAULT_H)
        except (TypeError, ValueError):
            x, y, w, h = 0.0, 0.0, cls.DEFAULT_W, cls.DEFAULT_H
        group_id = str(raw.get("id") or "")[:8] or None
        return cls(
            name=str(raw.get("name") or ""),
            x=x, y=y, width=w, height=h, group_id=group_id,
        )
