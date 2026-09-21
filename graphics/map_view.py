from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QPointF

try:
    from .server_node import ServerNode
except ImportError:
    from server_node import ServerNode

try:
    from .connection_arrow import (
        build_curve, edge_point, type_color, DEFAULT_CONNECTION_TYPE, ConnectionArrow,
    )
except ImportError:
    from connection_arrow import (
        build_curve, edge_point, type_color, DEFAULT_CONNECTION_TYPE, ConnectionArrow,
    )

try:
    from .sticky_note import StickyNote  # v0.7.2
except ImportError:
    try:
        from sticky_note import StickyNote
    except ImportError:
        StickyNote = None

try:
    from .node_group import NodeGroup  # v0.8.1: node groups (clusters/folders)
except ImportError:
    try:
        from node_group import NodeGroup
    except ImportError:
        NodeGroup = None

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme


if TYPE_CHECKING:
    from ..graphics.map_scene import MapScene


from PySide6.QtCore import Qt, Signal, QRectF, QEvent
from PySide6.QtGui import (QPainter, QWheelEvent, QKeyEvent, QMouseEvent, QFocusEvent,
                           QBrush, QColor, QPen, QTransform)  # QTransform — v1.3.3.3 zoom step
from PySide6.QtWidgets import QGraphicsView, QGraphicsPathItem, QMenu


def _t(key: str) -> str:
    """Safe i18n hook (consistent with server_node/connection_arrow)."""
    try:
        from i18n import t as _translate
        return _translate(key)
    except Exception:
        return key


class MapView(QGraphicsView):
    """Map view: zoom, panning, and (v0.7) connection creation by dragging."""

    connect_drag_started = Signal()   # Shift-drag of a connection from a node has started
    connect_drag_finished = Signal()  # finished (connection created or cancelled)
    zoomChanged = Signal(float)       # UI polish: current zoom — for the % in the status bar
    # v0.8.3: node drag gesture finished (node, old_scene_pos, new_scene_pos)
    node_drag_committed = Signal(object, object, object)
    # v0.9.3: GROUP drag gesture finished — a list
    # [(node, old_pos: QPointF, new_pos: QPointF)] for a single undo command
    nodes_drag_committed = Signal(list)
    # v0.9.9.1: view resized (floating panels over the viewport —
    # search bar — are repositioned on window resize / splitter drag)
    resized = Signal()

    def __init__(self, scene: "MapScene", parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setBackgroundBrush(QBrush(QColor(theme.CANVAS_BG)))  # v1.2.5: central theme
        self._zoom = 1.0

        # ── Drag mode for connection creation (v0.7) ─────────────
        self._connect_source: Optional[ServerNode] = None
        self._rubber_band: Optional[QGraphicsPathItem] = None

        # v0.8.3: active node-move gesture (for the CmdMoveNode undo command)
        self._move_drag_node: Optional[ServerNode] = None
        self._move_drag_old = None  # QPointF — position before the gesture started

        # ── v0.9.3: multi-selection + group drag ──────────────
        # Selection rectangle (Ctrl+LMB on empty space): a QGraphicsRectItem in the scene.
        self._rubber_select_item = None          # the selection-rectangle item
        self._rubber_select_origin = None        # starting point in scene coords (QPointF)
        self._rubber_saved_selection = []        # selection at the start of the Ctrl-drag
        # Group drag: positions of all selected nodes before the gesture
        self._group_drag_olds = []               # [(node, QPointF), ...]

    def refresh_theme(self):
        """v1.4.3 (ROADMAP task 5): re-read the theme for the view.

        `MapScene.drawBackground` paints over the viewport, but the view's own
        background brush is what shows before the first `drawBackground` — it
        cached the canvas colour at construction. The scene, its items and the
        minimap panel are refreshed by `MainWindow.apply_theme()` (the minimap is
        a child of the view but is OWNED by the window), so this method handles
        only what the view itself paints.
        """
        self.setBackgroundBrush(QBrush(QColor(theme.CANVAS_BG)))
        self.viewport().update()

    # UI polish: allowed zoom range (shared by wheel, fit, and restore).
    ZOOM_MIN = 0.1
    ZOOM_MAX = 5.0
    # v1.3.3.3 (task 2): one keyboard step of the Zoom In / Zoom Out actions
    # (the wheel keeps its own cursor-anchored 1.15/0.87 factors).
    ZOOM_STEP = 1.25

    @property
    def zoom(self) -> float:
        """Current zoom factor (public access; AUDIT v0.7.2, low #19)."""
        return self._zoom

    def _notify_zoom(self):
        """UI polish: report the current zoom (status bar shows %)."""
        try:
            self.zoomChanged.emit(float(self._zoom))
        except RuntimeError:
            pass  # Qt teardown — slots are already destroyed (pattern from _sync_selection_state)

    def reset_zoom(self):
        """Reset zoom to 100% and clear the transform (AUDIT v0.7.2, low #19)."""
        self.resetTransform()
        self._zoom = 1.0
        self._notify_zoom()

    # v1.3.3.3 (ROADMAP v1.3.3.3, task 2): a step API next to reset_zoom()/
    # set_zoom_and_center() — the "View → Zoom In / Zoom Out" actions need a
    # keyboard-reachable zoom that does not depend on the pointer position.

    def zoom_in(self, step: float = None) -> bool:
        """Zoom in by ``step`` (default ``ZOOM_STEP``) around the view centre."""
        return self._zoom_by(self.ZOOM_STEP if step is None else step)

    def zoom_out(self, step: float = None) -> bool:
        """Zoom out by ``step`` (default ``ZOOM_STEP``) around the view centre."""
        return self._zoom_by(1.0 / float(self.ZOOM_STEP if step is None else step))

    def _zoom_by(self, factor: float) -> bool:
        """Scale around the CENTRE of the viewport, clamped to [ZOOM_MIN, ZOOM_MAX].

        The wheel anchors on the cursor (the natural zoom of a map); an explicit
        keyboard action must not depend on where the pointer happens to be, so the
        scene point under the CENTRE of the visible area stays put. That is done with
        one QTransform edit — translate the viewport matrix in DEVICE terms, then
        scale — instead of QGraphicsView.scale() + translate(): the latter composes
        translations in the pre-scale basis and the content drifts away (verified by
        the anchoring check of tests/test_actions_keyboard.py).

        The bounds are the wheel's own (0.1..5.0): a step that would leave them is
        refused (returns False) rather than silently squashed. ``_zoom`` and the real
        transform are kept in sync (the set_zoom_and_center rule).
        """
        try:
            factor = float(factor)
        except (TypeError, ValueError):
            return False
        if factor <= 0.0:
            return False
        target = self._zoom * factor
        if not (self.ZOOM_MIN <= target <= self.ZOOM_MAX):
            return False
        viewport = self.viewport()
        if viewport is None or viewport.width() <= 0 or viewport.height() <= 0:
            return False  # not shown yet — nothing to anchor on
        centre = QPointF(viewport.rect().center())    # a point in the VIEW coordinates
        before = self.transform().map(self.mapToScene(centre.toPoint()))
        transform = QTransform(self.transform())
        transform.translate(before.x(), before.y())
        transform.scale(factor, factor)
        transform.translate(-before.x(), -before.y())
        self.setTransform(transform)
        self._zoom = target
        self._notify_zoom()
        return True

    def resizeEvent(self, event):
        """v0.9.9.1: notify about a size change — floating panels over the viewport
        (the search bar) are repositioned on window resize and splitter drag."""
        super().resizeEvent(event)
        self.resized.emit()

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        zoom_factor = 1.15 if delta > 0 else 0.87
        new_zoom = self._zoom * zoom_factor
        if self.ZOOM_MIN < new_zoom < self.ZOOM_MAX:
            self._zoom = new_zoom
            self.scale(zoom_factor, zoom_factor)
            self._notify_zoom()

    # ── UI polish: "fit to content" and restoring the saved view ──

    def content_bounding_rect(self):
        """Combined boundingRect of nodes and notes (None if the map is empty)."""
        scene = self.scene()
        if scene is None:
            return None
        items = scene.nodes() if hasattr(scene, "nodes") else []
        items += [n for n in getattr(scene, "_notes", [])]
        rect = None
        for item in items:
            r = item.sceneBoundingRect()
            if r.isEmpty():
                continue
            rect = QRectF(r) if rect is None else rect.united(QRectF(r))
        return rect

    def fit_to_content(self, margin: float = 80.0) -> bool:
        """Fit the map content into the view area (KeepAspectRatio).

        Returns False if there is no content. Zoom is clamped to the
        [ZOOM_MIN, ZOOM_MAX] range like the wheel; _zoom is kept in sync with the transform.
        """
        rect = self.content_bounding_rect()
        if rect is None or rect.isEmpty():
            return False
        self.fitInView(rect.adjusted(-margin, -margin, margin, margin),
                       Qt.AspectRatioMode.KeepAspectRatio)
        # fitInView changes the transform behind _zoom — recompute and clamp
        target = float(self.transform().m11())
        if target < self.ZOOM_MIN or target > self.ZOOM_MAX:
            clamped = max(self.ZOOM_MIN, min(self.ZOOM_MAX, target))
            center = rect.center()
            self.resetTransform()
            self.translate(center.x(), center.y())
            self.scale(clamped, clamped)
            self.translate(-center.x(), -center.y())
            target = clamped
        self._zoom = target
        self._notify_zoom()
        return True

    def set_zoom_and_center(self, zoom: float, center_x: float, center_y: float):
        """Apply the zoom and center saved in the project (UI polish: previously ignored)."""
        try:
            z = float(zoom)
            cx = float(center_x)
            cy = float(center_y)
        except (TypeError, ValueError):
            return  # corrupt values from another file — keep the current view
        if not (self.ZOOM_MIN <= z <= self.ZOOM_MAX):
            z = max(self.ZOOM_MIN, min(self.ZOOM_MAX, z))
        self.resetTransform()
        self.scale(z, z)
        self._zoom = z
        self.centerOn(cx, cy)
        self._notify_zoom()

    # ── v0.7.2: dynamic drag mode (dragging nodes/notes) ──
    # Under ScrollHandDrag a left drag ALWAYS pans the canvas — items with
    # ItemIsMovable do not move with the mouse (verified empirically). So on
    # press over a movable object we temporarily switch to NoDrag, and
    # after release we restore ScrollHandDrag.

    def _item_at_scene(self, scene_pos):
        if self.scene() is None:
            return None
        return self.scene().itemAt(scene_pos, self.transform())

    @staticmethod
    def _is_movable_item(item) -> bool:
        """Whether item (or its parent group) is a movable object."""
        while item is not None:
            if isinstance(item, ServerNode):
                return True  # ItemIsMovable — standard Qt drag in NoDrag mode
            if StickyNote is not None and isinstance(item, StickyNote):
                return True  # manual move in the note's own mousePressEvent
            if NodeGroup is not None and isinstance(item, NodeGroup):  # v0.8.1: groups
                return True  # manual move in the group's own mousePressEvent (note pattern)
            item = item.parentItem()
        return False

    def _find_node_at(self, scene_pos) -> Optional[ServerNode]:
        """ServerNode under the scene point (accounting for group child elements)."""
        if self.scene() is None:
            return None
        item = self.scene().itemAt(scene_pos, self.transform())
        while item is not None:
            if isinstance(item, ServerNode):
                return item
            item = item.parentItem()
        return None

    def _classify_at(self, scene_pos):
        """Return (node, arrow, note) — the topmost object of each kind under the point."""
        node = arrow = note = None
        if self.scene() is None:
            return node, arrow, note
        for item in self.scene().items(scene_pos):
            # arrow — directly (it has no parent groups)
            if arrow is None and isinstance(item, ConnectionArrow):
                arrow = item
            n = item
            while n is not None:
                if node is None and isinstance(n, ServerNode):
                    node = n
                    break
                if note is None and StickyNote is not None and isinstance(n, StickyNote):
                    note = n
                    break
                n = n.parentItem()
        return node, arrow, note

    def _cancel_connect_drag(self):
        """Remove the rubber band and reset the drag-mode state."""
        if self._rubber_band is not None and self._rubber_band.scene() is not None:
            self._rubber_band.scene().removeItem(self._rubber_band)
        self._rubber_band = None
        self._connect_source = None
        self.unsetCursor()

    def mousePressEvent(self, event: QMouseEvent):
        # Shift+LMB on a node → create a connection by dragging (v0.7).
        # Don't pass the event on: the node doesn't move and panning doesn't start.
        if (event.button() == Qt.LeftButton
                and bool(event.modifiers() & Qt.ShiftModifier)
                and self._connect_source is None):
            # PySide6/Qt6 mapToScene doesn't bind the QPointF version — use QPoint
            scene_pos = self.mapToScene(event.position().toPoint())
            node = self._find_node_at(scene_pos)
            if node is not None:
                self._connect_source = node
                pen = QPen(type_color(DEFAULT_CONNECTION_TYPE), 2, Qt.DashLine)
                self._rubber_band = QGraphicsPathItem()
                self._rubber_band.setPen(pen)
                self._rubber_band.setZValue(100)
                if self.scene() is not None:
                    self.scene().addItem(self._rubber_band)
                self.setCursor(Qt.CrossCursor)
                self.connect_drag_started.emit()
                return
        # v0.7.2: press over a movable object (node/note) — temporary NoDrag,
        # otherwise ScrollHandDrag would swallow the gesture into panning and nothing would move.
        if event.button() == Qt.LeftButton and self._connect_source is None:
            scene_pos = self.mapToScene(event.position().toPoint())
            if self._is_movable_item(self._item_at_scene(scene_pos)):
                self.setDragMode(QGraphicsView.NoDrag)
            # v0.8.3: node-move gesture starts — remember the initial position
            node = self._find_node_at(scene_pos)
            if node is not None:
                self._move_drag_node = node
                from PySide6.QtCore import QPointF
                self._move_drag_old = QPointF(node.pos())
                # v0.9.3: if the node is already part of a multi-selection — this is a GROUP
                # drag (all selected move). Pre-gesture positions — for undo.
                if node.isSelected() and len([i for i in self.scene().selectedItems()
                                              if isinstance(i, ServerNode)]) > 1:
                    self._group_drag_olds = [
                        (n, QPointF(n.pos()))
                        for n in self.scene().selectedItems()
                        if isinstance(n, ServerNode)
                    ]
                else:
                    self._group_drag_olds = []
            # v0.9.3: Ctrl+LMB on empty space → selection rectangle (rubber band).
            elif bool(event.modifiers() & Qt.ControlModifier):
                from PySide6.QtWidgets import QGraphicsRectItem
                self._start_rubber_select(scene_pos,
                                          event.modifiers() & Qt.ShiftModifier)
                return  # don't start panning
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._connect_source is not None and self._rubber_band is not None:
            scene_pos = self.mapToScene(event.position().toPoint())
            # v1.4.2 (ROADMAP task 4): the band starts on the CARD edge (card_rect_scene),
            # not on the shadow halo-inflated boundingRect.
            _rect_fn = getattr(self._connect_source, "card_rect_scene", None)
            src_rect = _rect_fn() if callable(_rect_fn) else self._connect_source.sceneBoundingRect()
            p0 = edge_point(src_rect, src_rect.center(), scene_pos)
            path, _, _ = build_curve(p0, scene_pos)
            self._rubber_band.setPath(path)
        # v0.9.3: update the selection rectangle
        elif self._rubber_select_item is not None:
            scene_pos = self.mapToScene(event.position().toPoint())
            self._update_rubber_select(scene_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        # v0.9.3: selection rectangle finished — commit the selection
        if self._rubber_select_item is not None and event.button() == Qt.LeftButton:
            self._finish_rubber_select()
            return  # the press wasn't passed to Qt — we consume the release too
        if (self._connect_source is not None and event.button() == Qt.LeftButton):
            source = self._connect_source
            scene_pos = self.mapToScene(event.position().toPoint())
            target = self._find_node_at(scene_pos)
            self._cancel_connect_drag()
            self.connect_drag_finished.emit()
            if target is not None and target is not source:
                # MainWindow creates the connection via a pre-filled dialog (type + label).
                win = self.window()
                if hasattr(win, "_add_connection"):
                    win._add_connection(
                        default_source_id=source.data.id,
                        default_target_id=target.data.id,
                    )
            return  # the press wasn't passed to Qt — so we take the release too
        # v0.7.2: gesture over a movable object finished — restore panning
        if self.dragMode() == QGraphicsView.NoDrag:
            # v0.8.3: the node actually moved — notify the window (CmdMoveNode command)
            node = getattr(self, "_move_drag_node", None)
            if node is not None:
                old = getattr(self, "_move_drag_old", None)
                self._move_drag_node = None
                self._move_drag_old = None
                try:
                    new = node.pos()
                    if old is not None and (abs(new.x() - old.x()) > 0.5
                                            or abs(new.y() - old.y()) > 0.5):
                        # v0.9.3: group drag → ONE command for all selected;
                        # single drag → the previous signal with one node.
                        olds = getattr(self, "_group_drag_olds", [])
                        self._group_drag_olds = []
                        moved = [(n, o, QPointF(n.pos())) for n, o in olds
                                 if n.scene() is not None]
                        if len(moved) > 1 and any(
                                abs(n.pos().x() - o.x()) > 0.5 or abs(n.pos().y() - o.y()) > 0.5
                                for n, o, _ in moved):
                            self.nodes_drag_committed.emit(moved)
                        elif abs(new.x() - old.x()) > 0.5 or abs(new.y() - old.y()) > 0.5:
                            self.node_drag_committed.emit(node, old, QPointF(new))
                except RuntimeError:
                    pass  # Qt teardown — the gesture didn't finish normally, no command will be issued
            else:
                self._group_drag_olds = []
            self.setDragMode(QGraphicsView.ScrollHandDrag)
        super().mouseReleaseEvent(event)

    # ── v1.1.2RC2 (N3): resetting "stuck" drag state on focus loss ──
    # The only regular reset is mouseReleaseEvent; but if the capture is lost
    # without a release (Alt+Tab / window activation change mid-drag), the release
    # never arrives and the view stays in NoDrag with a live _move_drag_node:
    # the next left drag behaves unpredictably. Focus/activation loss is the
    # same symptom, so we restore ScrollHandDrag and clean up the gesture state
    # (idempotent: with no active drag both conditions are false — nothing
    # changes). In Qt "blur" is QFocusEvent(FocusOut) → focusOutEvent (QWidget
    # has no separate blurEvent, verified on PySide6 6.11); window activation
    # change — changeEvent.

    def _reset_stuck_drag_state(self):
        """Reset an unfinished drag gesture: ScrollHandDrag + state cleanup."""
        if self._move_drag_node is not None or self.dragMode() == QGraphicsView.NoDrag:
            self._move_drag_node = None
            self._move_drag_old = None
            self._group_drag_olds = []
            self.setDragMode(QGraphicsView.ScrollHandDrag)

    def focusOutEvent(self, event: QFocusEvent):
        """v1.1.2RC2 (N3): focus loss ("blur") — the capture may have been lost, the release won't come."""
        self._reset_stuck_drag_state()
        super().focusOutEvent(event)

    def changeEvent(self, event: QEvent):
        """v1.1.2RC2 (N3): window activation change — the same stuck path as blur."""
        if event.type() == QEvent.Type.ActivationChange:
            self._reset_stuck_drag_state()
        super().changeEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if self._rubber_select_item is not None:
            # Esc during the selection rectangle — cancel without changing the selection
            self._finish_rubber_select()
            return
        if self._connect_source is not None:
            # Any key during drag mode (incl. Esc/Delete) — cancels the drag;
            # we intentionally do NOT delete nodes here.
            self._cancel_connect_drag()
            self.connect_drag_finished.emit()
            return
        if event.key() == Qt.Key_Delete:
            # Delete the selected node (patch v0.6.x / v0.7.3: single guarded path —
            # confirmation + waiting for SSHWorker to finish before remove_server)
            scene = self.scene()
            node = None
            note = None
            group = None  # v0.8.1: selected group (cluster/folder)
            for item in scene.selectedItems() if scene else []:
                if isinstance(item, ServerNode):
                    node = item
                elif StickyNote is not None and isinstance(item, StickyNote):
                    note = item  # there may be several — take the first
                elif NodeGroup is not None and isinstance(item, NodeGroup):
                    group = item  # v0.8.1: take the first selected group
            if node:
                win = self.window()
                if hasattr(win, "_remove_node_guarded"):
                    win._remove_node_guarded(node)
                else:  # fallback for scenes without MainWindow (tests/external hosts)
                    scene.remove_server(node.data.id)
                    parent_widget = self.parent()
                    if hasattr(parent_widget, 'refresh_sidebar'):
                        parent_widget.refresh_sidebar()
            elif note is not None:
                # v0.7.2: selected note — a lightweight object, deleted without
                # confirmation. (If focus is inside its QTextEdit, keys don't reach
                # the view — Delete erases characters, not the note.)
                win = self.window()
                if hasattr(win, "_remove_note"):
                    win._remove_note(note)
                elif scene is not None:
                    scene.remove_note(note.note_id)
            elif group is not None and NodeGroup is not None:
                # v0.8.1: selected group — lightweight (servers stay on the map),
                # deleted without confirmation, like a note.
                win = self.window()
                if hasattr(win, "_remove_group"):
                    win._remove_group(group)
                elif scene is not None and hasattr(scene, "remove_group"):
                    scene.remove_group(group)
        super().keyPressEvent(event)

    # ── v0.7.2/v0.7.3: context menu on the map (RMB) ─────────────

    @staticmethod
    def _event_point(event):
        """Event position as a QPoint, in a version-agnostic form.

        Qt6/PySide6: events have position() (QPointF) and legacy pos(); across
        binding versions either one or the other may be available — try both.
        """
        position = getattr(event, "position", None)
        if callable(position):
            try:
                return position().toPoint()
            except Exception:
                pass  # legacy binding without position() — event.pos() below
        return event.pos()

    @classmethod
    def _event_global_point(cls, event):
        """Event global position as a QPoint (for QMenu.exec)."""
        global_position = getattr(event, "globalPosition", None)
        if callable(global_position):
            try:
                return global_position().toPoint()
            except Exception:
                pass  # legacy binding without globalPosition() — event.globalPos() below
        return event.globalPos()

    # ── v0.9.3: selection rectangle (Ctrl+LMB on empty space) ─────────

    def _start_rubber_select(self, scene_pos, additive: bool = False):
        """Start drawing the selection rectangle. Shift adds to the current
        selection; without Shift it replaces the selection."""
        from PySide6.QtWidgets import QGraphicsRectItem
        self._rubber_select_origin = scene_pos
        self._rubber_saved_selection = list(self.scene().selectedItems()) \
            if additive else []
        pen = QPen(QColor(theme.ACCENT), 0)  # v1.2.5: theme accent; cosmetic pen — thickness is zoom-independent
        self._rubber_select_item = QGraphicsRectItem()
        self._rubber_select_item.setPen(pen)
        _rubber_fill = QColor(theme.ACCENT)        # v1.2.5: ACCENT + alpha (selection-rectangle fill)
        _rubber_fill.setAlpha(30)
        self._rubber_select_item.setBrush(QBrush(_rubber_fill))
        self._rubber_select_item.setZValue(200)
        self.scene().addItem(self._rubber_select_item)
        self.setCursor(Qt.CrossCursor)

    def _update_rubber_select(self, scene_pos):
        """Update the rectangle geometry + live selection of intersecting nodes.

        v1.2.10rc3 (AUDIT auto #9): a full O(n) walk of ALL scene elements on every
        mouse move — scene.items() also returns QGraphicsItemGroup children, so with
        500 nodes that's ~6.5k elements, each with isinstance + (for nodes)
        sceneBoundingRect/intersects → direct walk of scene.nodes(): the SAME set
        of ServerNodes (the old isinstance filter picked exactly them), but without
        the ~6k group child elements. Measured ~3x faster than the full walk
        (tests/_bench_rubber.py, CHANGELOG v1.2.10rc3).

        The ROADMAP-suggested `scene().items(rect)` (Qt spatial index)
        was MEASURED and REJECTED: on Qt 6.11.1/PySide6 6.11.1 the per-candidate
        overhead is ~2.6 us, so a rectangle covering the whole map cost 15.6 ms versus
        0.9 ms for a plain walk of ALL elements — slower than the OLD code (the win
        only for small rectangles). The want-criterion is unchanged: intersecting OR
        in the base selection (Shift additive mode, _rubber_saved_selection) — the
        result is identical to v1.2.10rc2."""
        origin = self._rubber_select_origin
        rect = QRectF(origin, scene_pos).normalized()
        self._rubber_select_item.setRect(rect)
        # live: highlight the nodes under the rectangle right during the drag
        base_ids = {id(n) for n in getattr(self, "_rubber_saved_selection", [])}
        scene = self.scene()
        nodes = scene.nodes() if hasattr(scene, "nodes") \
            else [i for i in scene.items() if isinstance(i, ServerNode)]
        for node in nodes:
            hit = rect.intersects(node.sceneBoundingRect())
            want = hit or (id(node) in base_ids)
            if node.isSelected() != want:
                node.setSelected(want)

    def _finish_rubber_select(self):
        """Remove the rectangle; the final selection was already set in _update_rubber_select."""
        if self._rubber_select_item is not None:
            sc = self._rubber_select_item.scene()
            if sc is not None:
                sc.removeItem(self._rubber_select_item)
            self._rubber_select_item = None
        self._rubber_select_origin = None
        self._rubber_saved_selection = []
        self.unsetCursor()

    def contextMenuEvent(self, event):
        """RMB: empty space — add note/server; object — actions on it."""
        scene = self.scene()
        if scene is None:
            super().contextMenuEvent(event)
            return
        scene_pos = self.mapToScene(self._event_point(event))
        menu = self.build_context_menu(scene_pos)

        if not menu.isEmpty():
            # AUDIT v0.7.2 (medium #9): we don't swallow exceptions wholesale — a bare "pass"
            # silently turned any error into "the menu simply didn't open". Coordinates are
            # already converted to QPoint by the explicit helper above; if something still
            # goes wrong, let it be visible (log + traceback), not invisible.
            try:
                menu.exec(self._event_global_point(event))
            except Exception as e:  # noqa: BLE001 — a GUI component must not crash the app
                # v1.0-fix (audit #11): logger instead of print to stderr, like the rest of the code.
                try:
                    from modules.logger import get_logger
                    get_logger(__name__).error(f"contextMenuEvent: menu.exec failed: {e}")
                except Exception:  # noqa: BLE001 — a logger failure must not break the context menu
                    pass
        else:
            super().contextMenuEvent(event)

    def build_context_menu(self, scene_pos):
        """The node/note/arrow/empty-space context menu for a scene point.

        v1.4rc3: extracted from `contextMenuEvent()` so the composition is reachable
        WITHOUT showing the menu — the project's test-seam convention for QMenu
        (`tests/test_context_menus.py`: no `menu.exec()` in a test, the QActions are
        triggered directly). The returned QMenu owns its QActions; the caller shows it
        and must keep the wrapper alive until then (the gotcha #9 pattern).
        """
        scene = self.scene()
        if scene is None:
            return QMenu(self)
        win = self.window()
        node, arrow, note = self._classify_at(scene_pos)
        menu = QMenu(self)

        if note is not None and StickyNote is not None:
            # v1.2.4: attachment to a server (drag onto a node — primary path, menu — fallback).
            # Item order: [Attach… / Detach] → [Delete note].
            if hasattr(win, "_attach_note_to_node") or hasattr(win, "_detach_note"):
                if getattr(note, "server_id", None):
                    act_det = menu.addAction(_t("ctx.note_detach"))
                    def _det(checked=False, n=note):  # checked — a bool from triggered (v0.8.1 pitfall)
                        w = self.window()
                        if hasattr(w, "_detach_note"):
                            w._detach_note(n)
                    act_det.triggered.connect(_det)
                else:
                    target = node  # the node under the cursor (from _classify_at above)
                    if target is None and hasattr(scene, "get_selected_node"):
                        target = scene.get_selected_node()
                    if target is not None:
                        act_att = menu.addAction(_t("ctx.note_attach_to").format(
                            alias=(target.data.alias or target.data.host or target.data.id)))
                        def _att(checked=False, n=note, tnode=target):
                            w = self.window()
                            if hasattr(w, "_attach_note_to_node"):
                                w._attach_note_to_node(n, tnode)
                        act_att.triggered.connect(_att)
                    elif scene.nodes():
                        sub = menu.addMenu(_t("ctx.note_attach"))
                        for srv in scene.nodes():
                            label = (srv.data.alias or srv.data.host or srv.data.id)
                            act_s = sub.addAction(label)
                            def _atts(checked=False, n=note, tnode=srv):
                                w = self.window()
                                if hasattr(w, "_attach_note_to_node"):
                                    w._attach_note_to_node(n, tnode)
                            act_s.triggered.connect(_atts)
            # Note (v0.7.2): editing is via double-click; here only deletion
            act_del = menu.addAction(_t("ctx.delete_note"))
            # v0.8.1: QAction.triggered passes a bool `checked` as the first argument —
            # without an explicit parameter it would clobber the closure n (crash in _remove_note).
            def _del_note(checked=False, n=note):
                w = self.window()
                if hasattr(w, "_remove_note"):
                    w._remove_note(n)
                elif scene is not None:
                    scene.remove_note(n.note_id)
            act_del.triggered.connect(_del_note)

        # ── v0.7.3: node context menu ──────────────────────────
        if node is not None:
            win_node = node  # local reference for closures
            # v1.0RC4: Quick launch — the FIRST item (above "Connect via SSH").
            # Submenu: node.data.quick_launch items + separator + "Configure…".
            # No items — only "Configure…" (discoverability). The hasattr pattern is
            # the same as for the other actions: MapView doesn't know about MainWindow.
            if hasattr(win, "_run_quick_launch_entry") or \
                    hasattr(win, "_open_quick_launch_dialog"):
                ql_entries = list(getattr(win_node.data, "quick_launch", None) or [])
                ql_sub = menu.addMenu(_t("ctx.quick_launch"))
                for e in ql_entries:
                    if not hasattr(win, "_run_quick_launch_entry"):
                        break
                    act_ql = ql_sub.addAction(str(e.get("name") or e.get("value") or "?"))
                    def _ql(checked=False, n=win_node, en=e):  # checked — a bool from triggered
                        w = self.window()
                        if hasattr(w, "_run_quick_launch_entry"):
                            w._run_quick_launch_entry(n, en)
                    act_ql.triggered.connect(_ql)
                if ql_entries:
                    ql_sub.addSeparator()
                if hasattr(win, "_open_quick_launch_dialog"):
                    act_qc = ql_sub.addAction(_t("ql.configure"))
                    def _ql_cfg(checked=False, n=win_node):  # checked — a bool from triggered
                        w = self.window()
                        if hasattr(w, "_open_quick_launch_dialog"):
                            w._open_quick_launch_dialog(n)
                    act_qc.triggered.connect(_ql_cfg)
                menu.addSeparator()  # Quick launch is separated from the node's "main" menu
            if hasattr(win, "_connect_ssh_to_selected"):
                act_ssh = menu.addAction(_t("ctx.ssh_connect"))
                # v0.8.1: the first parameter is a bool `checked` from QAction.triggered;
                # without it PySide calls _ssh(True), clobbering the win_node closure
                # (crash in MainWindow._select_node: 'bool' object has no attribute 'setSelected').
                def _ssh(checked=False, n=win_node):
                    w = self.window()
                    w._select_node(n)          # the SSH dialog takes the selected node
                    w._connect_ssh_to_selected()
                act_ssh.triggered.connect(_ssh)
            # v0.8.2: connection in the OS system terminal
            if hasattr(win, "_connect_ssh_external"):
                act_ext = menu.addAction(_t("ctx.ssh_external"))
                def _ssh_ext(checked=False, n=win_node):  # checked — a bool from triggered
                    w = self.window()
                    w._select_node(n)
                    w._connect_ssh_external(n)
                act_ext.triggered.connect(_ssh_ext)
            if hasattr(win, "_edit_node"):
                act_edit = menu.addAction(_t("ctx.edit_server"))
                act_edit.triggered.connect(lambda _=False, n=win_node: self.window()._edit_node(n))
            # v0.9: automatic server-info collection (Linux) over SSH
            if hasattr(win, "_collect_node_info"):
                act_info = menu.addAction(_t("ctx.collect_info"))
                act_info.triggered.connect(
                    lambda _=False, n=win_node: self.window()._collect_node_info(n))
            # v0.8.4 (former DESIGN.md §D): collapse/expand the badge
            if hasattr(win_node, "toggle_collapsed"):
                act_col = menu.addAction(
                    _t("ctx.expand_server") if getattr(win_node.data, "collapsed", False)
                    else _t("ctx.collapse_server"))
                act_col.triggered.connect(lambda _=False, n=win_node: self._toggle_and_mark(n))
            menu.addSeparator()
            if hasattr(win, "_copy_node_info"):
                act_ip = menu.addAction(_t("ctx.copy_ip"))
                act_ip.triggered.connect(lambda _=False, n=win_node: self.window()._copy_node_info(n, "ip"))
                act_host = menu.addAction(_t("ctx.copy_hostname"))
                act_host.triggered.connect(lambda _=False, n=win_node: self.window()._copy_node_info(n, "hostname"))
                act_ping = menu.addAction(_t("ctx.ping"))
                act_ping.triggered.connect(lambda _=False, n=win_node: self.window()._ping_node(n))
            # v1.3.3.3 (ROADMAP task 5): "Check statuses now" — one on-demand round for
            # the SELECTION (the clicked node when nothing is selected). The probes stay
            # off the GUI thread (StatusChecker.start_round → _ProbeThread); the action
            # is registered (an empty default) and appears in the sidebar menu too.
            if hasattr(win, "_check_statuses_now"):
                act_status = menu.addAction(_t("ctx.check_status"))
                act_status.triggered.connect(
                    lambda _=False, n=win_node: self.window()._check_statuses_now(n))
            menu.addSeparator()
            if hasattr(win, "_duplicate_node"):
                # v0.9.3: node duplication (copy of fields + keyring password under a new id)
                act_dup = menu.addAction(_t("ctx.duplicate_server"))
                act_dup.triggered.connect(
                    lambda _=False, n=win_node: self.window()._duplicate_node(n))
            if hasattr(win, "_remove_node_guarded"):
                act_delnode = menu.addAction(_t("ctx.delete_server"))
                act_delnode.triggered.connect(
                    lambda _=False, n=win_node: self.window()._remove_node_guarded(n))
            # ── v1.4rc3 (plugin foundation, task 7): the plugin rows ──────────────
            # The frozen API v1 contract (`PLUGINS.md` §3) gives a plugin
            # `extend_node_context_menu(menu, nodes)`: the manager calls it
            # synchronously on the GUI thread (200 ms budget, "never throws") and
            # hands over the live QMenu plus the narrowed node records — never the
            # scene objects. The call sits LAST in the node block, so a plugin's
            # rows live under the built-in ones; `_extend_node_context_menu()`
            # re-runs the QAction guard (a plugin's QAction wrapper must outlive
            # the Python frame that created it — gotcha #9).
            if hasattr(win, "_extend_node_context_menu"):
                fn = getattr(win, "_extend_node_context_menu")
                try:
                    fn(menu, win_node)
                except Exception as e:  # noqa: BLE001 — a plugin must not break the menu
                    try:
                        from modules.logger import get_logger
                        get_logger(__name__).warning(f"plugin context menu failed: {e}")
                    except Exception:  # noqa: BLE001
                        pass

        # ── v0.9.3: group operations on multi-selection ─────────
        if node is not None and hasattr(win, "selected_nodes"):
            try:
                multi = len([i for i in scene.selectedItems()
                             if isinstance(i, ServerNode)]) > 1
            except RuntimeError:
                multi = False
            if multi:
                menu.addSeparator()
                if hasattr(win, "_connect_selected_nodes"):
                    act_conn = menu.addAction(_t("edit.connect_selected"))
                    def _conn_sel(checked=False):  # checked — a bool from triggered
                        w = self.window()
                        if hasattr(w, "_connect_selected_nodes"):
                            w._connect_selected_nodes()
                    act_conn.triggered.connect(_conn_sel)
                if hasattr(win, "_delete_selected_nodes"):
                    act_delmulti = menu.addAction(_t("edit.delete_selected"))
                    def _del_sel(checked=False):
                        w = self.window()
                        if hasattr(w, "_delete_selected_nodes"):
                            w._delete_selected_nodes()
                    act_delmulti.triggered.connect(_del_sel)

        # ── v0.7.3: arrow (connection) context menu ───────────────
        if arrow is not None and node is None:
            win_arrow = arrow
            if hasattr(win, "_edit_connection"):
                act_editc = menu.addAction(_t("ctx.edit_connection"))
                act_editc.triggered.connect(
                    lambda _=False, a=win_arrow: self.window()._edit_connection(a))
            if hasattr(win, "_remove_connection"):
                act_delconn = menu.addAction(_t("ctx.delete_connection"))
                act_delconn.triggered.connect(
                    lambda _=False, a=win_arrow: self.window()._remove_connection(a))

        if node is None and arrow is None:
            # Empty space (v0.7.2 — note; at the click point). A group under the point (v0.8.1):
            # actions on it are appended below — a click on a folder's "background" selects it too.
            if hasattr(win, "_add_server"):
                p = scene_pos
                act_srv = menu.addAction(_t("btn.add_server"))
                # v0.8.1: `checked` — a bool from QAction.triggered; it used to clobber
                # the closure p, and MainWindow._add_server received True instead of the click point.
                def _add_server(checked=False, p=p):
                    w = self.window()
                    fn = getattr(w, "_add_server", None)
                    if callable(fn):
                        try:
                            fn(p)  # the click-point position (the signature accepts it optionally)
                        except TypeError:
                            fn()
                act_srv.triggered.connect(_add_server)
            if hasattr(win, "_add_note_at"):
                p = scene_pos
                act_note = menu.addAction(_t("ctx.add_note"))
                def _add_note(checked=False, p=p):  # v0.8.1: see _add_server above
                    w = self.window()
                    if hasattr(w, "_add_note_at"):
                        w._add_note_at(p)
                act_note.triggered.connect(_add_note)
            if NodeGroup is not None and hasattr(win, "_add_group_at"):
                # v0.8.1: new group at the click point (nodes under the rectangle will be captured automatically)
                p = scene_pos
                act_grp = menu.addAction(_t("ctx.add_group"))
                def _add_group(checked=False, p=p):  # v0.8.1: checked — see above
                    w = self.window()
                    fn = getattr(w, "_add_group_at", None)
                    if callable(fn):
                        try:
                            fn(p)
                        except TypeError:
                            fn()
                act_grp.triggered.connect(_add_group)

            # ── v0.8.1: group context menu (click on its background/title) ──
            grp = None
            scene_obj = self.scene()
            if NodeGroup is not None and scene_obj is not None \
                    and hasattr(scene_obj, "find_group_at"):
                grp = scene_obj.find_group_at(scene_pos)
            if grp is not None:
                win_grp = grp  # local reference for closures (node/arrow pattern above)
                menu.addSeparator()
                act_rg = menu.addAction(_t("ctx.rename_group"))
                def _rename(checked=False, g=win_grp):  # v0.8.1: checked — a bool from triggered
                    w = self.window()
                    if hasattr(w, "_rename_group"):
                        w._rename_group(g)
                act_rg.triggered.connect(_rename)
                # v1.4.2 (ROADMAP task 5): the fold — the mirror of the title-band chevron.
                # The window owns the action (it pushes CmdToggleGroupCollapse).
                try:
                    _folded = bool(grp.is_collapsed())
                except (AttributeError, RuntimeError):
                    _folded = False
                act_fold = menu.addAction(
                    _t("ctx.expand_group") if _folded else _t("ctx.collapse_group"))
                def _fold(checked=False, g=win_grp):  # checked — a bool from triggered
                    w = self.window()
                    if hasattr(w, "_toggle_group_collapsed"):
                        w._toggle_group_collapsed(g)
                act_fold.triggered.connect(_fold)
                act_dg = menu.addAction(_t("ctx.delete_group"))
                def _del_grp(checked=False, g=win_grp):  # v0.8.1: checked — a bool from triggered
                    w = self.window()
                    if hasattr(w, "_remove_group"):
                        w._remove_group(g)
                    elif scene is not None and hasattr(scene, "remove_group"):
                        scene.remove_group(g)
                act_dg.triggered.connect(_del_grp)

        return menu

    def _toggle_and_mark(self, node):
        """v0.8.4 (former DESIGN.md §D): toggle_collapsed + mark the project as modified."""
        node.toggle_collapsed()
        w = self.window()
        if hasattr(w, "_mark_dirty"):
            w._mark_dirty()
