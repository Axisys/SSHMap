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
    """A cluster/folder on the map: a frame + a title, drag/resize, server membership.

    **v1.4.2 (ROADMAP task 5) — the FOLD.** A chevron in the title band (and a
    context-menu pair of the window) folds the group: every member card becomes its
    v0.8.4 BADGE and the badges are laid out in a grid inside the frame, which is then
    re-fitted to the grid. Unfolding restores the frame size, every member's position
    and its previous badge flag from the snapshot taken at the fold. While folded the
    members are NOT draggable (a folded group is a summary view; a manual move would be
    undone by the very next unfold) — the GROUP still drags as a whole, and a corner
    resize re-lays the badges out instead of scaling them.

    The state is PERSISTED (`collapsed` + `expanded_width`/`expanded_height`, written
    only while folded) and travels through `CmdToggleGroupCollapse` as one undo step —
    the fold moves real node positions, so it is not a pure view state like the per-node
    collapse. Known limitation: after a save+reload the pre-fold CARD arrangement is
    gone (the folded grid is what was saved); unfolding then restores the frame size and
    un-badges the members where they lie.
    """

    Z_VALUE = -5.0     # below the nodes (z=0) and the arrows (z=-2) — the map's "background" zone
    MIN_W, MIN_H = 160.0, 100.0
    MAX_W, MAX_H = 2400.0, 1600.0
    DEFAULT_W, DEFAULT_H = 480.0, 320.0

    CORNER_HIT = 18.0      # "grab the corner" zone for resize (px from the bottom-right, as with the notes)
    TITLE_ZONE_H = 28.0    # the top band: a double click — rename
    MEMBER_MARGIN = 8.0    # the minimum inset of the members from the frame when clamping on resize
    # v1.4.2: the fold (the grid of badges + the chevron's click zone in the title band)
    BADGE_GAP = 8.0        # the gap between two badges of a folded group
    CHEVRON_ZONE = 26.0    # the chevron's click zone in the RIGHT corner of the title band

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
    # v1.4.2: a click on the fold chevron → MainWindow pushes CmdToggleGroupCollapse (the
    # group never mutates itself — the same "ask, do not act" split as renameRequested)
    collapseRequested = Signal()
    # v1.4.2: the folded state changed (the dirty marker — the fold is persisted)
    collapsedChanged = Signal(bool)
    # v0.8.3-audit (#6): completed gestures — for the undo commands (the node_drag_committed pattern)
    moveCommitted = Signal(object, object)   # (the old position as a QPointF, the new one)
    resizeCommitted = Signal(float, float, float, float)  # (w0, h0, w1, h1)

    def __init__(self, x: float = 0.0, y: float = 0.0, width: Optional[float] = None,
                 height: Optional[float] = None, name: str = "",
                 group_id: Optional[str] = None,
                 collapsed: bool = False,
                 expanded_width=None, expanded_height=None):
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

        # v1.4.2 (ROADMAP task 5): the fold state.
        # `_collapsed`            — the flag (persisted);
        # `_expanded_state`       — the session snapshot {node_id: (x, y, collapsed, movable)};
        # `_expanded_size`        — the frame size to return to on unfold (persisted, so a
        #                           group restored from a file can unfold sensibly);
        # `_laying_out`           — the re-entry guard of the badge grid.
        self._collapsed = bool(collapsed)
        self._expanded_state = None
        self._expanded_size = None
        # v1.4.2: the badge grid must not be re-laid out in the MIDDLE of a bulk move or
        # of an unfold — the members of a group are shifted one by one, so every
        # intermediate resync would otherwise see a half-moved composition and rewrite
        # the grid (the "a folded group drags as a whole" regression).
        self._suspend_layout = False
        if self._collapsed:
            try:
                ew = float(expanded_width)
                eh = float(expanded_height)
                if ew > 0.0 and eh > 0.0:
                    self._expanded_size = (ew, eh)
            except (TypeError, ValueError):
                self._expanded_size = None
        self._laying_out = False

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
        # v1.4.2: a member captured while the group is folded joins the grid (a session
        # fold only — a group restored folded from a file keeps its saved arrangement)
        self.membershipChanged.connect(self._on_membership_changed)

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
        """The top band — the double-click zone for renaming (the chevron zone excluded)."""
        if self._in_chevron(local):
            return False  # v1.4.2: the fold chevron lives in the right corner of the band
        return 0.0 <= local.x() <= self._width and 0.0 <= local.y() <= self.TITLE_ZONE_H

    def _in_chevron(self, local: QPointF) -> bool:
        """v1.4.2: is the local point inside the fold chevron's click zone?"""
        try:
            return self.chevron_rect().contains(QPointF(local))
        except (TypeError, AttributeError):
            return False

    def chevron_rect(self) -> QRectF:
        """v1.4.2: the fold chevron's click zone — the RIGHT corner of the title band.

        The ServerNode pattern (a chevron in the top-right corner of the card), so the
        fold is discoverable without opening a menu; the same click is available as the
        `ctx.collapse_group`/`ctx.expand_group` pair of the context menu.
        """
        z = self.CHEVRON_ZONE
        return QRectF(max(self._width - z, 0.0), 0.0, z, self.TITLE_ZONE_H)

    def _chevron_path(self) -> QPainterPath:
        """The chevron glyph: ▾ while folded ("can be unfolded") / ▴ while expanded."""
        path = QPainterPath()
        cx = self._width - self.CHEVRON_ZONE / 2.0
        cy = self.TITLE_ZONE_H / 2.0
        if self._collapsed:
            path.moveTo(cx - 5.0, cy - 2.0)
            path.lineTo(cx + 5.0, cy - 2.0)
            path.lineTo(cx, cy + 4.0)
        else:
            path.moveTo(cx - 5.0, cy + 2.0)
            path.lineTo(cx + 5.0, cy + 2.0)
            path.lineTo(cx, cy - 4.0)
        path.closeSubpath()
        return path

    def set_frame_size(self, width: float, height: float, resync: bool = True) -> bool:
        """v1.4.2: set the FRAME size only — the members are NOT touched.

        The shared half of the fold (`_layout_badges` re-fits the frame around the badge
        grid) and of `set_group_size` in its folded branch; the expanded branch keeps its
        own proportional member scaling and does not come through here.
        Returns True if the size really changed. `resync=False` is for a caller that
        lays the members out itself right afterwards.
        """
        w, h = self._clamp_size(width, height)
        if abs(w - self._width) < 0.5 and abs(h - self._height) < 0.5:
            return False
        self.prepareGeometryChange()
        self._width, self._height = float(w), float(h)
        self._update_title_text()  # the title eliding depends on the width
        if resync:
            self._resync_members()
        self.update()
        return True

    def set_group_size(self, width: float, height: float) -> bool:
        """Change the group size (clamped MIN/MAX).

        Task v0.8.1 #2: the members move automatically when the boundary changes —
        their positions are scaled proportionally to the new size (sx/sy from the
        top-left corner), then clamped inside the frame with MEMBER_MARGIN, so they
        do not "fall out" of the folder even if the group became smaller than a node.

        v1.4.2 (ROADMAP task 5): a FOLDED group is the exception — its badges are a grid,
        so a resize re-lays the grid out (the column count follows the new width) instead
        of scaling cards that are not cards at the moment.

        Returns True if the size really changed.
        """
        if self._collapsed:
            if not self.set_frame_size(width, height, resync=False):
                return False
            self._layout_badges()
            self.resized.emit()
            return True

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
            # v1.4.2 (ROADMAP task 4): the member geometry is its CARD rect
            # (`card_rect_scene()`), not the painted boundingRect — the drop-shadow halo
            # would otherwise shift and inflate every proportional reposition.
            r = node.card_rect_scene()  # a node — an independent scene item: scene coordinates
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
        """Shift the group AND all members by delta (task v0.8.1 #2 — the drag part).

        v1.4.2: the whole shift is atomic for the badge grid (`_suspend_layout`) — the
        members move one by one, and a re-layout triggered by an intermediate resync
        would fight the very move it is part of.
        """
        if abs(delta.x()) < 0.5 and abs(delta.y()) < 0.5:
            return
        self.prepareGeometryChange()
        self._applying_move = True
        self._suspend_layout = True
        try:
            self.setPos(self.pos() + delta)
            for node in list(self._members):
                # ServerNode.itemChange syncs data.x/data.y and the connection arrows by itself
                node.setPos(node.pos() + delta)
            sc = self.scene()
            if sc is not None and hasattr(sc, "resync_group_members"):
                sc.resync_group_members()  # other nodes may have ended up under the frame
        finally:
            self._suspend_layout = False
            self._applying_move = False
        self.moved.emit()

    def itemChange(self, change, value):
        """An external (programmatic) setPos — the members follow the group the same way.

        An interactive drag goes through _apply_move() with the _applying_move flag — there
        the member shift is already done manually; without the flag itemChange catches only
        programmatic moves (tests/scripts), and there is no duplication.

        As with ServerNode, the hook is called BEFORE the position is applied: the frame for
        the resync is computed from value explicitly (the moving_group override in MapScene).
        v1.4.2: the same atomicity as in _apply_move (the badge grid is not re-laid mid-move).
        """
        if change == QGraphicsItem.ItemPositionChange and not getattr(self, "_applying_move", False):
            try:
                dx = float(value.x()) - float(self.pos().x())
                dy = float(value.y()) - float(self.pos().y())
            except Exception:  # noqa: BLE001 — an unexpected value type — hand it to the standard path
                return super().itemChange(change, value)
            if abs(dx) + abs(dy) > 0.5:
                result = super().itemChange(change, value)  # accept → Qt applies the position
                self._suspend_layout = True
                try:
                    for node in list(self._members):
                        node.setPos(node.pos() + QPointF(dx, dy))
                    sc = self.scene()
                    if sc is not None and hasattr(sc, "resync_group_members"):
                        target_rect = QRectF(float(value.x()), float(value.y()),
                                             self._width, self._height)
                        sc.resync_group_members(moving_group=(self, target_rect))
                finally:
                    self._suspend_layout = False
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

    # ── v1.4.2 (ROADMAP task 5): the FOLD — the members become a grid of badges ──────

    def is_collapsed(self) -> bool:
        """Is the group folded (its members shown as badges)?"""
        return bool(self._collapsed)

    @property
    def collapsed(self) -> bool:
        """The folded flag (the persisted state — `is_collapsed()` in property form)."""
        return bool(self._collapsed)

    def set_collapsed(self, collapsed: bool) -> bool:
        """Fold (True) or unfold (False); idempotent. Returns True if the state changed.

        The API `CmdToggleGroupCollapse` drives — the group never folds itself on a click
        (`collapseRequested` asks the window, which pushes the command).
        """
        return self.collapse() if collapsed else self.expand()

    def collapse(self) -> bool:
        """Fold the group: badge every member, lay the badges out, re-fit the frame.

        The snapshot (`_expanded_state` + `_expanded_size`) is taken FIRST, so `expand()`
        can restore the exact arrangement; a repeated call is a no-op.
        """
        if self._collapsed:
            return False
        self._expanded_size = (float(self._width), float(self._height))
        self._expanded_state = {}
        self._collapsed = True
        self._fold_members()
        self._layout_badges()
        self.update()
        self.collapsedChanged.emit(True)
        return True

    def expand(self) -> bool:
        """Unfold the group: restore the frame size and every member's arrangement.

        Without a snapshot (a group restored FOLDED from a project file, whose pre-fold
        card layout was never saved) the members are un-badged WHERE THEY LIE and only
        the frame size is restored — the documented v1.4.2 limitation.
        """
        if not self._collapsed:
            return False
        state = self._expanded_state or {}
        # `_collapsed` goes False BEFORE the loop: the members are un-badged one by one, and
        # a resync triggered by an intermediate setPos must not see a "folded" group and
        # re-fold the very members this call is restoring (the v1.4.2 expand regression).
        self._collapsed = False
        self._suspend_layout = True
        try:
            if self._expanded_size:
                self.set_frame_size(self._expanded_size[0], self._expanded_size[1], resync=False)
            gpos = self.pos()
            for member in list(self._members):
                data = getattr(member, "data", None)
                if data is None:
                    continue
                entry = state.get(str(getattr(data, "id", "") or ""))
                if entry is not None:
                    lx, ly, was_collapsed, was_movable = entry
                    data.collapsed = bool(was_collapsed)
                else:
                    data.collapsed = False
                    was_movable = True
                try:
                    member.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, bool(was_movable))
                    if entry is not None:
                        # the snapshot holds LOCAL offsets from the frame's top-left corner,
                        # so a group dragged while folded unfolds into its CURRENT place
                        member.setPos(gpos.x() + float(lx), gpos.y() + float(ly))
                except RuntimeError:
                    continue  # Qt teardown — the item is gone
                updater = getattr(member, "update_appearance", None)
                if callable(updater):
                    updater()
            self._resync_members()
        finally:
            self._suspend_layout = False
        self._expanded_state = None
        self._expanded_size = None
        self.update()
        self.collapsedChanged.emit(False)
        return True

    def _fold_members(self):
        """Switch every member into its v0.8.4 badge and freeze it (no dragging while folded).

        Called by `collapse()` and by a membership change of a session-owned fold; the
        snapshot entry is added only when one is due (`_expanded_state` is not None).
        """
        for member in list(self._members):
            data = getattr(member, "data", None)
            if data is None:
                continue
            if self._expanded_state is not None:
                try:
                    movable = bool(member.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
                    gpos = self.pos()
                    self._expanded_state.setdefault(
                        str(getattr(data, "id", "") or ""),
                        (float(member.pos().x()) - float(gpos.x()),
                         float(member.pos().y()) - float(gpos.y()),
                         bool(getattr(data, "collapsed", False)), movable))
                except RuntimeError:
                    continue
            if not getattr(data, "collapsed", False):
                data.collapsed = True
            try:
                member.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            except RuntimeError:
                continue
            updater = getattr(member, "update_appearance", None)
            if callable(updater):
                updater()

    @staticmethod
    def _grid_sort_key(member) -> tuple:
        """A STABLE reading order of the badge grid: alias (lower-cased), then id.

        Deliberately not the current position: a re-layout after an undo (or a resize of
        a folded group) must reproduce the same grid, and a position-derived order would
        shuffle as soon as the layout itself moved the cards.
        """
        data = getattr(member, "data", None)
        return (str(getattr(data, "alias", "") or "").lower(),
                str(getattr(data, "id", "") or ""))

    @staticmethod
    def _badge_size(member) -> tuple:
        """(width, height) a member occupies while folded (the badge metrics)."""
        try:
            width = float(getattr(member, "_current_width", 0.0) or 0.0)
        except (TypeError, ValueError):
            width = 0.0
        try:
            height = float(getattr(member, "COLLAPSED_HEIGHT", 0.0) or 0.0)
        except (TypeError, ValueError):
            height = 0.0
        return max(width, 60.0), max(height, 1.0)

    def _resync_members(self):
        """Recompute the membership of the scene (the group's frame just changed)."""
        sc = self.scene()
        if sc is not None and hasattr(sc, "resync_group_members"):
            sc.resync_group_members()

    def _layout_badges(self) -> bool:
        """Lay the members' badges out in a grid inside the frame and re-fit the frame.

        The grid: a uniform column width (the widest badge), `BADGE_GAP` between the
        cells, the first row under the title band, `MEMBER_MARGIN` insets. The column
        count starts from what the CURRENT width takes and grows until the grid fits
        `MAX_H`, so a wide group gets a table and a narrow one a column. Every badge is
        placed INSIDE the new frame — that is what preserves the geometric membership.
        Returns False when there is nothing to lay out (or on re-entry).
        """
        if self._laying_out:
            return False
        members = [m for m in self._members if getattr(m, "data", None) is not None]
        if not members:
            return False
        self._laying_out = True
        try:
            members.sort(key=self._grid_sort_key)
            m = self.MEMBER_MARGIN
            gap = self.BADGE_GAP
            top = self.TITLE_ZONE_H + m
            col_w = max(self._badge_size(x)[0] for x in members)
            badge_h = max(self._badge_size(x)[1] for x in members)
            n = len(members)

            columns = int(max(1.0, (self._width - 2.0 * m + gap) // (col_w + gap)))
            columns = max(1, min(columns, n))
            cols, need_w, need_h = columns, 0.0, 0.0
            for candidate in range(columns, n + 1):
                rows = (n + candidate - 1) // candidate
                need_w = 2.0 * m + candidate * col_w + (candidate - 1) * gap
                need_h = top + rows * badge_h + (rows - 1) * gap + m
                cols = candidate
                if need_h <= self.MAX_H:
                    break

            self.set_frame_size(max(need_w, self.MIN_W), max(need_h, self.MIN_H), resync=False)
            gpos = self.pos()
            for i, member in enumerate(members):
                row, col = divmod(i, cols)
                member.setPos(gpos.x() + m + col * (col_w + gap),
                              gpos.y() + top + row * (badge_h + gap))
            self._resync_members()
        finally:
            self._laying_out = False
        self.update()
        return True

    def _on_membership_changed(self):
        """v1.4.2: a member joined/left while the group is folded.

        A SESSION fold re-lays the grid (and badges the newcomer); a group restored
        folded from a FILE keeps its saved arrangement — there is no snapshot, and a
        re-layout would destroy exactly the positions the file stored. A bulk move
        (`_apply_move` / a programmatic setPos) and the unfold itself are ATOMIC: the
        grid is not touched while they run (`_suspend_layout`).
        """
        if (not self._collapsed or self._laying_out or self._suspend_layout
                or self._expanded_state is None):
            return
        self._fold_members()
        self._layout_badges()

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
                QRectF(14.0, 3.0, max(w - 28.0 - self.CHEVRON_ZONE, 1.0), self.TITLE_ZONE_H - 6.0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self._display_name)

        # v1.4.2: the fold chevron in the right corner of the title band (▾ folded /
        # ▴ expanded) — always visible, so the fold is discoverable without a menu.
        chevron_pen = QPen(title_color, 1.6)
        chevron_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(chevron_pen)
        painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        painter.drawPath(self._chevron_path())

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
            # v1.4.2: the fold chevron — the group ASKS (the window pushes the undo
            # command); checked BEFORE the move/resize branch so a click on it can never
            # start a drag or a resize.
            if self._in_chevron(local):
                self.setSelected(True)
                try:
                    self.collapseRequested.emit()
                except RuntimeError:
                    pass  # Qt teardown — the receiver is gone
                event.accept()
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
        """The `groups` record. v1.4.2: the fold state is written ONLY while folded
        (the optional-field pattern — an old file has no such keys and loads unfolded,
        an older application ignores them)."""
        data = {
            "id": self.group_id,
            "name": self._name,
            "x": float(self.pos().x()),
            "y": float(self.pos().y()),
            "width": float(self._width),
            "height": float(self._height),
        }
        if self._collapsed:
            data["collapsed"] = True
            if self._expanded_size:
                data["expanded_width"] = float(self._expanded_size[0])
                data["expanded_height"] = float(self._expanded_size[1])
        return data

    @classmethod
    def from_dict(cls, raw: dict) -> "NodeGroup":
        """Create a group from a JSON entry (corrupt values — defaults; the StickyNote pattern).

        v1.4.2: `collapsed` + the pre-fold frame size are read back. A FOLDED group is
        rebuilt WITHOUT re-laying the badges out — the saved member positions ARE the
        grid (the loader adds them afterwards), only the flag and the unfold size are
        restored.
        """
        try:
            x = float(raw.get("x") or 0.0)
            y = float(raw.get("y") or 0.0)
            w = float(raw.get("width") or cls.DEFAULT_W)
            h = float(raw.get("height") or cls.DEFAULT_H)
        except (TypeError, ValueError):
            x, y, w, h = 0.0, 0.0, cls.DEFAULT_W, cls.DEFAULT_H
        group_id = str(raw.get("id") or "")[:8] or None
        collapsed = bool(raw.get("collapsed"))
        expanded_w = raw.get("expanded_width") if collapsed else None
        expanded_h = raw.get("expanded_height") if collapsed else None
        return cls(
            name=str(raw.get("name") or ""),
            x=x, y=y, width=w, height=h, group_id=group_id,
            collapsed=collapsed, expanded_width=expanded_w, expanded_height=expanded_h,
        )
