# -*- coding: utf-8 -*-
"""v1.4.2 (ROADMAP task 1): the minimap — the big-picture level of the map.

A small panel floating over the canvas (a CHILD of `MapView`, outside the layout — the
`MapSearchBar` pattern: it is never a scene item, so it stays out of the exports, out of
a rubber-band selection and out of `itemsBoundingRect`). It draws the whole scheme at
fit scale — nodes as blocks coloured by status, notes, the group frames, the background
image — plus a frame around the part of the map the view is currently showing, and it
moves the view when clicked or dragged.

The pinned constraints (decision 2026-09-11):
  * **no text** and no arrows — the panel is a SHAPE, not a second sidebar;
  * **cheap rendering** — the scene is walked ONCE per change burst (a restart-guarded
    200 ms debounce) into a flat `[(QRectF, QColor)]` layer; a paint only applies ONE
    transform and draws those rects. There are no per-node QGraphicsItems (the v1.2.10
    audit: 500 cards must not cost 500 extra items);
  * **two-way synchronization** — the viewport frame follows `resized` / `zoomChanged` /
    both scrollbars, and a click/drag emits `center_requested(QPointF)`. The widget owns
    no camera logic: `MainWindow` decides where the view goes (the same split as the
    search bar, which owns no search logic).

The module is i18n-light: only the tooltip is translated, at construction and in
`retranslate()`.
"""

from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QTransform
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
        `MapView.centerOn`).
    """

    center_requested = Signal(QPointF)

    DEFAULT_WIDTH = 200
    DEFAULT_HEIGHT = 150
    MARGIN = 6.0                 # the inset of the content inside the panel
    REBUILD_MS = 200             # the debounce of the scene-changed rebuild
    RADIUS = float(theme.RADIUS_SEARCH_BAR)   # the panel's corner radius (one style with the search bar)
    VIEWPORT_FILL_ALPHA = 40     # the translucent accent fill of the viewport frame
    OUTLINE_WIDTH = 1.0          # cosmetic pen width of the group/background frames

    def __init__(self, view, parent=None):
        super().__init__(parent if parent is not None else view)
        self._view = view
        self._items = []              # [(QRectF scene, QColor, filled: bool)] — the cached layer
        self._content = QRectF()      # the union of the layer (the fit source)
        self._dragging = False

        self.setObjectName("MinimapWidget")
        self.setFixedSize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(_t("minimap.tooltip"))

        # The rebuild is debounced by a RESTART-GUARDED single-shot timer: a burst of
        # change signals (a drag, a paste, a project load) costs ONE walk, and starting
        # the timer only while it is idle is what keeps a continuous drag from starving it.
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(self.REBUILD_MS)
        self._rebuild_timer.timeout.connect(self.refresh)

        self.refresh()
        self._connect_view()

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

        KeepAspectRatio with a `MARGIN` inset, centered: the whole scheme fills the panel
        as far as its proportions allow.
        """
        rect = self._content
        if rect.isEmpty() or rect.width() <= 0.0 or rect.height() <= 0.0:
            return None
        avail_w = max(float(self.width()) - 2.0 * self.MARGIN, 1.0)
        avail_h = max(float(self.height()) - 2.0 * self.MARGIN, 1.0)
        scale = min(avail_w / rect.width(), avail_h / rect.height())
        if scale <= 0.0:
            return None
        offset_x = (float(self.width()) - rect.width() * scale) / 2.0 - rect.left() * scale
        offset_y = (float(self.height()) - rect.height() * scale) / 2.0 - rect.top() * scale
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
            path = QPainterPath()
            path.addRoundedRect(QRectF(1.0, 1.0, max(w - 2.0, 1.0), max(h - 2.0, 1.0)),
                                self.RADIUS, self.RADIUS)
            painter.setPen(QPen(QColor(theme.SURFACE_ALT), 1.0))
            painter.setBrush(QBrush(QColor(theme.WINDOW_BG)))
            painter.drawPath(path)
            painter.setClipPath(path)

            transform = self._transform()
            if transform is None:
                return  # an empty map: the empty panel is the whole story (no text)

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
        finally:
            painter.end()

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
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._emit_center(self._event_point(event))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and (event.buttons() & Qt.MouseButton.LeftButton):
            self._emit_center(self._event_point(event))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging = False
        super().mouseReleaseEvent(event)

    def _emit_center(self, point):
        scene_point = self.scene_point_at(point)
        if scene_point is not None:
            try:
                self.center_requested.emit(scene_point)
            except RuntimeError:
                pass  # Qt teardown — the receiver is gone

    # ── i18n ────────────────────────────────────────────────────────────────────

    def retranslate(self):
        """Re-read the only translatable string of the widget (the tooltip)."""
        self.setToolTip(_t("minimap.tooltip"))
