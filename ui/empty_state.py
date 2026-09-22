# -*- coding: utf-8 -*-
"""v1.4.5 (ROADMAP task 2): the first-run empty state of the map.

A new user opening the application sees an empty canvas and no hint about what to do
with it. This module is that hint: a floating card over the map with the vector
"server" icon, a title, the ONE button that starts the work (`Add your first server`
→ the AddServer dialog) and a line that points at the two import paths that really
ship — the TXT import and the `~/.ssh/config` import. The two labels in that line are
not copies: they are the translated File-menu strings themselves
(`file.import_servers` / `file.import_ssh_config`), so a re-worded menu item can never
leave a stale hint behind.

The pinned decisions (ROADMAP v1.4.5, task 2):

  * **it never blocks the canvas.** The hint card is `WA_TransparentForMouseEvents`
    (a click on it reaches the map: panning, the rubber band and the map context menu
    keep working behind the hint). Qt's attribute disables the delivery to the widget
    AND its children, so the button cannot live inside the card — it is created as a
    SIBLING child of the view and placed under the card by `place()`. It is the only
    piece of the empty state that takes the mouse;
  * **it is bound to the SERVER COUNT of the scene** (0 servers → visible): the window
    shows/hides it from `_sync_empty_state()`, so it appears again when a batch delete
    or a fresh project empties the map and disappears with the first server;
  * **it is not a scene item** — like the minimap, the search bar and the legend it is
    a child of `MapView`, so it stays out of every export and out of "fit to content".

The widget holds no logic beyond its own layout; the WINDOW owns the dialog
(`add_server_requested`) and the visibility (`set_state_visible`).
"""

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton, QWidget

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from . import theme
except ImportError:
    try:
        from ui import theme
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        import theme

try:  # v1.4.3 (ROADMAP task 4): the ONE QSS registry
    from . import theme_qss
except ImportError:
    try:
        from ui import theme_qss
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        theme_qss = None

try:  # UI polish: the vector icon of the hint (the same one the toolbar uses)
    from .icons import get_icon
except ImportError:
    try:
        from icons import get_icon
    except ImportError:  # flat layout without ui/icons — the hint stays text-only
        def get_icon(name):  # noqa: N802 — stub with the same signature
            return None


def _t(key: str, **kw) -> str:
    """Safe i18n hook (the map_search_bar / minimap pattern); kwargs are formatted."""
    try:
        from i18n import t as _translate
        return _translate(key, **kw)
    except Exception:
        return key


class EmptyStateOverlay(QWidget):
    """The first-run hint card (a transparent child of `MapView`).

    Signals:
        add_server_requested — the "Add your first server" button was clicked (the
        window opens the AddServer dialog through its ordinary path).
    """

    add_server_requested = Signal()

    ICON = 44                # the hint glyph
    PADDING_X = 20           # the card's horizontal inset
    PADDING_Y = 16           # the card's vertical inset
    GAP = 8                  # the gap between the icon, the title, the hint and the button
    BUTTON_H = 30            # the height of the ONE interactive piece
    MIN_WIDTH = 260          # below this the sentence stops reading
    RADIUS = float(theme.RADIUS_SEARCH_BAR)   # one style with the search bar / minimap / legend

    def __init__(self, view, parent=None):
        super().__init__(parent if parent is not None else view)
        self._view = view
        self.setObjectName("EmptyStateOverlay")
        # The hint must never eat a click meant for the map.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self._title_font = self._make_font(+1.0, bold=True)
        self._hint_font = self._make_font(-1.0)

        # The ONE interactive piece. It is a SIBLING (a child of the VIEW, not of this
        # card): WA_TransparentForMouseEvents above covers the children of the widget
        # it is set on, so a button inside the card would never receive a click.
        self.btn_add_first = QPushButton(_t("empty.state.add_first"), self._view)
        self.btn_add_first.setObjectName("EmptyStateButton")
        self.btn_add_first.setMinimumHeight(self.BUTTON_H)
        self.btn_add_first.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_first.clicked.connect(self.add_server_requested)
        if theme_qss is not None:
            theme_qss.refresh(self.btn_add_first, "empty_state.button")
        self.btn_add_first.hide()

        self._visible = False
        self.hide()

    # ── Text ─────────────────────────────────────────────────────────────────

    def _make_font(self, delta: float, bold: bool = False) -> QFont:
        """The UI font one point up/down (the hint is a headline, its line a footnote)."""
        font = QFont(self.font())
        try:
            font.setPointSizeF(max(font.pointSizeF() + delta, 7.0))
        except (TypeError, ValueError):  # pragma: no cover - a font without a point size
            pass
        font.setBold(bool(bold))
        return font

    def title_text(self) -> str:
        return _t("empty.state.title")

    def hint_text(self) -> str:
        """The import line — built from the REAL File-menu labels (never a copy)."""
        return _t("empty.state.import_hint",
                  import_txt=_t("file.import_servers"),
                  import_ssh=_t("file.import_ssh_config"))

    def retranslate(self):
        """Re-read the strings (language switch)."""
        self.btn_add_first.setText(_t("empty.state.add_first"))
        self.update()

    # ── Visibility ───────────────────────────────────────────────────────────

    def is_state_visible(self) -> bool:
        return bool(self._visible)

    def set_state_visible(self, visible: bool) -> None:
        """Show/hide the hint (the card AND its button — they are two widgets)."""
        visible = bool(visible)
        self._visible = visible
        for widget in (self, self.btn_add_first):
            try:
                widget.setVisible(visible)
            except RuntimeError:
                continue  # Qt teardown — the widget is already destroyed
        if visible:
            self.raise_()

    # ── Geometry ─────────────────────────────────────────────────────────────

    def place(self, view_w: int, view_h: int) -> None:
        """Center the card (a bit above the middle) and put the button under it.

        Called by the window on every view resize — the same split as the minimap
        and the legend: the window owns the placement, the widget owns its painting.
        """
        title_fm = QFontMetrics(self._title_font)
        hint_fm = QFontMetrics(self._hint_font)
        title = title_fm.elidedText(self.title_text(), Qt.TextElideMode.ElideRight,
                                    max(int(view_w) - 2 * self.PADDING_X - 24, 80))
        hint = hint_fm.elidedText(self.hint_text(), Qt.TextElideMode.ElideRight,
                                  max(int(view_w) - 2 * self.PADDING_X - 24, 80))
        width = max(title_fm.horizontalAdvance(title), hint_fm.horizontalAdvance(hint),
                    self.btn_add_first.sizeHint().width(), self.MIN_WIDTH) + 2 * self.PADDING_X
        # The card must stay INSIDE the view (the map can be as narrow as 240 px): the
        # sentences then elide rather than the card overflowing the canvas.
        width = min(width, max(int(view_w) - 16, 160))
        height = (self.PADDING_Y + self.ICON + self.GAP + title_fm.height() + 4
                  + hint_fm.height() + self.GAP + self.BUTTON_H + self.PADDING_Y)
        x = max(0, (int(view_w) - width) // 2)
        y = max(0, int(int(view_h) * 0.42) - height // 2)
        self.setGeometry(int(x), int(y), int(width), int(height))

        btn_w = max(self.btn_add_first.sizeHint().width(), 150)
        btn_w = min(btn_w, width - 2 * self.PADDING_X)
        self.btn_add_first.setGeometry(int(x + (width - btn_w) // 2),
                                       int(y + height - self.PADDING_Y - self.BUTTON_H),
                                       int(btn_w), int(self.BUTTON_H))

    # ── Rendering ────────────────────────────────────────────────────────────

    def refresh_theme(self):
        """Re-read the theme (the card paints from the live values) + the button's QSS."""
        if theme_qss is not None:
            theme_qss.refresh(self.btn_add_first, "empty_state.button")
        self.update()

    def paintEvent(self, event):
        w, h = float(self.width()), float(self.height())
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            # The card: WINDOW_BG + a SURFACE_ALT frame (the floating-panel family).
            path = QPainterPath()
            path.addRoundedRect(QRectF(1.0, 1.0, max(w - 2.0, 1.0), max(h - 2.0, 1.0)),
                                self.RADIUS, self.RADIUS)
            painter.setPen(QPen(QColor(theme.SURFACE_ALT), 1.0))
            painter.setBrush(QBrush(QColor(theme.WINDOW_BG)))
            painter.drawPath(path)
            painter.setClipPath(path)

            # The glyph (the same vector "server" icon the sidebar button carries).
            icon = get_icon("add_server")
            icon_rect = QRectF((w - self.ICON) / 2.0, float(self.PADDING_Y),
                               float(self.ICON), float(self.ICON))
            if icon is not None:
                try:
                    if not icon.isNull():
                        icon.paint(painter, icon_rect.toRect())
                except (RuntimeError, AttributeError):
                    pass  # a dead icon must not break the hint

            y = self.PADDING_Y + self.ICON + self.GAP
            title_fm = QFontMetrics(self._title_font)
            painter.setFont(self._title_font)
            painter.setPen(QPen(QColor(theme.TEXT_PRIMARY)))
            painter.drawText(QRectF(self.PADDING_X, float(y),
                                    max(w - 2.0 * self.PADDING_X, 1.0), float(title_fm.height())),
                             int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                             title_fm.elidedText(self.title_text(), Qt.TextElideMode.ElideRight,
                                                 int(max(w - 2.0 * self.PADDING_X, 1.0))))
            y += title_fm.height() + 4
            hint_fm = QFontMetrics(self._hint_font)
            painter.setFont(self._hint_font)
            painter.setPen(QPen(QColor(theme.TEXT_MUTED)))
            painter.drawText(QRectF(self.PADDING_X, float(y),
                                    max(w - 2.0 * self.PADDING_X, 1.0), float(hint_fm.height())),
                             int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                             hint_fm.elidedText(self.hint_text(), Qt.TextElideMode.ElideRight,
                                                int(max(w - 2.0 * self.PADDING_X, 1.0))))
        finally:
            painter.end()
