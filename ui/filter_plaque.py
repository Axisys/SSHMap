# -*- coding: utf-8 -*-
"""v1.5.4 (ROADMAP task 3): the ACTIVE-FILTER plaque — a floating panel that NAMES the filters.

The problem this panel closes is the silent one: the map search (Ctrl+F), the tag filter,
the status filter of the status bar and the "problems only" lens all DIM the map, and a
dimmed card looks exactly like a card that is not there any more. A forgotten filter used
to be indistinguishable from deleted servers — the same class the 1.5 line keeps treating
("the interface must say its own state").

The plaque is a WIDGET over the scene (`MapView`'s child), never a scene item — the
v1.4.2/v1.4.5 rule — so it stays out of the exports, out of a rubber-band selection, out
of `itemsBoundingRect()` and out of "fit to content". It joins the v1.5rc4 floating-panel
priority resolver (`MainWindow._overlay_panel_rects()`), which is what keeps the map
collapse diamond from landing under it.

It owns NO filter logic, exactly like the search bar and the legend: the window reports
the ACTIVE filters (`set_state`) and receives one `clear_requested(kind)` per row — the
window decides what clearing means (it already owns every one of those states). The
plaque appears only while at least one filter is active; every row carries ONE ×.

Pinned decisions of the release:

  * **transient by construction** — the widget holds live UI state only and writes no
    `config.json` key: a restart must not hide servers for no visible reason (the v1.4.5
    status-filter rule);
  * **one × per row, and only its own filter** — the × clears the search query, the tag
    pick, the status filter or the lens, never "all filters at once" (a user who wants
    everything gone clicks the four ×, or the search panel's own close);
  * **the words are i18n, the values are data** — the query and the tag are printed as
    the user typed them, the captions come from `filter.plaque.*` and the status word
    from the EXISTING `legend.status.*` (no fourth spelling of online/warn/offline).
"""

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

try:  # v1.2.5: the central theme (palette/radii/fonts — ui/theme.py)
    from . import theme
except ImportError:
    try:
        from ui import theme
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        import theme


def _t(key: str, **kw) -> str:
    """Safe i18n hook (the legend / map_search_bar pattern)."""
    try:
        from i18n import t as _translate
        return _translate(key, **kw) if kw else _translate(key)
    except Exception:  # noqa: BLE001 — a missing i18n must not break a paint
        return key


class FilterPlaque(QWidget):
    """The active-filter plaque: one caption + one × per active filter (v1.5.4).

    Signals:
        clear_requested(str) — the × of the row with this KIND was clicked
        (``"search"`` / ``"tag"`` / ``"status"`` / ``"problems"``).
    """

    clear_requested = Signal(str)

    #: The rows the plaque can show, in the order they are rendered. The ORDER is a
    #: declaration: the transient per-session filter (the search) stands above the two
    #: persisted-in-memory picks, and the lens of the release closes the list.
    KINDS = ("search", "tag", "status", "problems")

    WIDTH = 236              # the panel's fixed width
    HEADER_H = 20            # the title band
    ROW_H = 18               # one filter row
    PADDING = 6              # the inner inset of the card
    CLEAR_W = 16             # the × hit zone at the right end of a row
    TITLE_GAP = 4            # the room between the caption and the ×
    RADIUS = float(theme.RADIUS_SEARCH_BAR)   # one style with the legend / the search bar

    def __init__(self, view, parent=None):
        super().__init__(parent if parent is not None else view)
        self._view = view
        #: the LIVE state the window pushes — the widget translates it, it never
        #: interprets it (a query is a string, a tag is a string, the rest are flags)
        self._state = {"search": "", "tag": "", "status": "", "problems": False}
        self._rows_cache = []
        #: the panel's own caption, resolved ONCE per language (the paint path never calls
        #: i18n — the `LegendWidget` rule)
        self._title = _t("filter.plaque.title")

        self.setObjectName("FilterPlaque")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedWidth(self.WIDTH)
        self.setToolTip(_t("filter.plaque.tooltip"))
        self._font = self._make_font(-1.0)
        self._bold = self._make_font(-1.0, bold=True)
        self._apply_height()
        self.hide()

    # ── State (pushed by the window) ────────────────────────────────────────────

    def set_state(self, search: str = "", tag: str = "", status: str = "",
                  problems: bool = False) -> bool:
        """Report the ACTIVE filters; returns True when the row set really changed.

        The comparison is over the RAW state, not over the painted text: a language
        switch re-texts the rows but is not a state change (`retranslate()` is what
        handles that), so a caller may push the same state on every repaint for free.
        """
        new = {"search": str(search or ""), "tag": str(tag or ""),
               "status": str(status or ""), "problems": bool(problems)}
        if new == self._state:
            return False
        self._state = new
        self._rebuild_rows()
        self._apply_height()
        self.update()
        return True

    def active_kinds(self) -> list:
        """The kinds that are active right now (the order of `KINDS`)."""
        return [kind for kind, _text in self._rows_cache]

    def is_empty(self) -> bool:
        """True while no filter is active — the plaque hides itself then."""
        return not self._rows_cache

    def rows(self) -> list:
        """The painted rows as ``[(kind, text), …]`` — the translated captions."""
        return list(self._rows_cache)

    # ── Text ────────────────────────────────────────────────────────────────────

    def _make_font(self, delta: float, bold: bool = False) -> QFont:
        """The panel's font: the UI font one point smaller, optionally bold."""
        font = QFont(self.font())
        try:
            font.setPointSizeF(max(font.pointSizeF() + delta, 7.0))
        except (TypeError, ValueError):  # pragma: no cover - a font without a point size
            pass
        font.setBold(bool(bold))
        return font

    def _row_text(self, kind: str) -> str:
        """The caption of one row, built from the LIVE state (never cached)."""
        if kind == "search":
            return _t("filter.plaque.search", query=self._state.get("search", ""))
        if kind == "tag":
            return _t("filter.plaque.tag", tag=self._state.get("tag", ""))
        if kind == "status":
            status = self._state.get("status", "")
            return _t("filter.plaque.status", status=_t(f"legend.status.{status}"))
        if kind == "problems":
            return _t("filter.plaque.problems")
        return ""

    def _rebuild_rows(self):
        """Resolve the rows from the current state (i18n is read HERE, never in paint)."""
        self._rows_cache = [(kind, self._row_text(kind))
                            for kind in self.KINDS if self._is_active(kind)]

    def _is_active(self, kind: str) -> bool:
        if kind == "problems":
            return bool(self._state.get("problems"))
        return bool(self._state.get(kind))

    def retranslate(self):
        """Re-read the panel's strings (language switch) — values stay untouched."""
        try:
            self.setToolTip(_t("filter.plaque.tooltip"))
        except RuntimeError:
            return  # Qt teardown — the widget is already destroyed
        self._title = _t("filter.plaque.title")
        self._rebuild_rows()
        self.update()

    # ── Geometry ────────────────────────────────────────────────────────────────

    def body_height(self) -> int:
        """The height of the card (the title band + one row per active filter)."""
        return self.HEADER_H + len(self._rows_cache) * self.ROW_H + self.PADDING

    def _apply_height(self):
        self.setFixedHeight(self.body_height())

    def header_rect(self) -> QRectF:
        """The title band (the panel's own caption — not clickable)."""
        return QRectF(0.0, 0.0, float(self.width()), float(self.HEADER_H))

    def row_rect(self, index: int) -> QRectF:
        """The rect of row ``index`` (0 = the first active filter)."""
        return QRectF(0.0, float(self.HEADER_H + index * self.ROW_H),
                      float(self.width()), float(self.ROW_H))

    def clear_rect(self, kind: str) -> QRectF:
        """The × hit zone of one row (an empty rect — the kind is not shown).

        The geometry lives in ONE place, so the paint and the mouse handler cannot
        disagree about where the affordance is (the topical test reads it too).
        """
        for index, (row_kind, _text) in enumerate(self._rows_cache):
            if row_kind != kind:
                continue
            rect = self.row_rect(index)
            return QRectF(rect.right() - self.PADDING - self.CLEAR_W,
                          rect.top(), float(self.CLEAR_W), float(self.ROW_H))
        return QRectF()

    def clear_rects(self) -> dict:
        """``{kind: QRectF}`` of every visible × (the topical test's seam)."""
        return {kind: self.clear_rect(kind) for kind, _text in self._rows_cache}

    # ── Interaction ─────────────────────────────────────────────────────────────

    @staticmethod
    def _event_pos(event):
        """The event position as a QPointF (the legend's `pos()`/`position()` pattern)."""
        position = getattr(event, "position", None)
        if callable(position):
            try:
                return position()
            except Exception:  # noqa: BLE001 — an older binding without position()
                pass
        return event.pos()

    def mousePressEvent(self, event):
        """Only the × of a row reacts — a click on the caption does nothing."""
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        point = self._event_pos(event)
        for kind, _text in list(self._rows_cache):
            rect = self.clear_rect(kind)
            if rect.width() > 0 and rect.contains(point):
                try:
                    self.clear_requested.emit(kind)
                except RuntimeError:
                    pass  # Qt teardown — the receiver is gone
                event.accept()
                return
        super().mousePressEvent(event)

    # ── Rendering ───────────────────────────────────────────────────────────────

    def refresh_theme(self):
        """Re-read the theme (every colour is resolved in `paintEvent`)."""
        self.update()

    def paintEvent(self, event):
        w, h = float(self.width()), float(self.height())
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            path = QPainterPath()
            path.addRoundedRect(QRectF(1.0, 1.0, max(w - 2.0, 1.0), max(h - 2.0, 1.0)),
                                self.RADIUS, self.RADIUS)
            painter.setPen(QPen(QColor(theme.SURFACE_ALT), 1.0))
            painter.setBrush(QBrush(QColor(theme.WINDOW_BG)))
            painter.drawPath(path)
            painter.setClipPath(path)

            fm_title = QFontMetrics(self._bold)
            painter.setFont(self._bold)
            painter.setPen(QPen(QColor(theme.TEXT_PRIMARY)))
            painter.drawText(
                QRectF(self.PADDING, 0.0, max(w - 2.0 * self.PADDING, 1.0), float(self.HEADER_H)),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                fm_title.elidedText(self._title, Qt.TextElideMode.ElideRight,
                                    int(max(w - 2.0 * self.PADDING, 1.0))))

            fm = QFontMetrics(self._font)
            for index, (kind, text) in enumerate(self._rows_cache):
                rect = self.row_rect(index)
                clear = self.clear_rect(kind)
                room = max(int(clear.left() - rect.left() - self.PADDING - self.TITLE_GAP), 1)
                painter.setFont(self._font)
                painter.setPen(QPen(QColor(theme.TEXT_PRIMARY)))
                painter.drawText(
                    QRectF(rect.left() + self.PADDING, rect.top(), float(room), rect.height()),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    fm.elidedText(text, Qt.TextElideMode.ElideRight, room))
                self._paint_clear(painter, clear)
        finally:
            painter.end()

    def _paint_clear(self, painter, rect: QRectF):
        """The × of a row — the one affordance that clears exactly that filter."""
        cx, cy = rect.center().x(), rect.center().y()
        half = 3.5
        painter.setPen(QPen(QColor(theme.TEXT_MUTED), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(int(cx - half), int(cy - half), int(cx + half), int(cy + half))
        painter.drawLine(int(cx - half), int(cy + half), int(cx + half), int(cy - half))
