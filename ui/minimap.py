# -*- coding: utf-8 -*-
"""v1.4.2 (ROADMAP task 1): the minimap — the big-picture level of the map.

A small panel floating over the canvas (a CHILD of `MapView`, outside the layout — the
`MapSearchBar` pattern: it is never a scene item, so it stays out of the exports, out of
a rubber-band selection and out of `itemsBoundingRect`). It draws the whole scheme at
fit scale — nodes as blocks coloured by status, notes, the group frames, the background
image — plus a frame around the part of the map the view is currently showing, and it
moves the view when clicked or dragged.

The pinned constraints (decision 2026-09-11):
  * **no text** and no arrows — the panel is a SHAPE, not a second sidebar. **v1.4.6
    narrows this to the map AREA:** the panel now carries a vertical TITLE BAND
    (`minimap.title`, "Minimap", rotated — the one word that names the panel, the
    `legend.title` precedent), and that band is also its collapse affordance;
  * **cheap rendering** — the scene is walked ONCE per change burst (a restart-guarded
    200 ms debounce) into a flat `[(QRectF, QColor)]` layer; a paint only applies ONE
    transform and draws those rects. There are no per-node QGraphicsItems (the v1.2.10
    audit: 500 cards must not cost 500 extra items);
  * **two-way synchronization** — the viewport frame follows `resized` / `zoomChanged` /
    both scrollbars, and a click/drag emits `center_requested(QPointF)`. The widget owns
    no camera logic: `MainWindow` decides where the view goes (the same split as the
    search bar, which owns no search logic).

**v1.4.6 — the vertical band and the side collapse.** The panel is
`[map area | title band]`; a click on the band folds the panel sideways to the RIGHT
(the map area disappears, the band stays — the LegendWidget gesture rotated by 90°,
so the two floating panels are collapsed the same way: by clicking their title). The
state is the `ui_minimap_collapsed` key, written by the WINDOW (the widget only reports
the change on `collapsed_changed`, and the window re-places the panel because its width
changed — it is anchored to the right edge). v1.5rc5 (N6): the anchor holds with a SAVED
position too — `MainWindow._position_minimap()` shifts that x by the width delta, so a
fold of a MOVED panel keeps the band on the right edge and the unfold round trip is
lossless (before, the saved top-left was used verbatim and the band jumped
`BODY_WIDTH` = 200 px to the left).

**v1.4.6, part two — the panel is MOVABLE (the legend's drag, disambiguated by a HOLD).**
The body of the minimap already owns two gestures the mouse cannot tell apart at press
time: a click/drag PANS the camera (v1.4.2) and a drag should MOVE the panel (the legend
does it with a plain drag in its body). The pinned resolution is a **long press**: hold
the left button for `MOVE_HOLD_MS` (400 ms) without moving and the panel enters MOVE
mode — the cursor turns into `SizeAllCursor`, the frame lights up in the accent colour,
and every move drags the PANEL (clamped inside the view) instead of the camera; the
release reports `moved(QPoint)` so the WINDOW can persist `ui_minimap_position` (the
`ui_legend_position` precedent). Everything else stays exactly as it was:
  * a press that MOVES already (`MOVE_THRESHOLD_PX`) is a camera pan at once — no wait;
  * a short press-and-release is the v1.4.2 click (the view jumps to that point);
  * the title band keeps its own gesture (a click folds/unfolds), so a folded strip is
    unfolded first and moved after — the band is never a drag handle.

The module is i18n-light: the tooltip and the band title, resolved at construction and
in `retranslate()`.
"""

from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath,
                           QPen, QTransform)
from PySide6.QtWidgets import QWidget

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from . import theme
except ImportError:
    try:
        from ui import theme
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        import theme


def _t(key: str) -> str:
    """Safe i18n hook (the map_search_bar / server_node pattern)."""
    try:
        from i18n import t as _translate
        return _translate(key)
    except Exception:
        return key


class MinimapWidget(QWidget):
    """The map at fit scale + a viewport frame; a click or a drag moves the view.

    Signals:
        center_requested(QPointF) — the scene point the view should be centered on
        (emitted on press and on every drag step; the receiver clamps and calls
        `MapView.centerOn`);
        collapsed_changed(bool) — v1.4.6: the panel folded/unfolded through its title
        band (the window persists `ui_minimap_collapsed` and re-places the panel, whose
        width just changed);
        moved(QPoint) — v1.4.6: a MOVE gesture (a long press, then a drag) finished at
        this position inside the view (the window persists `ui_minimap_position`; the
        widget has already moved itself — the LegendWidget contract).
    """

    center_requested = Signal(QPointF)
    collapsed_changed = Signal(bool)
    moved = Signal(QPoint)

    BODY_WIDTH = 200             # the map area — the v1.4.2 panel size, kept
    HEADER_W = 20                # v1.4.6: the vertical title band on the RIGHT (also the collapsed width)
    DEFAULT_WIDTH = BODY_WIDTH + HEADER_W   # the panel's total width (map area + band)
    DEFAULT_HEIGHT = 150
    MARGIN = 6.0                 # the inset of the content inside the map area
    PADDING = 6                  # the inset of the title/chevron inside the band
    REBUILD_MS = 200             # the debounce of the scene-changed rebuild
    MOVE_HOLD_MS = 400           # v1.4.6: hold this long to start MOVING the panel
    MOVE_THRESHOLD_PX = 4        # a smaller movement is jitter: neither a pan nor a drag
    RADIUS = float(theme.RADIUS_SEARCH_BAR)   # the panel's corner radius (one style with the search bar)
    VIEWPORT_FILL_ALPHA = 40     # the translucent accent fill of the viewport frame
    OUTLINE_WIDTH = 1.0          # cosmetic pen width of the group/background frames

    def __init__(self, view, parent=None):
        super().__init__(parent if parent is not None else view)
        self._view = view
        self._items = []              # [(QRectF scene, QColor, filled: bool)] — the cached layer
        self._content = QRectF()      # the union of the layer (the fit source)
        self._collapsed = False       # v1.4.6: the side fold (the window persists it)
        # v1.4.6: the three gestures of one left button. `_press_pending` — the button is
        # down and nothing has been decided yet (a move or the hold timer settles it);
        # `_pan_active` — a camera pan; `_move_active` — the panel itself is being moved.
        self._press_pending = False
        self._pan_active = False
        self._move_active = False
        self._press_pos = QPoint(0, 0)
        self._drag_offset = QPoint(0, 0)

        self.setObjectName("MinimapWidget")
        self._font = self._make_font(-1.0)
        self._bold = self._make_font(-1.0, bold=True)
        self._title = _t("minimap.title")
        self._apply_size()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(_t("minimap.tooltip"))

        # The rebuild is debounced by a RESTART-GUARDED single-shot timer: a burst of
        # change signals (a drag, a paste, a project load) costs ONE walk, and starting
        # the timer only while it is idle is what keeps a continuous drag from starving it.
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(self.REBUILD_MS)
        self._rebuild_timer.timeout.connect(self.refresh)

        # v1.4.6: the HOLD detector — a single-shot timer started on every body press and
        # stopped by any real movement (a pan) or by the release (a click).
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(self.MOVE_HOLD_MS)
        self._hold_timer.timeout.connect(self._on_hold)

        self.refresh()
        self._connect_view()

    def _make_font(self, delta: float, bold: bool = False) -> QFont:
        """The band's font: the UI font one point smaller, optionally bold (the legend)."""
        font = QFont(self.font())
        try:
            font.setPointSizeF(max(font.pointSizeF() + delta, 7.0))
        except (TypeError, ValueError):  # pragma: no cover — a font without a point size
            pass
        font.setBold(bool(bold))
        return font

    # ── The side fold (v1.4.6) ──────────────────────────────────────────────────

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool) -> None:
        """Fold/unfold the panel sideways. Emits `collapsed_changed` on a real change.

        Folded: the panel is the title band alone (HEADER_W wide, the height kept), so a
        collapsed minimap is a thin vertical strip on the right edge of the map — it
        takes no room but stays a click away, exactly like the legend's title band.
        """
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._apply_size()
        self.update()
        try:
            self.collapsed_changed.emit(collapsed)
        except RuntimeError:
            pass  # Qt teardown — the receiver is gone

    def _apply_size(self):
        """Fix the widget's size: the map area + the band, or the band alone."""
        width = self.HEADER_W if self._collapsed else self.DEFAULT_WIDTH
        self.setFixedSize(int(width), int(self.DEFAULT_HEIGHT))

    def body_rect(self) -> QRectF:
        """The map area in widget coordinates (EMPTY while the panel is folded)."""
        return QRectF(0.0, 0.0, max(float(self.width()) - self.HEADER_W, 0.0),
                      float(self.height()))

    def header_rect(self) -> QRectF:
        """The title band (the fold affordance) — the RIGHT edge of the panel."""
        return QRectF(max(float(self.width()) - self.HEADER_W, 0.0), 0.0,
                      float(self.HEADER_W), float(self.height()))


    # ── Wiring (the widget follows its view; the window only places and toggles it) ──

    def _connect_view(self):
        """Follow the viewport: scene changes (debounced), zoom, resize and both scrollbars."""
        try:
            scene = self._view.scene()
            if scene is not None:
                scene.changed.connect(self._on_scene_changed)
            self._view.zoomChanged.connect(lambda *_a: self.update())
            self._view.resized.connect(self.update)
            for bar in (self._view.horizontalScrollBar(), self._view.verticalScrollBar()):
                if bar is not None:
                    bar.valueChanged.connect(lambda *_a: self.update())
        except (AttributeError, RuntimeError):
            pass  # a view without signals (a stand-in in a test) — the layer still rebuilds on demand

    def _on_scene_changed(self, *_args):
        """Any scene change: schedule ONE rebuild (never restart an already pending one)."""
        if not self._rebuild_timer.isActive():
            self._rebuild_timer.start()

    # ── The cached layer ────────────────────────────────────────────────────────

    def refresh(self):
        """Rebuild the cached layer from the scene (ONE walk; called by the debounce).

        Draw order = list order: the group frames and the background first, then the
        notes, then the nodes (so a card is never hidden by its own group). Every rect
        is stored in SCENE coordinates — the paint applies the fit transform.
        """
        scene = self._view.scene()
        items = []
        content = QRectF()

        def _add(rect, color, filled=True):
            nonlocal content
            try:
                r = QRectF(rect)
            except (TypeError, ValueError):
                return
            if r.isEmpty() or r.width() <= 0.0 or r.height() <= 0.0:
                return
            items.append((r, QColor(color), bool(filled)))
            content = QRectF(r) if content.isEmpty() else content.united(r)

        if scene is not None:
            # Groups: an OUTLINE frame (violet, one style with the map)
            for grp in getattr(scene, "groups", lambda: [])():
                try:
                    _add(grp.sceneBoundingRect(), theme.GROUP_BORDER, False)
                except RuntimeError:  # Qt teardown — the item is gone
                    continue
            # The background image: an outline too (it is a floor plan, not a block)
            try:
                bg = scene.background() if hasattr(scene, "background") else None
                if bg is not None:
                    _add(bg.sceneBoundingRect(), theme.SURFACE_ALT, False)
            except RuntimeError:
                pass
            # Notes: a filled block in the sticky color
            for note in getattr(scene, "notes", lambda: [])():
                try:
                    _add(note.sceneBoundingRect(), theme.NOTE_BG)
                except RuntimeError:
                    continue
            # Nodes: the CARD rect (never the shadow halo — a halo would inflate every
            # dot), coloured by status; an unchecked card uses the node border color.
            for node in getattr(scene, "nodes", lambda: [])():
                try:
                    rect_fn = getattr(node, "card_rect_scene", None)
                    rect = rect_fn() if callable(rect_fn) else node.sceneBoundingRect()
                    status = getattr(node, "status", "") or ""
                    color = theme.STATUS_COLORS.get(status, theme.NODE_BORDER)
                    _add(rect, color)
                except RuntimeError:
                    continue

        self._items = items
        self._content = content
        self.update()

    # ── Geometry ────────────────────────────────────────────────────────────────

    def fit(self):
        """(scale, offset_x, offset_y) mapping SCENE → WIDGET, or None with an empty map.

        KeepAspectRatio with a `MARGIN` inset, centered: the whole scheme fills the map
        AREA (the panel without its title band) as far as its proportions allow. A folded
        panel has no map area at all — the fit is None, exactly like an empty map.
        """
        rect = self._content
        body = self.body_rect()
        if rect.isEmpty() or rect.width() <= 0.0 or rect.height() <= 0.0 or body.isEmpty():
            return None
        avail_w = max(body.width() - 2.0 * self.MARGIN, 1.0)
        avail_h = max(body.height() - 2.0 * self.MARGIN, 1.0)
        scale = min(avail_w / rect.width(), avail_h / rect.height())
        if scale <= 0.0:
            return None
        offset_x = (body.width() - rect.width() * scale) / 2.0 - rect.left() * scale
        offset_y = (body.height() - rect.height() * scale) / 2.0 - rect.top() * scale
        return scale, offset_x, offset_y

    def _transform(self):
        fit = self.fit()
        if fit is None:
            return None
        scale, offset_x, offset_y = fit
        return QTransform().translate(offset_x, offset_y).scale(scale, scale)

    def scene_point_at(self, point):
        """The SCENE point under a widget point (None when the map is empty).

        The inverse of the fit transform — the public seam the topical test uses to
        prove that a click asks for the right place.
        """
        fit = self.fit()
        if fit is None:
            return None
        scale, offset_x, offset_y = fit
        if scale <= 0.0:
            return None
        return QPointF((float(point.x()) - offset_x) / scale,
                       (float(point.y()) - offset_y) / scale)

    def viewport_scene_rect(self):
        """The scene rect the view currently shows (None if the view is unusable)."""
        try:
            viewport = self._view.viewport()
            if viewport is None or viewport.width() <= 0 or viewport.height() <= 0:
                return None
            return QRectF(self._view.mapToScene(viewport.rect()).boundingRect())
        except (AttributeError, RuntimeError):
            return None

    def viewport_frame(self):
        """The viewport frame in WIDGET coordinates (None if either rect is unavailable)."""
        fit = self.fit()
        vp = self.viewport_scene_rect()
        if fit is None or vp is None:
            return None
        scale, offset_x, offset_y = fit
        return QRectF(vp.left() * scale + offset_x, vp.top() * scale + offset_y,
                      vp.width() * scale, vp.height() * scale)

    # ── Rendering ───────────────────────────────────────────────────────────────

    def item_count(self) -> int:
        """How many rects the cached layer holds (the topical test's seam)."""
        return len(self._items)

    def content_rect(self) -> QRectF:
        """The union of the cached layer, in scene coordinates."""
        return QRectF(self._content)

    def refresh_theme(self):
        """v1.4.3 (ROADMAP task 5): re-read the theme for the panel.

        The widget paints from the live theme (the panel card, the viewport
        frame), but the CACHED LAYER holds resolved QColor objects — one per node
        (`STATUS_COLORS` / `NOTE_BG` / the group frame) — so a theme switch has
        to rebuild it, exactly like a scene change does (only without the
        debounce: the switch is one event).
        """
        self.refresh()
        self.update()

    def paintEvent(self, event):
        w, h = float(self.width()), float(self.height())
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            # The panel: WINDOW_BG card + a SURFACE_ALT frame (one style with the search
            # bar). Painted by hand — the content is clipped to the rounded shape.
            # v1.4.6: while the MOVE gesture is active the frame turns accent — the one
            # affordance that says "you are moving the panel, not the view".
            path = QPainterPath()
            path.addRoundedRect(QRectF(1.0, 1.0, max(w - 2.0, 1.0), max(h - 2.0, 1.0)),
                                self.RADIUS, self.RADIUS)
            if self._move_active:
                painter.setPen(QPen(QColor(theme.ACCENT), 1.6))
            else:
                painter.setPen(QPen(QColor(theme.SURFACE_ALT), 1.0))
            painter.setBrush(QBrush(QColor(theme.WINDOW_BG)))
            painter.drawPath(path)
            painter.setClipPath(path)

            # The map area (v1.4.6: everything left of the title band; nothing while folded).
            transform = self._transform()
            if transform is not None:
                # The layer: ONE transform, then the cached rects as they are.
                painter.save()
                painter.setTransform(transform)
                for rect, color, filled in self._items:
                    if filled:
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(QBrush(color))
                    else:
                        pen = QPen(color, self.OUTLINE_WIDTH)
                        pen.setCosmetic(True)  # a frame stays 1 px at any fit scale
                        painter.setPen(pen)
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(rect)
                painter.restore()

                # The viewport frame — in WIDGET coordinates (a constant 1.4 px line and a
                # translucent fill, so it reads at any scale).
                frame = self.viewport_frame()
                if frame is not None:
                    fill = QColor(theme.ACCENT)
                    fill.setAlpha(self.VIEWPORT_FILL_ALPHA)
                    painter.setBrush(QBrush(fill))
                    painter.setPen(QPen(QColor(theme.ACCENT), 1.4))
                    painter.drawRect(frame)

            # The vertical title band — always painted (folded or not): it is the panel's
            # name AND its fold affordance.
            self._paint_header(painter, w, h)
        finally:
            painter.end()

    def _paint_header(self, painter, w: float, h: float) -> None:
        """The vertical title band on the right: the rotated title + the fold chevron."""
        cx = w - self.HEADER_W / 2.0
        chevron_room = 2.0 * self.PADDING + 8.0
        # The title reads BOTTOM-TO-TOP (the usual vertical-tab convention): the painter
        # is rotated -90° around the middle of the free part of the band, so the local
        # x axis runs up the screen and the local y axis runs right.
        painter.save()
        painter.translate(cx, (h + chevron_room) / 2.0)
        painter.rotate(-90.0)
        painter.setFont(self._bold)
        painter.setPen(QPen(QColor(theme.TEXT_PRIMARY)))
        fm = QFontMetrics(self._bold)
        length = max(h - chevron_room - 2.0 * self.PADDING, 1.0)
        painter.drawText(
            QRectF(-length / 2.0, -self.HEADER_W / 2.0, length, float(self.HEADER_W)),
            int(Qt.AlignmentFlag.AlignCenter),
            fm.elidedText(self._title, Qt.TextElideMode.ElideRight, int(length)))
        painter.restore()

        # The chevron at the TOP of the band: it points RIGHT while the panel is open
        # (the fold goes to the right) and LEFT while it is folded (the way back).
        cy = self.PADDING + 4.0
        path = QPainterPath()
        if self._collapsed:
            path.moveTo(cx + 2.0, cy - 4.0)
            path.lineTo(cx - 2.5, cy)
            path.lineTo(cx + 2.0, cy + 4.0)
        else:
            path.moveTo(cx - 2.0, cy - 4.0)
            path.lineTo(cx + 2.5, cy)
            path.lineTo(cx - 2.0, cy + 4.0)
        painter.setPen(QPen(QColor(theme.TEXT_MUTED), 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    # ── Interaction (the view moves; the widget only asks) ──────────────────────

    @staticmethod
    def _event_point(event):
        """The event position as a QPoint (the MapView._event_point pattern: pos()/position())."""
        position = getattr(event, "position", None)
        if callable(position):
            try:
                return position().toPoint()
            except Exception:  # noqa: BLE001 — an older binding without position()
                pass
        return event.pos()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        point = self._event_point(event)
        # v1.4.6: a click on the title band folds/unfolds the panel — the band is NEVER a
        # drag handle (a folded strip is unfolded first, moved after).
        if self.header_rect().contains(float(point.x()), float(point.y())):
            self.set_collapsed(not self._collapsed)
            event.accept()
            return
        # The map area: the button goes down and NOTHING is decided yet — a real movement
        # makes it a camera pan (v1.4.2), a release makes it a click (also a pan), and the
        # HOLD timer makes it "move the panel" (v1.4.6).
        self._press_pos = point
        self._press_pending = True
        self._pan_active = False
        self._move_active = False
        self._hold_timer.start()
        event.accept()

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        point = self._event_point(event)
        if self._move_active:
            self._drag_panel_to(point)
            event.accept()
            return
        if self._press_pending:
            if (point - self._press_pos).manhattanLength() < self.MOVE_THRESHOLD_PX:
                event.accept()   # jitter — not a gesture yet
                return
            # A real drag: it is the v1.4.2 camera pan (the hold is off the table).
            self._hold_timer.stop()
            self._press_pending = False
            self._pan_active = True
        if self._pan_active:
            self._emit_center(point)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and (
                self._press_pending or self._pan_active or self._move_active):
            point = self._event_point(event)
            self._hold_timer.stop()
            if self._move_active:
                self._move_active = False
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                self.update()
                try:
                    self.moved.emit(QPoint(self.pos()))   # the window persists it
                except RuntimeError:
                    pass  # Qt teardown — the receiver is gone
            elif self._press_pending:
                # A short press: the v1.4.2 click — the view jumps to that point. It is
                # emitted HERE (not on the press) so that holding cannot move the camera.
                self._emit_center(point)
            self._press_pending = False
            self._pan_active = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ── The MOVE gesture (v1.4.6: a long press, then a drag) ─────────────────────

    def is_moving(self) -> bool:
        """True while the panel itself is being dragged (the move gesture is active)."""
        return self._move_active

    def _on_hold(self):
        """The press was HELD long enough: from here on the mouse moves the PANEL.

        The camera is deliberately NOT touched (the pan emission waits for the release),
        so a hold that turns into a move never jumps the view.
        """
        if not self._press_pending or self._move_active:
            return
        self._press_pending = False
        self._pan_active = False
        self._move_active = True
        self._drag_offset = self._press_pos
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.raise_()
        self.update()   # the frame lights up in the accent colour

    def _drag_panel_to(self, point):
        """Move the panel by the drag delta, clamped inside its parent (the view)."""
        target = self.pos() + (point - self._drag_offset)
        parent = self.parentWidget()
        if parent is not None:
            target.setX(min(max(target.x(), 0), max(parent.width() - self.width(), 0)))
            target.setY(min(max(target.y(), 0), max(parent.height() - self.height(), 0)))
        self.move(target)

    def _emit_center(self, point):
        scene_point = self.scene_point_at(point)
        if scene_point is not None:
            try:
                self.center_requested.emit(scene_point)
            except RuntimeError:
                pass  # Qt teardown — the receiver is gone

    # ── i18n ────────────────────────────────────────────────────────────────────

    def retranslate(self):
        """Re-read the widget's two strings (the tooltip and the band title)."""
        self.setToolTip(_t("minimap.tooltip"))
        self._title = _t("minimap.title")
        self.update()
