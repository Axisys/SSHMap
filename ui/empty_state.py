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

v1.5rc3 (ROADMAP tasks 1 and 4) adds the two halves of "and then what?":

  * a SECOND button, **"Open the example map"** — the in-code demo project
    (`storage/example_project.py`), loaded through the ordinary project load path;
  * a SECOND hint line naming the **command palette** by its live hotkey
    (`palette_hotkey()` reads the action registry) and the `?` key of the cheat-sheet
    — the first screen stops being a dead end for a user who has no servers yet.

v1.5.6 (ROADMAP task 2) puts the **third door** between those two: "Open an existing
map" — a user who already has a project file must not go through the menus to find it.
The widget only EMITS (`open_map_requested`); the window owns the dialog and calls its
ORDINARY project-open path (`_open_project` → `_load_project_at`), the same one
File → Open and a dropped project use.

The pinned decisions (ROADMAP v1.4.5, task 2 — unchanged by the new pieces):

  * **it never blocks the canvas.** The hint card is `WA_TransparentForMouseEvents`
    (a click on it reaches the map: panning, the rubber band and the map context menu
    keep working behind the hint). Qt's attribute disables the delivery to the widget
    AND its children, so a button cannot live inside the card — the buttons are created
    as SIBLINGS children of the view and placed under the card by `place()`. They are
    the only pieces of the empty state that take the mouse;
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


def palette_hotkey() -> str:
    """The effective Ctrl+K sequence of the command palette (v1.5rc3, ROADMAP task 4).

    Read LIVE from the action registry, so the hint on the first screen names the key
    the user would really press (a rebound palette is named by its new key).

    A deliberately DISABLED palette hotkey ("" in `config.json`) falls back to the
    registry default: this text is the FIRST-RUN hint, and a first run has no saved
    customization at all. A user who later clears the key has already met the palette
    and does not need the sentence to be re-phrased for them.
    """
    try:
        from ui.hotkey_registry import configured_hotkeys, default_sequence
    except ImportError:
        try:
            from hotkey_registry import configured_hotkeys, default_sequence
        except ImportError:
            return "Ctrl+K"
    try:
        configured = str(configured_hotkeys().get("palette.open", "") or "").strip()
    except Exception:  # noqa: BLE001 — a broken config must not break the hint
        configured = ""
    return configured or default_sequence("palette.open") or "Ctrl+K"


class EmptyStateOverlay(QWidget):
    """The first-run hint card (a transparent child of `MapView`).

    Signals:
        add_server_requested — the "Add your first server" button was clicked (the
        window opens the AddServer dialog through its ordinary path);
        open_map_requested — v1.5.6: "Open an existing map" was clicked (the window
        runs its ORDINARY project-open path — the File → Open entry point);
        example_requested — v1.5rc3: "Open the example map" was clicked (the window
        loads the in-code demo project through the ORDINARY project load path).
    """

    add_server_requested = Signal()
    #: v1.5.6 (ROADMAP task 2): the third door — an existing project file on disk.
    open_map_requested = Signal()
    #: v1.5rc3 (ROADMAP task 1): the second way out of an empty map — the demo project.
    example_requested = Signal()

    ICON = 44                # the hint glyph
    PADDING_X = 20           # the card's horizontal inset
    PADDING_Y = 16           # the card's vertical inset
    GAP = 8                  # the gap between the icon, the title, the hints and the buttons
    BUTTON_H = 30            # the height of the interactive pieces
    BUTTON_MIN_W = 140       # below this a button label stops reading
    MIN_WIDTH = 300          # below this the sentences stop reading
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

        # The interactive pieces. They are SIBLINGS (children of the VIEW, not of this
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

        # v1.5.6 (ROADMAP task 2): "Open an existing map" — the door BETWEEN the two:
        # a user who already saved a project must not travel through File → Open to find
        # it, and the demo is not what they came for either. It shares the neutral look of
        # the example button (the accent fill belongs to the ONE primary action) and is
        # wired the way the other two are: the widget only emits, the window owns the dialog.
        self.btn_open_map = QPushButton(_t("empty.state.open_map"), self._view)
        self.btn_open_map.setObjectName("EmptyStateOpenButton")
        self.btn_open_map.setMinimumHeight(self.BUTTON_H)
        self.btn_open_map.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_map.clicked.connect(self.open_map_requested)
        self.btn_open_map.hide()

        # v1.5rc3 (ROADMAP task 1): "Open the example map" — the neutral secondary
        # action (the accent fill belongs to the ONE primary action above), and the
        # second entry point of the same project as Help → Open the example map.
        self.btn_example = QPushButton(_t("example.open"), self._view)
        self.btn_example.setObjectName("EmptyStateExampleButton")
        self.btn_example.setMinimumHeight(self.BUTTON_H)
        self.btn_example.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_example.clicked.connect(self.example_requested)
        self.btn_example.hide()

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

    def palette_text(self) -> str:
        """v1.5rc3 (ROADMAP task 4): the SECOND line — the palette and the cheat-sheet.

        The key is read from the action registry at call time (`palette_hotkey()`), so
        a rebound palette is named by its real sequence; the `?` half is the map's own
        key (see `MainWindow.keyPressEvent`), not a registry action.
        """
        return _t("empty.state.palette_hint", hotkey=palette_hotkey())

    def retranslate(self):
        """Re-read the strings (language switch)."""
        self.btn_add_first.setText(_t("empty.state.add_first"))
        self.btn_open_map.setText(_t("empty.state.open_map"))
        self.btn_example.setText(_t("example.open"))
        self.update()

    def buttons(self) -> tuple:
        """The three doors of the first screen, in reading order (v1.5.6).

        ONE declaration: `place()`, `set_state_visible()` and the raise/focus walks all
        read THIS tuple, so a fourth door would be added in one place. The order is the
        story the screen tells — add a server, open a saved map, look at the example.
        """
        return (self.btn_add_first, self.btn_open_map, self.btn_example)

    # ── Visibility ───────────────────────────────────────────────────────────

    def is_state_visible(self) -> bool:
        return bool(self._visible)

    def set_state_visible(self, visible: bool) -> None:
        """Show/hide the hint (the card AND its buttons — they are separate widgets).

        v1.5rc5 (N7): the buttons are RAISED above the card. They are siblings that sit
        inside the card's own rectangle, and the card paints an opaque fill — so a card
        raised last hid both actions completely (Qt's `isVisible()`/`visibleRegion()`
        cannot see it, because the card sets WA_NoSystemBackground rather than
        WA_OpaquePaintEvent). One place raises, in this order: card first, buttons last.
        """
        visible = bool(visible)
        self._visible = visible
        for widget in (self,) + self.buttons():
            try:
                widget.setVisible(visible)
            except RuntimeError:
                continue  # Qt teardown — the widget is already destroyed
        if visible:
            self.raise_()
            for button in self.buttons():
                try:
                    button.raise_()
                except RuntimeError:
                    continue  # Qt teardown

    # ── Geometry ─────────────────────────────────────────────────────────────

    def place(self, view_w: int, view_h: int) -> None:
        """Center the card (a bit above the middle) and put the THREE buttons under it.

        Called by the window on every view resize — the same split as the minimap
        and the legend: the window owns the placement, the widget owns its painting.
        The buttons share ONE row in the order of `buttons()`: the primary action first,
        then "open an existing map", then the example. They are squeezed into the card
        when the view is narrow (their labels elide — a QPushButton elides its own text).
        """
        title_fm = QFontMetrics(self._title_font)
        hint_fm = QFontMetrics(self._hint_font)
        lines = (self.title_text(), self.hint_text(), self.palette_text())
        max_text_w = max(fm.horizontalAdvance(line) for fm, line in
                         ((title_fm, lines[0]), (hint_fm, lines[1]), (hint_fm, lines[2])))
        buttons = self.buttons()
        widths = [max(btn.sizeHint().width(), self.BUTTON_MIN_W) for btn in buttons]
        gaps = self.GAP * (len(buttons) - 1)
        row_hint = sum(widths) + gaps
        # The row of THREE full labels is what a wide window shows, so the card is wide
        # enough for it (the sentences are measured too — a long hint still wins).
        width = max(max_text_w, row_hint, self.MIN_WIDTH) + 2 * self.PADDING_X
        # The card must stay INSIDE the view (the map can be as narrow as 240 px): the
        # sentences then elide rather than the card overflowing the canvas.
        width = min(width, max(int(view_w) - 16, 160))
        height = (self.PADDING_Y + self.ICON + self.GAP + title_fm.height() + 4
                  + hint_fm.height() + 2 + hint_fm.height() + self.GAP
                  + self.BUTTON_H + self.PADDING_Y)
        x = max(0, (int(view_w) - width) // 2)
        y = max(0, int(int(view_h) * 0.42) - height // 2)
        self.setGeometry(int(x), int(y), int(width), int(height))

        avail = max(int(width) - 2 * self.PADDING_X, 1)
        if row_hint > avail:          # narrow view — share what there is
            share = max((avail - gaps) // len(buttons), 1)
            widths = [min(w, share) for w in widths]
        row_w = sum(widths) + gaps
        btn_y = int(y + height - self.PADDING_Y - self.BUTTON_H)
        btn_x = int(x + (width - row_w) // 2)
        for button, button_w in zip(buttons, widths):
            button.setGeometry(btn_x, btn_y, int(button_w), self.BUTTON_H)
            btn_x += int(button_w) + self.GAP

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
            text_w = max(w - 2.0 * self.PADDING_X, 1.0)
            for line in (self.hint_text(), self.palette_text()):
                painter.drawText(QRectF(self.PADDING_X, float(y), text_w, float(hint_fm.height())),
                                 int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                                 hint_fm.elidedText(line, Qt.TextElideMode.ElideRight,
                                                    int(text_w)))
                y += hint_fm.height() + 2
        finally:
            painter.end()
