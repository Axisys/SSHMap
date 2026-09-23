# -*- coding: utf-8 -*-
"""v1.4.5 (ROADMAP task 4): the map legend — a small floating panel over the canvas.

The map distinguishes six connection types by colour and three availability statuses
by the colour of the card's dot, and until now the only way to learn a colour was to
open a dialog and compare. The legend names them in one place: the six arrow types
(`theme.ARROW_TYPE_COLORS`, the SAME declaration order the connection dialog uses) and
the three statuses (`theme.STATUS_COLORS`).

The pinned decisions (ROADMAP v1.4.5, task 4 — "pinned at start"):

  * **a widget over the scene, never a scene item** — like the minimap and the search
    bar it is a CHILD of `MapView`, so it is invisible to the exports, to a rubber-band
    selection, to `itemsBoundingRect()` and to "fit to content";
  * **collapsible** — a click on the title band folds the panel down to that band
    (the state is remembered in `config.json`, so a collapsed legend stays collapsed);
  * **movable and remembered** — the panel can be dragged anywhere inside the view and
    the position is persisted (`ui_legend_position`); with no saved position it sits in
    the bottom-left corner, the one corner the minimap (top-right) and the map-collapse
    diamond (bottom-right) leave free;
  * **the colours are read LIVE from the theme** — a theme switch repaints the panel
    through `refresh_theme()` (the swatches are `theme.ARROW_TYPE_COLORS` /
    `theme.STATUS_COLORS`, both live properties of the active `Theme`).

The widget owns its OWN geometry (a drag is a gesture inside its parent); the WINDOW
owns visibility, the config round-trip and the clamping on a view resize — the same
split as the minimap (`center_requested`) and the search bar.
"""

from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from . import theme
except ImportError:
    try:
        from ui import theme
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        import theme

try:  # v1.5rc2 (ROADMAP task 4): the declared status shapes — the row's shape sample
    from . import status_shape
except ImportError:
    try:
        from ui import status_shape
    except ImportError:  # flat layout without ui/status_shape — the v1.4.5 colour swatch
        status_shape = None


def _t(key: str, **kw) -> str:
    """Safe i18n hook (the map_search_bar / minimap pattern); kwargs are formatted."""
    try:
        from i18n import t as _translate
        return _translate(key, **kw)
    except Exception:
        return key


class LegendWidget(QWidget):
    """The legend panel: the 6 connection types + the 3 statuses, collapsible, draggable.

    Signals:
        collapsed_changed(bool) — the panel folded/unfolded (the window persists it);
        moved(QPoint) — a drag finished at this position inside the view (the window
        persists it; the widget has already moved itself).
    """

    collapsed_changed = Signal(bool)
    moved = Signal(QPoint)

    WIDTH = 172              # the panel's fixed width
    HEADER_H = 20            # the title band (also the collapsed height)
    ROW_H = 16               # one legend row
    SECTION_H = 16           # a section caption ("Connections" / "Statuses")
    PADDING = 6              # the inner inset of the card
    SWATCH = 9               # the colour square of a row (the fallback sample)
    SWATCH_GAP = 8           # the gap between the swatch and its label
    SECTION_GAP = 3          # the extra space above a section caption
    # v1.5rc2 (ROADMAP task 4): the row's SAMPLE — the panel explains the second
    # channel too. The sample box is a fixed slot (a 26 px line / a mark inside it),
    # so the labels of both sections stay aligned.
    SAMPLE_W = 26
    SAMPLE_MARK = 11
    RADIUS = float(theme.RADIUS_SEARCH_BAR)   # one style with the search bar / minimap

    def __init__(self, view, parent=None):
        super().__init__(parent if parent is not None else view)
        self._view = view
        self._collapsed = False
        self._dragging = False
        self._drag_offset = QPoint(0, 0)

        self.setObjectName("LegendWidget")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(_t("legend.tooltip"))

        self._font = self._make_font(-1.0)
        self._bold = self._make_font(-1.0, bold=True)
        self._section_font = self._make_font(-2.0, bold=True)
        self._labels = {}        # i18n key -> translated text (rebuilt by retranslate)
        self._rebuild_labels()
        self.setFixedWidth(self.WIDTH)
        self._apply_height()

    # ── Text (cached; the paint path never calls i18n) ───────────────────────

    def _make_font(self, delta: float, bold: bool = False) -> QFont:
        """The panel's font: the UI font one (or two) points smaller, optionally bold."""
        font = QFont(self.font())
        try:
            font.setPointSizeF(max(font.pointSizeF() + delta, 7.0))
        except (TypeError, ValueError):  # pragma: no cover - a font without a point size
            pass
        font.setBold(bool(bold))
        return font

    def rows(self) -> list:
        """The panel's body as data: [(kind, i18n key, theme colour), …].

        `kind` is "section" (a caption) or "item" (a swatch + a label). The ORDER is
        the theme's — the same dicts the map itself paints from, so a new connection
        type added to `Theme.arrow_type_colors` shows up here without an edit.
        """
        out = [("section", "legend.connections", None)]
        for ctype, color in theme.ARROW_TYPE_COLORS.items():
            out.append(("item", f"connection.type.{ctype}", color))
        out.append(("section", "legend.statuses", None))
        for status, color in theme.STATUS_COLORS.items():
            out.append(("item", f"legend.status.{status}", color))
        return out

    def _rebuild_labels(self):
        """Resolve every label of the panel once (the paint path stays i18n-free)."""
        self._labels = {}
        for kind, key, _color in self.rows():
            self._labels[key] = _t(key)

    def row_sample(self, kind: str, key: str, color):
        """The SAMPLE a row draws beside its label (v1.5rc2, ROADMAP task 4).

        Read from the SAME declaration the map paints from — `theme.ARROW_TYPE_STYLES`
        for a connection type, `theme.STATUS_SHAPES` for a status — so the panel
        explains the second channel (the dash pattern / the width / the double rail,
        the shape) and can never drift from the map. A section caption and an unknown
        row answer None. The colour is the row's own colour, never a second lookup.

        Returns a dict: ``{"kind": "line", "color", "style"}`` or
        ``{"kind": "shape", "color", "status", "shape"}``.
        """
        if kind != "item":
            return None
        prefix = "connection.type."
        if key.startswith(prefix):
            ctype = key[len(prefix):]
            return {"kind": "line", "color": color,
                    "style": theme.arrow_type_style(ctype)}
        prefix = "legend.status."
        if key.startswith(prefix):
            status = key[len(prefix):]
            return {"kind": "shape", "color": color, "status": status,
                    "shape": theme.status_shape(status)}
        return None

    def retranslate(self):
        """Re-read the panel's strings (language switch)."""
        self.setToolTip(_t("legend.tooltip"))
        self._rebuild_labels()
        self.update()

    # ── Geometry ─────────────────────────────────────────────────────────────

    def body_height(self) -> int:
        """The height of the body (0 while collapsed)."""
        if self._collapsed:
            return 0
        height = 0
        for kind, _key, _color in self.rows():
            height += self.SECTION_H + self.SECTION_GAP if kind == "section" else self.ROW_H
        return height + self.PADDING

    def _apply_height(self):
        """Fix the widget's height to the header (+ the body while expanded)."""
        self.setFixedHeight(self.HEADER_H + self.body_height())

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool) -> None:
        """Fold/unfold the panel. Emits `collapsed_changed` only on a real change."""
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._apply_height()
        self.update()
        try:
            self.collapsed_changed.emit(collapsed)
        except RuntimeError:
            pass  # Qt teardown — the receiver is gone

    def header_rect(self) -> QRectF:
        """The clickable title band (the collapse affordance)."""
        return QRectF(0.0, 0.0, float(self.width()), float(self.HEADER_H))

    # ── Interaction ──────────────────────────────────────────────────────────

    @staticmethod
    def _event_pos(event):
        """The event position as a QPoint (the minimap/MapView `pos()` vs `position()` pattern)."""
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
        point = self._event_pos(event)
        if self.header_rect().contains(float(point.x()), float(point.y())):
            self.set_collapsed(not self._collapsed)
            event.accept()
            return
        self._dragging = True
        self._drag_offset = point
        self.raise_()
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._dragging or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        point = self._event_pos(event)
        target = self.pos() + (point - self._drag_offset)
        parent = self.parentWidget()
        if parent is not None:
            max_x = max(parent.width() - self.width(), 0)
            max_y = max(parent.height() - self.height(), 0)
            target.setX(min(max(target.x(), 0), max_x))
            target.setY(min(max(target.y(), 0), max_y))
        self.move(target)
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            try:
                self.moved.emit(QPoint(self.pos()))
            except RuntimeError:
                pass  # Qt teardown — the receiver is gone
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ── Rendering ────────────────────────────────────────────────────────────

    def refresh_theme(self):
        """Re-read the theme: every colour of the panel is resolved in `paintEvent`."""
        self.update()

    def paintEvent(self, event):
        w, h = float(self.width()), float(self.height())
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            # The card: WINDOW_BG + a SURFACE_ALT frame — one style with the minimap
            # and the search bar.
            path = QPainterPath()
            path.addRoundedRect(QRectF(1.0, 1.0, max(w - 2.0, 1.0), max(h - 2.0, 1.0)),
                                self.RADIUS, self.RADIUS)
            painter.setPen(QPen(QColor(theme.SURFACE_ALT), 1.0))
            painter.setBrush(QBrush(QColor(theme.WINDOW_BG)))
            painter.drawPath(path)
            painter.setClipPath(path)

            # The title band + the fold marker on the right ("▾" expanded, "▸" folded).
            painter.setPen(QPen(QColor(theme.TEXT_PRIMARY)))
            painter.setFont(self._bold)
            fm = QFontMetrics(self._bold)
            title = self._labels.get("legend.title", _t("legend.title"))
            painter.drawText(QRectF(self.PADDING, 0.0, max(w - 2.0 * self.PADDING, 1.0),
                                    float(self.HEADER_H)),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                             fm.elidedText(title, Qt.TextElideMode.ElideRight,
                                           int(w) - 2 * self.PADDING - 14))
            self._paint_chevron(painter, w)
            if self._collapsed:
                return

            # The body rows.
            y = float(self.HEADER_H)
            for kind, key, color in self.rows():
                if kind == "section":
                    y += self.SECTION_GAP
                    painter.setFont(self._section_font)
                    painter.setPen(QPen(QColor(theme.TEXT_MUTED)))
                    painter.drawText(QRectF(self.PADDING, y,
                                            max(w - 2.0 * self.PADDING, 1.0), float(self.SECTION_H)),
                                     int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                                     self._labels.get(key, key))
                    y += self.SECTION_H
                    continue
                # v1.5rc2: the SAMPLE of the row (the declared line style or the
                # declared shape) + its label.
                self._paint_sample(painter, kind, key, color, y)
                painter.setFont(self._font)
                painter.setPen(QPen(QColor(theme.TEXT_PRIMARY)))
                text_x = self.PADDING + self.SAMPLE_W + self.SWATCH_GAP
                painter.drawText(
                    QRectF(text_x, y, max(w - text_x - self.PADDING, 1.0), float(self.ROW_H)),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    QFontMetrics(self._font).elidedText(
                        self._labels.get(key, key), Qt.TextElideMode.ElideRight,
                        int(max(w - text_x - self.PADDING, 1.0))))
                y += self.ROW_H
        finally:
            painter.end()

    def _paint_sample(self, painter, kind: str, key: str, color, y: float):
        """Draw the sample of one row (v1.5rc2, ROADMAP task 4) — never a copy of the map.

        A connection type draws its DECLARED stroke (the dash pattern, the width and
        the double rail — the casing uses the panel's own card colour, exactly as the
        arrow uses the canvas), a status draws its DECLARED shape in the status colour
        (`ui/status_shape.py`, the same module the card and the sidebar call). The
        v1.4.5 colour square survives as the fallback for an unknown row and for a
        layout without `ui/status_shape.py`.
        """
        sample = self.row_sample(kind, key, color)
        box = QRectF(self.PADDING, y, float(self.SAMPLE_W), float(self.ROW_H))
        if sample is None or (sample.get("kind") == "shape" and status_shape is None):
            # The v1.4.5 colour swatch (a rounded square).
            swatch = QPainterPath()
            swatch.addRoundedRect(
                QRectF(self.PADDING, y + (self.ROW_H - self.SWATCH) / 2.0,
                       float(self.SWATCH), float(self.SWATCH)), 2.0, 2.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(color)))
            painter.drawPath(swatch)
            return

        if sample["kind"] == "shape":
            size = float(self.SAMPLE_MARK)
            mark = QRectF(box.center().x() - size / 2.0, box.center().y() - size / 2.0,
                          size, size)
            status_shape.paint_shape(painter, mark, sample.get("status"), sample["color"])
            return

        style = sample["style"]
        width = min(max(float(getattr(style, "width", 2.2)), 1.0), 4.0)
        cy = box.center().y()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(sample["color"]), width)
        if getattr(style, "dash", ()):
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            pen.setDashPattern([float(v) for v in style.dash])
        painter.setPen(pen)
        painter.drawLine(QPointF(box.left(), cy), QPointF(box.right(), cy))
        if getattr(style, "double", False):
            # The same two-rail trick the arrow uses: a narrower stroke in the surface
            # colour over the middle of the wide one (here the surface is the CARD).
            painter.setPen(QPen(QColor(theme.WINDOW_BG),
                                max(width * theme.ARROW_CASING_RATIO, 0.8)))
            painter.drawLine(QPointF(box.left(), cy), QPointF(box.right(), cy))

    def _paint_chevron(self, painter, w: float):
        """The fold marker of the title band: down (expanded) or right (folded)."""
        cx, cy = w - self.PADDING - 4.0, self.HEADER_H / 2.0
        path = QPainterPath()
        if self._collapsed:
            path.moveTo(cx - 2.0, cy - 4.0)
            path.lineTo(cx + 2.5, cy)
            path.lineTo(cx - 2.0, cy + 4.0)
        else:
            path.moveTo(cx - 4.0, cy - 2.0)
            path.lineTo(cx, cy + 2.5)
            path.lineTo(cx + 4.0, cy - 2.0)
        painter.setPen(QPen(QColor(theme.TEXT_MUTED), 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
