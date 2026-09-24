from typing import Optional, List, Dict

try:
    from ..models.server import ServerData
except ImportError:
    from models.server import ServerData

from .server_node import ServerNode
from .connection_arrow import (ConnectionArrow, DEFAULT_CONNECTION_TYPE,
                               edge_point)  # v1.2.4: the anchor line "from edge to edge"
try:
    from .sticky_note import StickyNote
except ImportError:  # flat import (running from the root)
    from sticky_note import StickyNote

try:
    from .node_group import NodeGroup  # v0.8.1: node grouping (clusters/folders)
except ImportError:
    from node_group import NodeGroup

try:
    from .background_image import BackgroundImage  # v0.9.1: the background image
except ImportError:
    from background_image import BackgroundImage

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme

try:  # v1.4.4 (ROADMAP task 3): the motion standards — the node scale-in
    from ..ui import motion
except ImportError:
    try:
        from ui import motion
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        motion = None

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsScene

from contextlib import contextmanager


class MapScene(QGraphicsScene):
    """The main map scene."""

    # v1.4.4 (ROADMAP task 4): the HOVER FOCUS of a connection arrow.
    # The scene owns the STATE (the arrows live here, and only the scene knows when one
    # dies while it is hovered — `remove_connection`/`remove_server` clear it), while
    # `MainWindow` stays the ONE owner of the resulting dim (`_apply_map_dimming` merges
    # this focus with the tag filter and the search query, so the two can never stack).
    hover_focus_changed = Signal(object)

    # v1.2.4: anchor attachment of a note — the note's top-left corner = the node's
    # top-right corner + an offset (ROADMAP "top-right corner + 12px")
    NOTE_ANCHOR_OFFSET_X = 12.0
    NOTE_ANCHOR_OFFSET_Y = 12.0

    # ── v1.5.1 (ROADMAP task 2): the FIXED frame of the documentation poster ───────
    # `render_to_pixmap` fits the CONTENT (`itemsBoundingRect` + padding), so the size of
    # its result is a property of the map; a documentation image must instead be the SAME
    # size for every map (the README, an issue report and a slide all want one frame).
    # The frame is declared in LOGICAL pixels and rendered at `DOCS_FRAME_SCALE` (2×, the
    # scale every raster export already uses), i.e. 3200×1800 px out of the factory.
    # 1600×900 is 16:9 — the ratio of every screen the picture is looked at on.
    DOCS_FRAME_W = 1600.0
    DOCS_FRAME_H = 900.0
    DOCS_FRAME_SCALE = 2.0
    DOCS_FRAME_PADDING = 40.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(-5000, -5000, 10000, 10000)
        self._nodes: Dict[str, ServerNode] = {}
        self._arrows: List[ConnectionArrow] = []
        # v1.4.4: the arrow under the cursor (the hover focus), or None
        self._hover_focus_arrow: Optional[ConnectionArrow] = None
        # v0.7.2: standalone notes (not linked to servers)
        self._notes: List[StickyNote] = []
        # v1.2.4: anchor lines of the attached notes (note_id → QGraphicsPathItem)
        self._note_anchor_lines: Dict[str, object] = {}
        # v0.8.1: node groups (clusters/folders on the map). The order in the list — the
        # order of addition; at equal z the topmost group = the last one added.
        self._groups: List[NodeGroup] = []
        # v0.9.1: the background image (a building diagram / a data-center floor plan) — at most one.
        self._background: Optional[BackgroundImage] = None
        # UI polish: an adaptive grid — the base step is 20 px in scene coordinates; when
        # zoomed OUT (scale < 1) the step doubles until the on-screen interval returns to
        # the base one. Invariant: the on-screen interval is always ∈ [16, 32) px — the
        # density is constant, and at zoom >= 1 the grid is as before (exactly 20 px).
        # Without the adaptation at zoom 0.1 about 5× more lines were drawn on each axis
        # (a slowdown + visual noise).
        self._grid_size = 20
        self._grid_min_screen_px = float(self._grid_size) * 0.8   # 16 px
        self._grid_major_every = 5

    # ── The grid colours (v1.4.3, ROADMAP task 5) ────────────────────────────
    # Properties, not `__init__` attributes: the pre-v1.4.3 scene cached two
    # QColor objects at construction time, so a theme switch could never reach
    # them. `drawBackground` reads them on every repaint, which is exactly the
    # frequency a theme change needs.

    @property
    def _grid_color(self) -> QColor:
        """Minor grid line (WINDOW_BG of the ACTIVE theme)."""
        return QColor(theme.WINDOW_BG)

    @property
    def _grid_major_color(self) -> QColor:
        """Major grid line (BASE_BG of the ACTIVE theme, a bit lighter)."""
        return QColor(theme.BASE_BG)

    def refresh_theme(self):
        """v1.4.3: re-read the theme for the whole map.

        The scene is the one object that can reach EVERY theme-aware item it
        owns (nodes, arrows, notes, groups, the background frame), so the theme
        walk of `MainWindow.apply_theme()` enters the map here instead of
        iterating the item lists itself. One `update()` repaints the map with the
        new grid and background; each item is asked individually, because a
        QGraphicsItem keeps the QBrush/QPen values it was given.
        """
        self._refresh_items_theme()
        self.update()

    def _refresh_items_theme(self):
        """Ask every scene item that knows the hook to re-read the theme. Never raises.

        The items are taken from the scene's OWN registries (nodes/arrows/notes/
        groups/background) rather than from `QGraphicsScene.items()`: the QGraphicsItem
        children of a card/arrow are never handed a theme directly (their parent
        repaints them), and a registry walk is immune to the "items() only returns
        what is inside the scene rect" rule — a map panned far out of the default
        rect must still follow a theme switch.
        """
        candidates = list(self._nodes.values()) + list(self._arrows) + \
            list(self._notes) + list(self._groups)
        background = getattr(self, "_background", None)
        if background is not None:
            candidates.append(background)
        for item in candidates:
            hook = getattr(item, "refresh_theme", None)
            if not callable(hook):
                continue
            try:
                hook()
            except RuntimeError:
                continue  # Qt teardown — the item is already destroyed
            except Exception:  # noqa: BLE001 — one broken item must not stop the map
                continue

    # ── AUDIT v0.8.3 (#5): public iterators instead of accessing _nodes/_arrows ──

    def nodes(self) -> List[ServerNode]:
        """All map nodes (a list copy — safe to mutate during the iteration)."""
        return list(self._nodes.values())

    def arrows(self) -> List[ConnectionArrow]:
        """All connection arrows (a list copy)."""
        return list(self._arrows)

    def notes(self) -> List["StickyNote"]:
        """All sticky notes (a list copy) — an AUDIT fix: a public iterator
        instead of accessing _notes from outside (like nodes()/arrows()/groups())."""
        return list(self._notes)

    def get_node(self, node_id: str) -> Optional[ServerNode]:
        """A node by id, or None."""
        return self._nodes.get(node_id)

    def has_node(self, node_id: str) -> bool:
        return node_id in self._nodes

    def node_count(self) -> int:
        return len(self._nodes)

    def arrow_count(self) -> int:
        return len(self._arrows)

    def groups(self) -> List[NodeGroup]:
        """All groups (v0.8.1; a list copy)."""
        return list(self._groups)

    def refresh_group_aggregates(self, node=None) -> int:
        """v1.5.4 (ROADMAP task 1): repaint the groups whose aggregate just changed.

        The aggregate itself is read LIVE from the members at paint time (no cache to
        invalidate), so the ONE thing a status change needs is a repaint — otherwise a
        group that just gained its first offline member would keep its old frame until
        something else asked for a paint. `node` narrows the walk to the groups that
        really hold it (the probe-round path: one node, a handful of groups); without it
        every group is asked (a project load, a test seam).

        Returns the number of groups repainted (the topical test's seam). Never raises:
        a dead item during Qt teardown is skipped.
        """
        painted = 0
        for group in list(self._groups):
            try:
                if node is not None and not group.has_member(node):
                    continue
                group.refresh_aggregate()
                painted += 1
            except (RuntimeError, AttributeError):
                continue  # Qt teardown / a group without the v1.5.4 hook
            except Exception:  # noqa: BLE001 — one broken group must not stop the map
                continue
        return painted

    def _current_grid_step(self, scale: float) -> int:
        """The grid step in scene coordinates for the current view scale.

        At scale >= 1 — the base step (the grid as before); as the zoom shrinks the step
        doubles until the on-screen interval returns to the base one
        (the [0.8, 2)×base invariant).
        """
        if scale <= 0:
            scale = 1.0
        step = self._grid_size
        while scale < 1.0 and step * scale < self._grid_min_screen_px:
            step *= 2
        return step

    def drawBackground(self, painter: QPainter, rect: QRectF):
        painter.fillRect(rect, QBrush(QColor(theme.CANVAS_BG)))

        # The view scale (m11) — from the first view; without a view we draw the base step.
        scale = 1.0
        views = self.views()
        if views:
            try:
                s = float(views[0].transform().m11())
                if s > 0:
                    scale = s
            except Exception:  # noqa: BLE001 — without a transform we draw as-is
                pass

        step = self._current_grid_step(scale)
        minor_pen = QPen(self._grid_color)
        minor_pen.setWidth(1)
        major_pen = QPen(self._grid_major_color)
        major_pen.setWidth(1)

        left = int(rect.left()) // step * step
        top = int(rect.top()) // step * step
        # The major lines are anchored to scene coordinates (multiples of step*5), not to
        # a counter from the edge of the visible rect — otherwise the "light" lines would
        # run away during panning.
        for x in range(left, int(rect.right()), step):
            painter.setPen(major_pen if (x // step) % self._grid_major_every == 0 else minor_pen)
            painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
        for y in range(top, int(rect.bottom()), step):
            painter.setPen(major_pen if (y // step) % self._grid_major_every == 0 else minor_pen)
            painter.drawLine(int(rect.left()), y, int(rect.right()), y)

    def add_server(self, data: ServerData, animate: bool = False) -> ServerNode:
        # AUDIT v0.7.2 (low #17): a uuid[:8] collision — we regenerate the id instead of
        # silently clobbering an existing node (the notes already had such a check in add_note).
        if data.id in self._nodes:
            import uuid as _uuid
            while True:
                new_id = str(_uuid.uuid4())[:8]
                if new_id not in self._nodes:
                    break
            data.id = new_id
        node = ServerNode(data)
        self.addItem(node)
        self._nodes[data.id] = node
        # v0.8.1: a new node ended up under a group frame → automatically its member
        # (the geometric invariant — see resync_group_members). Cheap: only when groups exist.
        if self._groups:
            self.resync_group_members()
        # v1.4.4 (ROADMAP task 3): the node APPEARS — a 200 ms scale-in (scale 0.9 → 1.0 +
        # a fade) driven by `ui/motion.py` on the item's OWN properties. Only the ADD paths
        # ask for it (`CmdAddRemoveNode`/`CmdAddRemoveNodeBatch`); a project load, an
        # import of a saved map and a test fixture stay instant.
        if animate and motion is not None:
            try:
                motion.scale_in(node)
            except Exception:  # noqa: BLE001 — the appearance is cosmetic, the node is on the map
                pass
        return node

    def remove_server(self, node_id: str):
        if node_id in self._nodes:
            node = self._nodes[node_id]
            # v0.8.1: the node leaves the map — we remove it from the group membership
            # (the members stay where they are; the composition is just updated)
            for g in list(self._groups):
                if node in g.get_members():
                    g.remove_member(node)
            # Remove the connected arrows
            arrows_to_remove = [a for a in self._arrows
                                if a.source == node or a.target == node]
            for a in arrows_to_remove:
                self.clear_hover_focus(a)  # v1.4.4: a dying arrow drops the hover focus
                self.removeItem(a)
                getattr(a, 'deleteLater', lambda: None)()  # v0.9.3 fix: we drop the C++ object (otherwise a leak until the end of the session)
                self._arrows.remove(a)
            # v1.2.4 (D7): a safety net — the attached notes are detached, the lines are removed
            # (a no-op if the window already pushed the detach commands; protects the fallback
            # paths without a window)
            for n in self.notes_attached_to(node_id):
                n.server_id = None
                self._remove_note_anchor_line(n.note_id)
            self.removeItem(node)
            getattr(node, 'deleteLater', lambda: None)()  # v0.9.3 fix: the card+shadow+pulse+text — otherwise they live forever
            del self._nodes[node_id]

    def add_connection(self, source_id: str, target_id: str, label: str = "",
                       ctype: str = DEFAULT_CONNECTION_TYPE,
                       bidirectional: bool = False) -> Optional[ConnectionArrow]:
        # v1.2.6: bidirectional — arrowheads on both ends (optional; the default
        # False — a standard one-way arrow, as before v1.2.6).
        if source_id not in self._nodes or target_id not in self._nodes:
            return None
        if self.has_connection(source_id, target_id):
            return None  # we do not create a duplicate connection
        src = self._nodes[source_id]
        tgt = self._nodes[target_id]
        arrow = ConnectionArrow(src, tgt, label, ctype, bidirectional=bidirectional)
        self.addItem(arrow)
        self._arrows.append(arrow)
        return arrow

    def has_connection(self, source_id: str, target_id: str) -> bool:
        """Check whether a connection between the nodes already exists (in the same direction)."""
        for a in self._arrows:
            if a.source.data.id == source_id and a.target.data.id == target_id:
                return True
        return False

    # ── v0.7.3: removing a connection ─────────────────────────────────

    def remove_connection(self, arrow: ConnectionArrow) -> bool:
        """Remove a connection by a reference to the arrow (the context menu, v0.7.3).

        Returns True if the arrow was found and removed.
        """
        if arrow in self._arrows:
            self.clear_hover_focus(arrow)  # v1.4.4: an arrow cannot stay the hover focus dead
            self.removeItem(arrow)
            getattr(arrow, 'deleteLater', lambda: None)()  # v0.9.3 fix: the C++ object must not live until the scene's death (deleteLater is available on QObject subclasses)
            self._arrows.remove(arrow)
            return True
        return False

    # ── v1.4.4 (ROADMAP task 4): the arrow hover focus ─────────────────────

    def hover_focus_arrow(self) -> Optional[ConnectionArrow]:
        """The arrow under the cursor (the hover focus), or None."""
        return self._hover_focus_arrow

    def set_hover_focus_arrow(self, arrow) -> bool:
        """The arrow under the cursor became the focus — emit `hover_focus_changed`.

        Idempotent (a repeated enter of the same arrow is a no-op) and never raises: the
        signal only carries a FACT to the window, which owns the dim state.
        """
        if arrow is None:
            return self.clear_hover_focus()
        if arrow is self._hover_focus_arrow:
            return False
        self._hover_focus_arrow = arrow
        self._emit_hover_focus()
        return True

    def clear_hover_focus(self, arrow=None) -> bool:
        """Drop the focus — the cursor left `arrow` (or that arrow died).

        `arrow=None` clears unconditionally (the project was replaced / the map cleared);
        a specific arrow clears only while IT is the focus — a fast hover/un-hover
        sequence therefore cannot clear a focus that a newer event has already moved.
        """
        if self._hover_focus_arrow is None:
            return False
        if arrow is not None and arrow is not self._hover_focus_arrow:
            return False
        self._hover_focus_arrow = None
        self._emit_hover_focus()
        return True

    def _emit_hover_focus(self):
        try:
            self.hover_focus_changed.emit(self._hover_focus_arrow)
        except RuntimeError:
            pass  # Qt teardown — the scene is already destroyed

    def update_connections_for_node(self, node: ServerNode):
        for arrow in self._arrows:
            if arrow.source == node or arrow.target == node:
                arrow.update_position()
        # v1.2.4 (D4): the attached notes follow the node — a single point of coverage,
        # all paths that change the node geometry already call this method (itemChange on
        # any setPos, both ends of update_appearance). During a live drag the anchor
        # "catches up" one step behind, exactly like the arrows — self-healing via the
        # repeated setPos in CmdMoveNode.redo() on release.
        self.update_note_anchor_for_node(node)

    def get_selected_node(self):
        """Returns the selected ServerNode, or None."""
        for item in self.selectedItems():
            if isinstance(item, ServerNode):
                return item
        return None

    # ── v0.7.2: notes (Sticky Notes) ───────────────────────────

    def add_note(self, text: str = "", x: float = 0.0, y: float = 0.0,
                 width: float = 240.0, height: float = 160.0,
                 note_id: Optional[str] = None) -> StickyNote:
        """Create a note on the scene (the position — the top-left corner)."""
        if note_id is not None and any(n.note_id == note_id for n in self._notes):
            # a duplicate id when loading a corrupt file — generate a new one, do not lose the note
            note_id = None
        note = StickyNote(text=text, x=x, y=y, width=width, height=height, note_id=note_id)
        self.addItem(note)
        self._notes.append(note)
        # v1.2.4-fix: the live drag geometry — the anchor line of an attached note follows
        # it (for a free one the signal does nothing: on_note_drag_updated is a no-op)
        try:
            note.dragUpdated.connect(self.on_note_drag_updated)
        except RuntimeError:  # Qt teardown
            pass
        return note

    def remove_note(self, note_id: str):
        """Remove a note by id (a no-op if there is none)."""
        for i, n in enumerate(self._notes):
            if n.note_id == note_id:
                self._remove_note_anchor_line(note_id)  # v1.2.4: the line must not be left orphaned
                self.removeItem(n)
                getattr(n, 'deleteLater', lambda: None)()  # v0.9.3 fix: the QTextEdit inside the note — a heavy C++ object
                del self._notes[i]
                return

    def get_note_by_id(self, note_id: str) -> Optional[StickyNote]:
        for n in self._notes:
            if n.note_id == note_id:
                return n
        return None

    # ── v1.2.4: attaching notes to servers + the anchor line ────────

    def notes_attached_to(self, node_id: str) -> List["StickyNote"]:
        """The notes attached to the node (a list copy)."""
        return [n for n in self._notes if getattr(n, "server_id", None) == node_id]

    def attach_note_to_node(self, note, node, keep_position: bool = False) -> bool:
        """v1.2.4: attach a note to a node (server_id + the line).

        keep_position=False (menu/drag): the note "snaps" to the anchor — the node's
        top-right corner + a 12 px offset, anchor_offset is reset.
        keep_position=True (loading from a file / undo of a detach): the stored position
        is trusted — anchor_offset is computed from it relative to the anchor, the note
        does not jump into the corner (v1.2.4-fix: an attached note can be moved).
        Idempotent by id match; False — if the arguments are not on this scene.

        v1.4.2 (ROADMAP task 4): the anchor is the node's CARD rect
        (`card_rect_scene()`), not the painted boundingRect — otherwise the note would
        hang 9 px off the card now that the drop-shadow is a halo on all four sides.
        """
        if note is None or node is None or getattr(note, "scene", lambda: None)() is not self:
            return False
        r = node.card_rect_scene()
        anchor_x = r.right() + self.NOTE_ANCHOR_OFFSET_X
        anchor_y = r.top() + self.NOTE_ANCHOR_OFFSET_Y
        if keep_position:
            try:
                p = note.pos()
                note.anchor_offset = (float(p.x() - anchor_x), float(p.y() - anchor_y))
            except RuntimeError:  # Qt teardown
                note.anchor_offset = (0.0, 0.0)
        else:
            note.anchor_offset = (0.0, 0.0)
            self._place_note_at_anchor(note, node)
        note.server_id = node.data.id
        self._ensure_note_anchor_line(note, node)
        return True

    def detach_note_from_node(self, note) -> bool:
        """v1.2.4: detach the note (the note stays where it is; the line is removed)."""
        if not getattr(note, "server_id", None):
            return False
        note.server_id = None
        self._remove_note_anchor_line(getattr(note, "note_id", None))
        return True

    def on_note_drag_updated(self, note=None):
        """v1.2.4-fix: the note is moved/resized with the mouse (dragUpdated) — an attached
        one stays attached: the offset from the anchor is recomputed, the anchor line
        follows live. A free note / no living node — a no-op.
        v1.4.2: the anchor rect is the node's CARD (`card_rect_scene()` — task 4)."""
        if note is None or not getattr(note, "server_id", None):
            return
        node = self._nodes.get(note.server_id)
        if node is None:
            return
        try:
            r = node.card_rect_scene()
            p = note.pos()
            note.anchor_offset = (p.x() - (r.right() + self.NOTE_ANCHOR_OFFSET_X),
                                  p.y() - (r.top() + self.NOTE_ANCHOR_OFFSET_Y))
            self._update_note_anchor_line(note, node)
        except RuntimeError:  # Qt teardown — the item is destroyed
            pass

    def update_note_anchor_for_node(self, node):
        """v1.2.4: recompute the positions of the notes attached to the node (the
        update_connections_for_node pattern). Public — for direct attach/detach/load calls.
        v1.2.4-fix: the note follows while keeping its anchor_offset (after a manual
        shift it does not "jump back" into the node's corner)."""
        for note in self.notes_attached_to(node.data.id):
            try:
                if note.scene() is not None:
                    self._place_note_at_anchor(note, node)
                    self._update_note_anchor_line(note, node)
            except RuntimeError:  # Qt teardown — the item is destroyed
                pass

    def _place_note_at_anchor(self, note, node):
        """The note position = the node anchor (the card's top-right corner + a 12 px
        offset, D2) + the note's anchor_offset (v1.2.4-fix: it can be moved — the
        offset is kept). v1.4.2: the anchor rect is `card_rect_scene()` (task 4)."""
        r = node.card_rect_scene()
        ox, oy = getattr(note, "anchor_offset", (0.0, 0.0))
        note.prepareGeometryChange()  # QGraphicsProxyWidget — without this there are artifacts
        note.setPos(r.right() + self.NOTE_ANCHOR_OFFSET_X + ox,
                    r.top() + self.NOTE_ANCHOR_OFFSET_Y + oy)

    def _ensure_note_anchor_line(self, note, node):
        line = self._note_anchor_lines.get(getattr(note, "note_id", None))
        if line is None:
            from PySide6.QtWidgets import QGraphicsPathItem
            line = QGraphicsPathItem()
            pen = QPen(QColor(StickyNote.BG_COLOR), 1.2, Qt.PenStyle.DashLine)
            pen.setDashPattern([4.0, 3.0])
            line.setPen(pen)
            line.setZValue(-1.0)  # above the arrows (-2), below the nodes/notes (0)
            self.addItem(line)
            self._note_anchor_lines[note.note_id] = line
        self._update_note_anchor_line(note, node)

    def _update_note_anchor_line(self, note, node):
        """A straight path from the note edge to the node edge via two edge_point calls (D3).
        v1.4.2: the node end uses the CARD rect (`card_rect_scene()`) — the anchor line
        ends on the card, not on its shadow halo (ROADMAP task 4)."""
        line = self._note_anchor_lines.get(getattr(note, "note_id", None))
        if line is None:
            return
        nr, rr = note.sceneBoundingRect(), node.card_rect_scene()
        p0 = edge_point(nr, nr.center(), rr.center())
        p1 = edge_point(rr, rr.center(), nr.center())
        path = QPainterPath()
        path.moveTo(p0)
        path.lineTo(p1)
        line.setPath(path)

    def _remove_note_anchor_line(self, note_id):
        line = self._note_anchor_lines.pop(note_id, None) if note_id else None
        if line is not None:
            self.removeItem(line)
            getattr(line, "deleteLater", lambda: None)()  # the v0.9.3 anti-leak pattern

    # ── v0.8.1: node groups (clusters/folders on the map) ───────────

    def add_group(self, name: str = "", x: float = 0.0, y: float = 0.0,
                  width: Optional[float] = None, height: Optional[float] = None,
                  group_id: Optional[str] = None,
                  collapsed: bool = False,
                  expanded_width=None, expanded_height=None) -> NodeGroup:
        """Create a group (frame + title) at a scene point (the top-left corner).

        The nodes already lying under the frame automatically become members (resync).
        An id collision — regenerate (the add_server/add_note pattern), the entry is not lost.

        v1.4.2 (ROADMAP task 5): `collapsed` + the pre-fold frame size are the FOLD state
        (`NodeGroup.__init__`); a folded group is created with the flag only — its member
        badges arrive from the file with their own saved positions, so nothing is re-laid out.
        """
        if group_id is not None and any(g.group_id == group_id for g in self._groups):
            import uuid as _uuid
            while True:
                new_id = str(_uuid.uuid4())[:8]
                if new_id not in {g.group_id for g in self._groups}:
                    break
            group_id = new_id
        grp = NodeGroup(
            name=name, x=x, y=y,
            width=width if width is not None else NodeGroup.DEFAULT_W,
            height=height if height is not None else NodeGroup.DEFAULT_H,
            group_id=group_id,
            collapsed=collapsed,
            expanded_width=expanded_width, expanded_height=expanded_height)
        self.addItem(grp)
        self._groups.append(grp)
        self.resync_group_members()  # auto-capture of the nodes under the frame (task v0.8.1 #2)
        return grp

    def remove_group(self, group: NodeGroup) -> bool:
        """Remove a group. The member servers STAY on the map at the same positions —
        a group is a labeled container, not an owner of the nodes."""
        if group in self._groups:
            group.clear_members()  # a single signal, no N re-signals
            self.removeItem(group)
            getattr(group, 'deleteLater', lambda: None)()  # v0.9.3 fix: the group frame+title — C++ objects too
            self._groups.remove(group)
            # A node whose center was in this group may end up under the frame of another
            # (lower) group — we restore the invariant.
            if self._nodes and self._groups:
                self.resync_group_members()
            return True
        return False

    def remove_group_by_id(self, group_id: str) -> bool:
        grp = self.get_group_by_id(group_id)
        if grp is None:
            return False
        return self.remove_group(grp)

    def get_group_by_id(self, group_id: str) -> Optional[NodeGroup]:
        for g in self._groups:
            if g.group_id == group_id:
                return g
        return None

    def find_group_at(self, scene_pos) -> Optional[NodeGroup]:
        """The topmost group under a scene point (the later-added ones — on top)."""
        try:  # contains(qreal x, qreal y) — independent of the QPoint/QPointF binding variant
            px = float(scene_pos.x())
            py = float(scene_pos.y())
        except Exception:  # noqa: BLE001 — not a point (e.g. a bool from QAction.triggered)
            return None
        for g in reversed(self._groups):
            try:
                if QRectF(g.sceneBoundingRect()).contains(px, py):
                    return g
            except RuntimeError:  # Qt teardown — the item is already destroyed
                continue
        return None

    def get_selected_group(self) -> Optional[NodeGroup]:
        """Returns the selected group, or None (the get_selected_node analog)."""
        for item in self.selectedItems():
            if isinstance(item, NodeGroup):
                return item
        return None

    def resync_group_members(self, node_overrides=None, moving_group=None) -> bool:
        """v0.8.1: recompute the membership by the geometric invariant.

        A node — a member of the TOPMOST group whose frame contains its card center;
        outside all groups — a member of none (exclusivity). Called on any move/resize
        of the nodes and groups, so the membership does not need to be stored in the JSON:
        it is restored from the geometry. Returns True if the composition changed.

        node_overrides  — {node_id: QRectF}: the target rects of nodes whose move is not
                          yet applied by Qt (the itemChange hook is called before setPos).
        moving_group    — (NodeGroup, QRectF): the target frame of a group while it is
                          being moved (the same pre-apply moment).
        """
        if not self._groups:
            return False  # without groups there is nothing to recompute (a cheap exit on the hot path)

        moving_grp, moving_rect = (moving_group or (None, None))

        desired = {}  # node_id -> NodeGroup | None (one per node — the topmost group)
        for nid, node in list(self._nodes.items()):
            # v1.4.2 (ROADMAP task 4): the membership test uses the CARD rect
            # (card_rect_scene()) — the shadow halo must not count as the card, and the
            # halo-inflated rect would also shift the centre by SHADOW_DY/2.
            r = QRectF(node_overrides[nid]) if (node_overrides and nid in node_overrides) \
                else node.card_rect_scene()
            if r.isEmpty():
                continue
            center = r.center()
            cx, cy = float(center.x()), float(center.y())
            grp = None
            for g in reversed(self._groups):  # the topmost (the later-added) one wins
                try:
                    if g is moving_grp and moving_rect is not None:
                        gr = QRectF(moving_rect)  # the frame is not yet applied by Qt — the target from overrides
                    else:
                        gr = QRectF(g.sceneBoundingRect())
                    if gr.contains(cx, cy):
                        grp = g
                        break
                except RuntimeError:  # Qt teardown
                    continue
            desired[nid] = grp

        current = {}  # node_id -> the group from the live compositions (the exclusivity invariant)
        for g in self._groups:
            for n in list(g.get_members()):
                if getattr(n, "data", None) is not None and hasattr(n.data, "id"):
                    current[n.data.id] = g

        changed = False
        for nid, grp in desired.items():
            cur = current.get(nid)  # None — the node is in no group
            if cur is grp:
                continue
            node = self._nodes.get(nid)
            if node is None:
                continue
            if cur is not None:
                cur.remove_member(node)   # emits membershipChanged (the window's dirty marker)
                changed = True
            if grp is not None:
                grp.add_member(node)      # add_member guarantees the exclusivity itself
                changed = True
        return changed

    def clear_all(self):
        self.clear()  # removes the nodes, the arrows, the notes, the groups, and the background (all the QGraphicsItems)
        self._nodes.clear()
        self._arrows.clear()
        # v1.4.4: the hover focus died with its arrow — drop the state (and tell the window,
        # so a dim left over by a replaced project cannot survive the switch)
        self._hover_focus_arrow = None
        self._notes.clear()
        # v1.2.4: the anchor lines are scene items too — clear() already destroyed them
        # (the C++ objects are dead, a removeItem on them raises a RuntimeError), just
        # reset the references
        self._note_anchor_lines.clear()
        self._groups.clear()  # v0.8.1: the group compositions live in the items themselves — they are removed
        self._background = None  # v0.9.1

    # ── v0.9.1: the background image + map export ──────────────

    def background(self) -> Optional[BackgroundImage]:
        """The current background (or None)."""
        return self._background

    def set_background_image(self, path: str) -> BackgroundImage:
        """Set the background image (replaces the previous one).

        The default size — the native image size, the position (0, 0);
        move/resize with the mouse (drag / the bottom-right corner).
        Raises ValueError if the file cannot be read as an image.
        """
        self.remove_background()
        bg = BackgroundImage(path)
        self.addItem(bg)
        self._background = bg
        return bg

    def remove_background(self):
        """Remove the background image (a no-op if there is none)."""
        if self._background is not None:
            sc_item = self._background.scene()
            if sc_item is not None:
                self.removeItem(self._background)
            getattr(self._background, 'deleteLater', lambda: None)()  # v0.9.3 fix: the pixmap must not linger until the scene's death
            self._background = None

    def render_to_pixmap(self, scale: float = 2.0, padding: float = 60.0,
                         use_view_rect=None,
                         palette=theme.PALETTE_PRINT) -> "QPixmap":
        """Render the map into a QPixmap (v0.9.1 #1).

        The area — itemsBoundingRect (+padding), i.e. the whole map,
        regardless of the window's current zoom/pan. The background image
        is included in the result (it is part of the map); the background and the grid
        are drawn via drawBackground (CANVAS_BG + the lines) — QGraphicsScene.render calls it,
        so the export looks like the interactive view (behavior since v0.9.1).

        **v1.5rc2 (ROADMAP task 3): `palette` decides the LOOK of the export and
        defaults to `theme.PALETTE_PRINT`** — an export must not print a dark page, so
        a DARK window exports the LIGHT page with the high-contrast lines by default;
        `theme.PALETTE_THEME` keeps the current look (the opt-out of the export
        dialog). `self.export_palette()` swaps the active instance for the duration of
        the render and restores it, so nothing about the window changes.
        """
        from PySide6.QtGui import QPixmap, QColor

        with self.export_palette(palette):
            src = self.itemsBoundingRect().adjusted(
                -float(padding), -float(padding), float(padding), float(padding))
            if src.isEmpty():
                src = QRectF(-400, -300, 800, 600)

            w = max(int(src.width() * scale), 1)
            h = max(int(src.height() * scale), 1)
            pixmap = QPixmap(w, h)
            pixmap.fill(QColor(theme.RENDER_BG))  # the surface of the EXPORT palette

            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self.render(painter, target=QRectF(pixmap.rect()), source=src)
            painter.end()
            return pixmap

    # ── v1.5.1 (ROADMAP task 2): the fixed-frame documentation poster ────────────

    def render_frame_to_pixmap(self, scale: float = None, padding: float = None,
                               frame_w: float = None, frame_h: float = None,
                               palette=theme.PALETTE_THEME) -> "QPixmap":
        """Render the map inside a FIXED frame (v1.5.1) — the documentation poster.

        The v1.5.1 sibling of `render_to_pixmap`, and deliberately a SEPARATE method:
        the export fits the content (`itemsBoundingRect` + padding), so its pixel size
        is a property of the map and changes with every node added — useless as a
        documentation image. Here the FRAME is the constant: `frame_w × frame_h` LOGICAL
        pixels (1600×900 by default, the 16:9 screen ratio) rendered at `scale` (2 → a
        3200×1800 PNG), with the content fitted into it by `frame_source_rect()` (the
        larger dimension decides the scale, the free axis is centred) on a margin of
        `padding` scene units, and the canvas background painted around it.

        **The poster is a SCENE render, on purpose** — the frame holds the MAP and
        nothing else. The floating panels (the legend, the minimap, the search bar, the
        first-run hint) and the whole chrome (the sidebar, the toolbar, the status bar)
        are children of `MapView`, never scene items, so they cannot enter the image
        (the v1.4.2/v1.4.5 rule); the rejected alternative — a screenshot of the window —
        would need a temporary window resize that must never reach the persisted
        geometry. `MapScene.itemsBoundingRect()` is therefore the ONE source of the
        content and the frame is the ONE thing this method adds.

        **The palette defaults to `theme.PALETTE_THEME` — the CURRENT look**, because a
        poster is read on screen: `PALETTE_PRINT` (the light page of every export) stays
        available for a caller that wants a printable one. The caller's palette is handed
        to the scoped `export_palette()` swap exactly like in `render_to_pixmap`, so an
        empty map, a DARK window and a palette override all go down the same path. The
        size is DETERMINISTIC: the same scene renders the same pixel size twice (the
        acceptance of the ROADMAP task).
        """
        from PySide6.QtGui import QPixmap, QColor

        scale = self.DOCS_FRAME_SCALE if scale is None else float(scale)
        padding = self.DOCS_FRAME_PADDING if padding is None else float(padding)
        frame_w = self.DOCS_FRAME_W if frame_w is None else float(frame_w)
        frame_h = self.DOCS_FRAME_H if frame_h is None else float(frame_h)

        with self.export_palette(palette):
            src = self.frame_source_rect(frame_w, frame_h, padding)
            w = max(int(frame_w * scale), 1)
            h = max(int(frame_h * scale), 1)
            pixmap = QPixmap(w, h)
            pixmap.fill(QColor(theme.RENDER_BG))  # the surface of the EXPORT palette

            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self.render(painter, target=QRectF(pixmap.rect()), source=src)
            painter.end()
            return pixmap

    def frame_source_rect(self, frame_w: float = None, frame_h: float = None,
                          padding: float = None) -> QRectF:
        """The source rect of the FIXED-frame render — PURE geometry, no painting.

        The map (plus the declared margin) is fitted into the frame's LOGICAL size and
        centred: a small map is scaled UP to the frame and a huge one DOWN, so the poster
        looks the same way for a 5-card demo and a 200-card production map, and the
        returned rect carries the FRAME's own proportions — the rendered poster is
        therefore edge-to-edge identical in shape to the declared 16:9 frame, with the
        map centred (the grid and the canvas background fill whatever the fit leaves
        free). An empty scene (`itemsBoundingRect()` is empty) falls back to the same
        `QRectF(-400, -300, 800, 600)` rect `render_to_pixmap` uses, so an empty map
        renders a framed poster instead of raising (the acceptance of the task).

        It is a public method of the scene (not a private helper) because it is the part
        the gate can measure without a render: the fit ratio, the centring and the
        determinism.
        """
        padding = self.DOCS_FRAME_PADDING if padding is None else float(padding)
        frame_w = self.DOCS_FRAME_W if frame_w is None else float(frame_w)
        frame_h = self.DOCS_FRAME_H if frame_h is None else float(frame_h)

        box = QRectF(self.itemsBoundingRect())
        if box.isEmpty():
            box = QRectF(-400, -300, 800, 600)
        box = box.adjusted(-padding, -padding, padding, padding)

        # ONE ratio per axis from the DECLARED frame, the larger one wins: the source rect
        # is the whole frame in scene units, so the render is never distorted (the content
        # keeps its proportions and the free axis just carries more canvas).
        ratio = max(box.width() / max(frame_w, 1.0), box.height() / max(frame_h, 1.0))
        vis_w = frame_w * ratio
        vis_h = frame_h * ratio

        # The scene is rendered with explicit target/source rects (`QGraphicsScene
        # .render`), i.e. the scene->view transform is the identity here, so the source
        # rect is the content centred on the frame.
        center = box.center()
        return QRectF(center.x() - vis_w / 2.0, center.y() - vis_h / 2.0, vis_w, vis_h)

    # ── v1.5rc2 (ROADMAP task 3): the PRINT-FRIENDLY export palette ──────────────

    @contextmanager
    def export_palette(self, palette=theme.PALETTE_PRINT):
        """Render the map under an EXPORT palette (v1.5rc2) — a scoped theme switch.

        `theme.export_theme(palette)` answers the instance (`print` = LIGHT with the
        user's hue, `theme` = the active one). When it differs from the active
        instance the scene swaps it and asks every item to re-read the theme — the
        SAME walk a theme switch uses (`_refresh_items_theme`), because a QBrush/QPen
        handed to an item is a VALUE. The restore is unconditional (`finally`), so an
        export can neither leak its palette into the window nor leave the map
        half-repainted; a `theme` export takes the cheap branch (no swap at all).

        Yields the instance, so a caller (the topical gate) can assert what was
        rendered. One place decides — the three render methods and the `.drawio`
        writer all go through `theme.export_theme()`.
        """
        instance = theme.export_theme(palette)
        previous = theme.current_theme()
        if instance is previous:
            yield instance
            return
        theme.set_theme(instance)
        try:
            self._refresh_items_theme()
            yield instance
        finally:
            theme.set_theme(previous)
            self._refresh_items_theme()

    # ── v1.4.2 (ROADMAP task 3): the shadow halos of the cards ────────────────────

    def set_shadows_visible(self, visible: bool):
        """Show/hide every card's shadow halo (v1.4.2) — the vector export needs it OFF.

        A shadow is a cached QPixmap (`ServerNode._shadow_pixmap`), and `QSvgGenerator`
        writes a pixmap item as a base64 PNG: leaving the halos on would turn the SVG
        into a partially raster file and break the v1.3.3.7 contract. PNG/PDF exports
        keep the halo. Idempotent, never raises.
        """
        for node in list(self._nodes.values()):
            setter = getattr(node, "set_shadow_visible", None)
            if callable(setter):
                try:
                    setter(visible)
                except RuntimeError:  # Qt teardown — the item is already destroyed
                    continue

    # ── v1.3.3.7: SVG export of the map (the vector member of the format set) ──────

    def render_to_svg(self, path: str, scale: float = 1.0,
                      padding: float = 60.0,
                      palette=theme.PALETTE_PRINT) -> int:
        """Render the whole map into an SVG file (v1.3.3.7) — the VECTOR export.

        Same composition as `render_to_pixmap`/`render_to_pdf`: the area is
        `itemsBoundingRect` (+padding) — the whole map, regardless of the current
        zoom/pan — and the scene paints itself through `QSvgGenerator`, so the
        canvas background and the grid arrive via `drawBackground` exactly like in
        the PDF one. `scale` only sets the DECLARED size of the drawing — `setSize`
        (written into the root `width`/`height`, in mm at the generator's default
        90 dpi) plus the matching `setViewBox`; the geometry itself stays vector, so
        a larger scale costs nothing in quality. No new dependencies: `QSvgGenerator`
        ships with PySide6 (QtSvg).

        Returns the file size in bytes. Raises OSError if the paint device did not
        start or the file was not created (the render_to_pdf error contract).

        v1.4.2 (ROADMAP task 3): the cards' shadow halos are HIDDEN while the scene is
        rendered — they are cached pixmaps, and `QSvgGenerator` would embed them as
        base64 PNGs, i.e. the "vector" member of the format set would stop being vector.
        PNG/PDF keep the halo (raster formats).

        v1.5rc2 (ROADMAP task 3): `palette` decides the look and defaults to the
        PRINT-FRIENDLY one (the LIGHT page with the high-contrast lines); a PNG/PDF/SVG
        export of a DARK window therefore leaves a light page, and `PALETTE_THEME` is
        the opt-out the export dialog offers. The swap is scoped (`export_palette`).
        """
        with self.export_palette(palette):
            return self._render_svg_file(path, scale, padding)

    def _render_svg_file(self, path: str, scale: float, padding: float) -> int:
        """The SVG render itself — the body of `render_to_svg` inside the palette scope."""
        import os

        from PySide6.QtCore import QRect, QSize
        from PySide6.QtGui import QPainter
        from PySide6.QtSvg import QSvgGenerator

        src = self.itemsBoundingRect().adjusted(
            -float(padding), -float(padding), float(padding), float(padding))
        if src.isEmpty():
            src = QRectF(-400, -300, 800, 600)

        w = max(int(src.width() * scale), 1)
        h = max(int(src.height() * scale), 1)

        generator = QSvgGenerator()
        generator.setFileName(path)
        generator.setSize(QSize(w, h))
        generator.setViewBox(QRect(0, 0, w, h))
        generator.setTitle("SSH Map")
        generator.setDescription("Infrastructure map exported from SSHMap")

        painter = QPainter(generator)
        if not painter.isActive():
            raise OSError(f"cannot start painting on SVG device: {path}")
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            # v1.4.2: the card shadows are cached PIXMAPS — a QGraphicsPixmapItem would be
            # embedded as a base64 PNG and the file would stop being fully vector
            # (the v1.3.3.7 contract). They are hidden for the duration of the export.
            self.set_shadows_visible(False)
            try:
                self.render(painter, target=QRectF(0, 0, w, h), source=src)
            finally:
                self.set_shadows_visible(True)
        finally:
            painter.end()

        if not os.path.isfile(path):
            raise OSError(f"SVG file was not created: {path}")
        return os.path.getsize(path)

    # ── v0.9.9.7: PDF export of the map (on top of render_to_pixmap) ───────────────
    # v1.3.3.7-fix: the geometry constants of that export (see render_to_pdf).
    PDF_PAGE_LONG_SIDE_PT = 1200.0     # the page's long side ≈ 42 cm — the map fills the page
    PDF_RESOLUTION_DPI = 300           # the PAINT DEVICE unit (QPdfWriter defaults to 1200 dpi!)
    PDF_RASTER_DPI = 150               # the floor density of the embedded map image

    def render_to_pdf(self, path: str, scale: float = 2.0, padding: float = 60.0,
                      palette=theme.PALETTE_PRINT) -> int:
        """Render the whole map into a PDF file (v0.9.9.7): one page for the entire map.

        On top of the ready `render_to_pixmap`: the whole map (itemsBoundingRect + the
        same `padding` as the pixmap/SVG exports) is stretched to ONE custom-sized page
        whose long side is `PDF_PAGE_LONG_SIDE_PT` (1200 pt ≈ 42 cm) and whose short side
        follows the map's proportions — so the map fills the page, without A4 "stripes".

        **v1.5rc2 (ROADMAP task 3):** `palette` is handed straight to `render_to_pixmap`,
        so the page is PRINT-FRIENDLY by default (a DARK window prints the LIGHT page
        with the high-contrast lines) and `theme.PALETTE_THEME` keeps the current look.

        **v1.3.3.7-fix — the two geometry defects of the v0.9.9.7 implementation** (found
        while verifying the export set; the old code produced a ~72 pt thumbnail in the
        corner of an 870×1200 pt page):
          * `QPdfWriter` paints in DEVICE PIXELS (`resolution()`, 1200 dpi by default),
            while the old draw target was expressed in POINTS — the map was drawn
            1/16.7 of its intended size. The device resolution is now set explicitly
            (`PDF_RESOLUTION_DPI`) and the map is drawn into the device's OWN rect.
          * `QPageLayout` TRANSPOSES a custom page size when the orientation is
            Landscape, so the old code turned a landscape map into a PORTRAIT page
            (and vice versa). The page size is now given in its portrait form and the
            orientation carries the map's proportions.
        Both are pinned by `tests/test_pdf_export.py` (page box + ink coverage).

        `scale` is the raster scale of the embedded image (the pixmap is `scale`× the
        scene size); independently of it, a map with content is rendered at least at
        `PDF_RASTER_DPI` for the 42 cm page — a three-node map no longer prints at
        ~40 dpi. The floor is bounded by construction (the page follows the map, so it
        always means ≈2500 px on the long side) and never lowers a bigger `scale`. An
        EMPTY scene keeps the cheap fallback rect (a blank page needs no 25 MB raster).

        The PDF device: `QPdfWriter` (QtGui; Qt 6.11+/PySide6 6.11 — the replacement
        for `QPdfPrinter`, mentioned in CHANGELOG v0.9.1) with a fallback to
        `QPdfPrinter` for older Qt 6.x (the same API, the file is set via
        setOutputFileName). No new dependencies.

        Returns the file size in bytes. Raises ValueError (a null pixmap) or
        OSError (the device did not start / the file was not created).
        """
        import os

        from PySide6.QtCore import QMarginsF, QRectF, QSizeF
        from PySide6.QtGui import QPageLayout, QPageSize, QPainter

        try:  # Qt 6.11+ (PySide6 6.11): QPdfPrinter was replaced by QPdfWriter
            from PySide6.QtGui import QPdfWriter as _PdfDevice
            device = _PdfDevice(path)
        except ImportError:  # older Qt 6.x — the original ROADMAP v0.9.9.7 plan
            from PySide6.QtGui import QPdfPrinter as _PdfDevice
            device = _PdfDevice()
            device.setOutputFileName(path)

        # The raster floor: the page is sized to the map, so without it a small map
        # would be blown up to 42 cm from a thumbnail-sized pixmap. The floor keeps the
        # long side at ≈ PDF_PAGE_LONG_SIDE_PT/72 * PDF_RASTER_DPI px for ANY scene size.
        effective_scale = float(scale)
        if self.items():
            src = self.itemsBoundingRect().adjusted(
                -float(padding), -float(padding), float(padding), float(padding))
            long_side = max(float(src.width()), float(src.height()))
            if long_side > 0:
                effective_scale = max(
                    effective_scale,
                    (self.PDF_PAGE_LONG_SIDE_PT / 72.0 * self.PDF_RASTER_DPI) / long_side)

        pixmap = self.render_to_pixmap(scale=effective_scale, padding=padding,
                                       palette=palette)
        if pixmap.isNull():
            raise ValueError("render_to_pixmap returned a null pixmap")

        k = self.PDF_PAGE_LONG_SIDE_PT / max(float(pixmap.width()), float(pixmap.height()))
        page_w = max(float(pixmap.width()) * k, 1.0)    # the FINAL (oriented) page, in points
        page_h = max(float(pixmap.height()) * k, 1.0)

        try:  # QPdfWriter (Qt 6.11+) — the resolution defines the paint device unit
            device.setResolution(self.PDF_RESOLUTION_DPI)
        except AttributeError:  # a device without setResolution — its own default applies
            pass
        # QPageLayout TRANSPOSES a custom size for Landscape: pass the portrait form.
        portrait = QSizeF(min(page_w, page_h), max(page_w, page_h))
        layout = QPageLayout(
            QPageSize(portrait, QPageSize.Unit.Point),
            QPageLayout.Orientation.Portrait if page_h >= page_w
            else QPageLayout.Orientation.Landscape,
            QMarginsF())  # zero margins: the map fills the whole page
        device.setPageLayout(layout)

        painter = QPainter(device)
        if not painter.isActive():
            raise OSError(f"cannot start painting on PDF device: {path}")
        try:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            # The target is the device's OWN rect (device pixels at device.resolution()),
            # never the page size in points — that confusion was the v1.3.3.7-fix bug.
            painter.drawPixmap(
                QRectF(0.0, 0.0, float(device.width()), float(device.height())),
                pixmap, QRectF(pixmap.rect()))
        finally:
            painter.end()

        if not os.path.isfile(path):
            raise OSError(f"PDF file was not created: {path}")
        return os.path.getsize(path)